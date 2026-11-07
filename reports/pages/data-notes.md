---
title: Data notes
sidebar_position: 4
---

Things we found in the data and how each one is handled.

```sql qcad_off_ethereum
select sum(supply_native) as supply_native
from marts.daily_chain_supply
where asset_symbol = 'QCAD'
    and chain != 'Ethereum'
    and supply_date = (select max(supply_date) from marts.daily_chain_supply)
```

## BRZ's legacy 150M

Adding up mints and burns across both BRZ contracts gave about 158M on Ethereum, while Etherscan showed about 8.2M for the 2023 contract. The gap was exactly 150M, all on the 2019 contract, where 93.4% sits in two wallets and 2% is stuck in the token contract itself. It's left out of supply ([#16](https://github.com/SeanC66/Non-USD-Stablecoin-Analysis/issues/16)), but transfers on that contract still count as activity.

DefiLlama doesn't list BRZ, so its supply is Ethereum only.

## A7A5's supply mechanics

Adding up mints and burns overstated A7A5's supply by about 411M. Nearly all of that, 410.6M, was tokens sent into a wrapper contract, which leaves supply without a standard burn. Supply also seems to appear without mint events: rebuilding balances from transfers leaves 2,787 wallets below zero, which is consistent with yield being credited directly to holders.

Because supply moves both ways outside standard events, A7A5's supply comes from DefiLlama instead ([#17](https://github.com/SeanC66/Non-USD-Stablecoin-Analysis/issues/17)). Its activity figures are still valid. A7A5 mainly circulates on Tron, so Ethereum is a partial view of its use.

## QCAD off Ethereum

QCAD has <Value data={qcad_off_ethereum} column=supply_native fmt="#,##0"/> outside Ethereum, which is why its all-chains figure sits slightly above its Ethereum figure. QCAD issued before its prospectus is a separate contract, tracked as `QCAD_LEGACY` and left out of these charts.

## The stale RUB rate

The Bank of Canada stopped publishing the rouble rate after 2026-04-30. The last rate is carried forward and flagged as stale from 2026-05-08, so A7A5's CAD value from then on uses an old rate.

## Jumps when a data source changes

Headline supply uses DefiLlama's all-chains figure when one exists, and our Ethereum figure before that. The first all-chains day can look like sudden growth, so these charts start each coin at that day. QCAD is the exception, because its switch moved supply by only 0.1%.

| Asset | First all-chains day | Change on that day |
|---|---|---|
| CADD | 2026-05-04 | +96.2% |
| XSGD | 2025-07-16 | +76.8% |
| CADC | 2023-12-08 | +21.4% |
| EURC | 2022-06-30 | -44.6% |
| QCAD | 2026-07-11 | +0.1% |

CADD's change falls on its launch day, so it can't be read as the effect of launching.

## How activity is counted

- **Zero-value transfers:** these don't count toward active addresses, senders or receivers. Anyone can send one to any wallet, so they look like spam rather than usage, and 11.4% of EURC's addresses appear in nothing else. Spam using tiny non-zero amounts isn't caught.
- **Before launch:** CADD's activity before its 2026-05-04 launch is flagged and left out of adoption figures.
- **Ethereum only:** transfers are loaded for Ethereum alone. Base is deferred ([#10](https://github.com/SeanC66/Non-USD-Stablecoin-Analysis/issues/10)), so usage on other chains isn't counted, even where supply is.
