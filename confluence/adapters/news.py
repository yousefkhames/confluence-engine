"""Public RSS news (no key, no scraping behind logins). Timestamp = published time, millisecond precision where given."""
import re, hashlib, email.utils, xml.etree.ElementTree as ET
from .http import get
from .. import config, nlp

FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "TheBlock": "https://www.theblock.co/rss.xml",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
}

def fetch(con, feeds=None):
    n = 0
    for src, url in (feeds or FEEDS).items():
        try:
            root = ET.fromstring(get(url, as_json=False))
        except Exception as e:
            print(f"news {src}: {e}"); continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip(); link = it.findtext("link") or ""
            desc = re.sub("<[^>]+>", " ", it.findtext("description") or "")
            pub = it.findtext("pubDate")
            try: ts = email.utils.parsedate_to_datetime(pub).timestamp()
            except Exception: continue
            text = f"{title}. {desc[:300]}"
            sent, urg = nlp.score_text(text); cred = nlp.source_credibility(src)
            for c in nlp.mentions(text, config.COINS):
                con.execute("INSERT OR IGNORE INTO news VALUES(?,?,?,?,?,?,?,?,?)",
                            (hashlib.md5(f"{link}{c}".encode()).hexdigest(), ts, c, title, src, link, sent, urg, cred)); n += 1
    con.commit(); return n
