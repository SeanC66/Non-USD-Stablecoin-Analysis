"""Base chain transfers from the Coinbase CDP SQL API (issue #10).

Why CDP and not RPC: free RPC plans cap eth_getLogs at a few blocks per call,
so a Base backfill would take about a million requests. CDP's SQL API serves
indexed, decoded Base events (`base.events`) for free, up to 50,000 rows per
query, which turns the backfill into a few dozen queries.

Paging: results are read in (block_number, log_index) order with a keyset
cursor and LIMIT, never OFFSET. That order is unique on a chain, so each page
starts strictly after the last row of the previous one.

Budget: CDP's free tier allows roughly 1,000 queries a month. Every HTTP
attempt, retries included, counts toward a per-run cap (max_queries), and the
run logs how many it used.

Safety: only events older than FINALITY_MARGIN are read, so a reorged-out log
from the unsafe head can't land in the table. ERC-721 transfers share the
Transfer(address,address,uint256) signature but carry a fourth topic, so rows
must have exactly three topics.

On-chain decimals are still checked over plain JSON-RPC (one eth_call per
contract), which any free endpoint serves.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import requests
from google.cloud import bigquery

from ingest import bq as bqh
from ingest import retry
from ingest.config import Contract, load_contracts, table_id

log = logging.getLogger(__name__)

CDP_HOST = "api.cdp.coinbase.com"
CDP_PATH = "/platform/v2/data/query/run"
CDP_URL = f"https://{CDP_HOST}{CDP_PATH}"
PAGE_SIZE = 50_000  # CDP's per-query row limit
MIN_QUERY_INTERVAL = 0.6  # seconds between queries; CDP allows about 2 per second
DEFAULT_MAX_QUERIES = int(os.environ.get("CDP_MAX_QUERIES_PER_RUN", "100"))
FINALITY_MARGIN = timedelta(hours=1)
BLOCK_TIME_SECONDS = 2  # Base produces a block every 2 seconds
DEFAULT_LOOKBACK_HOURS = 24

DEFAULT_RPC_URL = "https://mainnet.base.org"
DECIMALS_SELECTOR = "0x313ce567"  # decimals()
TRANSFER_SIGNATURE = "Transfer(address,address,uint256)"
TABLE = "base_token_transfers"
INSERT_BATCH = 200_000  # rows per BigQuery load + insert; progress is committed at each one

# Assets in seeds/token_contracts.csv that this loader deliberately skips on Base.
# EURC on Base has ~31M transfers since 2024-06, about 630 CDP queries to
# backfill: most of a month's free quota. Loading only recent history would make
# the activity marts show a misleading partial series, so EURC stays out of Base
# transfers entirely until there's budget for a full backfill. Its Base supply is
# still covered by DefiLlama. Remove it from this mapping to load it.
EXCLUDED_ASSETS = {"EURC": "~31M transfers; full backfill needs ~630 CDP queries (issue #10)"}

SCHEMA = [
    bigquery.SchemaField("token_address", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("from_address", "STRING"),
    bigquery.SchemaField("to_address", "STRING"),
    bigquery.SchemaField("value", "STRING", description="Raw integer amount; scale by contract decimals"),
    bigquery.SchemaField("transaction_hash", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("log_index", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("block_number", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("block_timestamp", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP"),
]


class CdpError(Exception):
    pass


class QueryBudgetExceeded(CdpError):
    pass


class CdpClient:
    """Runs read-only SQL against CDP, signing a fresh JWT for every request.

    Credentials come from CDP_API_KEY_ID and CDP_API_KEY_SECRET. They and the
    JWTs are never logged.
    """

    def __init__(
        self,
        api_key_id: str | None = None,
        api_key_secret: str | None = None,
        session: requests.Session | None = None,
        max_queries: int = DEFAULT_MAX_QUERIES,
        sleep_fn=time.sleep,
        min_interval: float = MIN_QUERY_INTERVAL,
        backoff_factor: float = retry.DEFAULT_BACKOFF_FACTOR,
    ):
        self.api_key_id = api_key_id if api_key_id is not None else os.environ.get("CDP_API_KEY_ID", "")
        self.api_key_secret = (
            api_key_secret if api_key_secret is not None else os.environ.get("CDP_API_KEY_SECRET", "")
        )
        self.session = session or requests.Session()
        self.max_queries = max_queries
        self.queries = 0  # every HTTP attempt, retries included
        self.sleep_fn = sleep_fn
        self.min_interval = min_interval
        self.backoff_factor = backoff_factor
        self._last_sent: float | None = None

    def _headers(self) -> dict:
        if not self.api_key_id or not self.api_key_secret:
            raise CdpError("CDP_API_KEY_ID and CDP_API_KEY_SECRET must be set")
        from cdp.auth.utils.jwt import JwtOptions, generate_jwt

        token = generate_jwt(
            JwtOptions(
                api_key_id=self.api_key_id,
                api_key_secret=self.api_key_secret,
                request_method="POST",
                request_host=CDP_HOST,
                request_path=CDP_PATH,
                expires_in=120,
            )
        )
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # retry.post calls this once per attempt, so the cap covers retries too.
    def post(self, url, json=None, headers=None, timeout=60):
        if self.queries >= self.max_queries:
            raise QueryBudgetExceeded(
                f"CDP query cap of {self.max_queries} per run reached; rerun to continue from the watermark"
            )
        if self._last_sent is not None:
            wait = self.min_interval - (time.monotonic() - self._last_sent)
            if wait > 0:
                self.sleep_fn(wait)
        self.queries += 1
        self._last_sent = time.monotonic()
        return self.session.post(url, json=json, headers=headers, timeout=timeout)

    def query(self, sql: str) -> list[dict]:
        resp = retry.post(
            CDP_URL,
            json={"sql": sql},
            headers=self._headers,
            timeout=60,
            session=self,
            sleep_fn=self.sleep_fn,
            backoff_factor=self.backoff_factor,
        )
        if resp.status_code != 200:
            # The body carries CDP's error message (bad SQL, auth); never the key.
            raise CdpError(f"CDP query failed with HTTP {resp.status_code}: {resp.text[:500]}")
        body = resp.json()
        if "result" not in body:
            raise CdpError(f"CDP response has no result: {str(body)[:500]}")
        return body["result"]


def _sql_address_list(addresses: list[str]) -> str:
    for a in addresses:
        # Addresses come from our own seed, but they go into SQL text, so check them.
        if not (a.startswith("0x") and len(a) == 42 and all(c in "0123456789abcdef" for c in a[2:])):
            raise ValueError(f"not a lower-case hex address: {a!r}")
    return ", ".join(f"'{a}'" for a in addresses)


def build_query(
    addresses: list[str],
    start_block: int,
    cutoff: datetime,
    after: tuple[int, int] | None = None,
    limit: int = PAGE_SIZE,
) -> str:
    """One page of Transfer events for `addresses`, from `start_block` onward,
    older than `cutoff`, strictly after the (block_number, log_index) cursor."""
    keyset = ""
    if after is not None:
        block, index = after
        keyset = f"\n  AND (block_number > {int(block)} OR (block_number = {int(block)} AND log_index > {int(index)}))"
    return f"""SELECT
  address AS token_address,
  lower(toString(parameters['from'])) AS from_address,
  lower(toString(parameters['to'])) AS to_address,
  toString(parameters['value']) AS value,
  lower(transaction_hash) AS transaction_hash,
  log_index,
  block_number,
  block_timestamp
FROM base.events
WHERE address IN ({_sql_address_list(addresses)})
  AND event_signature = '{TRANSFER_SIGNATURE}'
  AND action = 'added'
  AND length(topics) = 3
  AND block_number >= {int(start_block)}
  AND block_timestamp < toDateTime64('{cutoff.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}', 3, 'UTC'){keyset}
ORDER BY block_number, log_index
LIMIT {int(limit)}"""


def parse_row(row: dict) -> dict:
    """Turn a CDP result row into our raw table's shape. CDP returns UInt64
    block numbers as strings; values stay strings because 18-decimal amounts
    overflow INT64."""
    value = str(row["value"])
    if not value.isdigit():
        raise CdpError(f"unexpected Transfer value {value!r} in {row.get('transaction_hash')}")
    ts = datetime.fromisoformat(str(row["block_timestamp"]).replace("Z", "+00:00").replace(" ", "T"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return {
        "token_address": str(row["token_address"]).lower(),
        "from_address": str(row["from_address"]).lower(),
        "to_address": str(row["to_address"]).lower(),
        "value": value,
        "transaction_hash": str(row["transaction_hash"]).lower(),
        "log_index": int(row["log_index"]),
        "block_number": int(row["block_number"]),
        "block_timestamp": ts.astimezone(timezone.utc).isoformat(),
    }


def fetch_transfers(
    cdp: CdpClient,
    addresses: list[str],
    start_block: int,
    cutoff: datetime,
    page_size: int = PAGE_SIZE,
) -> Iterator[list[dict]]:
    """Yield pages of parsed transfers in (block_number, log_index) order."""
    after = None
    while True:
        rows = [parse_row(r) for r in cdp.query(build_query(addresses, start_block, cutoff, after, page_size))]
        if rows:
            yield rows
        if len(rows) < page_size:
            return
        after = (rows[-1]["block_number"], rows[-1]["log_index"])


class Rpc:
    """Minimal JSON-RPC client, used only for the decimals check."""

    def __init__(self, url: str, session: requests.Session | None = None):
        self.url = url
        self.session = session
        self._id = 0

    def call(self, method: str, params: list):
        self._id += 1
        resp = retry.post(
            self.url,
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
            timeout=60,
            session=self.session,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC {method} failed: {body['error']}")
        return body["result"]


def onchain_decimals(rpc: Rpc, address: str) -> int:
    return int(rpc.call("eth_call", [{"to": address, "data": DECIMALS_SELECTOR}, "latest"]), 16)


def contracts_to_load() -> list[Contract]:
    contracts = []
    for c in load_contracts(chain="base"):
        if c.asset_symbol in EXCLUDED_ASSETS:
            log.info("skipping %s on Base: %s", c.asset_symbol, EXCLUDED_ASSETS[c.asset_symbol])
            continue
        contracts.append(c)
    return contracts


def plan_scans(
    addresses: list[str], watermarks: dict[str, int], lookback_hours: int
) -> list[tuple[int, list[str]]]:
    """Group contracts into at most two scans: (start_block, addresses).

    Contracts without rows are backfilled from block 0, which CDP answers from
    each contract's first transfer. Contracts with rows share one incremental
    scan from the oldest watermark minus the lookback window; rows already
    loaded are skipped on insert.
    """
    lookback_blocks = lookback_hours * 3600 // BLOCK_TIME_SECONDS
    new = sorted(a for a in addresses if a not in watermarks)
    known = sorted(a for a in addresses if a in watermarks)
    scans = []
    if new:
        scans.append((0, new))
    if known:
        scans.append((max(0, min(watermarks[a] for a in known) - lookback_blocks), known))
    return scans


def _watermarks(client: bigquery.Client) -> dict[str, int]:
    sql = f"SELECT token_address, MAX(block_number) AS last_block FROM `{table_id(TABLE)}` GROUP BY 1"
    return {row.token_address: row.last_block for row in bqh.run_query(client, sql, source="base").result()}


def load_pages(client, pages: Iterator[list[dict]], insert_batch: int = INSERT_BATCH) -> dict[str, int]:
    """Insert pages in batches, committing progress as it goes so an
    interrupted backfill resumes from the watermark. Returns rows fetched per
    token and the total inserted."""
    fetched: dict[str, int] = {}
    inserted = 0
    pending: list[dict] = []

    def flush():
        nonlocal inserted, pending
        if not pending:
            return
        now = datetime.now(timezone.utc).isoformat()
        for r in pending:
            r["_loaded_at"] = now
        inserted += bqh.insert_new_rows(
            client,
            table_id(TABLE),
            pending,
            SCHEMA,
            key=["transaction_hash", "log_index"],
            partition_field="block_timestamp",
            source="base",
        )
        pending = []

    try:
        for page in pages:
            for r in page:
                fetched[r["token_address"]] = fetched.get(r["token_address"], 0) + 1
            pending.extend(page)
            if len(pending) >= insert_batch:
                flush()
    except CdpError:
        # Pages arrive in block order, so everything fetched before a failure
        # (such as hitting the query cap) is a complete prefix: keep it rather
        # than spend the queries again on the next run.
        flush()
        raise
    flush()
    return {"fetched": fetched, "inserted": inserted}


def run(
    client: bigquery.Client,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_queries: int = DEFAULT_MAX_QUERIES,
    cdp: CdpClient | None = None,
    rpc_url: str | None = None,
) -> dict:
    cdp = cdp or CdpClient(max_queries=max_queries)
    rpc = Rpc(rpc_url or os.environ.get("BASE_RPC_URL") or DEFAULT_RPC_URL)
    bqh.ensure_table(
        client,
        TABLE,
        SCHEMA,
        partition_field="block_timestamp",
        cluster_fields=["token_address"],
        description="ERC-20 Transfer events for tracked contracts on Base, from the Coinbase CDP SQL API.",
    )
    contracts = contracts_to_load()
    for contract in contracts:
        actual = onchain_decimals(rpc, contract.address)
        if actual != contract.decimals:
            raise ValueError(
                f"{contract.asset_symbol} on Base reports {actual} decimals; seed says {contract.decimals}. Fix the seed."
            )
    symbols = {c.address: c.asset_symbol for c in contracts}
    cutoff = datetime.now(timezone.utc) - FINALITY_MARGIN
    watermarks = _watermarks(client)
    summary: dict = {"cutoff": cutoff.isoformat(), "fetched": {}, "inserted": 0}
    try:
        for start_block, addresses in plan_scans(list(symbols), watermarks, lookback_hours):
            log.info(
                "base: scanning %s from block %s", ", ".join(symbols[a] for a in addresses), start_block
            )
            result = load_pages(client, fetch_transfers(cdp, addresses, start_block, cutoff))
            for address, n in result["fetched"].items():
                summary["fetched"][symbols.get(address, address)] = n
            summary["inserted"] += result["inserted"]
    finally:
        summary["cdp_queries"] = cdp.queries
        log.info("base: %s (CDP queries used this run: %s of %s)", summary, cdp.queries, cdp.max_queries)
    return summary
