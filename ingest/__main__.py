"""Run ingestion jobs: python -m ingest <source> [<source> ...]"""

from __future__ import annotations

import argparse
import logging
import sys

from ingest import bq as bqh

SOURCES = ["ethereum"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest")
    parser.add_argument("sources", nargs="+", choices=SOURCES + ["all"])
    parser.add_argument("--lookback-hours", type=int, default=24, help="Ethereum overlap window")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sources = SOURCES if "all" in args.sources else args.sources
    client = bqh.client()

    failed = []
    for source in sources:
        try:
            if source == "ethereum":
                from ingest import ethereum

                ethereum.run(client, lookback_hours=args.lookback_hours)
        except Exception:  # keep going so one broken source doesn't block the others
            logging.exception("%s failed", source)
            failed.append(source)

    if failed:
        logging.error("failed sources: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
