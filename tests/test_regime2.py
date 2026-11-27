import sqlite3, unittest, math
from datetime import date, timedelta
from confluence.adapters import macro
from confluence import regime2

FRED_CSV = "observation_date,DGS10\n2026-11-24,4.01\n2026-11-25,.\n2026-11-26,4.05\n"
ECB_CSV = "KEY,TIME_PERIOD,OBS_VALUE\nX,2026-11-25,1.0935\nX,2026-11-26,1.0975\nX,2026-11-27,\n"

def fill(con, name, vals, src="fred", end=date(2026, 11, 26)):
    n = len(vals)
    macro.store(con, src, name, [((end - timedelta(days=n-1-i)).isoformat(), v) for i, v in enumerate(vals)])

def mk():
    con = sqlite3.connect(":memory:"); macro.init(con); return con

class T(unittest.TestCase):
    def test_parsers(self):
        self.assertEqual(macro.parse_fred(FRED_CSV), [("2026-11-24", 4.01), ("2026-11-26", 4.05)])
        self.assertEqual(len(macro.parse_ecb(ECB_CSV)), 2)

    def test_fetch_offline(self):
        con = mk()
        def g(url): return ECB_CSV if "ecb.europa" in url else FRED_CSV
        n = macro.fetch(con, getter=g)
        self.assertGreater(n, 0)
        self.assertEqual(con.execute("SELECT count(*) FROM macro_obs WHERE series='VIX'").fetchone()[0], 2)

    def test_fetch_survives_errors(self):
        con = mk()
        def g(url): raise OSError("blocked")
        self.assertEqual(macro.fetch(con, getter=g), 0)

    def test_empty_unknown(self):
        r = regime2.regime(mk(), date(2026, 11, 27))
        self.assertEqual(r["label"], "unknown"); self.assertEqual(r["confidence"], 0.0)

    def test_risk_on(self):
        con = mk()
        fill(con, "VIX", [13.0] * 5)
        fill(con, "T10Y2Y", [0.5] * 5)
        fill(con, "DXY", [100 - i * 0.1 for i in range(30)])
        fill(con, "BTC", [50000 * (1 + 0.004 * i) for i in range(80)])
        r = regime2.regime(con, date(2026, 11, 27))
        self.assertEqual(r["label"], "risk_on"); self.assertGreater(r["score"], 0.25)

    def test_stress(self):
        con = mk()
        fill(con, "VIX", [40.0] * 5)
        fill(con, "HY_OAS", [3.0] * 100 + [4.0, 5.0, 6.0, 7.0, 8.0])
        fill(con, "BTC", [50000 * (1 - 0.004 * i) for i in range(80)])
        r = regime2.regime(con, date(2026, 11, 27))
        self.assertEqual(r["label"], "stress")

    def test_stale_lowers_confidence(self):
        con = mk(); fill(con, "VIX", [13.0] * 5)
        fresh = regime2.regime(con, date(2026, 11, 27))["confidence"]
        stale = regime2.regime(con, date(2026, 12, 20))
        self.assertLess(stale["confidence"], fresh); self.assertTrue(any("stale" in n for n in stale["notes"]))

    def test_corr(self):
        a = [math.sin(i) for i in range(30)]
        self.assertAlmostEqual(regime2.corr(a, a), 1.0)
        self.assertAlmostEqual(regime2.corr(a, [-x for x in a]), -1.0)
        self.assertIsNone(regime2.corr([1] * 20, a[:20]))

    def test_cross_asset(self):
        con = mk()
        btc = [100 + i + (i % 3) for i in range(80)]
        fill(con, "BTC", btc); fill(con, "SPX", [x * 2 for x in btc])
        fill(con, "ETH", [x * (0.05 + i * 0.001) for i, x in enumerate(btc)])
        c = regime2.cross_asset(con)
        self.assertGreater(c["btc_spx_corr"], 0.99); self.assertEqual(c["alt_risk_appetite"], "rising")

    def test_confluence_input(self):
        con = mk(); fill(con, "VIX", [20.0] * 3)
        s, c, l = regime2.confluence_input(con)
        self.assertTrue(-1 <= s <= 1 and 0 <= c <= 1)

if __name__ == "__main__": unittest.main()
