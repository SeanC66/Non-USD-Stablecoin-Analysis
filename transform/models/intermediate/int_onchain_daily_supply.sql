-- One row per chain, asset and day: circulating supply rebuilt from our own
-- transfers, from the asset's first supply event on that chain through today.
-- mart_daily_supply reads the Ethereum rows for eth_supply_onchain, and both
-- supply marts use the rows DefiLlama doesn't cover to fill its gaps (XSGD on
-- Base, see defillama_lists_chain).

with assets as (
    select * from {{ ref('assets') }}
),

transfers as (
    select * from {{ ref('int_token_transfers') }}
),

chain_supply as (
    select * from {{ ref('stg_defillama__chain_supply') }}
),

-- Wallets whose balance isn't circulating, such as JPYC's pre-minted
-- treasury (see #11). They sit outside circulation like the zero address.
excluded_holders as (
    select chain, asset_symbol, holder_address
    from {{ ref('supply_excluded_holders') }}
),

-- Each supply-relevant transfer, flagged by whether each side is outside
-- circulation: the zero address (mint or burn) or an excluded holder. Only
-- contracts that count toward supply, and never external assets, whose supply
-- moves outside standard events (see #17).
supply_flows as (
    select
        t.chain,
        t.asset_symbol,
        t.block_date,
        t.amount,
        t.transfer_type = 'mint' or from_excluded.holder_address is not null as from_outside,
        t.transfer_type = 'burn' or to_excluded.holder_address is not null as to_outside
    from transfers as t
    inner join assets as a
        on t.asset_symbol = a.asset_symbol
    left join excluded_holders as from_excluded
        on t.chain = from_excluded.chain
        and t.asset_symbol = from_excluded.asset_symbol
        and t.from_address = from_excluded.holder_address
    left join excluded_holders as to_excluded
        on t.chain = to_excluded.chain
        and t.asset_symbol = to_excluded.asset_symbol
        and t.to_address = to_excluded.holder_address
    where t.counts_toward_supply
        and a.supply_method = 'transfers'
),

-- Net change in circulating supply per chain, asset and day. Tokens entering
-- circulation (minted, or released from an excluded holder) add; tokens leaving
-- it subtract. A mint straight into a treasury, or a burn from one, changes
-- nothing.
daily_net_supply as (
    select
        chain,
        asset_symbol,
        block_date as supply_date,
        sum(
            case
                when from_outside and not to_outside then amount
                when to_outside and not from_outside then -amount
                else 0
            end
        ) as net_supply
    from supply_flows
    group by chain, asset_symbol, block_date
),

first_dates as (
    select chain, asset_symbol, min(supply_date) as first_date
    from daily_net_supply
    group by chain, asset_symbol
),

-- The end date is exclusive, so add a day to include today.
calendar as (
    select cast(date_day as date) as supply_date
    from (
        {{ dbt_utils.date_spine(
            datepart="day",
            start_date="cast('2019-01-01' as date)",
            end_date="date_add(current_date(), interval 1 day)"
        ) }}
    )
),

-- The chains DefiLlama reports for each asset, in our lower-case names. It
-- writes them capitalised (Ethereum, Base), so lower() maps one to the other.
defillama_chains as (
    select distinct asset_symbol, lower(chain) as chain
    from chain_supply
)

-- Running total. Summing over the calendar rather than daily_net_supply means
-- days with no mints or burns still get a row, carrying the previous total.
select
    c.supply_date,
    fd.chain,
    fd.asset_symbol,
    sum(coalesce(dns.net_supply, 0)) over (
        partition by fd.chain, fd.asset_symbol
        order by c.supply_date
    ) as circulating,
    dc.chain is not null as defillama_lists_chain
from calendar as c
inner join first_dates as fd
    on c.supply_date >= fd.first_date
left join daily_net_supply as dns
    on fd.chain = dns.chain
    and fd.asset_symbol = dns.asset_symbol
    and c.supply_date = dns.supply_date
left join defillama_chains as dc
    on fd.chain = dc.chain
    and fd.asset_symbol = dc.asset_symbol
