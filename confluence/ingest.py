import time
from . import db
from .adapters import prices, news, social, onchain

def run_once(con):
    out = {"prices": prices.fetch(con)}
    for name, fn in (("news", lambda: news.fetch(con)), ("social", lambda: social.fetch(con)),
                     ("btc_whales", lambda: onchain.fetch_btc(con)), ("eth_whales", lambda: onchain.fetch_eth(con))):
        try: out[name] = fn()
        except Exception as e: out[name] = f"error: {e}"
    return out
