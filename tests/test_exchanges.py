import sqlite3, unittest
from confluence.adapters import exchanges as ex
from confluence import backfill

NOW = 1_800_000_000


def fake_get(url, params=None):
    if "coinbase" in url and url.endswith("/candles"):
        s = ex.time.strptime(params["start"], "%Y-%m-%dT%H:%M:%SZ")
        t = int(ex.time.mktime(s)) - ex.time.timezone
        return [[t, 99, 101, 100, 100.5, 3.0]]
    if "coinbase" in url and url.endswith("/book"):
        return {"bids": [["100", "1", 1], ["99", "2", 1]], "asks": [["101", "1", 1], ["102", "1", 1]]}
    if url.endswith("/OHLC"):
        return {"error": [], "result": {"XXBTZUSD": [[NOW - 7200, "1", "2", "0.5", "1.5", "1", "9", 3],
                                                     [NOW - 3600, "1", "2", "0.5", "1.5", "1", "9", 3],
                                                     [NOW, "1", "2", "0.5", "1.5", "1", "9", 3]], "last": NOW}}
    if url.endswith("/Depth"):
        return {"error": [], "result": {"X": {"bids": [["100", "1", 1]], "asks": [["101", "1", 1]]}}}
    if url.endswith("/market/candles") or url.endswith("/market/history-candles"):
        return {"code": "0", "data": [[str((NOW - 3600) * 1000), "1", "2", "0.5", "1.5", "5", "0", "0", "1"],
                                       [str(NOW * 1000), "1", "2", "0.5", "1.5", "5", "0", "0", "0"]]}
    if url.endswith("/market/books"):
        return {"code": "0", "data": [{"bids": [["100", "1", "0", "1"]], "asks": [["100.1", "3", "0", "1"]]}]}
    if url.endswith("/public/funding-rate"):
        return {"code": "0", "data": [{"fundingRate": "0.0001", "fundingTime": str(NOW * 1000)}]}
    if url.endswith("/public/funding-rate-history"):
        return {"code": "0", "data": [{"fundingTime": str((NOW - 28800) * 1000), "realizedRate": "0.0002", "fundingRate": "0.0002"}]}
    if url.endswith("/public/open-interest"):
        return {"code": "0", "data": [{"ts": str(NOW * 1000), "oiCcy": "10", "oiUsd": "1000"}]}
    if url.endswith("/public/liquidation-orders"):
        return {"code": "0", "data": [{"details": [{"ts": str(NOW * 1000), "posSide": "long", "sz": "2", "bkPx": "95"}]}]}
    if url.endswith("/tickers"):
        return {"tickers": [{"symbol": "PF_XBTUSD", "fundingRate": 0.00001, "openInterest": 5, "last": 100}]}
    raise RuntimeError("unexpected " + url)


class T(unittest.TestCase):
    def setUp(self):
        self.orig = ex._get
        ex._get = fake_get
        self.con = sqlite3.connect(":memory:")

    def tearDown(self):
        ex._get = self.orig

    def test_parsers(self):
        self.assertEqual(ex.parse_coinbase_candles([[1, 1, 3, 2, 2.5, 9]]), [(1, 2.0, 3.0, 1.0, 2.5, 9.0)])
        s = ex.book_stats([(100, 1)], [(101, 1)])
        self.assertAlmostEqual(s["spread_bps"], 99.50, 1)
        self.assertEqual(s["imbalance"], (100 - 101) / 201)
        self.assertIsNone(ex.book_stats([], [(1, 1)]))

    def test_okx_drops_unconfirmed(self):
        rows = ex.candles_okx("BTC", "1h")
        self.assertEqual(len(rows), 1)

    def test_kraken_drops_forming(self):
        self.assertEqual(len(ex.candles_kraken("BTC", "1h", 0)), 2)

    def test_fetch_all_tables_and_idempotent(self):
        n = ex.fetch(self.con, symbols=("BTC",), tfs=("1h",), now=NOW)
        self.assertGreater(n, 0)
        self.assertEqual(ex.fetch.last_errors, [])
        for t in ("ex_candles", "ex_orderbook", "ex_funding", "ex_oi", "ex_liquidations"):
            self.assertGreater(self.con.execute("select count(*) from " + t).fetchone()[0], 0, t)
        self.assertEqual(ex.fetch(self.con, symbols=("BTC",), tfs=("1h",), now=NOW), 0)

    def test_one_venue_failing_is_isolated(self):
        def bad(url, params=None):
            if "kraken" in url and "futures" not in url:
                raise RuntimeError("down")
            return fake_get(url, params)
        ex._get = bad
        n = ex.fetch(self.con, symbols=("BTC",), tfs=("1h",), now=NOW)
        self.assertGreater(n, 0)
        self.assertTrue(any("kraken" in e for e in ex.fetch.last_errors))

    def test_backfill(self):
        backfill.PAUSE = 0
        r = backfill.run(self.con, days=1, tfs=("1h",), symbols=("BTC",), now=NOW)
        self.assertGreater(self.con.execute("select count(*) from ex_candles").fetchone()[0], 0)
        self.assertGreater(self.con.execute("select count(*) from ex_funding").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
