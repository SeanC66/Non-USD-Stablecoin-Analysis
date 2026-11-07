-- Our Ethereum supply should be within 1% of DefiLlama's.
-- Only assets measured from transfers that DefiLlama lists can be compared.
-- Warns rather than fails: a mismatch is a finding to explain, not to silence.
--
-- DefiLlama stamps a figure at midnight UTC, so its figure for a date is the
-- close of the day before. Compare it with our figure from that day, using its
-- latest real date: the mart's final row can be carried forward.

{{ config(severity='warn') }}

with supply as (
    select
        supply_date,
        asset_symbol,
        supply_method,
        eth_supply_defillama,
        lag(eth_supply_onchain) over (
            partition by asset_symbol
            order by supply_date
        ) as eth_supply_onchain_prior_day
    from {{ ref('mart_daily_supply') }}
)

select
    supply_date,
    asset_symbol,
    eth_supply_onchain_prior_day,
    eth_supply_defillama,
    eth_supply_onchain_prior_day - eth_supply_defillama as difference
from supply
where supply_date = (select max(supply_date) from {{ ref('stg_defillama__chain_supply') }})
    and supply_method = 'transfers'
    and eth_supply_defillama is not null
    and abs(eth_supply_onchain_prior_day - eth_supply_defillama) > 0.01 * eth_supply_defillama
