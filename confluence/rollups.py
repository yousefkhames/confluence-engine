"""Rollups and retention so queries stay fast as data grows. All reads in the dashboard and assistant hit these
small tables or indexed time ranges; nothing scans a whole table.
  prices_1h        hourly OHLCV per symbol (built incrementally from 1-minute bars)
  daily_summary    per symbol per UTC day: whale flows, news count/mean sentiment, social count/bot share, signals, hits
  prune_minutes    drop 1-minute bars older than N days once they are rolled up (keeps hourly history)"""
import time

def init(con):
    con.executescript("""
CREATE TABLE IF NOT EXISTS prices_1h(symbol TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, ts));
CREATE TABLE IF NOT EXISTS daily_summary(symbol TEXT, day INTEGER, buy_usd REAL, sell_usd REAL, whale_tx INTEGER, news_n INTEGER,
  news_sent REAL, social_n INTEGER, bot_share REAL, signals_n INTEGER, hits_1h INTEGER, resolved_1h INTEGER, PRIMARY KEY(symbol, day));
CREATE TABLE IF NOT EXISTS rollup_state(k TEXT PRIMARY KEY, v REAL);
CREATE INDEX IF NOT EXISTS ix_signals_ts ON signals(ts);
CREATE INDEX IF NOT EXISTS ix_signals_sym ON signals(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_prices_ts ON prices(ts);
""")
    con.commit()

def _state(con, k, default=0):
    r = con.execute("SELECT v FROM rollup_state WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default

def _set(con, k, v):
    con.execute("INSERT INTO rollup_state VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

def roll_prices(con):
    """Incremental: only hours after the last rolled hour (the still-open current hour is skipped)."""
    init(con)
    last = int(_state(con, "prices_1h_last", 0))
    newest = con.execute("SELECT MAX(ts) t FROM prices WHERE ts>?", (last,)).fetchone()["t"]
    if not newest:
        return 0
    upto = (newest // 3600) * 3600   # exclusive: complete hours only
    cur = con.execute(
        "INSERT OR REPLACE INTO prices_1h SELECT a.symbol, a.h, o.open, a.hi, a.lo, c.close, a.vol FROM "
        "(SELECT symbol, (ts/3600)*3600 h, MIN(ts) t0, MAX(ts) t1, MAX(high) hi, MIN(low) lo, SUM(volume) vol "
        " FROM prices WHERE ts>=? AND ts<? GROUP BY symbol, h) a "
        "JOIN prices o ON o.symbol=a.symbol AND o.ts=a.t0 JOIN prices c ON c.symbol=a.symbol AND c.ts=a.t1", (last, upto))
    _set(con, "prices_1h_last", upto); con.commit()
    return cur.rowcount

def roll_daily(con, days_back=3):
    init(con)
    since = int(time.time()) - days_back * 86400 if days_back else 0
    mx = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
    if mx: since = int(mx) - days_back * 86400
    day0 = (since // 86400) * 86400
    n = 0
    for sym in [r["symbol"] for r in con.execute("SELECT DISTINCT symbol FROM prices_1h WHERE ts>=?", (day0,))] or \
               [r["symbol"] for r in con.execute("SELECT DISTINCT symbol FROM prices WHERE ts>=?", (day0,))]:
        d = day0
        while d <= (mx or d):
            e = d + 86400
            w = con.execute("SELECT COALESCE(SUM(CASE WHEN kind='from_exchange' THEN usd END),0) b, "
                            "COALESCE(SUM(CASE WHEN kind='to_exchange' THEN usd END),0) s, COUNT(*) n FROM whale_tx "
                            "WHERE symbol=? AND ts>=? AND ts<?", (sym, d, e)).fetchone()
            nw = con.execute("SELECT COUNT(*) n, AVG(sentiment) a FROM news WHERE symbol=? AND ts>=? AND ts<?", (sym, d, e)).fetchone()
            so = con.execute("SELECT COUNT(*) n, AVG(is_bot) b FROM social WHERE symbol=? AND ts>=? AND ts<?", (sym, d, e)).fetchone()
            sg = con.execute("SELECT COUNT(*) n, COALESCE(SUM(o.hit),0) h, COUNT(o.hit) r FROM signals s "
                             "LEFT JOIN outcomes o ON o.signal_id=s.id AND o.horizon='1h' WHERE s.symbol=? AND s.ts>=? AND s.ts<?",
                             (sym, d, e)).fetchone()
            con.execute("INSERT OR REPLACE INTO daily_summary VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sym, d, w["b"], w["s"], w["n"], nw["n"], nw["a"], so["n"], so["b"], sg["n"], sg["h"], sg["r"]))
            n += 1; d = e
    con.commit(); return n

def prune_minutes(con, keep_days=7):
    """Drop 1-minute bars older than keep_days that are already inside prices_1h. Returns rows deleted."""
    init(con)
    cutoff = min(int(_state(con, "prices_1h_last", 0)), int(time.time()) - keep_days * 86400)
    mx = con.execute("SELECT MAX(ts) t FROM prices").fetchone()["t"]
    if mx: cutoff = min(int(_state(con, "prices_1h_last", 0)), int(mx) - keep_days * 86400)
    cur = con.execute("DELETE FROM prices WHERE ts<?", (cutoff,)); con.commit()
    return cur.rowcount

def run_all(con, prune=False, keep_days=7):
    out = {"prices_1h": roll_prices(con), "daily": roll_daily(con)}
    if prune: out["pruned_1m_rows"] = prune_minutes(con, keep_days)
    return out
