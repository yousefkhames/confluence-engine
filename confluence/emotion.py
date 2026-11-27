"""Crowd emotion as a measured number: fear (-100) to greed (+100).

Composite of six psychology proxies, all computed only from information known at the bar's close:
 RSI (momentum mood), distance from EMA50 (stretch), position in the 30-bar range (euphoria vs despair),
 volume-weighted candle direction (panic selling vs buying frenzy), Fear & Greed index (survey-style crowd mood),
 and drawdown from the 30-bar high (pain).
Live-only extras (funding rate, news and social sentiment) are shown but not used in the historical test, because
they have no long history. The honest question: does the composite predict later returns? `validate` answers it with
quantile buckets and a rank correlation, and says "no relationship" when that is what the data shows.
"""
import math
from .patterns import Ctx, ema_series


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def composite(x, i):
    """Return (score, parts) at bar i or None if not enough history. x is a patterns.Ctx."""
    if i < 55 or x.rsi[i] is None:
        return None
    hi30 = max(x.h[i - 29:i + 1]); lo30 = min(x.l[i - 29:i + 1])
    vavg = sum(x.v[i - 20:i]) / 20 or 1e-9
    direction = 1 if x.c[i] >= x.o[i] else -1
    parts = {
        "rsi": (x.rsi[i] - 50) / 50,
        "stretch": _clamp((x.c[i] / x.e50[i] - 1) / 0.25),
        "range_pos": 2 * ((x.c[i] - lo30) / ((hi30 - lo30) or 1e-9)) - 1,
        "volume_mood": direction * min(x.v[i] / vavg, 3) / 3,
        "pain": -_clamp((hi30 - x.c[i]) / hi30 / 0.3, 0, 1),
    }
    if x.f[i] is not None:
        parts["fear_greed"] = (x.f[i] - 50) / 50
    score = 100 * sum(parts.values()) / len(parts)
    return score, parts


def label(score):
    return ("Extreme fear" if score <= -60 else "Fear" if score <= -25 else "Neutral" if score < 25 else "Greed" if score < 60 else "Extreme greed")


def _rank(v):
    order = sorted(range(len(v)), key=lambda k: v[k]); r = [0.0] * len(v); i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    n = len(a)
    if n < 10:
        return None, None
    ra, rb = _rank(a), _rank(b); ma = sum(ra) / n; mb = sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)); va = sum((x - ma) ** 2 for x in ra); vb = sum((y - mb) ** 2 for y in rb)
    r = cov / math.sqrt(va * vb) if va and vb else 0.0
    t = r * math.sqrt((n - 2) / max(1e-9, 1 - r * r))
    return r, t


def validate(series, fng, horizons=(1, 3, 7), cost_pct=0.0):
    """series {(sym,'1d'): bars}. Pooled over coins. Returns per-horizon quintile table, correlation and extremes.
    Overlapping forward windows make samples dependent, so t-statistics are shown as a rough guide, divided by sqrt(h)."""
    rows = {h: [] for h in horizons}
    for (sym, tf), bars in series.items():
        if tf != "1d" or len(bars) < 120:
            continue
        x = Ctx(bars, fng)
        for i in range(55, len(bars) - max(horizons) - 1):
            c = composite(x, i)
            if not c:
                continue
            for h in horizons:
                entry = bars[i + 1][1]
                if entry > 0:
                    rows[h].append((bars[i][0], c[0], (bars[i + h][4] / entry - 1) * 100))
    out = {"method": "pooled daily bars, entry = next open, forward return after h bars", "horizons": {}}
    for h, r in rows.items():
        if len(r) < 200:
            out["horizons"][str(h)] = {"status": "insufficient data", "n": len(r)}; continue
        r.sort(key=lambda t: t[1]); n = len(r); q = []
        for k in range(5):
            part = r[k * n // 5:(k + 1) * n // 5]
            q.append({"bucket": k + 1, "score_range": [round(part[0][1], 1), round(part[-1][1], 1)], "n": len(part),
                      "mean_fwd_pct": round(sum(p[2] for p in part) / len(part), 3),
                      "up_rate": round(sum(1 for p in part if p[2] > 0) / len(part), 3)})
        rho, t = spearman([p[1] for p in r], [p[2] for p in r])
        eff_t = t / math.sqrt(h) if t is not None else None
        fear = [p[2] for p in r if p[1] <= -40]; greed = [p[2] for p in r if p[1] >= 40]
        ext = lambda v: {"n": len(v), "mean_fwd_pct": round(sum(v) / len(v), 3), "up_rate": round(sum(1 for z in v if z > 0) / len(v), 3)} if v else {"n": 0}
        half = r[0][0] + (max(p[0] for p in r) - r[0][0]) * 0.5
        a = [p for p in r if p[0] <= half]; b = [p for p in r if p[0] > half]
        r1, _ = spearman([p[1] for p in a], [p[2] for p in a]); r2, _ = spearman([p[1] for p in b], [p[2] for p in b])
        verdict = ("contrarian signal (fear -> higher returns), same sign in both halves" if rho is not None and rho < -0.03 and abs(eff_t) > 2.5 and r1 is not None and r2 is not None and r1 < 0 and r2 < 0 else
                   "momentum signal (greed -> higher returns), same sign in both halves" if rho is not None and rho > 0.03 and abs(eff_t) > 2.5 and r1 is not None and r2 is not None and r1 > 0 and r2 > 0 else
                   "no reliable relationship")
        out["horizons"][str(h)] = {"n": n, "spearman_rho": round(rho, 4), "t_adjusted": round(eff_t, 2), "rho_first_half": round(r1 or 0, 4),
                                   "rho_second_half": round(r2 or 0, 4), "quintiles": q, "fear_le_-40": ext(fear), "greed_ge_40": ext(greed), "verdict": verdict}
    return out


def snapshot(series, fng):
    """Current emotion per coin on the newest closed daily bar."""
    out = []
    for (sym, tf), bars in series.items():
        if tf != "1d" or len(bars) < 80:
            continue
        x = Ctx(bars, fng); c = composite(x, len(bars) - 1)
        if c:
            out.append({"symbol": sym, "score": round(c[0], 1), "label": label(c[0]), "parts": {k: round(v, 2) for k, v in c[1].items()}})
    out.sort(key=lambda d: d["score"])
    return out
