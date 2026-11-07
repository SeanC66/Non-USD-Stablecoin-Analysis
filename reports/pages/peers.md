---
title: Versus non-USD peers
sidebar_position: 2
---

How the Canadian coins compare with EURC, XSGD and BRZ. A7A5 is left out: it's a sanctions case study, not a peer.

```sql peer_supply
-- All-chains figures only, so a change of source doesn't look like growth.
-- QCAD's switch moved supply by 0.1%, and BRZ only has Ethereum figures.
select supply_date, asset_symbol, supply_cad
from marts.daily_supply
where asset_symbol in ('CADD', 'QCAD', 'CADC', 'EURC', 'XSGD', 'BRZ')
    and (supply_source = 'defillama_all_chains' or asset_symbol in ('QCAD', 'BRZ'))
    and supply_cad > 0
order by supply_date
```

```sql peer_activity
-- Log axes can't show zero, so quiet weeks appear as gaps.
select activity_week, asset_symbol, active_addresses
from marts.weekly_activity
where asset_symbol in ('CADD', 'QCAD', 'CADC', 'EURC', 'XSGD', 'BRZ')
    and days_in_week = 7
    and not is_pre_launch
    and active_addresses > 0
order by activity_week
```

```sql peer_table
with last_full_week as (
    select max(activity_week) as activity_week
    from marts.weekly_activity
    where days_in_week = 7
)

select
    s.asset_symbol as asset,
    s.cohort,
    s.supply_cad,
    w.active_addresses,
    w.transfers
from marts.daily_supply as s
inner join marts.weekly_activity as w
    on s.asset_symbol = w.asset_symbol
inner join last_full_week as lfw
    on w.activity_week = lfw.activity_week
where s.asset_symbol in ('CADD', 'QCAD', 'CADC', 'EURC', 'XSGD', 'BRZ')
    and s.supply_date = (select max(supply_date) from marts.daily_supply)
order by s.supply_cad desc
```

## Latest figures

<DataTable data={peer_table}>
    <Column id=asset/>
    <Column id=cohort/>
    <Column id=supply_cad title="Supply (CAD)" fmt="#,##0"/>
    <Column id=active_addresses title="Active addresses, last full week" fmt="#,##0"/>
    <Column id=transfers title="Transfers, last full week" fmt="#,##0"/>
</DataTable>

Supply covers all chains, except BRZ, which is Ethereum only. Activity is Ethereum only for every coin, so it understates coins with more of their use elsewhere.

## Supply

<LineChart
    data={peer_supply}
    x=supply_date
    y=supply_cad
    series=asset_symbol
    yLog={true}
    yFmt="#,##0"
    title="Supply in CAD (log scale)"
/>

The scale is logarithmic because EURC is hundreds of times larger than the Canadian coins: each gridline is 10 times the one below.

## Active addresses

<LineChart
    data={peer_activity}
    x=activity_week
    y=active_addresses
    series=asset_symbol
    yLog={true}
    yFmt="#,##0"
    title="Weekly active addresses on Ethereum (log scale)"
/>
