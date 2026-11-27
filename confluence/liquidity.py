"""Order-book absorption, estimated liquidation map, short-squeeze check, cross-exchange gap.
The liquidation map is an ESTIMATE from open interest and typical leverage tiers (real heatmaps need paid data)."""
from .adapters import prices as P
from .adapters._http import get
from .adapters import derivs

def book_absorption(sym, band_pct=0.5, book=None):
    b = book or P.order_book(sym)
    bids = [(float(p), float(q)) for p, q, *_ in b["bids"]]; asks = [(float(p), float(q)) for p, q, *_ in b["asks"]]
    mid = (bids[0][0] + asks[0][0]) / 2
    bd = sum(p * q for p, q in bids if p >= mid * (1 - band_pct / 100)); ad = sum(p * q for p, q in asks if p <= mid * (1 + band_pct / 100))
    imb = (bd - ad) / ((bd + ad) or 1)
    return {"mid": mid, "bid_depth_usd": round(bd), "ask_depth_usd": round(ad), "imbalance": round(imb, 3),
            "read": "bid wall absorbing sells" if imb > 0.3 else "ask wall capping price" if imb < -0.3 else "balanced"}

def liquidation_map(price, oi_usd, long_share=0.5, tiers=((5, .15), (10, .35), (25, .3), (50, .2))):
    """Estimated liquidation price levels and USD at risk per leverage tier (maintenance ~ 1/lev)."""
    out = []
    for lev, w in tiers:
        out.append({"leverage": lev, "long_liq_price": round(price * (1 - 1 / lev * 0.9), 4),
                    "short_liq_price": round(price * (1 + 1 / lev * 0.9), 4),
                    "long_usd": round(oi_usd * long_share * w), "short_usd": round(oi_usd * (1 - long_share) * w)})
    return out

def squeeze_check(funding_rate, sentiment_factor, whale_factor):
    """Spec: whales withdrawing from exchanges + very negative sentiment/crowded shorts -> short squeeze risk (contrarian long)."""
    crowded_short = funding_rate < 0 or sentiment_factor < -0.4
    return bool(crowded_short and whale_factor > 0.3 and sentiment_factor < -0.2)

def cross_exchange_gap(sym):
    """Coinbase vs Kraken spot gap in percent (CEX-CEX; DEX pools need an on-chain quote source)."""
    pair = {"BTC": "XBTUSD"}.get(sym, f"{sym}USD")
    k = get(f"https://api.kraken.com/0/public/Ticker?pair={pair}")["result"]
    kp = float(list(k.values())[0]["c"][0])
    cb = float(get(f"https://api.exchange.coinbase.com/products/{sym}-USD/ticker")["price"])
    return {"coinbase": cb, "kraken": kp, "gap_pct": round((cb / kp - 1) * 100, 4)}
