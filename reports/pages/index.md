---
title: Canadian stablecoins
sidebar_position: 1
---

Are Canadian stablecoins actually being used? This page looks at how much of each exists and where it sits. See [Activity](/activity) for usage.

```sql latest_supply
select asset_symbol, supply_cad
from marts.daily_supply
where asset_symbol in ('CADD', 'QCAD', 'CADC')
    and supply_date = (select max(supply_date) from marts.daily_supply)
order by supply_cad desc
```

```sql supply_over_time
-- All-chains figures only, so a change of source doesn't look like growth.
-- QCAD keeps its earlier Ethereum figures: its switch moved supply by 0.1%.
select supply_date, asset_symbol, supply_cad
from marts.daily_supply
where asset_symbol in ('CADD', 'QCAD', 'CADC')
    and (supply_source = 'defillama_all_chains' or asset_symbol = 'QCAD')
order by supply_date
```

```sql cadd_ethereum
select supply_date, eth_supply_onchain
from marts.daily_supply
where asset_symbol = 'CADD'
order by supply_date
```

```sql cadd_by_chain
select supply_date, chain, supply_cad
from marts.daily_chain_supply
where asset_symbol = 'CADD'
order by supply_date, chain
```

```sql latest_by_chain
select asset_symbol, chain, supply_cad
from marts.daily_chain_supply
where asset_symbol in ('CADD', 'QCAD', 'CADC')
    and supply_cad > 0
    and supply_date = (select max(supply_date) from marts.daily_chain_supply)
order by asset_symbol, supply_cad desc
```

## Supply today

<BarChart
    data={latest_supply}
    x=asset_symbol
    y=supply_cad
    yFmt="#,##0"
    title="Supply across all chains (CAD)"
    swapXY=true
/>

## Supply over time

<LineChart
    data={supply_over_time}
    x=supply_date
    y=supply_cad
    series=asset_symbol
    yFmt="#,##0"
    title="Supply across all chains (CAD)"
/>

CADD starts at its launch and CADC at 2023-12-08, the first days DefiLlama reports them. Earlier figures cover Ethereum only, so joining them on would show a jump that isn't real growth. [Data notes](/data-notes) has more.

## CADD before and after launch

<LineChart
    data={cadd_ethereum}
    x=supply_date
    y=eth_supply_onchain
    yFmt="#,##0"
    title="CADD supply on Ethereum, from mints and burns"
>
    <ReferenceLine x="2026-05-04" label="Public launch" hideValue={true}/>
</LineChart>

This chart uses Ethereum alone because it's the only figure that runs across the launch. CADD's all-chains figure starts on launch day.

## Supply by chain

<AreaChart
    data={cadd_by_chain}
    x=supply_date
    y=supply_cad
    series=chain
    yFmt="#,##0"
    title="CADD supply by chain (CAD)"
/>

<BarChart
    data={latest_by_chain}
    x=asset_symbol
    y=supply_cad
    series=chain
    yFmt="#,##0"
    title="Where each coin sits today (CAD)"
    swapXY=true
/>
