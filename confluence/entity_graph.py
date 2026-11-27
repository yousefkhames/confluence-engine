"""W1 Wallet entity graph v2. Stdlib only, offline, analytics only.

Clusters addresses from public on-chain transfers (whale_tx) with explainable
heuristics. Every link carries a heuristic name and confidence; clusters are
hypotheses, never proof of identity. Nothing here executes trades or contacts anyone.

Assumed whale_tx columns (tx_hash, chain, ts, from_addr, to_addr, token, amount_usd);
ts is unix seconds. Missing columns are tolerated where possible.
"""
import sqlite3
from collections import defaultdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_links(
  a TEXT NOT NULL, b TEXT NOT NULL, heuristic TEXT NOT NULL,
  confidence REAL NOT NULL, evidence TEXT,
  PRIMARY KEY(a,b,heuristic));
CREATE TABLE IF NOT EXISTS entity_clusters(
  address TEXT PRIMARY KEY, cluster_id TEXT NOT NULL, cluster_size INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entity_trails(
  origin TEXT NOT NULL, hop INTEGER NOT NULL, address TEXT NOT NULL,
  kind TEXT NOT NULL, confidence REAL NOT NULL, tx_hash TEXT,
  PRIMARY KEY(origin,hop,address));
"""

# Public, well-known shared infrastructure must never merge wallets.
DEFAULT_HUBS = set()  # caller supplies exchange/bridge/router addresses (lowercase)

CONF = {"common_funder": 0.55, "sweep": 0.7, "bridge": 0.65, "peel": 0.5, "stealth": 0.4}


def init(con):
    con.executescript(SCHEMA)


def _norm(x):
    return x.strip().lower() if isinstance(x, str) else x


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _tx_table(con):
    r = con.execute("SELECT 1 FROM sqlite_master WHERE name='whale_tx_std'").fetchone()
    return "whale_tx_std" if r else "whale_tx"

def load_txs(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(whale_tx)")}
    if not cols:
        return []
    want = ["tx_hash", "chain", "ts", "from_addr", "to_addr", "token", "amount_usd"]
    sel = ", ".join(c if c in cols else "NULL AS " + c for c in want)
    out = []
    for r in con.execute("SELECT %s FROM %s" % (sel, _tx_table(con))):
        d = dict(zip(want, r))
        d["from_addr"], d["to_addr"] = _norm(d["from_addr"]), _norm(d["to_addr"])
        if d["from_addr"] and d["to_addr"] and d["from_addr"] != d["to_addr"]:
            out.append(d)
    out.sort(key=lambda d: (d["ts"] or 0))
    return out


def common_funder_links(txs, hubs, max_fanout=8, max_amount=None):
    """Wallets whose FIRST inbound transfer came from the same non-hub funder,
    where the funder has a small fan-out. Large fan-out suggests an exchange/airdrop."""
    first = {}
    for t in txs:
        first.setdefault(t["to_addr"], t)
    by_funder = defaultdict(list)
    for addr, t in first.items():
        f = t["from_addr"]
        if f in hubs or (max_amount and (t["amount_usd"] or 0) > max_amount):
            continue
        by_funder[f].append((addr, t))
    links = []
    for f, lst in by_funder.items():
        if 2 <= len(lst) <= max_fanout:
            conf = CONF["common_funder"] * (1.0 if len(lst) <= 4 else 0.8)
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    links.append((lst[i][0], lst[j][0], "common_funder", conf,
                                  "funder=%s tx=%s,%s" % (f, lst[i][1]["tx_hash"], lst[j][1]["tx_hash"])))
    return links


def sweep_links(txs, hubs, min_sources=3, window=7 * 86400):
    """>=3 single-purpose wallets (degree<=2) sending the same token to one non-hub
    collector in a window. Two senders to one recipient is too weak (could be payers)."""
    deg = defaultdict(int)
    for t in txs:
        deg[t["from_addr"]] += 1
        deg[t["to_addr"]] += 1
    by_dst = defaultdict(list)
    for t in txs:
        if deg[t["from_addr"]] <= 2 and t["to_addr"] not in hubs and t["from_addr"] not in hubs:
            by_dst[(t["to_addr"], t["token"])].append(t)
    links = []
    for (dst, tok), lst in by_dst.items():
        srcs = {}
        for t in lst:
            srcs.setdefault(t["from_addr"], t)
        ts = [t["ts"] or 0 for t in srcs.values()]
        if len(srcs) >= min_sources and max(ts) - min(ts) <= window and len(srcs) <= 10:
            s = sorted(srcs)
            for i in range(len(s)):
                links.append((s[i], dst, "sweep", CONF["sweep"], "token=%s" % tok))
    return links


def bridge_links(txs, bridges, window=3600, tol=0.03):
    """Match a transfer into a bridge on chain A with a transfer out of a bridge on
    chain B: similar usd amount (fee tolerance), later within window, different chain.
    Ambiguous matches (more than one candidate) are dropped, not guessed."""
    ins = [t for t in txs if t["to_addr"] in bridges]
    outs = [t for t in txs if t["from_addr"] in bridges]
    links = []
    for i in ins:
        amt = i["amount_usd"] or 0
        if amt <= 0:
            continue
        cands = [o for o in outs
                 if o["chain"] != i["chain"] and o["token"] == i["token"]
                 and 0 <= (o["ts"] or 0) - (i["ts"] or 0) <= window
                 and amt * (1 - tol) <= (o["amount_usd"] or 0) <= amt * (1 + 1e-9)]
        if len(cands) == 1:
            o = cands[0]
            if o["to_addr"] != i["from_addr"]:
                links.append((i["from_addr"], o["to_addr"], "bridge",
                              CONF["bridge"], "in=%s out=%s" % (i["tx_hash"], o["tx_hash"])))
    return links


def peel_trail(txs, origin, hubs, max_hops=5, window=86400, min_keep=0.7):
    """Follow a withdrawal: origin sends to a fresh (few-tx) wallet which forwards most
    of the amount onward soon after. Returns list of (hop, address, kind, conf, tx_hash)."""
    outflow = defaultdict(list)
    degree = defaultdict(int)
    for t in txs:
        outflow[t["from_addr"]].append(t)
        degree[t["from_addr"]] += 1
        degree[t["to_addr"]] += 1
    trail, seen, cur, conf = [], {origin}, origin, 1.0
    for hop in range(1, max_hops + 1):
        nxt = None
        for t in sorted(outflow.get(cur, []), key=lambda d: d["ts"] or 0):
            a = t["to_addr"]
            if a in seen or a in hubs or degree[a] > 6:
                continue
            fwd = [u for u in outflow.get(a, []) if 0 <= (u["ts"] or 0) - (t["ts"] or 0) <= window
                   and (u["amount_usd"] or 0) >= min_keep * (t["amount_usd"] or 0)]
            if fwd:
                nxt = (a, t)
                break
        if not nxt:
            break
        a, t = nxt
        conf *= CONF["peel"] / 0.5 * 0.8
        trail.append((hop, a, "peel", round(conf, 3), t["tx_hash"]))
        seen.add(a)
        cur = a
    return trail


def stealth_candidates(txs, origin, hubs, window=1800, tol=0.05):
    """Single-use fresh wallets receiving ~equal amounts from origin within a short
    window (splitting to dodge tracking). Low confidence, flagged as hypothesis."""
    degree = defaultdict(int)
    for t in txs:
        degree[t["to_addr"]] += 1
        degree[t["from_addr"]] += 1
    outs = [t for t in txs if t["from_addr"] == origin and t["to_addr"] not in hubs
            and degree[t["to_addr"]] <= 3]
    res = []
    for i, a in enumerate(outs):
        peers = [b for b in outs if b is not a and abs((b["ts"] or 0) - (a["ts"] or 0)) <= window
                 and a["amount_usd"] and abs(b["amount_usd"] - a["amount_usd"]) <= tol * a["amount_usd"]]
        if peers:
            res.append(a)
    return res


def build(con, hubs=None, bridges=None, trail_origins=None):
    """Compute links, clusters, trails; persist. Returns summary dict."""
    init(con)
    hubs = {_norm(h) for h in (hubs or DEFAULT_HUBS)}
    bridges = {_norm(b) for b in (bridges or set())}
    hubs |= bridges
    txs = load_txs(con)
    links = (common_funder_links(txs, hubs) + sweep_links(txs, hubs)
             + bridge_links(txs, bridges))
    origins = [_norm(o) for o in (trail_origins or [])]
    trails = []
    for o in origins:
        for hop, a, kind, c, h in peel_trail(txs, o, hubs):
            trails.append((o, hop, a, kind, c, h))
            links.append((o, a, "peel", c, "hop=%d tx=%s" % (hop, h)))
        for t in stealth_candidates(txs, o, hubs):
            trails.append((o, 1, t["to_addr"], "stealth", CONF["stealth"], t["tx_hash"]))
            links.append((o, t["to_addr"], "stealth", CONF["stealth"], "tx=%s" % t["tx_hash"]))
    uf = UnionFind()
    with con:
        con.execute("DELETE FROM entity_links")
        con.execute("DELETE FROM entity_clusters")
        con.execute("DELETE FROM entity_trails")
        for a, b, h, c, ev in links:
            con.execute("INSERT OR REPLACE INTO entity_links VALUES(?,?,?,?,?)", (a, b, h, c, ev))
            uf.find(a); uf.find(b)
            if c >= 0.45:  # stealth (0.4) is shown but never merges clusters
                uf.union(a, b)
        groups = defaultdict(list)
        for x in list(uf.p):
            groups[uf.find(x)].append(x)
        for root, mem in groups.items():
            for m in mem:
                con.execute("INSERT OR REPLACE INTO entity_clusters VALUES(?,?,?)",
                            (m, "ent_" + root[:12], len(mem)))
        for t in trails:
            con.execute("INSERT OR REPLACE INTO entity_trails VALUES(?,?,?,?,?,?)", t)
    return {"links": len(links), "clusters": sum(1 for g in groups.values() if len(g) > 1),
            "trails": len(trails)}


def cluster_of(con, address):
    r = con.execute("SELECT cluster_id, cluster_size FROM entity_clusters WHERE address=?",
                    (_norm(address),)).fetchone()
    return r


def entity_activity(con, address, since_ts=0):
    """Aggregate whale_tx usd flow for the whole cluster of address (for scoring).
    Returns {'cluster_id','size','inflow_usd','outflow_usd','n_tx'}."""
    c = cluster_of(con, address)
    members = [address.lower()] if not c else [r[0] for r in con.execute(
        "SELECT address FROM entity_clusters WHERE cluster_id=?", (c[0],))]
    ph = ",".join("?" * len(members))
    inf = con.execute("SELECT COALESCE(SUM(amount_usd),0),COUNT(*) FROM " + _tx_table(con) + " WHERE lower(to_addr) IN (%s) AND ts>=?" % ph,
                      members + [since_ts]).fetchone()
    out = con.execute("SELECT COALESCE(SUM(amount_usd),0),COUNT(*) FROM " + _tx_table(con) + " WHERE lower(from_addr) IN (%s) AND ts>=?" % ph,
                      members + [since_ts]).fetchone()
    return {"cluster_id": c[0] if c else None, "size": len(members),
            "inflow_usd": inf[0], "outflow_usd": out[0], "n_tx": inf[1] + out[1]}


def run(con=None, **kw):
    if con is None:
        from confluence import db  # core module, supplied by integrator
        con = db.connect()
    return build(con, **kw)
