-- Fails if a week has fewer active addresses than its busiest day, or more than
-- all its days combined. Either means the weekly and daily counts were built
-- from different transfers.

with daily_by_week as (
    select
        date_trunc(activity_date, week(monday)) as activity_week,
        asset_symbol,
        max(active_addresses) as busiest_day,
        sum(active_addresses) as all_days
    from {{ ref('mart_daily_activity') }}
    group by activity_week, asset_symbol
)

select
    wa.activity_week,
    wa.asset_symbol,
    wa.active_addresses,
    dbw.busiest_day,
    dbw.all_days
from {{ ref('mart_weekly_activity') }} as wa
inner join daily_by_week as dbw
    on wa.activity_week = dbw.activity_week
    and wa.asset_symbol = dbw.asset_symbol
where wa.active_addresses < dbw.busiest_day
    or wa.active_addresses > dbw.all_days
