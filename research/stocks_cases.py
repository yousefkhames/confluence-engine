"""R3 Stocks case studies loader.

Loads curated public-equities trade cases from research/cases/stocks.json
into the shared trade_cases table. Core contract:
    from confluence import db; con = db.connect()
    import research.stocks_cases as sc
    sc.init(con); n = sc.fetch(con)
Standard library only. No network access; the JSON is a curated fixture.
"""
import json
import os
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_cases (
    id TEXT PRIMARY KEY,
    collected_at REAL,
    source_type TEXT,
    source_url TEXT,
    market TEXT,
    instrument TEXT,
    side TEXT,
    entry_ts TEXT,
    entry_price REAL,
    exit_price REAL,
    size_note TEXT,
    outcome TEXT,
    pnl_note TEXT,
    why_what TEXT,
    how TEXT,
    where_ctx TEXT,
    lesson TEXT,
    verified INTEGER DEFAULT 0,
    confidence REAL,
    tags TEXT
)
"""

_FIELDS = ["id", "source_type", "source_url", "market", "instrument", "side",
           "entry_ts", "entry_price", "exit_price", "size_note", "outcome",
           "pnl_note", "why_what", "how", "where_ctx", "lesson", "verified",
           "confidence", "tags"]


def _json_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "cases", "stocks.json")


def load_cases(path=None):
    """Return the list of case dicts from the JSON fixture."""
    with open(path or _json_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def init(con):
    """Create the shared trade_cases table if it does not exist."""
    con.execute(_SCHEMA)
    con.commit()


def fetch(con):
    """Insert/replace all stock cases into trade_cases. Returns row count."""
    init(con)
    cases = load_cases()
    now = time.time()
    placeholders = ", ".join(["?"] * (len(_FIELDS) + 1))
    sql = ("INSERT OR REPLACE INTO trade_cases "
           "(id, collected_at, {}) VALUES ({})".format(
               ", ".join(_FIELDS[1:]), placeholders))
    for c in cases:
        row = [c["id"], now] + [c.get(k) for k in _FIELDS[1:]]
        con.execute(sql, row)
    con.commit()
    return len(cases)


if __name__ == "__main__":
    import sqlite3
    con = sqlite3.connect(":memory:")
    print("inserted:", fetch(con))
