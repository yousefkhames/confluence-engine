"""Longer candle history for pattern backtests. Free Coinbase public candles (no key), grown a little every run."""
import time
from confluence import config
from confluence.adapters._http import get

TFS = {3600: 1500, 21600: 800, 86400: 400}   # granularity seconds -> max bars kept per coin
DDL = ("CREATE TABLE IF NOT EXISTS candles(symbol TEXT, tf INTEGER, ts INTEGER, open REAL, high REAL, low REAL, close REAL, "
       "volume REAL, PRIMARY KEY(symbol, tf, ts))")


def init(con):
    con.execute(DDL)


def _fetch(sym, tf, start=None, end=None):
    url = "https://api.exchange.coinbase.com/products/%s/candles?granularity=%d" % (config.PRODUCT[sym], tf)
    if start is not None:
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        url += "&start=%s&end=%s" % (iso(start), iso(end))
    return get(url, timeout=20)


def update(con, coins=None, budget_s=70):
    """Newest 300 bars per coin and timeframe, plus one older page until the cap. Returns {'rows': n, 'errors': n}."""
    t0 = time.time(); rows = errs = 0
    for sym in coins or config.COINS:
        for tf, cap in TFS.items():
            if time.time() - t0 > budget_s:
                return {"rows": rows, "errors": errs, "stopped": "time budget"}
            pages = [(None, None)]
            lo = con.execute("SELECT MIN(ts) m, COUNT(*) n FROM candles WHERE symbol=? AND tf=?", (sym, tf)).fetchone()
            if lo["n"] and lo["n"] < cap:
                pages.append((lo["m"] - 300 * tf, lo["m"]))
            for a, b in pages:
                try:
                    data = _fetch(sym, tf, a, b)
                except Exception:
                    errs += 1; continue
                con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?,?)",
                                [(sym, tf, r[0], r[3], r[2], r[1], r[4], r[5]) for r in data])
                rows += len(data); time.sleep(0.12)
    con.commit()
    return {"rows": rows, "errors": errs}


def series(con):
    """{(symbol, tf label): bars oldest first} using only CLOSED bars."""
    lab = {3600: "1h", 21600: "6h", 86400: "1d"}; out = {}; now = time.time()
    for r in con.execute("SELECT symbol, tf, ts, open, high, low, close, volume FROM candles ORDER BY symbol, tf, ts"):
        if r["ts"] + r["tf"] > now:
            continue   # still-forming bar
        out.setdefault((r["symbol"], lab[r["tf"]]), []).append((r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
    return out
