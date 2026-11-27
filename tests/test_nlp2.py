import os, sys, sqlite3, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from confluence import nlp2


class T(unittest.TestCase):
    def test_sentiment_direction(self):
        s = nlp2.LexiconScorer()
        self.assertEqual(s.score("Bitcoin surges to record on ETF inflows")["label"], "positive")
        self.assertEqual(s.score("Exchange hacked, withdrawals halted, panic selloff")["label"], "negative")
        self.assertEqual(s.score("The committee met on Tuesday")["label"], "neutral")

    def test_negation_and_probs(self):
        r = nlp2.LexiconScorer().score("Earnings did not beat estimates")
        self.assertLess(r["score"], 0)
        self.assertAlmostEqual(r["positive"] + r["negative"] + r["neutral"], 1.0)

    def test_fallback_when_no_finbert(self):
        self.assertIsInstance(nlp2.get_scorer(), nlp2.LexiconScorer)

    def test_urgency(self):
        self.assertGreater(nlp2.urgency("BREAKING: exchange hacked, withdrawals paused!"), 0.7)
        self.assertLess(nlp2.urgency("Upcoming scheduled weekly recap"), 0.2)
        self.assertEqual(nlp2.urgency(""), 0.0)

    def test_credibility(self):
        self.assertGreater(nlp2.source_credibility("https://www.sec.gov/news/x"), 0.9)
        self.assertEqual(nlp2.source_credibility("https://news.bloomberg.com/a"), 0.88)
        self.assertEqual(nlp2.source_credibility("unknown-blog.example"), nlp2.DEFAULT_CREDIBILITY)
        self.assertEqual(nlp2.source_credibility("https://data.agency.gov/x"), 0.8)
        self.assertLess(nlp2.source_credibility("t.me/pumpgroup"), 0.2)

    def test_bot_features(self):
        bots = [{"text": "100x gem airdrop, join now! http://x.co #moon", "ts": 1000 + i * 10,
                 "author": "a%d" % (i % 2), "account_age_days": 3, "followers": 2, "following": 900}
                for i in range(10)]
        humans = [{"text": "Thoughts on the rate decision %d and what it means" % i,
                   "ts": [0, 4000, 5000, 20000, 21000, 90000][i] + i, "author": "u%d" % i,
                   "account_age_days": 2000, "followers": 300, "following": 200} for i in range(6)]
        self.assertGreater(nlp2.bot_features(bots)["bot_score"], 0.7)
        self.assertLess(nlp2.bot_features(humans)["bot_score"], 0.2)
        self.assertEqual(nlp2.bot_features([])["bot_score"], 0.0)

    def test_analyze_weight(self):
        a = nlp2.analyze("SEC approves spot ETF", "https://sec.gov/x")
        b = nlp2.analyze("SEC approves spot ETF", "https://t.me/x")
        self.assertGreater(a["weighted_score"], b["weighted_score"])

    def test_store(self):
        con = sqlite3.connect(":memory:")
        nlp2.store(con, "Token crashes after exploit", "https://reuters.com/a")
        nlp2.store(con, "Token crashes after exploit", None)
        self.assertEqual(con.execute("select count(*) from nlp2_scores").fetchone()[0], 2)
        self.assertLess(con.execute("select score from nlp2_scores").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
