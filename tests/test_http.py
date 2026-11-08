from __future__ import annotations

import requests
import pytest

from ingest import http


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Error", response=self)


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, params: dict | None = None, timeout: float = 60):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if not self.responses:
            raise RuntimeError("No more responses queued in FakeSession")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_retries_on_522_and_then_succeeds():
    delays: list[float] = []
    session = FakeSession([FakeResponse(522), FakeResponse(200, "OK")])

    resp = http.get(
        "https://api.example.com/data",
        session=session,
        sleep_fn=delays.append,
        backoff_factor=1.0,
    )

    assert resp.status_code == 200
    assert resp.text == "OK"
    assert len(session.calls) == 2
    assert len(delays) == 1
    assert delays[0] >= 1.0  # initial exponential backoff


def test_gives_up_after_n_attempts():
    delays: list[float] = []
    session = FakeSession([FakeResponse(522), FakeResponse(522), FakeResponse(522)])

    resp = http.get(
        "https://api.example.com/data",
        session=session,
        max_attempts=3,
        sleep_fn=delays.append,
    )

    assert resp.status_code == 522
    assert len(session.calls) == 3
    assert len(delays) == 2
    with pytest.raises(requests.exceptions.HTTPError):
        resp.raise_for_status()


def test_does_not_retry_404():
    delays: list[float] = []
    session = FakeSession([FakeResponse(404)])

    resp = http.get(
        "https://api.example.com/missing",
        session=session,
        sleep_fn=delays.append,
    )

    assert resp.status_code == 404
    assert len(session.calls) == 1
    assert len(delays) == 0
    with pytest.raises(requests.exceptions.HTTPError):
        resp.raise_for_status()


def test_honours_retry_after_header():
    delays: list[float] = []
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "5"}), FakeResponse(200, "OK")])

    resp = http.get(
        "https://api.example.com/rate-limited",
        session=session,
        sleep_fn=delays.append,
    )

    assert resp.status_code == 200
    assert len(session.calls) == 2
    assert delays == [5.0]


def test_retries_on_connection_error_and_timeout():
    delays: list[float] = []
    session = FakeSession([
        requests.exceptions.ConnectionError("Connection reset"),
        requests.exceptions.Timeout("Read timeout"),
        FakeResponse(200, "Recovered"),
    ])

    resp = http.get(
        "https://api.example.com/flaky",
        session=session,
        sleep_fn=delays.append,
    )

    assert resp.status_code == 200
    assert resp.text == "Recovered"
    assert len(session.calls) == 3
    assert len(delays) == 2
