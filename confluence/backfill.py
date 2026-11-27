"""History backfill for exchange candles and OKX funding. Public endpoints only.

Usage: python -m confluence.backfill [--days 365] [--tf 1h] [--symbols BTC,ETH]
Idempotent: INSERT OR IGNORE, resumes from the oldest stored candle. Throttled.
"""
import argparse
import time

from confluence.adapters import exchanges as ex

PAUSE = 0.25  # seconds between requests, stay well under public rate limits


def _sleep():
    time.sleep(PAUSE)


def backfill_coinbase(con, sym, tf, start, end):
    n, step = 0, ex.TF[tf][1] * 300 if ex.TF[tf][1] else 0
    if not step:
        return 0
    t = start
    while t < end:
        e = min(t + step, end)
        rows = ex.candles_coinbase(sym, tf, t, e)
        n += ex.save_candles(con, "coinbase", sym, tf, rows)
        con.commit()
        t = e
        _sleep()
    return n


def backfill_okx(con, sym, tf, start, end):
    """Walk backwards with history-candles (newest first, 'after' = older than ts)."""
    n, cursor = 0, int(end * 1000)
    while cursor > start * 1000:
        rows = ex.candles_okx(sym, tf, limit=100, after_ms=cursor, history=True)
        if not rows:
            break
        n += ex.save_candles(con, "okx", sym, tf, rows)
        con.commit()
        oldest = rows[0][0] * 1000
        if oldest >= cursor:
            break
        cursor = oldest
        _sleep()
    return n


def backfill_kraken(con, sym, tf, start, end):
    """Kraken OHLC serves only the latest 720 candles; take what exists."""
    rows = [r for r in ex.candles_kraken(sym, tf, start) if r[0] >= start]
    return ex.save_candles(con, "kraken", sym, tf, rows)


def backfill_funding_okx(con, sym, start, end):
    n, cursor = 0, int(end * 1000)
    while cursor > start * 1000:
        rows = ex.funding_okx_history(sym, 100, cursor)
        if not rows:
            break
        n += ex._insert(con, "INSERT OR IGNORE INTO ex_funding VALUES(?,?,?,?)",
                        [("okx", sym, t, r) for t, r in rows])
        con.commit()
        oldest = min(t for t, _ in rows) * 1000
        if oldest >= cursor:
            break
        cursor = oldest
        _sleep()
    return n


def run(con, days=365, tfs=("1h", "1d"), symbols=("BTC", "ETH"), now=None):
    ex.ensure_schema(con)
    now = int(now or time.time())
    start = now - days * 86400
    total = {}
    for sym in symbols:
        for tf in tfs:
            for name, fn in (("coinbase", backfill_coinbase), ("okx", backfill_okx),
                             ("kraken", backfill_kraken)):
                try:
                    total[(name, sym, tf)] = fn(con, sym, tf, start, now)
                except Exception as exc:
                    total[(name, sym, tf)] = "error: %s" % exc
        try:
            total[("okx_funding", sym)] = backfill_funding_okx(con, sym, start, now)
        except Exception as exc:
            total[("okx_funding", sym)] = "error: %s" % exc
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--tf", default="1h,1d")
    ap.add_argument("--symbols", default="BTC,ETH")
    a = ap.parse_args()
    from confluence import db
    con = db.connect()
    for k, v in run(con, a.days, tuple(a.tf.split(",")), tuple(a.symbols.split(","))).items():
        print(k, v)


if __name__ == "__main__":
    main()
