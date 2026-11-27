"""Exchange and derivatives public data: Coinbase, Kraken, OKX.

Public, free, unauthenticated GET endpoints only. No keys, no orders.
Entry point for the engine: fetch(con) -> int (rows written).
Network access goes through _get(), which tests replace with a fake.
"""
import json
import sqlite3
import time
import urllib.parse
import urllib.request

UA = "confluence-research/0.1 (paper-only analytics)"
TIMEOUT = 15

# canonical symbol -> per-venue instrument ids
SYMBOLS = {
    "BTC": {"coinbase": "BTC-USD", "kraken": "XBTUSD", "okx": "BTC-USDT",
            "okx_swap": "BTC-USDT-SWAP", "kraken_perp": "PF_XBTUSD", "okx_uly": "BTC-USDT"},
    "ETH": {"coinbase": "ETH-USD", "kraken": "ETHUSD", "okx": "ETH-USDT",
            "okx_swap": "ETH-USDT-SWAP", "kraken_perp": "PF_ETHUSD", "okx_uly": "ETH-USDT"},
}
# timeframe -> (seconds, coinbase granularity, kraken minutes, okx bar)
TF = {
    "1m": (60, 60, 1, "1m"), "5m": (300, 300, 5, "5m"), "15m": (900, 900, 15, "15m"),
    "1h": (3600, 3600, 60, "1H"), "6h": (21600, 21600, None, "6H"),
    "4h": (14400, None, 240, "4H"), "1d": (86400, 86400, 1440, "1D"),
}
URLS = {
    "coinbase": "https://api.exchange.coinbase.com",
    "kraken": "https://api.kraken.com/0/public",
    "kraken_fut": "https://futures.kraken.com/derivatives/api/v3",
    "okx": "https://www.okx.com/api/v5",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ex_candles(
  venue TEXT, symbol TEXT, tf TEXT, ts INTEGER,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY(venue, symbol, tf, ts));
CREATE TABLE IF NOT EXISTS ex_orderbook(
  venue TEXT, symbol TEXT, ts INTEGER, best_bid REAL, best_ask REAL,
  spread_bps REAL, bid_depth REAL, ask_depth REAL, imbalance REAL, levels INTEGER,
  PRIMARY KEY(venue, symbol, ts));
CREATE TABLE IF NOT EXISTS ex_funding(
  venue TEXT, symbol TEXT, ts INTEGER, rate REAL,
  PRIMARY KEY(venue, symbol, ts));
CREATE TABLE IF NOT EXISTS ex_oi(
  venue TEXT, symbol TEXT, ts INTEGER, oi REAL, oi_usd REAL,
  PRIMARY KEY(venue, symbol, ts));
CREATE TABLE IF NOT EXISTS ex_liquidations(
  venue TEXT, symbol TEXT, ts INTEGER, side TEXT, size REAL, price REAL,
  PRIMARY KEY(venue, symbol, ts, side, size, price));
"""


def ensure_schema(con):
    con.executescript(SCHEMA)


def _get(url, params=None):
    """HTTP GET -> parsed JSON. Replaced in tests."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


# ---------- parsers (pure functions, tested offline) ----------

def parse_coinbase_candles(rows):
    # [time, low, high, open, close, volume]
    return [(int(r[0]), _f(r[3]), _f(r[2]), _f(r[1]), _f(r[4]), _f(r[5])) for r in rows or []]


def parse_kraken_candles(js):
    if js.get("error"):
        raise ValueError("kraken: %s" % js["error"])
    res = js.get("result", {})
    for k, v in res.items():
        if k != "last":
            # [time, o, h, l, c, vwap, vol, count]
            return [(int(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[6])) for r in v]
    return []


def parse_okx_candles(js):
    if js.get("code") not in (None, "0", 0):
        raise ValueError("okx: %s" % js.get("msg"))
    out = []
    for r in js.get("data", []):
        if len(r) > 8 and r[8] != "1":
            continue  # skip unconfirmed (still-forming) candle
        out.append((int(r[0]) // 1000, _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5])))
    return sorted(out)


def book_stats(bids, asks, levels=20):
    """bids/asks: lists of (price, size) best first."""
    if not bids or not asks:
        return None
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2.0
    bd = sum(p * s for p, s in bids[:levels])
    ad = sum(p * s for p, s in asks[:levels])
    tot = bd + ad
    return dict(best_bid=bb, best_ask=ba, spread_bps=(ba - bb) / mid * 1e4 if mid else None,
                bid_depth=bd, ask_depth=ad, imbalance=(bd - ad) / tot if tot else 0.0,
                levels=min(levels, len(bids), len(asks)))


def _lv(rows):
    return [(float(r[0]), float(r[1])) for r in rows]


# ---------- DB writers ----------

def _insert(con, sql, rows):
    n0 = con.total_changes
    con.executemany(sql, rows)
    return con.total_changes - n0


def save_candles(con, venue, symbol, tf, rows):
    return _insert(con, "INSERT OR IGNORE INTO ex_candles VALUES(?,?,?,?,?,?,?,?,?)",
                   [(venue, symbol, tf) + r for r in rows])


# ---------- per-venue fetchers ----------

def candles_coinbase(sym, tf, start, end):
    g = TF[tf][1]
    if not g:
        return []
    out, step = [], g * 300
    t = start
    while t < end:
        e = min(t + step, end)
        rows = _get("%s/products/%s/candles" % (URLS["coinbase"], SYMBOLS[sym]["coinbase"]),
                    {"granularity": g, "start": _iso(t), "end": _iso(e)})
        out += parse_coinbase_candles(rows)
        t = e
    return sorted(set(out))


def candles_kraken(sym, tf, since):
    m = TF[tf][2]
    if not m:
        return []
    js = _get(URLS["kraken"] + "/OHLC", {"pair": SYMBOLS[sym]["kraken"], "interval": m, "since": int(since)})
    rows = parse_kraken_candles(js)
    return rows[:-1] if rows else rows  # last candle is still forming


def candles_okx(sym, tf, limit=100, after_ms=None, history=False):
    p = {"instId": SYMBOLS[sym]["okx"], "bar": TF[tf][3], "limit": limit}
    if after_ms:
        p["after"] = after_ms
    path = "/market/history-candles" if history else "/market/candles"
    return parse_okx_candles(_get(URLS["okx"] + path, p))


def book_coinbase(sym):
    js = _get("%s/products/%s/book" % (URLS["coinbase"], SYMBOLS[sym]["coinbase"]), {"level": 2})
    return book_stats(_lv(js["bids"]), _lv(js["asks"]))


def book_kraken(sym):
    js = _get(URLS["kraken"] + "/Depth", {"pair": SYMBOLS[sym]["kraken"], "count": 50})
    if js.get("error"):
        raise ValueError("kraken: %s" % js["error"])
    v = next(iter(js["result"].values()))
    return book_stats(_lv([r[:2] for r in v["bids"]]), _lv([r[:2] for r in v["asks"]]))


def book_okx(sym):
    js = _get(URLS["okx"] + "/market/books", {"instId": SYMBOLS[sym]["okx"], "sz": 50})
    d = js["data"][0]
    return book_stats(_lv([r[:2] for r in d["bids"]]), _lv([r[:2] for r in d["asks"]]))


def funding_okx_current(sym):
    js = _get(URLS["okx"] + "/public/funding-rate", {"instId": SYMBOLS[sym]["okx_swap"]})
    d = js["data"][0]
    return [(int(d["fundingTime"]) // 1000, _f(d["fundingRate"]))]


def funding_okx_history(sym, limit=100, before_ms=None):
    p = {"instId": SYMBOLS[sym]["okx_swap"], "limit": limit}
    if before_ms:
        p["after"] = before_ms  # OKX: "after" = records older than this ts
    js = _get(URLS["okx"] + "/public/funding-rate-history", p)
    return [(int(d["fundingTime"]) // 1000, _f(d["realizedRate"] or d["fundingRate"])) for d in js.get("data", [])]


def oi_okx(sym):
    js = _get(URLS["okx"] + "/public/open-interest", {"instType": "SWAP", "instId": SYMBOLS[sym]["okx_swap"]})
    d = js["data"][0]
    return (int(d["ts"]) // 1000, _f(d.get("oiCcy")), _f(d.get("oiUsd")))


def kraken_fut_ticker(sym):
    """Kraken Futures public tickers: funding rate and open interest for the perp."""
    js = _get(URLS["kraken_fut"] + "/tickers")
    want = SYMBOLS[sym]["kraken_perp"]
    for t in js.get("tickers", []):
        if t.get("symbol") == want:
            return t
    return None


def liquidations_okx(sym, limit=100):
    """Public recent filled liquidation orders (OKX). Returns [(ts, side, size, price)]."""
    js = _get(URLS["okx"] + "/public/liquidation-orders",
              {"instType": "SWAP", "uly": SYMBOLS[sym]["okx_uly"], "state": "filled", "limit": limit})
    out = []
    for blk in js.get("data", []):
        for d in blk.get("details", []):
            out.append((int(d["ts"]) // 1000, d.get("posSide") or d.get("side"),
                        _f(d.get("sz")), _f(d.get("bkPx"))))
    return out


# ---------- entry point ----------

def _safe(errors, label, fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # one dead venue must not kill the rest
        errors.append("%s: %s" % (label, exc))
        return None


def fetch(con, symbols=("BTC", "ETH"), tfs=("1h", "1d"), now=None):
    """Pull latest public data from all three venues. Returns rows written."""
    ensure_schema(con)
    now = int(now or time.time())
    n, errors = 0, []
    for sym in symbols:
        for tf in tfs:
            sec = TF[tf][0]
            r = _safe(errors, "coinbase candles", candles_coinbase, sym, tf, now - sec * 100, now)
            if r:
                n += save_candles(con, "coinbase", sym, tf, r)
            r = _safe(errors, "kraken candles", candles_kraken, sym, tf, now - sec * 100)
            if r:
                n += save_candles(con, "kraken", sym, tf, r)
            r = _safe(errors, "okx candles", candles_okx, sym, tf)
            if r:
                n += save_candles(con, "okx", sym, tf, r)
        for venue, fn in (("coinbase", book_coinbase), ("kraken", book_kraken), ("okx", book_okx)):
            b = _safe(errors, venue + " book", fn, sym)
            if b:
                n += _insert(con, "INSERT OR IGNORE INTO ex_orderbook VALUES(?,?,?,?,?,?,?,?,?,?)",
                             [(venue, sym, now, b["best_bid"], b["best_ask"], b["spread_bps"],
                               b["bid_depth"], b["ask_depth"], b["imbalance"], b["levels"])])
        f = _safe(errors, "okx funding", funding_okx_current, sym)
        if f:
            n += _insert(con, "INSERT OR IGNORE INTO ex_funding VALUES(?,?,?,?)",
                         [("okx", sym, t, r) for t, r in f])
        o = _safe(errors, "okx oi", oi_okx, sym)
        if o:
            n += _insert(con, "INSERT OR IGNORE INTO ex_oi VALUES(?,?,?,?,?)", [("okx", sym) + o])
        t = _safe(errors, "kraken futures", kraken_fut_ticker, sym)
        if t:
            fr = _f(t.get("fundingRate"))
            if fr is not None:
                n += _insert(con, "INSERT OR IGNORE INTO ex_funding VALUES(?,?,?,?)",
                             [("kraken_fut", sym, now - now % 3600, fr)])
            oi = _f(t.get("openInterest"))
            if oi is not None:
                last = _f(t.get("last")) or 0
                n += _insert(con, "INSERT OR IGNORE INTO ex_oi VALUES(?,?,?,?,?)",
                             [("kraken_fut", sym, now - now % 3600, oi, oi * last or None)])
        L = _safe(errors, "okx liquidations", liquidations_okx, sym)
        if L:
            n += _insert(con, "INSERT OR IGNORE INTO ex_liquidations VALUES(?,?,?,?,?,?)",
                         [("okx", sym, ts, sd, sz, px) for ts, sd, sz, px in L])
    con.commit()
    fetch.last_errors = errors
    return n


def init(con):
    """Contract name for table creation."""
    ensure_schema(con)
