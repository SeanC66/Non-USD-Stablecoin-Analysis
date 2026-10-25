from datetime import datetime, timedelta, timezone

import pytest

from ingest.ethereum import render_sql, start_timestamp, timestamp_literal

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def test_start_is_watermark_minus_lookback():
    watermark = NOW - timedelta(days=3)
    assert start_timestamp(watermark, 24, now=NOW) == watermark - timedelta(hours=24)


def test_refuses_empty_table():
    with pytest.raises(RuntimeError, match="empty"):
        start_timestamp(None, 24, now=NOW)


def test_refuses_stale_watermark():
    with pytest.raises(RuntimeError, match="30 days"):
        start_timestamp(NOW - timedelta(days=31), 24, now=NOW)


def test_timestamp_literal_is_utc():
    eastern = timezone(timedelta(hours=-4))
    ts = datetime(2026, 10, 24, 20, 0, 0, 123456, tzinfo=eastern)
    assert timestamp_literal(ts) == "TIMESTAMP '2026-10-25 00:00:00.123456+00'"


def test_load_uses_insert_with_constant_partition_filter():
    # The bytes cap is checked against BigQuery's estimate. A MERGE, or a
    # filter on a script variable, makes the estimate a full ~1 TiB scan and
    # the cap rejects the query. An INSERT filtered on a constant prunes.
    sql = "\n".join(line.split("--")[0] for line in render_sql(NOW).splitlines())  # code only
    assert "MERGE" not in sql and "DECLARE" not in sql
    assert sql.count("block_timestamp >= TIMESTAMP '2026-10-25 12:00:00.000000+00'") == 2
    assert "NOT EXISTS" in sql
