"""Load the R5 binary/short-expiry case file into trade_cases. Offline, no network."""
import json, time
from pathlib import Path
DEFAULT = Path(__file__).resolve().parents[2] / "research/cases/binary.json"
COLS = ("id","collected_at","source_type","source_url","market","instrument","side","outcome","pnl_note","why_what","how","where_ctx","lesson","verified","confidence","tags")
def init(con):
    pass  # trade_cases is owned by core
def fetch(con, path=None):
    data = json.load(open(path or DEFAULT))
    n = 0
    now = time.time()
    for r in data["trade_cases"]:
        r = dict(r, collected_at=now)
        con.execute("INSERT OR REPLACE INTO trade_cases (%s) VALUES (%s)" % (",".join(COLS), ",".join("?"*len(COLS))), [r.get(c) for c in COLS])
        n += 1
    con.commit()
    return n
