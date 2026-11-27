# SECURITY.md: Confluence Score engine (paper-only)

## Scope
Research and analytics only. The engine reads public, free data and scores it. It never places, signs or routes orders.

## Safety checklist (release gate; enforced by `python -m unittest discover tests`)
- [ ] No order or execution code: no functions like place/submit/cancel/execute order or trade; no broker or exchange client libraries (ccxt, alpaca, binance, ib_insync, web3 ...). `test_security.NoExecutionCode`
- [ ] Read-only HTTP: no POST/PUT/DELETE/PATCH, no request signing (hmac). confluence/adapters/* only GET public endpoints.
- [ ] No credentials or keys in any file; no `.env`, `.pem`, `.key`, `credentials.json`. Secret-pattern scan. `test_security.SecretScan`
- [ ] No logins, no paid data, no API keys, even free-tier keys. If a source demands a key, drop the source.
- [ ] No contacting anyone: no email, chat, form or social posting code (smtplib etc. blocked).
- [ ] Nothing personal about the user (name, phone, contacts, accounts). `test_security.test_nothing_personal`
- [ ] Standard library only. `test_security.StdlibOnly`
- [ ] Offline tests: adapters import without network; tests use fixtures. `test_contract.Adapters`
- [ ] Every trade case has source_url, market, outcome, why_what, confidence 0..1; `verified` is set only with a `how`. `test_contract.TradeCases`
- [ ] Losses carry their why; case base is not dominated by wins (survivorship check, needs 10+ rows).
- [ ] Self-reported results stay unverified (verified=0) unless independently confirmed.

## Deliberate exceptions (reviewed)
- `confluence/adapters/onchain.py` sends JSON-RPC POSTs to a public Ethereum RPC. Read-only methods only (eth_blockNumber, eth_getBlockByNumber). No keys, no signing. Any new POST method must be reviewed the same way.
- `confluence/adapters/public_feeds.py` sends read-only POSTs to the public Hyperliquid `info` endpoint (`clearinghouseState`, one public address per call) to read open positions of leaderboard traders. No key, no signing, no order endpoint.
- `pipeline/model.py` (scheduled job only) imports numpy and scikit-learn, installed from `requirements-pipeline.txt`. The core `confluence/` package stays standard-library only. The job saves model files with pickle and only ever loads files it wrote itself; never load a model file from an untrusted source.
- `confluence/alerts.py` can POST alert text to Telegram, Discord or a generic webhook. It is the one outbound write path. It is dry-run by default (stdout and data/alerts.log), activates only when the operator sets env vars on their own machine, and holds no credentials in code. Alerts carry signal text only, never order instructions. The CLI must not default to dry_run=False.

## Data handling
- Respect each source's robots.txt and terms; throttle requests; identify with a generic User-Agent, no personal info.
- Store only public data and the source URL. Keep fetched pages out of the repo if licensing is unclear.
- SQLite file is local; do not commit it.

## Known limits of the automated checks
Pattern scans catch common cases, not all. Do a manual read of every adapter for hidden writes or obfuscated strings (base64, string-built URLs) before release. Paper results are not live performance: slippage, fees and survivorship bias are not modelled unless stated.

## Reporting
Any finding of keys or execution code blocks the merge. Notify the integrator.
