"""Ingestion jobs that land source data in the BigQuery `raw` dataset.

Each module owns one source and is safe to re-run: loads merge on a natural
key instead of appending blindly. dbt reads `raw` and never writes to it.
"""
