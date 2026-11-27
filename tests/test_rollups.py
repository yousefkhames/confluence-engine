import unittest, sqlite3
from confluence import db, demo, rollups, dashboard

class T(unittest.TestCase):
    def test_rollups_and_pagination(self):
        con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row; con.executescript(db.SCHEMA)
        demo.generate(con, days=3, coins=["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"])
        n_min = con.execute("SELECT COUNT(*) c FROM prices WHERE symbol='ETH'").fetchone()["c"]
        r = rollups.run_all(con)
        self.assertGreater(r["prices_1h"], 0)
        h = con.execute("SELECT COUNT(*) c FROM prices_1h WHERE symbol='ETH'").fetchone()["c"]
        self.assertLess(h, n_min / 50)
        self.assertEqual(rollups.roll_prices(con), 0)          # incremental: nothing new, nothing redone
        self.assertGreater(con.execute("SELECT COUNT(*) c FROM daily_summary").fetchone()["c"], 0)
        # OHLC sanity for one hour
        row = con.execute("SELECT * FROM prices_1h WHERE symbol='ETH' ORDER BY ts LIMIT 1").fetchone()
        self.assertLessEqual(row["low"], row["open"]); self.assertGreaterEqual(row["high"], row["close"] - 1e-9)
        deleted = rollups.prune_minutes(con, keep_days=1)
        self.assertGreater(deleted, 0)
        self.assertGreater(con.execute("SELECT COUNT(*) c FROM prices_1h").fetchone()["c"], 0)

if __name__ == "__main__": unittest.main()
