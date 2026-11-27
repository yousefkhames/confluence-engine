"""Explanations layer. For every logged signal (and paper trade), store a record of:
  WHAT  the setup: factors and their contributions, flags, regime
  HOW   the plan: entry, stop, targets, size (paper)
  WHERE the context: regime, sector, volatility, recent events
  WHY   the cause of the outcome, win or loss (filled once an outcome exists)
Aggregates show which factors/flags/regimes win or lose across the whole log."""
import json
from ..postmortem import post_mortem
from ..market import volatility_pct, regime
from ..setup import trade_setup
from .. import config

def init(con):
    con.execute("CREATE TABLE IF NOT EXISTS explanations(signal_id INTEGER PRIMARY KEY, what TEXT, how TEXT, where_ctx TEXT, "
                "why_1h TEXT, why_24h TEXT, won_1h INTEGER, updated REAL)")
    con.commit()

def _ctx(con, s):
    reg = regime(con, now=s["ts"]); sector = next((k for k, m in config.SECTORS.items() if s["symbol"] in m), None)
    return {"regime": reg["regime"], "er": reg["er"], "sector": sector, "vol_pct": round(volatility_pct(con, s["symbol"], s["ts"]), 3)}

def build_record(con, signal_id):
    init(con)
    s = con.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    if not s: return None
    f = json.loads(s["factors"]); flags = json.loads(s["flags"]); w = {k: v for k, v in config.DEFAULT_WEIGHTS.items()}
    what = {"reason": s["reason"], "factors": f, "contribution": {k: round(w[k] * f[k], 3) for k in f}, "flags": flags, "score": s["score"]}
    ctx = _ctx(con, s)
    sig_like = {"price": s["price"], "direction": s["direction"], "symbol": s["symbol"], "score": s["score"], "flags": flags,
                "net_edge_pct": s["net_edge_pct"], "regime": {"regime": ctx["regime"]}}
    how = trade_setup(sig_like, ctx["vol_pct"])
    why = {h: post_mortem(con, signal_id, h) for h in ("1h", "24h")}
    won = why["1h"]["won"] if why["1h"] else None
    import time
    con.execute("INSERT INTO explanations VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE SET what=excluded.what, how=excluded.how, "
                "where_ctx=excluded.where_ctx, why_1h=excluded.why_1h, why_24h=excluded.why_24h, won_1h=excluded.won_1h, updated=excluded.updated",
                (signal_id, json.dumps(what), json.dumps(how), json.dumps(ctx), json.dumps(why["1h"]), json.dumps(why["24h"]),
                 None if won is None else int(won), time.time()))
    con.commit()
    return {"what": what, "how": how, "where": ctx, "why": why}

def build_all(con):
    return sum(1 for r in con.execute("SELECT id FROM signals").fetchall() if build_record(con, r["id"]))

def attribution_summary(con):
    """Win rate by flag, by regime, by agreeing-factor count, using resolved 1h outcomes."""
    init(con); rows = con.execute("SELECT * FROM explanations WHERE won_1h IS NOT NULL").fetchall()
    by = {"flag": {}, "regime": {}, "agree": {}}
    for r in rows:
        what = json.loads(r["what"]); ctx = json.loads(r["where_ctx"]); won = r["won_1h"]
        def add(group, key):
            d = by[group].setdefault(key, [0, 0]); d[0] += 1; d[1] += won
        for fl in what["flags"]: add("flag", fl.split(":")[0])
        add("regime", ctx["regime"])
        add("agree", str(sum(1 for v in what["factors"].values() if abs(v) > 0.15)))
    return {g: {k: {"n": n, "win_rate": round(w / n, 3)} for k, (n, w) in d.items()} for g, d in by.items()}
