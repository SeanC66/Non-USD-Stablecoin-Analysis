from ingest.config import Asset
from ingest.defillama import match_assets

ASSETS = [
    Asset("EURC", "EUR", "benchmark"),
    Asset("QCAD", "CAD", "canadian"),
    Asset("QCAD_LEGACY", "CAD", "canadian"),
    Asset("CADD", "CAD", "canadian"),
]

LISTING = [
    {"id": "50", "symbol": "EURC", "pegType": "peggedEUR", "circulating": {"peggedEUR": 200_000_000}},
    {"id": "51", "symbol": "EURC", "pegType": "peggedEUR", "circulating": {"peggedEUR": 10}},  # copycat
    {"id": "52", "symbol": "EURC", "pegType": "peggedUSD", "circulating": {"peggedUSD": 999_999_999}},
    {"id": "60", "symbol": "QCAD", "pegType": "peggedCAD", "circulating": {"peggedCAD": 5_000_000}},
]


def test_matches_symbol_and_peg_currency_and_prefers_largest():
    assert match_assets(LISTING, ASSETS)["EURC"]["id"] == "50"


def test_wrong_peg_never_matches_even_if_larger():
    assert match_assets(LISTING[2:3], ASSETS)["EURC"] is None


def test_unlisted_asset_is_recorded_as_missing():
    assert match_assets(LISTING, ASSETS)["CADD"] is None


def test_legacy_qcad_does_not_borrow_the_current_qcad_listing():
    matches = match_assets(LISTING, ASSETS)
    assert matches["QCAD"]["id"] == "60"
    assert matches["QCAD_LEGACY"] is None
