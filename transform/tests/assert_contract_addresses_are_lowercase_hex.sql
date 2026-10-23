-- Addresses are compared as strings, so a single upper-case character would
-- silently drop a contract from every join.
select chain, contract_address
from {{ ref('token_contracts') }}
where not regexp_contains(contract_address, r'^0x[0-9a-f]{40}$')
