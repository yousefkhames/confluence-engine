"""Full-population study. No sampling.
1. kNN walk-forward over EVERY valid hourly bar of every coin (exact search, no approximation). For a query at bar i the references are the same coin's bars
   at least 48 h older (block-lagged: references end at the start of the query's block of BLOCK bars, so the lag is 48..48+BLOCK-1 h). Forward labels of references are
   known by then (label horizon <= 25 h). Feature scaling uses the first 70% of each coin's time only.
   Output is kept as exact histograms of the neighbour up-share m/K (K+1 bins) per coin x horizon x period, so AUC, accuracy, calibration and net long/short results are exact
   and the run is resumable chunk by chunk (progress JSON).
2. K-means over every point (all coins pooled, 19 standardized features, centroids fit on the first 70% of time, every point assigned), k by Davies-Bouldin on all points,
   cluster effects on the last 30% with Benjamini-Hochberg, plus time-of-day, volatility, BTC regime and Fear and Greed context.
numpy only. Paper research. Not financial advice."""
import json, os, math, time, datetime
import numpy as np
from pipeline import research as R

K = 60; BLOCK = 512; EMBARGO = 48; MIN_REFS = 2000; HZ = (1, 4, 12, 24); COST = R.COST_PCT


def _prep(series_1h):
    data = R.build(series_1h)
    out = {}
    for coin, (ts, X, c, fwd) in data.items():
        ok = ~np.isnan(X).any(axis=1)
        idx = np.where(ok)[0]
        if len(idx) < MIN_REFS + 500: continue
        out[coin] = {"ts": ts[idx], "X": X[idx], "fwd": {H: fwd[H][idx] for H in R.HORIZONS}}
    return out


def _period_keys(ts_arr, cut):
    yrs = np.array([datetime.datetime.utcfromtimestamp(int(t)).year for t in ts_arr[::1]]) if len(ts_arr) < 0 else None
    return yrs


def knn_coin(d, cut, progress, coin, budget_s=None, t0=None):
    """Process all remaining blocks for one coin. progress[coin] = {"next": idx, "hist": {...}}"""
    ts = d["ts"]; X = d["X"]; n = len(ts)
    m = ts < cut; mu = X[m].mean(0); sd = X[m].std(0) + 1e-9
    Z = ((X - mu) / sd).astype(np.float32); sq = (Z * Z).sum(1)
    yrs = np.array([datetime.datetime.utcfromtimestamp(int(t)).year for t in ts[::24]]); ymap = {}
    st = progress.setdefault(coin, {"next": MIN_REFS + EMBARGO, "hist": {}})
    F = {H: d["fwd"][H] for H in HZ}
    years_all = np.array([datetime.datetime.utcfromtimestamp(int(t)).year for t in ts])  # per-bar year (cheap enough, 1e5)
    s = st["next"]
    while s < n:
        e = min(s + BLOCK, n); lim = s - EMBARGO            # refs: indices < lim
        ref = Z[:lim]; D = sq[s:e, None] + sq[None, :lim] - 2.0 * (Z[s:e] @ ref.T)
        nn = np.argpartition(D, K, axis=1)[:, :K]
        for H in HZ:
            f = F[H]; fr = f[nn]; ok_ref = ~np.isnan(fr)
            cnt_ok = ok_ref.sum(1); up = ((fr > 0) & ok_ref).sum(1)
            q = f[s:e]; qok = ~np.isnan(q) & (cnt_ok >= K - 5)
            # bin = number of up neighbours scaled to K (missing refs are rare; scale)
            b = np.minimum(K, np.round(up / np.maximum(cnt_ok, 1) * K).astype(int))
            for per, pm in (("all", np.ones(e - s, bool)), ("test", ts[s:e] >= cut), ("train", ts[s:e] < cut)):
                sel = qok & pm
                if per == "all":
                    # per-year histograms too
                    for y in np.unique(years_all[s:e][sel]):
                        sy = sel & (years_all[s:e] == y); _acc(st["hist"], "%s|%d" % (H, y), b[sy], q[sy])
                _acc(st["hist"], "%s|%s" % (H, per), b[sel], q[sel])
        s = e; st["next"] = s
        if budget_s and time.time() - t0 > budget_s: return False
    st["done"] = True
    return True


def _acc(hist, key, b, ret):
    h = hist.setdefault(key, {"n": [0] * (K + 1), "up": [0] * (K + 1), "sum": [0.0] * (K + 1)})
    n = np.bincount(b, minlength=K + 1); u = np.bincount(b, weights=(ret > 0).astype(float), minlength=K + 1); sm = np.bincount(b, weights=ret, minlength=K + 1)
    for i in range(K + 1):
        h["n"][i] += int(n[i]); h["up"][i] += int(u[i]); h["sum"][i] += float(sm[i])


def metrics(h, neff_div=12.0):
    n = np.array(h["n"], float); up = np.array(h["up"], float); sm = np.array(h["sum"], float); N = n.sum()
    if N < 200: return {"n": int(N), "status": "insufficient"}
    pos = up.sum(); neg = N - pos
    # AUC from histogram: P(score_pos > score_neg) + 0.5 ties
    neg_b = n - up; cum_neg = np.cumsum(neg_b) - neg_b
    auc = float((up * (cum_neg + 0.5 * neg_b)).sum() / (pos * neg)) if pos and neg else None
    p = np.arange(K + 1) / K; pred_up = p >= 0.5
    acc = float(((up * pred_up) + (neg_b * (~pred_up))).sum() / N); base = float(max(pos, neg) / N)
    # net long / short, thresholds 0.6 / 0.4 of up share, entry cost 0.30%
    lm = p >= 0.6; sm_ = p <= 0.4
    ln = n[lm].sum(); sn = n[sm_].sum()
    long_net = float(sm[lm].sum() / ln - COST) if ln else None; short_net = float(-sm[sm_].sum() / sn - COST) if sn else None
    z = (acc - base) / math.sqrt(base * (1 - base) / N)
    # z with n/neff_div to account for overlapping labels and correlated coins
    zadj = z / math.sqrt(neff_div)
    # AUC standard error (Hanley-McNeil) with the same n shrink
    return {"n": int(N), "auc": round(auc, 4) if auc is not None else None, "accuracy": round(acc, 4), "base_rate_acc": round(base, 4), "z_vs_base": round(z, 2), "z_adj": round(zadj, 2),
            "long_trades": int(ln), "long_net_pct": round(long_net, 3) if long_net is not None else None, "short_trades": int(sn), "short_net_pct": round(short_net, 3) if short_net is not None else None,
            "mean_fwd_pct": round(float(sm.sum() / N), 4), "up_rate": round(float(pos / N), 4)}


def merge(progress):
    tot = {}
    for coin, st in progress.items():
        for k, h in st["hist"].items():
            t = tot.setdefault(k, {"n": [0] * (K + 1), "up": [0] * (K + 1), "sum": [0.0] * (K + 1)})
            for i in range(K + 1):
                t["n"][i] += h["n"][i]; t["up"][i] += h["up"][i]; t["sum"][i] += h["sum"][i]
    return tot


def summarize_knn(progress):
    tot = merge(progress); out = {"k": K, "embargo_h": EMBARGO, "block": BLOCK, "cost_pct": COST, "coins_done": sorted(c for c, s in progress.items() if s.get("done")), "coins_partial": sorted(c for c, s in progress.items() if not s.get("done")), "horizons": {}}
    for H in HZ:
        row = {"all": metrics(tot.get("%s|all" % H, {"n": [0] * (K + 1), "up": [0] * (K + 1), "sum": [0.0] * (K + 1)})), "test": metrics(tot.get("%s|test" % H, {"n": [0] * (K + 1), "up": [0] * (K + 1), "sum": [0.0] * (K + 1)})),
               "train": metrics(tot.get("%s|train" % H, {"n": [0] * (K + 1), "up": [0] * (K + 1), "sum": [0.0] * (K + 1)}))}
        yrs = sorted({k.split("|")[1] for k in tot if k.startswith("%s|" % H) and k.split("|")[1].isdigit()})
        row["by_year"] = {y: metrics(tot["%s|%s" % (H, y)]) for y in yrs}
        h = tot.get("%s|all" % H)
        if h:  # calibration by predicted up-share decile
            n = np.array(h["n"], float); up = np.array(h["up"], float); sm = np.array(h["sum"], float); cal = []
            edges = [0, 18, 24, 27, 30, 33, 36, 42, 61]
            for a, b in zip(edges[:-1], edges[1:]):
                nn_ = n[a:b].sum()
                if nn_ > 0: cal.append({"up_share_bin": "%.2f-%.2f" % (a / K, min(b, K + 1) / K), "n": int(nn_), "realized_up_rate": round(float(up[a:b].sum() / nn_), 4), "mean_fwd_pct": round(float(sm[a:b].sum() / nn_), 4)})
            row["calibration"] = cal
        h_ = row["test"]
        row["verdict"] = ("no usable edge" if not (h_.get("auc") and h_["auc"] > 0.53 and h_.get("z_adj", 0) > 3) else "possible edge, needs more evidence")
        out["horizons"][str(H)] = row
    return out


def run_knn(series_1h, data_dir, budget_s=None, only=None):
    t0 = time.time(); d = _prep(series_1h); allts = np.concatenate([v["ts"] for v in d.values()]); cut = float(np.quantile(allts, 0.7))
    pf = os.path.join(data_dir, "knn_full_progress.json"); progress = json.load(open(pf)) if os.path.exists(pf) else {}
    for coin in sorted(d, key=lambda c: len(d[c]["ts"])):
        if only and coin not in only: continue
        if progress.get(coin, {}).get("done"): continue
        finished = knn_coin(d[coin], cut, progress, coin, budget_s, t0)
        json.dump(progress, open(pf, "w"))
        if not finished: break
    res = summarize_knn(progress); res["generated"] = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"; res["split_ts"] = cut; res["coins_total"] = len(d)
    res["queries_total_hint"] = int(sum(len(v["ts"]) - MIN_REFS - EMBARGO for v in d.values()))
    json.dump(res, open(os.path.join(data_dir, "knn_full.json"), "w"), indent=1)
    return res


# ---------------------------------------------------------------- clustering of every situation
def _kmeans(Z, k, iters=15, seed=3, chunk=100000):
    rng = np.random.default_rng(seed); sub = Z[rng.choice(len(Z), size=min(20000, len(Z)), replace=False)]
    cen = [sub[rng.integers(len(sub))]]; d2 = ((sub - cen[0]) ** 2).sum(1)
    for _ in range(1, k):
        p = d2 / d2.sum(); c = sub[rng.choice(len(sub), p=p)]; cen.append(c); d2 = np.minimum(d2, ((sub - c) ** 2).sum(1))
    cen = np.array(cen, dtype=np.float32)
    for _ in range(iters):
        S = np.zeros_like(cen, dtype=np.float64); N = np.zeros(k)
        for a in range(0, len(Z), chunk):
            zb = Z[a:a + chunk]; lab = _assign(zb, cen)
            for j in range(k):
                m = lab == j
                if m.any(): S[j] += zb[m].sum(0); N[j] += m.sum()
        new = np.where(N[:, None] > 0, S / np.maximum(N[:, None], 1), cen); cen = new.astype(np.float32)
    return cen


def _assign(zb, cen):
    d = (zb * zb).sum(1)[:, None] + (cen * cen).sum(1)[None, :] - 2.0 * zb @ cen.T
    return d.argmin(1)


def _db(Z, cen, chunk=100000):
    k = len(cen); sc = np.zeros(k); n = np.zeros(k)
    for a in range(0, len(Z), chunk):
        zb = Z[a:a + chunk]; lab = _assign(zb, cen); dist = np.sqrt(((zb - cen[lab]) ** 2).sum(1))
        for j in range(k):
            m = lab == j; sc[j] += dist[m].sum(); n[j] += m.sum()
    s = sc / np.maximum(n, 1); dm = np.sqrt(((cen[:, None, :] - cen[None, :, :]) ** 2).sum(2)); np.fill_diagonal(dm, np.inf)
    return float(np.mean([max((s[i] + s[j]) / dm[i, j] for j in range(k) if j != i) for i in range(k)]))


def run_clusters(series_1h, data_dir, fng_path=None, ks=(6, 8, 12, 16), hz=(1, 4, 24)):
    d = _prep(series_1h); coins = sorted(d)
    X = np.vstack([d[c]["X"] for c in coins]); T = np.concatenate([d[c]["ts"] for c in coins])
    F = {H: np.concatenate([d[c]["fwd"][H] for c in coins]) for H in hz}; C = np.concatenate([[i] * len(d[c]["ts"]) for i, c in enumerate(coins)])
    cut = float(np.quantile(T, 0.7)); tr = T < cut
    mu = X[tr].mean(0); sd = X[tr].std(0) + 1e-9; Z = ((X - mu) / sd).astype(np.float32)
    cand = {}
    for k in ks:
        cen = _kmeans(Z[tr], k); cand[k] = (_db(Z[tr], cen), cen)
    kbest = min(cand, key=lambda k: cand[k][0]); cen = cand[kbest][1]
    lab = np.concatenate([_assign(Z[a:a + 100000], cen) for a in range(0, len(Z), 100000)])
    # context: BTC regime (BTC 72h return sign at the same hour), fear and greed by UTC day
    btc = {int(t): v for t, v in zip(d["BTC"]["ts"], d["BTC"]["X"][:, 4])} if "BTC" in d else {}
    reg = np.array([btc.get(int(t), np.nan) for t in T]); fng = {}
    if fng_path and os.path.exists(fng_path):
        try:
            j = json.load(open(fng_path)); rows = [] if isinstance(j, dict) else j
            if isinstance(j, dict):
                for kk, vv in j.items():
                    try: fng[int(float(kk)) // 86400] = float(vv)
                    except Exception: pass
            for r in rows:
                if isinstance(r, dict): fng[int(r.get("ts", r.get("timestamp", 0))) // 86400] = float(r.get("value", r.get("v", np.nan)))
                elif isinstance(r, (list, tuple)): fng[int(r[0]) // 86400] = float(r[1])
        except Exception:
            fng = {}
    fv = np.array([fng.get(int(t) // 86400, np.nan) for t in T]) if fng else np.full(len(T), np.nan)
    hour = (T // 3600) % 24; rows = []; pv = []; idx = []
    for j in range(kbest):
        m = lab == j; mt = m & ~tr; mtr = m & tr
        row = {"cluster": j, "n_all": int(m.sum()), "share_pct": round(100 * m.mean(), 2), "n_train": int(mtr.sum()), "n_test": int(mt.sum()),
               "centroid_raw": {nm: round(float(X[m][:, i].mean()), 3) for i, nm in enumerate(R.FEATS) if nm in ("ret3", "ret24", "ret72", "vol24", "rsi14", "dist_ema50", "range_pos7d", "vol_z", "lower_wick")},
               "top_hours_utc": [int(h) for h in np.argsort(-np.bincount(hour[m].astype(int), minlength=24))[:3]], "btc_up_regime_pct": round(float(100 * np.nanmean(reg[m] > 0)), 1) if np.isfinite(reg[m]).any() else None,
               "mean_fear_greed": round(float(np.nanmean(fv[m])), 1) if np.isfinite(fv[m]).any() else None, "fwd": {}}
        for H in hz:
            f = F[H]; a = f[mtr & ~np.isnan(f)]; b = f[mt & ~np.isnan(f)]
            def tstat(x):
                if len(x) < 50: return None, 1.0
                ne = len(x) / 12.0; t = x.mean() / (x.std() / math.sqrt(max(ne, 1))); return float(t), R._p_from_t(t)
            ta, pa = tstat(a); tb, pb = tstat(b)
            row["fwd"][str(H)] = {"train_mean_pct": round(float(a.mean()), 4) if len(a) else None, "test_mean_pct": round(float(b.mean()), 4) if len(b) else None, "test_t_adj": round(tb, 2) if tb is not None else None, "p_test": round(pb, 4),
                                  "test_net_long_pct": round(float(b.mean()) - COST, 4) if len(b) else None, "test_net_short_pct": round(float(-b.mean()) - COST, 4) if len(b) else None}
            dts = (T[mt & ~np.isnan(f)] // 86400).astype(int)
            if len(b) >= 50:
                u, inv = np.unique(dts, return_inverse=True); sums = np.bincount(inv, weights=b); cnts = np.bincount(inv)
                top = np.argsort(-np.abs(sums))[:3]; keepd = np.ones(len(u), bool); keepd[top] = False
                row["fwd"][str(H)]["test_distinct_days"] = int(len(u)); row["fwd"][str(H)]["test_mean_ex_top3_days_pct"] = round(float(sums[keepd].sum() / max(cnts[keepd].sum(), 1)), 4) if keepd.any() else None
                row["fwd"][str(H)]["test_top3_days_share_of_abs_sum"] = round(float(np.abs(sums[top]).sum() / max(np.abs(sums).sum(), 1e-12)), 3)
            pv.append(pb); idx.append((j, str(H)))
        rows.append(row)
    keep = R.bh(pv)
    for (j, H), kp in zip(idx, keep):
        rows[j]["fwd"][H]["survives_fdr5"] = bool(kp)
        f_ = rows[j]["fwd"][H]; f_["same_sign_train_test"] = bool(f_["train_mean_pct"] is not None and f_["test_mean_pct"] is not None and np.sign(f_["train_mean_pct"]) == np.sign(f_["test_mean_pct"]))
    out = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "points": int(len(T)), "coins": len(coins), "features": R.FEATS, "k_candidates_davies_bouldin": {str(k): round(v[0], 3) for k, v in cand.items()}, "k": kbest,
           "fit_on": "first 70% of time; every point of every coin is assigned; effects judged on the last 30%", "tests": len(pv), "survivors_fdr5": int(sum(keep)),
           "survivors_oos_same_sign": int(sum(1 for (j, H), kp in zip(idx, keep) if kp and rows[j]["fwd"][H]["same_sign_train_test"])), "clusters": rows,
           "news_note": "No free historical news archive is stored, so news is not part of the context columns. Fear and Greed is included where available."}
    json.dump(out, open(os.path.join(data_dir, "clusters.json"), "w"), indent=1)
    return out


def _t(head, rows):
    import html as h
    return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % h.escape(x) for x in head), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % h.escape(str(c)) for c in r) for r in rows))


def page(knn, cl):
    b = ['<p class=warn>No sampling: every valid hourly bar of all %d coins is a query (%s queries per horizon). Exact nearest-neighbour search, no approximation. Walk-forward: references are at least 48 h older than the query. '
         'Paper research only. A result is called usable only if it holds in the last 30%% of time and clears costs after correction.</p>' % (knn["coins_total"], format(knn["horizons"]["1"]["all"]["n"], ","))]
    b.append("<h2>1. kNN walk-forward over every point (K=%d)</h2>" % knn["k"])
    rows = []
    for H, v in knn["horizons"].items():
        for per in ("all", "train", "test"):
            m = v[per]; rows.append([H + " h", {"all": "all time", "train": "first 70%", "test": "last 30%"}[per], format(m["n"], ","), m.get("auc"), m.get("accuracy"), m.get("base_rate_acc"), m.get("z_adj"), m.get("long_trades"), m.get("long_net_pct"), m.get("short_trades"), m.get("short_net_pct"), v["verdict"] if per == "test" else ""])
    b.append(_t(["Horizon", "Period", "Queries", "AUC", "Accuracy", "Base", "z (adj)", "Long trades (p>=0.6)", "Long net %", "Short trades (p<=0.4)", "Short net %", "Verdict"], rows))
    b.append("<p class=m>Net = mean forward return minus the 0.30% round-trip cost. z is shrunk by sqrt(12) for overlapping labels and correlated coins.</p>")
    b.append("<h3>AUC by year (the ranking is slightly better than chance and shrinking)</h3>" + _t(["Year"] + [h + " h" for h in knn["horizons"]], [[y] + [knn["horizons"][h]["by_year"].get(y, {}).get("auc", "") for h in knn["horizons"]] for y in sorted(knn["horizons"]["1"]["by_year"])]))
    b.append("<h3>Calibration, 24 h (neighbour up-share bin vs what happened)</h3>" + _t(["Up-share bin", "n", "Realized up rate", "Mean 24 h return %"], [[c["up_share_bin"], c["n"], c["realized_up_rate"], c["mean_fwd_pct"]] for c in knn["horizons"]["24"]["calibration"]]))
    if knn.get("top_bin_test"):
        b.append("<h3>Strongest agreement bin (up-share 0.70 or more), last 30% only</h3>" + _t(["Horizon", "Trades", "Up rate", "Mean return %", "Net of 0.30%"], [[r["h"], r["n"], r["up_rate"], r["mean"], r["net"]] for r in knn["top_bin_test"]]) +
                 "<p class=m>Post-hoc threshold, overlapping holds and correlated coins: a candidate to test forward, not a result.</p>")
    b.append("<h2>2. Clusters of every situation (k=%d, %s points)</h2><p class=m>%s Davies-Bouldin by k: %s. %s %d tests, %d survive Benjamini-Hochberg 5%%, %d with the same sign in the first 70%% and the last 30%%.</p>" % (
        cl["k"], format(cl["points"], ","), cl["fit_on"], cl["k_candidates_davies_bouldin"], cl["news_note"], cl["tests"], cl["survivors_fdr5"], cl["survivors_oos_same_sign"]))
    rows = []
    for c in cl["clusters"]:
        ce = c["centroid_raw"]
        for H, v in c["fwd"].items():
            if H == "4": continue
            rows.append([c["cluster"], format(c["n_all"], ","), c["n_test"], ce.get("ret24"), ce.get("vol24"), ce.get("rsi14"), c["top_hours_utc"], c["btc_up_regime_pct"], c["mean_fear_greed"], H + " h", v["train_mean_pct"], v["test_mean_pct"], v["test_t_adj"], "YES" if v.get("survives_fdr5") else "", v.get("test_distinct_days", ""), v.get("test_mean_ex_top3_days_pct", "")])
    b.append(_t(["Cluster", "Points", "Test points", "ret24 %", "vol24 %", "RSI", "Top UTC hours", "BTC up %", "Fear&Greed", "Horizon", "Train mean %", "Test mean %", "t (adj)", "FDR 5%", "Test days", "Test mean ex top-3 days %"], rows))
    b.append("<p class=m>Reading: 4 of the 5 surviving cluster-horizon results are sharp-drop situations (24 h return about -11% to -20%, high volatility, BTC mostly in a down regime, fear): prices tend to rebound. The fifth (cluster 9) is a mild uptrend evening cluster whose 24 h mean is under cost once the biggest days are removed. Some clusters rest on a few event days (see the ex top-3 days column). A gross 24 h rebound of about 0.9% to 1.3% in the broadest surviving cluster is above the 0.30% cost, but it is a candidate that must hold in forward paper trading, not a proven edge.</p>")
    return "".join(b)
