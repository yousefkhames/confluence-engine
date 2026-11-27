"""Builds docs/demo.html: a static page from SYNTHETIC demo data. Run from the repo root: python3 docs/build_demo.py"""
import sqlite3, json, sys, os, html
sys.path.insert(0, os.getcwd())
from confluence import db, demo, signals, config
from confluence.scoring import explain
con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row; con.executescript(db.SCHEMA)
demo.generate(con, days=4)
end = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
start = con.execute("SELECT MIN(ts) t FROM prices").fetchone()["t"]
t = start + (end - start) * 0.5
while t < end - 86400 // 4:
    signals.scan(con, t); t += 3600
signals.evaluate_outcomes(con, end + 86400)
ok, _ = signals.verify_chain(con)
rec = signals.track_record(con)
rows = con.execute("SELECT * FROM signals ORDER BY ts DESC LIMIT 12").fetchall()
cards = ""
for r in rows:
    fl = json.loads(r["flags"]); f = json.loads(r["factors"])
    cards += (f'<div class="card {r["direction"][0]}"><span class="score">{r["score"]:.0f}</span> <b>{html.escape(r["symbol"])}</b> {r["direction"]}'
              f'<br><small>{html.escape(r["reason"] or "")}</small><br><small>whale {f["whale"]:+.2f} / news {f["news"]:+.2f} / sentiment {f["sentiment"]:+.2f}</small>'
              + "".join(f'<div class="flag">! {html.escape(x)}</div>' for x in fl) + "</div>")
sym = rows[0]["symbol"] if rows else "BTC"
pr = [[r["ts"], r["close"]] for r in con.execute("SELECT ts, close FROM prices WHERE symbol=? AND ts>? ORDER BY ts", (sym, end - 86400))]
sig = [[r["ts"], r["price"], r["direction"]] for r in con.execute("SELECT * FROM signals WHERE symbol=? AND ts>?", (sym, end - 86400))]
tr = "".join(f"<tr><td>{h}</td><td>{v['n']}</td><td>{v['hit_rate']}</td><td>{v['avg_directional_ret_pct']}</td></tr>" for h, v in rec.items())
page = f"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Confluence Engine demo (synthetic data)</title>
<style>body{{font:15px system-ui;margin:0;background:#0b0f17;color:#dbe4f0}}header{{padding:14px 20px;background:#111827}}.warn{{background:#7c2d12;color:#fff;padding:10px 20px;font-weight:600}}
main{{display:grid;grid-template-columns:minmax(300px,420px) 1fr;gap:14px;padding:14px;max-width:1200px;margin:auto}}@media(max-width:800px){{main{{grid-template-columns:1fr}}}}
.card{{background:#111827;border-radius:8px;padding:10px;margin-bottom:8px}}.L{{border-left:4px solid #22c55e}}.S{{border-left:4px solid #ef4444}}.score{{font-size:20px;font-weight:700}}small{{color:#8da2bd}}.flag{{color:#f59e0b;font-size:12px}}
canvas{{background:#111827;border-radius:8px;width:100%}}table{{border-collapse:collapse}}td,th{{padding:4px 10px;border-bottom:1px solid #223}}</style>
<div class=warn>SYNTHETIC DEMO DATA with planted patterns. Not real market data, not a track record, not financial advice. Paper signals only.</div>
<header><b>Confluence Engine</b> &middot; built with an AI assistant (Instinct) &middot; <a style=color:#60a5fa href="https://github.com/yousefkhames/confluence-engine">source</a></header>
<main><div><h3>Latest paper signals (synthetic)</h3>{cards}</div>
<div><h3>{sym} synthetic price with signal markers</h3><canvas id=c width=900 height=380></canvas>
<h3>Outcome log on synthetic data (hash chain valid: {ok})</h3><table><tr><th>Horizon</th><th>Signals</th><th>Hit rate</th><th>Avg directional return %</th></tr>{tr}</table>
<p><small>These numbers only show the plumbing works on data the demo planted. Judge the engine on live signals only.</small></p></div></main>
<script>const P={json.dumps(pr)},S={json.dumps(sig)};const c=document.getElementById('c'),x=c.getContext('2d');
if(P.length){{const t0=P[0][0],t1=P[P.length-1][0],lo=Math.min(...P.map(p=>p[1])),hi=Math.max(...P.map(p=>p[1]));const X=t=>30+(t-t0)/(t1-t0)*850,Y=v=>360-(v-lo)/(hi-lo||1)*330;
x.strokeStyle='#60a5fa';x.beginPath();P.forEach((p,i)=>i?x.lineTo(X(p[0]),Y(p[1])):x.moveTo(X(p[0]),Y(p[1])));x.stroke();
S.forEach(s=>{{x.fillStyle=s[2]=='LONG'?'#22c55e':'#ef4444';x.fillRect(X(s[0])-4,Y(s[1])-4,8,8)}})}}</script></html>"""
open("docs/demo.html", "w").write(page); print(len(rows), ok, rec)
