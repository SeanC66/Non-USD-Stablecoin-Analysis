-- One row per asset, chain and day: where each stablecoin's supply sits, in its
-- own currency and in CAD. Only assets DefiLlama lists have rows. Chains come
-- from DefiLlama, plus any chain we load transfers for that DefiLlama doesn't
-- list for the asset (XSGD on Base), which supply_source marks.

with daily_supply as (
    select * from {{ ref('mart_daily_supply') }}
),

chain_supply as (
    select * from {{ ref('stg_defillama__chain_supply') }}
),

onchain_daily as (
    select * from {{ ref('int_onchain_daily_supply') }}
),

-- The first day each chain reports, so a chain only counts from when it starts.
chain_first_dates as (
    select asset_symbol, chain, min(supply_date) as first_date
    from chain_supply
    group by asset_symbol, chain
),

-- Fills across days DefiLlama skipped, the same way mart_daily_supply does before
-- it sums the chains. assert_chain_supply_sums_to_total keeps the two in step.
defillama_chain_days as (
    select
        ds.supply_date,
        ds.asset_symbol,
        cfd.chain,
        'defillama' as supply_source,
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
),

-- Our own figure for chains DefiLlama doesn't list, on the same days
-- mart_daily_supply adds them to its total: only alongside a DefiLlama total.
-- The chain is capitalised to match how DefiLlama writes the others.
onchain_chain_days as (
    select
        ds.supply_date,
        ds.asset_symbol,
        initcap(od.chain) as chain,
        'onchain_transfers' as supply_source,
        ds.cohort,
        ds.peg_currency,
        ds.cad_per_unit,
        ds.fx_is_stale,
        od.circulating as supply_native
    from daily_supply as ds
    inner join onchain_daily as od
        on ds.asset_symbol = od.asset_symbol
        and ds.supply_date = od.supply_date
    where not od.defillama_lists_chain
        and ds.total_supply_defillama is not null
),

chain_days as (
    select * from defillama_chain_days
    union all
    select * from onchain_chain_days
)

select
    supply_date,
    asset_symbol,
    chain,
    supply_source,
    cohort,
    peg_currency,
    supply_native,
    cad_per_unit,
    fx_is_stale,
    supply_native * cad_per_unit as supply_cad
from chain_days
