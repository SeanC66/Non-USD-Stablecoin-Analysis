-- One row per asset, chain and day: where each stablecoin's supply sits, in its
-- own currency and in CAD. Only assets DefiLlama lists have rows.

with daily_supply as (
    select * from {{ ref('mart_daily_supply') }}
),

chain_supply as (
    select * from {{ ref('stg_defillama__chain_supply') }}
),

-- The first day each chain reports, so a chain only counts from when it starts.
chain_first_dates as (
    select asset_symbol, chain, min(supply_date) as first_date
    from chain_supply
    group by asset_symbol, chain
),

-- Fills across days DefiLlama skipped, the same way mart_daily_supply does before
-- it sums the chains. assert_chain_supply_sums_to_total keeps the two in step.
chain_days as (
    select
        ds.supply_date,
        ds.asset_symbol,
        cfd.chain,
        ds.cohort,
        ds.peg_currency,
        ds.cad_per_unit,
        ds.fx_is_stale,
        last_value(cs.circulating ignore nulls) over (
            partition by ds.asset_symbol, cfd.chain
            order by ds.supply_date
        ) as supply_native
    from daily_supply as ds
    inner join chain_first_dates as cfd
        on ds.asset_symbol = cfd.asset_symbol
        and ds.supply_date >= cfd.first_date
    left join chain_supply as cs
        on cfd.asset_symbol = cs.asset_symbol
        and cfd.chain = cs.chain
        and ds.supply_date = cs.supply_date
)

select
    supply_date,
    asset_symbol,
    chain,
    cohort,
    peg_currency,
    supply_native,
    cad_per_unit,
    fx_is_stale,
    supply_native * cad_per_unit as supply_cad
from chain_days
