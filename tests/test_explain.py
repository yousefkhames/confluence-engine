import unittest, sqlite3, json
from confluence import db, demo, signals
from confluence.explain import build_record, build_all, attribution_summary

class T(unittest.TestCase):
    def test_records_for_win_and_loss(self):
        con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row; con.executescript(db.SCHEMA)
        demo.generate(con, days=3)
        end = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
        D = {"whale": {"n_tx": 0, "net_usd_weighted": 0}, "news": {}, "sentiment": {}}
        base = {"detail": D, "symbol": "SOL", "direction": "LONG", "score": 70, "price": 100.0, "flags": [], "net_edge_pct": 1.0,
                "factors": {"whale": .5, "news": .2, "sentiment": .1}}
        a, _ = signals.append_signal(con, {**base, "ts": end - 90000})
        b, _ = signals.append_signal(con, {**base, "ts": end - 80000, "factors": {"whale": .5, "news": -.4, "sentiment": .1}, "flags": ["REGIME_CHOPPY: x"]})
        con.execute("INSERT INTO outcomes VALUES(?,?,?,?,?)", (a, "1h", 103.0, 3.0, 1))
        con.execute("INSERT INTO outcomes VALUES(?,?,?,?,?)", (b, "1h", 97.0, -3.0, 0)); con.commit()
        self.assertEqual(build_all(con), 2)
        r = build_record(con, b)
        self.assertFalse(r["why"]["1h"]["won"]); self.assertTrue(r["why"]["1h"]["causes"]); self.assertIn("line1", r["how"])
        summ = attribution_summary(con)
        self.assertEqual(summ["regime"] and sum(v["n"] for v in summ["regime"].values()), 2)

if __name__ == "__main__": unittest.main()
