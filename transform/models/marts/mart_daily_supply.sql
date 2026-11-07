-- One row per asset per day: how much of each stablecoin exists, in its own
-- currency and in CAD, from the asset's first appearance through today.

with assets as (
    select * from {{ ref('assets') }}
),

transfers as (
    select * from {{ ref('stg_ethereum__token_transfers') }}
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

-- Net change in Ethereum supply per asset per day. Only contracts that count
-- toward supply, and never external assets, whose supply moves outside
-- standard events (see #17).
daily_net_supply as (
    select
        t.asset_symbol,
        t.block_date as supply_date,
        sum(
            case t.transfer_type
                when 'mint' then t.amount
                when 'burn' then -t.amount
                else 0
            end
        ) as net_supply
    from transfers as t
    inner join assets as a
        on t.asset_symbol = a.asset_symbol
    where t.counts_toward_supply
        and a.supply_method = 'transfers'
    group by t.asset_symbol, t.block_date
),

-- Running total. Summing over asset_days rather than daily_net_supply means
-- days with no mints or burns still get a row, carrying the previous total.
onchain_supply as (
    select
        ad.supply_date,
        ad.asset_symbol,
        case
            when ad.supply_method = 'transfers' then sum(coalesce(dns.net_supply, 0)) over (
                partition by ad.asset_symbol
                order by ad.supply_date
            )
        end as eth_supply_onchain
    from asset_days as ad
    left join daily_net_supply as dns
        on ad.asset_symbol = dns.asset_symbol
        and ad.supply_date = dns.supply_date
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
    left join fx_days as fxd
        on ad.peg_currency = fxd.currency
        and ad.supply_date = fxd.supply_date
),

-- The headline figure: all chains when DefiLlama has them, otherwise our own
-- Ethereum figure. It jumps on the day an asset switches source, so supply_source
-- says which one a reader is seeing.
with_headline as (
    select
        *,
        coalesce(total_supply_defillama, eth_supply_onchain) as supply_native,
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
    supply_native,
    supply_source,
    cad_per_unit,
    fx_is_stale,
    supply_native * cad_per_unit as supply_cad
from with_headline
