-- Fails if an asset's chain appears twice on a day, for example once from
-- DefiLlama and once from our own transfers. Chain names are compared in lower
-- case, since DefiLlama capitalises them and our transfers don't. A failure
-- means a chain is counted twice in supply_native.

select
    supply_date,
    asset_symbol,
    lower(chain) as chain,
    count(*) as chain_rows,
    string_agg(supply_source, ', ' order by supply_source) as supply_sources
from {{ ref('mart_daily_chain_supply') }}
group by supply_date, asset_symbol, lower(chain)
having count(*) > 1
