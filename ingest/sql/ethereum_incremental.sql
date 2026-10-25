-- Daily incremental load of Ethereum transfers for registered contracts.
--
-- Parameters (set by ingest/ethereum.py)
--   @contracts  ARRAY<STRING>  every Ethereum address in seeds/token_contracts.csv
--   @start_ts   TIMESTAMP      watermark minus the lookback window
--
-- Cost: the public table is partitioned by block_timestamp. Because @start_ts
-- is a query parameter, BigQuery knows its value before planning, prunes old
-- partitions, and bills ~1.3 GB per day of data. An earlier version computed
-- the start time in a script variable; BigQuery then estimated a full ~1 TiB
-- scan and the 10 GB bytes-billed cap rejected the query (at no charge).
--
-- Idempotency: MERGE on (transaction_hash, log_index), the natural key of an
-- ERC-20 Transfer event, so overlapping windows and re-runs never duplicate.

MERGE `{project}.{dataset}.ethereum_token_transfers` AS t
USING (
  SELECT
    token_address,
    from_address,
    to_address,
    value,
    transaction_hash,
    log_index,
    block_number,
    block_timestamp,
    CURRENT_TIMESTAMP() AS _loaded_at
  FROM `bigquery-public-data.crypto_ethereum.token_transfers`
  WHERE block_timestamp >= @start_ts
    AND token_address IN UNNEST(@contracts)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY transaction_hash, log_index ORDER BY block_number) = 1
) AS s
ON  t.transaction_hash = s.transaction_hash
AND t.log_index = s.log_index
AND t.block_timestamp >= @start_ts  -- limits the target side to recent partitions
WHEN NOT MATCHED THEN INSERT ROW;
