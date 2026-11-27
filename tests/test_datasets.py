import csv, json, os, sqlite3, tempfile, unittest
from confluence import datasets


def mkcon():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE trade_cases(id INTEGER PRIMARY KEY, source_url TEXT, market TEXT, outcome TEXT, why_what TEXT, how TEXT, where_ctx TEXT, verified INTEGER, confidence TEXT)")
    con.execute("CREATE TABLE creds(id INTEGER PRIMARY KEY, name TEXT, api_key TEXT)")
    con.execute("INSERT INTO trade_cases VALUES(1,'https://x.test','BTC','loss','why, with comma','how \"q\"','ctx',0,'low')")
    con.execute("INSERT INTO trade_cases VALUES(2,'https://y.test','ES','win',NULL,NULL,NULL,0,'medium')")
    con.execute("INSERT INTO creds VALUES(1,'a','SECRET')")
    return con


class T(unittest.TestCase):
    def test_export(self):
        con = mkcon()
        with tempfile.TemporaryDirectory() as d:
            m = datasets.export_all(con, d, version="v1")
            o = os.path.join(d, "v1")
            self.assertEqual([t["table"] for t in m["tables"]], ["creds", "trade_cases"])
            rows = [json.loads(l) for l in open(os.path.join(o, "trade_cases.jsonl"))]
            self.assertEqual(len(rows), 2)
            self.assertIsNone(rows[1]["how"])
            self.assertEqual(list(csv.reader(open(os.path.join(o, "trade_cases.csv"), newline="")))[1][4], "why, with comma")
            self.assertNotIn("api_key", open(os.path.join(o, "creds.jsonl")).read())
            self.assertNotIn("SECRET", open(os.path.join(o, "creds.csv")).read())
            md = open(os.path.join(o, "DATA_DICTIONARY.md")).read()
            self.assertIn("survivorship", md)
            self.assertEqual(datasets.verify(o), [])
            with self.assertRaises(FileExistsError):
                datasets.export_all(con, d, version="v1")

    def test_deterministic_and_tamper(self):
        con = mkcon()
        with tempfile.TemporaryDirectory() as d:
            a = datasets.export_all(con, d, version="a")
            b = datasets.export_all(con, d, version="b")
            self.assertEqual(a["content_id"], b["content_id"])
            open(os.path.join(d, "a", "trade_cases.csv"), "a").write("x")
            self.assertTrue(datasets.verify(os.path.join(d, "a")))


if __name__ == "__main__":
    unittest.main()
