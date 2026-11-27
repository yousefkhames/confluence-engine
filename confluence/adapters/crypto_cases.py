"""Offline loader: research/cases/crypto.json -> trade_cases. No network."""
import json, os, time

PATH = os.path.join(os.path.dirname(__file__), "..", "..", "research", "cases", "crypto.json")
COLS = ["id", "source_type", "source_url", "market", "instrument", "side", "entry_ts",
        "entry_price", "exit_price", "size_note", "outcome", "pnl_note", "why_what", "how",
        "where_ctx", "lesson", "verified", "confidence", "tags"]


def load(path=PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch(con, path=PATH):
    """Insert cases (INSERT OR IGNORE by id). Returns number of new rows."""
    n = 0
    now = time.time()
    for r in load(path):
        cur = con.execute(
            "INSERT OR IGNORE INTO trade_cases (collected_at,%s) VALUES (?,%s)"
            % (",".join(COLS), ",".join("?" * len(COLS))),
            [now] + [r.get(c) for c in COLS])
        n += cur.rowcount if cur.rowcount > 0 else 0
    con.commit()
    return n
