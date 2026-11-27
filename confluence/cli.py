import argparse, json, time, sys
from . import db, config
from .wallets import profile_wallets, cluster_entities, insider_scan

def main(argv=None):
    ap = argparse.ArgumentParser(prog="confluence", description="Confluence Engine (paper signals only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo-data", help="fill DB with SYNTHETIC data")
    sub.add_parser("ingest", help="pull live public data once")
    sc = sub.add_parser("scan"); sc.add_argument("--threshold", type=float); sc.add_argument("--now", type=float)
    sub.add_parser("outcomes"); sub.add_parser("profile"); sub.add_parser("reweight"); sub.add_parser("verify")
    bt = sub.add_parser("backtest"); bt.add_argument("--threshold", type=float, default=None)
    ds = sub.add_parser("dashboard"); ds.add_argument("--port", type=int, default=8080)
    tk = sub.add_parser("token"); tk.add_argument("tier", choices=list(config.TIERS))
    ask = sub.add_parser("ask"); ask.add_argument("question", nargs="+")
    a = ap.parse_args(argv)
    con = db.connect()
    if a.cmd == "demo-data":
        from .demo import generate
        info = generate(con); print(json.dumps({k: info[k] for k in ("start", "end")}))
    elif a.cmd == "ingest":
        from .ingest import run_once; print(run_once(con))
    elif a.cmd == "scan":
        from .signals import scan; from .alerts import send
        now = a.now or (con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"])
        for s in scan(con, now, a.threshold): send(s)
    elif a.cmd == "outcomes":
        from .signals import evaluate_outcomes, track_record
        now = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
        print(evaluate_outcomes(con, now), json.dumps(track_record(con), indent=1))
    elif a.cmd == "profile":
        p = profile_wallets(con); print(len(p), "wallets;", json.dumps(cluster_entities(con))); print(insider_scan(con))
    elif a.cmd == "reweight":
        from .signals import reweight; print(reweight(con))
    elif a.cmd == "verify":
        from .signals import verify_chain; print(verify_chain(con))
    elif a.cmd == "backtest":
        from .backtest import run
        end = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]; start = con.execute("SELECT MIN(ts) t FROM prices").fetchone()["t"]
        split = start + int((end - start) * 0.5)
        print(json.dumps(run(con, split, end - 86400 // 4, threshold=a.threshold), indent=1))
    elif a.cmd == "dashboard":
        from .dashboard import serve; serve(a.port)
    elif a.cmd == "token":
        from .tiers import issue_token; print(issue_token(con, a.tier))
    elif a.cmd == "ask":
        from .ask import answer; print(answer(con, " ".join(a.question)))

if __name__ == "__main__":
    main()
