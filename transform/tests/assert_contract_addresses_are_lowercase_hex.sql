-- Addresses are compared as strings, so a single upper-case character would
-- silently drop a contract from every join.
select chain, contract_address as address
from {{ ref('token_contracts') }}
where not regexp_contains(contract_address, r'^0x[0-9a-f]{40}$')

union all

select chain, holder_address as address
from {{ ref('supply_excluded_holders') }}
where not regexp_contains(holder_address, r'^0x[0-9a-f]{40}$')
