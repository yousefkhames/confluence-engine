"""Single-screen terminal: live confluence cards, annotated chart, signal log, track record, research explorer, tiers."""
import json, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import db, config
from .signals import track_record, verify_chain
from .tiers import tier_for, visible_signals
from .postmortem import post_mortem

PAGE = open(__file__.replace("dashboard.py", "web/index.html")).read() if False else None

def _now(con):
    return con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"] or time.time()

def api(path, qs, token):
    con = db.connect(); now = _now(con); tier = tier_for(con, token)
    if path == "/api/feed":
        return [{k: r[k] for k in ("id", "ts", "symbol", "direction", "score", "price", "reason", "flags", "net_edge_pct", "hash")}
                for r in visible_signals(con, tier, now)] + [{"tier": tier}]
    if path == "/api/chart":
        sym = qs.get("symbol", ["BTC"])[0]
        if sym not in config.COINS[: config.TIERS[tier]["max_coins"]]:
            return {"error": "coin not in your tier"}
        cutoff = now - config.TIERS[tier]["delay_s"]
        pr = [[r["ts"], r["close"]] for r in con.execute("SELECT ts, close FROM prices WHERE symbol=? AND ts>? AND ts<=? ORDER BY ts",
                                                          (sym, cutoff - 86400, cutoff))]
        ann = [{"ts": r["ts"], "type": "news", "label": r["title"][:60], "sent": r["sentiment"]} for r in
               con.execute("SELECT * FROM news WHERE symbol=? AND ts>? AND ts<=?", (sym, cutoff - 86400, cutoff))]
        ann += [{"ts": r["ts"], "type": "whale", "label": f"{r['kind']} ${r['usd']/1e6:.1f}M", "kind": r["kind"]} for r in
                con.execute("SELECT * FROM whale_tx WHERE symbol=? AND ts>? AND ts<=?", (sym, cutoff - 86400, cutoff))]
        ann += [{"ts": r["ts"], "type": "signal", "label": f"{r['direction']} {r['score']}"} for r in
                con.execute("SELECT * FROM signals WHERE symbol=? AND ts>? AND ts<=?", (sym, cutoff - 86400, cutoff))]
        return {"symbol": sym, "prices": pr, "annotations": ann}
    if path == "/api/track":
        ok, bad = verify_chain(con)
        return {"record": track_record(con), "chain_valid": ok}
    if path == "/api/postmortem":
        if not config.TIERS[tier]["api"] and tier == "free": return {"error": "pro tier required"}
        return post_mortem(con, int(qs.get("id", ["0"])[0]), qs.get("h", ["1h"])[0])
    if path == "/api/cases":
        rows = con.execute("SELECT market, instrument, side, outcome, why_what, how, where_ctx, source_url, verified, confidence "
                           "FROM trade_cases ORDER BY collected_at DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]
    if path == "/api/tiers":
        return config.TIERS
    return None

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
        token = qs.get("token", [None])[0] or self.headers.get("X-API-Key")
        if u.path == "/":
            body = INDEX.encode(); ct = "text/html; charset=utf-8"
        else:
            r = api(u.path, qs, token)
            if r is None: self.send_response(404); self.end_headers(); return
            body = json.dumps(r).encode(); ct = "application/json"
        self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body)

def serve(port=8080):
    print(f"Dashboard on http://127.0.0.1:{port}  (paper signals only)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

INDEX = """<!doctype html><meta charset=utf-8><title>Confluence</title>
<style>body{font:14px system-ui;margin:0;background:#0b0f17;color:#dbe4f0}header{padding:12px 20px;background:#111827;display:flex;justify-content:space-between}
main{display:grid;grid-template-columns:380px 1fr;gap:12px;padding:12px}.card{background:#111827;border-radius:8px;padding:10px;margin-bottom:8px;cursor:pointer}
.L{border-left:4px solid #22c55e}.S{border-left:4px solid #ef4444}.score{font-size:20px;font-weight:700}small{color:#8da2bd}.flag{color:#f59e0b;font-size:12px}
canvas{background:#111827;border-radius:8px;width:100%}</style>
<header><b>Confluence Engine</b><span id=rec></span></header>
<main><div id=feed></div><div><canvas id=c width=900 height=420></canvas><div id=legend><small>Annotated chart: triangles = whale tx (green buy / red sell), dots = news, squares = signal. Paper signals only. Not financial advice.</small></div><div id=pm></div></div></main>
<script>
const esc=t=>String(t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const q=new URLSearchParams(location.search),tok=q.get('token')||'';const A=p=>fetch(p+(p.includes('?')?'&':'?')+'token='+tok).then(r=>r.json());
async function load(){const f=await A('/api/feed');const t=f.pop();document.getElementById('feed').innerHTML='<small>Tier: '+t.tier+'</small>'+f.map(s=>`<div class="card ${s.direction[0]}" onclick="chart('${s.symbol}');pm(${s.id})"><span class=score>${s.score}%</span> <b>${s.symbol}</b> ${s.direction} <small>@${s.price}</small><br><small>${esc(s.reason)}</small>${JSON.parse(s.flags).map(x=>'<div class=flag>! '+esc(x)+'</div>').join('')}</div>`).join('');
const r=await A('/api/track');document.getElementById('rec').innerHTML='Track record 1h: '+JSON.stringify(r.record['1h'])+' chain '+(r.chain_valid?'valid':'BROKEN');if(f[0])chart(f[0].symbol)}
async function pm(id){const p=await A('/api/postmortem?id='+id);document.getElementById('pm').innerHTML=p&&p.causes?'<div class=card><b>Why it '+(p.won?'won':'lost')+'</b><br>'+p.causes.join('<br>')+'</div>':''}
async function chart(sym){const d=await A('/api/chart?symbol='+sym);const c=document.getElementById('c'),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);if(!d.prices||!d.prices.length)return;
const P=d.prices,t0=P[0][0],t1=P[P.length-1][0],lo=Math.min(...P.map(p=>p[1])),hi=Math.max(...P.map(p=>p[1]));const X=t=>40+(t-t0)/(t1-t0)*850,Y=v=>400-(v-lo)/(hi-lo||1)*370;
x.strokeStyle='#60a5fa';x.beginPath();P.forEach((p,i)=>i?x.lineTo(X(p[0]),Y(p[1])):x.moveTo(X(p[0]),Y(p[1])));x.stroke();x.fillStyle='#8da2bd';x.fillText(sym,45,18);
d.annotations.forEach(a=>{const px=P.reduce((b,p)=>Math.abs(p[0]-a.ts)<Math.abs(b[0]-a.ts)?p:b),X0=X(a.ts),Y0=Y(px[1]);
if(a.type=='whale'){x.fillStyle=a.kind=='from_exchange'?'#22c55e':a.kind=='to_exchange'?'#ef4444':'#a3a3a3';x.beginPath();x.moveTo(X0,Y0-10);x.lineTo(X0-5,Y0);x.lineTo(X0+5,Y0);x.fill()}
else if(a.type=='news'){x.fillStyle=a.sent>=0?'#facc15':'#fb923c';x.beginPath();x.arc(X0,Y0+8,4,0,7);x.fill()}
else{x.fillStyle='#fff';x.fillRect(X0-4,Y0-4,8,8)}})}
load();setInterval(load,15000)
</script>"""
