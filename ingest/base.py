"""Base chain transfers via standard Ethereum JSON-RPC (eth_getLogs).

Why RPC and not an explorer API: Base is not in the BigQuery public datasets,
and Etherscan dropped Base from its free API tier in late 2025. Any Base RPC
endpoint works; set BASE_RPC_URL to a provider key for higher limits.

Transfers are decoded from raw logs: an ERC-20 Transfer event has exactly
three topics (signature, from, to) and the amount in `data`. ERC-721
transfers share the signature but carry a fourth topic, so they are skipped.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone

import requests
from google.cloud import bigquery

from ingest import bq as bqh
from ingest.config import Contract, load_contracts, table_id

log = logging.getLogger(__name__)

DEFAULT_RPC_URL = "https://mainnet.base.org"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DECIMALS_SELECTOR = "0x313ce567"  # decimals()
TABLE = "base_token_transfers"
MERGE_BATCH = 20_000

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


class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, url: str, session: requests.Session | None = None, max_retries: int = 5):
        self.url = url
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self._id = 0

    def _post(self, payload):
        for attempt in range(self.max_retries):
            resp = self.session.post(self.url, json=payload, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = min(2**attempt, 30)
                log.warning("RPC HTTP %s, retrying in %ss", resp.status_code, wait)
                time.sleep(wait)
                continue
            if resp.status_code == 400:
                # Providers return JSON-RPC errors (such as block-range limits)
                # with HTTP 400. Hand the body back so call() raises an RpcError
                # carrying the provider's message instead of a bare "Bad Request".
                try:
                    body = resp.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and "error" in body:
                    return body
            resp.raise_for_status()
            return resp.json()
        raise RpcError(f"RPC failed after {self.max_retries} retries")

    def call(self, method: str, params: list):
        self._id += 1
        body = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if "error" in body:
            raise RpcError(body["error"].get("message", str(body["error"])))
        return body["result"]

    def batch(self, calls: list[tuple[str, list]]) -> list:
        payload = []
        for method, params in calls:
            self._id += 1
            payload.append({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        body = self._post(payload)
        if isinstance(body, dict):  # some providers reject batches with a single error object
            raise RpcError(body.get("error", {}).get("message", "batch request rejected"))
        by_id = {item["id"]: item for item in body}
        results = []
        for request in payload:
            item = by_id.get(request["id"])
            if item is None or "error" in item:
                raise RpcError(f"batch item {request['method']} failed: {item and item.get('error')}")
            results.append(item["result"])
        return results


def decode_transfer(raw_log: dict) -> dict | None:
    """Decode an ERC-20 Transfer log. Returns None for anything else."""
    topics = raw_log.get("topics", [])
    if raw_log.get("removed") or len(topics) != 3 or topics[0].lower() != TRANSFER_TOPIC:
        return None
    data = raw_log.get("data") or "0x"
    return {
        "token_address": raw_log["address"].lower(),
        "from_address": "0x" + topics[1][-40:].lower(),
        "to_address": "0x" + topics[2][-40:].lower(),
        "value": str(int(data, 16)) if data != "0x" else "0",
        "transaction_hash": raw_log["transactionHash"].lower(),
        "log_index": int(raw_log["logIndex"], 16),
        "block_number": int(raw_log["blockNumber"], 16),
    }


def _is_range_error(err: Exception) -> bool:
    text = str(err).lower()
    return any(s in text for s in ("range", "limit", "too many", "exceed", "timeout", "10000", "response size"))


def fetch_logs(
    rpc: Rpc,
    address: str,
    start: int,
    end: int,
    chunk: int = 2_000,
    min_chunk: int = 10,
    max_chunk: int = 10_000,
) -> Iterator[tuple[int, list[dict]]]:
    """Yield (chunk_end_block, logs) across [start, end], shrinking the block
    range when the provider refuses it and growing it again after successes."""
    cursor = start
    while cursor <= end:
        upper = min(cursor + chunk - 1, end)
        try:
            logs = rpc.call(
                "eth_getLogs",
                [{"address": address, "topics": [TRANSFER_TOPIC], "fromBlock": hex(cursor), "toBlock": hex(upper)}],
            )
        except RpcError as err:
            if _is_range_error(err) and chunk > min_chunk:
                chunk = max(chunk // 2, min_chunk)
                log.info("narrowing getLogs range to %s blocks (%s)", chunk, err)
                continue
            raise
        yield upper, logs
        cursor = upper + 1
        chunk = min(chunk * 2, max_chunk)


def block_timestamps(rpc: Rpc, blocks: set[int], batch_size: int = 50) -> dict[int, datetime]:
    out: dict[int, datetime] = {}
    ordered = sorted(blocks)
    for i in range(0, len(ordered), batch_size):
        group = ordered[i : i + batch_size]
        results = rpc.batch([("eth_getBlockByNumber", [hex(b), False]) for b in group])
        for number, block in zip(group, results):
            out[number] = datetime.fromtimestamp(int(block["timestamp"], 16), tz=timezone.utc)
    return out


def safe_head(rpc: Rpc) -> int:
    """Latest block considered safe from reorgs."""
    try:
        return int(rpc.call("eth_getBlockByNumber", ["safe", False])["number"], 16)
    except RpcError:
        return int(rpc.call("eth_blockNumber", []), 16) - 300  # ~10 minutes on Base


def onchain_decimals(rpc: Rpc, address: str) -> int:
    return int(rpc.call("eth_call", [{"to": address, "data": DECIMALS_SELECTOR}, "latest"]), 16)


def first_code_block(rpc: Rpc, address: str, head: int) -> int:
    """Binary-search the deployment block with eth_getCode. Needs an RPC
    endpoint that serves historical state; otherwise pass --base-from-block."""
    lo, hi = 0, head
    while lo < hi:
        mid = (lo + hi) // 2
        if rpc.call("eth_getCode", [address, hex(mid)]) not in ("0x", "0x0", None):
            hi = mid
        else:
            lo = mid + 1
    return lo


def _watermarks(client: bigquery.Client) -> dict[str, int]:
    sql = f"SELECT token_address, MAX(block_number) AS last_block FROM `{table_id(TABLE)}` GROUP BY 1"
    return {row.token_address: row.last_block for row in bqh.run_query(client, sql, source="base").result()}


def _load_contract(client, rpc: Rpc, contract: Contract, start: int, end: int) -> int:
    loaded, pending = 0, []

    def flush():
        nonlocal loaded, pending
        if not pending:
            return
        stamps = block_timestamps(rpc, {r["block_number"] for r in pending})
        now = datetime.now(timezone.utc).isoformat()
        for r in pending:
            r["block_timestamp"] = stamps[r["block_number"]].isoformat()
            r["_loaded_at"] = now
        loaded += bqh.merge_rows(
            client, table_id(TABLE), pending, SCHEMA, key=["transaction_hash", "log_index"], source="base"
        )
        pending = []

    for _, logs in fetch_logs(rpc, contract.address, start, end):
        pending.extend(t for t in (decode_transfer(lg) for lg in logs) if t)
        if len(pending) >= MERGE_BATCH:
            flush()  # persist progress so a long backfill can resume from the watermark
    flush()
    return loaded


def run(client: bigquery.Client, rpc_url: str | None = None, from_block: int | None = None) -> dict:
    rpc = Rpc(rpc_url or os.environ.get("BASE_RPC_URL") or DEFAULT_RPC_URL)
    bqh.ensure_table(
        client,
        TABLE,
        SCHEMA,
        partition_field="block_timestamp",
        cluster_fields=["token_address"],
        description="ERC-20 Transfer events for tracked contracts on Base, decoded from eth_getLogs.",
    )
    head = safe_head(rpc)
    watermarks = _watermarks(client)
    summary = {}
    for contract in load_contracts(chain="base"):
        actual = onchain_decimals(rpc, contract.address)
        if actual != contract.decimals:
            raise ValueError(
                f"{contract.asset_symbol} on Base reports {actual} decimals; seed says {contract.decimals}. Fix the seed."
            )
        if contract.address in watermarks:
            start = watermarks[contract.address] + 1
        else:
            start = from_block if from_block is not None else first_code_block(rpc, contract.address, head)
            log.info("backfilling %s on Base from block %s", contract.asset_symbol, start)
        summary[contract.asset_symbol] = _load_contract(client, rpc, contract, start, head) if start <= head else 0
    log.info("base: rows merged per asset %s (head block %s)", summary, head)
    return summary
