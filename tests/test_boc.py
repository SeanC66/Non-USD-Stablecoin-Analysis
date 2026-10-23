from ingest.boc import parse

# Shape confirmed against the live Valet response (FX_RATES_DAILY group).
PAYLOAD = {
    "terms": {"url": "https://www.bankofcanada.ca/terms/"},
    "groupDetail": {"label": "Daily exchange rates"},
    "seriesDetail": {
        "FXUSDCAD": {"label": "USD/CAD", "description": "US dollar to Canadian dollar daily exchange rate"},
        "FXRUBCAD": {"label": "RUB/CAD", "description": "Russian ruble to Canadian dollar daily exchange rate"},
    },
    "observations": [
        {"d": "2026-10-19", "FXUSDCAD": {"v": "1.4097"}},
        {"d": "2026-10-20", "FXUSDCAD": {"v": "1.4054"}, "FXRUBCAD": {"v": ""}},
    ],
}


def test_parse_emits_one_row_per_date_and_series():
    rows = parse(PAYLOAD)
    assert [(r["rate_date"], r["series_id"], r["cad_per_unit"]) for r in rows] == [
        ("2026-10-19", "FXUSDCAD", "1.4097"),
        ("2026-10-20", "FXUSDCAD", "1.4054"),
    ]
    assert rows[0]["series_label"] == "USD/CAD"


def test_parse_skips_missing_values_rather_than_writing_zero():
    assert all(r["series_id"] != "FXRUBCAD" for r in parse(PAYLOAD))


def test_parse_handles_empty_payload():
    assert parse({}) == []
