"""One-off Ethereum backfill for newly seeded contracts.

    python -m ingest.backfill --assets JPYC AUDD --start 2023-09-07 --end 2026-11-23 --dry-run
    python -m ingest.backfill --assets JPYC AUDD --start 2023-09-07 --end 2026-11-23 --max-gb 950

Renders backfill/ethereum_backfill_contracts.sql with literal timestamps so
the estimate reflects partition pruning. --dry-run prints the estimate and
bills nothing. A real run requires an explicit --max-gb cap.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from google.cloud import bigquery

from ingest import bq as bqh
from ingest.config import JOB_LABELS, PROJECT, RAW_DATASET, REPO_ROOT, load_contracts
from ingest.ethereum import timestamp_literal

log = logging.getLogger(__name__)

SQL_PATH = REPO_ROOT / "backfill" / "ethereum_backfill_contracts.sql"


def parse_ts(value: str) -> datetime:
    """A date (YYYY-MM-DD, midnight UTC) or an ISO timestamp; naive means UTC."""
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def render_sql(start: datetime, end: datetime) -> str:
    if start >= end:
        raise ValueError(f"start {start.isoformat()} must be before end {end.isoformat()}")
    return SQL_PATH.read_text().format(
        project=PROJECT,
        dataset=RAW_DATASET,
        start_ts=timestamp_literal(start),
        end_ts=timestamp_literal(end),
    )


def resolve_contracts(assets: list[str], contracts: list[str]) -> list[str]:
    """Ethereum addresses for the given asset symbols plus any explicit addresses.

    Assets must exist in seeds/token_contracts.csv, so a typo fails loudly
    instead of scanning the date range for nothing.
    """
    seeded = load_contracts(chain="ethereum")
    out = {c.lower() for c in contracts}
    for symbol in assets:
        matches = {c.address for c in seeded if c.asset_symbol == symbol}
        if not matches:
            raise ValueError(f"no Ethereum contracts seeded for asset {symbol}")
        out |= matches
    if not out:
        raise ValueError("pass --assets and/or --contracts")
    return sorted(out)


def run(
    client: bigquery.Client,
    contracts: list[str],
    start: datetime,
    end: datetime,
    max_bytes: int | None,
    dry_run: bool,
) -> dict:
    sql = render_sql(start, end)
    params = [bigquery.ArrayQueryParameter("contracts", "STRING", contracts)]
    summary = {"start_ts": start.isoformat(), "end_ts": end.isoformat(), "contracts": contracts}
    if dry_run:
        config = bigquery.QueryJobConfig(
            query_parameters=params, dry_run=True, use_query_cache=False, labels={**JOB_LABELS, "source": "backfill"}
        )
        job = client.query(sql, job_config=config)
        summary["gb_estimated"] = round((job.total_bytes_processed or 0) / 1e9, 2)
        summary["tib_estimated"] = round((job.total_bytes_processed or 0) / 2**40, 4)
    else:
        if not max_bytes:
            raise ValueError("a real run needs --max-gb")
        job = bqh.run_query(client, sql, params=params, max_bytes=max_bytes, source="backfill")
        summary["rows_inserted"] = job.num_dml_affected_rows or 0
        summary["gb_billed"] = round((job.total_bytes_billed or 0) / 1e9, 2)
        summary["job_id"] = job.job_id
    log.info("backfill: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.backfill", description=__doc__.split("\n\n")[0])
    parser.add_argument("--assets", nargs="*", default=[], help="asset symbols from seeds/token_contracts.csv")
    parser.add_argument("--contracts", nargs="*", default=[], help="extra Ethereum contract addresses")
    parser.add_argument("--start", required=True, type=parse_ts, help="inclusive, e.g. 2023-09-07")
    parser.add_argument("--end", required=True, type=parse_ts, help="exclusive, e.g. 2026-11-23")
    parser.add_argument("--dry-run", action="store_true", help="print the estimate; bills nothing")
    parser.add_argument("--max-gb", type=float, help="maximum_bytes_billed for a real run, in GB (1e9 bytes)")
    parser.add_argument("--print-sql", action="store_true", help="print the rendered SQL and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    contracts = resolve_contracts(args.assets, args.contracts)
    if args.print_sql:
        print(render_sql(args.start, args.end))
        print(f"-- @contracts = {contracts}")
        return 0
    max_bytes = int(args.max_gb * 1e9) if args.max_gb else None
    summary = run(bqh.client(), contracts, args.start, args.end, max_bytes, args.dry_run)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
