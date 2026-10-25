"""Incremental Ethereum load from the BigQuery public dataset."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.cloud import bigquery

from ingest import bq as bqh
from ingest.config import PROJECT, RAW_DATASET, load_contracts, table_id

log = logging.getLogger(__name__)

SQL_PATH = Path(__file__).parent / "sql" / "ethereum_incremental.sql"
TABLE = "ethereum_token_transfers"

# A day of the public transfers table is ~1.3 GB for the columns we read.
# 10 GB allows a week-long catch-up and blocks anything larger.
MAX_BYTES = 10_000_000_000

# Beyond this gap, catching up should be a deliberate backfill, not the daily job.
MAX_STALENESS = timedelta(days=30)


def timestamp_literal(ts: datetime) -> str:
    """A BigQuery TIMESTAMP literal. Partition pruning in the cost estimate
    needs a constant here; the value comes from our own table, not user input."""
    return f"TIMESTAMP '{ts.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')}+00'"


def render_sql(start: datetime) -> str:
    return SQL_PATH.read_text().format(project=PROJECT, dataset=RAW_DATASET, start_ts=timestamp_literal(start))


def start_timestamp(watermark: datetime | None, lookback_hours: int, now: datetime | None = None) -> datetime:
    """Where the incremental scan begins: the watermark minus an overlap window.

    Refuses to run when the table is empty or too far behind, because either
    case would make the daily job scan years of history.
    """
    if watermark is None:
        raise RuntimeError(f"{TABLE} is empty. Run backfill/ethereum_backfill.sql first.")
    now = now or datetime.now(timezone.utc)
    if watermark < now - MAX_STALENESS:
        raise RuntimeError(
            f"Watermark {watermark.isoformat()} is more than {MAX_STALENESS.days} days old. "
            "Backfill the gap deliberately instead of letting the daily job scan it."
        )
    return watermark - timedelta(hours=lookback_hours)


def _watermark(client: bigquery.Client) -> datetime | None:
    sql = f"SELECT MAX(block_timestamp) AS watermark FROM `{table_id(TABLE)}`"
    return next(iter(bqh.run_query(client, sql, source="ethereum").result())).watermark


def run(client: bigquery.Client, lookback_hours: int = 24) -> dict:
    start = start_timestamp(_watermark(client), lookback_hours)
    contracts = sorted({c.address for c in load_contracts(chain="ethereum")})
    params = [bigquery.ArrayQueryParameter("contracts", "STRING", contracts)]
    job = bqh.run_query(client, render_sql(start), params=params, max_bytes=MAX_BYTES, source="ethereum")
    summary = {
        "start_ts": start.isoformat(),
        "contracts": len(contracts),
        "rows_inserted": job.num_dml_affected_rows or 0,
        "gb_billed": round((job.total_bytes_billed or 0) / 1e9, 2),
    }
    log.info("ethereum: %s", summary)
    return summary
