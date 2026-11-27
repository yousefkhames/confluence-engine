# Datasets

Versioned exports of every table in the Confluence database, written by `confluence/datasets.py`.
Paper-only research and analytics. Public, free sources only. Not investment advice.

## Make an export

    python -m confluence.datasets --out datasets/out            # version = UTC timestamp
    python -m confluence.datasets --out datasets/out --version v1

Or from code: `datasets.export_all(db.connect(), "datasets/out")`.

Each export goes in `datasets/out/<version>/` and is never overwritten.

## Files in a version

- `<table>.jsonl` one JSON object per row, sorted keys, UTF-8. NULL is `null`.
- `<table>.csv` same rows with a header line. NULL is an empty cell. Blobs are hex.
- `DATA_DICTIONARY.md` and `data_dictionary.json` table and column names, types, keys, row counts, descriptions.
- `manifest.json` version, creation time, per-file SHA-256, row counts, and `content_id`.

Rows are ordered by primary key (or all columns if none), so the same data gives the same files and the same `content_id`.
Check files with `datasets.verify("datasets/out/<version>")`; it returns a list of problems, empty when fine.

## Rules built in

- Columns whose names suggest secrets (password, token, api_key, secret, private_key, credential) are dropped.
- The export log table `dataset_exports` is not exported. Tables are found automatically, so tables from other workers are included.
- `trade_cases` descriptions are built in. Other tables get names and types only until a description is added to `KNOWN_DESCRIPTIONS`.

## Reading the data honestly

- `trade_cases.verified = 0` means the result is self-reported and unverified. Survivorship bias is likely: winners get posted more than losers.
- Always keep `source_url` and `confidence` with any finding you quote.
- Losses and their reasons (`why_what`, `how`, `where_ctx`) matter as much as wins.

## Tests

    python -m unittest tests.test_datasets
