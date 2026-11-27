-- One row per asset per day: how much each stablecoin is actually used, from
-- the asset's first event through the latest complete UTC day loaded on every
-- chain (see chain_last_dates).
--
-- Counts are summed across every chain in int_token_transfers (Ethereum and Base
-- today), so chain is not part of the grain. Usage of an asset is the question
-- here, wherever it happens; a per-chain view can group int_token_transfers by
-- chain directly.

with assets as (
    select * from {{ ref('assets') }}
),

-- Test deployments and wrappers aren't real usage of the asset. Legacy contracts
-- are, even when they're outside supply (see #16). A7A5 stays in: #17 only rules
-- out its supply.
transfers as (
    select * from {{ ref('int_token_transfers') }}
    where contract_role in ('primary', 'legacy')
),

-- Ends at the latest complete UTC day every chain has reached, never a partial
-- one. A chain's latest loaded day stops wherever its load stopped: the day of
-- the run for Base (CDP is near real time, less an hour) and often for
-- Ethereum, or mid-day on an earlier date when Google's public dataset lags.
-- That day is undercounted until the next run fills it in.
--
-- So a chain counts as complete only through the day before its latest loaded
-- day: a transfer on day D means the load got past the end of D - 1. Both
-- chains have transfers within the first half hour of every UTC day, so this
-- drops a complete day only when a load stops in the last minutes of one, and
-- then by one day at most. Taking the earliest chain keeps a lagging chain
-- from showing false zeros, and capping at yesterday guards against a row
-- stamped in the future. mart_weekly_activity ends here too, and
-- assert_activity_ends_on_complete_day checks the rule.
chain_last_dates as (
    select chain, date_sub(max(block_date), interval 1 day) as last_complete_date
    from transfers
    group by chain
),

activity_end as (
    select least(
        min(last_complete_date),
        date_sub(current_date('UTC'), interval 1 day)
    ) as last_date
    from chain_last_dates
),

asset_date_ranges as (
    select
        asset_symbol,
        min(block_date) as first_date,
        (select last_date from activity_end) as last_date
    from transfers
    group by asset_symbol
),

-- The spine of the mart: one row per asset per day, with no gaps. Quiet days
-- need a row too, or averages and weekly rollups would skip them.
asset_days as (
    select
        activity_date,
        a.asset_symbol,
        a.cohort,
        a.peg_currency,
        a.public_launch_date
    from asset_date_ranges as adr
    cross join unnest(generate_date_array(adr.first_date, adr.last_date)) as activity_date
    inner join assets as a
        on adr.asset_symbol = a.asset_symbol
),

daily_events as (
    select
        asset_symbol,
        block_date as activity_date,
        countif(transfer_type = 'transfer') as transfers,
        countif(transfer_type = 'mint') as mints,
        countif(transfer_type = 'burn') as burns,
        sum(if(transfer_type = 'transfer', amount, 0)) as transfer_volume_native,
        max(if(transfer_type = 'transfer', amount, null)) as largest_transfer
    from transfers
    group by asset_symbol, block_date
),

-- Both sides of every transfer are in one column, so a wallet that sent and
-- received on the same day counts once.
daily_addresses as (
    select
        asset_symbol,
        activity_date,
        count(distinct address) as active_addresses,
        count(distinct if(side = 'sender', address, null)) as senders,
        count(distinct if(side = 'receiver', address, null)) as receivers
    from {{ ref('int_transfer_addresses') }}
    group by asset_symbol, activity_date
)

select
    ad.activity_date,
    ad.asset_symbol,
    ad.cohort,
    ad.peg_currency,
    -- Assets without a launch date are never pre-launch. Only CADD has activity
    -- before its date, which shouldn't count as adoption.
    coalesce(ad.activity_date < ad.public_launch_date, false) as is_pre_launch,
    coalesce(de.transfers, 0) as transfers,
    coalesce(de.mints, 0) as mints,
    coalesce(de.burns, 0) as burns,
    coalesce(da.active_addresses, 0) as active_addresses,
    coalesce(da.senders, 0) as senders,
    coalesce(da.receivers, 0) as receivers,
    coalesce(de.transfer_volume_native, 0) as transfer_volume_native,
    -- Null on days with no volume, including days of only zero-value transfers.
    safe_divide(de.largest_transfer, de.transfer_volume_native) as largest_transfer_share
from asset_days as ad
left join daily_events as de
    on ad.asset_symbol = de.asset_symbol
    and ad.activity_date = de.activity_date
left join daily_addresses as da
    on ad.asset_symbol = da.asset_symbol
    and ad.activity_date = da.activity_date
