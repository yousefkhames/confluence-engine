"""Offline tests for confluence/learning.py (Workstream S1).

No network, no core package needed: the module is loaded straight from its file
and every fixture is built in an in-memory SQLite database that mirrors the
core DDL (signals / outcomes / weights) plus the shared trade_cases table.

Run:  python3 tests/test_learning.py         (or python3 -m unittest discover -s tests)
"""

import importlib.util
import json
import math
import os
import random
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(os.path.dirname(HERE), "confluence", "learning.py")


def load_module():
    spec = importlib.util.spec_from_file_location("learning_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = load_module()

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
DAY = 86400.0


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def new_db(with_core=True):
    con = sqlite3.connect(":memory:")
    if with_core:
        con.execute(
            """CREATE TABLE signals (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL, symbol TEXT, direction TEXT, score REAL, price REAL,
                   reason TEXT, factors TEXT, flags TEXT, net_edge_pct REAL,
                   prev_hash TEXT, hash TEXT)"""
        )
        con.execute(
            """CREATE TABLE outcomes (
                   signal_id INTEGER, horizon TEXT, price REAL, ret_pct REAL,
                   hit INTEGER, PRIMARY KEY (signal_id, horizon))"""
        )
        con.execute("CREATE TABLE weights (k TEXT PRIMARY KEY, v REAL)")
        for k, v in (("whale", 0.40), ("news", 0.30), ("sentiment", 0.30)):
            con.execute("INSERT INTO weights VALUES (?,?)", (k, v))
    con.commit()
    return con


def add_signal(con, ts, direction, factors, score, hit, ret_pct=None, horizon="1h",
               symbol="BTCUSDT", flags=None, net_edge=None):
    """Insert one signal and its outcome. ret_pct defaults to a consistent value."""
    dir_sign = -1.0 if str(direction).upper().startswith("S") else 1.0
    if ret_pct is None:
        ret_pct = (0.8 if hit else -0.8) * dir_sign
    con.execute(
        "INSERT INTO signals (ts, symbol, direction, score, price, reason, factors,"
        " flags, net_edge_pct) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, symbol, direction, score, 100.0, "test", json.dumps(factors),
         json.dumps(flags or []), net_edge),
    )
    sid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.execute(
        "INSERT INTO outcomes (signal_id, horizon, price, ret_pct, hit) VALUES (?,?,?,?,?)",
        (sid, horizon, 100.0 * (1 + ret_pct / 100.0), ret_pct, 1 if hit else 0),
    )
    return sid


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def synth(con, n=320, seed=7, whale_effect=1.6, news_effect=0.7, sentiment_effect=0.0,
          step_days=0.35, horizon="1h", noise_score=12.0):
    """Signals whose outcomes follow the direction-aligned factors.

    The engine's own score is deliberately over-dispersed so that ``score/100``
    is a worse probability than a properly fitted, calibrated model: that is the
    gap the walk-forward is supposed to detect.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        ts = BASE.timestamp() + i * step_days * DAY
        direction = "LONG" if i % 2 == 0 else "SHORT"
        dir_sign = 1.0 if direction == "LONG" else -1.0
        whale = round(rng.uniform(-1, 1), 3)
        news = round(rng.uniform(-1, 1), 3)
        sentiment = round(rng.uniform(-1, 1), 3)
        eta = (whale_effect * whale * dir_sign + news_effect * news * dir_sign
               + sentiment_effect * sentiment * dir_sign)
        y = 1 if rng.random() < sigmoid(eta) else 0
        raw = 50.0 + 34.0 * (0.5 * whale + 0.3 * news + 0.2 * sentiment) * dir_sign
        score = max(0.0, min(100.0, raw + rng.gauss(0, noise_score)))
        rows.append(add_signal(con, ts, direction,
                               {"whale": whale, "news": news, "sentiment": sentiment},
                               score, y, horizon=horizon))
    con.commit()
    return rows


def trade_cases_ddl(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS trade_cases (
               id TEXT PRIMARY KEY, collected_at REAL, source_type TEXT,
               source_url TEXT, market TEXT, instrument TEXT, side TEXT,
               entry_ts REAL, entry_price REAL, exit_price REAL, size_note TEXT,
               outcome TEXT, pnl_note TEXT, why_what TEXT, how TEXT,
               where_ctx TEXT, lesson TEXT, verified INTEGER DEFAULT 0,
               confidence REAL, tags TEXT)"""
    )
    con.commit()


def add_research(con, cid, outcome, verified=0, confidence=0.7, market="BTC",
                 side="long", why="funding flipped negative", lesson="", url=None,
                 ts=None):
    trade_cases_ddl(con)
    con.execute(
        """INSERT OR REPLACE INTO trade_cases
           (id, collected_at, source_type, source_url, market, instrument, side,
            entry_ts, outcome, why_what, how, where_ctx, lesson, verified, confidence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, (ts or BASE.timestamp()), "research", url or ("https://example.test/" + cid),
         market, "BTCUSDT", side, (ts or BASE.timestamp()), outcome, why, "step 1",
         "binance perp", lesson, verified, confidence),
    )
    con.commit()


# ---------------------------------------------------------------------------
# utilities, outcomes, timestamps
# ---------------------------------------------------------------------------

class TestUtilities(unittest.TestCase):
    def test_parse_ts_variants(self):
        self.assertEqual(L.parse_ts("2026-03-01").year, 2026)
        self.assertEqual(L.parse_ts("2026-03-01T10:20:30Z").hour, 10)
        self.assertEqual(L.parse_ts(1770000000).year, 2026)
        self.assertEqual(L.parse_ts(1770000000000).year, 2026)  # milliseconds
        self.assertIsNone(L.parse_ts(None))
        self.assertIsNone(L.parse_ts("not a date"))
        dt = L.parse_ts("2026-03-01T10:00:00")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(L.iso(dt), "2026-03-01T10:00:00Z")

    def test_sql_identifier_guard(self):
        self.assertEqual(L._q("signals"), '"signals"')
        with self.assertRaises(ValueError):
            L._q("signals; DROP TABLE signals")

    def test_normalize_outcome(self):
        cases = {
            "win": "win", "WON": "win", "target_hit": "win", 1: "win", True: "win",
            "loss": "loss", "stopped out": "loss", 0: "loss", -1: "loss", False: "loss",
            "breakeven": "flat", "BE": "flat",
            "open": "open", "pending": "open", None: None, "banana": None,
        }
        for raw, want in cases.items():
            self.assertEqual(L.normalize_outcome(raw), want, "outcome %r" % (raw,))

    def test_label_of(self):
        self.assertEqual(L.label_of("win"), 1.0)
        self.assertEqual(L.label_of("loss"), 0.0)
        self.assertIsNone(L.label_of("flat"))
        self.assertIsNone(L.label_of(None))

    def test_label_from_prices(self):
        self.assertEqual(L.label_from_prices(100, 110, "long"), "win")
        self.assertEqual(L.label_from_prices(100, 90, "long"), "loss")
        self.assertEqual(L.label_from_prices(100, 90, "short"), "win")
        self.assertIsNone(L.label_from_prices(None, 90, "long"))
        self.assertIsNone(L.label_from_prices(100, 100, "long"))

    def test_sigmoid_and_logit_roundtrip(self):
        for p in (0.01, 0.3, 0.5, 0.9, 0.99):
            self.assertAlmostEqual(L.sigmoid(L.logit(p)), p, places=6)
        self.assertLess(L.sigmoid(-1000), 1e-9)
        self.assertGreater(L.sigmoid(1000), 1 - 1e-9)


class TestSchema(unittest.TestCase):
    def test_ensure_schema_is_idempotent(self):
        con = new_db()
        L.ensure_schema(con)
        L.ensure_schema(con)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in (L.CASES_TABLE, L.WEIGHTS_TABLE, L.CALIBRATION_TABLE,
                      L.RUNS_TABLE, L.PREDICTIONS_TABLE):
            self.assertIn(table, names)
        # init() alias used by the integrator's loader
        L.init(con)
        self.assertTrue(L._table_exists(con, L.CASES_TABLE))

    def test_columns_and_pick(self):
        con = new_db()
        cols = L._columns(con, "signals")
        self.assertIn("score", cols)
        self.assertEqual(L._pick(cols, "SCORE"), "score")
        self.assertIsNone(L._pick(cols, "nope"))
        self.assertEqual(L._columns(con, "missing_table"), [])


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

class TestSources(unittest.TestCase):
    def test_load_signals_aligns_factors_by_side(self):
        con = new_db()
        add_signal(con, BASE.timestamp(), "SHORT",
                   {"whale": -0.6, "news": 0.4, "sentiment": 0.0}, 70.0, hit=1)
        add_signal(con, BASE.timestamp() + DAY, "LONG",
                   {"whale": -0.6, "news": 0.4, "sentiment": 0.0}, 30.0, hit=0)
        cases = L.load_signals(con, "1h")
        self.assertEqual(len(cases), 2)
        short, long_ = cases[0], cases[1]
        # a bearish whale on a SHORT supports the call
        self.assertAlmostEqual(short["factors"]["whale"], 0.6)
        self.assertAlmostEqual(long_["factors"]["whale"], -0.6)
        self.assertEqual(short["label"], 1)
        self.assertEqual(long_["label"], 0)
        self.assertEqual(short["direction"], "SHORT")
        self.assertAlmostEqual(short["dir_sign"], -1.0)
        # directional return is side-adjusted
        self.assertAlmostEqual(short["dir_ret"], 0.8)

    def test_load_signals_manipulation_flag(self):
        con = new_db()
        add_signal(con, BASE.timestamp(), "LONG",
                   {"whale": 0.1, "news": 0.1, "sentiment": 0.1}, 60.0, hit=0,
                   flags=[L.MANIP_FLAG])
        add_signal(con, BASE.timestamp() + DAY, "LONG",
                   {"whale": 0.1, "news": 0.1, "sentiment": 0.1}, 60.0, hit=1)
        cases = L.load_signals(con, "1h")
        self.assertEqual(cases[0]["factors"]["manip"], -1.0)
        self.assertEqual(cases[1]["factors"]["manip"], 0.0)
        self.assertIn(L.MANIP_FLAG, cases[0]["flags"])

    def test_load_signals_without_core_tables(self):
        con = sqlite3.connect(":memory:")
        self.assertEqual(L.load_signals(con, "1h"), [])

    def test_load_signals_filters_horizon(self):
        con = new_db()
        add_signal(con, BASE.timestamp(), "LONG",
                   {"whale": 0.1, "news": 0.1, "sentiment": 0.1}, 60.0, hit=1,
                   horizon="1h")
        add_signal(con, BASE.timestamp(), "LONG",
                   {"whale": 0.1, "news": 0.1, "sentiment": 0.1}, 60.0, hit=0,
                   horizon="24h")
        self.assertEqual(len(L.load_signals(con, "1h")), 1)
        self.assertEqual(len(L.load_signals(con, "24h")), 1)
        self.assertEqual(len(L.load_signals(con, "all")), 2)

    def test_label_falls_back_to_directional_return(self):
        con = new_db()
        # hit column absent -> label comes from ret_pct and direction
        con.execute("ALTER TABLE outcomes RENAME TO outcomes_old")
        con.execute("CREATE TABLE outcomes (signal_id INTEGER, horizon TEXT, ret_pct REAL)")
        con.execute("INSERT INTO signals (ts, symbol, direction, score, factors, flags)"
                    " VALUES (?,?,?,?,?,?)",
                    (BASE.timestamp(), "BTCUSDT", "SHORT", 55.0,
                     json.dumps({"whale": 0.0, "news": 0.0, "sentiment": 0.0}), "[]"))
        con.execute("INSERT INTO outcomes VALUES (1,'1h',-1.5)")  # price fell: short won
        cases = L.load_signals(con, "1h")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["label"], 1)

    def test_research_cases_and_sync(self):
        con = new_db(with_core=False)
        add_research(con, "c1", "win", verified=1, confidence=0.8)
        add_research(con, "c2", "loss", verified=0, confidence=0.9, why="late entry")
        cases = L.load_research_cases(con)
        self.assertEqual(len(cases), 2)
        by_id = {c["case_id"]: c for c in cases}
        self.assertEqual(by_id["c1"]["label"], 1.0)
        self.assertEqual(by_id["c2"]["label"], 0.0)
        self.assertEqual(by_id["c2"]["verified"], 0)
        L.ensure_schema(con)
        self.assertEqual(L.sync_cases(con), 2)
        rows = con.execute("SELECT case_id, label, verified FROM learning_cases"
                           " ORDER BY case_id").fetchall()
        self.assertEqual(rows, [("c1", 1, 1), ("c2", 0, 0)])
        # idempotent
        self.assertEqual(L.sync_cases(con), 2)
        self.assertEqual(con.execute("SELECT count(*) FROM learning_cases").fetchone()[0], 2)

    def test_ingest_trade_cases_respects_existing_ddl(self):
        con = new_db(with_core=False)
        con.execute("CREATE TABLE trade_cases (id TEXT PRIMARY KEY, source_url TEXT,"
                    " market TEXT, outcome TEXT)")
        n = L.ingest_trade_cases(con, [
            {"id": "a", "source_url": "https://x.test/a", "market": "ETH",
             "outcome": "win", "why_what": "not a column here", "confidence": 0.9},
        ])
        self.assertEqual(n, 1)
        row = con.execute("SELECT id, source_url, market, outcome FROM trade_cases").fetchone()
        self.assertEqual(row, ("a", "https://x.test/a", "ETH", "win"))

    def test_ingest_trade_cases_creates_table_when_missing(self):
        con = new_db(with_core=False)
        n = L.ingest_trade_cases(con, [{
            "id": "z1", "source_url": "https://x.test/z", "market": "BTC",
            "outcome": "loss", "why_what": "chased", "verified": True,
            "confidence": 0.4,
        }])
        self.assertEqual(n, 1)
        row = con.execute("SELECT verified, confidence FROM trade_cases").fetchone()
        self.assertEqual(row, (1, 0.4))

    def test_load_cases_falls_back_to_research(self):
        con = new_db(with_core=False)
        add_research(con, "c1", "win")
        cases = L.load_cases(con, "auto", horizon="1h")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["source"], "research")

    def test_sample_weights_discounts_unverified_and_old(self):
        now = BASE + timedelta(days=200)
        cases = [
            {"source": "signals", "verified": 1, "confidence": None, "ts": now},
            {"source": "research", "verified": 0, "confidence": 1.0, "ts": now},
            {"source": "research", "verified": 1, "confidence": 1.0,
             "ts": now - timedelta(days=90)},
        ]
        w = L.sample_weights(cases, as_of=now, half_life_days=90.0, unverified_weight=0.35)
        # the decay is normalized to mean 1, so compare ratios, not levels
        self.assertAlmostEqual(w[1] / w[0], 0.35, places=6)
        self.assertAlmostEqual(w[2] / w[0], 0.5, places=6)
        flat = [{"source": "signals", "verified": 1, "confidence": None, "ts": now}
                for _ in range(3)]
        self.assertAlmostEqual(sum(L.sample_weights(flat, as_of=now)) / 3, 1.0, places=6)




class TestPartialSchemas(unittest.TestCase):
    """The core DDL may be narrower or older than the documented one."""

    def test_signals_without_flags_or_net_edge(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " ts REAL, symbol TEXT, direction TEXT, score REAL, factors TEXT)")
        con.execute("CREATE TABLE outcomes (signal_id INTEGER, horizon TEXT,"
                    " ret_pct REAL, hit INTEGER)")
        con.execute("INSERT INTO signals (ts, symbol, direction, score, factors)"
                    " VALUES (?,?,?,?,?)",
                    (BASE.timestamp(), "BTCUSDT", "LONG", 61.0,
                     json.dumps({"whale": 0.5, "news": 0.1, "sentiment": -0.2})))
        con.execute("INSERT INTO outcomes VALUES (1,'1h',0.4,1)")
        cases = L.load_signals(con, "1h")
        self.assertEqual(len(cases), 1)
        self.assertAlmostEqual(cases[0]["factors"]["whale"], 0.5)
        self.assertEqual(cases[0]["factors"]["manip"], 0.0)
        self.assertEqual(cases[0]["label"], 1)
        payload = L.fit_weights(con, "1h", min_events=1)
        self.assertIn("whale", payload["weights"])

    def test_null_and_malformed_factor_json(self):
        con = new_db()
        con.execute("INSERT INTO signals (ts, symbol, direction, score, factors, flags)"
                    " VALUES (?,?,?,?,?,?)",
                    (BASE.timestamp(), "BTCUSDT", "LONG", 55.0, None, "[]"))
        con.execute("INSERT INTO signals (ts, symbol, direction, score, factors, flags)"
                    " VALUES (?,?,?,?,?,?)",
                    (BASE.timestamp() + DAY, "BTCUSDT", "LONG", 55.0,
                     "{not json", "not json"))
        con.execute("INSERT INTO outcomes (signal_id, horizon, ret_pct, hit)"
                    " VALUES (1,'1h',0.5,1), (2,'1h',-0.5,0)")
        con.commit()
        cases = L.load_signals(con, "1h")
        self.assertEqual(len(cases), 2)
        self.assertNotIn("whale", cases[0]["factors"])
        self.assertEqual(cases[0]["factors"]["manip"], 0.0)
        self.assertEqual(cases[0]["raw_factors"], {})
        self.assertEqual(cases[0]["label"], 1)
        # no factors anywhere -> fit falls back to the prior, no crash
        payload = L.fit_weights(con, "1h")
        self.assertEqual(payload["method"], "prior")
        out = L.predict(con, {"whale": 0.4}, "LONG", weights_payload=None)
        self.assertEqual(out["p_raw"], 0.5)

    def test_partial_research_ddl(self):
        con = new_db(with_core=False)
        con.execute("CREATE TABLE trade_cases (id TEXT PRIMARY KEY, outcome TEXT,"
                    " verified INTEGER)")
        con.execute("INSERT INTO trade_cases VALUES ('x','win',1)")
        cases = L.load_research_cases(con)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["label"], 1.0)
        self.assertIsNone(cases[0]["market"])


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------

class TestLogistic(unittest.TestCase):
    def test_recovers_known_coefficients(self):
        rng = random.Random(11)
        true = [1.2, -0.8, 0.0]
        X, y, sw = [], [], []
        for _ in range(4000):
            row = [rng.gauss(0, 1) for _ in true]
            eta = sum(b * v for b, v in zip(true, row))
            y.append(1.0 if rng.random() < sigmoid(eta) else 0.0)
            X.append(row)
            sw.append(1.0)
        fit = L.fit_logistic(X, y, sw, l2=0.5)
        self.assertTrue(fit["converged"])
        for got, want in zip(fit["coef"], true):
            self.assertAlmostEqual(got, want, delta=0.2)
        self.assertAlmostEqual(fit["intercept"], 0.0, delta=0.2)

    def test_separable_data_stays_finite(self):
        X = [[1.0], [2.0], [3.0], [4.0]]
        y = [0.0, 0.0, 1.0, 1.0]
        fit = L.fit_logistic(X, y, [1.0] * 4, l2=1.0)
        self.assertTrue(all(math.isfinite(v) for v in fit["coef"]))
        self.assertGreater(fit["coef"][0], 0.0)

    def test_singular_system_raises(self):
        with self.assertRaises(ValueError):
            L._solve([[0.0, 0.0], [0.0, 0.0]], [1.0, 1.0])


class TestWeights(unittest.TestCase):
    def test_predictive_factor_gains_weight(self):
        con = new_db()
        synth(con, n=400)
        payload = L.fit_weights(con, "1h")
        self.assertEqual(payload["method"], "logistic")
        self.assertGreater(payload["weights"]["whale"], 0.40)
        self.assertLess(payload["weights"]["sentiment"], 0.30)
        total = sum(abs(v) for v in payload["weights"].values())
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertAlmostEqual(sum(payload["weights_nonneg"].values()), 1.0, places=6)
        self.assertGreater(payload["alpha"]["whale"], 0.5)
        self.assertEqual(payload["n_events"], 400)
        self.assertIn("whale", payload["coef"])
        self.assertIn("whale", payload["center"])
        self.assertIn("whale", payload["scale"])

    def test_noise_corpus_stays_bounded(self):
        con = new_db()
        synth(con, n=300, whale_effect=0.0, news_effect=0.0, sentiment_effect=0.0,
              seed=3)
        payload = L.fit_weights(con, "1h")
        self.assertIn(payload["method"], ("logistic", "univariate"))
        for key, val in payload["weights"].items():
            self.assertTrue(math.isfinite(val))
            self.assertLessEqual(abs(val), 1.0)
            self.assertIn(key, ("whale", "news", "sentiment"))
        self.assertLess(abs(payload["weights"]["whale"] - 0.40), 0.45)

    def test_insufficient_data_returns_prior(self):
        con = new_db()
        synth(con, n=8)
        payload = L.fit_weights(con, "1h", min_events=50)
        self.assertEqual(payload["method"], "prior")
        self.assertAlmostEqual(payload["weights"]["whale"], 0.40, places=6)
        self.assertIn("reason", payload["diagnostics"])

    def test_univariate_fallback_when_multivariate_fails(self):
        con = new_db()
        synth(con, n=200)
        original = L.fit_logistic
        calls = {"n": 0}

        def flaky(X, y, sw, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("singular matrix")
            return original(X, y, sw, **kw)

        L.fit_logistic = flaky
        try:
            payload = L.fit_weights(con, "1h")
        finally:
            L.fit_logistic = original
        self.assertEqual(payload["method"], "univariate")
        self.assertIn("multivariate_error", payload["diagnostics"])

    def test_weights_artifact_roundtrip_and_drift(self):
        con = new_db()
        synth(con, n=200)
        payload = L.fit_weights(con, "1h")
        L.save_weights(con, payload)
        loaded = L.load_weights(con, horizon="1h")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["method"], payload["method"])
        self.assertEqual(loaded["weights"]["whale"], payload["weights"]["whale"])
        drift = L.weight_drift({"whale": 0.4, "news": 0.3, "sentiment": 0.3},
                              {"whale": 0.6, "news": 0.3, "sentiment": 0.1})
        self.assertAlmostEqual(drift["l1"], 0.4, places=6)
        self.assertAlmostEqual(drift["max"], 0.2, places=6)
        self.assertIsNone(L.weight_drift(None, {"whale": 1.0}))

    def test_apply_weights_never_writes_without_a_core_writer(self):
        con = new_db()
        original = L._signals_module
        L._signals_module = lambda: None
        try:
            out = L.apply_weights(con, {"whale": 0.5, "news": 0.3, "sentiment": 0.2})
        finally:
            L._signals_module = original
        self.assertFalse(out["applied"])
        self.assertIn("no weight writer", out["reason"])
        rows = dict(con.execute("SELECT k, v FROM weights").fetchall())
        self.assertEqual(rows, {"whale": 0.4, "news": 0.3, "sentiment": 0.3})

    def test_apply_weights_uses_the_core_writer(self):
        con = new_db()
        seen = {}

        class FakeSignals:
            @staticmethod
            def save_weights(connection, mapping):
                seen.update(mapping)

        original = L._signals_module
        L._signals_module = lambda: FakeSignals
        try:
            out = L.apply_weights(con, {"whale": 0.5, "news": 0.3, "sentiment": 0.2})
        finally:
            L._signals_module = original
        self.assertTrue(out["applied"])
        self.assertEqual(seen, {"whale": 0.5, "news": 0.3, "sentiment": 0.2})

    def test_apply_weights_dry_run(self):
        con = new_db()
        out = L.apply_weights(con, {"whale": 0.5}, dry_run=True)
        self.assertFalse(out["applied"])
        self.assertEqual(out["reason"], "dry_run")

    def test_load_core_weights_defaults_and_table(self):
        con = new_db()
        self.assertEqual(L.load_core_weights(con)["whale"], 0.4)
        con.execute("UPDATE weights SET v = 0.8 WHERE k = 'whale'")
        con.commit()
        got = L.load_core_weights(con)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=6)
        self.assertGreater(got["whale"], 0.4)


# ---------------------------------------------------------------------------
# metrics and calibration
# ---------------------------------------------------------------------------

class TestMetrics(unittest.TestCase):
    PAIRS = [(0.9, 1), (0.8, 0), (0.3, 0), (0.6, 1)]

    def test_brier_logloss_accuracy(self):
        self.assertAlmostEqual(L.brier(self.PAIRS), 0.225, places=6)
        self.assertAlmostEqual(L.accuracy(self.PAIRS), 0.75, places=6)
        expect = -(math.log(0.9) + math.log(0.2) + math.log(0.7) + math.log(0.6)) / 4
        self.assertAlmostEqual(L.log_loss(self.PAIRS), expect, places=6)

    def test_auc(self):
        self.assertAlmostEqual(L.auc(self.PAIRS), 0.75, places=6)
        self.assertAlmostEqual(L.auc([(0.5, 1), (0.5, 0)]), 0.5, places=6)
        self.assertIsNone(L.auc([(0.5, 1), (0.6, 1)]))

    def test_reliability_and_ece(self):
        # p=0.1 that really hits 10% of the time -> that bin is calibrated
        pairs = [(0.1, 0)] * 90 + [(0.1, 1)] * 10
        self.assertAlmostEqual(L.ece(pairs), 0.0, places=6)
        bins = L.reliability(pairs, bins=10)
        self.assertEqual(len(bins), 1)
        self.assertAlmostEqual(bins[0]["pred"], 0.1, places=6)
        self.assertAlmostEqual(bins[0]["obs"], 0.1, places=6)
        # claims 90%, delivers 20% -> 0.7 miscalibration
        bad = [(0.9, 0)] * 80 + [(0.9, 1)] * 20
        self.assertAlmostEqual(L.ece(bad), 0.7, places=6)
        two = [(0.1, 0)] * 50 + [(0.9, 1)] * 50
        self.assertAlmostEqual(L.ece(two), 0.1, places=6)

    def test_summarize_shape(self):
        s = L.summarize(self.PAIRS)
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["positives"], 2)
        self.assertAlmostEqual(s["base_rate"], 0.5)
        self.assertEqual(L.summarize([])["n"], 0)
        self.assertIsNone(L.summarize([])["brier"])

    def test_clean_pairs_clips_and_drops(self):
        pairs = L._clean_pairs([(0.0, 1), (1.0, 0), (None, 1), (0.5, None)])
        self.assertEqual(len(pairs), 2)
        self.assertGreater(pairs[0][0], 0.0)
        self.assertLess(pairs[1][0], 1.0)


class TestCalibration(unittest.TestCase):
    def test_isotonic_is_monotone_on_noisy_data(self):
        pairs = [(0.1, 1), (0.2, 1), (0.3, 0), (0.5, 1), (0.6, 0), (0.8, 0), (0.9, 1)]
        knots = L.fit_isotonic(pairs)
        ys = [y for _, y in knots]
        self.assertEqual(ys, sorted(ys))
        self.assertGreaterEqual(len(knots), 2)

    def test_apply_isotonic_clamps_and_interpolates(self):
        knots = [[0.2, 0.1], [0.8, 0.7]]
        self.assertAlmostEqual(L.apply_isotonic(knots, 0.0), 0.1)
        self.assertAlmostEqual(L.apply_isotonic(knots, 1.0), 0.7)
        self.assertAlmostEqual(L.apply_isotonic(knots, 0.5), 0.4, places=6)
        self.assertAlmostEqual(L.apply_isotonic([], 0.42), 0.42)

    def test_isotonic_constant_target(self):
        knots = L.fit_isotonic([(0.3, 1), (0.4, 1), (0.5, 1)])
        self.assertAlmostEqual(L.apply_isotonic(knots, 0.35), 1.0, places=6)

    def test_platt_fixes_overconfidence(self):
        rng = random.Random(5)
        pairs = []
        for _ in range(600):
            p = rng.uniform(0.55, 0.95)
            pairs.append((p, 1 if rng.random() < 0.5 else 0))
        before = L.brier(pairs)
        model = L.fit_calibration_model(pairs, min_n_isotonic=10_000)
        self.assertEqual(model["method"], "platt")
        after = L.brier([(L.apply_calibration(model, p), y) for p, y in pairs])
        self.assertLess(after, before)
        self.assertLess(L.apply_calibration(model, 0.9), 0.9)

    def test_model_choice_by_rule(self):
        rng = random.Random(2)
        big = [(rng.random(), rng.randint(0, 1)) for _ in range(200)]
        self.assertEqual(L.fit_calibration_model(big, choose="rule")["method"], "isotonic")
        small = [(rng.random(), rng.randint(0, 1)) for _ in range(30)]
        self.assertEqual(L.fit_calibration_model(small, choose="rule")["method"], "platt")
        tiny = [(0.5, 1), (0.6, 0)]
        self.assertEqual(L.fit_calibration_model(tiny, choose="rule")["method"], "identity")
        self.assertEqual(L.apply_calibration({"method": "identity"}, 0.3), 0.3)

    def test_holdout_choice_keeps_a_calibrated_score_alone(self):
        rng = random.Random(9)
        pairs = []
        for _ in range(400):
            p = rng.uniform(0.2, 0.8)
            pairs.append((p, 1 if rng.random() < p else 0))
        model = L.fit_calibration_model(pairs)
        self.assertEqual(model["method"], "identity")
        self.assertIn("holdout", model)

    def test_holdout_choice_accepts_a_fix_when_one_is_needed(self):
        rng = random.Random(4)
        pairs = []
        for _ in range(400):
            p = rng.uniform(0.6, 0.99)
            pairs.append((p, 1 if rng.random() < 0.35 else 0))
        model = L.fit_calibration_model(pairs)
        self.assertIn(model["method"], ("platt", "isotonic"))
        self.assertLess(L.apply_calibration(model, 0.9), 0.75)

    def test_fit_calibration_payload_and_store(self):
        con = new_db()
        synth(con, n=300)
        payload = L.fit_calibration(con, "1h")
        self.assertEqual(payload["evaluation"], "in_sample")
        self.assertIn(payload["method"], ("isotonic", "platt", "identity"))
        # the honest claim is only that calibration does not make it worse
        self.assertLessEqual(payload["after"]["brier"], payload["before"]["brier"] + 1e-9)
        L.save_calibration(con, payload)
        loaded = L.load_calibration(con, horizon="1h")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["method"], payload["method"])
        self.assertIsNone(L.load_calibration(con, horizon="24h"))


# ---------------------------------------------------------------------------
# walk-forward
# ---------------------------------------------------------------------------

class TestWalkForward(unittest.TestCase):
    def test_insufficient_data(self):
        con = new_db()
        synth(con, n=20)
        report = L.walk_forward(con, "1h", folds=5, min_train_cases=40, persist=False)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertFalse(report["promotion"]["recommend"])
        self.assertEqual(report["corpus"]["n_closed"], 20)

    def test_folds_are_time_ordered_and_embargoed(self):
        con = new_db()
        synth(con, n=300)
        report = L.walk_forward(con, "1h", folds=4, min_train_cases=60,
                                embargo_days=2.0, persist=False)
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["leakage"]["ok"])
        scored = [f for f in report["folds"] if f.get("metrics")]
        self.assertGreaterEqual(len(scored), 3)
        for fold in scored:
            train_end = datetime.strptime(fold["train_ts"][1], "%Y-%m-%dT%H:%M:%SZ")
            test_start = datetime.strptime(fold["test_ts"][0], "%Y-%m-%dT%H:%M:%SZ")
            self.assertLess(train_end, test_start)
            self.assertGreaterEqual((test_start - train_end).total_seconds(),
                                    2.0 * DAY - 1)

    def test_learned_loop_beats_the_baseline_out_of_fold(self):
        con = new_db()
        synth(con, n=400, whale_effect=1.8, news_effect=0.9)
        report = L.walk_forward(con, "1h", folds=4, min_train_cases=100,
                                persist=False)
        self.assertEqual(report["status"], "ok")
        pooled = report["pooled"]
        self.assertGreater(pooled["learned"]["n"], 100)
        self.assertLess(pooled["learned"]["brier"], pooled["base_raw"]["brier"])
        self.assertGreater(report["improvement"]["brier"], 0.0)
        self.assertLessEqual(pooled["learned"]["brier"], pooled["base_cal"]["brier"])
        self.assertTrue(report["promotion"]["recommend"])
        self.assertIsNotNone(report["weight_stability"]["whale"])

    def test_persists_predictions_and_run(self):
        con = new_db()
        synth(con, n=320)
        report = L.walk_forward(con, "1h", folds=3, min_train_cases=80,
                                run_id="wf-test-1")
        self.assertEqual(report["run_id"], "wf-test-1")
        n_pred = con.execute("SELECT count(*) FROM learning_predictions"
                             " WHERE run_id = ?", ("wf-test-1",)).fetchone()[0]
        self.assertEqual(n_pred, report["pooled"]["learned"]["n"])
        stored = L.load_run(con, run_id="wf-test-1")
        self.assertEqual(stored["kind"], "walk_forward")
        self.assertEqual(stored["status"], "ok")

    def test_rolling_window_mode(self):
        con = new_db()
        synth(con, n=320)
        report = L.walk_forward(con, "1h", folds=3, min_train_cases=100,
                                mode="rolling", rolling_days=30, persist=False)
        self.assertEqual(report["status"], "ok")
        for fold in [f for f in report["folds"] if f.get("metrics")]:
            self.assertLessEqual(fold["train_n"], 100)

    def test_deterministic_for_the_same_corpus(self):
        con = new_db()
        synth(con, n=260, seed=42)
        a = L.walk_forward(con, "1h", folds=3, min_train_cases=80, persist=False)
        b = L.walk_forward(con, "1h", folds=3, min_train_cases=80, persist=False)
        self.assertEqual(a["pooled"]["learned"]["brier"], b["pooled"]["learned"]["brier"])
        fa = [f for f in a["folds"] if f.get("metrics")][0]
        fb = [f for f in b["folds"] if f.get("metrics")][0]
        self.assertEqual(fa["weights"], fb["weights"])
        self.assertEqual(fa["metrics"], fb["metrics"])


class TestSignificance(unittest.TestCase):
    def test_paired_gain_detects_a_real_edge(self):
        base = [(0.5, y) for y in ([1, 0] * 50)]
        good = [(0.9 if y == 1 else 0.1, y) for _, y in base]
        out = L.paired_gain(good, base)
        self.assertEqual(out["n"], 100)
        self.assertGreater(out["mean_gain"], 0.0)
        self.assertTrue(out["significant"])
        self.assertGreater(out["z"], 1.645)

    def test_paired_gain_rejects_noise(self):
        base = [(0.5, y) for y in ([1, 0] * 50)]
        worse = [(0.5, y) for _, y in base]
        out = L.paired_gain(worse, base)
        self.assertAlmostEqual(out["mean_gain"], 0.0)
        self.assertFalse(out["significant"])
        self.assertFalse(L.paired_gain([], [])["significant"])

    def test_noise_corpus_is_not_promoted(self):
        con = new_db()
        synth(con, n=240, whale_effect=0.0, news_effect=0.0, sentiment_effect=0.0,
              seed=17)
        report = L.walk_forward(con, "1h", folds=4, min_train_cases=80,
                                persist=False)
        self.assertEqual(report["status"], "ok")
        self.assertIn("significance", report)
        self.assertFalse(report["promotion"]["recommend"])


# ---------------------------------------------------------------------------
# predict / run / digest
# ---------------------------------------------------------------------------

class TestPredict(unittest.TestCase):
    def test_alignment_invariant(self):
        con = new_db()
        synth(con, n=300)
        payload = L.fit_weights(con, "1h")
        long_call = L.predict(con, {"whale": 0.8, "news": 0.2, "sentiment": -0.1},
                              "LONG", weights_payload=payload)
        short_call = L.predict(con, {"whale": -0.8, "news": -0.2, "sentiment": 0.1},
                               "SHORT", weights_payload=payload)
        self.assertAlmostEqual(long_call["p_raw"], short_call["p_raw"], places=9)
        self.assertAlmostEqual(long_call["aligned_factors"]["whale"], 0.8)
        self.assertAlmostEqual(short_call["aligned_factors"]["whale"], 0.8)

    def test_falls_back_to_score_without_weights(self):
        con = new_db()
        out = L.predict(con, {"whale": 0.5}, "LONG")
        self.assertEqual(out["p_raw"], 0.5)
        self.assertIsNone(out["weights_created_at"])

    def test_probability_is_bounded(self):
        con = new_db()
        payload = {"intercept": 0.0, "coef": {"whale": 3.0}, "center": {"whale": 0.0},
                   "scale": {"whale": 0.01}}
        out = L.predict(con, {"whale": 1.0}, "LONG", weights_payload=payload)
        self.assertGreater(out["p_raw"], 0.99)
        self.assertLessEqual(out["p_calibrated"], 1.0)


class TestRun(unittest.TestCase):
    def test_end_to_end(self):
        con = new_db()
        synth(con, n=360)
        add_research(con, "r1", "win", verified=1, confidence=0.8)
        add_research(con, "r2", "loss", verified=0, confidence=0.9, why="chased a wick")
        summary = L.run(con, horizon="1h", folds=3, min_train_cases=100)
        self.assertEqual(summary["walk_forward"]["status"], "ok")
        self.assertIsNotNone(summary["weights"]["weights"]["whale"])
        self.assertEqual(summary["research_rows_synced"], 2)
        self.assertIsNone(summary["applied"])
        for table in (L.WEIGHTS_TABLE, L.CALIBRATION_TABLE, L.RUNS_TABLE):
            self.assertGreater(con.execute("SELECT count(*) FROM %s" % table).fetchone()[0], 0)

    def test_empty_database_reports_instead_of_raising(self):
        con = sqlite3.connect(":memory:")
        summary = L.run(con, horizon="1h")
        self.assertEqual(summary["weights"]["method"], "prior")
        self.assertEqual(summary["walk_forward"]["status"], "insufficient_data")
        self.assertTrue(any("prior" in w for w in summary["warnings"]))
        self.assertEqual(summary["outcome_consistency"]["n"], 0)

    def test_promote_refused_when_gate_fails(self):
        con = new_db()
        synth(con, n=120, whale_effect=0.0, news_effect=0.0, sentiment_effect=0.0)
        summary = L.run(con, horizon="1h", folds=3, min_train_cases=40, promote=True)
        # nothing is ever written without the gate, and nothing at all without
        # a core writer: either way the core table is untouched
        self.assertTrue(summary["applied"] is None
                        or summary["applied"]["applied"] is False)
        rows = dict(con.execute("SELECT k, v FROM weights").fetchall())
        self.assertEqual(rows, {"whale": 0.4, "news": 0.3, "sentiment": 0.3})
        self.assertTrue(any("promotion" in w for w in summary["warnings"]))


class TestResearchDigest(unittest.TestCase):
    def test_win_rates_verified_and_losses(self):
        con = new_db(with_core=False)
        add_research(con, "a", "win", verified=1, confidence=0.9)
        add_research(con, "b", "win", verified=0, confidence=0.9)
        add_research(con, "c", "win", verified=0, confidence=0.8)
        add_research(con, "d", "loss", verified=0, confidence=0.95, why="entered late")
        add_research(con, "e", "loss", verified=1, confidence=0.6, why="regime flipped")
        add_research(con, "f", "open", verified=0, confidence=0.7)
        digest = L.research_digest(con)
        self.assertEqual(digest["n_rows"], 6)
        self.assertEqual(digest["n_closed"], 5)
        self.assertEqual(digest["n_open_or_flat"], 1)
        self.assertAlmostEqual(digest["win_rate"], 0.6, places=6)
        self.assertEqual(digest["verified"]["n"], 2)
        self.assertAlmostEqual(digest["verified"]["win_rate"], 0.5, places=6)
        self.assertAlmostEqual(digest["unverified"]["win_rate"], 2 / 3, places=6)
        self.assertEqual(len(digest["losses_with_reasons"]), 2)
        self.assertEqual(digest["losses_with_reasons"][0]["why_what"], "entered late")
        self.assertIn("survivorship", digest["caveat"])
        self.assertGreater(digest["stated_confidence"]["gap"], 0.2)
        self.assertEqual(digest["n_sources"], 6)

    def test_empty_corpus(self):
        con = new_db(with_core=False)
        digest = L.research_digest(con)
        self.assertEqual(digest["n_rows"], 0)
        self.assertIsNone(digest["win_rate"])


class TestConsistency(unittest.TestCase):
    def test_detects_hit_return_disagreement(self):
        con = new_db()
        add_signal(con, BASE.timestamp(), "LONG",
                   {"whale": 0.1, "news": 0.1, "sentiment": 0.1}, 60.0, hit=1,
                   ret_pct=-2.0)
        add_signal(con, BASE.timestamp() + DAY, "LONG",
                   {"whale": 0.1, "news": 0.1, "sentiment": 0.1}, 60.0, hit=1,
                   ret_pct=1.0)
        out = L.outcome_consistency(con, "1h")
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["mismatches"], 1)
        self.assertAlmostEqual(out["rate"], 0.5)
        self.assertEqual(out["examples"][0]["direction"], "LONG")


if __name__ == "__main__":
    unittest.main(verbosity=2)
