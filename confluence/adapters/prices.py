"""Coinbase Exchange public candles (no key). 1-minute bars."""
from ._http import get
from .. import config

def fetch(con, coins=None, granularity=60):
    n = 0
    for c in coins or config.COINS:
        try:
            rows = get(f"https://api.exchange.coinbase.com/products/{config.PRODUCT[c]}/candles?granularity={granularity}")
        except Exception as e:
            print(f"prices {c}: {e}"); continue
        # Coinbase row: [time, low, high, open, close, volume]
        con.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?)",
                        [(c, r[0], r[3], r[2], r[1], r[4], r[5]) for r in rows])
        n += len(rows)
    con.commit(); return n

def order_book(sym, level=2):
    return get(f"https://api.exchange.coinbase.com/products/{config.PRODUCT[sym]}/book?level={level}")
