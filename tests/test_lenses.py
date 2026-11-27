import os, sys, json, math, gzip, tempfile, unittest, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from pipeline import lenses as L, site as S


def fake_arrays(n=4000, coins=("BTC", "ETH", "CCC")):
    rng = np.random.default_rng(0); A = {}
    for c in coins:
        r = rng.normal(0, 0.01, n); cl = 100 * np.exp(np.cumsum(r)); ts = 1500000000 + np.arange(n) * 3600.0
        d = cl[::24]
        A[c] = {"ts": ts, "o": cl, "h": cl * 1.001, "l": cl * 0.999, "c": cl, "v": np.ones(n), "r": np.diff(np.log(cl), prepend=np.log(cl[0])),
                "dc": d, "dr": np.diff(np.log(d), prepend=np.log(d[0]))}
    return A


class T(unittest.TestCase):
    def test_bh(self):
        self.assertEqual(L.bh([0.001, 0.5, 0.9]), [True, False, False])

    def test_random_walk_has_no_survivors(self):
        A = fake_arrays()
        r3 = L.lens3(A); self.assertEqual(r3["survivors_oos"], 0)
        r1 = L.lens1(A); self.assertEqual(r1["totals"]["ohlc_violations"], 0); self.assertEqual(r1["totals"]["dup_or_unsorted"], 0)
        self.assertIn("verdict", L.lens5(A))

    def test_coverage_and_pages(self):
        with tempfile.TemporaryDirectory() as d:
            h = os.path.join(d, "history"); os.makedirs(h)
            with gzip.open(os.path.join(h, "AAA-1h.csv.gz"), "wt") as f:
                for i in range(200):
                    if i != 50: f.write("%d,1,1,1,1,1\n" % (1500000000 // 86400 * 86400 + i * 3600))
            c = S.compute_coverage(h); self.assertEqual(c["rows"][0]["bars_1h"], 199); self.assertEqual(c["missing_hours"], 1)
            site = os.path.join(d, "site"); os.makedirs(site); open(os.path.join(site, "index.html"), "w").write("<title>x</title><div class=live></div></html>")
            S.finalize(site, d, None, c); s = open(os.path.join(site, "index.html")).read(); self.assertIn("coverage.html", s)
            self.assertTrue(os.path.exists(os.path.join(site, "manifest.json")))

if __name__ == "__main__":
    unittest.main()


class DemoTrades(unittest.TestCase):
    def test_stats(self):
        from pipeline import demo_trades as D
        lo, hi = D.wilson(8, 11); self.assertTrue(lo < 8 / 11 < hi)
        up, two = D.binom_p_ge(5, 10, 0.5); self.assertAlmostEqual(up, 0.623046875, 5)
        raw = os.path.join(os.path.dirname(__file__), "..", "demo", "demo_trades_raw.csv")
        r = D.analyze(raw); self.assertEqual(r["total_rows"], 89)
        s = r["segments"]["post_reset_usd"]; self.assertEqual(s["wins"] + s["losses"], s["closed"])
        self.assertIn("<table>", D.page(r))
