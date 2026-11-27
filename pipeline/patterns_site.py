"""Run the pattern library on stored candles, write results + a standalone patterns page."""
import json, os, time, datetime, html
from confluence import patterns, config, emotion
from confluence.adapters._http import get
from pipeline import history, deep_history


def fng_history(data_dir):
    """Full Fear & Greed history (alternative.me, free): {utc day start: value}. Cached in data/fng.json."""
    f = os.path.join(data_dir, "fng.json"); cached = {}
    if os.path.exists(f):
        cached = {int(k): v for k, v in json.load(open(f)).items()}
    try:
        for r in get("https://api.alternative.me/fng/?limit=0&date_format=us", timeout=30)["data"]:
            t = int(datetime.datetime.strptime(r["timestamp"], "%m-%d-%Y").replace(tzinfo=datetime.timezone.utc).timestamp())
            cached[t] = int(r["value"])
    except Exception:
        pass
    if cached:
        json.dump({str(k): v for k, v in sorted(cached.items())}, open(f, "w"))
    return cached


def run(con, data_dir, site_dir):
    hist_dir = os.path.join(data_dir, "history")
    S = deep_history.series(hist_dir)
    source = "Binance public data dumps (USDT pairs), hourly, aggregated to 6h and 1d"
    if not S:
        S = history.series(con); source = "Coinbase public candles (short history)"
    fng = fng_history(data_dir)
    cost = 2 * (config.FEE_PCT + config.SLIPPAGE_PCT)
    res = patterns.run_all(S, cost, fng=fng)
    live = patterns.live_matches(S, fng=fng)
    emo = {"validation": emotion.validate(S, fng), "snapshot": emotion.snapshot(S, fng),
           "fear_greed_now": (lambda k: [k and fng[k], k])(max(fng) if fng else None)}
    now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    bars = {"%s/%s" % k: len(v) for k, v in S.items()}
    span = [min((v[0][0] for v in S.values()), default=None), max((v[-1][0] for v in S.values()), default=None)]
    out = {"generated": now, "cost_round_trip_pct": cost, "series": len(S), "bars_total": sum(len(v) for v in S.values()),
           "span_utc": [datetime.datetime.utcfromtimestamp(t).isoformat(timespec="minutes") + "Z" if t else None for t in span],
           "rules": res, "live_matches": live, "emotion": emo, "price_source": source,
           "note": "%d rules were tested on the same data. Expect some to look good by luck: a 'weak' label is a lead to watch, not an edge." % len(res)}
    os.makedirs(data_dir, exist_ok=True); os.makedirs(site_dir, exist_ok=True)
    json.dump(out, open(os.path.join(data_dir, "pattern_results.json"), "w"), indent=1, sort_keys=True)
    json.dump(out, open(os.path.join(site_dir, "patterns.json"), "w"), indent=1, sort_keys=True)
    with open(os.path.join(data_dir, "pattern_history.jsonl"), "a", encoding="utf-8", newline="\n") as f:   # how each rule's numbers drift run to run
        f.write(json.dumps({"t": now, "rules": {r["id"]: [r["all"].get("n"), r["all"].get("hit_rate"), r["all"].get("avg_net_pct"), r["status"]] for r in res}}, sort_keys=True) + "\n")
    e = html.escape
    rows = []
    for r in res:
        a = r["all"]; o = r.get("out_of_sample", {})
        rows.append("<tr><td><b>%s</b><br><small>%s</small></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            e(r["id"]), e(r["rule"]), e(r.get("direction", "")), a.get("n", 0), a.get("hit_rate", ""), r.get("base_rate_hit", ""),
            "%s (%s)" % (o.get("hit_rate", ""), o.get("n", 0)), a.get("avg_net_pct", ""), e(r["status"])))
    lm = "".join("<li>%s %s: %s (%s bar)</li>" % (e(m["symbol"]), e(m["tf"]), e(m["rule"] + " " + m["direction"]), datetime.datetime.utcfromtimestamp(m["bar_ts"]).strftime("%m-%d %H:%M")) for m in live) or "<li>none on the newest closed bars</li>"
    ev = out["emotion"]["validation"]["horizons"]
    erows = "".join("<tr><td>%s bars</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        h, v.get("n"), v.get("spearman_rho"), v.get("t_adjusted"),
        " | ".join("Q%d %s%% (%s up)" % (q["bucket"], q["mean_fwd_pct"], q["up_rate"]) for q in v.get("quintiles", [])), e(v.get("verdict", v.get("status", "")))) for h, v in ev.items())
    snap = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(d["symbol"]), d["score"], e(d["label"])) for d in out["emotion"]["snapshot"])
    fgn = out["emotion"]["fear_greed_now"][0]
    page = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Confluence Engine | pattern library</title>
<style>body{font:15px system-ui;margin:0;background:#0b0f17;color:#dbe4f0}a{color:#60a5fa}main{max-width:1200px;margin:auto;padding:16px}table{border-collapse:collapse;font-size:13px;width:100%%}td,th{padding:6px 8px;border-bottom:1px solid #223;text-align:left;vertical-align:top}small,.m{color:#8da2bd}.warn{background:#3b2a12;color:#fde68a;padding:8px 12px;border-radius:6px}</style>
<main><p><a href="./">&larr; live dashboard</a></p><h1>Pattern library</h1>
<p class=warn>Real candles (1h, 6h, 1d; %d series, %d bars, %s to %s). Each rule is code: <i>if X then expect Y</i>. Entry is the next bar's open, exit after the hold period, net of %.2f%% round-trip costs. Hit rate is compared with the base rate of the same direction. %s Not financial advice, paper research only.</p>
<table><tr><th>Rule</th><th>Dir</th><th>Trades</th><th>Hit rate</th><th>Base rate</th><th>Out-of-sample hit (n)</th><th>Avg net %%</th><th>Verdict</th></tr>%s</table>
<h3>Rules firing on the newest closed bars</h3><ul>%s</ul>
<h2>Crowd emotion (fear to greed), measured</h2><p class=m>Composite of RSI, stretch from EMA50, position in 30-day range, volume-weighted candle mood, drawdown pain and the Fear &amp; Greed index (now: %s). Question tested: does it predict later returns? Pooled daily bars, 20 coins, buckets Q1 (most fearful) to Q5 (most greedy), mean forward return after entry at the next open. Rank correlation shown with a rough t-statistic adjusted for overlapping windows.</p>
<table><tr><th>Horizon</th><th>n</th><th>Spearman rho</th><th>t (adj.)</th><th>Quintiles</th><th>Verdict</th></tr>%s</table>
<h3>Emotion now (newest closed daily bar)</h3><table><tr><th>Coin</th><th>Score (-100 fear, +100 greed)</th><th>Mood</th></tr>%s</table><p class=m>Generated %s. Raw: <a href="patterns.json">patterns.json</a>.</p></main>""" % (
        len(S), out["bars_total"], out["span_utc"][0], out["span_utc"][1], cost, e(out["note"] + " Source: " + out["price_source"] + "."), "".join(rows), lm, fgn, erows, snap, now)
    open(os.path.join(site_dir, "patterns.html"), "w", encoding="utf-8").write(page)
    return out
