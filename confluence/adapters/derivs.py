"""Free public futures data (OKX): funding rate and open interest. Used for the squeeze/liquidation model."""
import time
from ._http import get
from .. import config

def funding_oi(sym):
    inst = f"{sym}-USDT-SWAP"
    f = get(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst}")["data"][0]
    o = get(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}")["data"][0]
    return {"funding_rate": float(f["fundingRate"]), "oi_usd": float(o["oiUsd"])}

def fetch(con, coins=None):
    con.execute("CREATE TABLE IF NOT EXISTS derivs_snap(symbol TEXT, ts REAL, funding_rate REAL, oi_usd REAL, PRIMARY KEY(symbol, ts))")
    n = 0
    for c in coins or config.COINS[:10]:
        try:
            d = funding_oi(c)
            con.execute("INSERT OR REPLACE INTO derivs_snap VALUES(?,?,?,?)", (c, time.time(), d["funding_rate"], d["oi_usd"])); n += 1
        except Exception as e:
            print(f"derivs {c}: {e}")
    con.commit(); return n
