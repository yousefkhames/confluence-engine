"""Live mass paper-trading test. Virtual money only: no accounts, no orders, no real funds, nothing is ever sent anywhere.

Every ROUND seconds the runner opens one simulated BUY and one SELL on every instrument at every horizon, regardless of
any expected result, then settles each at expiry from the live price stream. It stores compact cumulative counters
(instrument x horizon x direction x UTC hour), not raw trades, so the repo stays small.
Free public sources only: Binance public REST (all crypto pairs in one call, plus PAXG gold token) and Kraken public
REST (EUR/USD, GBP/USD, USD/JPY, AUD/USD, XAUT gold token). Silver and oil have no free live feed we could verify: not covered.
Honest limits: prices are sampled every SAMPLE seconds, so a 30s trade settles within about +-5s of expiry; the
GitHub runner restarts about every 30 minutes (pending trades are carried over, short ones that expire in a gap settle
late and are dropped, counted as 'dropped'). Latency, spread and slippage of a real venue are not modeled except a flat cost.
"""
import json, os, time, math, datetime, urllib.request

HORIZONS = {"30s": 30, "60s": 60, "5m": 300, "10m": 600, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "3h": 10800, "4h": 14400, "5h": 18000, "6h": 21600}
SAMPLE = 5
ROUND = 300
UA = "confluence-engine/0.2 (paper research; public endpoints only)"
CRYPTO = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "LTC", "BCH", "ATOM", "UNI", "NEAR", "APT", "ARB", "OP", "AAVE", "FIL", "ETC",
          "BNB", "TRX", "SHIB", "TON", "XLM", "HBAR", "SUI", "INJ", "MATIC", "SEI", "TIA", "RUNE", "FET", "RNDR", "PEPE", "WIF", "ALGO", "VET", "MKR", "CRV"]
FX = {"ZEURZUSD": "EURUSD", "ZGBPZUSD": "GBPUSD", "ZUSDZJPY": "USDJPY", "AUDUSD": "AUDUSD", "XAUTUSD": "XAUT_gold"}


def _get(url, timeout=15):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read())


def fetch_prices():
    """{instrument: price}. Failures drop that source only."""
    out = {}; errs = []
    try:
        for r in _get("https://data-api.binance.vision/api/v3/ticker/price"):
            s = r["symbol"]
            if s.endswith("USDT") and (s[:-4] in CRYPTO or s == "PAXGUSDT"):
                out[s[:-4] + ("_gold" if s == "PAXGUSDT" else "")] = float(r["price"])
    except Exception as e:
        errs.append("binance: %s" % e)
    try:
        res = _get("https://api.kraken.com/0/public/Ticker?pair=EURUSD,GBPUSD,USDJPY,AUDUSD,XAUTUSD")["result"]
        for k, v in res.items():
            if k in FX:
                out[FX[k]] = float(v["c"][0])
    except Exception as e:
        errs.append("kraken: %s" % e)
    return out, errs


def klass(inst):
    return "gold" if "gold" in inst else "fx" if inst in FX.values() else "crypto"


def session(hour):
    return "asia" if hour < 8 else "europe" if hour < 16 else "us"


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - w, 4), round(c + w, 4)]


def bh(pv, q=0.05):
    m = len(pv); order = sorted(range(m), key=lambda i: pv[i]); kmax = 0
    for r, i in enumerate(order, 1):
        if pv[i] <= q * r / m:
            kmax = r
    keep = [False] * m
    for r, i in enumerate(order, 1):
        if r <= kmax:
            keep[i] = True
    return keep


class Book:
    """Cumulative counters. key = 'inst|horizon|dir|hour' -> [n, wins, sum_ret_pct, sum_ret2, n_first_half..]. Plus pending trades."""
    def __init__(self):
        self.cells = {}; self.pending = []; self.meta = {"opened": 0, "settled": 0, "dropped": 0, "since": None, "cost_pct": 0.10}

    def open_round(self, prices, now, include_long=True):
        """Short horizons every round (5 min); horizons of 1h and more only on long rounds (every 30 min) to keep the state small."""
        n = 0
        for inst, p in prices.items():
            for h, secs in HORIZONS.items():
                if secs >= 3600 and not include_long:
                    continue
                for d in (1, -1):
                    self.pending.append([inst, h, d, p, now, now + secs]); n += 1
        self.meta["opened"] += n
        self.meta["since"] = self.meta["since"] or now

    def settle(self, prices, now, max_late=40):
        keep = []
        for t in self.pending:
            inst, h, d, p0, t0, texp = t
            if now < texp:
                keep.append(t); continue
            px = prices.get(inst)
            if px is None or now - texp > (max_late if texp - t0 < 3600 else 150):
                self.meta["dropped"] += 1; continue
            ret = (px / p0 - 1) * 100 * d
            k = "%s|%s|%s|%d" % (inst, h, "buy" if d == 1 else "sell", datetime.datetime.utcfromtimestamp(t0).hour)
            c = self.cells.setdefault(k, [0, 0, 0.0, 0.0, 0, 0])
            c[0] += 1; c[1] += ret > 0; c[2] += ret; c[3] += ret * ret
            self.meta["settled"] += 1
        self.pending = keep

    def to_json(self):
        return {"meta": self.meta, "cells": self.cells, "pending": self.pending}

    @staticmethod
    def from_json(j):
        b = Book(); b.meta.update(j.get("meta", {})); b.cells = j.get("cells", {}); b.pending = j.get("pending", []); return b


def aggregate(book, minimum=200):
    """Hit rates with Wilson bounds per grouping, binomial z-test vs 50% (buy and sell are both traded, so a no-edge market sits near 50%
    minus costs), Benjamini-Hochberg over every cell tested. A group is only 'significant' if it survives."""
    groups = {"horizon": {}, "instrument": {}, "class_horizon": {}, "session_horizon": {}, "instrument_horizon_dir": {}}
    for k, c in book.cells.items():
        inst, h, d, hr = k.split("|"); hr = int(hr)
        keys = {"horizon": h, "instrument": inst, "class_horizon": "%s|%s" % (klass(inst), h), "session_horizon": "%s|%s" % (session(hr), h),
                "instrument_horizon_dir": "%s|%s|%s" % (inst, h, d)}
        for g, key in keys.items():
            a = groups[g].setdefault(key, [0, 0, 0.0]); a[0] += c[0]; a[1] += c[1]; a[2] += c[2]
    out = {}; tests = []
    for g, d in groups.items():
        rows = []
        for key, (n, w, sr) in d.items():
            if n < minimum:
                continue
            z = (w / n - 0.5) / math.sqrt(0.25 / n)
            # n_eff: trades on the same instrument and horizon overlap in time and instruments move together: divide n by a conservative factor
            neff = max(2.0, n / 12.0); zadj = (w / n - 0.5) / math.sqrt(0.25 / neff)
            p = math.erfc(abs(zadj) / math.sqrt(2))
            row = {"key": key, "n": n, "hit_rate": round(w / n, 4), "ci95": wilson(w, n), "mean_ret_pct": round(sr / n, 4), "z_adj": round(zadj, 2), "p": p}
            rows.append(row); tests.append(row)
        out[g] = sorted(rows, key=lambda r: r["p"])[:60]
    keep = bh([t["p"] for t in tests])
    for t, k in zip(tests, keep):
        t["survives_fdr5"] = k; t["p"] = round(t["p"], 5)
    return {"groups": out, "tests": len(tests), "survivors": sum(keep), "min_n": minimum,
            "note": "n_eff = n/12 (overlapping trades, correlated instruments). Zero survivors means no instrument, horizon, class or session can be said to have an edge."}


def run(state_path, minutes=25, now_fn=time.time, sleep_fn=time.sleep, fetch=fetch_prices):
    book = Book.from_json(json.load(open(state_path))) if os.path.exists(state_path) else Book()
    end = now_fn() + minutes * 60; next_round = now_fn(); next_long = next_round; log = {"samples": 0, "errors": []}
    while now_fn() < end:
        t = now_fn(); prices, errs = fetch(); log["errors"] += errs[:1]; log["samples"] += 1
        if prices:
            book.settle(prices, t)
            if t >= next_round:
                book.open_round(prices, t, include_long=t >= next_long); next_round = t + ROUND
                if t >= next_long:
                    next_long = t + 1800
        sleep_fn(max(0.0, SAMPLE - (now_fn() - t)))
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    json.dump(book.to_json(), open(state_path, "w"), separators=(",", ":"))
    return book, log
