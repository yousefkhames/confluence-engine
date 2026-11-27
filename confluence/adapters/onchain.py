"""Large transfers from free public sources: BTC via mempool.space, ETH via a free public JSON-RPC endpoint.
Direction needs address labels (data/labels.json, supplied by the operator; none are bundled so nothing is invented).
Without labels, transfers are stored as wallet_to_wallet and carry no directional weight."""
import time
from .http import get, post_json
from .. import config
from ..wallets import load_labels, classify_direction
from .prices import fetch as _p

ETH_RPC = "https://ethereum-rpc.publicnode.com"

def _last_price(con, sym):
    r = con.execute("SELECT close FROM prices WHERE symbol=? ORDER BY ts DESC LIMIT 1", (sym,)).fetchone()
    return r["close"] if r else None

def fetch_btc(con):
    px = _last_price(con, "BTC"); labels = load_labels(); n = 0
    if not px: return 0
    for t in get("https://mempool.space/api/mempool/recent"):
        usd = t.get("value", 0) / 1e8 * px
        if usd >= config.WHALE_USD_MIN:
            kind, wallet = "wallet_to_wallet", t["txid"][:12]
            con.execute("INSERT OR IGNORE INTO whale_tx VALUES(?,?,?,?,?,?,?,?)",
                        (t["txid"], time.time(), "BTC", "?", "?", usd, kind, None)); n += 1
    con.commit(); return n

def fetch_eth(con, blocks=5):
    px = _last_price(con, "ETH"); labels = load_labels(); n = 0
    if not px: return 0
    head = int(post_json(ETH_RPC, {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})["result"], 16)
    for b in range(head - blocks + 1, head + 1):
        blk = post_json(ETH_RPC, {"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": [hex(b), True]})["result"]
        ts = int(blk["timestamp"], 16)
        for tx in blk["transactions"]:
            usd = int(tx["value"], 16) / 1e18 * px
            if usd >= config.WHALE_USD_MIN and tx.get("to"):
                kind, wallet = classify_direction(tx["from"].lower(), tx["to"].lower(), {k.lower(): v for k, v in labels.items()})
                con.execute("INSERT OR IGNORE INTO whale_tx VALUES(?,?,?,?,?,?,?,?)",
                            (tx["hash"], ts, "ETH", tx["from"], tx["to"], usd, kind, wallet)); n += 1
    con.commit(); return n
