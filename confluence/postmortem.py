"""Win AND loss attribution for every logged signal: what was the setup, how did it play out, why."""
import json
from .market import price_at, volatility_pct
from . import config

def post_mortem(con, signal_id, horizon="1h"):
    s = con.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    o = con.execute("SELECT * FROM outcomes WHERE signal_id=? AND horizon=?", (signal_id, horizon)).fetchone()
    if not s or not o: return None
    f = json.loads(s["factors"]); flags = json.loads(s["flags"]); sign = 1 if s["direction"] == "LONG" else -1
    ret = o["ret_pct"] * sign
    vol = volatility_pct(con, s["symbol"], s["ts"])
    causes = []
    if o["hit"]:
        lead = max(f, key=lambda k: f[k] * sign)
        causes.append(f"Win: strongest supporting factor was {lead} ({f[lead]:+.2f}).")
        if abs(ret) < s["net_edge_pct"] * 0 + 0.3: causes.append("Win was smaller than round-trip costs, so not tradable in practice.")
    else:
        wrong = [k for k, v in f.items() if v * sign > 0.15]
        opp = [k for k, v in f.items() if v * sign < -0.15]
        if opp: causes.append(f"Loss: factors that disagreed at entry were ignored: {', '.join(opp)}.")
        if wrong: causes.append(f"Factors that were wrong this time: {', '.join(wrong)}.")
        for fl in flags:
            if fl.split(":")[0] in ("MANIPULATION_WARNING", "TOO_LATE", "REGIME_CHOPPY", "MACRO_AGAINST", "NET_EDGE_LOW"):
                causes.append(f"Warning present at entry: {fl.split(':')[0]}.")
        if abs(o["ret_pct"]) <= vol: causes.append("Move was within normal volatility: likely noise, not a thesis failure.")
        elif not causes: causes.append("Price moved against the signal beyond normal volatility with no flagged warning: unexplained, review data.")
    return {"signal_id": signal_id, "symbol": s["symbol"], "direction": s["direction"], "score": s["score"],
            "setup": s["reason"], "horizon": horizon, "directional_return_pct": round(ret, 3), "won": bool(o["hit"]),
            "flags_at_entry": flags, "causes": causes}

def all_post_mortems(con, horizon="1h"):
    return [pm for r in con.execute("SELECT id FROM signals ORDER BY id") if (pm := post_mortem(con, r["id"], horizon))]
