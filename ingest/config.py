"""Shared settings, read from the environment so CI and laptops run the same code."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEEDS_DIR = REPO_ROOT / "transform" / "seeds"

PROJECT = os.environ.get("GCP_PROJECT", "crypto-504119")
RAW_DATASET = os.environ.get("RAW_DATASET", "raw")
LOCATION = "US"  # must match bigquery-public-data

# Labels make this project's spend easy to find in INFORMATION_SCHEMA.JOBS.
JOB_LABELS = {"project": "stablecoin-monitor"}


@dataclass(frozen=True)
class Contract:
    chain: str
    address: str
    asset_symbol: str
    decimals: int
    role: str
    counts_toward_supply: bool


@dataclass(frozen=True)
class Asset:
    symbol: str
    peg_currency: str
    cohort: str


def _read_csv(name: str) -> list[dict[str, str]]:
    with open(SEEDS_DIR / name, newline="") as f:
        return list(csv.DictReader(f))


def load_contracts(chain: str | None = None) -> list[Contract]:
    """Read the contract registry seed. The CSV is the single source of truth."""
    contracts = [
        Contract(
            chain=row["chain"],
            address=row["contract_address"].lower(),
            asset_symbol=row["asset_symbol"],
            decimals=int(row["decimals"]),
            role=row["contract_role"],
            counts_toward_supply=row["counts_toward_supply"] == "true",
        )
        for row in _read_csv("token_contracts.csv")
    ]
    return [c for c in contracts if chain is None or c.chain == chain]


def load_assets() -> list[Asset]:
    return [
        Asset(symbol=row["asset_symbol"], peg_currency=row["peg_currency"], cohort=row["cohort"])
        for row in _read_csv("assets.csv")
    ]


def table_id(name: str) -> str:
    return f"{PROJECT}.{RAW_DATASET}.{name}"
