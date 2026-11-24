-- One-off backfill of Ethereum transfer history for newly seeded contracts.
--
-- Rendered by `python -m ingest.backfill` (see backfill/README.md):
--   {{start_ts}}, {{end_ts}}  TIMESTAMP literals, half-open window [start, end)
--   @contracts            ARRAY<STRING> parameter: the contracts to backfill
--
-- Same column shape and transformations as ingest/sql/ethereum_incremental.sql.
--
-- Cost: the public token_transfers table is partitioned by date but not
-- clustered by token, so the bill depends on the date range, not on how many
-- contracts are listed. Backfill several contracts in one pass, from the
-- earliest deployment date. The window bounds must be literals: with query
-- parameters the dry-run estimate cannot prune partitions and prices the
-- whole table (the lesson from PR #9).
--
-- Idempotency: NOT EXISTS skips any (transaction_hash, log_index) already in
-- raw, so a rerun, overlapping split windows, or overlap with the daily
-- incremental never duplicate rows.

INSERT INTO `{project}.{dataset}.ethereum_token_transfers`
  (token_address, from_address, to_address, value, transaction_hash, log_index, block_number, block_timestamp, _loaded_at)
SELECT
  s.token_address,
  s.from_address,
  s.to_address,
  s.value,
  s.transaction_hash,
  s.log_index,
  s.block_number,
  s.block_timestamp,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM `bigquery-public-data.crypto_ethereum.token_transfers` AS s
WHERE s.block_timestamp >= {start_ts}
  AND s.block_timestamp < {end_ts}
  AND s.token_address IN UNNEST(@contracts)
  AND NOT EXISTS (
    SELECT 1
    FROM `{project}.{dataset}.ethereum_token_transfers` AS t
    WHERE t.block_timestamp >= {start_ts}  -- only the window's partitions of our table
      AND t.block_timestamp < {end_ts}
      AND t.transaction_hash = s.transaction_hash
      AND t.log_index = s.log_index
  )
QUALIFY ROW_NUMBER() OVER (PARTITION BY s.transaction_hash, s.log_index ORDER BY s.block_number) = 1
