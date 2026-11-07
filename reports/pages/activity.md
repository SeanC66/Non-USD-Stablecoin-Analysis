---
title: Activity
sidebar_position: 3
---

Supply shows how much exists. Activity shows whether anyone is using it. All figures are for Ethereum, in full weeks from Monday to Sunday, and CADD's start at its public launch.

```sql asset_list
select distinct asset_symbol
from marts.weekly_activity
order by asset_symbol
```

```sql canadian_weekly
select activity_week, asset_symbol, active_addresses, transfers
from marts.weekly_activity
where asset_symbol in ('CADD', 'QCAD', 'CADC')
    and days_in_week = 7
    and not is_pre_launch
    and activity_week >= '2026-05-04'
order by activity_week
```

```sql asset_weekly
select activity_week, active_addresses, transfers
from marts.weekly_activity
where asset_symbol = '${inputs.asset.value}'
    and days_in_week = 7
    and not is_pre_launch
order by activity_week
```

## Canadian coins since CADD's launch

<LineChart
    data={canadian_weekly}
    x=activity_week
    y=active_addresses
    series=asset_symbol
    title="Weekly active addresses"
/>

<LineChart
    data={canadian_weekly}
    x=activity_week
    y=transfers
    series=asset_symbol
    yFmt="#,##0"
    title="Weekly transfers"
/>

## Any asset

<Dropdown data={asset_list} name=asset value=asset_symbol defaultValue="CADD" title="Asset"/>

<LineChart
    data={asset_weekly}
    x=activity_week
    y=active_addresses
    yFmt="#,##0"
    title="Weekly active addresses"
/>

<LineChart
    data={asset_weekly}
    x=activity_week
    y=transfers
    yFmt="#,##0"
    title="Weekly transfers"
/>

Active addresses count wallets that sent or received a non-zero amount. Transfers count every transfer between wallets, including zero-value ones.
