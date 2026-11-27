import unittest, random
from confluence import patterns as P


def walk(n, seed=1, drift=0.0, vol=0.01):
    rnd = random.Random(seed); p = 100.0; bars = []
    for i in range(n):
        o = p; p *= 1 + rnd.gauss(drift, vol); hi = max(o, p) * (1 + abs(rnd.gauss(0, vol / 3))); lo = min(o, p) * (1 - abs(rnd.gauss(0, vol / 3)))
        bars.append((i * 3600, o, hi, lo, p, 100 + rnd.random() * 20))
    return bars


class Indicators(unittest.TestCase):
    def test_rsi_bounds(self):
        r = [x for x in P.rsi_series([b[4] for b in walk(300)]) if x is not None]
        self.assertTrue(all(0 <= x <= 100 for x in r))

    def test_rules_are_causal(self):
        """Truncating the future must not change what a rule says about bar i."""
        bars = walk(500, seed=4)
        fng = {b[0] // 86400 * 86400: (b[0] // 86400 * 37) % 100 for b in bars}
        full = P.Ctx(bars, fng)
        for rid, _t, fn, *_rest in P.RULES:
            for i in range(230, 480, 7):
                cut = P.Ctx(bars[:i + 1], fng)
                self.assertEqual(fn(full, i), fn(cut, i), rid)


class Backtest(unittest.TestCase):
    def test_planted_pattern_is_found(self):
        """Plant: after a four-red-bars reversal the next 6 bars rise 1.5%. The backtest must call it supported."""
        bars = walk(3000, seed=2); out = []; i = 0
        x = P.Ctx(bars); b = [list(r) for r in bars]
        for j in range(30, len(b) - 10):
            if P.r_four_down_reversal(x, j):
                for k in range(1, 7):
                    b[j + k][4] = b[j][4] * (1 + 0.003 * k); b[j + k][1] = b[j + k - 1][4]
                    b[j + k][2] = max(b[j + k][1], b[j + k][4]) * 1.001; b[j + k][3] = min(b[j + k][1], b[j + k][4]) * 0.999
        res = P.backtest_rule({("X", "1h"): [tuple(r) for r in b]}, [r for r in P.RULES if r[0] == "four_down_reversal"][0], 0.3)
        self.assertGreater(res["all"]["hit_rate"], 0.7)

    def test_random_walk_has_no_supported_rule(self):
        series = {("S%d" % k, "1h"): walk(2500, seed=10 + k) for k in range(6)}
        res = P.run_all(series, 0.3)
        self.assertFalse([r["id"] for r in res if r["status"].startswith("supported")])

    def test_wilson(self):
        lo, hi = P.wilson(60, 100)
        self.assertTrue(0.49 < lo < 0.6 < hi < 0.70)


class Emotion(unittest.TestCase):
    def test_score_range_and_noise(self):
        from confluence import emotion as E
        series = {("S%d" % k, "1d"): [(b[0] * 24, b[1], b[2], b[3], b[4], b[5]) for b in walk(600, seed=30 + k)] for k in range(8)}
        res = E.validate(series, {})
        for h, v in res["horizons"].items():
            self.assertEqual(v["verdict"], "no reliable relationship")
        c = E.composite(P.Ctx(series[("S0", "1d")]), 300)
        self.assertTrue(-100 <= c[0] <= 100)

    def test_spearman_perfect(self):
        from confluence import emotion as E
        r, _ = E.spearman(list(range(50)), [2 * i for i in range(50)])
        self.assertAlmostEqual(r, 1.0)


if __name__ == "__main__":
    unittest.main()
