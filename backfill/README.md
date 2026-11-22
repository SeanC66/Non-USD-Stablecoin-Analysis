# Backfill queries for raw data ingestion

| File | What it does |
|---|---|
| `ethereum_backfill.sql` | The original one-time `CREATE TABLE ... AS` load of full history for the first set of contracts (~0.95 TiB). Historical; don't rerun it. |
| `ethereum_backfill_contracts.sql` | Template for backfilling contracts that were seeded later. `python -m ingest.backfill` renders and runs it. |

## Why new contracts need a backfill

The daily incremental (`ingest/sql/ethereum_incremental.sql`) only looks back 24 hours from the
table's watermark. A newly seeded contract therefore gets transfers from its seed date onward and
none of its history.

## Cost

`bigquery-public-data.crypto_ethereum.token_transfers` is partitioned by date but **not clustered
by token**. The bill depends on the date range, not on how many contracts are listed. So:

- backfill all new contracts in **one pass**, starting from the **earliest deployment date**;
- **dry-run first**, and check the estimate plus ~40 GB/month of daily runs fits the remaining
  1 TiB monthly free tier; if it doesn't, split the range across two calendar months;
- always set a cap (`--max-gb`) on the real run.

The template uses literal `TIMESTAMP` bounds. With query parameters or script variables the
estimate can't prune partitions and prices the whole table (the lesson from PR #9).
`NOT EXISTS` on `(transaction_hash, log_index)` makes reruns, overlapping split windows and
overlap with the daily incremental safe.

## How to run

```bash
# 1. Estimate (bills nothing). The window is [start, end), dates are UTC midnight.
python -m ingest.backfill --assets JPYC AUDD --start 2023-09-07 --end 2026-11-23 --dry-run

# Optional: inspect the rendered SQL.
python -m ingest.backfill --assets JPYC AUDD --start 2023-09-07 --end 2026-11-23 --print-sql

# 2. Real run, capped a little above the estimate. --max-gb is required.
python -m ingest.backfill --assets JPYC AUDD --start 2023-09-07 --end 2026-11-23 --max-gb 700
```

`--assets` resolves Ethereum addresses from `transform/seeds/token_contracts.csv`;
`--contracts 0x...` adds explicit addresses. Set `--end` to the day after the run date so the
window reaches the daily incremental's coverage; the overlap is deduplicated.

To split, run consecutive windows that share a boundary, e.g. `--start 2023-09-07 --end 2025-11-01`
in one month and `--start 2025-11-01 --end 2026-11-23` (or later) in the next.

## JPYC and AUDD (#33)

Deployment (proxy contract creation; ERC-20 `Transfer` events are emitted from the proxy address):

| Asset | Contract | Block | Timestamp (UTC) | Creation tx |
|---|---|---|---|---|
| AUDD | `0x4cce605ed955295432958d8951d0b176c10720d5` | 18,083,094 | 2023-09-07 07:33:59 | `0xc30e3baaeda08387366a9704080e8142364fdf652d81c2e1f7d3d7163538d2a0` |
| JPYC | `0xe7c3d8c9a439fede00d2600032d5db0be71c3c29` | 22,622,960 | 2025-06-03 08:32:35 | `0x5f9618fe7f2ea9a06abf1b94d731b8dd461b1388a9f63d83081f27613a1f25a7` |

Sources: Blockscout (`eth.blockscout.com/api/v2/addresses/<addr>` → `creation_transaction_hash`),
cross-checked with `eth_getTransactionByHash` (`to: null`, block number) and
`eth_getBlockByNumber` (timestamp) on a public RPC. The pass starts at AUDD's deployment date,
2023-09-07.

Dry-run estimates (2026-11-22, `--end 2026-11-23`):

| Window | Bytes processed | GB | TiB |
|---|---:|---:|---:|
| 2023-09-07 → 2026-11-23 (full) | 671,378,674,451 | 671.38 | 0.611 |
| 2023-09-07 → 2025-11-01 | | 329.18 | 0.299 |
| 2025-11-01 → 2026-11-23 | | 342.46 | 0.312 |
| 2023-09-07 → 2025-06-03 (before JPYC) | | 239.99 | 0.218 |
| 2025-06-03 → 2026-11-23 | | 431.57 | 0.393 |

Of the full estimate, the `NOT EXISTS` against `raw` accounts for about 0.13 GB
(128,786,364 bytes); the rest is the public table. Recent partitions are larger, so the last
year costs more than the two years before it.

## Run log

| Date (UTC) | Assets | Window | Estimate (GB) | GB billed | Rows inserted | Job ID |
|---|---|---|---:|---:|---:|---|
| 2026-11-22 | JPYC, AUDD | 2023-09-07 → 2026-11-23 | 671.38 | 671.43 | 126,925 (AUDD 22,334; JPYC 104,591) | `0464c490-f678-4a3f-8851-f341885132b4` |
