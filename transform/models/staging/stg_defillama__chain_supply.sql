-- One row per asset, chain and day: circulating supply from DefiLlama, in the
-- asset's own currency units.
--
-- Every snapshot holds the full daily history, so only the latest one per asset
-- is read. Assets DefiLlama doesn't list have a null llama_id and are skipped.

with snapshots as (
    select * from {{ source('raw', 'defillama_stablecoin_snapshots') }}
),

assets as (
    select * from {{ ref('assets') }}
),

latest_snapshots as (
    select
        asset_symbol,
        -- 'round' stops one over-precise number from failing the whole parse.
        parse_json(detail, wide_number_mode => 'round') as detail
    from snapshots
    where llama_id is not null
    qualify row_number() over (partition by asset_symbol order by snapshot_date desc) = 1
),

daily_balances as (
    select
        ls.asset_symbol,
        chain,
        token_day,
        concat('pegged', a.peg_currency) as peg_key
    from latest_snapshots as ls
    inner join assets as a
        on ls.asset_symbol = a.asset_symbol
    cross join unnest(json_keys(ls.detail.chainBalances, 1)) as chain
    cross join unnest(json_query_array(ls.detail.chainBalances[chain], '$.tokens')) as token_day
)

select
    asset_symbol,
    chain,
    date(timestamp_seconds(lax_int64(token_day.date))) as supply_date,
    -- Null means the value failed to parse, which the not_null test catches.
    safe_cast(json_value(token_day.circulating[peg_key]) as numeric) as circulating

from daily_balances

-- Drop rows with no figure in the asset's own currency, rather than reading
-- another currency as this one. XSGD on Ethereum has a bad peggedUSD row on
-- 2025-07-17: 30.6M against about 7.8M on the days around it.
where token_day.circulating[peg_key] is not null
