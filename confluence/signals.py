"""Hash-chained signal log (tamper-evident), outcome tracking, dynamic weighting, alerts payload."""
import hashlib, json, time
from . import config
from .market import price_at
from .scoring import compute, explain, load_weights

GENESIS = "0" * 64

def _hash(prev, body):
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()

def _body(ts, symbol, direction, score, price, factors, flags):
    return {"ts": float(ts), "symbol": symbol, "direction": direction, "score": float(score), "price": float(price),
            "factors": {k: float(v) for k, v in factors.items()}, "flags": list(flags)}

def append_signal(con, sig):
    last = con.execute("SELECT hash FROM signals ORDER BY id DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else GENESIS
    body = _body(sig["ts"], sig["symbol"], sig["direction"], sig["score"], sig["price"], sig["factors"], sig["flags"])
    h = _hash(prev, body)
    cur = con.execute("INSERT INTO signals(ts,symbol,direction,score,price,reason,factors,flags,net_edge_pct,prev_hash,hash) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (sig["ts"], sig["symbol"], sig["direction"], sig["score"], sig["price"], explain(sig),
                       json.dumps(sig["factors"]), json.dumps(sig["flags"]), sig["net_edge_pct"], prev, h))
    con.commit()
    return cur.lastrowid, h

def verify_chain(con):
    prev = GENESIS
    for r in con.execute("SELECT * FROM signals ORDER BY id"):
        body = _body(r["ts"], r["symbol"], r["direction"], r["score"], r["price"], json.loads(r["factors"]), json.loads(r["flags"]))
        if r["prev_hash"] != prev or _hash(prev, body) != r["hash"]:
            return False, r["id"]
        prev = r["hash"]
    return True, None

def scan(con, now, threshold=None, coins=None):
    """Compute Confluence for each coin; log signals above the threshold (with per-coin cooldown)."""
    threshold = config.SIGNAL_THRESHOLD if threshold is None else threshold
    from .market import regime
    reg = regime(con, now=now); w = load_weights(con)
    emitted = []
    for c in coins or config.COINS:
        last = con.execute("SELECT ts FROM signals WHERE symbol=? ORDER BY ts DESC LIMIT 1", (c,)).fetchone()
        if last and now - last["ts"] < config.SIGNAL_COOLDOWN_S:
            continue
        sig = compute(con, c, now, w, reg)
        if sig["price"] and sig["score"] >= threshold:
            sid, h = append_signal(con, sig)
            sig["id"], sig["hash"] = sid, h
            emitted.append(sig)
    return emitted

def evaluate_outcomes(con, now):
    """After 15m/1h/4h/24h, record price change and whether the call was right."""
    n = 0
    for s in con.execute("SELECT * FROM signals").fetchall():
        for name, secs in config.HORIZONS.items():
            if s["ts"] + secs > now:
                continue
            if con.execute("SELECT 1 FROM outcomes WHERE signal_id=? AND horizon=?", (s["id"], name)).fetchone():
                continue
            p = price_at(con, s["symbol"], s["ts"] + secs, "before")
            if not p or not s["price"]:
                continue
            ret = (p / s["price"] - 1) * 100
            hit = 1 if (ret > 0) == (s["direction"] == "LONG") else 0
            con.execute("INSERT INTO outcomes VALUES(?,?,?,?,?)", (s["id"], name, p, ret, hit))
            n += 1
    con.commit()
    return n

def track_record(con):
    out = {}
    for name in config.HORIZONS:
        r = con.execute("SELECT COUNT(*) n, SUM(hit) h, AVG(CASE WHEN s.direction='LONG' THEN ret_pct ELSE -ret_pct END) avg "
                        "FROM outcomes o JOIN signals s ON s.id=o.signal_id WHERE horizon=?", (name,)).fetchone()
        out[name] = {"n": r["n"], "hit_rate": round(r["h"] / r["n"], 3) if r["n"] else None,
                     "avg_directional_ret_pct": round(r["avg"], 3) if r["avg"] is not None else None}
    return out

def reweight(con, horizon="1h", lr=0.3, min_n=20):
    """Dynamic weighting: factors that pointed the right way on logged signals gain weight."""
    rows = con.execute("SELECT s.factors, o.hit, s.direction FROM outcomes o JOIN signals s ON s.id=o.signal_id "
                       "WHERE o.horizon=?", (horizon,)).fetchall()
    if len(rows) < min_n:
        return None
    skill = {k: [0, 0] for k in config.DEFAULT_WEIGHTS}
    for r in rows:
        f = json.loads(r["factors"]); sign = 1 if r["direction"] == "LONG" else -1
        for k in skill:
            if f[k] * sign > 0.15:
                skill[k][0] += 1; skill[k][1] += r["hit"]
    w = load_weights(con); new = {}
    for k in w:
        n, h = skill[k]
        rate = (h + 1) / (n + 2)
        new[k] = max(0.05, w[k] * (1 + lr * (rate - 0.5) * 2))
    s = sum(new.values())
    new = {k: v / s for k, v in new.items()}
    for k, v in new.items():
        con.execute("INSERT INTO weights(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    con.commit()
    return new
