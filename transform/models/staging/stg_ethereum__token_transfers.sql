-- One row per ERC-20 Transfer event on Ethereum, labelled with its asset from
-- the contract registry and scaled to a human-readable amount.
--
-- Transfers are the left side of the join: every loaded transfer is kept, and
-- a contract missing from seeds/token_contracts.csv shows up as a null
-- asset_symbol, which the not_null test catches.

with transfers as (
    select * from {{ source('raw', 'ethereum_token_transfers') }}
),

contracts as (
    select * from {{ ref('token_contracts') }}
    where chain = 'ethereum'
)

select
    'ethereum' as chain,
    tc.asset_symbol,
    ett.token_address as contract_address,
    tc.contract_role,
    tc.counts_toward_supply,
    ett.transaction_hash,
    ett.log_index,
    ett.block_number,
    ett.block_timestamp,
    date(ett.block_timestamp) as block_date,
    ett.from_address,
    ett.to_address,
    -- value is a STRING because 18-decimal amounts overflow INT64. Keep the
    -- divisor BIGNUMERIC too: pow(10, n) returns FLOAT64, which would turn
    -- the result back into a float and drop digits.
    safe_cast(ett.value as bignumeric) / pow(cast(10 as bignumeric), tc.decimals) as amount,
    case
        when ett.from_address = '0x0000000000000000000000000000000000000000' then 'mint'
        when ett.to_address   = '0x0000000000000000000000000000000000000000' then 'burn'
        else 'transfer'
    end as transfer_type

from transfers as ett

left join contracts as tc
    on ett.token_address = tc.contract_address
