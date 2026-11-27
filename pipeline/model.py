"""Real ML layer (scikit-learn, installed only in the pipeline job). PAPER ONLY. No real money, no orders.

Features are rebuilt from the stored raw data on an hourly grid (price returns, volatility, news, social, whale
activity, smart-money flow, fear & greed). Labels are the forward return at 15m / 1h / 4h / 24h, known only after
that time has passed. Validation is walk-forward with an embargo of one horizon, so the numbers in the model card are
out-of-sample. Until there is enough data the card says 'not enough data yet' and no model is trained.
The predictions log is scored later against real outcomes: that is the true out-of-sample record.
"""
import os, json, time, math, pickle, random, datetime, bisect

HORIZONS = {"15m": 900, "1h": 3600, "4h": 14400, "24h": 86400}
GRID = 3600
MIN_TRAIN, MIN_TEST = 300, 100   # samples before we train / before we report metrics
ENTER = 0.60                     # paper-trade only when P(up) >= .60 (long) or <= .40 (short)
FEATURES = ["r15m", "r1h", "r4h", "r24h", "vol24h", "er24h", "btc_r1h", "news_n4h", "news_sent4h", "news_urg4h",
            "soc_n4h", "soc_sent4h", "soc_eng4h", "whale_usd4h", "whale_n4h", "sm_net", "sm_gross", "fear_greed", "funding"]
PRED_DDL = ("CREATE TABLE IF NOT EXISTS model_predictions(ts REAL, symbol TEXT, horizon TEXT, p_up REAL, price REAL, "
            "model TEXT, mode TEXT, fwd_ret_pct REAL, pnl_pct REAL, PRIMARY KEY(ts, symbol, horizon))")
FEE = None


def _costs():
    from confluence import config
    return 2 * (config.FEE_PCT + config.SLIPPAGE_PCT)   # round trip, percent


class Series:
    def __init__(self, rows):
        self.t = [r[0] for r in rows]; self.v = [r[1] for r in rows]

    def at(self, ts, max_gap=900):
        i = bisect.bisect_right(self.t, ts) - 1
        return self.v[i] if i >= 0 and ts - self.t[i] <= max_gap else None

    def after(self, ts, max_gap=900):
        i = bisect.bisect_left(self.t, ts)
        return self.v[i] if i < len(self.t) and self.t[i] - ts <= max_gap else None


def _window(rows, t, secs):
    """rows sorted by ts: items with t-secs < ts <= t"""
    ts = [r[0] for r in rows]
    return rows[bisect.bisect_right(ts, t - secs):bisect.bisect_right(ts, t)]


def load_data(con):
    d = {"px": {}, "news": {}, "soc": {}, "wh": {}, "sm": {}, "fg": [], "fund": {}}
    for r in con.execute("SELECT symbol, ts, close FROM prices ORDER BY symbol, ts"):
        d["px"].setdefault(r[0], []).append((r[1], r[2]))
    d["px"] = {k: Series(v) for k, v in d["px"].items()}
    for r in con.execute("SELECT symbol, ts, sentiment, urgency, credibility FROM news ORDER BY ts"):
        d["news"].setdefault(r[0], []).append((r[1], r[2] or 0, r[3] or 0, r[4] or 0.5))
    for r in con.execute("SELECT symbol, ts, sentiment, engagement, is_bot FROM social ORDER BY ts"):
        if not r[4]:
            d["soc"].setdefault(r[0], []).append((r[1], r[2] or 0, r[3] or 0))
    for r in con.execute("SELECT symbol, ts, usd FROM whale_tx ORDER BY ts"):
        d["wh"].setdefault(r[0], []).append((r[1], r[2] or 0))
    try:
        for r in con.execute("SELECT symbol, ts, long_usd, short_usd FROM smart_flow ORDER BY ts"):
            d["sm"].setdefault(r[0], []).append((r[1], r[2], r[3]))
        d["fg"] = [(r[0], r[1]) for r in con.execute("SELECT ts, value FROM market_ctx WHERE key='fear_greed' ORDER BY ts")]
    except Exception:
        pass
    for r in con.execute("SELECT symbol, ts, funding_rate FROM derivs_snap ORDER BY ts"):
        d["fund"].setdefault(r[0], []).append((r[1], r[2] or 0))
    return d


def _last(rows, t, max_age=7200):
    ts = [r[0] for r in rows]
    i = bisect.bisect_right(ts, t) - 1
    return rows[i] if i >= 0 and t - rows[i][0] <= max_age else None


def features(d, sym, t):
    px = d["px"].get(sym)
    if not px:
        return None
    p0 = px.at(t)
    if p0 is None:
        return None
    f = {}
    for name, secs in (("r15m", 900), ("r1h", 3600), ("r4h", 14400), ("r24h", 86400)):
        p = px.at(t - secs)
        if p is None:
            return None
        f[name] = (p0 / p - 1) * 100
    pts = [px.at(t - 3600 * k) for k in range(25)]
    if any(x is None for x in pts):
        return None
    rets = [pts[i] / pts[i + 1] - 1 for i in range(24)]
    f["vol24h"] = (sum(x * x for x in rets) / 24) ** 0.5 * 100
    path = sum(abs(x) for x in rets) or 1e-9
    f["er24h"] = abs(pts[0] / pts[24] - 1) / path
    b = d["px"].get("BTC"); bp = b.at(t) if b else None; bq = b.at(t - 3600) if b else None
    f["btc_r1h"] = (bp / bq - 1) * 100 if bp and bq else 0.0
    nw = _window(d["news"].get(sym, []), t, 14400)
    f["news_n4h"] = len(nw)
    f["news_sent4h"] = sum(x[1] * x[3] for x in nw) / len(nw) if nw else 0.0
    f["news_urg4h"] = max([x[2] for x in nw], default=0.0)
    sc = _window(d["soc"].get(sym, []), t, 14400)
    f["soc_n4h"] = len(sc)
    f["soc_sent4h"] = sum(x[1] for x in sc) / len(sc) if sc else 0.0
    f["soc_eng4h"] = math.log1p(sum(x[2] for x in sc))
    wh = _window(d["wh"].get(sym, []), t, 14400)
    f["whale_usd4h"] = math.log1p(sum(x[1] for x in wh)); f["whale_n4h"] = len(wh)
    sm = _last(d["sm"].get(sym, []), t)
    tot = (sm[1] + sm[2]) if sm else 0
    f["sm_net"] = (sm[1] - sm[2]) / tot if tot else 0.0
    f["sm_gross"] = math.log1p(tot)
    fg = _last(d["fg"], t, 172800)
    f["fear_greed"] = (fg[1] if fg else 50.0) / 100
    fu = _last(d["fund"].get(sym, []), t, 14400)
    f["funding"] = (fu[1] if fu else 0.0) * 100
    return f


def build_dataset(d, now, step=GRID):
    """rows: (t, sym, feature vector, {horizon: fwd return pct or None}). Newest unlabeled rows are kept for inference."""
    syms = [s for s in d["px"] if s != "USD"]
    starts = [d["px"][s].t[0] for s in syms if d["px"][s].t]
    if not starts:
        return []
    t0 = math.ceil((min(starts) + 86400) / step) * step
    out = []; t = t0
    while t <= now:
        for s in syms:
            f = features(d, s, t)
            if f is None:
                continue
            px = d["px"][s]; p0 = px.at(t)
            lab = {}
            for h, secs in HORIZONS.items():
                p1 = px.after(t + secs) if t + secs <= now else None
                lab[h] = (p1 / p0 - 1) * 100 if p1 else None
            out.append((t, s, [f[k] for k in FEATURES], lab))
        t += step
    return out


def _auc(y, p):
    pos = [(pp, yy) for pp, yy in zip(p, y)]
    n1 = sum(y); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return None
    order = sorted(range(len(p)), key=lambda i: p[i]); ranks = [0.0] * len(p); i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and p[order[j + 1]] == p[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return (sum(ranks[i] for i in range(len(y)) if y[i]) - n1 * (n1 + 1) / 2) / (n1 * n0)


def _models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {"logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500)),
            "hgb": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=80, learning_rate=0.05, l2_regularization=1.0,
                                                          min_samples_leaf=40, random_state=7)}


def _paper(p, ret, cost):
    pnl = []
    for pp, r in zip(p, ret):
        if pp >= ENTER:
            pnl.append(r - cost)
        elif pp <= 1 - ENTER:
            pnl.append(-r - cost)
    return pnl


def _boot(x, n=1000, seed=3):
    if len(x) < 20:
        return None
    rnd = random.Random(seed); m = len(x)
    means = sorted(sum(x[rnd.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return [round(means[int(n * .025)], 4), round(means[int(n * .975)], 4)]


def walk_forward(rows, h, name, mk, cost):
    """Expanding window. Train on all rows before the cut, skip one horizon (embargo), test on the next block."""
    import numpy as np
    lab = [r for r in rows if r[3][h] is not None]
    lab.sort(key=lambda r: r[0])
    if len(lab) < MIN_TRAIN + MIN_TEST:
        return None
    ts = [r[0] for r in lab]
    span = ts[-1] - ts[0]; blocks = 4
    cut0 = ts[0] + span * 0.5
    ys, ps, rets = [], [], []
    for b in range(blocks):
        a = cut0 + span * 0.5 * b / blocks; z = cut0 + span * 0.5 * (b + 1) / blocks
        tr = [r for r in lab if r[0] <= a - HORIZONS[h]]
        te = [r for r in lab if a <= r[0] < z or (b == blocks - 1 and r[0] >= a)]
        if len(tr) < MIN_TRAIN or not te:
            continue
        y = [1 if r[3][h] > 0 else 0 for r in tr]
        if len(set(y)) < 2:
            continue
        m = mk(); m.fit(np.array([r[2] for r in tr]), y)
        pp = m.predict_proba(np.array([r[2] for r in te]))[:, 1]
        ps += list(pp); ys += [1 if r[3][h] > 0 else 0 for r in te]; rets += [r[3][h] for r in te]
    if len(ys) < MIN_TEST:
        return None
    eps = 1e-6; n = len(ys)
    base = max(sum(ys), n - sum(ys)) / n
    acc = sum(1 for p, y in zip(ps, ys) if (p >= .5) == bool(y)) / n
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    ll = -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in zip(ps, ys)) / n
    pnl = _paper(ps, rets, cost)
    return {"model": name, "n_test": n, "auc": round(_auc(ys, ps) or 0.5, 4), "accuracy": round(acc, 4),
            "base_rate_acc": round(base, 4), "brier": round(brier, 4), "brier_naive": round(
                sum((sum(ys) / n - y) ** 2 for y in ys) / n, 4), "logloss": round(ll, 4),
            "paper_trades": len(pnl), "paper_mean_net_pct": round(sum(pnl) / len(pnl), 4) if pnl else None,
            "paper_total_net_pct": round(sum(pnl), 2) if pnl else 0.0, "paper_ci95_mean": _boot(pnl)}


def run(con, data_dir, now=None):
    """Train, validate, log predictions, score old predictions. Returns the model card (also written to data_dir)."""
    now = now or time.time()
    con.execute(PRED_DDL)
    card = {"generated": datetime.datetime.utcfromtimestamp(now).isoformat(timespec="seconds") + "Z",
            "paper_only": True, "real_money": False, "min_train": MIN_TRAIN, "min_test": MIN_TEST,
            "costs_round_trip_pct": _costs(), "entry_threshold": ENTER, "features": FEATURES, "horizons": {}}
    try:
        import numpy as np
        mods = _models()
    except Exception as e:
        card["status"] = "sklearn unavailable: %s" % e
        _write(card, data_dir); return card
    d = load_data(con)
    rows = build_dataset(d, now)
    card["samples_total"] = len(rows)
    card["span_days"] = round((rows[-1][0] - rows[0][0]) / 86400, 1) if rows else 0
    cost = _costs(); stamp = datetime.datetime.utcfromtimestamp(now).strftime("%Y%m%dT%H%M%SZ")
    latest_t = max((r[0] for r in rows), default=None)
    infer = [r for r in rows if r[0] == latest_t] if latest_t and now - latest_t < 2 * GRID + 600 else []
    # inference needs current features at 'now' not the hourly grid: recompute for newest price
    infer = []
    for s in d["px"]:
        f = features(d, s, now)
        if f:
            infer.append((now, s, [f[k] for k in FEATURES]))
    trained = {}
    for h in HORIZONS:
        n_lab = sum(1 for r in rows if r[3][h] is not None)
        hc = {"labeled_samples": n_lab, "status": "not enough data yet"}
        if n_lab >= MIN_TRAIN + MIN_TEST:
            res = {}
            for name, mk in mods.items():
                try:
                    res[name] = walk_forward(rows, h, name, mk, cost)
                except Exception as e:
                    res[name] = {"error": str(e)}
            res = {k: v for k, v in res.items() if v and "error" not in v}
            if res:
                best = max(res.values(), key=lambda m: m["auc"])
                hc.update({"walk_forward": res, "chosen": best["model"]})
                lo = (best["paper_ci95_mean"] or [None])[0]
                validated = (best["auc"] > 0.53 and best["n_test"] >= 500 and best["paper_trades"] >= 100
                             and lo is not None and lo > 0)
                hc["status"] = "validated (paper candidate)" if validated else "trained, NOT validated (no proven edge)"
                lab = [r for r in rows if r[3][h] is not None]
                m = mods[best["model"]](); m.fit(np.array([r[2] for r in lab]), [1 if r[3][h] > 0 else 0 for r in lab])
                trained[h] = (m, best["model"], "validated" if validated else "shadow")
        card["horizons"][h] = hc
    card["status"] = ("no horizon has enough labeled data yet" if not trained else
                      "%d/4 horizons trained; see per-horizon status" % len(trained))
    # log predictions (true out-of-sample from here on)
    for h, (m, name, mode) in trained.items():
        if not infer:
            break
        pp = m.predict_proba(np.array([r[2] for r in infer]))[:, 1]
        for r, p in zip(infer, pp):
            price = d["px"][r[1]].at(now)
            con.execute("INSERT OR IGNORE INTO model_predictions(ts,symbol,horizon,p_up,price,model,mode) VALUES(?,?,?,?,?,?,?)",
                        (now, r[1], h, float(p), price, name + "-" + stamp, mode))
    # score old predictions against real later prices
    for ts, sym, h, p, price in con.execute("SELECT ts,symbol,horizon,p_up,price FROM model_predictions WHERE fwd_ret_pct IS NULL").fetchall():
        px = d["px"].get(sym)
        if not px or ts + HORIZONS[h] > now or not price:
            continue
        p1 = px.after(ts + HORIZONS[h], max_gap=1800)
        if p1 is None:
            continue
        ret = (p1 / price - 1) * 100
        pnl = (ret - cost) if p >= ENTER else (-ret - cost) if p <= 1 - ENTER else None
        con.execute("UPDATE model_predictions SET fwd_ret_pct=?, pnl_pct=? WHERE ts=? AND symbol=? AND horizon=?", (ret, pnl, ts, sym, h))
    con.commit()
    card["live"] = live_record(con)
    # versioned artifacts, keep the last 30
    if trained:
        mdir = os.path.join(data_dir, "models"); os.makedirs(mdir, exist_ok=True)
        with open(os.path.join(mdir, "model-%s.pkl" % stamp), "wb") as f:
            pickle.dump({"horizons": {h: v[0] for h, v in trained.items()}, "features": FEATURES, "card": card}, f)
        for old in sorted(os.listdir(mdir))[:-30]:
            os.remove(os.path.join(mdir, old))
    _write(card, data_dir)
    return card


def live_record(con):
    """Out-of-sample record of the logged predictions, scored on real later prices."""
    out = {}
    for h in HORIZONS:
        rows = con.execute("SELECT p_up, fwd_ret_pct, pnl_pct FROM model_predictions WHERE horizon=? AND fwd_ret_pct IS NOT NULL", (h,)).fetchall()
        tot = con.execute("SELECT COUNT(*) FROM model_predictions WHERE horizon=?", (h,)).fetchone()[0]
        pn = [r[2] for r in rows if r[2] is not None]
        out[h] = {"logged": tot, "scored": len(rows),
                  "hit_rate": round(sum(1 for r in rows if (r[0] >= .5) == (r[1] > 0)) / len(rows), 4) if rows else None,
                  "paper_trades": len(pn), "paper_total_net_pct": round(sum(pn), 2) if pn else 0.0}
    return out


def _write(card, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "model_card.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(card, f, indent=1, sort_keys=True)
