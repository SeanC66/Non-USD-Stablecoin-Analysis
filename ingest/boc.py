"""Bank of Canada daily FX rates (Valet API, group FX_RATES_DAILY).

All 27 published currency series are loaded in long format (date, series,
rate). The models need USD, EUR, SGD, BRL and RUB against CAD to put every
stablecoin's supply on one scale. Some series stop or skip dates, so the
loader keeps whatever is published and the models handle gaps.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import requests
from google.cloud import bigquery

from ingest import bq as bqh
from ingest.config import table_id

log = logging.getLogger(__name__)

URL = "https://www.bankofcanada.ca/valet/observations/group/FX_RATES_DAILY/json"
TABLE = "boc_fx_daily"
HISTORY_START = date(2019, 1, 1)  # covers the oldest tracked contract (BRZ, 2019)
REFETCH_DAYS = 7  # the Bank occasionally revises recent values

SCHEMA = [
    bigquery.SchemaField("rate_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("series_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("series_label", "STRING"),
    bigquery.SchemaField("cad_per_unit", "NUMERIC", description="Canadian dollars per one unit of the foreign currency"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP"),
]


def parse(payload: dict) -> list[dict]:
    labels = {sid: detail.get("label") for sid, detail in payload.get("seriesDetail", {}).items()}
    loaded_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for obs in payload.get("observations", []):
        for series_id, cell in obs.items():
            if series_id == "d" or not isinstance(cell, dict) or cell.get("v") in (None, ""):
                continue
            rows.append(
                {
                    "rate_date": obs["d"],
                    "series_id": series_id,
                    "series_label": labels.get(series_id),
                    "cad_per_unit": cell["v"],
                    "_loaded_at": loaded_at,
                }
            )
    return rows


def _start_date(client: bigquery.Client) -> date:
    sql = f"SELECT MAX(rate_date) AS last_date FROM `{table_id(TABLE)}`"
    last = next(iter(bqh.run_query(client, sql, source="boc").result())).last_date
    return HISTORY_START if last is None else last - timedelta(days=REFETCH_DAYS)


def run(client: bigquery.Client) -> dict:
    bqh.ensure_table(
        client,
        TABLE,
        SCHEMA,
        partition_field="rate_date",
        cluster_fields=["series_id"],
        description="Bank of Canada daily exchange rates (Valet FX_RATES_DAILY), long format.",
    )
    start = _start_date(client)
    resp = requests.get(URL, params={"start_date": start.isoformat()}, timeout=60)
    resp.raise_for_status()
    rows = parse(resp.json())
    merged = bqh.merge_rows(
        client, table_id(TABLE), rows, SCHEMA, key=["rate_date", "series_id"], update_existing=True, source="boc"
    )
    summary = {"start_date": start.isoformat(), "rows_fetched": len(rows), "rows_merged": merged}
    log.info("boc: %s", summary)
    return summary
