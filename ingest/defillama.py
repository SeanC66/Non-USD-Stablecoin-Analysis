"""DefiLlama stablecoin supply snapshots (free API, no key).

On-chain transfers only cover Ethereum and Base. DefiLlama reports
circulating supply on every chain, which is the only way to size tokens
that live mostly elsewhere (A7A5 on Tron, BRZ on Polygon and others).

Responses land as raw JSON, one row per asset per day; dbt parses them.
Assets are matched by symbol and peg currency rather than a hard-coded
DefiLlama id, and any tracked asset DefiLlama doesn't list is logged and
recorded as missing, not silently skipped.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests
from google.cloud import bigquery

from ingest import bq as bqh
from ingest.config import Asset, load_assets, table_id

log = logging.getLogger(__name__)

BASE_URL = "https://stablecoins.llama.fi"
TABLE = "defillama_stablecoin_snapshots"

SCHEMA = [
    bigquery.SchemaField("snapshot_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("asset_symbol", "STRING", mode="REQUIRED", description="Symbol from seeds/assets.csv"),
    bigquery.SchemaField("llama_id", "STRING", description="DefiLlama stablecoin id; null when not listed"),
    bigquery.SchemaField("list_entry", "STRING", description="Raw JSON from /stablecoins"),
    bigquery.SchemaField("detail", "STRING", description="Raw JSON from /stablecoin/{id}, incl. per-chain history"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP"),
]


def match_assets(pegged_assets: list[dict], assets: list[Asset]) -> dict[str, dict | None]:
    """Map each tracked asset to its DefiLlama list entry (or None).

    Symbols collide across issuers, so the peg currency must match too
    (DefiLlama pegType looks like "peggedEUR"). If several entries still
    match, take the one with the largest circulating supply and log it.
    """
    matches: dict[str, dict | None] = {}
    for asset in assets:
        symbol = asset.symbol.split("_")[0]  # QCAD_LEGACY shares the QCAD listing, if any
        candidates = [
            p
            for p in pegged_assets
            if (p.get("symbol") or "").upper() == symbol.upper()
            and (p.get("pegType") or "").upper() == f"PEGGED{asset.peg_currency}"
        ]
        if len(candidates) > 1:
            log.warning("%s matches %s DefiLlama entries; using the largest", asset.symbol, len(candidates))
            candidates.sort(key=lambda p: _circulating(p, asset.peg_currency), reverse=True)
        matches[asset.symbol] = candidates[0] if candidates else None
    # Legacy QCAD has no listing of its own; don't double-attribute the QCAD entry to it.
    if "QCAD_LEGACY" in matches:
        matches["QCAD_LEGACY"] = None
    return matches


def _circulating(entry: dict, peg_currency: str) -> float:
    return float((entry.get("circulating") or {}).get(f"pegged{peg_currency}", 0) or 0)


def run(client: bigquery.Client) -> dict:
    bqh.ensure_table(
        client,
        TABLE,
        SCHEMA,
        partition_field="snapshot_date",
        cluster_fields=["asset_symbol"],
        description="Daily raw JSON snapshots from the DefiLlama stablecoins API.",
    )
    session = requests.Session()
    listing = session.get(f"{BASE_URL}/stablecoins", params={"includePrices": "true"}, timeout=60)
    listing.raise_for_status()
    matches = match_assets(listing.json().get("peggedAssets", []), load_assets())

    now = datetime.now(timezone.utc)
    rows = []
    for symbol, entry in matches.items():
        detail = None
        if entry is not None:
            resp = session.get(f"{BASE_URL}/stablecoin/{entry['id']}", timeout=120)
            resp.raise_for_status()
            detail = resp.text
        else:
            log.warning("DefiLlama does not list %s", symbol)
        rows.append(
            {
                "snapshot_date": now.date().isoformat(),
                "asset_symbol": symbol,
                "llama_id": None if entry is None else str(entry["id"]),
                "list_entry": None if entry is None else json.dumps(entry),
                "detail": detail,
                "_loaded_at": now.isoformat(),
            }
        )
    merged = bqh.merge_rows(
        client,
        table_id(TABLE),
        rows,
        SCHEMA,
        key=["snapshot_date", "asset_symbol"],
        update_existing=True,
        source="defillama",
    )
    summary = {"listed": sorted(s for s, e in matches.items() if e), "missing": sorted(s for s, e in matches.items() if not e)}
    log.info("defillama: %s (%s rows merged)", summary, merged)
    return summary
