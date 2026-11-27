"""Offline tests for adapters/social2.py (Workstream D4).

No network: every test either calls the pure parsers with fixture payloads or
monkeypatches social2.http_get. DB tests use sqlite3 :memory:, which satisfies
the same DB-API surface as confluence.db.connect().
"""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from confluence.adapters import social2  # noqa: E402


# --------------------------------------------------------------------------
# Fixture payloads
# --------------------------------------------------------------------------

REDDIT_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Bitcoin breakout: BTC hits new ATH</title>
    <link href="https://www.reddit.com/r/CryptoCurrency/comments/abc123/bitcoin_breakout/?utm_source=rss"/>
    <author><name>/u/some_trader</name></author>
    <updated>2026-11-27T10:00:00+00:00</updated>
    <content type="html">&lt;p&gt;Bullish rally continues, green candles everywhere&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>ETH dump incoming? Fear and FUD everywhere</title>
    <link href="https://www.reddit.com/r/eth/comments/def456/eth_dump/"/>
    <author><name>/u/bear_case</name></author>
    <updated>2026-11-27T11:00:00+00:00</updated>
    <content type="html">&lt;p&gt;Crash risk, capitulation ahead&lt;/p&gt;</content>
  </entry>
</feed>
"""

HN_JSON = """{
  "hits": [
    {"objectID": "991", "title": "Bitcoin exchange insolvent after hack",
     "url": "https://example.com/hack-story", "author": "pg",
     "points": 512, "created_at": "2026-11-27T09:00:00.000Z", "story_text": null},
    {"objectID": "992", "title": "Show HN: self-hosted Bitcoin node dashboard",
     "url": null, "author": "maker42", "points": 87,
     "created_at": "2026-11-27T08:00:00.000Z", "story_text": "No login needed"}
  ]
}"""

MASTODON_JSON = """[
  {"id": "1", "created_at": "2026-11-27T07:00:00.000Z",
   "url": "https://mastodon.social/@alice/1",
   "content": "<p>Solana surge looks like a real breakout</p>",
   "replies_count": 2, "reblogs_count": 5, "favourites_count": 9,
   "account": {"acct": "alice", "bot": false}},
  {"id": "2", "created_at": "2026-11-27T07:05:00.000Z",
   "url": "https://mastodon.social/@newsbot/2",
   "content": "<p>Bitcoin price update</p>",
   "replies_count": 0, "reblogs_count": 1, "favourites_count": 1,
   "account": {"acct": "newsbot", "bot": true}}
]"""

TELEGRAM_HTML = """<!DOCTYPE html><html><body>
<section class="tgme_channel_history">
  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="cointelegraph/12345">
      <div class="tgme_widget_message_text js-message_text" dir="auto">Bitcoin ETF sees record inflows, bullish adoption signal</div>
      <div class="tgme_widget_message_info">
        <span class="tgme_widget_message_views">12.5K</span>
        <a class="tgme_widget_message_date" href="https://t.me/cointelegraph/12345">
          <time datetime="2026-11-27T06:30:00+00:00">06:30</time>
        </a>
      </div>
    </div>
  </div>
  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message" data-post="cointelegraph/12346">
      <div class="tgme_widget_message_text" dir="auto">Exchange exploit: users rekt, withdrawal fears rise</div>
      <span class="tgme_widget_message_views">3.2M</span>
      <time datetime="2026-11-27T05:30:00+00:00">05:30</time>
    </div>
  </div>
</section>
</body></html>"""


class FakeHTTP:
    """Routes URL substrings to fixture payloads; unlisted routes raise."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout=15):
        self.calls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                return payload
        raise ConnectionError("fixture: no route for " + url)


FULL_ROUTES = {
    "search.rss": REDDIT_ATOM,
    "hn.algolia.com": HN_JSON,
    "mastodon.social": MASTODON_JSON,
    "t.me/s/": TELEGRAM_HTML,
}


def fresh_db():
    con = sqlite3.connect(":memory:")
    social2.init(con)
    return con


# --------------------------------------------------------------------------
# Parser tests
# --------------------------------------------------------------------------

class TestRedditParser(unittest.TestCase):
    def test_parses_entries(self):
        items = social2.parse_reddit_rss(REDDIT_ATOM)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["source"], "reddit_rss")
        self.assertEqual(
            first["source_url"],
            "https://www.reddit.com/r/CryptoCurrency/comments/abc123/bitcoin_breakout/",
        )
        self.assertEqual(first["author"], "/u/some_trader")
        self.assertIn("Bullish rally", first["body"])

    def test_empty_feed(self):
        items = social2.parse_reddit_rss('<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        self.assertEqual(items, [])


class TestHNParser(unittest.TestCase):
    def test_parses_hits(self):
        items = social2.parse_hn_search(HN_JSON)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["engagement"], 512)
        # HN story without external URL falls back to the HN item page
        self.assertEqual(items[1]["source_url"],
                         "https://news.ycombinator.com/item?id=992")


class TestMastodonParser(unittest.TestCase):
    def test_parses_statuses_and_native_bot(self):
        items = social2.parse_mastodon_timeline(MASTODON_JSON)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["engagement"], 16)  # 2 + 5 + 9
        self.assertFalse(items[0]["native_bot"])
        self.assertTrue(items[1]["native_bot"])
        self.assertIn("Solana surge", items[0]["body"])


class TestTelegramParser(unittest.TestCase):
    def test_parses_messages(self):
        items = social2.parse_telegram_preview(TELEGRAM_HTML)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source_url"], "https://t.me/cointelegraph/12345")
        self.assertEqual(items[0]["engagement"], 12500)
        self.assertEqual(items[0]["posted_at"], "2026-11-27T06:30:00+00:00")
        self.assertEqual(items[1]["engagement"], 3200000)

    def test_views_suffixes(self):
        self.assertEqual(social2._parse_views("1.2K"), 1200)
        self.assertEqual(social2._parse_views("3.4M"), 3400000)
        self.assertEqual(social2._parse_views("512"), 512)
        self.assertIsNone(social2._parse_views(None))


# --------------------------------------------------------------------------
# Sentiment / bot heuristics
# --------------------------------------------------------------------------

class TestScoring(unittest.TestCase):
    def test_positive_sentiment(self):
        self.assertGreater(social2.sentiment_score("bullish breakout, price surge to ATH"), 0)

    def test_negative_sentiment(self):
        self.assertLess(social2.sentiment_score("exchange hack, users rekt in the crash"), 0)

    def test_neutral_sentiment(self):
        self.assertEqual(social2.sentiment_score("minutes from the committee meeting"), 0.0)

    def test_spam_flagged(self):
        s = social2.bot_score("FREE BITCOIN GIVEAWAY!!! DM me to double your coins, join my signal group")
        self.assertGreaterEqual(s, 0.5)

    def test_native_bot_flagged(self):
        self.assertGreaterEqual(social2.bot_score("price update", native_bot=True), 0.5)

    def test_normal_text_not_flagged(self):
        s = social2.bot_score("Thoughtful take on the Ethereum upgrade timeline", author="alice")
        self.assertLess(s, 0.5)


class TestMarketDetection(unittest.TestCase):
    def test_symbol_mapping(self):
        self.assertEqual(social2.detect_market("Bitcoin and Solana rally"), "BTC,SOL")
        self.assertEqual(social2.detect_market("cardano upgrade"), "ADA")

    def test_fallback(self):
        self.assertEqual(social2.detect_market("macro outlook for rates"), "CRYPTO")


# --------------------------------------------------------------------------
# fetch(con) end-to-end, offline
# --------------------------------------------------------------------------

class TestFetch(unittest.TestCase):
    def setUp(self):
        self.orig = social2.http_get

    def tearDown(self):
        social2.http_get = self.orig

    def test_fetch_inserts_and_dedupes(self):
        social2.http_get = FakeHTTP(FULL_ROUTES)
        con = fresh_db()
        n1 = social2.fetch(con)
        self.assertEqual(n1, 8)  # 2 reddit + 2 hn + 2 mastodon + 2 telegram
        n2 = social2.fetch(con)  # second run: everything dedupes
        self.assertEqual(n2, 0)
        rows = con.execute(
            "SELECT source, sentiment, bot_flag, market FROM social2_items"
        ).fetchall()
        self.assertEqual(len(rows), 8)
        by_src = {}
        for src, sent, flag, market in rows:
            by_src.setdefault(src, []).append((sent, flag, market))
        self.assertEqual(set(by_src), {"reddit_rss", "hackernews", "mastodon", "telegram"})
        # mastodon native bot account must be flagged
        self.assertTrue(any(f for _, f, _ in by_src["mastodon"]))
        # negative HN hack story must carry negative sentiment
        self.assertTrue(any(s < 0 for s, _, _ in by_src["hackernews"]))
        con.close()

    def test_source_failure_is_logged_and_skipped(self):
        # Reddit route absent -> ConnectionError -> logged, others still work
        routes = {k: v for k, v in FULL_ROUTES.items() if k != "search.rss"}
        social2.http_get = FakeHTTP(routes)
        con = fresh_db()
        n = social2.fetch(con)
        self.assertEqual(n, 6)
        logs = con.execute(
            "SELECT source, ok, error FROM social2_fetch_log WHERE ok = 0"
        ).fetchall()
        self.assertEqual(len(logs), 3)  # 3 reddit queries failed
        self.assertTrue(all(src == "reddit_rss" for src, _, _ in logs))
        self.assertTrue(all("ConnectionError" in err for _, _, err in logs))
        con.close()

    def test_init_idempotent(self):
        con = fresh_db()
        social2.init(con)
        social2.init(con)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("social2_items", tables)
        self.assertIn("social2_fetch_log", tables)
        con.close()

    def test_fetch_returns_int(self):
        social2.http_get = FakeHTTP(FULL_ROUTES)
        con = fresh_db()
        self.assertIsInstance(social2.fetch(con), int)
        con.close()


if __name__ == "__main__":
    unittest.main()
