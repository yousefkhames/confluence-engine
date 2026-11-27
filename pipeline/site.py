"""Site shell: one nav on every page, a manifest of every data file, generated pages from the JSON data layer
(lens log, coverage table, run history, data index). Static output for GitHub Pages. Standard library only."""
import json, os, html, glob, datetime, re

REPO = "https://github.com/yousefkhames/confluence-engine"
RAW = "https://raw.githubusercontent.com/yousefkhames/confluence-engine"
PAGES = [("index.html", "Live"), ("paper.html", "Paper test"), ("patterns.html", "Patterns"), ("research.html", "Research"),
         ("lenses.html", "Lenses"), ("fullstudy.html", "Full study"), ("demo-trades.html", "Demo trades"), ("coverage.html", "Coverage"), ("runs.html", "Runs"), ("data.html", "Data"), ("demo.html", "Synthetic demo")]

CSS = """<style id=shell>
:root{--bg:#0b0f17;--card:#111827;--line:#1f2a40;--ink:#dbe4f0;--mut:#8da2bd;--acc:#60a5fa}
.shell{position:sticky;top:0;z-index:50;display:flex;flex-wrap:wrap;gap:4px 2px;align-items:center;padding:8px 16px;background:rgba(11,15,23,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);font:600 13px system-ui}
.shell b{margin-right:12px;color:#fff;letter-spacing:.2px}.shell a{color:var(--mut);text-decoration:none;padding:5px 10px;border-radius:6px}.shell a:hover{background:#1a2338;color:#fff}.shell a.on{background:#1d2b4a;color:#fff}.shell .sp{flex:1}
.sh-foot{max-width:1200px;margin:24px auto;padding:12px 16px;color:var(--mut);font:12px system-ui;border-top:1px solid var(--line)}
table{border-radius:8px}th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
h1,h2{letter-spacing:-.01em}.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;background:#1a2338;color:var(--mut)}.pill.ok{background:#12351f;color:#86efac}.pill.no{background:#3b1d1d;color:#fca5a5}.pill.mid{background:#3b2a12;color:#fde68a}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:12px 0}.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.stat b{display:block;font-size:22px;color:#fff}.stat span{color:var(--mut);font-size:12px}
</style>"""


def nav(active):
    items = "".join('<a href="%s"%s>%s</a>' % (p, ' class=on' if p == active else "", t) for p, t in PAGES)
    return '<nav class=shell><b>Confluence Engine</b>%s<span class=sp></span><a href="%s">Source</a><a href="%s/tree/data">Data branch</a></nav>' % (items, REPO, REPO)


def inject(site_dir):
    """Add the shared nav + styles to every generated page (idempotent)."""
    for p, _t in PAGES:
        f = os.path.join(site_dir, p)
        if not os.path.exists(f):
            continue
        s = open(f, encoding="utf-8").read()
        if "id=shell" in s:
            continue
        s = s.replace("<title>", CSS + "<title>", 1) if "<title>" in s else CSS + s
        n = nav(p)
        for marker in ("<div class=live>", "<main>", "<header>"):
            if marker in s:
                s = s.replace(marker, n + marker, 1); break
        else:
            s = s.replace("</style>", "</style>" + n, 1)
        s = s.replace("</html>", '<div class=sh-foot>Paper research only, not financial advice. Free public data. Every number on this site comes from the JSON files listed on the <a href="data.html" style="color:var(--acc)">Data</a> page. Built by an AI assistant.</div></html>') if "</html>" in s else s + '<div class=sh-foot>Paper research only, not financial advice.</div>'
        open(f, "w", encoding="utf-8").write(s)


def shell_page(title, body, active):
    return ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>%s | Confluence Engine</title>"
            "<style>body{font:15px/1.5 system-ui;margin:0;background:var(--bg,#0b0f17);color:var(--ink,#dbe4f0)}a{color:#60a5fa}main{max-width:1200px;margin:auto;padding:16px}"
            "table{border-collapse:collapse;font-size:13px;width:100%%;background:#111827}td,th{padding:6px 10px;border-bottom:1px solid #1f2a40;text-align:left;vertical-align:top}small,.m{color:#8da2bd}"
            ".warn{background:#3b2a12;color:#fde68a;padding:8px 12px;border-radius:8px}.lens{background:#111827;border:1px solid #1f2a40;border-radius:12px;padding:14px 16px;margin:14px 0}"
            ".lens h3{margin:0 0 6px}.v{border-left:3px solid #60a5fa;padding-left:10px;margin:8px 0}</style></head>"
            "<main><h1>%s</h1>%s</main></html>") % (html.escape(title), html.escape(title), body)


def _table(head, rows):
    return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % html.escape(h) for h in head),
                                              "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows))


def lenses_page(log):
    e = html.escape; parts = ['<p class=warn>Same data, different mindsets. Each lens states a hypothesis, runs a test with a 70/30 time split (decide on the first 70%, judge on the last 30%), '
                              'corrects for multiple tests (Benjamini-Hochberg 5%) and logs the verdict, negatives included. Raw: <a href="lens_log.json">lens_log.json</a>. Paper research only.</p>']
    names = {"1": "1 Engineer", "2": "2 Math / physics", "3": "3 Statistician", "4": "4 Microstructure / trading scientist", "5": "5 Risk / quant"}
    for k in sorted(log.get("lenses", {})):
        L = log["lenses"][k]; b = ['<div class=lens><h3>Lens %s</h3>' % e(names.get(k, L.get("lens", k)))]
        b.append("<p><b>Hypothesis.</b> %s</p>" % e(L.get("hypothesis", "")))
        b.append("<p><b>Tests.</b> %s tests; %s survive FDR 5%%.</p>" % (L.get("multiple_tests", "n/a"), L.get("survivors_fdr5", "n/a")))
        if k == "2":
            b.append(_table(["Coin", "Hurst", "VR(4)", "VR(24)", "VR(24) last 30%", "ACF lag1", "|r| ACF lag1", "Vol half-life h", "Kurtosis", "Tail index"],
                            [[e(r["coin"]), r["hurst_all"], r["vr4"], r["vr24"], r["vr24_last30"], r["acf_lag1"], r["abs_acf_lag1"], r["vol_half_life_h"], r["kurtosis"], r["hill_tail_index"]] for r in L["rows"]]))
        if k == "4":
            b.append(_table(["Horizon h", "Rule", "Gross test %", "Break-even cost %", "Net at 0.30 %", "t (adj)", "FDR"],
                            [[r["horizon_h"], e(r["rule"]), r["gross_test_pct"], r["breakeven_cost_pct"], r["net_test_at_0.30"], r["t_adj"], "yes" if r["survives_fdr5"] else "no"] for r in L["cost_breakeven"]]))
            t = L["time_of_day"]; b.append("<p class=m>Dollar-volume index by UTC hour (1.0 = average): %s</p>" % e(", ".join("%02d:%s" % (i, x) for i, x in enumerate(t["dollar_volume_index_by_utc_hour"]))))
            b.append("<p class=m>%s</p>" % e(L.get("no_order_book", "")))
        for extra in L.get("extra_tables", []):
            b.append(_table(extra["head"], extra["rows"]))
        b.append('<div class=v><b>Verdict.</b> %s</div></div>' % e(L.get("verdict", "")))
        parts.append("".join(b))
    try:
        x = json.load(open(os.path.join(os.path.dirname(__file__), "..", "demo", "crosscheck.json"), encoding="utf-8"))
        c = ['<div class=lens><h3>Cross-check with a second, independent assistant</h3><p class=m>%s</p>' % e(x["source"]), "<h4>Descriptive statistics</h4>", _table(x["stats"]["head"], [[e(c_) for c_ in r] for r in x["stats"]["rows"]]),
             "<h4>Power: how many trades are needed to see an edge</h4>", _table(x["power"]["head"], [[e(c_) for c_ in r] for r in x["power"]["rows"]]), "<p class=m>%s</p>" % e(x["power"]["note"]),
             "<h4>Demo stake ladder: chance of hitting the $70 stop</h4>", _table(x["ladder"]["head"], [[e(c_) for c_ in r] for r in x["ladder"]["rows"]]), "<p class=m>%s</p>" % e(x["ladder"]["note"]),
             "<p><b>Ruin simulation.</b> %s</p><p><b>Rule scorer.</b> %s</p><p><b>Integrity.</b> %s</p>" % (e(x["ruin"]), e(x["scorer"]), e(x["integrity"])),
             '<div class=v><b>Verdict.</b> Both sides get the same numbers to 2 or 3 decimals on the shared statistics, and the power and sizing results reproduce. No rule is verified on either side. Sizing and stops change how fast a break-even process loses, not whether it has an edge.</div></div>']
        parts.append("".join(c))
    except Exception as ex:
        print("crosscheck section failed: %s" % ex)
    parts.append("<p class=m>Generated %s.</p>" % e(log.get("generated", "")))
    return shell_page("Lens log", "".join(parts), "lenses.html")


def coverage_page(cov):
    e = html.escape
    cards = '<div class=cards>%s</div>' % "".join('<div class=stat><b>%s</b><span>%s</span></div>' % (v, k) for k, v in (
        ("1h bars", format(cov["totals"]["1h"], ",")), ("6h bars (built from 1h)", format(cov["totals"]["6h"], ",")), ("1d bars (built from 1h)", format(cov["totals"]["1d"], ",")),
        ("Feature rows", format(cov["feature_rows"], ",")), ("Simulated entries", format(cov["entries"], ",")), ("Missing hours", format(cov["missing_hours"], ","))))
    t = _table(["Coin", "1h bars", "6h", "1d", "From", "To", "Missing hours", "Feature rows", "Entries (both directions, 10 horizons)"],
               [[e(r["coin"]), format(r["bars_1h"], ","), format(r["bars_6h"], ","), format(r["bars_1d"], ","), r["from"], r["to"], r["missing_hours"], format(r["feature_rows"], ","), format(r["entries"], ",")] for r in cov["rows"]])
    nc = "".join("<li>%s</li>" % e(x) for x in cov["not_covered"])
    return shell_page("Coverage", '<p class=warn>Exact counts computed from the stored files on every run. %s</p>%s%s<h2>What is not covered</h2><ul>%s</ul><p class=m>Generated %s. Raw: <a href="coverage.json">coverage.json</a>.</p>' % (
        e(cov["source"]), cards, t, nc, e(cov["generated"])), "coverage.html")


def runs_page(data_dir):
    rows = []; f = os.path.join(data_dir, "runs.jsonl")
    if os.path.exists(f):
        for line in open(f, encoding="utf-8").read().splitlines()[-100:]:
            try:
                r = json.loads(line)
            except Exception:
                continue
            c = r.get("counts") or {}
            rows.append([html.escape(str(r.get("started", ""))), r.get("seconds", ""), r.get("new_signals", ""), c.get("prices", ""), c.get("candles", ""),
                         '<span class="pill %s">%s</span>' % ("no" if r.get("errors") else "ok", html.escape(", ".join(r.get("errors") or []) or "ok")),
                         html.escape(str(r.get("model_status", ""))[:60])])
    rows.reverse()
    return shell_page("Run history", '<p class=m>Every pipeline run (hourly workflow, plus manual dispatches). Source: data/runs.jsonl on the data branch.</p>' +
                      _table(["Started (UTC)", "Seconds", "New signals", "Price rows", "Candle rows", "Status", "Model"], rows), "runs.html")


MANIFEST_DOC = [
    ("data/runs.jsonl", "data", "Run log: one line per pipeline run (counts, errors, timing)"),
    ("data/fng.json", "data", "Fear & Greed index history (alternative.me), by UTC day"),
    ("data/pattern_results.json", "data", "Pattern library backtest: per rule, in/out-of-sample, verdicts, emotion study"),
    ("data/pattern_history.jsonl", "data", "How each rule's numbers drift run to run"),
    ("data/research.json", "data", "Research engine: session effects, kNN now, kNN validation"),
    ("data/lens_log.json", "data", "Lens log: hypothesis, test, numbers, verdict per lens"),
    ("data/coverage.json", "data", "Exact coverage table"),
    ("data/model_card.json", "data", "ML model card: walk-forward metrics, status per horizon"),
    ("data/history/BTC-1h.csv.gz", "data", "Deep hourly history (20 coins, one file per coin, same pattern)"),
    ("data/signals.jsonl", "data", "Signal log (hash-chained)"),
    ("data/outcomes.jsonl", "data", "Signal outcomes at 15m/1h/4h/24h"),
    ("data/model_predictions.jsonl", "data", "Live ML predictions and their scored outcomes"),
    ("stats.json", "paper", "Live paper test: aggregated hit rates with Wilson bounds and FDR flags"),
]


EXTERNAL = ("<h2>Second assistant: inputs received (m12 build, 2026-11-27)</h2><p class=m>A second, independent assistant works on the same question with its own code and data. "
            "What we received and what we did with it. Its code is treated as untrusted: read, scanned for keys and unexpected network calls (none found, only public data reads), not executed here.</p><ul>"
            "<li>Lens 1, 3 and 5 write-ups and CSVs: summarized with our reproduction on the <a href='lenses.html' style='color:#60a5fa'>Lenses</a> page.</li>"
            "<li>Demo trade log (89 rows, re-issued from its raw session log): <a href='demo-trades.html' style='color:#60a5fa'>Demo trades</a>.</li>"
            "<li>1h and 5m coverage tables: 1h 20 coins 1,213,961 bars (includes a Coinbase fill for 2026-11), 5m 20 coins 5,961,600 bars 2024-01 to 2026-10. Our own 5m load is pending, then we compare bar by bar.</li>"
            "<li>m12 build: 193 files (research cases, walk-forward scorer results for 14 rules on BTC, ETH, SOL, docs, 40 test files). Result: 0 rules verified, 34 not proven, 8 small sample.</li>"
            "<li>Private chat and decision logs of its user: not published. Available on request, redacted, with its user's consent.</li></ul>")


def data_page(site_dir):
    e = html.escape; rows = []
    for path, br, desc in MANIFEST_DOC:
        rows.append([e(path), br, e(desc), '<a href="%s/%s/%s">raw</a>' % (RAW, br, path)])
    site_files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(site_dir, "*.json")))
    s = "".join('<li><a href="%s">%s</a></li>' % (e(f), e(f)) for f in site_files)
    return shell_page("Data layer", '<p class=m>All results are plain JSON/JSONL files committed by the hourly workflow to the <code>data</code> branch (and <code>paper</code> branch for the paper test). Pages are generated from them. Machine-readable index: <a href="manifest.json">manifest.json</a>.</p>' +
                      _table(["File", "Branch", "What it holds", "Link"], rows) + "<h2>Files served by this site</h2><ul>%s</ul>" % s + EXTERNAL, "data.html")


def build_manifest(site_dir, data_dir):
    files = []
    for f in sorted(glob.glob(os.path.join(site_dir, "*"))):
        files.append({"path": os.path.basename(f), "bytes": os.path.getsize(f)})
    hist = sorted(glob.glob(os.path.join(data_dir, "history", "*.csv.gz")))
    m = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "site_files": files, "data_branch_files": [
        {"path": "data/" + os.path.relpath(f, data_dir), "bytes": os.path.getsize(f)} for f in sorted(glob.glob(os.path.join(data_dir, "*.json*"))) + hist],
        "documented": [{"path": p, "branch": b, "description": d} for p, b, d in MANIFEST_DOC], "repo": REPO}
    json.dump(m, open(os.path.join(site_dir, "manifest.json"), "w"), indent=1)


def finalize(site_dir, data_dir, lens_log=None, coverage=None):
    if lens_log:
        open(os.path.join(site_dir, "lenses.html"), "w", encoding="utf-8").write(lenses_page(lens_log))
        json.dump(lens_log, open(os.path.join(site_dir, "lens_log.json"), "w"), indent=1)
    if coverage:
        open(os.path.join(site_dir, "coverage.html"), "w", encoding="utf-8").write(coverage_page(coverage))
        json.dump(coverage, open(os.path.join(site_dir, "coverage.json"), "w"), indent=1)
    try:
        from pipeline import fullstudy
        rd = os.path.join(os.path.dirname(__file__), "..", "results")
        knn = json.load(open(os.path.join(rd, "knn_full.json"))); cl = json.load(open(os.path.join(rd, "clusters.json")))
        open(os.path.join(site_dir, "fullstudy.html"), "w", encoding="utf-8").write(shell_page("Full-population study", fullstudy.page(knn, cl), "fullstudy.html"))
        json.dump(knn, open(os.path.join(site_dir, "knn_full.json"), "w")); json.dump(cl, open(os.path.join(site_dir, "clusters.json"), "w"))
    except Exception as ex:
        print("fullstudy page failed: %s" % ex)
    try:
        from pipeline import demo_trades
        raw = os.path.join(os.path.dirname(__file__), "..", "demo", "demo_trades_raw.csv")
        if os.path.exists(raw):
            dres = demo_trades.analyze(raw); json.dump(dres, open(os.path.join(site_dir, "demo_trades.json"), "w"), indent=1)
            open(os.path.join(site_dir, "demo-trades.html"), "w", encoding="utf-8").write(shell_page("Demo trades", demo_trades.page(dres), "demo-trades.html"))
    except Exception as ex:
        print("demo trades page failed: %s" % ex)
    open(os.path.join(site_dir, "runs.html"), "w", encoding="utf-8").write(runs_page(data_dir))
    open(os.path.join(site_dir, "data.html"), "w", encoding="utf-8").write(data_page(site_dir))
    build_manifest(site_dir, data_dir)
    inject(site_dir)


def compute_coverage(hist_dir):
    """Exact counts from the stored hourly files. 6h and 1d bars are built from the 1h bars (complete buckets only)."""
    import gzip
    rows = []; tot = {"1h": 0, "6h": 0, "1d": 0}; ent = 0; feat = 0; miss = 0
    for f in sorted(glob.glob(os.path.join(hist_dir, "*-1h.csv.gz"))):
        coin = os.path.basename(f).split("-")[0]; ts = []
        for line in gzip.open(f, "rt"):
            if line and line[0].isdigit(): ts.append(int(line.split(",", 1)[0]))
        if not ts: continue
        s = set(ts); n = len(ts); missing = (ts[-1] - ts[0]) // 3600 + 1 - len(s)
        b6 = len({t // 21600 for t in ts if all((t // 21600 * 21600 + 3600 * k) in s for k in range(6))}); b1d = len({t // 86400 for t in ts if all((t // 86400 * 86400 + 3600 * k) in s for k in range(24))})
        fr = max(0, n - 167); e = fr * 2 * 10
        rows.append({"coin": coin, "bars_1h": n, "bars_6h": b6, "bars_1d": b1d, "from": datetime.datetime.utcfromtimestamp(ts[0]).strftime("%Y-%m-%d"), "to": datetime.datetime.utcfromtimestamp(ts[-1]).strftime("%Y-%m-%d"),
                     "missing_hours": missing, "feature_rows": fr, "entries": e})
        tot["1h"] += n; tot["6h"] += b6; tot["1d"] += b1d; ent += e; feat += fr; miss += missing
    last = max((r["to"] for r in rows), default="")
    return {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "source": "Binance public dumps (data.binance.vision), spot USDT pairs, hourly.", "rows": rows,
            "totals": tot, "feature_rows": feat, "entries": ent, "missing_hours": miss,
            "not_covered": ["Data ends %s; later months are not loaded yet." % last, "No sub-hour bars (5m, 1m) in the deep history yet.", "Only 20 coins in the deep set.",
                            "No order book, trade-level or spread data: costs are a flat assumption.", "No equities, metals or oil history: no free feed verified."]}
