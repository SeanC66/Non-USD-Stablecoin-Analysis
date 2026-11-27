-- One row per ERC-20 Transfer event on Base, labelled with its asset from the
-- contract registry and scaled to a human-readable amount. Loaded from the
-- Coinbase CDP SQL API by ingest/base.py, which skips EURC on Base for now
-- (see EXCLUDED_ASSETS there and issue #10).
--
-- Transfers are the left side of the join: every loaded transfer is kept, and
-- a contract missing from seeds/token_contracts.csv shows up as a null
-- asset_symbol, which the not_null test catches.

with transfers as (
    select * from {{ source('raw', 'base_token_transfers') }}
),

contracts as (
    select * from {{ ref('token_contracts') }}
    where chain = 'base'
)

select
    'base' as chain,
    tc.asset_symbol,
    btt.token_address as contract_address,
    tc.contract_role,
    tc.counts_toward_supply,
    btt.transaction_hash,
    btt.log_index,
    btt.block_number,
    btt.block_timestamp,
    date(btt.block_timestamp) as block_date,
    btt.from_address,
    btt.to_address,
    -- value is a STRING because 18-decimal amounts overflow INT64; keep the
    -- divisor BIGNUMERIC so the result isn't turned back into a float.
    safe_cast(btt.value as bignumeric) / pow(cast(10 as bignumeric), tc.decimals) as amount,
    case
        when btt.from_address = '0x0000000000000000000000000000000000000000' then 'mint'
        when btt.to_address   = '0x0000000000000000000000000000000000000000' then 'burn'
        else 'transfer'
    end as transfer_type

from transfers as btt

left join contracts as tc
    on btt.token_address = tc.contract_address
