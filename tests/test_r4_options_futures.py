import json, os, unittest
P=os.path.join(os.path.dirname(__file__),"..","research","cases","options_futures.json")
F=["source_url","market","outcome","why_what","how","where_ctx","verified","confidence"]
class T(unittest.TestCase):
    def setUp(self): self.c=json.load(open(P))
    def test_count(self): self.assertGreaterEqual(len(self.c),30)
    def test_fields(self):
        for x in self.c:
            for f in F: self.assertIn(f,x)
            self.assertTrue(x["source_url"].startswith("http"))
            self.assertTrue(0<=x["confidence"]<=1); self.assertEqual(x["verified"],0)
    def test_unique(self): self.assertEqual(len({x["source_url"] for x in self.c}),len(self.c))
    def test_has_losses(self): self.assertTrue(any("loss" in x["outcome"] for x in self.c))
if __name__=="__main__": unittest.main()
