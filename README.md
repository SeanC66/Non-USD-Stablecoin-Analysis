# Non-USD Stablecoin Analysis

I've pulled together some public on chain data to look at Canadian stablecoin usage and adoption and how it compares to other non-USD stablecoins.

## Data notes

- **A7A5 in CAD:** the Bank of Canada stopped publishing the rouble rate (`FXRUBCAD`) after 2026-04-30. `mart_daily_supply` carries the last rate forward and sets `fx_is_stale` once it is more than 7 days old, so A7A5's `supply_cad` from 2026-05-08 onward uses an old rate and should be excluded or greyed out.
