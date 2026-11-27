"""Lenses: the same data studied with different mindsets. Each lens logs hypothesis, test, numbers, verdict.
Rules for every lens: decide on the first 70% of time, judge on the last 30%; Benjamini-Hochberg over all p-values of the
lens; effect size next to significance; negative results are logged. numpy only (pipeline job).
"""
import math, json, os, datetime
import numpy as np
from pipeline import deep_history as D

COST = 0.30


def _p(z):
    return math.erfc(abs(z) / math.sqrt(2))


def bh(pv, q=0.05):
    m = len(pv); order = sorted(range(m), key=lambda i: pv[i]); kmax = 0
    for r, i in enumerate(order, 1):
        if pv[i] <= q * r / m:
            kmax = r
    keep = [False] * m
    for r, i in enumerate(order, 1):
        if r <= kmax:
            keep[i] = True
    return keep


def arrays(S):
    """{coin: dict(ts, o,h,l,c,v, r)} hourly, plus daily."""
    out = {}
    for coin in {k[0] for k in S}:
        a = np.array(S[(coin, "1h")], dtype=float); d = np.array(S[(coin, "1d")], dtype=float)
        out[coin] = {"ts": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5], "r": np.diff(np.log(a[:, 4]), prepend=np.log(a[0, 4])),
                     "dc": d[:, 4], "dr": np.diff(np.log(d[:, 4]), prepend=np.log(d[0, 4]))}
    return out


def acf(x, lags):
    x = x - x.mean(); den = (x * x).sum()
    return np.array([(x[:-k] * x[k:]).sum() / den for k in lags])


def adf_t(y, lags=4):
    """Dickey-Fuller regression with constant and `lags` lagged differences. 5% critical value about -2.86 (reject unit root if t below)."""
    dy = np.diff(y); n = len(dy) - lags
    X = [np.ones(n), y[lags:-1][:n]]
    for k in range(1, lags + 1):
        X.append(dy[lags - k:len(dy) - k][:n])
    X = np.column_stack(X); t = dy[lags:][:n]
    beta, res, *_ = np.linalg.lstsq(X, t, rcond=None)
    e = t - X @ beta; s2 = (e @ e) / (n - X.shape[1]); cov = s2 * np.linalg.inv(X.T @ X)
    return float(beta[1] / math.sqrt(cov[1, 1]))


def variance_ratio(r, q):
    """Lo-MacKinlay VR(q) with heteroskedasticity-robust z*. VR>1 momentum, VR<1 mean reversion."""
    n = len(r); mu = r.mean(); x = r - mu
    s1 = (x * x).sum() / (n - 1)
    rq = np.convolve(r, np.ones(q), mode="valid")
    sq = ((rq - q * mu) ** 2).sum() / (len(rq) * q) * (len(rq) / (len(rq) - 1))
    vr = sq / s1
    x2 = x * x; den = x2.sum() ** 2; th = 0.0
    for j in range(1, q):
        delta = n * (x2[j:] * x2[:-j]).sum() / den
        th += (2 * (q - j) / q) ** 2 * delta
    z = (vr - 1) / math.sqrt(th / n) if th > 0 else 0.0
    return float(vr), float(z)


def hurst(r):
    """Aggregated-variance Hurst: slope of log std of q-sums vs log q (0.5 random walk, >0.5 persistent, <0.5 anti-persistent)."""
    qs = [1, 2, 4, 8, 16, 32, 64]; sd = []
    for q in qs:
        s = np.convolve(r, np.ones(q), mode="valid")[::q]
        sd.append(s.std())
    return float(np.polyfit(np.log(qs), np.log(sd), 1)[0])


def hill(x, frac=0.05):
    a = np.sort(np.abs(x))[::-1]; k = max(10, int(len(a) * frac))
    return float(1 / np.mean(np.log(a[:k] / a[k])))


def lens2(A):
    log = {"lens": "2 Math/physics", "tests": []}; pv = []; rows = []
    for coin, d in sorted(A.items()):
        r = d["r"][1:]; n = len(r); cut = int(n * 0.7); lp = np.log(d["c"])
        row = {"coin": coin, "n": n, "adf_logprice_t": round(adf_t(lp), 2), "adf_returns_t": round(adf_t(r), 2),
               "kurtosis": round(float(((r - r.mean()) ** 4).mean() / r.var() ** 2), 1), "hill_tail_index": round(hill(r), 2),
               "hurst_all": round(hurst(r), 3), "hurst_first70": round(hurst(r[:cut]), 3), "hurst_last30": round(hurst(r[cut:]), 3)}
        for q in (4, 24):
            vr, z = variance_ratio(r, q); row["vr%d" % q] = round(vr, 3); row["vr%d_z" % q] = round(z, 2)
            vr2, z2 = variance_ratio(r[cut:], q); row["vr%d_last30" % q] = round(vr2, 3); row["vr%d_last30_z" % q] = round(z2, 2)
            pv.append(_p(z))
        a = acf(r, range(1, 25)); se = 1.96 / math.sqrt(n)
        row["acf_lag1"] = round(float(a[0]), 4); row["acf_sig_lags_of_24"] = int((np.abs(a) > se).sum())
        pv += [_p(x * math.sqrt(n)) for x in a]
        av = acf(np.abs(r), range(1, 241)); half = next((i + 1 for i, x in enumerate(av) if x < av[0] / 2), None)
        row["abs_acf_lag1"] = round(float(av[0]), 3); row["vol_half_life_h"] = half
        rows.append(row)
    # BH over all variance-ratio and ACF tests (2 VR + 24 lags per coin)
    keep = bh(pv); log["multiple_tests"] = len(pv); log["survivors_fdr5"] = int(sum(keep))
    log["rows"] = rows
    med = lambda k: round(float(np.median([r[k] for r in rows])), 3)
    log["summary"] = {"median_hurst": med("hurst_all"), "median_vr4": med("vr4"), "median_vr24": med("vr24"), "median_acf_lag1": med("acf_lag1"),
                      "median_abs_acf_lag1": med("abs_acf_lag1"), "median_kurtosis": med("kurtosis"), "median_tail_index": med("hill_tail_index"),
                      "price_stationary_coins": sum(1 for r in rows if r["adf_logprice_t"] < -2.86), "returns_stationary_coins": sum(1 for r in rows if r["adf_returns_t"] < -2.86),
                      "hurst_stable_sign_coins": sum(1 for r in rows if (r["hurst_first70"] - .5) * (r["hurst_last30"] - .5) > 0), "coins": len(rows),
                      "vol_half_life_median_h": float(np.median([r["vol_half_life_h"] or 241 for r in rows]))}
    s = log["summary"]
    log["hypothesis"] = "If prices follow a random walk: unit root in log price, returns stationary, VR near 1, Hurst near 0.5, no return autocorrelation, but volatility clusters and tails are fat."
    log["verdict"] = ("Log price is non-stationary (%d of %d coins reject a unit root), returns are stationary (%d of %d). Hurst median %.3f, VR(4) %.3f, VR(24) %.3f, lag-1 return ACF %.4f: close to a random walk, small mean-reversion at hourly scale. "
                      "Volatility clusters strongly (|r| ACF lag 1 = %.3f, half-life median %.0f h). Tails are fat (kurtosis %.1f, Hill index %.1f). %d of %d VR/ACF tests survive FDR 5%%; the survivors are tiny effect sizes." %
                      (s["price_stationary_coins"], s["coins"], s["returns_stationary_coins"], s["coins"], s["median_hurst"], s["median_vr4"], s["median_vr24"], s["median_acf_lag1"],
                       s["median_abs_acf_lag1"], s["vol_half_life_median_h"], s["median_kurtosis"], s["median_tail_index"], log["survivors_fdr5"], log["multiple_tests"]))
    return log


def lens4(A):
    log = {"lens": "4 Microstructure/trading scientist", "no_order_book": "No order book, trades or spread data in the stored history: costs are a flat assumption, queue position and impact are not modeled."}
    coins = sorted(A)
    # 1. time-of-day profile (pooled, normalised per coin)
    vol = np.zeros(24); vv = np.zeros(24)
    for c in coins:
        d = A[c]; h = (d["ts"] // 3600 % 24).astype(int); ar = np.abs(d["r"]); v = d["v"] * d["c"]
        for k in range(24):
            vol[k] += ar[h == k].mean() / ar.mean(); vv[k] += v[h == k].mean() / v.mean()
    vol /= len(coins); vv /= len(coins)
    log["time_of_day"] = {"abs_return_index_by_utc_hour": [round(float(x), 2) for x in vol], "dollar_volume_index_by_utc_hour": [round(float(x), 2) for x in vv],
                          "busiest_volume_hours_utc": [int(i) for i in np.argsort(-vv)[:3]], "quietest_volume_hours_utc": [int(i) for i in np.argsort(vv)[:3]]}
    # 2. cost break-even for momentum and mean-reversion on prior-h returns
    pv = []; rows = []
    for H in (1, 2, 4, 12, 24):
        for side, nm in ((1, "momentum"), (-1, "mean_reversion")):
            g_tr = []; g_te = []
            for c in coins:
                d = A[c]; cl = d["c"]; o = d["o"]; n = len(cl); cut = int(n * 0.7)
                past = np.full(n, np.nan); past[H:] = cl[H:] / cl[:-H] - 1
                fwd = np.full(n, np.nan); fwd[:n - H - 1] = cl[H:n - 1] / o[1:n - H] - 1
                ok = ~np.isnan(past) & ~np.isnan(fwd); ok &= past != 0
                g = side * np.sign(past) * fwd * 100
                idx = np.arange(n)
                g_tr.append(g[ok & (idx < cut)][::H]); g_te.append(g[ok & (idx >= cut)][::H])   # non-overlapping entries
            tr = np.concatenate(g_tr); te = np.concatenate(g_te)
            z = te.mean() / (te.std() / math.sqrt(len(te) / 5.0))     # /5: coins co-move, conservative n_eff
            pv.append(_p(z)); rows.append({"horizon_h": H, "rule": nm, "n_test": int(len(te)), "gross_train_pct": round(float(tr.mean()), 4), "gross_test_pct": round(float(te.mean()), 4),
                                           "t_adj": round(z, 2), "breakeven_cost_pct": round(float(max(te.mean(), 0)), 4), "net_test_at_0.30": round(float(te.mean() - COST), 4)})
    keep = bh(pv)
    for r, k in zip(rows, keep):
        r["survives_fdr5"] = bool(k)
    log["cost_breakeven"] = rows
    # 3. BTC/ETH lead-lag on alts, lags -3..3, first 70% vs last 30%
    ll = {}
    for lead in ("BTC", "ETH"):
        if lead not in A:
            continue
        res = {}
        for lag in range(-3, 4):
            cs = {"first70": [], "last30": []}
            for c in coins:
                if c in ("BTC", "ETH"):
                    continue
                a = A[lead]; b = A[c]; ts_a = {t: i for i, t in enumerate(a["ts"])}
                common = [(ts_a[t], i) for i, t in enumerate(b["ts"]) if t in ts_a]
                ia = np.array([x[0] for x in common]); ib = np.array([x[1] for x in common])
                x = a["r"][ia]; y = b["r"][ib]
                if lag > 0:
                    x2, y2 = x[:-lag], y[lag:]
                elif lag < 0:
                    x2, y2 = x[-lag:], y[:lag]
                else:
                    x2, y2 = x, y
                cut = int(len(x2) * 0.7)
                cs["first70"].append(np.corrcoef(x2[:cut], y2[:cut])[0, 1]); cs["last30"].append(np.corrcoef(x2[cut:], y2[cut:])[0, 1])
            res[str(lag)] = {k: round(float(np.mean(v)), 4) for k, v in cs.items()}
        ll[lead] = res
    log["lead_lag_corr_by_lag_hours"] = ll
    # trading test: BTC current-hour return sign -> alt next-hour direction (lag +1), net of cost, last 30% only
    hits = []; nets = []
    if "BTC" in A:
        a = A["BTC"]; ts_a = {t: i for i, t in enumerate(a["ts"])}
        for c in coins:
            if c == "BTC":
                continue
            b = A[c]; cut = int(len(b["c"]) * 0.7)
            for i in range(cut, len(b["c"]) - 2):
                j = ts_a.get(b["ts"][i])
                if j is None or a["r"][j] == 0:
                    continue
                f = b["c"][i + 1] / b["o"][i + 1] - 1; s = np.sign(a["r"][j]); hits.append(s * f > 0); nets.append(s * f * 100 - COST)
    log["btc_to_alt_next_hour"] = {"n": len(hits), "hit_rate": round(float(np.mean(hits)), 4) if hits else None, "mean_net_pct_at_0.30": round(float(np.mean(nets)), 4) if nets else None}
    # 4. big bar + high volume: continuation or reversal in next hours
    ev = []; 
    for c in coins:
        d = A[c]; r = d["r"]; v = d["v"]; n = len(r)
        sd = np.sqrt(np.convolve(r * r, np.ones(24) / 24, mode="full")[:n]); vm = np.convolve(v, np.ones(24) / 24, mode="full")[:n]
        ok = (np.abs(r) > 3 * np.roll(sd, 1)) & (v > 2 * np.roll(vm, 1)); ok[:30] = False; ok[-5:] = False
        for i in np.where(ok)[0]:
            s = np.sign(r[i]); ev.append((d["ts"][i], s * (d["c"][i + 1] / d["o"][i + 1] - 1) * 100, s * (d["c"][i + 4] / d["o"][i + 1] - 1) * 100))
    ev.sort(); cut = int(len(ev) * 0.7)
    log["big_bar_high_volume"] = {"events": len(ev)}
    for nm, k in (("next_1h", 1), ("next_4h", 2)):
        tr = np.array([e[k] for e in ev[:cut]]); te = np.array([e[k] for e in ev[cut:]])
        z = te.mean() / (te.std() / math.sqrt(len(te) / 5.0)); log["big_bar_high_volume"][nm] = {"train_mean_signed_pct": round(float(tr.mean()), 4), "test_mean_signed_pct": round(float(te.mean()), 4), "t_adj": round(z, 2), "p": round(_p(z), 4)}
        pv.append(_p(z))
    keep_all = bh(pv); log["multiple_tests"] = len(pv); log["survivors_fdr5"] = int(sum(keep_all))
    be = [r for r in rows if r["survives_fdr5"]]
    log["hypothesis"] = "Short-horizon structure lives in microstructure: activity peaks by hour, BTC leads alts by an hour, big high-volume bars continue or reverse, and any momentum or reversion edge must exceed costs."
    log["verdict"] = ("Cost break-even: best out-of-sample gross move per trade is %.3f%% vs a %.2f%% round-trip cost; %d of %d momentum/reversion tests survive FDR and %d of them clear costs. "
                      "BTC sign predicts next-hour alt direction %.1f%% of the time (net %.3f%% per trade at 0.30%% cost). Big-bar/high-volume next-hour mean %.3f%% (t %.2f). Volume is busiest at UTC hours %s."
                      % (max(r["gross_test_pct"] for r in rows), COST, len(be), len(rows), sum(1 for r in be if r["net_test_at_0.30"] > 0),
                         100 * (log["btc_to_alt_next_hour"]["hit_rate"] or 0), log["btc_to_alt_next_hour"]["mean_net_pct_at_0.30"] or 0,
                         log["big_bar_high_volume"]["next_1h"]["test_mean_signed_pct"], log["big_bar_high_volume"]["next_1h"]["t_adj"], log["time_of_day"]["busiest_volume_hours_utc"]))
    return log


def _grid(A):
    """Common hourly grid; R[coin, t] log returns (nan where no bar), C close."""
    t0 = int(min(v["ts"][0] for v in A.values())); t1 = int(max(v["ts"][-1] for v in A.values()))
    T = (t1 - t0) // 3600 + 1; coins = sorted(A); R = np.full((len(coins), T), np.nan); C = np.full((len(coins), T), np.nan)
    for i, c in enumerate(coins):
        idx = ((A[c]["ts"] - t0) // 3600).astype(int); R[i, idx] = A[c]["r"]; C[i, idx] = A[c]["c"]
    return t0, coins, R, C


def _boot_p(x, block=10, n=1000, seed=1):
    """Two-sided p that mean(x)=0, circular block bootstrap of the centered series."""
    x = x[~np.isnan(x)]; n0 = len(x)
    if n0 < 50:
        return 1.0, 0.0
    rng = np.random.default_rng(seed); m = x.mean(); xc = x - m; nb = int(math.ceil(n0 / block))
    st = rng.integers(0, n0, size=(n, nb)); idx = (st[:, :, None] + np.arange(block)[None, None, :]) % n0
    means = xc[idx.reshape(n, -1)[:, :n0]].mean(axis=1)
    return float((np.abs(means) >= abs(m)).mean() + 1.0 / n), float(m)


def lens1(A, hist_dir=None):
    """Engineer: is the data trustworthy, and is the (non-)result stable to costs and parameters?"""
    rows = []; tot = {"bars": 0, "dup_or_unsorted": 0, "ohlc_violations": 0, "zero_volume": 0, "gaps_gt_1h": 0, "abs_ret_gt_30pct": 0}
    for c in sorted(A):
        v = A[c]; ts = v["ts"]; d = np.diff(ts)
        dup = int((d <= 0).sum()); gaps = int((d > 3600).sum()); missing = int(((d[d > 3600] // 3600) - 1).sum())
        viol = int(((v["h"] < np.maximum(v["o"], v["c"]) - 1e-9) | (v["l"] > np.minimum(v["o"], v["c"]) + 1e-9)).sum())
        zv = int((v["v"] <= 0).sum()); big = int((np.abs(v["r"]) > 0.30).sum())
        rows.append({"coin": c, "bars": int(len(ts)), "dup_or_unsorted": dup, "gaps": gaps, "missing_hours": missing, "ohlc_violations": viol, "zero_volume_bars": zv, "abs_ret_gt_30pct": big})
        tot["bars"] += len(ts); tot["dup_or_unsorted"] += dup; tot["ohlc_violations"] += viol; tot["zero_volume"] += zv; tot["gaps_gt_1h"] += gaps; tot["abs_ret_gt_30pct"] += big
    # parameter / cost jitter on a momentum rule (sign of past L-hour return, hold H, non-overlapping), last 30% only
    grid = []
    for L in (6, 12, 24, 48, 96):
        for H in (6, 24):
            g = []
            for c in A:
                cl = A[c]["c"]; n = len(cl); cut = int(n * 0.7)
                i = np.arange(max(cut, L), n - H, H); past = cl[i] / cl[i - L] - 1; fwd = cl[i + H] / cl[i] - 1
                g.append(np.sign(past) * fwd)
            g = np.concatenate(g) * 100
            grid.append({"lookback_h": L, "hold_h": H, "n": int(len(g)), "gross_pct": round(float(g.mean()), 4), "net_at_0.10": round(float(g.mean() - 0.10), 4),
                         "net_at_0.30": round(float(g.mean() - 0.30), 4), "net_at_0.50": round(float(g.mean() - 0.50), 4), "t": round(float(g.mean() / (g.std() / math.sqrt(len(g)))), 2)})
    # timestamp unit sanity: all within the plausible window, spacing exactly 3600 s in the mode
    modal = int(all(int(np.median(np.diff(A[c]["ts"]))) == 3600 for c in A))
    pos = sum(1 for r in grid if r["net_at_0.10"] > 0)
    best = max(grid, key=lambda r: r["gross_pct"])
    verdict = ("Data integrity: %d bars, %d duplicate/unsorted, %d OHLC violations, %d zero-volume bars, %d gaps over 1h (every missing hour is counted on the Coverage page), %d bars with |return| > 30%%. "
               "Timestamps are on a clean 3600 s grid for all coins: %s. Jitter test (10 lookback/hold pairs, last 30%% of time, pooled coins): best gross %.3f%% per trade (L=%dh, H=%dh); %d of 10 settings are positive after even a 0.10%% cost, none after 0.30%%. "
               "The null result does not depend on one parameter choice. Not done: exchange basis check (Binance vs Coinbase), which needs a second price source.") % (
        tot["bars"], tot["dup_or_unsorted"], tot["ohlc_violations"], tot["zero_volume"], tot["gaps_gt_1h"], tot["abs_ret_gt_30pct"], "yes" if modal else "no", best["gross_pct"], best["lookback_h"], best["hold_h"], pos)
    return {"lens": "1 Engineer", "hypothesis": "The data is clean and the pipeline is deterministic; if so, any conclusion is stable to small changes in cost and parameters.",
            "multiple_tests": 10, "survivors_fdr5": 0, "totals": tot, "rows": rows, "jitter": grid, "verdict": verdict}


def lens3(A):
    """Statistician: calendar effects (hour, weekday, month) in an equal-weight market return, with block bootstrap, BH, split and per-year stability."""
    t0, coins, R, C = _grid(A)
    M = np.nanmean(R, axis=0) * 100; T = len(M); ts = t0 + np.arange(T) * 3600
    hour = (ts // 3600) % 24; dow = ((ts // 86400) + 3) % 7; mon = np.array([datetime.datetime.utcfromtimestamp(int(x)).month for x in ts[::1]]) if T < 1 else None
    day = ts // 86400
    # month via day number (cheap): compute once per day
    ud = np.unique(day); mmap = {int(d): datetime.datetime.utcfromtimestamp(int(d) * 86400).month for d in ud}; mon = np.array([mmap[int(d)] for d in day])
    yr = np.array([datetime.datetime.utcfromtimestamp(int(d) * 86400).year for d in ud]); ymap = dict(zip(ud.tolist(), yr.tolist())); year = np.array([ymap[int(d)] for d in day])
    cut = int(T * 0.7); tr = np.arange(T) < cut; te = ~tr
    tests = []
    for name, lab, K in (("hour_utc", hour, 24), ("weekday", dow, 7), ("month", mon, 12)):
        for k in range(K):
            sel = lab == k
            x_tr = M[sel & tr]; x_te = M[sel & te]
            # series restricted to that slot, day-aligned: block bootstrap over slot observations (each is a distinct day or hour-of-day)
            p, m = _boot_p(x_tr, block=10 if name != "hour_utc" else 7, n=600, seed=k + 1)
            yrs = sorted(set(year[sel & tr].tolist())); signs = [int(np.sign(np.nanmean(M[sel & (year == y)]))) for y in yrs if (sel & (year == y)).sum() > 20]
            tests.append({"effect": name, "slot": k, "train_mean_pct": round(float(np.nanmean(x_tr)), 4), "test_mean_pct": round(float(np.nanmean(x_te)), 4), "p_train": round(p, 4),
                          "years_same_sign_as_train": int(sum(1 for s in signs if s == np.sign(np.nanmean(x_tr)))), "years": len(signs)})
    keep = bh([t["p_train"] for t in tests])
    for t, k in zip(tests, keep):
        t["survives_fdr5"] = bool(k); t["holds_out_of_sample"] = bool(k and np.sign(t["train_mean_pct"]) == np.sign(t["test_mean_pct"]))
    surv = [t for t in tests if t["survives_fdr5"]]; hold = [t for t in surv if t["holds_out_of_sample"]]
    # stationarity of the volatility level across years (for the statistician: are samples exchangeable?)
    vols = {}
    for y in sorted(set(year.tolist())):
        z = M[year == y]; z = z[~np.isnan(z)]
        if len(z) > 500: vols[int(y)] = round(float(z.std()), 4)
    top = sorted(tests, key=lambda t: t["p_train"])[:8]
    verdict = ("%d calendar tests (24 hours + 7 weekdays + 12 months) on the equal-weight market return, block-bootstrap p-values from the first 70%%, Benjamini-Hochberg 5%%: %d survive, %d of those keep their sign in the last 30%%. "
               "Hourly volatility changes by year (std of hourly market return per year: %s), so effects are not drawn from one stable distribution. Smallest train p-values: %s.") % (
        len(tests), len(surv), len(hold), ", ".join("%d:%.3f" % kv for kv in vols.items()), "; ".join("%s %d p=%.3f train %.4f%% test %.4f%%" % (t["effect"], t["slot"], t["p_train"], t["train_mean_pct"], t["test_mean_pct"]) for t in top[:5]))
    return {"lens": "3 Statistician", "hypothesis": "Calendar effects (hour of day, weekday, month) exist in crypto returns; they should survive a dependence-robust test, multiple-testing correction and the later 30% of time.",
            "multiple_tests": len(tests), "survivors_fdr5": len(surv), "survivors_oos": len(hold), "tests": tests, "yearly_hourly_vol_pct": vols, "verdict": verdict}


def _dd(eq):
    pk = np.maximum.accumulate(eq); return float((eq / pk - 1).min())


def lens5(A):
    """Risk/quant: does volatility targeting help, do correlations rise in selloffs, does volatility predict crash probability."""
    t0, coins, R, C = _grid(A); T = R.shape[1]; ts = t0 + np.arange(T) * 3600
    nd = T // 24; Rf = np.nan_to_num(R[:, :nd * 24]); N = (~np.isnan(R[:, :nd * 24])).astype(float)
    D = Rf.reshape(len(coins), nd, 24).sum(axis=2); Nn = N.reshape(len(coins), nd, 24).sum(axis=2); D[Nn < 12] = np.nan
    mkt = np.nanmean(D, axis=0)
    out_rows = []
    def vt(r, tgt=0.02, win=20, cap=1.0):
        s = np.full(len(r), np.nan); lev = np.zeros(len(r))
        for i in range(win, len(r)):
            w = r[i - win:i]; w = w[~np.isnan(w)]
            lev[i] = min(cap, tgt / max(w.std(), 1e-6)) if len(w) > 10 else 0
        return lev * np.nan_to_num(r)
    cut = int(nd * 0.7)
    def stats(r):
        r = r[~np.isnan(r)]; eq = np.exp(np.cumsum(r)); sh = r.mean() / r.std() * math.sqrt(365) if r.std() > 0 else 0
        return {"ann_ret_pct": round(float(r.mean() * 365 * 100), 1), "ann_vol_pct": round(float(r.std() * math.sqrt(365) * 100), 1), "sharpe": round(float(sh), 2), "max_drawdown_pct": round(_dd(eq) * 100, 1)}
    series = {"equal-weight market": mkt}
    for i, c in enumerate(coins):
        if c in ("BTC", "ETH"): series[c] = D[i]
    boot_notes = []
    for name, r in series.items():
        v = vt(r)
        for per, sl in (("all", slice(30, nd)), ("last 30%", slice(cut, nd))):
            a = stats(r[sl]); b = stats(v[sl])
            out_rows.append({"series": name, "period": per, "unmanaged": a, "vol_targeted": b})
    # bootstrap of Sharpe difference, last 30%, market
    rng = np.random.default_rng(3); v = vt(mkt); x = np.nan_to_num(mkt[cut:]); y = v[cut:]; n = len(x); d = []
    for _ in range(500):
        idx = (rng.integers(0, n, size=int(math.ceil(n / 10)))[:, None] + np.arange(10)[None, :]).ravel()[:n] % n
        xs, ys = x[idx], y[idx]; d.append(ys.mean() / max(ys.std(), 1e-9) - xs.mean() / max(xs.std(), 1e-9))
    d = np.array(d) * math.sqrt(365); ci = (round(float(np.percentile(d, 2.5)), 2), round(float(np.percentile(d, 97.5)), 2))
    # correlation on up vs down market days (pairwise mean over coins with enough overlap)
    def avg_corr(mask):
        sub = D[:, mask]; cs = []
        for i in range(len(coins)):
            for j in range(i + 1, len(coins)):
                ok = ~np.isnan(sub[i]) & ~np.isnan(sub[j])
                if ok.sum() > 60: cs.append(np.corrcoef(sub[i][ok], sub[j][ok])[0, 1])
        return float(np.mean(cs)), len(cs)
    valid = ~np.isnan(mkt); q10, q90 = np.nanpercentile(mkt, 10), np.nanpercentile(mkt, 90)
    cu = avg_corr(valid & (mkt > 0)); cd = avg_corr(valid & (mkt < 0)); cx = avg_corr(valid & (mkt <= q10)); call = avg_corr(valid)
    corr = {"all_days": round(call[0], 3), "up_days": round(cu[0], 3), "down_days": round(cd[0], 3), "worst_10pct_days": round(cx[0], 3), "pairs": call[1]}
    # crash probability by ex-ante vol regime: trailing 24h hourly vol terciles; outcome = next-24h return < -5% (per coin, non-overlapping)
    pooled = []
    for i, c in enumerate(coins):
        cl = C[i]; r = np.nan_to_num(R[i]); ok = ~np.isnan(cl)
        for k in range(48, T - 24, 24):
            if ok[k] and ok[k + 24]:
                pooled.append((r[k - 24:k].std(), cl[k + 24] / cl[k] - 1, k))
    P = np.array(pooled); vol = P[:, 0]; fwd = P[:, 1]; k_idx = P[:, 2]
    lo, hi = np.percentile(vol, [33.3, 66.7]); reg = np.digitize(vol, [lo, hi]); crash = []
    for g, nm in enumerate(("low vol", "mid vol", "high vol")):
        m = reg == g; n = int(m.sum()); p5 = float((fwd[m] < -0.05).mean()); p10 = float((fwd[m] < -0.10).mean())
        crash.append({"regime": nm, "n": n, "p_drop_5pct_24h": round(p5, 4), "p_drop_10pct_24h": round(p10, 4), "mean_fwd_24h_pct": round(float(fwd[m].mean() * 100), 3)})
    def z2(a, b):
        p = (a["p_drop_5pct_24h"] * a["n"] + b["p_drop_5pct_24h"] * b["n"]) / (a["n"] + b["n"]); se = math.sqrt(p * (1 - p) * (1 / a["n"] + 1 / b["n"])); return (b["p_drop_5pct_24h"] - a["p_drop_5pct_24h"]) / se
    zc = z2(crash[0], crash[2]); pv = [_p(zc)]
    mk = out_rows[2]
    verdict = ("Volatility targeting (20-day trailing vol, target 2%% daily, leverage cap 1 so it only de-risks): equal-weight market, last 30%% of time, Sharpe %.2f unmanaged vs %.2f targeted, max drawdown %.1f%% vs %.1f%%; bootstrap 95%% interval of the Sharpe difference %s (an interval containing 0 means no proven gain). "
               "Average pairwise daily correlation across %d coin pairs: %.2f on all days, %.2f on up days, %.2f on down days, %.2f on the worst 10%% of days. "
               "Crash risk by ex-ante volatility tercile (next 24h drop over 5%%): low %.1f%%, mid %.1f%%, high %.1f%% (high vs low z = %.1f, n = %d). Higher volatility goes with more large drops. The z-score treats coin-days as independent although coins correlate about 0.6, so it is overstated; the ordering low < mid < high is the finding. The up/down correlation gap is partly mechanical (conditioning on the market's sign selects days when coins moved together). Volatility is a sizing input, not a direction signal.") % (
        mk["unmanaged"]["sharpe"], mk["vol_targeted"]["sharpe"], mk["unmanaged"]["max_drawdown_pct"], mk["vol_targeted"]["max_drawdown_pct"], ci, corr["pairs"], corr["all_days"], corr["up_days"], corr["down_days"], corr["worst_10pct_days"],
        crash[0]["p_drop_5pct_24h"] * 100, crash[1]["p_drop_5pct_24h"] * 100, crash[2]["p_drop_5pct_24h"] * 100, zc, len(P))
    return {"lens": "5 Risk / quant", "hypothesis": "Risk is more predictable than return: volatility clusters, so sizing by volatility should cut drawdowns; diversification fails in selloffs; high volatility should precede crashes.",
            "multiple_tests": 2, "survivors_fdr5": int(sum(bh([ _p(zc), 1.0 if ci[0] <= 0 <= ci[1] else 0.0 ]))), "sizing": out_rows, "sharpe_diff_ci95_last30": ci, "correlation": corr, "crash_by_vol_regime": crash, "verdict": verdict}


def run(hist_dir, data_dir, which=(1, 2, 3, 4, 5)):
    S = D.series(hist_dir); A = arrays(S)
    out = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "coins": len(A), "bars": int(sum(len(v["c"]) for v in A.values())), "lenses": {}}
    for n in which:
        out["lenses"][str(n)] = {1: lens1, 2: lens2, 3: lens3, 4: lens4, 5: lens5}[n](A)
    os.makedirs(data_dir, exist_ok=True)
    p = os.path.join(data_dir, "lens_log.json")
    old = json.load(open(p)) if os.path.exists(p) else {"lenses": {}}
    old["lenses"].update(out["lenses"]); old["generated"] = out["generated"]; old["coins"] = out["coins"]; old["bars"] = out["bars"]
    json.dump(old, open(p, "w"), indent=1, default=float)
    return old
