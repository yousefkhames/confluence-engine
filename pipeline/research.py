"""Research engine: replay history as if live, one simulated entry at EVERY hourly bar of every coin, at many horizons,
both directions, no hindsight. Rich causal feature vector per point; similarity search (kNN); session effects;
multiple-testing control. Needs numpy (pipeline job only).

Honest limits: the deep history is hourly (Binance dumps). Horizons shorter than 1 hour (10s..30m) cannot be replayed
from stored data: they need tick data, which has no free deep archive. They are covered by the live paper runner only.
"""
import math, json, os, datetime
import numpy as np

HORIZONS = [1, 2, 3, 4, 5, 6, 8, 12, 24, 48]     # hours
FEATS = ["ret1", "ret3", "ret6", "ret24", "ret72", "vol24", "volratio", "rsi14", "dist_ema50", "dist_hi24", "dist_lo24",
         "range_pos7d", "lower_wick", "body_atr", "vol_z", "hour_sin", "hour_cos", "dist_swing_lo", "dist_swing_hi"]
COST_PCT = 0.30


def _ema(x, n):
    k = 2 / (n + 1); out = np.empty_like(x); e = x[0]
    for i, v in enumerate(x):
        e = v * k + e * (1 - k); out[i] = e
    return out


def _roll(x, n, fn):
    """Trailing window (inclusive) max/min/sum via cumulative trick; NaN until full."""
    out = np.full(len(x), np.nan)
    if fn == "sum":
        c = np.cumsum(np.insert(x, 0, 0.0)); out[n - 1:] = c[n:] - c[:-n]
        return out
    from numpy.lib.stride_tricks import sliding_window_view as sw
    w = sw(x, n); out[n - 1:] = w.max(axis=1) if fn == "max" else w.min(axis=1)
    return out


def featurize(bars):
    """bars: list of (ts, o, h, l, c, v) oldest first. Returns (ts, X [n x F] with NaN warm-up, close, open, forward dict)."""
    a = np.array(bars, dtype=float); ts = a[:, 0]; o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    n = len(c); X = np.full((n, len(FEATS)), np.nan)
    lc = np.log(c); r1 = np.diff(lc, prepend=lc[0])
    def ret(k):
        out = np.full(n, np.nan); out[k:] = (c[k:] / c[:-k] - 1) * 100; return out
    X[:, 0] = ret(1); X[:, 1] = ret(3); X[:, 2] = ret(6); X[:, 3] = ret(24); X[:, 4] = ret(72)
    s1 = _roll(r1, 24, "sum"); s2 = _roll(r1 * r1, 24, "sum"); X[:, 5] = np.sqrt(np.maximum(s2 / 24 - (s1 / 24) ** 2, 0)) * 100
    s6 = _roll(r1 * r1, 6, "sum"); s72 = _roll(r1 * r1, 72, "sum")
    X[:, 6] = np.sqrt(s6 / 6) / (np.sqrt(s72 / 72) + 1e-12)
    d = np.diff(c, prepend=c[0]); g = np.maximum(d, 0); ls = np.maximum(-d, 0)
    ag = np.full(n, np.nan); al = np.full(n, np.nan)
    if n > 14:
        ag[14] = g[1:15].mean(); al[14] = ls[1:15].mean()
        for i in range(15, n):
            ag[i] = (ag[i - 1] * 13 + g[i]) / 14; al[i] = (al[i - 1] * 13 + ls[i]) / 14
    X[:, 7] = 100 - 100 / (1 + ag / (al + 1e-12))
    X[:, 8] = (c / _ema(c, 50) - 1) * 100
    hi24 = _roll(h, 24, "max"); lo24 = _roll(l, 24, "min")
    X[:, 9] = (c / hi24 - 1) * 100; X[:, 10] = (c / lo24 - 1) * 100
    hi7 = _roll(h, 168, "max"); lo7 = _roll(l, 168, "min"); X[:, 11] = (c - lo7) / (hi7 - lo7 + 1e-12)
    rng = h - l + 1e-12; X[:, 12] = (np.minimum(o, c) - l) / rng
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1)))); atr = _roll(tr, 14, "sum") / 14
    tr[0] = h[0] - l[0]; atr = _roll(tr, 14, "sum") / 14
    X[:, 13] = np.abs(c - o) / (atr + 1e-12)
    vs = _roll(v, 24, "sum") / 24; v2 = _roll(v * v, 24, "sum") / 24
    X[:, 14] = (v - vs) / (np.sqrt(np.maximum(v2 - vs ** 2, 0)) + 1e-12)
    hr = (ts // 3600) % 24; X[:, 15] = np.sin(2 * np.pi * hr / 24); X[:, 16] = np.cos(2 * np.pi * hr / 24)
    # distance (in ATR) to the nearest confirmed swing low / high within the last 72 bars (confirmed = 3 bars each side, so known 3 bars later)
    X[:, 17] = np.nan; X[:, 18] = np.nan
    from numpy.lib.stride_tricks import sliding_window_view as sw
    if n > 7:
        w = sw(l, 7); is_lo = np.zeros(n, bool); is_lo[3:n - 3] = w[:, 3] <= w.min(axis=1)
        w = sw(h, 7); is_hi = np.zeros(n, bool); is_hi[3:n - 3] = w[:, 3] >= w.max(axis=1)
        lo_idx = np.where(is_lo)[0]; hi_idx = np.where(is_hi)[0]
        for i in range(80, n):
            k = np.searchsorted(lo_idx, i - 3, side="right"); lo = lo_idx[max(0, k - 5):k]; lo = lo[lo >= i - 72]
            if len(lo):
                X[i, 17] = (c[i] - l[lo].max()) / (atr[i] + 1e-12) if False else (c[i] - l[lo[np.argmin(np.abs(c[i] - l[lo]))]]) / (atr[i] + 1e-12)
            k = np.searchsorted(hi_idx, i - 3, side="right"); hi = hi_idx[max(0, k - 5):k]; hi = hi[hi >= i - 72]
            if len(hi):
                X[i, 18] = (h[hi[np.argmin(np.abs(c[i] - h[hi]))]] - c[i]) / (atr[i] + 1e-12)
    fwd = {}
    for H in HORIZONS:
        f = np.full(n, np.nan)
        if n > H + 1:
            f[:n - H - 1] = (c[H:n - 1] / o[1:n - H] - 1) * 100       # enter next open, exit close H bars later
        fwd[H] = f
    return ts, X, c, o, fwd


def bh(pvals, q=0.05):
    """Benjamini-Hochberg: boolean list of tests that survive FDR q."""
    m = len(pvals); order = sorted(range(m), key=lambda i: pvals[i]); keep = [False] * m; kmax = -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / m:
            kmax = rank
    for rank, i in enumerate(order, 1):
        if rank <= kmax:
            keep[i] = True
    return keep


def _p_from_t(t):
    return math.erfc(abs(t) / math.sqrt(2))


def build(series_1h):
    """series_1h {coin: bars}. Returns dict coin -> (ts, X, fwd) and pooled arrays."""
    data = {}
    for coin, bars in series_1h.items():
        if len(bars) < 500:
            continue
        ts, X, c, o, fwd = featurize(bars); data[coin] = (ts, X, c, fwd)
    return data


def session_effects(data, cross_coin_factor=5.0):
    """Mean forward return by UTC hour and by session, per horizon, with n_eff and BH correction over all tests.
    n_eff = n / H (overlap) / cross_coin_factor (coins move together; deliberately conservative)."""
    tests = []
    for H in HORIZONS:
        by_hour = {k: [] for k in range(24)}
        for coin, (ts, X, c, fwd) in data.items():
            f = fwd[H]; ok = ~np.isnan(f); hrs = ((ts // 3600) % 24).astype(int)
            for hh in range(24):
                by_hour[hh].append(f[ok & (hrs == hh)])
        allv = np.concatenate([np.concatenate(v) for v in by_hour.values()]); mu0 = allv.mean(); sd = allv.std() or 1e-9
        for hh in range(24):
            v = np.concatenate(by_hour[hh]); n = len(v)
            if n < 200:
                continue
            neff = max(2.0, n / H / cross_coin_factor)
            t = (v.mean() - mu0) / (sd / math.sqrt(neff))
            tests.append({"horizon_h": H, "utc_hour": hh, "n": n, "n_eff": round(neff), "mean_pct": round(float(v.mean()), 4),
                          "excess_vs_all_pct": round(float(v.mean() - mu0), 4), "up_rate": round(float((v > 0).mean()), 4), "t": round(t, 2), "p": _p_from_t(t)})
    keep = bh([t["p"] for t in tests])
    for t, k in zip(tests, keep):
        t["survives_fdr5"] = k; t["p"] = round(t["p"], 5)
    return {"tests": len(tests), "survivors": sum(keep), "cross_coin_factor": cross_coin_factor,
            "top": sorted(tests, key=lambda t: t["p"])[:12], "note": "Survivors under Benjamini-Hochberg FDR 5%; zero survivors means no hour-of-day effect can be claimed."}


def _stack(data, stride=1, max_ts=None):
    Xs, Fs, Ts, Cs = [], {H: [] for H in HORIZONS}, [], []
    for coin, (ts, X, c, fwd) in data.items():
        ok = ~np.isnan(X).any(axis=1)
        if max_ts is not None:
            ok &= ts <= max_ts
        idx = np.where(ok)[0][::stride]
        Xs.append(X[idx]); Ts.append(ts[idx]); Cs.append(np.array([coin] * len(idx)))
        for H in HORIZONS:
            Fs[H].append(fwd[H][idx])
    return np.vstack(Xs), {H: np.concatenate(v) for H, v in Fs.items()}, np.concatenate(Ts), np.concatenate(Cs)


def knn_now(data, k=60, horizons=(1, 4, 12, 24)):
    """For each coin's newest bar: nearest historical situations (standardized features, all coins pooled) and what followed.
    Neighbours must be at least 48 bars older than the query's own future, so no outcome overlaps the present."""
    X, F, T, C = _stack(data, stride=1)
    mu = X.mean(0); sd = X.std(0) + 1e-9; Z = ((X - mu) / sd).astype(np.float32)
    now_ts = max(d[0][-1] for d in data.values())
    base = {H: {"up": round(float((F[H][~np.isnan(F[H])] > 0).mean()), 4), "mean": round(float(np.nanmean(F[H])), 4)} for H in horizons}
    out = []
    for coin, (ts, Xc, c, fwd) in data.items():
        q = Xc[-1]
        if np.isnan(q).any() or now_ts - ts[-1] > 3 * 86400:
            continue
        zq = ((q - mu) / sd).astype(np.float32)
        dist = np.sqrt(((Z - zq) ** 2).sum(1)); dist[T > ts[-1] - 48 * 3600] = np.inf
        for H in horizons:
            dist[np.isnan(F[H])] = np.inf
        idx = np.argpartition(dist, k)[:k]; idx = idx[np.argsort(dist[idx])]
        res = {"coin": coin, "asof": datetime.datetime.utcfromtimestamp(ts[-1]).isoformat(timespec="minutes") + "Z", "k": k,
               "median_distance": round(float(np.median(dist[idx])), 2), "horizons": {}}
        for H in horizons:
            f = F[H][idx]; f = f[~np.isnan(f)]
            if len(f) < 10:
                continue
            res["horizons"][str(H)] = {"n": len(f), "up_rate": round(float((f > 0).mean()), 3), "base_up_rate": base[H]["up"],
                                       "mean_pct": round(float(f.mean()), 3), "base_mean_pct": base[H]["mean"],
                                       "p10": round(float(np.percentile(f, 10)), 2), "p50": round(float(np.percentile(f, 50)), 2), "p90": round(float(np.percentile(f, 90)), 2)}
        diff = (zq - Z[idx].mean(0))
        res["how_conditions_differ"] = {FEATS[j]: round(float(diff[j]), 2) for j in np.argsort(-np.abs(diff))[:3]}
        res["closest"] = [{"coin": str(C[i]), "date": datetime.datetime.utcfromtimestamp(T[i]).strftime("%Y-%m-%d %H:%M"), "distance": round(float(dist[i]), 2),
                           "after_4h_pct": None if np.isnan(F[4][i]) else round(float(F[4][i]), 2), "after_24h_pct": None if np.isnan(F[24][i]) else round(float(F[24][i]), 2)} for i in idx[:5]]
        res["opposite_cases"] = {"share_reversed_4h": round(float((np.sign(F[4][idx]) != np.sign(Xc[-1, 1])).mean()), 3), "note": "share of neighbours where the next 4h moved against the preceding 3h move"}
        out.append(res)
    return out


def knn_validate(data, k=60, n_query=800, horizons=(4, 24), stride_ref=3, seed=5):
    """Walk-forward: query points from the last 2 years, references strictly older (embargo = 48h). Out-of-sample by construction."""
    X, F, T, C = _stack(data, stride=stride_ref)
    mu = X.mean(0); sd = X.std(0) + 1e-9; Z = ((X - mu) / sd).astype(np.float32)
    tmax = T.max(); cand = np.where(T > tmax - 2 * 365 * 86400)[0]
    rng = np.random.default_rng(seed); pick = rng.choice(cand, size=min(n_query, len(cand)), replace=False)
    res = {"queries": int(len(pick)), "k": k, "horizons": {}}
    for H in horizons:
        hits = []; preds = []; rets = []
        for i in pick:
            if np.isnan(F[H][i]):
                continue
            d = np.sqrt(((Z - Z[i]) ** 2).sum(1)); d[T > T[i] - 48 * 3600] = np.inf; d[np.isnan(F[H])] = np.inf
            nn = np.argpartition(d, k)[:k]; nn = nn[np.isfinite(d[nn])]
            if len(nn) < k // 2:
                continue
            p_up = float((F[H][nn] > 0).mean()); preds.append(p_up); rets.append(float(F[H][i]))
        preds = np.array(preds); rets = np.array(rets); y = rets > 0
        if len(y) < 100:
            res["horizons"][str(H)] = {"status": "insufficient data", "n": int(len(y))}; continue
        order = preds.argsort(); ranks = np.empty(len(preds)); ranks[order] = np.arange(len(preds))
        n1 = y.sum(); n0 = len(y) - n1
        auc = float((ranks[y].sum() - n1 * (n1 - 1) / 2) / (n1 * n0)) if n1 and n0 else None
        acc = float(((preds >= 0.5) == y).mean()); base = float(max(y.mean(), 1 - y.mean()))
        long = rets[preds >= 0.6] - COST_PCT; short = -rets[preds <= 0.4] - COST_PCT
        z = (acc - base) / math.sqrt(base * (1 - base) / len(y))
        res["horizons"][str(H)] = {"n": int(len(y)), "auc": round(auc, 4) if auc else None, "accuracy": round(acc, 4), "base_rate_acc": round(base, 4),
                                   "z_vs_base": round(z, 2), "long_trades": int(len(long)), "long_mean_net_pct": round(float(long.mean()), 3) if len(long) else None,
                                   "short_trades": int(len(short)), "short_mean_net_pct": round(float(short.mean()), 3) if len(short) else None,
                                   "verdict": "possible edge, needs more evidence" if (auc and auc > 0.53 and z > 3) else "no usable edge"}
    return res


def run(series_1h, data_dir, site_dir):
    data = build(series_1h)
    out = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "coins": len(data),
           "points": int(sum(len(v[0]) for v in data.values())), "horizons_h": HORIZONS, "features": FEATS,
           "entries_simulated": int(sum(np.sum(~np.isnan(v[3][H])) for v in data.values() for H in HORIZONS)) * 2,
           "note": "Every hourly bar of every coin is an entry at every horizon, both directions, no hindsight. Sub-hour horizons need tick data (live runner only)."}
    out["sessions"] = session_effects(data)
    out["knn_now"] = knn_now(data)
    out["knn_validation"] = knn_validate(data)
    os.makedirs(site_dir, exist_ok=True); os.makedirs(data_dir, exist_ok=True)
    for d in (data_dir, site_dir):
        json.dump(out, open(os.path.join(d, "research.json"), "w"), indent=1, sort_keys=True)
    return out


def page(out):
    import html
    e = html.escape
    kn = "".join("<tr><td>%s</td><td>%s</td>%s<td>%s</td><td>%s</td></tr>" % (e(k["coin"]), e(k["asof"]), "".join(
        "<td>%s</td>" % ("%s up vs %s base, mean %s%% (n=%s)" % (v["up_rate"], v["base_up_rate"], v["mean_pct"], v["n"]) if v else "") for v in (k["horizons"].get("4"), k["horizons"].get("24"))),
        e(json.dumps(k["how_conditions_differ"])), e("; ".join("%s %s (4h %s%%)" % (c["coin"], c["date"], c["after_4h_pct"]) for c in k["closest"][:3]))) for k in out["knn_now"])
    kv = "".join("<tr><td>%sh</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (h, v.get("n"), v.get("auc"), "%s vs base %s (z %s)" % (v.get("accuracy"), v.get("base_rate_acc"), v.get("z_vs_base")), "long %s / short %s" % (v.get("long_mean_net_pct"), v.get("short_mean_net_pct")), e(v.get("verdict", v.get("status", "")))) for h, v in out["knn_validation"]["horizons"].items())
    ss = out["sessions"]; top = "".join("<tr><td>%sh</td><td>%s:00 UTC</td><td>%s</td><td>%s%%</td><td>%s</td><td>%s</td></tr>" % (t["horizon_h"], t["utc_hour"], t["n_eff"], t["excess_vs_all_pct"], t["t"], "yes" if t["survives_fdr5"] else "no") for t in ss["top"])
    return """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Confluence Engine | research engine</title>
<style>body{font:15px system-ui;margin:0;background:#0b0f17;color:#dbe4f0}a{color:#60a5fa}main{max-width:1200px;margin:auto;padding:16px}table{border-collapse:collapse;font-size:13px;width:100%%}td,th{padding:6px 8px;border-bottom:1px solid #223;text-align:left;vertical-align:top}small,.m{color:#8da2bd}.warn{background:#3b2a12;color:#fde68a;padding:8px 12px;border-radius:6px}</style>
<main><p><a href="./">&larr; live dashboard</a> | <a href="patterns.html">pattern library</a></p><h1>Research engine</h1>
<p class=warn>Replay on %d coins, %s hourly points, horizons %s hours. %s simulated entries (both directions, entry at next open, no hindsight). %s Paper research only, not financial advice. Generated %s.</p>
<h2>Similar situations now (kNN, %d features, k=60)</h2><p class=m>Nearest historical situations to each coin's newest bar, from all coins and 9 years, never overlapping the present. Compare the neighbours' outcome with the base rate.</p>
<table><tr><th>Coin</th><th>As of</th><th>After 4h</th><th>After 24h</th><th>How now differs from neighbours (z)</th><th>Closest cases</th></tr>%s</table>
<h2>Does similarity predict? Walk-forward test</h2><p class=m>%d random query points from the last 2 years, neighbours only from strictly earlier data (48h embargo). Costs %.2f%% round trip. If AUC is near 0.5 there is no usable edge.</p>
<table><tr><th>Horizon</th><th>n</th><th>AUC</th><th>Accuracy</th><th>Net mean per trade %%</th><th>Verdict</th></tr>%s</table>
<h2>Session effects (hour of day), multiple-testing corrected</h2><p class=m>%d tests (hours x horizons). %d survive Benjamini-Hochberg FDR 5%%. n_eff accounts for overlapping windows and coins moving together. Smallest p-values:</p>
<table><tr><th>Horizon</th><th>Hour</th><th>n_eff</th><th>Excess return</th><th>t</th><th>Survives FDR</th></tr>%s</table>
<p class=m>Not covered by stored history: horizons under 1 hour (10s to 30m) need tick data, which has no free deep archive. News context history is also short (the pipeline collects it going forward). Raw: <a href="research.json">research.json</a>.</p></main>""" % (
        out["coins"], format(out["points"], ","), out["horizons_h"], format(out["entries_simulated"], ","), e(out["note"]), out["generated"], len(out["features"]), kn,
        out["knn_validation"]["queries"], COST_PCT, kv, ss["tests"], ss["survivors"], top)
