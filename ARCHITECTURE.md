# Architecture and ownership

Core (integrator): confluence/{config,db,nlp,market,wallets,scoring,signals,backtest,tiers,alerts,cli,dashboard}.py
Interfaces every workstream codes against:
- DB access: `from confluence import db; con = db.connect()`. Tables are in db.py. A workstream that needs a new table
  creates it with `CREATE TABLE IF NOT EXISTS` inside its own module `init(con)`; it never edits db.py.
- Adapters: `confluence/adapters/<name>.py` with `fetch(con) -> int` (rows written). Public endpoints only.
- Research cases: rows in `trade_cases` (schema in db.py) plus one markdown/JSON file per source under research/sources/.
  Every case needs source_url, market, outcome, why_what, how, where_ctx, verified (0 unless independently checkable),
  confidence 0-1. Self-reported results are verified=0 and capped at confidence 0.4.
- Tests: tests/test_<workstream>.py using unittest, offline (fixtures), no network.
- Safety: public pages only, no logins, no paid data, no contact with anyone, no order placement, no credentials.
