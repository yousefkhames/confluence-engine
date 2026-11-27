import json, sqlite3, unittest, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from confluence.adapters import binary_cases
class T(unittest.TestCase):
    def setUp(self): self.d = json.load(open(ROOT / "research/cases/binary.json"))
    def test_count(self): self.assertGreaterEqual(len(self.d["trade_cases"]), 30)
    def test_fields_and_rules(self):
        for c in self.d["trade_cases"]:
            for k in ("source_url","market","outcome","why_what","how","where_ctx"):
                self.assertTrue(c[k], k)
            self.assertTrue(c["source_url"].startswith("http"))
            if not c["verified"]: self.assertLessEqual(c["confidence"], 0.4)
    def test_bias_and_losses(self):
        self.assertTrue(self.d["survivorship_bias_note"])
        self.assertTrue(any("loss" in c["outcome"] for c in self.d["trade_cases"]))
    def test_adapter(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE trade_cases(id TEXT PRIMARY KEY, collected_at REAL, source_type, source_url, market, instrument, side, entry_ts, entry_price, exit_price, size_note, outcome, pnl_note, why_what, how, where_ctx, lesson, verified INTEGER DEFAULT 0, confidence REAL, tags)")
        n = binary_cases.fetch(con)
        self.assertEqual(n, len(self.d["trade_cases"]))
        self.assertEqual(binary_cases.fetch(con), n)
        self.assertEqual(con.execute("select count(*) from trade_cases").fetchone()[0], n)
if __name__ == "__main__": unittest.main()
