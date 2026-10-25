-- Daily incremental load of Ethereum transfers for registered contracts.
--
-- Rendered by ingest/ethereum.py:
--   {{start_ts}} TIMESTAMP literal: watermark minus the lookback window
--   @contracts   ARRAY<STRING> parameter: every Ethereum address in seeds/token_contracts.csv
--
-- Why INSERT ... NOT EXISTS and not MERGE: the 10 GB bytes-billed cap is
-- checked against BigQuery's estimate. For a MERGE, the estimate ignores
-- partition filters on the source and prices a full ~1 TiB scan, so the cap
-- rejects it, even though the real run bills about 1 GB. An INSERT with the
-- same filter estimates ~1.3 GB per day of data. (Dry runs, Oct 2026: MERGE
-- 1,045 GB; SELECT and INSERT with the same filter 4.2 GB.)
--
-- Idempotency: NOT EXISTS skips any (transaction_hash, log_index), the natural
-- key of an ERC-20 Transfer event, that is already loaded, so overlapping
-- windows and re-runs never duplicate rows.

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
  AND s.token_address IN UNNEST(@contracts)
  AND NOT EXISTS (
    SELECT 1
    FROM `{project}.{dataset}.ethereum_token_transfers` AS t
    WHERE t.block_timestamp >= {start_ts}  -- only recent partitions of our table
      AND t.transaction_hash = s.transaction_hash
      AND t.log_index = s.log_index
  )
QUALIFY ROW_NUMBER() OVER (PARTITION BY s.transaction_hash, s.log_index ORDER BY s.block_number) = 1
