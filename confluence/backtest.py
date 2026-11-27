"""Quick Backtest / Replay. Works on a copy of the DB so the real signal log is never touched.
No look-ahead: wallet profiles are built only from events whose outcome was known at the split time."""
import sqlite3, json, random
from . import config, db
from .wallets import profile_wallets, cluster_entities, insider_scan
from .signals import scan, evaluate_outcomes, track_record, verify_chain
from .scoring import compute
from .market import regime

def _clone(con):
    mem = sqlite3.connect(":memory:"); mem.row_factory = sqlite3.Row
    con.backup(mem)
    return mem

def run(con, split_ts, end_ts, step_s=900, threshold=None, coins=None):
    mem = _clone(con)
    mem.execute("DELETE FROM signals"); mem.execute("DELETE FROM outcomes"); mem.execute("DELETE FROM weights")
    mem.execute("DELETE FROM wallets")
    profile_wallets(mem, until=split_ts); cluster_entities(mem); 
    # keep only history up to split for insider detection
    insider_scan(mem)
    t = split_ts
    emitted = []
    while t <= end_ts:
        emitted += scan(mem, t, threshold, coins)
        t += step_s
    n = evaluate_outcomes(mem, end_ts + max(config.HORIZONS.values()))
    rec = track_record(mem)
    ok, bad = verify_chain(mem)
    # random-direction baseline on the same entries
    rnd = random.Random(1); base_hits = 0; base_n = 0
    for s in mem.execute("SELECT * FROM outcomes o JOIN signals s ON s.id=o.signal_id WHERE o.horizon='1h'"):
        base_n += 1
        base_hits += 1 if (s["ret_pct"] > 0) == (rnd.random() < 0.5) else 0
    cost = 2 * (config.FEE_PCT + config.SLIPPAGE_PCT)
    net = mem.execute("SELECT AVG(CASE WHEN s.direction='LONG' THEN ret_pct ELSE -ret_pct END) a FROM outcomes o "
                      "JOIN signals s ON s.id=o.signal_id WHERE horizon='1h'").fetchone()["a"]
    return {"signals": len(emitted), "track_record": rec, "chain_valid": ok,
            "random_baseline_hit_rate_1h": round(base_hits / base_n, 3) if base_n else None,
            "avg_1h_directional_ret_pct": round(net, 3) if net is not None else None,
            "avg_1h_net_of_costs_pct": round(net - cost, 3) if net is not None else None,
            "cost_assumption_pct_roundtrip": cost, "threshold": threshold or config.SIGNAL_THRESHOLD,
            "disclaimer": "Paper analysis only. Not financial advice. Past performance does not predict results."}

def replay(con, symbol, center_ts, before_s=7200, after_s=7200, step_s=300):
    """Score timeline around a past event so a user can see how the engine read it."""
    mem = _clone(con)
    profile_wallets(mem, until=center_ts - before_s)
    out = []
    t = center_ts - before_s
    while t <= center_ts + after_s:
        s = compute(mem, symbol, t)
        out.append({"ts": t, "score": s["score"], "direction": s["direction"], "price": s["price"], "flags": s["flags"]})
        t += step_s
    return out
