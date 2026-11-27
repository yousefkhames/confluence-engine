# Confluence Engine

Crypto-intelligence engine: whale-wallet flow + news/macro events + social sentiment merged into one 0-100
**Confluence Score**, with anti-manipulation filtering, wallet profiling, insider radar, price-in detection,
a hash-chained signal log, backtesting, alerts and subscription-tier gating.

**Analysis and paper signals only.** There is no exchange order code, no trade button and no key handling in this
repo. Playbooks write to a paper ledger. Not financial advice.

## Status (v0.1 MVP)
| Spec area | State |
|---|---|
| Data pipeline (prices, news RSS, Reddit RSS, BTC/ETH large tx, OKX funding/OI) | live adapters; free public endpoints only |
| Confluence formula (smart whale flow, unpriced news, organic sentiment velocity, manipulation penalty) | done: `scoring.py` |
| Price-in ratio / "too late" flag | done |
| Bot filter and manipulation flag | done (`nlp.flag_bots`) |
| Wallet profiling, market-maker detection, insider radar, entity clustering (basic) | done: `wallets.py` |
| Signal log with 15m/1h/4h/24h outcomes, tamper-evident | done: `signals.py` |
| Self-learning dynamic weights | done (basic): `signals.reweight` |
| Backtest / replay without look-ahead | done: `backtest.py` |
| Regime detection, net-edge, trade-setup calculator | done |
| Sector spillover, order-book absorption, estimated liquidation map, squeeze check | done (liquidation map is an estimate) |
| Playbooks, paper ledger, Tilt Guard | done: `paper.py` |
| Ask the Engine | rule-based, grounded in the DB: `ask.py` |
| Dashboard (cards, annotated chart, track record, post-mortem, research explorer) | done: `dashboard.py` |
| Tiers (free 15-min delay / pro / quant API) | gating done; billing not implemented |
| Win AND loss post-mortems | basic: `postmortem.py` (expanded in the research layer) |
| Research layer (trade case studies, findings, own demo logs) | in progress: `research/` |

## Live pipeline (v0.2: runs without any assistant)

A GitHub Actions workflow (`.github/workflows/pipeline.yml`) runs hourly (cron, minute 17). GitHub may delay scheduled runs by 5 to 30 minutes and disables schedules after 60 days without repo activity, so each run also commits a heartbeat to the `data` branch. Each run restores the dataset from the `data` branch, collects free public data, scans for signals, fills outcomes, re-fits weights and calibration (promoted only if a walk-forward test passes), retrains the ML model, writes everything back as JSONL, and redeploys the live dashboard to GitHub Pages. Free tier only. No secrets, no API keys.

- Live dashboard (REAL public data): https://yousefkhames.github.io/confluence-engine/
- Synthetic demo (planted patterns, NOT real): https://yousefkhames.github.io/confluence-engine/demo.html
- Dataset: the `data` branch (monthly JSONL per table, 5-minute price bars, model files, `model_card.json`).

### ML layer (paper only, no orders, no real money)
Logistic regression and gradient boosting (scikit-learn) predict P(up) per coin at 15m, 1h, 4h and 24h from price returns, volatility, news and social sentiment, whale activity, smart-money positioning, fear and greed and funding. Validation is walk-forward with an embargo of one horizon, after fees and slippage. The model card shows out-of-sample AUC, accuracy against the base rate, Brier score and paper PnL with a bootstrap interval, and says "not enough data yet" until there is enough. A horizon is labeled validated only if AUC > 0.53, at least 500 test samples, at least 100 paper trades and the lower end of the 95% interval is above zero. Otherwise it runs in shadow mode. Predictions are logged live and scored against later real prices: that log is the real track record. With a few days of data expect no edge; crypto at these horizons is close to a random walk.

### Data sources, honestly
| Source | Status |
|---|---|
| Coinbase candles, Kraken and OKX derivatives, mempool.space, public Ethereum RPC | real, free, no key |
| CoinDesk, CoinTelegraph, Decrypt, The Block, Bitcoin Magazine, CryptoSlate, The Defiant RSS | real, free |
| SEC and Federal Reserve press-release RSS, GDELT news index | real, free (GDELT is rate limited and may return nothing) |
| Fear and Greed index, DeFiLlama stablecoin supply | real, free |
| Hyperliquid leaderboard and public open positions of consistently profitable traders | real, free; picked by past profit (survivorship bias) |
| Hacker News, Mastodon tags, public Telegram previews | real, free, thin coverage |
| Reddit, Bluesky search | blocked from cloud IPs, shows as failing in the health panel |
| X/Twitter API, Arkham, Nansen, Whale Alert wallet labels | NOT available free, not used. No scraping behind logins |

Whale transfers are counted as activity only: direction needs wallet labels, so the whale weight stays near zero. Limits: GitHub cron is best effort, the `data` branch grows (old months are kept, the working window is 45 days), 5-minute bars, small samples early on.

## Free-data limits (honest list)
- X/Twitter and Telegram feeds need paid or keyed access: not used. Adapter hook `adapters/social.ingest_posts`.
- Binance is blocked in some regions; prices come from Coinbase public candles.
- Real liquidation heatmaps and wallet labels (Arkham/Nansen class) are paid. Provide your own `data/labels.json`
  (`{"0xaddr": "exchange:Name"}`); without it on-chain transfers have no direction and carry no weight.
- SQLite instead of TimescaleDB/Kafka for the MVP. Tables are plain and time-indexed; migration is a schema copy.

## Quick start
```
python3 -m confluence demo-data      # SYNTHETIC data, for offline demo and tests
python3 -m confluence backtest       # no look-ahead, runs on a copy of the DB
python3 -m confluence ingest         # live public data
python3 -m confluence profile        # wallet scores, clusters, insider scan
python3 -m confluence scan           # log signals + alerts (dry run prints)
python3 -m confluence outcomes       # fill 15m/1h/4h/24h results
python3 -m confluence rollup         # hourly/daily rollups (add --prune to drop old 1-min bars)
python3 -m confluence dashboard      # http://127.0.0.1:8080  (CONFLUENCE_DEMO=1 shows a synthetic-data banner)
python3 -m confluence token pro      # local API token for tier gating
python3 -m unittest discover -s tests
```
Set `CONFLUENCE_DB`, `WHALE_USD_MIN`, `SIGNAL_THRESHOLD`; for alerts set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`,
`DISCORD_WEBHOOK_URL` or `ALERT_WEBHOOK_URL` in your own environment. Nothing secret is stored in the repo.

## Reading backtest numbers
The bundled demo data is synthetic with planted patterns, so its hit rates only prove the plumbing works. Judge the
engine only on live signals accumulated in the log (the hash chain shows nothing was edited after the fact).
See ARCHITECTURE.md for module ownership and interfaces.

## Scaling notes
- Dashboard endpoints are paginated (`/api/feed?limit=&before_id=`, `/api/cases?limit=&offset=&market=`) and every query is time-bounded and indexed.
- `confluence rollup` builds `prices_1h` (incremental) and `daily_summary`; long chart ranges and the assistant's weekly/monthly answers read only these.
- `confluence rollup --prune --keep-days 7` drops 1-minute bars already covered by hourly rollups.
- Live view: `/api/live` proxies Coinbase public ticker/candles with a 5 s cache; the page also embeds the free TradingView widget (loads from TradingView's site in the browser).
- Research-workstream tests that live under `research/` run through `tests/test_research_pkgs.py`.
