"""Workstream D4: public social sentiment sources for the Confluence engine.

Sources (all public, no login, no keys):
  - Reddit public RSS/Atom feeds (search.rss per query). NOTE: blocked from
    the current build sandbox; code kept, fetch errors are logged and skipped.
  - Hacker News via the Algolia API (hn.algolia.com), no auth.
  - Mastodon public tag timelines (mastodon.social/api/v1/timelines/tag),
    no auth. Carries a native per-account bot flag.
  - Telegram public channel preview pages (t.me/s/<channel>), no auth.

Every item gets a lexicon sentiment score in [-1, 1] and a heuristic
bot_score in [0, 1] (bot_flag when >= 0.5). Rows land in the workstream-owned
table social2_items; per-source fetch outcomes land in social2_fetch_log.

Stdlib only. Contract: init(con) creates tables; fetch(con) -> int (new rows).
"""

import json
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

USER_AGENT = "confluence-research/0.1 (+public sentiment adapter; no auth)"
ATOM = "{http://www.w3.org/2005/Atom}"

# ---------------------------------------------------------------------------
# Source configuration (override by passing config= to fetch)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "reddit_queries": ["bitcoin", "ethereum", "crypto market"],
    "hn_queries": ["bitcoin", "ethereum", "crypto"],
    "mastodon_tags": ["bitcoin", "crypto"],
    "telegram_channels": ["cointelegraph", "WatcherGuru"],
}

REDDIT_SEARCH_RSS = "https://www.reddit.com/search.rss?q={q}&sort=new"
HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=story&hitsPerPage=30"
MASTODON_TAG = "https://mastodon.social/api/v1/timelines/tag/{tag}?limit=40"
TELEGRAM_PREVIEW = "https://t.me/s/{channel}"

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS social2_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,             -- reddit_rss | hackernews | mastodon | telegram
    source_url TEXT NOT NULL,
    author TEXT,
    title TEXT,
    body TEXT,
    market TEXT,                      -- comma list of matched symbols, else CRYPTO
    sentiment REAL,                   -- -1..1 lexicon score
    bot_score REAL,                   -- 0..1 heuristic
    bot_flag INTEGER NOT NULL DEFAULT 0,
    engagement INTEGER,               -- points / views / fav+reblog+reply
    posted_at TEXT,
    fetched_at REAL NOT NULL,
    UNIQUE(source, source_url)
);
CREATE TABLE IF NOT EXISTS social2_fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    ok INTEGER NOT NULL,
    items INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    fetched_at REAL NOT NULL
);
"""


def init(con):
    """Create this workstream's tables. Idempotent."""
    con.executescript(_SCHEMA)
    con.commit()


# ---------------------------------------------------------------------------
# HTTP layer (module-level so tests can monkeypatch it)
# ---------------------------------------------------------------------------


def http_get(url, timeout=15):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def _quote(term):
    from urllib.parse import quote

    return quote(term, safe="")


# ---------------------------------------------------------------------------
# Sentiment lexicon (crypto-flavored, deliberately small and auditable)
# ---------------------------------------------------------------------------

_POSITIVE = [
    "bullish", "moon", "mooning", "pump", "breakout", "rally", "surge",
    "gain", "ath", "all time high", "profit", "green", "accumulate",
    "undervalued", "adoption", "record high", "soar",
]
_NEGATIVE = [
    "bearish", "dump", "crash", "scam", "rug", "rugpull", "ponzi", "fraud",
    "hack", "hacked", "exploit", "lawsuit", "liquidation", "liquidated",
    "red", "fear", "fud", "rekt", "plunge", "collapse", "capitulation",
    "ban", "seized", "insolvent",
]


def sentiment_score(text):
    """Lexicon sentiment in [-1, 1]; 0 when no lexicon hits."""
    t = " " + (text or "").lower() + " "
    pos = sum(t.count(" " + w) for w in _POSITIVE)
    neg = sum(t.count(" " + w) for w in _NEGATIVE)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


# ---------------------------------------------------------------------------
# Bot heuristics
# ---------------------------------------------------------------------------

_SPAM_PHRASES = [
    "giveaway", "airdrop", "free bitcoin", "double your", "guaranteed profit",
    "dm me", "whatsapp me", "join my", "signal group", "trading signals",
    "send me", "100x", "pump group",
]
_SHORTENERS = ("bit.ly", "tinyurl", "cutt.ly", "t.co/", "goo.gl", "is.gd")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]"
)


def bot_score(text, author=None, native_bot=False, url=""):
    """Heuristic bot/shill score in [0, 1]. native_bot is Mastodon's own flag."""
    score = 0.0
    t = (text or "").lower()
    score += 0.9 if native_bot else 0.0
    hits = sum(1 for p in _SPAM_PHRASES if p in t)
    score += min(0.5, hits * 0.25)
    if any(s in (url or "") or s in t for s in _SHORTENERS):
        score += 0.2
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) >= 20 and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        score += 0.15
    if len(_EMOJI_RE.findall(text or "")) > 8:
        score += 0.15
    if (text or "").count("!") > 3:
        score += 0.1
    if author and re.search(r"\d{5,}$", author):
        score += 0.1
    return round(min(1.0, score), 4)


# ---------------------------------------------------------------------------
# Market keyword mapping
# ---------------------------------------------------------------------------

_MARKETS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", " eth "],
    "SOL": ["solana", " sol "],
    "XRP": ["xrp", "ripple"],
    "DOGE": ["doge", "dogecoin"],
    "ADA": ["cardano", " ada "],
    "BNB": ["binance coin", " bnb "],
    "LTC": ["litecoin", " ltc "],
    "LINK": ["chainlink", " link "],
}


def detect_market(text):
    t = " " + (text or "").lower() + " "
    found = [sym for sym, words in _MARKETS.items() if any(w in t for w in words)]
    return ",".join(sorted(found)) if found else "CRYPTO"


# ---------------------------------------------------------------------------
# HTML stripping helper
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html):
    txt = _TAG_RE.sub(" ", html or "")
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
                 ("<br>", " ")):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


# ---------------------------------------------------------------------------
# Parsers (pure functions; take raw payload text, return item dicts)
# ---------------------------------------------------------------------------


def parse_reddit_rss(xml_text):
    items = []
    root = ET.fromstring(xml_text)
    for entry in root.findall(ATOM + "entry"):
        link_el = entry.find(ATOM + "link")
        url = link_el.get("href") if link_el is not None else None
        if not url:
            continue
        author_el = entry.find(ATOM + "author")
        items.append({
            "source": "reddit_rss",
            "source_url": url.split("?")[0],
            "author": (author_el.findtext(ATOM + "name") if author_el is not None else None),
            "title": entry.findtext(ATOM + "title") or "",
            "body": strip_html(entry.findtext(ATOM + "content") or ""),
            "engagement": None,
            "posted_at": entry.findtext(ATOM + "updated"),
        })
    return items


def parse_hn_search(json_text):
    data = json.loads(json_text)
    items = []
    for hit in data.get("hits", []):
        oid = hit.get("objectID")
        url = hit.get("url") or ("https://news.ycombinator.com/item?id=%s" % oid)
        items.append({
            "source": "hackernews",
            "source_url": url,
            "author": hit.get("author"),
            "title": hit.get("title") or "",
            "body": hit.get("story_text") or "",
            "engagement": hit.get("points"),
            "posted_at": hit.get("created_at"),
        })
    return items


def parse_mastodon_timeline(json_text):
    data = json.loads(json_text)
    items = []
    for st in data:
        account = st.get("account") or {}
        engagement = (st.get("favourites_count") or 0) + \
                     (st.get("reblogs_count") or 0) + \
                     (st.get("replies_count") or 0)
        items.append({
            "source": "mastodon",
            "source_url": st.get("url") or st.get("uri") or "",
            "author": account.get("acct"),
            "title": "",
            "body": strip_html(st.get("content") or ""),
            "engagement": engagement,
            "posted_at": st.get("created_at"),
            "native_bot": bool(account.get("bot")),
        })
    return [i for i in items if i["source_url"]]


class _TelegramPreviewParser(HTMLParser):
    """Extracts messages from a t.me/s/<channel> preview page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self._cur = None
        self._in_text = False
        self._in_views = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "div" and "tgme_widget_message_text" in cls and self._cur is not None:
            self._in_text = True
        elif tag == "div" and "tgme_widget_message" in cls and a.get("data-post"):
            if self._cur is not None:
                self._flush()
            self._cur = {"post": a["data-post"], "text": [], "views": None,
                         "datetime": None}
        elif tag == "time" and a.get("datetime") and self._cur is not None:
            self._cur["datetime"] = a["datetime"]
        elif tag == "span" and "tgme_widget_message_views" in cls and self._cur is not None:
            self._in_views = True

    def handle_endtag(self, tag):
        if tag == "div" and self._in_text:
            self._in_text = False
        if tag == "span" and self._in_views:
            self._in_views = False


    def handle_data(self, data):
        if self._in_text and self._cur is not None:
            self._cur["text"].append(data)
        elif self._in_views and self._cur is not None:
            self._cur["views"] = data.strip()

    def close(self):
        super().close()
        if self._cur is not None:
            self._flush()

    def _flush(self):
        c = self._cur
        self.items.append({
            "source": "telegram",
            "source_url": "https://t.me/" + c["post"],
            "author": c["post"].split("/")[0],
            "title": "",
            "body": re.sub(r"\s+", " ", " ".join(c["text"])).strip(),
            "engagement": _parse_views(c["views"]),
            "posted_at": c["datetime"],
        })
        self._cur = None


def _parse_views(txt):
    if not txt:
        return None
    m = re.match(r"([\d.]+)\s*([KkMm]?)", txt)
    if not m:
        return None
    n = float(m.group(1))
    mult = {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    return int(n * mult)


def parse_telegram_preview(html_text):
    p = _TelegramPreviewParser()
    p.feed(html_text)
    p.close()
    return p.items


# ---------------------------------------------------------------------------
# fetch(con) -> int
# ---------------------------------------------------------------------------


def _log(con, source, endpoint, ok, items, error=None):
    con.execute(
        "INSERT INTO social2_fetch_log (source, endpoint, ok, items, error, fetched_at)"
        " VALUES (?,?,?,?,?,?)",
        (source, endpoint, 1 if ok else 0, items, error, time.time()),
    )


def _insert_items(con, items):
    before = con.total_changes
    for it in items:
        text = (it.get("title") or "") + " " + (it.get("body") or "")
        bs = bot_score(text, author=it.get("author"),
                       native_bot=it.get("native_bot", False),
                       url=it.get("source_url", ""))
        con.execute(
            "INSERT OR IGNORE INTO social2_items"
            " (source, source_url, author, title, body, market, sentiment,"
            "  bot_score, bot_flag, engagement, posted_at, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                it["source"], it["source_url"], it.get("author"),
                it.get("title"), it.get("body"), detect_market(text),
                sentiment_score(text), bs, 1 if bs >= 0.5 else 0,
                it.get("engagement"), it.get("posted_at"), time.time(),
            ),
        )
    return con.total_changes - before


def _fetch_one(con, source, endpoint, parser):
    """Fetch + parse + insert one endpoint; never raises. Returns new row count."""
    try:
        payload = http_get(endpoint)
        items = parser(payload)
        n = _insert_items(con, items)
        _log(con, source, endpoint, True, n)
        return n
    except Exception as exc:  # network down, source blocked, parse error...
        _log(con, source, endpoint, False, 0, error="%s: %s" % (type(exc).__name__, exc))
        return 0


def fetch(con, config=None):
    """Pull all configured public social sources. Returns count of NEW rows.

    Per-source failures (e.g. Reddit RSS blocked from this sandbox) are logged
    to social2_fetch_log and skipped; they never abort the other sources.
    """
    cfg = config or DEFAULT_CONFIG
    init(con)
    total = 0
    for q in cfg.get("reddit_queries", []):
        total += _fetch_one(con, "reddit_rss", REDDIT_SEARCH_RSS.format(q=_quote(q)),
                            parse_reddit_rss)
    for q in cfg.get("hn_queries", []):
        total += _fetch_one(con, "hackernews", HN_SEARCH.format(q=_quote(q)),
                            parse_hn_search)
    for tag in cfg.get("mastodon_tags", []):
        total += _fetch_one(con, "mastodon", MASTODON_TAG.format(tag=_quote(tag)),
                            parse_mastodon_timeline)
    for ch in cfg.get("telegram_channels", []):
        total += _fetch_one(con, "telegram", TELEGRAM_PREVIEW.format(channel=_quote(ch)),
                            parse_telegram_preview)
    con.commit()
    return int(total)


def run():
    """Standalone entry point using the core database."""
    from confluence import db

    con = db.connect()
    try:
        n = fetch(con)
    finally:
        con.close()
    print("social2: inserted %d new items" % n)
    return n


if __name__ == "__main__":
    run()
