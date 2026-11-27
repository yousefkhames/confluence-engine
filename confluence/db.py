import sqlite3, os
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices(symbol TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, ts));
CREATE TABLE IF NOT EXISTS news(id TEXT PRIMARY KEY, ts REAL, symbol TEXT, title TEXT, source TEXT, url TEXT,
  sentiment REAL, urgency REAL, credibility REAL);
CREATE TABLE IF NOT EXISTS whale_tx(txhash TEXT, ts REAL, symbol TEXT, from_addr TEXT, to_addr TEXT, usd REAL,
  kind TEXT, wallet TEXT, PRIMARY KEY(txhash, symbol));
CREATE TABLE IF NOT EXISTS social(id TEXT PRIMARY KEY, ts REAL, symbol TEXT, author TEXT, text TEXT,
  author_age_days REAL, sentiment REAL, engagement REAL, is_bot REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, symbol TEXT, direction TEXT,
  score REAL, price REAL, reason TEXT, factors TEXT, flags TEXT, net_edge_pct REAL, prev_hash TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS outcomes(signal_id INTEGER, horizon TEXT, price REAL, ret_pct REAL, hit INTEGER,
  PRIMARY KEY(signal_id, horizon));
CREATE TABLE IF NOT EXISTS wallets(addr TEXT PRIMARY KEY, label TEXT, smart_score REAL DEFAULT 0.5,
  n_calls INTEGER DEFAULT 0, n_hits INTEGER DEFAULT 0, insider_hits INTEGER DEFAULT 0, cluster TEXT);
CREATE TABLE IF NOT EXISTS weights(k TEXT PRIMARY KEY, v REAL);
CREATE TABLE IF NOT EXISTS api_keys(token TEXT PRIMARY KEY, tier TEXT, created REAL);
CREATE TABLE IF NOT EXISTS trade_cases(id TEXT PRIMARY KEY, collected_at REAL, source_type TEXT, source_url TEXT,
  market TEXT, instrument TEXT, side TEXT, entry_ts TEXT, entry_price REAL, exit_price REAL, size_note TEXT, outcome TEXT,
  pnl_note TEXT, why_what TEXT, how TEXT, where_ctx TEXT, lesson TEXT, verified INTEGER DEFAULT 0, confidence REAL, tags TEXT);
CREATE VIEW IF NOT EXISTS whale_tx_std AS SELECT txhash AS tx_hash, symbol AS chain, ts, from_addr, to_addr,
  symbol AS token, usd AS amount_usd, kind, wallet FROM whale_tx;
CREATE INDEX IF NOT EXISTS ix_cases ON trade_cases(market, outcome);
CREATE INDEX IF NOT EXISTS ix_news ON news(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_whale ON whale_tx(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_social ON social(symbol, ts);
"""

def connect(path=None):
    path = path or config.DB_PATH
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
