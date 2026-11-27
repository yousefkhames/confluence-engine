"""Builds the static dashboard (site/index.html + site/status.json) from the pipeline database. No server needed."""
import json, os, time, datetime, html
from confluence import config, signals

TOP = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK"]


def _runs(data_dir, n=48):
    p = os.path.join(data_dir, "runs.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for l in open(p, encoding="utf-8").read().splitlines()[-n:]:
        try:
            r = json.loads(l)
            out.append({"started": r.get("started"), "seconds": r.get("seconds"), "errors": r.get("errors", []),
                        "ingest_errors": r.get("ingest_errors", {}), "new_signals": r.get("new_signals"),
                        "price_age_s": r.get("price_age_s")})
        except Exception:
            pass
    return out


def _learn_view(learn):
    if not learn:
        return None
    w = learn.get("weights") or {}; c = learn.get("calibration") or {}; wf = learn.get("walk_forward") or {}
    return {"weights_method": w.get("method"), "weights": w.get("weights_nonneg") or w.get("weights"), "n_events": w.get("n_events"),
            "cal_method": c.get("method"), "cal_n": c.get("n_cases"), "cal_before": c.get("before"), "cal_after": c.get("after"),
            "wf_status": wf.get("status"), "promotion": (wf.get("promotion") or {}).get("recommend"),
            "promotion_reason": (wf.get("promotion") or {}).get("reason"), "applied": learn.get("applied"),
            "warnings": learn.get("warnings", [])[:6]}


def build(con, site_dir, run, learn, data_dir, mcard=None):
    os.makedirs(site_dir, exist_ok=True)
    now = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"] or time.time()
    span = con.execute("SELECT MIN(ts) a, MAX(ts) b FROM prices").fetchone()
    coins = [c for c in TOP if con.execute("SELECT 1 FROM prices WHERE symbol=? LIMIT 1", (c,)).fetchone()]
    prices = {c: [[int(r["ts"]), round(r["close"], 6)] for r in con.execute(
        "SELECT ts, close FROM prices WHERE symbol=? AND ts>? ORDER BY ts", (c, now - 2 * 86400))] for c in coins}
    sigs = []
    for r in con.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 40"):
        outs = {o["horizon"]: round(o["ret_pct"], 3) for o in con.execute("SELECT * FROM outcomes WHERE signal_id=?", (r["id"],))}
        sigs.append({"id": r["id"], "ts": r["ts"], "symbol": r["symbol"], "direction": r["direction"], "score": r["score"],
                     "price": r["price"], "reason": r["reason"], "flags": json.loads(r["flags"] or "[]"), "out": outs})
    ok, _ = signals.verify_chain(con)
    status = {
        "generated_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "data_kind": "LIVE public data (real). Paper signals only.",
        "latest_price_utc": datetime.datetime.utcfromtimestamp(now).isoformat(timespec="seconds") + "Z",
        "price_span_utc": [datetime.datetime.utcfromtimestamp(span["a"]).isoformat(timespec="seconds") + "Z" if span["a"] else None,
                           datetime.datetime.utcfromtimestamp(span["b"]).isoformat(timespec="seconds") + "Z" if span["b"] else None],
        "counts_in_working_window": run.get("counts"), "chain_valid": ok,
        "track_record": signals.track_record(con), "learning": _learn_view(learn),
        "last_run": {k: run.get(k) for k in ("started", "seconds", "errors", "ingest_errors", "new_signals", "price_age_s", "outcomes_filled")},
        "recent_runs": _runs(data_dir),
    }
    json.dump(status, open(os.path.join(site_dir, "status.json"), "w"), indent=1, default=str)
    def q(sql, *a):
        try:
            return [dict(r) for r in con.execute(sql, a)]
        except Exception:
            return []
    preds = q("SELECT ts,symbol,horizon,p_up,price,mode,fwd_ret_pct,pnl_pct FROM model_predictions ORDER BY ts DESC, symbol LIMIT 40")
    eq, tot = [], 0.0
    for r in q("SELECT ts,pnl_pct FROM model_predictions WHERE pnl_pct IS NOT NULL ORDER BY ts"):
        tot += r["pnl_pct"]; eq.append([r["ts"], round(tot, 3)])
    sources = q("SELECT s.source,s.ok,s.items,s.note,s.ts FROM source_status s JOIN (SELECT source,MAX(ts) m FROM source_status GROUP BY source) x ON s.source=x.source AND s.ts=x.m ORDER BY s.source")
    flow = q("SELECT symbol,long_usd,short_usd,n_traders FROM smart_flow WHERE ts=(SELECT MAX(ts) FROM smart_flow) ORDER BY long_usd+short_usd DESC LIMIT 8")
    events = q("SELECT ts,source,title,url FROM events ORDER BY ts DESC LIMIT 12")
    extra = {"model": mcard, "preds": preds, "equity": eq, "sources": sources, "flow": flow, "events": events}
    blob = json.dumps({"status": status, "prices": prices, "signals": sigs, **extra}, default=str).replace("</", "<\\/")
    open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8").write(PAGE.replace("__DATA__", blob))
    demo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "demo.html")
    if os.path.exists(demo):
        import shutil; shutil.copy(demo, os.path.join(site_dir, "demo.html"))
    return status


PAGE = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Confluence Engine | live pipeline</title>
<style>body{font:15px system-ui;margin:0;background:#0b0f17;color:#dbe4f0}a{color:#60a5fa}header{padding:14px 20px;background:#111827;display:flex;gap:16px;flex-wrap:wrap;justify-content:space-between}
.live{background:#064e3b;color:#d1fae5;padding:8px 20px;font-weight:600}.warn{background:#3b2a12;color:#fde68a;padding:6px 20px;font-size:13px}
main{display:grid;grid-template-columns:minmax(300px,420px) 1fr;gap:14px;padding:14px;max-width:1240px;margin:auto}@media(max-width:820px){main{grid-template-columns:1fr}}
.card{background:#111827;border-radius:8px;padding:10px;margin-bottom:8px}.L{border-left:4px solid #22c55e}.S{border-left:4px solid #ef4444}.score{font-size:20px;font-weight:700}small,.m{color:#8da2bd}.flag{color:#f59e0b;font-size:12px}
canvas{background:#111827;border-radius:8px;width:100%}button{background:#1f2a40;color:#dbe4f0;border:0;border-radius:6px;padding:5px 10px;margin:0 4px 6px 0;cursor:pointer}button.on{background:#2563eb}
main>div{min-width:0}.card,small{overflow-wrap:anywhere}table{border-collapse:collapse;font-size:13px}td,th{padding:3px 8px;border-bottom:1px solid #223;text-align:left}h3{margin:14px 0 8px}</style>
<div class=live>LIVE public data (real), refreshed hourly by a GitHub Actions pipeline. Paper signals only. Not financial advice.</div>
<div class=warn>Early stage: few or no signals yet, so there is no track record to judge. Synthetic demo: <a href="demo.html">demo.html</a>. <a href="patterns.html">Pattern library</a>. <a href="research.html">Research engine</a>. Data: <a href="status.json">status.json</a>.</div>
<header><b>Confluence Engine</b><span id=upd class=m></span><a href="https://github.com/yousefkhames/confluence-engine">source</a></header>
<main><div><h3 style="margin-top:0">Latest paper signals</h3><div id=feed></div></div>
<div><div id=btns></div><canvas id=c width=900 height=360></canvas><small id=cl></small>
<h3>Track record (live, paper)</h3><div id=rec></div>
<h3>Learning loop</h3><div id=learn></div>
<h3>ML model (paper only, unvalidated until proven)</h3><div id=ml></div>
<h3>Model predictions vs outcomes (logged live, scored on real later prices)</h3><div id=pr></div><canvas id=eq width=900 height=160></canvas><small id=eql></small>
<h3>Data sources (last run: real and working or failing)</h3><div id=src></div>
<h3>Smart-money flow (public Hyperliquid positions of consistently profitable traders)</h3><div id=sm></div>
<h3>Latest official / wire headlines</h3><div id=ev></div>
<h3>Pipeline health (last runs)</h3><div id=health></div>
<h3>TradingView chart (third-party widget, loads in your browser)</h3><div class=card><div id=tv style="height:420px"></div></div></div></main>
<script>
const D=JSON.parse(document.getElementById('d').textContent);const S=D.status;
function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e}
document.getElementById('upd').textContent='updated '+S.generated_utc+' | latest price '+S.latest_price_utc;
const feed=document.getElementById('feed');
if(!D.signals.length)feed.append(el('div','card','No signals logged yet. The engine only logs a signal when the Confluence Score passes the threshold; that can take a while on real data.'));
D.signals.forEach(s=>{const c=el('div','card '+s.direction[0]);c.append(el('span','score',Math.round(s.score)+' '),el('b','',s.symbol+' '+s.direction),el('small','',' @'+s.price+' '+new Date(s.ts*1000).toISOString().slice(0,16)+'Z'));
c.append(el('br'),el('small','',s.reason||''));s.flags.forEach(f=>c.append(el('div','flag','! '+f)));
const o=Object.entries(s.out).map(([h,v])=>h+': '+v+'%').join('  ');c.append(el('br'),el('small','',o||'outcomes pending'));feed.append(c)});
let cur=Object.keys(D.prices)[0];const btns=document.getElementById('btns');
function draw(){const P=D.prices[cur]||[];const cv=document.getElementById('c'),x=cv.getContext('2d');x.clearRect(0,0,cv.width,cv.height);if(P.length<2)return;
const t0=P[0][0],t1=P[P.length-1][0],lo=Math.min(...P.map(p=>p[1])),hi=Math.max(...P.map(p=>p[1]));const X=t=>50+(t-t0)/(t1-t0)*830,Y=v=>335-(v-lo)/(hi-lo||1)*300;
x.strokeStyle='#60a5fa';x.beginPath();P.forEach((p,i)=>i?x.lineTo(X(p[0]),Y(p[1])):x.moveTo(X(p[0]),Y(p[1])));x.stroke();x.fillStyle='#8da2bd';x.fillText(cur+' '+P[P.length-1][1],55,16);x.fillText(hi,2,40);x.fillText(lo,2,335);
D.signals.filter(s=>s.symbol==cur&&s.ts>=t0).forEach(s=>{x.fillStyle=s.direction=='LONG'?'#22c55e':'#ef4444';x.fillRect(X(s.ts)-4,Y(s.price)-4,8,8)});
document.getElementById('cl').textContent='Last 48h, 5-minute bars, Coinbase public candles. Squares are logged paper signals.'}
Object.keys(D.prices).forEach(k=>{const b=el('button',k==cur?'on':'',k);b.onclick=()=>{cur=k;[...btns.children].forEach(c=>c.className=c==b?'on':'');draw()};btns.append(b)});draw();
const rec=document.getElementById('rec');const tr=S.track_record;const t=el('table');t.innerHTML='<tr><th>Horizon</th><th>Signals</th><th>Hit rate</th><th>Avg dir. return %</th></tr>';
Object.entries(tr).forEach(([h,v])=>{const r=t.insertRow();[h,v.n,v.hit_rate,v.avg_directional_ret_pct].forEach(z=>r.insertCell().textContent=z==null?'n/a':z)});rec.append(t,el('small','','Signal log hash chain valid: '+S.chain_valid+'. With few signals these numbers are noise.'));
const L=S.learning,lb=document.getElementById('learn');
if(L){[['Weights method',L.weights_method+' (n='+L.n_events+')'],['Weights',JSON.stringify(L.weights)],['Calibration',L.cal_method+' (n='+L.cal_n+')'],['Walk-forward',L.wf_status+', promotion recommended: '+L.promotion+' '+(L.promotion_reason||'')]].forEach(([a,b])=>{lb.append(el('div','',a+': '+b))});(L.warnings||[]).forEach(w=>lb.append(el('div','flag','! '+w)))}else lb.textContent='no learning summary yet';
lb.append(el('small','','Simple, labeled: weights and calibration are re-fit from logged outcomes and only promoted if a time-ordered walk-forward test passes. With little data it stays on the default weights.'));
const h=document.getElementById('health');const ht=el('table');ht.innerHTML='<tr><th>Run (UTC)</th><th>s</th><th>New signals</th><th>Price age s</th><th>Problems</th></tr>';
(S.recent_runs||[]).slice(-12).reverse().forEach(r=>{const w=ht.insertRow();[r.started,r.seconds,r.new_signals,r.price_age_s,[...(r.errors||[]),...Object.keys(r.ingest_errors||{})].join(', ')||'none'].forEach(z=>w.insertCell().textContent=z==null?'':z)});h.append(ht);
h.append(el('small','','Rows in working window: '+JSON.stringify(S.counts_in_working_window)));

function tbl(id,head,rows){const t=el('table');t.innerHTML='<tr>'+head.map(h=>'<th>'+h+'</th>').join('')+'</tr>';rows.forEach(r=>{const w=t.insertRow();r.forEach(z=>w.insertCell().textContent=z==null?'':z)});document.getElementById(id).append(t)}
const M=D.model,ml=document.getElementById('ml');
if(!M)ml.textContent='no model card yet';else{ml.append(el('div','',M.status+' | samples '+(M.samples_total||0)+' over '+(M.span_days||0)+' days | round-trip cost '+M.costs_round_trip_pct+'%'));
const rows=[];Object.entries(M.horizons||{}).forEach(([h,v])=>{const c=v.walk_forward&&v.walk_forward[v.chosen];rows.push([h,v.status,v.labeled_samples,c?c.model:'',c?c.auc:'',c?c.accuracy+' vs base '+c.base_rate_acc:'',c?c.brier+' vs naive '+c.brier_naive:'',c?(c.paper_trades+' trades, mean net '+c.paper_mean_net_pct+'%, CI '+JSON.stringify(c.paper_ci95_mean)):''])});
tbl('ml',['Horizon','Status','Labeled n','Model','Out-of-sample AUC','Accuracy','Brier','Paper PnL (walk-forward)'],rows);
const lv=Object.entries(M.live||{}).map(([h,v])=>[h,v.logged,v.scored,v.hit_rate,v.paper_trades,v.paper_total_net_pct]);
ml.append(el('small','','Walk-forward = trained only on the past, embargo of one horizon, tested on later blocks. AUC 0.5 = coin flip. Live record of logged predictions:'));tbl('ml',['Horizon','Logged','Scored','Hit rate','Paper trades','Paper net %'],lv)}
if(D.preds.length)tbl('pr',['Time (UTC)','Coin','Horizon','P(up)','Mode','Actual return %','Paper net %'],D.preds.map(p=>[new Date(p.ts*1000).toISOString().slice(0,16),p.symbol,p.horizon,Math.round(p.p_up*100)/100,p.mode,p.fwd_ret_pct==null?'pending':Math.round(p.fwd_ret_pct*1000)/1000,p.pnl_pct==null?'no trade':Math.round(p.pnl_pct*1000)/1000]));else document.getElementById('pr').textContent='No predictions yet: the model needs enough labeled data first.';
(function(){const E=D.equity,cv=document.getElementById('eq'),x=cv.getContext('2d');if(E.length<2){document.getElementById('eql').textContent='Paper equity curve appears once scored paper trades exist. Shadow model, no real money.';return}
const t0=E[0][0],t1=E[E.length-1][0],lo=Math.min(0,...E.map(p=>p[1])),hi=Math.max(0,...E.map(p=>p[1]));const X=t=>40+(t-t0)/(t1-t0||1)*840,Y=v=>140-(v-lo)/(hi-lo||1)*120;x.strokeStyle='#22c55e';x.beginPath();E.forEach((p,i)=>i?x.lineTo(X(p[0]),Y(p[1])):x.moveTo(X(p[0]),Y(p[1])));x.stroke();x.fillStyle='#8da2bd';x.fillText('cumulative paper net % (after fees and slippage)',45,12);document.getElementById('eql').textContent='Cumulative paper PnL of logged model trades, not compounded, no real money.'})();
tbl('src',['Source','Status','Items','Note'],D.sources.map(s=>[s.source,s.ok?'working':'FAILING',s.items,s.note]));
document.getElementById('src').append(el('small','','Not available free: X/Twitter API (paid), paid wallet labels (Arkham, Nansen, Whale Alert), Reddit and Bluesky search from cloud IPs. Whale direction needs wallet labels, so whale transfers are counted as activity only.'));
tbl('sm',['Coin','Long USD','Short USD','Traders'],D.flow.map(f=>[f.symbol,Math.round(f.long_usd),Math.round(f.short_usd),f.n_traders]));
document.getElementById('sm').append(el('small','','Leaderboard-picked traders are chosen by past profit (survivorship bias): a signal about positioning, not a promise.'));
(function(){const e=document.getElementById('ev');D.events.forEach(v=>{const d=el('div','card');const a=el('a','',v.title);if(/^https?:/.test(v.url||''))a.href=v.url;d.append(a,el('small','',' '+v.source+' '+new Date(v.ts*1000).toISOString().slice(0,16)+'Z'));e.append(d)})})();
const sc=document.createElement('script');sc.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';sc.async=true;sc.text=JSON.stringify({autosize:true,symbol:'COINBASE:BTCUSD',interval:'60',theme:'dark',locale:'en',hide_side_toolbar:true});document.getElementById('tv').append(sc);
</script>"""
PAGE = PAGE.replace("<script>\nconst D=", "<script id=d type=application/json>__DATA__</script><script>\nconst D=")
