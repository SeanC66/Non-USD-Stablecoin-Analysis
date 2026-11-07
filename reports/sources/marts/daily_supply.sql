select
    supply_date,
    asset_symbol,
    cohort,
    peg_currency,
    supply_source,
    fx_is_stale,
    cast(eth_supply_onchain as float64) as eth_supply_onchain,
    cast(supply_native as float64) as supply_native,
    cast(supply_cad as float64) as supply_cad
from `crypto-504119.marts.mart_daily_supply`
