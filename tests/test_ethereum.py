from datetime import datetime, timedelta, timezone

import pytest

from ingest.ethereum import render_sql, start_timestamp

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


def test_partition_filter_uses_a_query_parameter_not_a_script_variable():
    # BigQuery can only prune partitions in its byte estimate when the filter
    # value is known before planning. A DECLAREd variable is not, so the
    # estimate becomes a full-history scan and the bytes cap rejects the query.
    sql = render_sql()
    assert "block_timestamp >= @start_ts" in sql
    assert "DECLARE" not in sql
