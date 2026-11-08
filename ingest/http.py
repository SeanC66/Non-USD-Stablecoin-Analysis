"""HTTP helpers with exponential backoff and retry for upstream data sources."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

import requests

log = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_FACTOR = 1.0


def get(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 60,
    session: requests.Session | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """Fetch a URL with retry and exponential backoff for transient errors.

    Retries on:
      - Connection errors and timeouts
      - HTTP 429 (Too Many Requests)
      - HTTP 5xx (Internal Server Error, Bad Gateway, Cloudflare 520-524, etc.)

    Does NOT retry client errors (4xx other than 429).
    Honours the Retry-After header when present.
    """
    requester = session if session is not None else requests

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requester.get(url, params=params, timeout=timeout)
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < max_attempts:
                delay = None
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except (ValueError, TypeError):
                        delay = None
                if delay is None:
                    delay = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 0.5)

                log.warning(
                    "HTTP %s from %s, retrying in %.2fs (attempt %d/%d)",
                    resp.status_code,
                    url,
                    delay,
                    attempt,
                    max_attempts,
                )
                sleep_fn(delay)
                continue
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt < max_attempts:
                delay = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log.warning(
                    "HTTP error %s from %s, retrying in %.2fs (attempt %d/%d)",
                    exc,
                    url,
                    delay,
                    attempt,
                    max_attempts,
                )
                sleep_fn(delay)
                continue
            raise
