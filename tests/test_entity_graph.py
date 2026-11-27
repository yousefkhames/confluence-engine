import sqlite3, sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from confluence import entity_graph as eg

def mk(rows):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE whale_tx(tx_hash,chain,ts,from_addr,to_addr,token,amount_usd)")
    con.executemany("INSERT INTO whale_tx VALUES(?,?,?,?,?,?,?)", rows)
    return con

class T(unittest.TestCase):
    def test_common_funder(self):
        con = mk([("1","eth",10,"F","A","usdc",1000),("2","eth",20,"F","B","usdc",900)])
        eg.build(con)
        self.assertEqual(eg.cluster_of(con,"a")[0], eg.cluster_of(con,"b")[0])
    def test_hub_not_merged(self):
        rows=[("%d"%i,"eth",i,"EX","W%d"%i,"usdc",500) for i in range(5)]
        con = mk(rows); eg.build(con, hubs=["ex"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM entity_clusters").fetchone()[0],0)
    def test_bridge_match_and_ambiguity(self):
        con = mk([("i","eth",100,"W1","BR","usdc",10000),("o","arb",400,"BR","W2","usdc",9980)])
        eg.build(con, bridges=["br"])
        self.assertEqual(eg.cluster_of(con,"w1")[0], eg.cluster_of(con,"w2")[0])
        con = mk([("i","eth",100,"W1","BR","usdc",10000),("o","arb",400,"BR","W2","usdc",9990),
                  ("o2","arb",410,"BR","W3","usdc",9985)])
        eg.build(con, bridges=["br"])
        self.assertIsNone(eg.cluster_of(con,"w1"))
    def test_peel_trail(self):
        con = mk([("1","eth",10,"ORG","P1","eth",1000),("2","eth",100,"P1","P2","eth",950),
                  ("3","eth",200,"P2","P3","eth",900)])
        eg.build(con, trail_origins=["ORG"])
        n = con.execute("SELECT COUNT(*) FROM entity_trails WHERE kind='peel'").fetchone()[0]
        self.assertEqual(n, 2)
    def test_stealth_not_merged(self):
        con = mk([("a","eth",1,"F1","S1","eth",5),("b","eth",2,"F2","S2","eth",5),("1","eth",10,"ORG","S1","eth",1000),("2","eth",60,"ORG","S2","eth",1010)])
        s = eg.build(con, trail_origins=["ORG"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM entity_trails WHERE kind='stealth'").fetchone()[0],2)
        self.assertEqual(s["clusters"], 0)
        self.assertEqual(eg.cluster_of(con,"org")[1],1)
    def test_sweep(self):
        con = mk([("%d"%i,"eth",i,"D%d"%i,"C","usdc",100) for i in range(3)])
        eg.build(con)
        self.assertEqual(eg.cluster_of(con,"d0")[0], eg.cluster_of(con,"c")[0])
    def test_activity(self):
        con = mk([("1","eth",10,"F","A","u",100),("2","eth",20,"F","B","u",50),("3","eth",30,"A","X","u",20)])
        eg.build(con)
        self.assertEqual(eg.entity_activity(con,"A")["size"], 2)

if __name__ == "__main__": unittest.main()
