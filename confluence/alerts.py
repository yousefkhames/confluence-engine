"""Alert delivery. Dry-run by default: prints and appends to data/alerts.log.
Telegram / Discord / generic webhook sinks activate only if the operator sets env vars on their own machine.
Nothing here places trades; there are no exchange order hooks."""
import os, json, urllib.request

def format_alert(sig):
    flags = ("\n" + "\n".join("! " + f for f in sig["flags"])) if sig["flags"] else ""
    return (f"[{sig['direction']}] {sig['symbol']}  Confluence {sig['score']}/100  @ {sig['price']}\n"
            f"{sig.get('reason') or ''}\nNet edge est: {sig['net_edge_pct']}%  Regime: {sig['regime']['regime']}{flags}\n"
            "Paper signal. Not financial advice.")

def _post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()

def send(sig, dry_run=True):
    from .scoring import explain
    sig.setdefault("reason", explain(sig))
    text = format_alert(sig)
    os.makedirs("data", exist_ok=True)
    open("data/alerts.log", "a").write(text + "\n---\n")
    if dry_run:
        print(text); return ["stdout"]
    sent = []
    tg, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tg and chat:
        _post(f"https://api.telegram.org/bot{tg}/sendMessage", {"chat_id": chat, "text": text}); sent.append("telegram")
    for env, key in (("DISCORD_WEBHOOK_URL", "content"), ("ALERT_WEBHOOK_URL", "text")):
        if os.environ.get(env):
            _post(os.environ[env], {key: text, "signal": {k: sig[k] for k in ("symbol", "direction", "score", "price")}})
            sent.append(env)
    return sent
