"""Incremental Ethereum load from the BigQuery public dataset."""

from __future__ import annotations

import logging
from pathlib import Path

from google.cloud import bigquery

from ingest import bq as bqh
from ingest.config import PROJECT, RAW_DATASET, load_contracts

log = logging.getLogger(__name__)

SQL_PATH = Path(__file__).parent / "sql" / "ethereum_incremental.sql"

# A day of the public transfers table is ~1.3 GB for the columns we read.
# 10 GB allows a week-long catch-up and blocks anything larger.
MAX_BYTES = 10_000_000_000


def render_sql() -> str:
    return SQL_PATH.read_text().format(project=PROJECT, dataset=RAW_DATASET)


def run(client: bigquery.Client, lookback_hours: int = 24) -> dict:
    contracts = sorted({c.address for c in load_contracts(chain="ethereum")})
    params = [
        bigquery.ArrayQueryParameter("contracts", "STRING", contracts),
        bigquery.ScalarQueryParameter("lookback_hours", "INT64", lookback_hours),
    ]
    job = bqh.run_query(client, render_sql(), params=params, max_bytes=MAX_BYTES, source="ethereum")

    # A script runs as child jobs; sum their stats for an honest run summary.
    inserted, billed = 0, 0
    for child in client.list_jobs(parent_job=job.job_id):
        inserted += getattr(child, "num_dml_affected_rows", 0) or 0
        billed += getattr(child, "total_bytes_billed", 0) or 0
    summary = {"contracts": len(contracts), "rows_inserted": inserted, "gb_billed": round(billed / 1e9, 2)}
    log.info("ethereum: %s", summary)
    return summary
