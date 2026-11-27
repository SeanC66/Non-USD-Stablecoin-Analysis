-- Fails if an asset's chains don't add up to its totals on any day: the
-- DefiLlama-sourced chains to total_supply_defillama, and all chains, including
-- those filled from our own transfers, to supply_native. mart_daily_chain_supply
-- fills gaps separately from mart_daily_supply, so a failure means the two have
-- drifted apart.

with chain_totals as (
    select
        supply_date,
        asset_symbol,
        sum(if(supply_source = 'defillama', supply_native, null)) as defillama_total,
        sum(supply_native) as chain_total
    from {{ ref('mart_daily_chain_supply') }}
    group by supply_date, asset_symbol
)

select
    ds.supply_date,
    ds.asset_symbol,
    ds.total_supply_defillama,
    ct.defillama_total,
    ds.supply_native,
    ct.chain_total
from {{ ref('mart_daily_supply') }} as ds
left join chain_totals as ct
    on ds.supply_date = ct.supply_date
    and ds.asset_symbol = ct.asset_symbol
where ds.total_supply_defillama is not null
    and (
        ct.chain_total is null
        or ct.defillama_total is distinct from ds.total_supply_defillama
        or ct.chain_total != ds.supply_native
    )
