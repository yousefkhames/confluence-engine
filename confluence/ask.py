"""Ask the Engine: rule-based Q&A over the local database. Answers cite numbers, tx hashes and news timestamps.
(An LLM can be put in front of this, but it must call these same queries so answers stay grounded.)"""
import re, time, datetime
from . import config, nlp
from .market import price_at

def _t(ts): return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")

def answer(con, q):
    now = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"] or time.time()
    ql = q.lower(); coins = nlp.mentions(q, config.COINS)
    if coins and ("week" in ql or "أسبوع" in q or "month" in ql or "شهر" in q):   # rollup-backed, no raw scans
        from . import rollups
        rollups.init(con); d = 30 if ("month" in ql or "شهر" in q) else 7
        rows = con.execute("SELECT * FROM daily_summary WHERE symbol=? ORDER BY day DESC LIMIT ?", (coins[0], d)).fetchall()
        if rows:
            b = sum(r["buy_usd"] for r in rows); s_ = sum(r["sell_usd"] for r in rows)
            return (f"{coins[0]} last {len(rows)} days: whale buys ${b/1e6:.1f}M vs sells ${s_/1e6:.1f}M, "
                    f"{sum(r['news_n'] for r in rows)} news items, {sum(r['signals_n'] for r in rows)} signals "
                    f"({sum(r['hits_1h'] for r in rows)}/{sum(r['resolved_1h'] for r in rows)} correct at 1h).")
    if ("silent" in ql or "quiet" in ql or "بدون" in q or "صمت" in q) and not coins:
        rows = con.execute("SELECT symbol, SUM(usd) u, COUNT(*) n FROM whale_tx WHERE kind='from_exchange' AND ts>? GROUP BY symbol ORDER BY u DESC", (now - 21600,)).fetchall()
        out = []
        for r in rows:
            nn = con.execute("SELECT COUNT(*) c FROM news WHERE symbol=? AND ts>?", (r["symbol"], now - 21600)).fetchone()["c"]
            if nn == 0: out.append(f"{r['symbol']}: ${r['u']/1e6:.1f}M from exchanges across {r['n']} tx, no news in 6h")
        return "Whales buying quietly (6h):\n" + ("\n".join(out[:5]) or "none found")
    if coins and ("why" in ql or "لي" in q or "dump" in ql or "drop" in ql or "نزل" in q):
        c = coins[0]; p0, p1 = price_at(con, c, now - 300), price_at(con, c, now)
        mv = (p1 / p0 - 1) * 100 if p0 and p1 else 0
        tx = con.execute("SELECT * FROM whale_tx WHERE symbol=? AND ts>? ORDER BY ts DESC LIMIT 3", (c, now - 3600)).fetchall()
        nw = con.execute("SELECT * FROM news WHERE symbol=? AND ts>? ORDER BY ts DESC LIMIT 2", (c, now - 3600)).fetchall()
        lines = [f"{c} moved {mv:.2f}% in the last 5 minutes."]
        for t in tx: lines.append(f"Whale {t['kind']} ${t['usd']/1e6:.1f}M tx {t['txhash'][:16]} at {_t(t['ts'])}")
        for n in nw: lines.append(f"News '{n['title'][:80]}' ({n['source']}) at {_t(n['ts'])}, sentiment {n['sentiment']:.2f}")
        if not tx and not nw: lines.append("No whale or news event found in the last hour: likely noise or profit taking.")
        return "\n".join(lines)
    rows = con.execute("SELECT symbol, direction, score, reason FROM signals ORDER BY ts DESC LIMIT 5").fetchall()
    return "Latest signals:\n" + "\n".join(f"{r['symbol']} {r['direction']} {r['score']}: {r['reason']}" for r in rows) if rows else "No signals yet."
