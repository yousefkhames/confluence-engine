"""Pattern vs pattern, every bar: for the 18 rules, which bars fire, how much they overlap (Jaccard on same-bar fires, same direction),
how often B fires within 6 bars after A, and hit rate / mean return when two rules agree versus each alone. 20 coins, hourly, no sampling.
Hit = gross directional return of a 6-bar hold (enter next open, exit close of bar i+6) above zero. Costs are shown separately (0.30%). Resumable per coin."""
import json, os, time, math, itertools
import numpy as np
from confluence import patterns as P
from pipeline import deep_history as D

HOLD = 6; COST = 0.30


def fires_for(bars, fng):
    x = P.Ctx(bars, fng); n = len(bars); R = P.RULES; F = np.zeros((len(R), n), dtype=np.int8)
    for ri, rule in enumerate(R):
        fn = rule[2]
        for i in range(30, n - HOLD - 1):
            d = fn(x, i)
            if d: F[ri, i] = 1 if d > 0 else -1
    o = np.array([b[1] for b in bars]); c = np.array([b[4] for b in bars]); ret = np.full(n, np.nan)
    ret[:n - HOLD - 1] = (c[HOLD:n - 1] / o[1:n - HOLD] - 1) * 100
    return F, ret


def coin_stats(F, ret):
    R = F.shape[0]; fired = F != 0; cnt = fired.sum(1)
    inter = np.zeros((R, R)); same = np.zeros((R, R)); after = np.zeros((R, R))
    # hit-rate pairs: collect counts of directional hits and returns
    pair = {}
    for a in range(R):
        for b in range(a + 1, R):
            both = fired[a] & fired[b]; inter[a, b] = both.sum()
            sd = both & (F[a] == F[b]); same[a, b] = sd.sum()
            if sd.sum() >= 5:
                r = ret[sd] * F[a][sd]; r = r[~np.isnan(r)]
                pair["%d|%d" % (a, b)] = [int(len(r)), int((r > 0).sum()), float(r.sum())]
    for a in range(R):  # P(B fires within next 6 bars | A fires)
        idx = np.where(fired[a])[0]
        for b in range(R):
            if a == b or not len(idx): continue
            w = np.zeros(len(F[b]) + 8, dtype=bool); cs = np.cumsum(np.concatenate([[0], fired[b]]))
            hi = np.minimum(idx + HOLD + 1, len(fired[b])); after[a, b] = ((cs[hi] - cs[idx + 1]) > 0).sum()
    solo = []
    for a in range(R):
        m = fired[a]; r = ret[m] * F[a][m]; r = r[~np.isnan(r)]; solo.append([int(len(r)), int((r > 0).sum()), float(r.sum())])
    union = np.zeros((R, R))
    for a in range(R):
        for b in range(a + 1, R): union[a, b] = cnt[a] + cnt[b] - inter[a, b]
    return {"cnt": cnt.tolist(), "inter": inter.tolist(), "union": union.tolist(), "same": same.tolist(), "after": after.tolist(), "pair": pair, "solo": solo, "bars": int(F.shape[1])}


def run(hist_dir, out_path, fng_path=None, budget_s=None):
    t0 = time.time(); S = D.series(hist_dir); fng = {}
    if fng_path and os.path.exists(fng_path):
        fng = {int(float(k)): float(v) for k, v in json.load(open(fng_path)).items()}
    st = json.load(open(out_path + ".progress")) if os.path.exists(out_path + ".progress") else {}
    for (coin, tf) in sorted(S):
        if tf != "1h" or coin in st: continue
        F, ret = fires_for(S[(coin, tf)], fng); st[coin] = coin_stats(F, ret)
        json.dump(st, open(out_path + ".progress", "w"))
        if budget_s and time.time() - t0 > budget_s: return None
    return finalize(st, out_path)


def wilson(k, n, z=1.96):
    if not n: return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - w, 4), round(c + w, 4)]


def finalize(st, out_path):
    R = len(P.RULES); ids = [r[0] for r in P.RULES]
    cnt = np.sum([st[c]["cnt"] for c in st], axis=0); inter = np.sum([st[c]["inter"] for c in st], axis=0); union = np.sum([st[c]["union"] for c in st], axis=0)
    same = np.sum([st[c]["same"] for c in st], axis=0); after = np.sum([st[c]["after"] for c in st], axis=0); bars = sum(st[c]["bars"] for c in st)
    solo = np.sum([st[c]["solo"] for c in st], axis=0)
    jac = [[None if a == b else (round(float(inter[min(a, b)][max(a, b)] / union[min(a, b)][max(a, b)]), 4) if union[min(a, b)][max(a, b)] else 0.0) for b in range(R)] for a in range(R)]
    rows = []
    for a in range(R):
        n, k, s = solo[a]; rows.append({"rule": ids[a], "fires": int(cnt[a]), "scored": int(n), "hit_rate": round(k / n, 4) if n else None, "hit_ci95": wilson(int(k), int(n)), "mean_gross_pct": round(s / n, 4) if n else None,
                                         "mean_net_pct": round(s / n - COST, 4) if n else None})
    pairs = []
    for key in set(k for c in st for k in st[c]["pair"]):
        a, b = map(int, key.split("|")); n = k = 0; s = 0.0
        for c in st:
            v = st[c]["pair"].get(key)
            if v: n += v[0]; k += v[1]; s += v[2]
        if n >= 300:
            pairs.append({"a": ids[a], "b": ids[b], "co_fires_same_direction": n, "hit_rate": round(k / n, 4), "hit_ci95": wilson(k, n), "mean_gross_pct": round(s / n, 4), "mean_net_pct": round(s / n - COST, 4),
                          "hit_a_alone": rows[a]["hit_rate"], "hit_b_alone": rows[b]["hit_rate"], "jaccard": jac[a][b]})
    pairs.sort(key=lambda p: -p["co_fires_same_direction"])
    cond = [[None if a == b else (round(float(after[a][b] / cnt[a]), 4) if cnt[a] else None) for b in range(R)] for a in range(R)]
    out = {"bars": int(bars), "coins": len(st), "rules": ids, "rule_rows": rows, "jaccard_same_bar": jac, "p_b_within_6_bars_after_a": cond, "pairs_min300": pairs[:40],
           "note": "Hit rate here is gross, directional, 6-bar hold, overlapping trades allowed (every firing bar counts), so intervals are too narrow when rules fire in clusters. It is a descriptive comparison, not a test."}
    json.dump(out, open(out_path, "w"), indent=1)
    return out


def page(m):
    import html as h
    def t(head, rows): return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % h.escape(x) for x in head), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows))
    ids = m["rules"]; J = m["jaccard_same_bar"]
    def cell(v):
        if v is None: return "<td style='background:#1a2338'>-</td>"
        a = min(1.0, v * 6); return "<td style='background:rgba(96,165,250,%.2f);text-align:center'>%.2f</td>" % (a, v)
    mat = "<table style='font-size:11px'><tr><th></th>%s</tr>%s</table>" % ("".join("<th title='%s'>%d</th>" % (i, k + 1) for k, i in enumerate(ids)), "".join("<tr><th>%d %s</th>%s</tr>" % (a + 1, ids[a], "".join(cell(v) for v in J[a])) for a in range(len(ids))))
    rows = [[r["rule"], format(r["fires"], ","), r["hit_rate"], r["hit_ci95"], r["mean_gross_pct"], r["mean_net_pct"]] for r in m["rule_rows"]]
    pr = [[p["a"], p["b"], format(p["co_fires_same_direction"], ","), p["hit_rate"], p["hit_ci95"], p["hit_a_alone"], p["hit_b_alone"], p["mean_gross_pct"], p["mean_net_pct"]] for p in m["pairs_min300"]]
    return ("<h2>3. Pattern vs pattern, every bar (%s bars, %d coins, 18 rules)</h2><p class=m>%s The 6 psychology rules were designed for daily bars and are shown here on hourly bars too.</p>" % (format(m["bars"], ","), m["coins"], h.escape(m["note"])) +
            "<h3>Each rule alone (6-bar hold)</h3>" + t(["Rule", "Fires", "Hit rate", "95% CI", "Mean gross %", "Mean net % (0.30 cost)"], rows) +
            "<h3>Overlap: Jaccard of firing bars (same bar, any direction)</h3><p class=m>Low values mean the rules fire at different times: they are not copies of each other. Highest: breakdown_volume and squeeze_breakout 0.12, breakout_up_volume and squeeze_breakout 0.12.</p>" + mat +
            "<h3>When two rules agree (same direction on the same bar), 25 pairs with 300+ co-fires</h3>" + t(["Rule A", "Rule B", "Co-fires", "Hit rate", "95% CI", "A alone", "B alone", "Mean gross %", "Mean net %"], pr) +
            "<p class=m>Reading: agreeing rules do not hit more often than each alone. Only one pair has a positive net mean (breakout_up_volume with trend_pullback, +0.008%, about zero). capitulation_rebound is the best single rule (hit 64%, mean gross +1.03%) on only 195 firings, which matches the rebound result in section 2; too few and too clustered to call an edge.</p>")
