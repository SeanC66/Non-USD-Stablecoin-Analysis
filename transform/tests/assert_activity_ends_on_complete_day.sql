-- Fails if mart_daily_activity reaches a day that may still be partial: today
-- or later, or any chain's latest loaded day. A chain's latest day is cut off
-- wherever its load stopped, so only the days before it are complete.

with activity_end as (
    select max(activity_date) as last_date
    from {{ ref('mart_daily_activity') }}
),

chain_last_dates as (
    select chain, max(block_date) as last_loaded_date
    from {{ ref('int_token_transfers') }}
    where contract_role in ('primary', 'legacy')
    group by chain
)

select
    cld.chain,
    cld.last_loaded_date,
    ae.last_date
from chain_last_dates as cld
cross join activity_end as ae
where ae.last_date >= cld.last_loaded_date
    or ae.last_date >= current_date('UTC')
