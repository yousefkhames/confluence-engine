"""Contract checks per workstream, from the shared contract:
- confluence/adapters/<name>.py exposes fetch(con)->int
- trade_cases table has the agreed fields and sane rows
- offline: importing adapters must not open sockets.
Skips cleanly when the core (db.py) or adapters are not yet merged."""
import importlib, os, socket, sqlite3, sys, unittest, pkgutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIELDS = {"id", "collected_at", "source_type", "source_url", "market", "instrument", "side", "entry_ts", "entry_price", "exit_price", "size_note", "outcome", "pnl_note", "why_what", "how", "where_ctx", "lesson", "verified", "confidence", "tags"}


def adapter_names():
    d = os.path.join(ROOT, "confluence", "adapters")
    if not os.path.isdir(d):
        return []
    return sorted(m.name for m in pkgutil.iter_modules([d]) if not m.name.startswith("_"))


class BlockNet:
    def __enter__(self):
        self._c, self._g = socket.socket.connect, socket.getaddrinfo
        def deny(*a, **k):
            raise AssertionError("network access attempted during offline test")
        socket.socket.connect = deny
        socket.getaddrinfo = deny
    def __exit__(self, *a):
        socket.socket.connect, socket.getaddrinfo = self._c, self._g


class Adapters(unittest.TestCase):
    def test_import_offline_and_fetch_exposed(self):
        names = adapter_names()
        if not names:
            self.skipTest("no adapters yet")
        for n in names:
            with BlockNet():
                m = importlib.import_module(f"confluence.adapters.{n}")
            self.assertTrue(callable(getattr(m, "fetch", None)), f"confluence.adapters.{n}.fetch missing")


class TradeCases(unittest.TestCase):
    def setUp(self):
        try:
            self.db = importlib.import_module("confluence.db")
        except ImportError:
            self.skipTest("core db.py not present")

    def test_schema_and_rows(self):
        con = self.db.connect()
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(trade_cases)")}
        except sqlite3.Error:
            self.skipTest("trade_cases not created")
        if not cols:
            self.skipTest("trade_cases not created")
        self.assertTrue(FIELDS <= cols, f"missing columns: {FIELDS - cols}")
        bad = []
        for r in con.execute("SELECT source_url, market, outcome, why_what, how, where_ctx, verified, confidence FROM trade_cases"):
            url, market, outcome, why, how, where, ver, conf = r
            if not (url or "").startswith(("http://", "https://")):
                bad.append(("no source_url", url))
            if not market or not outcome:
                bad.append(("market/outcome empty", url))
            if not why:
                bad.append(("no why_what", url))
            if conf is None or (isinstance(conf, (int, float)) and not 0 <= conf <= 1) :
                bad.append(("confidence not in 0..1", url))
            if ver in (1, True, "1", "true") and not how:
                bad.append(("verified without how", url))
        self.assertEqual(bad, [])

    def test_losses_have_why(self):
        con = self.db.connect()
        try:
            rows = con.execute("SELECT source_url, outcome, why_what FROM trade_cases").fetchall()
        except sqlite3.Error:
            self.skipTest("trade_cases not created")
        bad = [u for u, o, w in rows if "loss" in (o or "").lower() and len((w or "").strip()) < 20]
        self.assertEqual(bad, [], "losses need a real why")

    def test_survivorship_balance(self):
        con = self.db.connect()
        try:
            rows = con.execute("SELECT outcome FROM trade_cases").fetchall()
        except sqlite3.Error:
            self.skipTest("trade_cases not created")
        if len(rows) < 10:
            self.skipTest("too few cases to judge")
        losses = sum("loss" in (r[0] or "").lower() for r in rows)
        self.assertGreater(losses / len(rows), 0.15, "case base looks survivorship-biased (few losses)")


if __name__ == "__main__":
    unittest.main()
