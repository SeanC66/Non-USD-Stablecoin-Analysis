"""Thin BigQuery helpers: guarded queries and idempotent merges from Python rows."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery

from ingest.config import JOB_LABELS, LOCATION, PROJECT, RAW_DATASET

log = logging.getLogger(__name__)

# Default cap for any query this package runs. Callers that legitimately
# scan the public dataset pass a higher, explicit limit.
DEFAULT_MAX_BYTES = 1_000_000_000  # 1 GB


def client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT, location=LOCATION)


def run_query(
    bq: bigquery.Client,
    sql: str,
    params: list | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    source: str = "adhoc",
) -> bigquery.QueryJob:
    config = bigquery.QueryJobConfig(
        query_parameters=params or [],
        maximum_bytes_billed=max_bytes,
        labels={**JOB_LABELS, "source": source},
    )
    job = bq.query(sql, job_config=config)
    job.result()
    return job


def ensure_table(
    bq: bigquery.Client,
    name: str,
    schema: list[bigquery.SchemaField],
    partition_field: str | None = None,
    cluster_fields: list[str] | None = None,
    description: str = "",
) -> str:
    table_ref = f"{PROJECT}.{RAW_DATASET}.{name}"
    table = bigquery.Table(table_ref, schema=schema)
    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(field=partition_field)
    if cluster_fields:
        table.clustering_fields = cluster_fields
    table.description = description
    bq.create_table(table, exists_ok=True)
    return table_ref


def merge_rows(
    bq: bigquery.Client,
    target: str,
    rows: list[dict],
    schema: list[bigquery.SchemaField],
    key: list[str],
    update_existing: bool = False,
    source: str = "adhoc",
) -> int:
    """Load rows into a short-lived staging table, then MERGE on `key`.

    Load jobs are free; the MERGE only reads our own small tables. Returns the
    number of rows inserted or updated.
    """
    if not rows:
        return 0

    staging = f"{PROJECT}.{RAW_DATASET}._staging_{uuid.uuid4().hex[:12]}"
    staging_table = bigquery.Table(staging, schema=schema)
    staging_table.expires = datetime.now(timezone.utc) + timedelta(hours=1)
    bq.create_table(staging_table)
    try:
        load_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            labels={**JOB_LABELS, "source": source},
        )
        bq.load_table_from_json(rows, staging, job_config=load_config).result()

        columns = [f.name for f in schema]
        on = " AND ".join(f"t.{k} = s.{k}" for k in key)
        insert_cols = ", ".join(columns)
        insert_vals = ", ".join(f"s.{c}" for c in columns)
        update_clause = ""
        if update_existing:
            sets = ", ".join(f"{c} = s.{c}" for c in columns if c not in key)
            update_clause = f"WHEN MATCHED THEN UPDATE SET {sets}"
        sql = f"""
            MERGE `{target}` t
            USING `{staging}` s
            ON {on}
            {update_clause}
            WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
        """
        job = run_query(bq, sql, source=source)
        affected = job.num_dml_affected_rows or 0
        log.info("merged %s rows into %s (%s staged)", affected, target, len(rows))
        return affected
    finally:
        bq.delete_table(staging, not_found_ok=True)
