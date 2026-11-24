from datetime import datetime, timezone

import pytest

from ingest.backfill import parse_ts, render_sql, resolve_contracts

START = datetime(2023, 9, 7, tzinfo=timezone.utc)
END = datetime(2026, 11, 23, tzinfo=timezone.utc)


def test_window_bounds_are_literals_on_both_tables():
    # Literal bounds let the dry-run estimate prune partitions (PR #9).
    sql = "\n".join(line.split("--")[0] for line in render_sql(START, END).splitlines())  # code only
    assert "MERGE" not in sql and "DECLARE" not in sql
    assert sql.count("block_timestamp >= TIMESTAMP '2023-09-07 00:00:00.000000+00'") == 2
    assert sql.count("block_timestamp < TIMESTAMP '2026-11-23 00:00:00.000000+00'") == 2
    assert "NOT EXISTS" in sql and "@contracts" in sql


def test_rejects_empty_window():
    with pytest.raises(ValueError, match="before"):
        render_sql(END, START)


def test_parse_ts_defaults_to_utc():
    assert parse_ts("2023-09-07") == START


def test_resolves_assets_from_seed():
    assert resolve_contracts(["JPYC", "AUDD"], []) == [
        "0x4cce605ed955295432958d8951d0b176c10720d5",
        "0xe7c3d8c9a439fede00d2600032d5db0be71c3c29",
    ]


def test_unknown_asset_fails_loudly():
    with pytest.raises(ValueError, match="NOPE"):
        resolve_contracts(["NOPE"], [])
