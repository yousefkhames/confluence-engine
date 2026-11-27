"""AI trade-setup & risk calculator: turns a signal into a 3-line paper plan. Output only, never an order."""
from .market import volatility_pct

def trade_setup(sig, vol_pct, paper_equity=10_000, risk_pct=1.0, book=None):
    px = sig["price"]; long = sig["direction"] == "LONG"
    stop_dist = max(vol_pct * 1.5, 0.4)             # percent
    entry = px
    if book and book.get("imbalance") is not None and abs(book["imbalance"]) > 0.3:
        entry = px * (1 - 0.001) if long else px * (1 + 0.001)   # lean on the wall, small improvement
    stop = entry * (1 - stop_dist / 100) if long else entry * (1 + stop_dist / 100)
    t1 = entry * (1 + 1.5 * stop_dist / 100) if long else entry * (1 - 1.5 * stop_dist / 100)
    t2 = entry * (1 + 3 * stop_dist / 100) if long else entry * (1 - 3 * stop_dist / 100)
    risk_usd = paper_equity * risk_pct / 100
    size_usd = risk_usd / (stop_dist / 100)
    if sig["regime"]["regime"] == "Choppy" or any(f.startswith("MACRO_AGAINST") for f in sig["flags"]):
        size_usd *= 0.5
    return {"line1": f"{sig['direction']} {sig['symbol']} ({sig['score']:.0f}% confluence)",
            "line2": f"Entry ~{entry:.4f}, stop {stop:.4f} ({stop_dist:.2f}% = volatility based)",
            "line3": f"Targets {t1:.4f} (1.5R) / {t2:.4f} (3R); paper size ${size_usd:,.0f} risking ${risk_usd:,.0f}",
            "size_usd": round(size_usd), "net_edge_pct": sig["net_edge_pct"], "paper_only": True}
