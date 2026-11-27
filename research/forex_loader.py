"""R2 forex case-studies loader.

Owns: research/cases/forex.json rows -> shared trade_cases table.
Core contract: never edit core files; call init(con) before load(con).
The shared table is created defensively with CREATE TABLE IF NOT EXISTS;
if the integrator already created it, this is a no-op.
"""
import json
import os
import sqlite3
import time

DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "cases", "forex.json")

DDL = """
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

COLUMNS = ["id", "collected_at", "source_type", "source_url", "market",
           "instrument", "side", "entry_ts", "entry_price", "exit_price",
           "size_note", "outcome", "pnl_note", "why_what", "how",
           "where_ctx", "lesson", "verified", "confidence", "tags"]

REQUIRED = ["source_url", "market", "outcome", "why_what", "how", "where_ctx"]


def init(con: sqlite3.Connection) -> None:
    con.execute(DDL)
    con.commit()


def _row(case: dict, collected_at: float) -> tuple:
    for key in REQUIRED:
        if not case.get(key):
            raise ValueError(f"case {case.get('id')} missing required field {key}")
    return tuple(case.get(col) if col != "collected_at" else collected_at
                 for col in COLUMNS)


def load(con: sqlite3.Connection, path: str = DEFAULT_JSON) -> int:
    """Insert/replace all cases from the JSON file. Returns row count."""
    init(con)
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)
    now = time.time()
    rows = [_row(c, now) for c in cases]
    placeholders = ",".join("?" * len(COLUMNS))
    con.executemany(
        f"INSERT OR REPLACE INTO trade_cases ({','.join(COLUMNS)}) VALUES ({placeholders})",
        rows,
    )
    con.commit()
    return len(rows)


def run() -> int:
    """Entry point inside the repo: uses the core db connection."""
    from confluence import db  # core import, only at run time
    con = db.connect()
    n = load(con)
    print(f"forex_loader: loaded {n} trade_cases rows")
    return n


if __name__ == "__main__":
    run()
