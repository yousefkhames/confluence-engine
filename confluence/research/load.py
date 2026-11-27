"""Load research/cases/*.json into the trade_cases table. Enforces the contract: source_url, market, outcome,
why_what, how, where_ctx required; self-reported/unverified rows capped at confidence 0.4."""
import json, glob, hashlib, time, sys
from .. import db

REQ = ("source_url", "market", "outcome", "why_what", "how", "where_ctx")
COLS = ("source_type", "source_url", "market", "instrument", "side", "entry_ts", "entry_price", "exit_price", "size_note",
        "outcome", "pnl_note", "why_what", "how", "where_ctx", "lesson", "verified", "confidence", "tags")

def load(con, pattern="research/cases/*.json"):
    ok = bad = 0; problems = []
    for path in sorted(glob.glob(pattern)):
        data = json.load(open(path)); data = data if isinstance(data, list) else (data.get("cases") or data.get("trade_cases") or [])
        for i, c in enumerate(data):
            miss = [k for k in REQ if not c.get(k)]
            if miss or not str(c["source_url"]).startswith(("http://", "https://", "own:")):
                bad += 1; problems.append((path, i, miss or "bad url")); continue
            c = dict(c); c.setdefault("verified", 0)
            conf = float(c.get("confidence") or 0.3)
            if not c["verified"] and c.get("source_type") in ("self_reported", "forum", "social", "own_demo", None): conf = min(conf, 0.4)
            c["confidence"] = conf
            cid = hashlib.md5((c["source_url"] + c["why_what"][:80]).encode()).hexdigest()
            row = [c.get(k) if not isinstance(c.get(k), (list, dict)) else json.dumps(c.get(k)) for k in COLS]
            con.execute(f"INSERT OR REPLACE INTO trade_cases VALUES(?,?,{','.join('?'*len(COLS))})", [cid, time.time()] + row)
            ok += 1
    con.commit(); return {"loaded": ok, "rejected": bad, "problems": problems[:10]}

if __name__ == "__main__":
    print(load(db.connect()))
