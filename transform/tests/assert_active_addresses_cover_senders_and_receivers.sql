-- Fails if a day has fewer active addresses than senders or receivers. Every
-- sender and receiver is an active address, so a failure means the two counts
-- were built from different transfers.

select
    activity_date,
    asset_symbol,
    active_addresses,
    senders,
    receivers
from {{ ref('mart_daily_activity') }}
where active_addresses < greatest(senders, receivers)
