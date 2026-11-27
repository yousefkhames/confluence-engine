"""Free public futures data (OKX): funding rate and open interest. Used for the squeeze/liquidation model."""
from .http import get
def funding_oi(sym):
    inst = f"{sym}-USDT-SWAP"
    f = get(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst}")["data"][0]
    o = get(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}")["data"][0]
    return {"funding_rate": float(f["fundingRate"]), "oi_usd": float(o["oiUsd"])}
