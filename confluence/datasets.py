"""Dataset builder: versioned JSONL/CSV exports of every table plus a data dictionary.

Research and analytics only. Paper-only. Standard library only.

Usage:
    from confluence import datasets
    from confluence import db
    con = db.connect()
    info = datasets.export_all(con, "datasets/out")
    # or: python -m confluence.datasets --out datasets/out
"""
import csv
import datetime
import hashlib
import json
import os
import sqlite3
import sys

SCHEMA_VERSION = 1

# Tables that never get exported (internal bookkeeping).
SKIP_TABLES = {"sqlite_sequence", "dataset_exports"}
# Column names whose values are never written out (defence in depth: no keys/credentials).
SECRET_HINTS = ("password", "passwd", "secret", "api_key", "apikey", "token", "credential", "private_key")

# Descriptions for known shared tables. Unknown tables/columns get an auto description.
KNOWN_DESCRIPTIONS = {
    "trade_cases": {
        "_table": "Researched real-world trade cases from public sources. Self-reported results are unverified (survivorship bias).",
        "id": "Case id (text primary key).",
        "collected_at": "Unix time (REAL) when the case was collected.",
        "source_type": "Kind of source (forum, article, filing, etc.).",
        "source_url": "Public URL where the case was found.",
        "market": "Market the case concerns (crypto, futures, equities...).",
        "instrument": "Specific instrument or ticker.",
        "side": "long or short, as reported.",
        "entry_ts": "Entry time as reported.",
        "entry_price": "Entry price as reported.",
        "exit_price": "Exit price as reported.",
        "size_note": "Position size note, as reported.",
        "outcome": "Result as reported (win, loss, mixed, unknown). Losses matter as much as wins.",
        "pnl_note": "Profit or loss note, as reported.",
        "why_what": "Why the trade was taken and what was traded.",
        "how": "How it was executed or managed, per the source.",
        "where_ctx": "Where/context: venue, regime, timeframe, conditions.",
        "lesson": "Lesson stated or drawn, including why a loss happened.",
        "verified": "1 if independently verified from a second source, else 0 (default).",
        "confidence": "Confidence in the finding, REAL 0 to 1.",
        "tags": "Free-form tags.",
    },
    "ex_candles": {"_table": "Exchange OHLCV candles from public endpoints."},
    "ex_orderbook": {"_table": "Public order book snapshots."},
    "ex_funding": {"_table": "Perpetual funding rates from public endpoints."},
    "ex_oi": {"_table": "Open interest from public endpoints."},
    "ex_liquidations": {"_table": "Liquidation events from public endpoints."},
    "whale_tx": {"_table": "Large on-chain transfers from public sources."},
    "signals": {"_table": "Confluence Score signals (paper only)."},
    "outcomes": {"_table": "Evaluated outcomes of signals (paper only)."},
    "dataset_exports": {"_table": "Log of dataset exports made by confluence/datasets.py."},
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def init(con):
    """Create this module's own table (export log). Safe to call repeatedly."""
    con.execute("CREATE TABLE IF NOT EXISTS dataset_exports(version TEXT PRIMARY KEY, created_utc TEXT, content_id TEXT, n_tables INTEGER)")
    con.commit()


def list_tables(con):
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if r[0] not in SKIP_TABLES]


def table_columns(con, table):
    """Return list of dicts: name, type, notnull, pk."""
    q = '"%s"' % table.replace('"', '""')
    out = []
    for cid, name, typ, notnull, dflt, pk in [tuple(r)[:6] for r in con.execute("PRAGMA table_info(%s)" % q)]:
        out.append({"name": name, "type": typ or "", "notnull": bool(notnull),
                    "default": dflt, "pk": bool(pk)})
    return out


def _is_secret(col):
    low = col.lower()
    return any(h in low for h in SECRET_HINTS)


def _jsonable(v):
    if isinstance(v, bytes):
        return {"_bytes_hex": v.hex()}
    return v


def _csvval(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.hex()
    return v


def iter_rows(con, table):
    """Yield (columns, row tuple) deterministically ordered by primary key, else all columns."""
    cols = table_columns(con, table)
    keep = [c["name"] for c in cols if not _is_secret(c["name"])]
    if not keep:
        return keep, []
    q = '"%s"' % table.replace('"', '""')
    sel = ", ".join('"%s"' % c.replace('"', '""') for c in keep)
    pks = [c["name"] for c in cols if c["pk"]]
    order_cols = pks or keep
    order = ", ".join('"%s"' % c.replace('"', '""') for c in order_cols)
    cur = con.execute("SELECT %s FROM %s ORDER BY %s" % (sel, q, order))
    return keep, cur.fetchall()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def export_table(con, table, outdir):
    keep, rows = iter_rows(con, table)
    jpath = os.path.join(outdir, table + ".jsonl")
    cpath = os.path.join(outdir, table + ".csv")
    with open(jpath, "w", encoding="utf-8", newline="\n") as jf:
        for r in rows:
            rec = {k: _jsonable(v) for k, v in zip(keep, tuple(r))}
            jf.write(json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str) + "\n")
    with open(cpath, "w", encoding="utf-8", newline="") as cf:
        w = csv.writer(cf, lineterminator="\n")
        w.writerow(keep)
        for r in rows:
            w.writerow([_csvval(v) for v in tuple(r)])
    return {"table": table, "rows": len(rows), "columns": keep,
            "jsonl": os.path.basename(jpath), "csv": os.path.basename(cpath),
            "jsonl_sha256": _sha256(jpath), "csv_sha256": _sha256(cpath)}


def build_dictionary(con, tables=None):
    """Return the data dictionary as a dict and markdown string."""
    tables = tables if tables is not None else list_tables(con)
    d = {}
    for t in tables:
        known = KNOWN_DESCRIPTIONS.get(t, {})
        cols = []
        for c in table_columns(con, t):
            if _is_secret(c["name"]):
                continue
            c = dict(c)
            c["description"] = known.get(c["name"], "")
            cols.append(c)
        n = con.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
        d[t] = {"description": known.get("_table", ""), "row_count": n, "columns": cols}
    md = ["# Data dictionary", "", "Generated by confluence/datasets.py. Paper-only research data.", ""]
    for t, info in d.items():
        md += ["## %s" % t, "", info["description"] or "(no description recorded)",
               "", "Rows: %d" % info["row_count"], "",
               "| column | type | pk | not null | description |", "|---|---|---|---|---|"]
        for c in info["columns"]:
            md.append("| %s | %s | %s | %s | %s |" % (
                c["name"], c["type"] or "-", "yes" if c["pk"] else "", "yes" if c["notnull"] else "",
                (c["description"] or "").replace("|", "/")))
        md.append("")
    return d, "\n".join(md)


def export_all(con, outroot, version=None, tables=None):
    """Write a versioned export under outroot/<version>/. Returns the manifest dict.

    version defaults to a UTC timestamp, v20261127T154000Z. Existing versions are never overwritten.
    The manifest has a content_id (hash of all file hashes) so identical data is recognisable.
    """
    now = _now()
    version = version or "v" + now.strftime("%Y%m%dT%H%M%SZ")
    outdir = os.path.join(outroot, version)
    if os.path.exists(outdir):
        raise FileExistsError("dataset version already exists: %s" % outdir)
    os.makedirs(outdir)
    tabs = tables if tables is not None else list_tables(con)
    entries = [export_table(con, t, outdir) for t in tabs]
    ddict, md = build_dictionary(con, tabs)
    with open(os.path.join(outdir, "DATA_DICTIONARY.md"), "w", encoding="utf-8") as f:
        f.write(md + "\n")
    with open(os.path.join(outdir, "data_dictionary.json"), "w", encoding="utf-8") as f:
        json.dump(ddict, f, indent=2, sort_keys=True)
    h = hashlib.sha256()
    for e in entries:
        h.update((e["table"] + e["jsonl_sha256"] + e["csv_sha256"]).encode())
    manifest = {"schema_version": SCHEMA_VERSION, "version": version,
                "created_utc": now.isoformat(), "content_id": h.hexdigest()[:16],
                "tables": entries,
                "notes": "Public sources only. Self-reported results are unverified. Not investment advice."}
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    try:
        init(con)
        con.execute("INSERT OR REPLACE INTO dataset_exports VALUES(?,?,?,?)",
                    (version, manifest["created_utc"], manifest["content_id"], len(entries)))
        con.commit()
    except Exception:
        pass
    return manifest


def verify(outdir):
    """Check files against manifest hashes. Returns list of problems (empty = ok)."""
    with open(os.path.join(outdir, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    bad = []
    for e in m["tables"]:
        for k, h in (("jsonl", "jsonl_sha256"), ("csv", "csv_sha256")):
            p = os.path.join(outdir, e[k])
            if not os.path.exists(p):
                bad.append("missing " + e[k])
            elif _sha256(p) != e[h]:
                bad.append("hash mismatch " + e[k])
    return bad


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Export all tables to versioned JSONL/CSV.")
    ap.add_argument("--out", default="datasets/out")
    ap.add_argument("--version", default=None)
    a = ap.parse_args(argv)
    from . import db  # core module, provided by the integrator
    con = db.connect()
    init(con)
    m = export_all(con, a.out, a.version)
    print("wrote %s (%d tables, content_id %s)" % (m["version"], len(m["tables"]), m["content_id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
