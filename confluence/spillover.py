"""Sector spillover: a leader moves on whale/news -> flag same-sector coins that have not moved yet (Laggard Catch-up)."""
from . import config
from .market import price_at

def laggards(con, leader, now, lookback_s=3600, lag_ratio=0.3):
    sector = next((s for s, m in config.SECTORS.items() if leader in m), None)
    if not sector: return []
    def ret(c):
        a, b = price_at(con, c, now - lookback_s), price_at(con, c, now)
        return (b / a - 1) * 100 if a and b else 0.0
    lr = ret(leader); out = []
    for c in config.SECTORS[sector]:
        if c == leader: continue
        r = ret(c)
        if abs(lr) >= 1.0 and (r * lr <= 0 or abs(r) < abs(lr) * lag_ratio):
            out.append({"symbol": c, "ret_pct": round(r, 2), "leader_ret_pct": round(lr, 2), "alert": "Laggard Catch-up candidate"})
    return out
