"""Public Reddit RSS (Atom) feeds for sentiment. No login. X/Twitter and Telegram are NOT used: they need paid or
keyed access. Plug a licensed feed into `ingest_posts` if you have one."""
import re, hashlib, time, datetime, xml.etree.ElementTree as ET
from ._http import get
from .. import config, nlp

SUBS = ["CryptoCurrency", "Bitcoin", "ethereum", "solana", "CryptoMarkets"]
NS = {"a": "http://www.w3.org/2005/Atom"}

def ingest_posts(con, posts):
    """posts: dicts {id, ts, author, text, author_age_days, engagement}. Runs the bot filter, stores per coin."""
    posts = nlp.flag_bots(posts); n = 0
    for p in posts:
        sent, _ = nlp.score_text(p["text"])
        for c in nlp.mentions(p["text"], config.COINS):
            con.execute("INSERT OR IGNORE INTO social VALUES(?,?,?,?,?,?,?,?,?)",
                        (f"{p['id']}-{c}", p["ts"], c, p["author"], p["text"][:500], p.get("author_age_days"), sent,
                         p.get("engagement") or 0, p["is_bot"])); n += 1
    con.commit(); return n

def fetch(con, subs=None):
    posts = []
    for s in subs or SUBS:
        time.sleep(2)  # be polite: public endpoints rate-limit quickly
        try:
            root = ET.fromstring(get(f"https://www.reddit.com/r/{s}/new/.rss?limit=50", as_json=False))
        except Exception as e:
            print(f"reddit {s}: {e}"); continue
        for e in root.findall("a:entry", NS):
            title = e.findtext("a:title", "", NS); upd = e.findtext("a:updated", "", NS)
            try: ts = datetime.datetime.fromisoformat(upd.replace("Z", "+00:00")).timestamp()
            except Exception: ts = time.time()
            auth = (e.find("a:author/a:name", NS).text if e.find("a:author/a:name", NS) is not None else "?")
            posts.append({"id": hashlib.md5((e.findtext("a:id", "", NS)).encode()).hexdigest(), "ts": ts, "author": auth,
                          "text": title, "author_age_days": None, "engagement": 0})
    return ingest_posts(con, posts)
