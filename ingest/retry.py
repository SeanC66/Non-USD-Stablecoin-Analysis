"""HTTP helpers with exponential backoff and retry for upstream data sources."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

import requests

log = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_FACTOR = 5.0
# Upper bound on a server-supplied Retry-After, so a bad value cannot stall the job.
MAX_RETRY_AFTER = 60.0


def _is_retryable(status_code: int) -> bool:
    # 408 Request Timeout and 429 Too Many Requests are transient client-side
    # codes; every 5xx (including Cloudflare's 520-524) is treated as transient.
    return status_code in (408, 429) or status_code >= 500


def _request(
    send: Callable[[], requests.Response],
    url: str,
    *,
    max_attempts: int,
    backoff_factor: float,
    sleep_fn: Callable[[float], None],
) -> requests.Response:
    for attempt in range(1, max_attempts + 1):
        try:
            resp = send()
            if _is_retryable(resp.status_code) and attempt < max_attempts:
                delay = None
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(0.0, min(float(retry_after), MAX_RETRY_AFTER))
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
    raise AssertionError("unreachable")  # the last attempt always returns or raises


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
      - HTTP 408 (Request Timeout) and 429 (Too Many Requests)
      - HTTP 5xx (Internal Server Error, Bad Gateway, Cloudflare 520-524, etc.)

    Does NOT retry other client errors (4xx).
    Honours the Retry-After header when present, clamped to [0, MAX_RETRY_AFTER].
    """
    requester = session if session is not None else requests
    return _request(
        lambda: requester.get(url, params=params, timeout=timeout),
        url,
        max_attempts=max_attempts,
        backoff_factor=backoff_factor,
        sleep_fn=sleep_fn,
    )


def post(
    url: str,
    *,
    json: dict | list | None = None,
    headers: dict | Callable[[], dict] | None = None,
    timeout: float = 60,
    session: requests.Session | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """POST with the same retry rules as get().

    `headers` may be a callable, called before every attempt, for APIs that
    need a freshly signed token per request.
    """
    requester = session if session is not None else requests

    def send() -> requests.Response:
        hdrs = headers() if callable(headers) else headers
        return requester.post(url, json=json, headers=hdrs, timeout=timeout)

    return _request(send, url, max_attempts=max_attempts, backoff_factor=backoff_factor, sleep_fn=sleep_fn)
