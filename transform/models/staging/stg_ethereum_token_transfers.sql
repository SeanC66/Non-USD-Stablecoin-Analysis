select 

    cast('ethereum' as string) as chain,
    tc.asset_symbol,
    tc.contract_address,
    tc.contract_role,
    tc.counts_toward_supply,
    ett.transaction_hash,
    ett.log_index,
    ett.block_number,
    ett.block_timestamp,,
    cast(left(ett.block_date, 10) as date) as block_date,
    ett.from_address,
    ett.to_address,
    cast(ett.value as float) as amount,
    cast(ett.from_address as string) as transfer_type
        where ett.from_address is ''



from raw.token_contracts as tc



left join raw.ethereum_token_transfers as ett on 