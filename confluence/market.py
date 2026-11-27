"""Price helpers, Price-In ratio, market regime."""
import statistics

def _stride(rows, seconds):
    """Rows to skip to get roughly one sample per `seconds`. 1-minute bars: 60 for an hour; 5-minute bars: 12."""
    if len(rows) < 3:
        return 1
    ts = [r["ts"] for r in rows[: min(len(rows), 50)]]
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
    bar = gaps[len(gaps) // 2] if gaps else 60
    return max(1, int(round(seconds / max(bar, 1))))

def price_at(con, sym, ts, side="before"):
    if side == "before":
        r = con.execute("SELECT close FROM prices WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1", (sym, int(ts))).fetchone()
    else:
        r = con.execute("SELECT close FROM prices WHERE symbol=? AND ts>=? ORDER BY ts ASC LIMIT 1", (sym, int(ts))).fetchone()
    return r["close"] if r else None

def shock_impact(con, sym, ts, windows=(15, 60, 300)):
    """Price change % and volume after a timestamp, for each window (spec: 15s, 1m, 5m).
    Bars are 1 minute, so sub-minute windows resolve to the first bar."""
    p0 = price_at(con, sym, ts, "before")
    out = {}
    if not p0:
        return out
    for w in windows:
        p1 = price_at(con, sym, ts + max(w, 60), "before")
        vol = con.execute("SELECT COALESCE(SUM(volume),0) v FROM prices WHERE symbol=? AND ts>? AND ts<=?",
                          (sym, int(ts), int(ts + max(w, 60)))).fetchone()["v"]
        out[w] = {"ret_pct": (p1 / p0 - 1) * 100 if p1 else 0.0, "volume": vol}
    return out

def price_in_ratio(move_pct, expected_pct=1.5):
    """0 = nothing priced in yet, 1 = fully priced. Uses the absolute move vs an expected shock size."""
    return max(0.0, min(1.5, abs(move_pct) / expected_pct))

def regime(con, ref="BTC", now=None):
    """Risk-On / Risk-Off / Choppy from hourly-ish BTC action over 24h using an efficiency ratio."""
    now = now or con.execute("SELECT MAX(ts) t FROM prices WHERE symbol=?", (ref,)).fetchone()["t"]
    if not now:
        return {"regime": "Unknown", "er": None, "ret_pct": None, "conf_mult": 1.0}
    rows = con.execute("SELECT ts, close FROM prices WHERE symbol=? AND ts>? AND ts<=? ORDER BY ts",
                       (ref, int(now - 86400), int(now))).fetchall()
    closes = [r["close"] for r in rows][::_stride(rows, 3600)] or [r["close"] for r in rows]
    if len(closes) < 6:
        return {"regime": "Unknown", "er": None, "ret_pct": None, "conf_mult": 1.0}
    net = closes[-1] / closes[0] - 1
    path = sum(abs(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))) or 1e-9
    er = abs(net) / path
    if er < 0.25:
        reg, mult = "Choppy", 0.8
    elif net > 0:
        reg, mult = "Risk-On", 1.0
    else:
        reg, mult = "Risk-Off", 1.0
    return {"regime": reg, "er": round(er, 3), "ret_pct": round(net * 100, 2), "conf_mult": mult}

def volatility_pct(con, sym, now, hours=24):
    rows = con.execute("SELECT ts, close FROM prices WHERE symbol=? AND ts>? AND ts<=? ORDER BY ts",
                       (sym, int(now - hours * 3600), int(now))).fetchall()
    c = [r["close"] for r in rows][::_stride(rows, 900)]
    if len(c) < 5:
        return 1.0
    rets = [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
    return statistics.pstdev(rets) * 2  # rough expected 1h-ish move scale
