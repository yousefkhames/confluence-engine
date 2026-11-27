"""Offline unittest for the R3 stocks case loader. Standard library only."""
import os
import sqlite3
import unittest

from research import stocks_cases

REQUIRED_TEXT = ["source_url", "market", "outcome", "why_what", "how",
                 "where_ctx"]


class TestStocksCases(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.n = stocks_cases.fetch(self.con)

    def tearDown(self):
        self.con.close()

    def rows(self):
        cur = self.con.execute(
            "SELECT id, source_url, market, outcome, why_what, how,"
            " where_ctx, verified, confidence FROM trade_cases")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def test_at_least_30_cases(self):
        self.assertGreaterEqual(self.n, 30)
        self.assertEqual(self.n, len(stocks_cases.load_cases()))

    def test_ids_unique(self):
        ids = [r["id"] for r in self.rows()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_fields_present(self):
        for r in self.rows():
            for field in ("source_url", "market", "outcome", "why_what",
                          "how", "where_ctx"):
                self.assertTrue(r[field], (r["id"], field))
            self.assertTrue(r["source_url"].startswith("http"), r["id"])

    def test_outcome_values(self):
        for r in self.rows():
            self.assertIn(r["outcome"], ("win", "loss"), r["id"])

    def test_losses_have_detail(self):
        losses = [r for r in self.rows() if r["outcome"] == "loss"]
        self.assertGreaterEqual(len(losses), 10)
        for r in losses:
            self.assertTrue(len(r["why_what"]) > 40, r["id"])

    def test_self_reported_flagged(self):
        for r in self.rows():
            if r["verified"] == 0:
                self.assertLessEqual(r["confidence"], 0.4, r["id"])
        self.assertTrue(any(r["verified"] == 0 for r in self.rows()))

    def test_confidence_range(self):
        for r in self.rows():
            self.assertTrue(0.0 < r["confidence"] <= 1.0, r["id"])

    def test_fetch_is_idempotent(self):
        again = stocks_cases.fetch(self.con)
        self.assertEqual(again, self.n)
        count = self.con.execute("SELECT COUNT(*) FROM trade_cases").fetchone()[0]
        self.assertEqual(count, self.n)


if __name__ == "__main__":
    unittest.main()
