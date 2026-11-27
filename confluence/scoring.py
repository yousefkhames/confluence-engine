"""The Confluence Formula.

Signed factors in [-1, 1] (positive = bullish):
  whale      Smart Whale Flow: net flow of wallets, weighted by their Smart Money score
  news       Unpriced News Impact: sentiment * urgency * credibility * (1 - price-in)
  sentiment  Organic Sentiment Velocity: bot-filtered mood * acceleration vs 24h baseline
Penalty in [0, 1]:
  manipulation  bot share of social volume + wash/circular wallet flow share
Score 0-100 = 100 * |weighted sum| * (1 - penalty) * agreement bonus * regime multiplier.
"""
import math, json
from . import config
from .market import shock_impact, price_in_ratio, regime, volatility_pct, price_at
from .wallets import wallet_score, is_insider

def _tanh(x): return math.tanh(x)

def load_weights(con):
    w = dict(config.DEFAULT_WEIGHTS)
    for r in con.execute("SELECT k, v FROM weights"):
        if r["k"] in w:
            w[r["k"]] = r["v"]
    s = sum(w.values()) or 1
    return {k: v / s for k, v in w.items()}

def whale_factor(con, sym, now):
    rows = con.execute("SELECT * FROM whale_tx WHERE symbol=? AND ts>? AND ts<=?",
                       (sym, now - config.WHALE_WINDOW_S, now)).fetchall()
    net = 0.0; wash = 0.0; total = 0.0; insider = []
    for r in rows:
        w = wallet_score(con, r["wallet"]) if r["wallet"] else 0.5
        weight = 0.25 + 1.5 * w   # smart wallets count several times a random whale
        sign = 1 if r["kind"] == "from_exchange" else -1 if r["kind"] == "to_exchange" else 0
        net += sign * r["usd"] * weight
        total += r["usd"]
        if r["kind"] == "wallet_to_wallet" and r["wallet"]:
            cl = con.execute("SELECT cluster FROM wallets WHERE addr=?", (r["wallet"],)).fetchone()
            to_cl = con.execute("SELECT cluster FROM wallets WHERE addr=?", (r["to_addr"],)).fetchone()
            if cl and to_cl and cl["cluster"] and cl["cluster"] == to_cl["cluster"]:
                wash += r["usd"]   # moving funds inside one entity: not real flow
        if sign > 0 and r["wallet"] and is_insider(con, r["wallet"]):
            insider.append(r["wallet"])
    f = _tanh(net / 5_000_000)
    return f, (wash / total if total else 0.0), {"n_tx": len(rows), "net_usd_weighted": round(net), "insider_wallets": insider}

def news_factor(con, sym, now):
    rows = con.execute("SELECT * FROM news WHERE symbol=? AND ts>? AND ts<=? ORDER BY ts",
                       (sym, now - config.NEWS_WINDOW_S, now)).fetchall()
    total = 0.0; best = None; late = False
    for r in rows:
        shock = shock_impact(con, sym, r["ts"], windows=(300,)).get(300)
        move = shock["ret_pct"] if shock else 0.0
        signed_move = move if r["sentiment"] >= 0 else -move
        pi = price_in_ratio(move)
        if signed_move >= config.LATE_MOVE_PCT:
            late = True
        unpriced = max(0.0, 1 - pi)
        v = r["sentiment"] * r["urgency"] * r["credibility"] * (0.2 + 0.8 * unpriced) * 2
        total += v
        if best is None or abs(v) > abs(best[0]):
            best = (v, r["title"], r["ts"], move, unpriced)
    info = {"n_news": len(rows)}
    if best:
        info.update({"top_title": best[1], "top_ts": best[2], "move_since_pct": round(best[3], 2),
                     "unpriced": round(best[4], 2)})
    return _tanh(total), late, info

def sentiment_factor(con, sym, now):
    recent = con.execute("SELECT * FROM social WHERE symbol=? AND ts>? AND ts<=?",
                         (sym, now - config.SOCIAL_WINDOW_S, now)).fetchall()
    base = con.execute("SELECT COUNT(*) c FROM social WHERE symbol=? AND ts>? AND ts<=?",
                       (sym, now - 86400, now - config.SOCIAL_WINDOW_S)).fetchone()["c"]
    organic = [r for r in recent if r["is_bot"] < 0.5]
    bots = len(recent) - len(organic)
    bot_share = bots / len(recent) if recent else 0.0
    if not organic:
        return 0.0, bot_share, {"n_posts": len(recent), "bot_share": round(bot_share, 2), "velocity": 0}
    mood = sum(r["sentiment"] for r in organic) / len(organic)
    base_rate = base / 23.0   # posts per hour baseline
    velocity = len(organic) / max(base_rate, 1.0)
    f = _tanh(mood * min(velocity, 4.0) * 0.8)
    return f, bot_share, {"n_posts": len(recent), "bot_share": round(bot_share, 2), "velocity": round(velocity, 2),
                          "mood": round(mood, 2)}

def compute(con, sym, now, weights=None, reg=None):
    weights = weights or load_weights(con)
    reg = reg or regime(con, now=now)
    wf, wash, winfo = whale_factor(con, sym, now)
    nf, late, ninfo = news_factor(con, sym, now)
    sf, bot_share, sinfo = sentiment_factor(con, sym, now)
    factors = {"whale": wf, "news": nf, "sentiment": sf}
    raw = sum(weights[k] * factors[k] for k in factors)
    direction = "LONG" if raw > 0 else "SHORT"
    sign = 1 if raw > 0 else -1
    agree = sum(1 for v in factors.values() if v * sign > 0.15)
    bonus = {0: 0.6, 1: 0.8, 2: 1.15, 3: 1.4}[agree]
    penalty = min(1.0, 0.7 * bot_share + 0.8 * wash)
    mult = reg["conf_mult"]
    # Opposed regime: a long in Risk-Off (or short in Risk-On) is lowered further.
    if (reg["regime"] == "Risk-Off" and sign > 0) or (reg["regime"] == "Risk-On" and sign < 0):
        mult *= 0.85
    score = max(0.0, min(100.0, 100 * abs(raw) * 1.6 * bonus * (1 - penalty) * mult))
    flags = []
    if penalty >= 0.4:
        flags.append("MANIPULATION_WARNING: bot campaign or intra-entity wallet flow, possible pump and dump")
    if late and sign > 0:
        flags.append("TOO_LATE: price already moved sharply after the news, correction risk")
    if ninfo.get("unpriced", 0) >= 0.7 and abs(nf) > 0.3:
        flags.append("UNPRICED_CATALYST: news not yet reflected in price")
    if winfo["insider_wallets"]:
        flags.append("INSIDER_PATTERN: wallets with past front-running behaviour are accumulating")
    if reg["regime"] in ("Choppy",):
        flags.append("REGIME_CHOPPY: low trend quality, reduce size")
    if (reg["regime"] == "Risk-Off" and sign > 0):
        flags.append("MACRO_AGAINST: good setup, hostile macro, reduce size")
    price = price_at(con, sym, now, "before")
    vol = volatility_pct(con, sym, now)
    exp_move = vol * (score / 100) * 1.5
    cost = 2 * (config.FEE_PCT + config.SLIPPAGE_PCT)
    net_edge = exp_move - cost
    if net_edge <= 0:
        flags.append("NET_EDGE_LOW: expected move does not cover fees and slippage")
    return {"symbol": sym, "ts": now, "direction": direction, "score": round(score, 1), "price": price,
            "factors": {k: round(v, 3) for k, v in factors.items()}, "penalty": round(penalty, 3),
            "flags": flags, "regime": reg, "net_edge_pct": round(net_edge, 3), "expected_move_pct": round(exp_move, 3),
            "detail": {"whale": winfo, "news": ninfo, "sentiment": sinfo}}

def explain(sig):
    """One-line reason in plain language (English; the dashboard shows it on the card)."""
    d, f = sig["detail"], sig["factors"]
    parts = []
    if abs(f["whale"]) > 0.15:
        side = "accumulating" if f["whale"] > 0 else "sending to exchanges"
        parts.append(f"{d['whale']['n_tx']} whale tx, smart-weighted flow {side} (${abs(d['whale']['net_usd_weighted'])/1e6:.1f}M)")
    if abs(f["news"]) > 0.15 and d["news"].get("top_title"):
        parts.append(f"news: \"{d['news']['top_title'][:70]}\" (price moved {d['news'].get('move_since_pct')}% since)")
    if abs(f["sentiment"]) > 0.15:
        parts.append(f"organic sentiment x{d['sentiment'].get('velocity')} vs 24h, bot share {d['sentiment'].get('bot_share')}")
    return "; ".join(parts) or "weak combined evidence"
