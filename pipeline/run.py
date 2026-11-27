"""Hourly pipeline: restore dataset -> ingest real public data -> scan -> outcomes -> learn -> persist -> build site.

Runs with no agent and no secrets (GitHub Actions or any machine). Standard library only. Paper signals only.
Usage: python -m pipeline.run --data data-branch/data --site site
"""
import argparse, json, os, sqlite3, sys, time, datetime, glob, traceback

from confluence import db, config, signals, rollups
from confluence.ingest import run_once
from confluence.market import regime

TS_TABLES = ("prices", "news", "whale_tx", "social", "derivs_snap", "events", "market_ctx", "smart_traders", "smart_flow", "source_status")   # monthly JSONL partitions
FULL_TABLES = ("signals", "outcomes", "weights", "learning_runs", "model_predictions", "candles")      # small, saved whole
WINDOW_DAYS = 45
GRANULARITY = 300   # 5-minute bars keep the dataset small
DERIVS_DDL = ("CREATE TABLE IF NOT EXISTS derivs_snap(symbol TEXT, ts REAL, funding_rate REAL, oi_usd REAL, "
              "PRIMARY KEY(symbol, ts))")


def _month(ts):
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m")


def _cols(con, table):
    return [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]


def load(con, data_dir, now):
    """Insert saved rows: whole months inside the window for time-series tables, everything for the small tables."""
    first = datetime.datetime.utcfromtimestamp(now - WINDOW_DAYS * 86400).strftime("%Y-%m")
    n = {}
    for t in TS_TABLES:
        cols = _cols(con, t); n[t] = 0
        for f in sorted(glob.glob(os.path.join(data_dir, t, "*.jsonl"))):
            if os.path.basename(f)[:7] < first:
                continue
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
            con.executemany("INSERT OR REPLACE INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))),
                            [[r.get(c) for c in cols] for r in rows])
            n[t] += len(rows)
    for t in FULL_TABLES:
        f = os.path.join(data_dir, t + ".jsonl")
        if not os.path.exists(f) or not _cols(con, t):
            continue
        cols = _cols(con, t)
        rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        con.executemany("INSERT OR REPLACE INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))),
                        [[r.get(c) for c in cols] for r in rows])
        n[t] = len(rows)
    con.commit()
    return n


def _dump(rows, path):
    lines = sorted(json.dumps(dict(r), sort_keys=True, ensure_ascii=False, default=str) for r in rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = "\n".join(lines) + ("\n" if lines else "")
    if os.path.exists(path) and open(path, encoding="utf-8").read() == new:
        return 0
    open(path, "w", encoding="utf-8", newline="\n").write(new)
    return len(lines)


def save(con, data_dir):
    written = {}
    for t in TS_TABLES:
        months = {}
        for r in con.execute("SELECT * FROM %s" % t):
            months.setdefault(_month(r["ts"]), []).append(r)
        for m, rows in months.items():
            if _dump(rows, os.path.join(data_dir, t, m + ".jsonl")):
                written[t + "/" + m] = len(rows)
    for t in FULL_TABLES:
        try:
            order = "id" if "id" in _cols(con, t) else "rowid"
            rows = con.execute("SELECT * FROM %s ORDER BY %s" % (t, order)).fetchall()
        except sqlite3.OperationalError:
            continue
        # signals keep id order (hash chain), so do not sort lexically
        path = os.path.join(data_dir, t + ".jsonl")
        os.makedirs(data_dir, exist_ok=True)
        new = "".join(json.dumps(dict(r), sort_keys=True, ensure_ascii=False, default=str) + "\n" for r in rows)
        if not (os.path.exists(path) and open(path, encoding="utf-8").read() == new):
            open(path, "w", encoding="utf-8", newline="\n").write(new); written[t] = len(rows)
    return written


def counts(con):
    out = {}
    for t in TS_TABLES + FULL_TABLES:
        try: out[t] = con.execute("SELECT COUNT(*) c FROM %s" % t).fetchone()["c"]
        except sqlite3.OperationalError: out[t] = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data-branch/data")
    ap.add_argument("--site", default="site")
    ap.add_argument("--no-ingest", action="store_true", help="skip live fetches (tests)")
    a = ap.parse_args(argv)
    t0 = time.time(); started = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    os.makedirs(a.data, exist_ok=True)
    con = db.connect(":memory:")
    con.execute(DERIVS_DDL)
    from confluence import learning
    learning.ensure_schema(con); rollups.init(con)
    from confluence.adapters import public_feeds
    from pipeline import model
    from pipeline import history, patterns_site
    public_feeds.init(con); con.execute(model.PRED_DDL); history.init(con)
    loaded = load(con, a.data, t0)
    run = {"started": started, "loaded": loaded, "errors": []}

    if not a.no_ingest:
        try:
            run["ingest"] = run_once(con, granularity=GRANULARITY)
        except Exception as e:
            run["errors"].append("ingest: %s" % e)
        try:
            run["history"] = history.update(con)
        except Exception as e:
            run["errors"].append("history: %s" % e)
        try:
            from pipeline import deep_history
            run["deep_history"] = deep_history.update(os.path.join(a.data, "history"), budget_s=60)
        except Exception as e:
            run["errors"].append("deep_history: %s" % e)
        try:
            run["public_feeds"] = public_feeds.fetch(con)
        except Exception as e:
            run["errors"].append("public_feeds: %s" % e)
        run["ingest_errors"] = {k: v for k, v in (run.get("ingest") or {}).items() if isinstance(v, str)}

    now = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
    if now:
        run["price_age_s"] = int(t0 - now)
        try:
            new = signals.scan(con, now)
            run["new_signals"] = len(new)
        except Exception as e:
            run["errors"].append("scan: %s" % e); traceback.print_exc()
        try:
            run["outcomes_filled"] = signals.evaluate_outcomes(con, now)
        except Exception as e:
            run["errors"].append("outcomes: %s" % e)
    learn = None
    try:
        learn = learning.run(con, promote=True)
    except Exception as e:
        run["errors"].append("learning: %s" % e); traceback.print_exc()
    pres = None
    try:
        pres = patterns_site.run(con, a.data, a.site)
        run["patterns"] = {r["id"]: r["status"] for r in pres["rules"]}
    except Exception as e:
        run["errors"].append("patterns: %s" % e); traceback.print_exc()
    mcard = None
    try:
        mcard = model.run(con, a.data)
        run["model_status"] = mcard.get("status")
    except Exception as e:
        run["errors"].append("model: %s" % e); traceback.print_exc()
    ok, bad = signals.verify_chain(con)
    run["chain_valid"] = ok
    run["finished"] = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    run["seconds"] = round(time.time() - t0, 1)
    run["counts"] = counts(con)

    run["written"] = save(con, a.data)
    # append-only run log (health history)
    with open(os.path.join(a.data, "runs.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({k: run[k] for k in run if k not in ("written",)}, sort_keys=True, default=str) + "\n")

    from pipeline.build_site import build
    build(con, a.site, run, learn, a.data, mcard)
    try:
        from pipeline import lenses, site as site_mod
        hd = os.path.join(a.data, "history"); lp = os.path.join(a.data, "lens_log.json"); lg = None
        stale = (not os.path.exists(lp)) or (time.time() - os.path.getmtime(lp) > 20 * 3600)
        if os.path.isdir(hd) and os.listdir(hd):
            if stale:
                lg = lenses.run(hd, a.data)
            elif os.path.exists(lp):
                lg = json.load(open(lp))
            cov = site_mod.compute_coverage(hd); json.dump(cov, open(os.path.join(a.data, "coverage.json"), "w"), indent=1)
        else:
            cov = None
        site_mod.finalize(a.site, a.data, lg, cov)
    except Exception as e:
        traceback.print_exc(); print("site shell failed: %s" % e)
    print(json.dumps({k: run[k] for k in ("started", "seconds", "errors", "new_signals", "chain_valid", "counts") if k in run}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
