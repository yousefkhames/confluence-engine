# Confluence Engine

[![Demo](https://img.shields.io/badge/demo-synthetic%20data-orange)](https://yousefkhames.github.io/confluence-engine/) ![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![deps](https://img.shields.io/badge/dependencies-stdlib%20only-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

**[Live demo (synthetic data)](https://yousefkhames.github.io/confluence-engine/)** | built with Khames's Instinct for Yousef Khames

A crypto-intelligence engine that merges **whale-wallet flow**, **news/macro events** and **social sentiment** into one 0-100 **Confluence Score**, with anti-manipulation filtering, wallet profiling, an insider radar, price-in detection, a tamper-evident (hash-chained) signal log, a no-look-ahead backtest, alerts and subscription-tier gating.

> **Paper signals only. Not financial advice.** There is no exchange order code, no trade button and no key handling in this repo. Playbooks write to a local paper ledger. Crypto is risky; this project makes no claim that it makes money.

## What is real and what is not
- **Real:** the scoring engine, hash-chained log, backtest, paper ledger, dashboard and the free public-data adapters (Coinbase candles, public news and Reddit RSS, mempool.space, a public Ethereum RPC, OKX funding/OI).
- **Synthetic:** the bundled demo and the live demo page use generated data with planted patterns (`confluence/demo.py`). Their hit rates only prove the plumbing works. They are not a track record.
- **Estimated or missing:** the liquidation map is an estimate. Whale direction needs your own address labels (`data/labels.json`). Billing, X/Twitter and Telegram feeds, and the research layer are not implemented.
- **Unproven:** there is no live track record yet. Judge the engine only on live signals accumulated in the log.

## Status (v0.1 MVP)
| Spec area | State |
|---|---|
| Data pipeline (prices, news RSS, Reddit RSS, BTC/ETH large tx, OKX funding/OI) | live adapters; free public endpoints only |
| Confluence formula (smart whale flow, unpriced news, organic sentiment velocity, manipulation penalty) | done: `scoring.py` |
| Price-in ratio / "too late" flag | done |
| Bot filter and manipulation flag | done (`nlp.flag_bots`) |
| Wallet profiling, market-maker detection, insider radar, entity clustering (basic) | done: `wallets.py` |
| Signal log with 15m/1h/4h/24h outcomes, tamper-evident | done: `signals.py` |
| Self-learning dynamic weights | basic: `signals.reweight` (needs 20+ logged outcomes) |
| Backtest / replay without look-ahead | done: `backtest.py` |
| Regime detection, net-edge, trade-setup calculator | done |
| Sector spillover, order-book absorption, estimated liquidation map, squeeze check | done (liquidation map is an estimate) |
| Playbooks, paper ledger, Tilt Guard | done: `paper.py` |
| Ask the Engine | rule-based, grounded in the DB: `ask.py` |
| Dashboard (cards, annotated chart, track record, post-mortem, research explorer) | done: `dashboard.py` |
| Tiers (free 15-min delay / pro / quant API) | gating logic only, with local tokens. **Billing is not implemented**; the prices in `config.py` are placeholders |
| Win AND loss post-mortems | basic: `postmortem.py` (expanded in the research layer) |
| Research layer (trade case studies, findings) | **not in this release**: only the `trade_cases` table exists, no `research/` code yet |

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
python3 -m confluence dashboard      # http://127.0.0.1:8080
python3 -m confluence token pro      # local API token for tier gating
python3 -m unittest discover -s tests
```
Set `CONFLUENCE_DB`, `WHALE_USD_MIN`, `SIGNAL_THRESHOLD`; for alerts set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`,
`DISCORD_WEBHOOK_URL` or `ALERT_WEBHOOK_URL` in your own environment. Nothing secret is stored in the repo.

## Reading backtest numbers
The bundled demo data is synthetic with planted patterns, so its hit rates only prove the plumbing works. Judge the
engine only on live signals accumulated in the log (the hash chain shows nothing was edited after the fact).
See ARCHITECTURE.md for module ownership and interfaces.

## Requirements
Python 3.9+ and the standard library only. No packages, no API keys.

## Safety review
Code reviewed before publishing: network calls go only to free public endpoints (listed above); the only POST is a read-only JSON-RPC call to a public Ethereum node. Alert sinks (Telegram, Discord, webhook) stay off unless you set their environment variables yourself, and `scan` runs them in dry-run mode. The dashboard binds to 127.0.0.1. Tests include a scan that fails if order-placement or private-key code appears.

## Layout
`confluence/` engine, adapters and dashboard | `tests/` offline unit tests | `docs/` static synthetic demo (`python3 docs/build_demo.py` rebuilds it) | `ARCHITECTURE.md` module ownership.

## Credits and license
Built with Khames's Instinct for Yousef Khames. MIT licensed, see `LICENSE`.
