-- One-time backfill: full Ethereum transfer history for the tracked non-USD stablecoins.
--
-- Why one table, one pass: the public token_transfers table is partitioned by
-- block_timestamp but not clustered by token_address, so cost depends on the
-- date range and columns scanned, not on how many tokens we filter for.
-- Dry run: ~0.95 TiB scanned, once. Daily incrementals afterwards scan ~1.3 GB/day.
--
-- The raw layer deliberately over-captures candidate contracts (legacy and
-- migrated deployments). The dbt seed `token_contracts.csv` decides which
-- contracts count toward each asset, with decimals, validity and legacy flags.
-- Never filter by symbol: the public tokens table lists ~100 contracts using
-- the "EURC" symbol alone.

CREATE SCHEMA IF NOT EXISTS `crypto-504119.raw`
OPTIONS (location = 'US', description = 'Raw ingested data. Do not model directly; use dbt staging.');

CREATE TABLE `crypto-504119.raw.ethereum_token_transfers`
PARTITION BY DATE(block_timestamp)
CLUSTER BY token_address
OPTIONS (description = 'ERC-20 Transfer events for tracked stablecoin contracts. Source: bigquery-public-data.crypto_ethereum.token_transfers.')
AS
SELECT
  token_address,
  from_address,
  to_address,
  value,              -- raw integer amount as STRING; scale by per-contract decimals in staging
  transaction_hash,
  log_index,
  block_number,
  block_timestamp,
  CURRENT_TIMESTAMP() AS _loaded_at
FROM `bigquery-public-data.crypto_ethereum.token_transfers`
WHERE token_address IN (
  -- CADD (Tetra) — verified on tetradg.com/legal/supported-blockchains
  '0x16f93ebc5320c89efc8701577efe49d14a276a06',
  -- QCAD (Stablecorp): 2019 original, 2020 legacy, two post-prospectus deployments (one to confirm)
  '0x196ce252320872694ae8650eeee22bce2c7f085f',
  '0x4a16baf414b8e637ed12019fad5dd705735db2e0',
  '0xa83dbfeacc5e125e34340f75dde7a710655a22f0',
  '0x3fa142dd3f384414e05e71ad0939274edc82ec0a',
  -- CADC (LOON) — listed on loon.finance
  '0xcadc0acd4b445166f12d2c07eac6e2544fbe2eef',
  -- EURC (Circle) — verified on developers.circle.com
  '0x1abaea1f7c830bd89acc67ec4af516284b1bc33c',
  -- XSGD (StraitsX) — verified on support.straitsx.com; second deployment to confirm
  '0x70e8de73ce538da2beed35d14187f6959a8eca96',
  '0x5256c4307e0ef634c072c9163b6d0d8c281526b8',
  -- BRZ (Transfero): 2019 contract (4 decimals) and 2023 migrated contract (18 decimals)
  '0x420412e765bfa6d85aaac94b4f7b708c89be2e2b',
  '0x01d33fd36ec67c6ada32cf36b31e88ee190b1839',
  -- A7A5 (Old Vector; sanctioned by US/UK/EU): current contract, earlier deployments, wrapper
  '0x6fa0be17e4bea2fcfa22ef89bf8ac9aab0ab0fc9',
  '0x4c743b2744ac10bc4e5c48781fa58c4834ef5f74',
  '0xcc66bf11d5128a48a693febbdc39ad954c1b5ff7',
  '0xf7261b7c013c676d7d81321b6f308d71260b54f0',
  '0x71355812dba6981b1bcb11091d973d669387ad45',
  '0xa4af52653ba7e46a8a43d81d6f63422e954b03f6',
  '0xc63266786fe3b047c163fcec6bb7b38d39139337',
  '0x0d57436f2d39c0664c6f0f2e349229483f87ea38'
);
