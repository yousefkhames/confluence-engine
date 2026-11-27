# Decision log (engineering)
- Scope: all 8 spec parts, built in phases; MVP first. Paper signals only. No real-money execution code anywhere.
  "Trade Now", exchange API execution and affiliate fee capture are replaced by paper ledger + notification-only webhooks.
- Free/public data only: Coinbase public candles (Binance is geo-blocked), RSS news, Reddit RSS (rate-limited), mempool.space,
  free ETH RPC, OKX funding/OI. X/Twitter, Telegram firehose, paid wallet labels and liquidation heatmaps are not available free.
- SQLite instead of TimescaleDB/Kafka for the MVP; schema is plain and time-indexed for migration.
- Smart Money score uses Beta(1,1) shrinkage; calls judged only after their horizon elapsed (no look-ahead). Market makers capped at 0.3.
- Backtest runs on a DB copy; real signal log is never modified by it. Synthetic demo data only proves plumbing.
- Signal log is hash-chained (SHA-256 of prev hash + canonical JSON) so later edits are detectable.
- Self-reported trader results are treated as unverified (survivorship bias): verified=0, confidence <= 0.4.
- Every signal gets WHAT/HOW/WHERE/WHY records, for wins and losses (confluence/explain, confluence/postmortem.py).
- Worker split and merge order: see ARCHITECTURE.md and docs/workstreams.md.
