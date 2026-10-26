-- Fails if any contract's running net issuance (mints minus burns) drops
-- below zero on any day. Real ERC-20 supply can't go negative, so a failure
-- means missing history, wrong decimals, or a mislabelled mint or burn.
-- Only contracts that count toward supply are checked. The A7A5 test deployment
-- 0xa4af… burned 848,117.73 more than it minted (likely yield credited without
-- mint events), which is outside supply and not a pipeline error.

with daily as (
    select
        chain,
        contract_address,
        asset_symbol,
        block_date,
        sum(case transfer_type
                when 'mint' then amount
                when 'burn' then -amount
            end) as net_issuance
    from {{ ref('stg_ethereum__token_transfers') }}
        where transfer_type in ('mint', 'burn')
        and counts_toward_supply = true
    group by chain, contract_address, asset_symbol, block_date
),

running as (
    select
        *,
        sum(net_issuance) over (
            partition by chain, contract_address
            order by block_date
            rows between unbounded preceding and current row
        ) as running_supply
    from daily
)

select *
from running
where running_supply < 0