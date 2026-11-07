-- One row per asset per day: how much each stablecoin is actually used on
-- Ethereum, from the asset's first event through the latest day loaded.

with assets as (
    select * from {{ ref('assets') }}
),

-- Test deployments and wrappers aren't real usage of the asset. Legacy contracts
-- are, even when they're outside supply (see #16). A7A5 stays in: #17 only rules
-- out its supply.
transfers as (
    select * from {{ ref('stg_ethereum__token_transfers') }}
    where contract_role in ('primary', 'legacy')
),

-- Ends at the latest day loaded rather than today, so a late ingest doesn't
-- look like a day with no activity.
asset_date_ranges as (
    select
        asset_symbol,
        min(block_date) as first_date,
        (select max(block_date) from transfers) as last_date
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
