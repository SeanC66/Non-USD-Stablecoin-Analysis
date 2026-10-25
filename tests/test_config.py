from ingest.config import load_assets, load_contracts
from ingest.ethereum import render_sql


def test_every_contract_points_at_a_known_asset():
    symbols = {a.symbol for a in load_assets()}
    assert {c.asset_symbol for c in load_contracts()} <= symbols


def test_contract_addresses_are_unique_per_chain():
    keys = [(c.chain, c.address) for c in load_contracts()]
    assert len(keys) == len(set(keys))


def test_chain_filter():
    assert {c.chain for c in load_contracts(chain="base")} == {"base"}


def test_ethereum_sql_reads_registry_parameters_not_hardcoded_addresses():
    sql = render_sql()
    assert "@contracts" in sql and "@start_ts" in sql
    assert "0x" not in sql.split("MERGE", 1)[1]
