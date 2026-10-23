-- Daily incremental load of Ethereum transfers for registered contracts.
--
-- Parameters
--   @contracts      ARRAY<STRING>  every Ethereum address in seeds/token_contracts.csv
--   @lookback_hours INT64          overlap re-read behind the watermark (default 24)
--
-- Cost: the public table is partitioned by block_timestamp, so only partitions
-- from the watermark onward are scanned (~1.3 GB per day of data). The guards
-- below fail the run rather than fall back to a full-history scan (~1 TiB).
--
-- Idempotency: MERGE on (transaction_hash, log_index), the natural key of an
-- ERC-20 Transfer event, so overlapping windows and re-runs never duplicate.

DECLARE watermark TIMESTAMP DEFAULT (
  SELECT MAX(block_timestamp) FROM `{project}.{dataset}.ethereum_token_transfers`
);
DECLARE start_ts TIMESTAMP;

IF watermark IS NULL THEN
  RAISE USING MESSAGE = 'ethereum_token_transfers is empty. Run backfill/ethereum_backfill.sql first.';
END IF;

IF watermark < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY) THEN
  RAISE USING MESSAGE = FORMAT(
    'Watermark %t is more than 30 days old. Backfill the gap deliberately instead of letting the daily job scan it.',
    watermark);
END IF;

SET start_ts = TIMESTAMP_SUB(watermark, INTERVAL @lookback_hours HOUR);

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
  WHERE block_timestamp >= start_ts
    AND token_address IN UNNEST(@contracts)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY transaction_hash, log_index ORDER BY block_number) = 1
) AS s
ON  t.transaction_hash = s.transaction_hash
AND t.log_index = s.log_index
AND t.block_timestamp >= start_ts  -- limits the target side to recent partitions
WHEN NOT MATCHED THEN INSERT ROW;
