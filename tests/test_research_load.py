import unittest, sqlite3, json, os, tempfile
from confluence import db
from confluence.research.load import load

class T(unittest.TestCase):
    def test_load_and_reject(self):
        con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row; con.executescript(db.SCHEMA)
        d = tempfile.mkdtemp()
        json.dump([{"source_url": "https://x.example/a", "market": "crypto", "outcome": "loss", "why_what": "w", "how": "h",
                    "where_ctx": "c", "source_type": "self_reported", "confidence": 0.9},
                   {"source_url": "", "market": "crypto", "outcome": "win", "why_what": "w", "how": "h", "where_ctx": "c"}],
                  open(d + "/a.json", "w"))
        r = load(con, d + "/*.json")
        self.assertEqual((r["loaded"], r["rejected"]), (1, 1))
        self.assertLessEqual(con.execute("SELECT confidence c FROM trade_cases").fetchone()["c"], 0.4)

if __name__ == "__main__": unittest.main()
