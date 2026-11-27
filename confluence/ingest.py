import time
from . import db
from .adapters import prices, news, social, onchain, social2, social_bridge, derivs, macro

def run_once(con, granularity=60):
    out = {"prices": prices.fetch(con, granularity=granularity)}
    for name, fn in (("news", lambda: news.fetch(con)), ("social", lambda: social.fetch(con)),
                     ("btc_whales", lambda: onchain.fetch_btc(con)), ("eth_whales", lambda: onchain.fetch_eth(con)),
                     ("social2", lambda: social2.fetch(con)), ("social_bridge", lambda: social_bridge.fetch(con)),
                     ("derivs", lambda: derivs.fetch(con)), ("macro", lambda: macro.fetch(con))):
        try: out[name] = fn()
        except Exception as e: out[name] = f"error: {e}"
    return out
