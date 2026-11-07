select
    supply_date,
    asset_symbol,
    chain,
    cohort,
    cast(supply_native as float64) as supply_native,
    cast(supply_cad as float64) as supply_cad
from `crypto-504119.marts.mart_daily_chain_supply`
