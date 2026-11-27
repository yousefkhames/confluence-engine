"""Wallet behavioural profiling (Smart Money score) and insider radar."""
import json, os, math
from .market import price_at

LABELS_FILE = os.environ.get("CONFLUENCE_LABELS", "data/labels.json")  # {"addr": "exchange:Name"}; user supplied

def load_labels():
    if os.path.exists(LABELS_FILE):
        try:
            return json.load(open(LABELS_FILE))
        except Exception:
            return {}
    return {}

def classify_direction(from_addr, to_addr, labels):
    f, t = labels.get(from_addr, ""), labels.get(to_addr, "")
    if t.startswith("exchange") and not f.startswith("exchange"):
        return "to_exchange", from_addr      # likely sell pressure
    if f.startswith("exchange") and not t.startswith("exchange"):
        return "from_exchange", to_addr      # likely accumulation
    return "wallet_to_wallet", from_addr

def profile_wallets(con, hit_pct=3.0, horizon_s=6 * 3600, min_calls=3, until=None):
    """Smart Money score from history: of the wallet's accumulation events, how often did price rise
    by hit_pct within the horizon. Bayesian shrinkage so 1-for-1 wallets do not score 100%.
    Market-maker heuristic: buys and sells of similar size, many events -> low weight."""
    txs = con.execute("SELECT * FROM whale_tx WHERE wallet IS NOT NULL AND ts<=? ORDER BY ts", (until if until else 9e12,)).fetchall()
    stats = {}
    for tx in txs:
        w = tx["wallet"]
        s = stats.setdefault(w, {"buy": 0, "sell": 0, "calls": 0, "hits": 0, "buy_usd": 0.0, "sell_usd": 0.0})
        if tx["kind"] == "from_exchange":
            s["buy"] += 1; s["buy_usd"] += tx["usd"]
            last = con.execute("SELECT MAX(ts) t FROM prices WHERE symbol=?", (tx["symbol"],)).fetchone()["t"] or 0
            if until:
                last = min(last, until)
            p0 = price_at(con, tx["symbol"], tx["ts"], "before")
            p1 = price_at(con, tx["symbol"], tx["ts"] + horizon_s, "before")
            if p0 and p1 and tx["ts"] + horizon_s <= last:   # only judge calls whose horizon has elapsed
                s["calls"] += 1
                if (p1 / p0 - 1) * 100 >= hit_pct:
                    s["hits"] += 1
        elif tx["kind"] == "to_exchange":
            s["sell"] += 1; s["sell_usd"] += tx["usd"]
    out = {}
    for w, s in stats.items():
        a, b = 1.0, 1.0  # prior: Beta(1,1)
        score = (s["hits"] + a) / (s["calls"] + a + b)
        total = s["buy"] + s["sell"]
        mm = total >= 10 and s["buy_usd"] and s["sell_usd"] and 0.7 < s["buy_usd"] / s["sell_usd"] < 1.4
        label = "market_maker" if mm else ("smart_money" if score >= 0.65 and s["calls"] >= min_calls else "whale")
        if mm:
            score = min(score, 0.3)
        out[w] = {"label": label, "smart_score": round(score, 3), "n_calls": s["calls"], "n_hits": s["hits"]}
        con.execute("INSERT INTO wallets(addr,label,smart_score,n_calls,n_hits) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(addr) DO UPDATE SET label=excluded.label, smart_score=excluded.smart_score, "
                    "n_calls=excluded.n_calls, n_hits=excluded.n_hits",
                    (w, label, out[w]["smart_score"], s["calls"], s["hits"]))
    con.commit()
    return out

def wallet_score(con, addr):
    r = con.execute("SELECT smart_score FROM wallets WHERE addr=?", (addr,)).fetchone()
    return r["smart_score"] if r else 0.5

def cluster_entities(con, window_s=600, min_links=2):
    """Phase 3 entity graph (simple): wallets that fund/move together. Links wallets that moved the same coin
    within window_s of each other at least min_links times; union-find into clusters."""
    rows = con.execute("SELECT wallet, symbol, ts FROM whale_tx WHERE wallet IS NOT NULL ORDER BY symbol, ts").fetchall()
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    links = {}
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if b["symbol"] != a["symbol"] or b["ts"] - a["ts"] > window_s:
                break
            if a["wallet"] != b["wallet"]:
                k = tuple(sorted((a["wallet"], b["wallet"])))
                links[k] = links.get(k, 0) + 1
    for (x, y), n in links.items():
        if n >= min_links:
            parent[find(x)] = find(y)
    groups = {}
    for w in {r["wallet"] for r in rows}:
        groups.setdefault(find(w), []).append(w)
    n = 0
    for root, members in groups.items():
        if len(members) > 1:
            n += 1
            for m in members:
                con.execute("UPDATE wallets SET cluster=? WHERE addr=?", (f"cluster-{n}", m))
    con.commit()
    return {f"cluster-{i+1}": m for i, m in enumerate([m for m in groups.values() if len(m) > 1])}

def insider_scan(con, news_lookahead_s=3600, smart_min=0.6):
    """Retro scan: smart wallets that accumulated a coin, then within lookahead a high-urgency positive news item
    appeared and price rose -> count an insider hit for the wallet. Returns wallets flagged (>=2 hits)."""
    buys = con.execute("SELECT * FROM whale_tx WHERE kind='from_exchange' AND wallet IS NOT NULL").fetchall()
    for tx in buys:
        sc = wallet_score(con, tx["wallet"])
        if sc < smart_min:
            continue
        n = con.execute("SELECT COUNT(*) c FROM news WHERE symbol=? AND ts>? AND ts<=? AND sentiment>0.3 AND urgency>=0.45",
                        (tx["symbol"], tx["ts"], tx["ts"] + news_lookahead_s)).fetchone()["c"]
        before = con.execute("SELECT COUNT(*) c FROM news WHERE symbol=? AND ts>? AND ts<=?",
                             (tx["symbol"], tx["ts"] - 7200, tx["ts"])).fetchone()["c"]
        if n and not before:   # bought in silence, news followed
            con.execute("UPDATE wallets SET insider_hits=insider_hits+1 WHERE addr=?", (tx["wallet"],))
    con.commit()
    return [r["addr"] for r in con.execute("SELECT addr FROM wallets WHERE insider_hits>=2")]

def is_insider(con, addr):
    r = con.execute("SELECT insider_hits FROM wallets WHERE addr=?", (addr,)).fetchone()
    return bool(r and r["insider_hits"] >= 2)
