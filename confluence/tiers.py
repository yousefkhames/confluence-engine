"""Subscription tiers as gating logic. Billing is not implemented (needs a payment provider); tokens are local."""
import secrets, time
from . import config

def issue_token(con, tier):
    assert tier in config.TIERS
    tok = secrets.token_hex(16)
    con.execute("INSERT INTO api_keys VALUES(?,?,?)", (tok, tier, time.time())); con.commit()
    return tok

def tier_for(con, token):
    if not token:
        return "free"
    r = con.execute("SELECT tier FROM api_keys WHERE token=?", (token,)).fetchone()
    return r["tier"] if r else "free"

def visible_signals(con, tier, now, limit=50):
    t = config.TIERS[tier]
    rows = con.execute("SELECT * FROM signals WHERE ts<=? ORDER BY ts DESC LIMIT ?", (now - t["delay_s"], limit * 4)).fetchall()
    coins = list(config.COINS)[: t["max_coins"]]
    return [r for r in rows if r["symbol"] in coins][:limit]
