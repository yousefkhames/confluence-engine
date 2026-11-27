"""SYNTHETIC data generator. Clearly fake: lets the whole pipeline, dashboard and backtest run offline and
gives tests a known ground truth (planted smart wallets, planted bot campaigns, planted market makers).
Never presented as real market data."""
import random, math, hashlib
from . import config

def _h(*a): return hashlib.md5("|".join(map(str, a)).encode()).hexdigest()

def generate(con, days=4, end_ts=1_795_800_000, seed=7, coins=None):
    rnd = random.Random(seed)
    coins = coins or config.COINS
    start = end_ts - days * 86400
    smart = [f"0xSMART{i}" for i in range(4)]
    mm = [f"0xMM{i}" for i in range(2)]
    randoms = [f"0xRAND{i}" for i in range(30)]
    events = []   # (coin, ts, kind)
    # --- plan events across the window
    for d in range(days * 4):
        t = start + 6 * 3600 * 1 + d * 5400 * 3 + rnd.randint(0, 1800)
        if t > end_ts - 5 * 3600:
            break
        c = rnd.choice(coins[3:])
        kind = rnd.choices(["insider_pump", "bot_dump", "bad_news_dump", "noise"], [0.4, 0.15, 0.2, 0.25])[0]
        events.append((c, t, kind))
    ev_by = {}
    for c, t, k in events:
        ev_by.setdefault(c, []).append((t, k))
    # --- prices (1-min bars), BTC drives a beta
    btc_drift = 0.0
    btc = []
    p = 60000.0
    for ts in range(start, end_ts, 60):
        p *= 1 + rnd.gauss(0, 0.0004)
        btc.append(p)
    rows = []
    for c in coins:
        price = rnd.uniform(0.5, 300) if c != "BTC" else 60000.0
        shift = {}
        for t, k in ev_by.get(c, []):
            if k == "insider_pump": shift[t + 1500] = ("ramp", 0.07)    # news at +25 min, pump after
            if k == "bad_news_dump": shift[t + 600] = ("ramp", -0.06)
            if k == "bot_dump": shift[t + 900] = ("ramp", -0.05)
        ramps = []
        prev_btc = btc[0]
        for i, ts in enumerate(range(start, end_ts, 60)):
            r = (btc[i] / prev_btc - 1) * (1.0 if c == "BTC" else 0.8) + rnd.gauss(0, 0.0007 if c != "BTC" else 0)
            prev_btc = btc[i]
            for st, (_, amt) in list(shift.items()):
                if st <= ts < st + 600:
                    r += amt / 10   # 10 one-minute bars
            price *= 1 + r
            o = price; hi = price * (1 + abs(rnd.gauss(0, 0.0003))); lo = price * (1 - abs(rnd.gauss(0, 0.0003)))
            vol = abs(rnd.gauss(50, 15)) * (3 if any(st <= ts < st + 600 for st in shift) else 1)
            rows.append((c, ts, o, hi, lo, price, vol))
    con.executemany("INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?)", rows)
    # --- whale, news, social
    def whale(c, ts, who, usd, kind, tag):
        con.execute("INSERT OR REPLACE INTO whale_tx VALUES(?,?,?,?,?,?,?,?)",
                    (_h(c, ts, who, tag), ts, c, who if kind == "from_exchange" else "0xX", "0xEX" if kind == "from_exchange" else "0xEX",
                     usd, kind, who))
    def news(c, ts, title, src, sent, urg, cred):
        con.execute("INSERT OR REPLACE INTO news VALUES(?,?,?,?,?,?,?,?,?)", (_h(c, ts, title), ts, c, title, src, "https://example.invalid/synthetic", sent, urg, cred))
    def social(c, ts, n, mood, bots=0):
        for i in range(n):
            bot = i < bots
            con.execute("INSERT OR REPLACE INTO social VALUES(?,?,?,?,?,?,?,?,?)",
                        (_h(c, ts, i, "s"), ts + rnd.random() * 600, c, f"bot{i}" if bot else f"user{rnd.randint(0,999)}",
                         f"{c} to the moon" if bot else f"thoughts on {c} {i}", 3 if bot else rnd.randint(40, 900),
                         0.9 if bot else mood + rnd.gauss(0, 0.2), 0 if bot else rnd.randint(0, 40), 0))
    for c in coins:   # baseline chatter + random whale noise
        for h in range(0, days * 24):
            social(c, start + h * 3600, rnd.randint(2, 5), rnd.gauss(0, 0.1))
        for _ in range(days * 3):
            t = start + rnd.randint(0, days * 86400)
            whale(c, t, rnd.choice(randoms), rnd.uniform(0.6e6, 3e6), rnd.choice(["from_exchange", "to_exchange"]), "n")
    for c, t, k in events:
        if k == "insider_pump":
            for w in rnd.sample(smart, 3):
                whale(c, t + rnd.randint(0, 600), w, rnd.uniform(2e6, 6e6), "from_exchange", "ev")
            news(c, t + 1500, f"{c} announces partnership with major exchange listing", "CoinDesk", 0.9, 0.7, 0.85)
            social(c, t + 1500, 40, 0.6)
        elif k == "bad_news_dump":
            whale(c, t, rnd.choice(smart), rnd.uniform(3e6, 8e6), "to_exchange", "ev")
            news(c, t + 300, f"{c} protocol hit by exploit, funds stolen", "CoinTelegraph", -0.9, 0.9, 0.75)
        elif k == "bot_dump":
            social(c, t, 80, 0.9, bots=70)
            whale(c, t + 300, rnd.choice(randoms), 1.2e6, "from_exchange", "ev")
        else:
            whale(c, t, rnd.choice(randoms), rnd.uniform(1e6, 3e6), rnd.choice(["from_exchange", "to_exchange"]), "ev")
    for w in mm:   # market makers: balanced buys and sells all the time
        for _ in range(16):
            c = rnd.choice(coins)
            t = start + rnd.randint(0, days * 86400)
            whale(c, t, w, 1e6, "from_exchange", "mmb"); whale(c, t + 60, w, 1e6, "to_exchange", "mms")
    con.commit()
    return {"start": start, "end": end_ts, "events": events, "smart_wallets": smart, "market_makers": mm}
