-- One row per asset per week, Monday to Sunday. Active addresses are counted
-- again at this grain: summing the daily figure would count a wallet once for
-- every day it was active.

with daily_activity as (
    select * from {{ ref('mart_daily_activity') }}
),

weekly_totals as (
    select
        date_trunc(activity_date, week(monday)) as activity_week,
        asset_symbol,
        any_value(cohort) as cohort,
        any_value(peg_currency) as peg_currency,
        count(*) as days_in_week,
        logical_and(is_pre_launch) as is_pre_launch,
        sum(transfers) as transfers,
        sum(mints) as mints,
        sum(burns) as burns,
        sum(transfer_volume_native) as transfer_volume_native
    from daily_activity
    group by activity_week, asset_symbol
),

weekly_addresses as (
    select
        date_trunc(activity_date, week(monday)) as activity_week,
        asset_symbol,
        count(distinct address) as active_addresses
    from {{ ref('int_transfer_addresses') }}
    group by activity_week, asset_symbol
)

select
    wt.activity_week,
    wt.asset_symbol,
    wt.cohort,
    wt.peg_currency,
    wt.days_in_week,
    wt.is_pre_launch,
    wt.transfers,
    wt.mints,
    wt.burns,
    coalesce(wa.active_addresses, 0) as active_addresses,
    wt.transfer_volume_native
from weekly_totals as wt
left join weekly_addresses as wa
    on wt.asset_symbol = wa.asset_symbol
    and wt.activity_week = wa.activity_week
