with transfers as (
    select * from {{ source('raw', 'ethereum_token_transfers') }}
),

contracts as (
    select * from {{ ref('token_contracts') }}
    where chain = 'ethereum'
)

select 

    cast('ethereum' as string) as chain,
    tc.asset_symbol,
    tc.contract_address,
    tc.contract_role,
    tc.counts_toward_supply,
    ett.transaction_hash,
    ett.log_index,
    ett.block_number,
    ett.block_timestamp,,
    cast(left(ett.block_date, 10) as date) as block_date,
    ett.from_address,
    ett.to_address,
    safe_cast(ett.value as bignumeric) / pow(10, tc.decimals) as amount,
    case
        when ett.from_address = '0x0000000000000000000000000000000000000000' then 'mint'
        when ett.to_address   = '0x0000000000000000000000000000000000000000' then 'burn'
        else 'transfer'
    end as transfer_type

from contracts as tc

left join transfers as ett 
    on ett.token_address = tc.contract_address