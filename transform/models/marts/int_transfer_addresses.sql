-- One row per side of every transfer that counts as usage. Shared by the daily
-- and weekly activity marts, so both count addresses the same way.

{{ config(materialized='ephemeral') }}

-- Test deployments and wrappers aren't real usage of the asset. Mints and burns
-- are left out, which also keeps the zero address out: it's only ever on one
-- side of those. Zero-value transfers are left out too: anyone can send one to
-- any wallet, so they look like spam rather than usage, and 11% of EURC's
-- addresses appear in nothing else.
with transfers as (
    select * from {{ ref('stg_ethereum__token_transfers') }}
    where contract_role in ('primary', 'legacy')
        and transfer_type = 'transfer'
        and amount > 0
)

select
    asset_symbol,
    block_date as activity_date,
    'sender' as side,
    from_address as address
from transfers

union all

select
    asset_symbol,
    block_date as activity_date,
    'receiver' as side,
    to_address as address
from transfers
