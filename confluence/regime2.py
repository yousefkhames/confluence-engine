"""Regime v2: macro + cross-asset regime (research/analytics only, no execution).
regime(con) -> dict(label, score[-1..1], confidence[0..1], components, notes).
Reads macro_obs (adapters/macro.py). Pure stdlib. Heuristic, unvalidated: treat as context, not signal."""
import math, time
from datetime import date

def init(con):
    from .adapters import macro
    macro.init(con)

def series(con, name, source=None):
    q = "SELECT date, value FROM macro_obs WHERE series=?"
    a = [name]
    if source: q += " AND source=?"; a.append(source)
    return [(d, v) for d, v in con.execute(q + " ORDER BY date", a)]

def _clip(x, lo=-1.0, hi=1.0): return max(lo, min(hi, x))

def pct_change(s, n):
    if len(s) <= n or s[-1 - n][1] == 0: return None
    return s[-1][1] / s[-1 - n][1] - 1

def zscore(vals, window=252):
    v = vals[-window:]
    if len(v) < 30: return None
    m = sum(v) / len(v); sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
    return None if sd == 0 else (v[-1] - m) / sd

def corr(a, b):
    """Pearson correlation of two equal-length lists."""
    n = len(a)
    if n < 10 or n != len(b): return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
    if va == 0 or vb == 0: return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)

def returns_aligned(s1, s2, window=60):
    d2 = dict(s2); common = [(d, v, d2[d]) for d, v in s1 if d in d2]
    common = common[-(window + 1):]
    r1 = [common[i][1] / common[i-1][1] - 1 for i in range(1, len(common)) if common[i-1][1] and common[i-1][2]]
    r2 = [common[i][2] / common[i-1][2] - 1 for i in range(1, len(common)) if common[i-1][1] and common[i-1][2]]
    return r1, r2

def age_days(s, asof):
    if not s: return None
    y, m, d = map(int, s[-1][0].split("-"))
    return (asof - date(y, m, d)).days

# Each component returns (score in [-1,1] with +1 = risk-on/supportive for crypto, note) or None.
def c_vix(con):
    s = series(con, "VIX")
    if not s: return None
    v = s[-1][1]
    return _clip((20 - v) / 10), f"VIX {v:.1f}"

def c_credit(con):
    s = series(con, "HY_OAS")
    if len(s) < 30: return None
    z = zscore([v for _, v in s])
    return None if z is None else (_clip(-z / 2), f"HY OAS {s[-1][1]:.2f} z={z:.2f}")

def c_curve(con):
    s = series(con, "T10Y2Y")
    if not s: return None
    v = s[-1][1]
    return _clip(v / 1.0), f"10y-2y {v:.2f}"

def c_usd(con):
    s = series(con, "DXY")
    ch = pct_change(s, 20)
    if ch is None: return None
    return _clip(-ch / 0.03), f"broad USD 20d {ch*100:+.1f}%"

def c_liquidity(con):
    f = series(con, "FED_ASSETS"); b = series(con, "BOJ_ASSETS")
    parts = []; notes = []
    ch = pct_change(f, 13)  # weekly
    if ch is not None: parts.append(_clip(ch / 0.02)); notes.append(f"Fed assets 13w {ch*100:+.1f}%")
    ch = pct_change(b, 3)   # monthly
    if ch is not None: parts.append(_clip(ch / 0.02)); notes.append(f"BoJ assets 3m {ch*100:+.1f}%")
    if not parts: return None
    return sum(parts) / len(parts), "; ".join(notes)

def c_real_rates(con):
    s = series(con, "DGS10")
    ch = None if len(s) < 21 else s[-1][1] - s[-21][1]
    if ch is None: return None
    return _clip(-ch / 0.5), f"US10y 20d change {ch:+.2f}pp"

def c_yen_carry(con):
    """Fast yen strength = carry-unwind risk (risk-off). EURJPY 10d fall."""
    s = series(con, "EURJPY")
    ch = pct_change(s, 10)
    if ch is None: return None
    return _clip(ch / 0.03), f"EURJPY 10d {ch*100:+.1f}% (falling yen cross = unwind risk)"

def c_crypto_trend(con):
    s = series(con, "BTC")
    if len(s) < 60: return None
    px = [v for _, v in s]; ma = sum(px[-50:]) / 50
    ch30 = pct_change(s, 30) or 0
    sc = _clip(0.5 * (1 if px[-1] > ma else -1) + 0.5 * _clip(ch30 / 0.2))
    return sc, f"BTC {px[-1]:.0f} vs 50d MA {ma:.0f}, 30d {ch30*100:+.1f}%"

COMPONENTS = {  # name: (fn, weight)
    "vix": (c_vix, 1.5), "credit": (c_credit, 1.5), "curve": (c_curve, 0.5),
    "usd": (c_usd, 1.0), "liquidity": (c_liquidity, 1.0), "rates": (c_real_rates, 0.75),
    "yen_carry": (c_yen_carry, 0.75), "crypto_trend": (c_crypto_trend, 1.0),
}

def cross_asset(con, window=60):
    """Rolling return correlations: BTC vs SPX/NASDAQ/USD, ETH/BTC ratio trend."""
    out = {}
    btc = series(con, "BTC")
    for name in ("SPX", "NASDAQ", "DXY"):
        r1, r2 = returns_aligned(btc, series(con, name), window)
        c = corr(r1, r2)
        if c is not None: out[f"btc_{name.lower()}_corr"] = round(c, 3)
    eth = dict(series(con, "ETH"))
    ratio = [(d, v and eth[d] / v) for d, v in btc if d in eth and v]
    ch = pct_change(ratio, 30) if len(ratio) > 30 else None
    if ch is not None:
        out["eth_btc_30d"] = round(ch, 4)
        out["alt_risk_appetite"] = "rising" if ch > 0.05 else "falling" if ch < -0.05 else "flat"
    return out

def regime(con, asof=None):
    asof = asof or date.today()
    comps, notes, wsum, tot, stale = {}, [], 0.0, 0.0, []
    for name, (fn, w) in COMPONENTS.items():
        try: r = fn(con)
        except Exception as e: r = None; notes.append(f"{name} error: {e}")
        if r is None: notes.append(f"{name}: no data"); continue
        sc, note = r
        comps[name] = {"score": round(sc, 3), "weight": w, "note": note}
        wsum += w; tot += sc * w
    for n in ("VIX", "DXY", "BTC", "HY_OAS"):
        a = age_days(series(con, n), asof)
        if a is not None and a > 7: stale.append(f"{n} {a}d old")
    score = tot / wsum if wsum else 0.0
    cov = wsum / sum(w for _, w in COMPONENTS.values())
    conf = round(max(0.0, cov * (0.7 if stale else 1.0)), 2)
    vix = comps.get("vix", {}).get("score"); cr = comps.get("credit", {}).get("score")
    if vix is not None and cr is not None and vix < -0.6 and cr < -0.4: label = "stress"
    elif score > 0.25: label = "risk_on"
    elif score < -0.25: label = "risk_off"
    else: label = "neutral"
    if not comps: label, conf = "unknown", 0.0
    if stale: notes.append("stale: " + ", ".join(stale))
    return {"label": label, "score": round(score, 3), "confidence": conf, "components": comps,
            "cross_asset": cross_asset(con), "notes": notes, "asof": asof.isoformat(),
            "caveat": "Heuristic context, not validated or predictive. Paper research only."}

def confluence_input(con):
    """Compact (score, confidence) for the Confluence engine."""
    r = regime(con); return r["score"], r["confidence"], r["label"]
