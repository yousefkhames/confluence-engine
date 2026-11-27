"""Copies social2_items (public HN/Mastodon/Telegram-preview/Reddit) into the `social` table the scorer reads,
one row per tracked coin mentioned. Keeps the bot score computed by social2."""
import hashlib, datetime
from .. import config, nlp

def _ts(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    try: return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception: return None

def fetch(con):
    try:
        rows = con.execute("SELECT * FROM social2_items").fetchall()
    except Exception:
        return 0
    n = 0
    for r in rows:
        text = ((r["title"] or "") + " " + (r["body"] or "")).strip()
        ts = _ts(r["posted_at"]) or r["fetched_at"]
        for c in nlp.mentions(text, config.COINS):
            cur = con.execute("INSERT OR IGNORE INTO social VALUES(?,?,?,?,?,?,?,?,?)",
                              (hashlib.md5(f"{r['source_url']}{c}".encode()).hexdigest(), ts, c, r["author"], text[:500], None,
                               r["sentiment"] if r["sentiment"] is not None else 0.0, r["engagement"] or 0, r["bot_score"] or 0))
            n += cur.rowcount
    con.commit(); return n
