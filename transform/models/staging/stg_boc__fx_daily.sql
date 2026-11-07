-- One row per date and currency: Bank of Canada daily rates for the currencies
-- our assets are pegged to, plus USD.
--
-- Series stop or skip dates (FXRUBCAD ends 2026-04-30). Gaps are left as they
-- are here; the marts decide how to handle them.

with rates as (
    select * from {{ source('raw', 'boc_fx_daily') }}
)

select
    rate_date,
    -- series_id looks like FXEURCAD: the currency is the middle three letters.
    substr(series_id, 3, 3) as currency,
    cad_per_unit

from rates

where series_id in ('FXEURCAD', 'FXSGDCAD', 'FXBRLCAD', 'FXRUBCAD', 'FXUSDCAD')
