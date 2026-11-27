import json, os, sqlite3, unittest
from confluence.adapters import crypto_cases as cc

SCHEMA = """CREATE TABLE IF NOT EXISTS trade_cases(id TEXT PRIMARY KEY, collected_at REAL, source_type TEXT,
source_url TEXT, market TEXT, instrument TEXT, side TEXT, entry_ts TEXT, entry_price REAL, exit_price REAL,
size_note TEXT, outcome TEXT, pnl_note TEXT, why_what TEXT, how TEXT, where_ctx TEXT, lesson TEXT,
verified INTEGER DEFAULT 0, confidence REAL, tags TEXT)"""


class T(unittest.TestCase):
    def setUp(self):
        self.rows = cc.load()

    def test_count_and_required(self):
        self.assertGreaterEqual(len(self.rows), 40)
        for r in self.rows:
            for k in ("source_url", "market", "outcome", "why_what", "how", "where_ctx"):
                self.assertTrue(r.get(k), (r.get("id"), k))
            self.assertTrue(r["source_url"].startswith("http"))

    def test_unique_ids_and_losses_present(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(sum(r["outcome"] == "loss" for r in self.rows), 10)

    def test_self_reported_capped(self):
        for r in self.rows:
            if r["source_type"] in ("reddit", "tradingview"):
                self.assertEqual(r["verified"], 0)
                self.assertLessEqual(r["confidence"], 0.4)

    def test_fetch_idempotent(self):
        con = sqlite3.connect(":memory:")
        con.execute(SCHEMA)
        n = cc.fetch(con)
        self.assertEqual(n, len(self.rows))
        self.assertEqual(cc.fetch(con), 0)

if __name__ == "__main__":
    unittest.main()
