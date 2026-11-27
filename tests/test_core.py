import unittest, sqlite3, os, tempfile
os.environ["CONFLUENCE_DB"] = ":memory:"
from confluence import db, demo, nlp, signals, backtest, scoring, wallets, paper, postmortem, tiers, config

def fresh():
    con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA); return con

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = fresh(); cls.info = demo.generate(cls.con, days=4)

    def test_nlp(self):
        s, u = nlp.score_text("BREAKING: SEC approves Bitcoin ETF, record inflow")
        self.assertGreater(s, 0.5); self.assertGreater(u, 0.4)
        s, _ = nlp.score_text("Protocol hacked, funds stolen")
        self.assertLess(s, -0.5)

    def test_bot_filter(self):
        posts = [{"text": "XYZ to the moon", "author": f"b{i}", "author_age_days": 2, "ts": 100, "engagement": 0} for i in range(6)]
        posts.append({"text": "careful with XYZ valuation", "author": "real", "author_age_days": 900, "ts": 500, "engagement": 20})
        out = nlp.flag_bots(posts)
        self.assertTrue(all(p["is_bot"] >= 0.5 for p in out[:6])); self.assertLess(out[6]["is_bot"], 0.5)

    def test_chain_tamper(self):
        con = fresh(); demo.generate(con, days=2, coins=["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"])
        end = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
        for i in range(3):
            signals.append_signal(con, {"ts": end - i * 4000, "symbol": "ETH", "direction": "LONG", "score": 70, "price": 100.0,
                                        "factors": {"whale": .5, "news": .2, "sentiment": .1}, "flags": [], "net_edge_pct": 1.0,
                                        "detail": {"whale": {"n_tx": 0, "net_usd_weighted": 0}, "news": {}, "sentiment": {}}})
        self.assertTrue(signals.verify_chain(con)[0])
        con.execute("UPDATE signals SET score=99 WHERE id=2"); con.commit()
        self.assertFalse(signals.verify_chain(con)[0])

    def test_profiles_find_smart_wallets_not_market_makers(self):
        split = self.info["start"] + (self.info["end"] - self.info["start"]) // 2
        wallets.profile_wallets(self.con, until=split)
        smart = [self.con.execute("SELECT smart_score FROM wallets WHERE addr=?", (w,)).fetchone() for w in self.info["smart_wallets"]]
        mm = [self.con.execute("SELECT label FROM wallets WHERE addr=?", (w,)).fetchone() for w in self.info["market_makers"]]
        self.assertTrue(any(r and r["smart_score"] > 0.5 for r in smart))
        self.assertTrue(all(r is None or r["label"] == "market_maker" for r in mm))

    def test_backtest_runs_no_lookahead_and_clean_chain(self):
        end, start = self.info["end"], self.info["start"]
        r = backtest.run(self.con, start + (end - start) // 2, end - 21600)
        self.assertTrue(r["chain_valid"]); self.assertIn("disclaimer", r)
        self.assertEqual(self.con.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"], 0)  # real log untouched

    def test_postmortem_explains_losses(self):
        con = fresh(); demo.generate(con, days=3)
        end = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
        sid, _ = signals.append_signal(con, {"ts": end - 80000, "symbol": "SOL", "direction": "LONG", "score": 70,
                    "price": 100.0, "factors": {"whale": .5, "news": -.4, "sentiment": .1}, "flags": ["REGIME_CHOPPY: x"], "net_edge_pct": 1,
                    "detail": {"whale": {"n_tx": 0, "net_usd_weighted": 0}, "news": {}, "sentiment": {}}})
        con.execute("INSERT INTO outcomes VALUES(?,?,?,?,?)", (sid, "1h", 97.0, -3.0, 0)); con.commit()
        pm = postmortem.post_mortem(con, sid)
        self.assertFalse(pm["won"]); self.assertTrue(pm["causes"])

    def test_tier_delay(self):
        con = fresh()
        for t in (1000, 5000):
            con.execute("INSERT INTO signals(ts,symbol,direction,score,price,reason,factors,flags,net_edge_pct,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (t, "BTC", "LONG", 70, 1, "", "{}", "[]", 1, "", str(t)))
        self.assertEqual(len(tiers.visible_signals(con, "free", 5500)), 1)
        self.assertEqual(len(tiers.visible_signals(con, "pro", 5500)), 2)

    def test_paper_only_no_order_code(self):
        root = os.path.dirname(os.path.dirname(__file__)); bad = []
        for dp, _, fs in os.walk(os.path.join(root, "confluence")):
            for f in fs:
                if f.endswith(".py") and f != "datasets.py":
                    src = open(os.path.join(dp, f)).read().lower()
                    if any(x in src for x in ("create_order", "place_order", "/api/v3/order", "private_key", "api_secret")):
                        bad.append(f)
        self.assertEqual(bad, [])

if __name__ == "__main__":
    unittest.main()
