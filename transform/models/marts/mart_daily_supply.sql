-- One row per asset per day: how much of each stablecoin exists, in its own
-- currency and in CAD, from the asset's first appearance through today.

with assets as (
    select * from {{ ref('assets') }}
),

-- Ethereum only, for when each asset first appears. eth_supply_onchain stays
-- Ethereum only, and other chains come from DefiLlama's all-chain total, plus
-- our own figure for chains DefiLlama doesn't list (unlisted_chain_supply).
transfers as (
    select * from {{ ref('int_token_transfers') }}
    where chain = 'ethereum'
),

fx_rates as (
    select * from {{ ref('stg_boc__fx_daily') }}
),

chain_supply as (
    select * from {{ ref('stg_defillama__chain_supply') }}
),

-- Every date we could need. The end date is exclusive, so add a day to include
-- today. The start matches the earliest FX history we load.
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

-- The dates each asset shows up in a source it's measured by. External assets
-- skip transfers: their on-chain figure is null by design, so starting there
-- would create rows with no supply.
source_dates as (
    select t.asset_symbol, t.block_date as seen_date
    from transfers as t
    inner join assets as a
        on t.asset_symbol = a.asset_symbol
    where t.counts_toward_supply
        and a.supply_method = 'transfers'

    union all

    select asset_symbol, supply_date as seen_date
    from chain_supply
),

first_appearance as (
    select asset_symbol, min(seen_date) as first_date
    from source_dates
    group by asset_symbol
),

-- The spine of the mart: one row per asset per day, with no gaps.
asset_days as (
    select
        c.supply_date,
        a.asset_symbol,
        a.cohort,
        a.peg_currency,
        a.supply_method
    from calendar as c
    inner join first_appearance as fa
        on c.supply_date >= fa.first_date
    inner join assets as a
        on fa.asset_symbol = a.asset_symbol
),

-- Our own supply per chain, rebuilt from transfers. int_onchain_daily_supply
-- applies the supply rules: contracts that count toward supply, no external
-- assets (see #17), and excluded holders treated like the zero address (#11).
onchain_daily as (
    select * from {{ ref('int_onchain_daily_supply') }}
),

-- Ethereum only. Days before an asset's first Ethereum event are zero, and
-- external assets are null by design.
onchain_supply as (
    select
        ad.supply_date,
        ad.asset_symbol,
        case
            when ad.supply_method = 'transfers' then coalesce(od.circulating, 0)
        end as eth_supply_onchain
    from asset_days as ad
    left join onchain_daily as od
        on ad.asset_symbol = od.asset_symbol
        and ad.supply_date = od.supply_date
        and od.chain = 'ethereum'
),

-- Our supply on chains we load transfers for but DefiLlama doesn't list for
-- the asset, such as XSGD on Base. It tops up DefiLlama's total in
-- with_headline and never overlaps it: a chain DefiLlama lists is left to it.
unlisted_chain_supply as (
    select
        supply_date,
        asset_symbol,
        sum(circulating) as onchain_supply_unlisted_chains
    from onchain_daily
    where not defillama_lists_chain
    group by supply_date, asset_symbol
),

-- The first day each chain reports, so a chain only counts from when it starts.
chain_first_dates as (
    select asset_symbol, chain, min(supply_date) as first_date
    from chain_supply
    group by asset_symbol, chain
),

-- One row per asset, chain and day, carrying the last reported figure across
-- days DefiLlama skipped. Fill each chain before summing: a chain missing a
-- day would otherwise look like its supply vanished from the total.
chain_days as (
    select
        c.supply_date,
        cfd.asset_symbol,
        cfd.chain,
        last_value(cs.circulating ignore nulls) over (
            partition by cfd.asset_symbol, cfd.chain
            order by c.supply_date
        ) as circulating
    from calendar as c
    inner join chain_first_dates as cfd
        on c.supply_date >= cfd.first_date
    left join chain_supply as cs
        on cfd.asset_symbol = cs.asset_symbol
        and cfd.chain = cs.chain
        and c.supply_date = cs.supply_date
),

defillama_supply as (
    select
        supply_date,
        asset_symbol,
        sum(if(chain = 'Ethereum', circulating, null)) as eth_supply_defillama,
        sum(circulating) as total_supply_defillama
    from chain_days
    group by supply_date, asset_symbol
),

-- CAD has no Bank of Canada series: it's fixed at 1 in the final select.
foreign_currencies as (
    select distinct peg_currency as currency
    from assets
    where peg_currency != 'CAD'
),

-- One row per currency per day. Rates are published on business days only, so
-- fill onto the calendar: filling within the rates table can't create the
-- weekends and holidays it doesn't have. rate_date is carried too, to tell how
-- old each rate is.
fx_days as (
    select
        c.supply_date,
        fc.currency,
        last_value(fx.cad_per_unit ignore nulls) over currency_history as cad_per_unit,
        last_value(fx.rate_date ignore nulls) over currency_history as rate_date
    from calendar as c
    cross join foreign_currencies as fc
    left join fx_rates as fx
        on fc.currency = fx.currency
        and c.supply_date = fx.rate_date
    window currency_history as (
        partition by fc.currency
        order by c.supply_date
    )
),

daily_figures as (
    select
        ad.*,
        os.eth_supply_onchain,
        ds.eth_supply_defillama,
        ds.total_supply_defillama,
        -- Only alongside a DefiLlama total: assets it doesn't list at all (BRZ,
        -- QCAD_LEGACY) are Ethereum only, already in eth_supply_onchain.
        if(ds.total_supply_defillama is not null, ucs.onchain_supply_unlisted_chains, null)
            as onchain_supply_unlisted_chains,
        if(ad.peg_currency = 'CAD', cast(1 as numeric), fxd.cad_per_unit) as cad_per_unit,
        -- RUB stops on 2026-04-30, so A7A5's CAD value goes stale after a week.
        ad.peg_currency != 'CAD' and date_diff(ad.supply_date, fxd.rate_date, day) > 7 as fx_is_stale
    from asset_days as ad
    left join onchain_supply as os
        on ad.asset_symbol = os.asset_symbol
        and ad.supply_date = os.supply_date
    left join defillama_supply as ds
        on ad.asset_symbol = ds.asset_symbol
        and ad.supply_date = ds.supply_date
    left join unlisted_chain_supply as ucs
        on ad.asset_symbol = ucs.asset_symbol
        and ad.supply_date = ucs.supply_date
    left join fx_days as fxd
        on ad.peg_currency = fxd.currency
        and ad.supply_date = fxd.supply_date
),

-- The headline figure: all chains when DefiLlama has them, plus our own figure
-- for chains it doesn't list, otherwise our own Ethereum figure. It jumps on the
-- day an asset switches source, so supply_source says which one a reader is
-- seeing. An unlisted chain isn't a switch: its supply starts from its first
-- mint, so adding it creates no jump.
with_headline as (
    select
        *,
        coalesce(
            total_supply_defillama + coalesce(onchain_supply_unlisted_chains, 0),
            eth_supply_onchain
        ) as supply_native,
        if(
            total_supply_defillama is not null,
            'defillama_all_chains',
            'ethereum_onchain'
        ) as supply_source
    from daily_figures
)

select
    supply_date,
    asset_symbol,
    cohort,
    peg_currency,
    supply_method,
    eth_supply_onchain,
    eth_supply_defillama,
    total_supply_defillama,
    onchain_supply_unlisted_chains,
    supply_native,
    supply_source,
    cad_per_unit,
    fx_is_stale,
    supply_native * cad_per_unit as supply_cad
from with_headline
