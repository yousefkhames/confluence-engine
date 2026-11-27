import unittest, random, os, tempfile
from pipeline import paper as P


class Paper(unittest.TestCase):
    def test_random_market_has_no_survivors(self):
        rnd = random.Random(3); price = {"AAA": 100.0, "BBB": 50.0}; clock = [1_700_000_000.0]
        def fetch():
            for k in price:
                price[k] *= 1 + rnd.gauss(0, 0.0004)
            return dict(price), []
        def now(): return clock[0]
        def sleep(s): clock[0] += s
        st = os.path.join(tempfile.mkdtemp(), "state.json")
        book, log = P.run(st, minutes=60 * 8, now_fn=now, sleep_fn=sleep, fetch=fetch)
        self.assertGreater(book.meta["settled"], 2000)
        agg = P.aggregate(book, minimum=100)
        self.assertEqual(agg["survivors"], 0)
        self.assertEqual(sum(1 for t in book.pending if t[5] < clock[0]), 0)

    def test_buy_and_sell_are_opposites(self):
        b = P.Book(); b.open_round({"X": 100.0}, 0.0); b.settle({"X": 101.0}, 30.0)
        wins = {k: c[1] for k, c in b.cells.items() if "|30s|" in k}
        self.assertEqual(sorted(wins.values()), [0, 1])

    def test_wilson(self):
        lo, hi = P.wilson(50, 100); self.assertTrue(0.40 < lo < 0.5 < hi < 0.60)


if __name__ == "__main__":
    unittest.main()
