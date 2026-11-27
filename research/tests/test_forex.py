"""Offline unittest for the R2 forex workstream. No network access.

Run from repo root: python -m unittest research.tests.test_forex
"""
import json
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # so `import forex_loader` works

from research import forex_loader  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "forex_sample.json")
FULL_JSON = os.path.join(HERE, "..", "cases", "forex.json")

REQUIRED = ["source_url", "market", "outcome", "why_what", "how", "where_ctx"]


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")

    def tearDown(self):
        self.con.close()

    def test_init_creates_table(self):
        forex_loader.init(self.con)
        name = self.con.execute(
            "SELECT name FROM sqlite_master WHERE name='trade_cases'").fetchone()
        self.assertIsNotNone(name)

    def test_load_fixture_returns_count_and_rows(self):
        n = forex_loader.load(self.con, FIXTURE)
        self.assertEqual(n, 2)
        rows = self.con.execute(
            "SELECT id, source_url, verified, confidence FROM trade_cases ORDER BY id"
        ).fetchall()
        self.assertEqual([r[0] for r in rows], ["forex-001", "forex-034"])
        for _, url, verified, conf in rows:
            self.assertTrue(url.startswith("http"))
            self.assertIn(verified, (0, 1))
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 1.0)

    def test_reload_is_idempotent(self):
        forex_loader.load(self.con, FIXTURE)
        forex_loader.load(self.con, FIXTURE)
        count = self.con.execute("SELECT COUNT(*) FROM trade_cases").fetchone()[0]
        self.assertEqual(count, 2)

    def test_missing_required_field_raises(self):
        bad = [{"id": "bad-1", "source_url": "http://x", "market": "forex"}]
        with self.assertRaises(ValueError):
            forex_loader._row(bad[0], 0.0)


class FullJsonTests(unittest.TestCase):
    """Schema and policy checks over the real workstream JSON."""

    @classmethod
    def setUpClass(cls):
        with open(FULL_JSON, encoding="utf-8") as fh:
            cls.cases = json.load(fh)

    def test_at_least_30_cases(self):
        self.assertGreaterEqual(len(self.cases), 30)

    def test_unique_ids(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_fields_present(self):
        for c in self.cases:
            for key in REQUIRED:
                self.assertTrue(c.get(key), f"{c['id']} missing {key}")

    def test_urls_wellformed(self):
        for c in self.cases:
            self.assertTrue(c["source_url"].startswith("http"), c["id"])

    def test_confidence_bounds(self):
        for c in self.cases:
            self.assertGreaterEqual(c["confidence"], 0.0, c["id"])
            self.assertLessEqual(c["confidence"], 1.0, c["id"])

    def test_unverified_self_reports_capped(self):
        for c in self.cases:
            if c["verified"] == 0:
                self.assertLessEqual(c["confidence"], 0.4, c["id"])

    def test_losses_have_why_and_lesson(self):
        for c in self.cases:
            if c["outcome"] == "loss":
                self.assertTrue(c.get("why_what"), c["id"])
                self.assertTrue(c.get("lesson"), c["id"])


if __name__ == "__main__":
    unittest.main()
