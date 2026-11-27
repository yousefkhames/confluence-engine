"""Paper-trading ledger, automated playbooks (rules -> paper action / webhook) and the Tilt Guard.
There is no exchange connection and no order placement code in this project."""
import json, time, sqlite3
from . import config

PLAYBOOKS = {
    "news_breakout": {"min_score": 70, "require_flags": ["UNPRICED_CATALYST"], "forbid_flags": ["TOO_LATE", "MANIPULATION_WARNING"],
                      "min_agree": 2, "desc": "Fresh credible news not yet priced, with confirmation from whales or sentiment."},
    "whale_reversal": {"min_score": 65, "require_flags": [], "forbid_flags": ["MANIPULATION_WARNING"], "min_agree": 2,
                       "min_whale": 0.5, "desc": "Smart-money accumulation after a sharp drop."},
    "insider_follow": {"min_score": 55, "require_flags": ["INSIDER_PATTERN"], "forbid_flags": ["MANIPULATION_WARNING"], "min_agree": 1,
                       "desc": "Wallets with a front-running history accumulating in silence."},
}

def init(con):
    con.execute("CREATE TABLE IF NOT EXISTS paper_trades(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, symbol TEXT, direction TEXT, "
                "price REAL, size_usd REAL, playbook TEXT, closed_ts REAL, close_price REAL, pnl_usd REAL)")
    con.commit()

def matches(sig, rule):
    f = sig["factors"]; sign = 1 if sig["direction"] == "LONG" else -1
    agree = sum(1 for v in f.values() if v * sign > 0.15)
    flags = " | ".join(sig["flags"])
    return (sig["score"] >= rule["min_score"] and agree >= rule.get("min_agree", 1)
            and all(r in flags for r in rule["require_flags"]) and not any(x in flags for x in rule["forbid_flags"])
            and abs(f["whale"]) >= rule.get("min_whale", 0))

def tilt_guard(con, sig_manip_penalty=0.0, now=None, window_s=3600):
    """Warn on overtrading (many paper trades in a window), size increases after a loss, or trading into high manipulation."""
    init(con); now = now or time.time()
    rows = con.execute("SELECT * FROM paper_trades WHERE ts>? ORDER BY ts", (now - window_s,)).fetchall()
    warns = []
    if len(rows) >= 5: warns.append(f"OVERTRADING: {len(rows)} paper trades in the last hour. Pause.")
    last2 = con.execute("SELECT * FROM paper_trades WHERE closed_ts IS NOT NULL ORDER BY ts DESC LIMIT 2").fetchall()
    if len(last2) == 2 and last2[0]["pnl_usd"] is not None and last2[0]["pnl_usd"] < 0 and last2[0]["size_usd"] > last2[1]["size_usd"]:
        warns.append("TILT: size was increased right after a loss.")
    if sig_manip_penalty >= 0.4 and rows: warns.append("High manipulation and you are still opening trades. Stop for now.")
    return warns

def paper_open(con, sig, setup, playbook=None):
    init(con)
    con.execute("INSERT INTO paper_trades(ts,symbol,direction,price,size_usd,playbook) VALUES(?,?,?,?,?,?)",
                (sig["ts"], sig["symbol"], sig["direction"], sig["price"], setup["size_usd"], playbook)); con.commit()

def run_playbooks(con, sig, setup, rules=None):
    """Returns the playbooks that fired. A fire writes a PAPER trade; a webhook, if configured, is a notification only."""
    fired = []
    for name, rule in (rules or PLAYBOOKS).items():
        if matches(sig, rule):
            if not tilt_guard(con, sig["penalty"], now=sig["ts"]):
                paper_open(con, sig, setup, name); fired.append(name)
    return fired

def paper_pnl(con):
    init(con)
    r = con.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) p FROM paper_trades WHERE closed_ts IS NOT NULL").fetchone()
    return {"closed": r["n"], "pnl_usd": round(r["p"], 2)}
