import unittest, random
try:
    import numpy as np
    from pipeline import research as R
except Exception:
    np = None


@unittest.skipIf(np is None, "numpy only in the pipeline job")
class Research(unittest.TestCase):
    def bars(self, n, seed):
        rnd = random.Random(seed); p = 100.0; out = []
        for i in range(n):
            o = p; p *= 1 + rnd.gauss(0, 0.01); out.append((i * 3600, o, max(o, p) * 1.002, min(o, p) * 0.998, p, 100 + rnd.random() * 10))
        return out

    def test_features_are_causal(self):
        b = self.bars(800, 1); _, X, _, _, _ = R.featurize(b); _, X2, _, _, _ = R.featurize(b[:600])
        self.assertTrue(np.allclose(X[:600], X2, equal_nan=True))

    def test_bh(self):
        self.assertEqual(R.bh([0.001, 0.2, 0.9]), [True, False, False])

    def test_noise_has_no_session_effect(self):
        data = R.build({"S%d" % k: self.bars(4000, 20 + k) for k in range(4)})
        self.assertEqual(R.session_effects(data)["survivors"], 0)


if __name__ == "__main__":
    unittest.main()
