-- One row per token transfer event on every chain we load, in one shape. Marts
-- read this model, never a chain's staging model, so adding a chain means
-- adding its staging model here and nothing else.
--
-- Every staging model must output exactly these columns, in this order:
-- chain, asset_symbol, contract_address, contract_role, counts_toward_supply,
-- transaction_hash, log_index, block_number, block_timestamp, block_date,
-- from_address, to_address, amount, transfer_type. Each branch selects them by
-- name, so a staging model missing one fails here instead of union all quietly
-- pairing up columns by position.

{%- set chain_models = [
    'stg_ethereum__token_transfers',
] %}

{% for chain_model in chain_models %}
select
    chain,
    asset_symbol,
    contract_address,
    contract_role,
    counts_toward_supply,
    transaction_hash,
    log_index,
    block_number,
    block_timestamp,
    block_date,
    from_address,
    to_address,
    amount,
    transfer_type
from {{ ref(chain_model) }}
{% if not loop.last %}
union all
{% endif %}
{%- endfor %}
