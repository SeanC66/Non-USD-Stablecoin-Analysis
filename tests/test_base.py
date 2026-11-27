import re
from datetime import datetime, timezone

import pytest

from ingest import base
from ingest.base import (
    CdpClient,
    CdpError,
    QueryBudgetExceeded,
    build_query,
    contracts_to_load,
    fetch_transfers,
    load_pages,
    parse_row,
    plan_scans,
)

CADD = "0x16f93ebc5320c89efc8701577efe49d14a276a06"
CUTOFF = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def cdp_row(block, index, value="1000000", token=CADD):
    """A row as CDP returns it: UInt64 block numbers come back as strings."""
    return {
        "token_address": token,
        "from_address": "0x" + "AB" * 20,
        "to_address": "0x" + "cd" * 20,
        "value": value,
        "transaction_hash": f"0x{block:064X}",
        "log_index": index,
        "block_number": str(block),
        "block_timestamp": "2026-02-26T15:04:05.000Z",
    }


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body


class FakeSession:
    """Answers CDP queries from a list of rows, honouring the keyset cursor and
    LIMIT in the SQL, like the real API. Optional `errors` are returned first."""

    def __init__(self, rows=(), errors=()):
        self.rows = sorted(rows, key=lambda r: (int(r["block_number"]), r["log_index"]))
        self.errors = list(errors)
        self.sqls = []
        self.headers = []

    def post(self, url, json, headers, timeout):
        assert url == base.CDP_URL
        self.sqls.append(json["sql"])
        self.headers.append(headers)
        if self.errors:
            return self.errors.pop(0)
        sql = json["sql"]
        limit = int(re.search(r"LIMIT (\d+)", sql).group(1))
        rows = self.rows
        m = re.search(r"block_number > (\d+) OR \(block_number = \d+ AND log_index > (\d+)\)", sql)
        if m:
            after = (int(m.group(1)), int(m.group(2)))
            rows = [r for r in rows if (int(r["block_number"]), r["log_index"]) > after]
        return FakeResponse(200, {"result": rows[:limit], "metadata": {"rowCount": len(rows[:limit])}})


def make_cdp(session, **kwargs):
    cdp = CdpClient("key-id", "key-secret", session=session, sleep_fn=lambda s: None, min_interval=0, **kwargs)
    cdp._headers = lambda: {"Authorization": "Bearer test"}  # no real signing in tests
    return cdp


def test_keyset_pagination_covers_every_row_once_across_pages():
    # Several logs share a block, and a page boundary falls inside block 2.
    rows = [cdp_row(b, i) for b in range(1, 6) for i in range(3)]
    session = FakeSession(rows)
    pages = list(fetch_transfers(make_cdp(session), [CADD], 0, CUTOFF, page_size=4))

    got = [(r["block_number"], r["log_index"]) for page in pages for r in page]
    assert got == [(b, i) for b in range(1, 6) for i in range(3)]
    assert [len(p) for p in pages] == [4, 4, 4, 3]
    assert len(session.sqls) == 4
    assert "block_number > 2 OR (block_number = 2 AND log_index > 0)" in session.sqls[1]
    assert "block_number > 3 OR (block_number = 3 AND log_index > 1)" in session.sqls[2]
    assert all("OFFSET" not in sql for sql in session.sqls)


def test_full_last_page_costs_one_extra_empty_query():
    session = FakeSession([cdp_row(b, 0) for b in range(4)])
    pages = list(fetch_transfers(make_cdp(session), [CADD], 0, CUTOFF, page_size=2))
    assert [len(p) for p in pages] == [2, 2]
    assert len(session.sqls) == 3


def test_query_filters_erc20_transfers_and_respects_cutoff():
    sql = build_query([CADD], 123, CUTOFF)
    assert f"address IN ('{CADD}')" in sql
    assert "event_signature = 'Transfer(address,address,uint256)'" in sql
    assert "action = 'added'" in sql
    assert "length(topics) = 3" in sql  # ERC-721 transfers carry a fourth topic
    assert "block_number >= 123" in sql
    assert "block_timestamp < toDateTime64('2026-11-22 12:00:00', 3, 'UTC')" in sql
    assert sql.rstrip().endswith("ORDER BY block_number, log_index\nLIMIT 50000")


def test_query_rejects_anything_but_lowercase_hex_addresses():
    with pytest.raises(ValueError):
        build_query(["0xabc'); DROP TABLE x; --"], 0, CUTOFF)
    with pytest.raises(ValueError):
        build_query([CADD.upper().replace("0X", "0x")], 0, CUTOFF)


def test_parse_row_types_and_lowercases():
    row = parse_row(cdp_row(42, 7, value=str(2**200)))
    assert row == {
        "token_address": CADD,
        "from_address": "0x" + "ab" * 20,
        "to_address": "0x" + "cd" * 20,
        "value": str(2**200),  # beyond INT64, kept exact as a string
        "transaction_hash": f"0x{42:064x}",
        "log_index": 7,
        "block_number": 42,
        "block_timestamp": "2026-02-26T15:04:05+00:00",
    }


def test_parse_row_accepts_space_separated_timestamp_and_zero_value():
    raw = cdp_row(1, 0, value="0") | {"block_timestamp": "2026-02-26 15:04:05.000"}
    row = parse_row(raw)
    assert row["value"] == "0"
    assert row["block_timestamp"] == "2026-02-26T15:04:05+00:00"


@pytest.mark.parametrize("value", ["", "-5", "1e18", "None"])
def test_parse_row_rejects_non_integer_values(value):
    with pytest.raises(CdpError):
        parse_row(cdp_row(1, 0, value=value))


def test_query_cap_stops_paging_and_counts_queries():
    session = FakeSession([cdp_row(b, 0) for b in range(10)])
    cdp = make_cdp(session, max_queries=3)
    pages = []
    with pytest.raises(QueryBudgetExceeded):
        for page in fetch_transfers(cdp, [CADD], 0, CUTOFF, page_size=2):
            pages.append(page)
    assert cdp.queries == 3
    assert len(session.sqls) == 3
    assert len(pages) == 3


def test_retries_on_429_and_counts_the_retry():
    session = FakeSession(
        [cdp_row(1, 0)],
        errors=[FakeResponse(429, {"error": "rate limited"}, headers={"Retry-After": "1"})],
    )
    cdp = make_cdp(session)
    pages = list(fetch_transfers(cdp, [CADD], 0, CUTOFF))
    assert [len(p) for p in pages] == [1]
    assert cdp.queries == 2  # the rejected attempt still spends a query
    assert len(session.headers) == 2  # a header set (fresh JWT) per attempt


def test_retry_attempts_also_respect_the_cap():
    session = FakeSession(errors=[FakeResponse(503, {})] * 5)
    cdp = make_cdp(session, max_queries=2, backoff_factor=0)
    with pytest.raises(QueryBudgetExceeded):
        cdp.query("SELECT 1")
    assert cdp.queries == 2


def test_non_retryable_error_raises_with_cdp_message():
    session = FakeSession(errors=[FakeResponse(400, {"errorMessage": "syntax error"})])
    cdp = make_cdp(session)
    with pytest.raises(CdpError, match="HTTP 400.*syntax error"):
        cdp.query("SELEC 1")
    assert cdp.queries == 1


def test_missing_credentials_fail_before_any_request():
    session = FakeSession()
    cdp = CdpClient("", "", session=session, sleep_fn=lambda s: None)
    with pytest.raises(CdpError, match="must be set"):
        cdp.query("SELECT 1")
    assert session.sqls == []


def test_eurc_is_excluded_from_base_loads():
    seeded = {c.asset_symbol for c in base.load_contracts(chain="base")}
    loaded = {c.asset_symbol for c in contracts_to_load()}
    assert "EURC" in seeded
    assert "EURC" not in loaded
    assert loaded == seeded - set(base.EXCLUDED_ASSETS)
    assert {"CADD", "CADC", "XSGD", "AUDD"} <= loaded


def test_plan_scans_backfills_new_contracts_and_increments_known_ones():
    scans = plan_scans(["0xb", "0xa", "0xc"], {"0xa": 100_000, "0xc": 90_000}, lookback_hours=1)
    assert scans == [(0, ["0xb"]), (90_000 - 1_800, ["0xa", "0xc"])]
    assert plan_scans(["0xa"], {}, 24) == [(0, ["0xa"])]
    assert plan_scans(["0xa"], {"0xa": 10}, 24) == [(0, ["0xa"])]  # never below block 0


def test_load_pages_flushes_fetched_rows_when_the_cap_is_hit(monkeypatch):
    inserted = []
    monkeypatch.setattr(base.bqh, "insert_new_rows", lambda client, target, rows, *a, **k: inserted.append(rows) or len(rows))

    def pages():
        yield [parse_row(cdp_row(1, 0)), parse_row(cdp_row(2, 0))]
        raise QueryBudgetExceeded("cap")

    with pytest.raises(QueryBudgetExceeded):
        load_pages(None, pages(), insert_batch=1_000)
    assert [len(batch) for batch in inserted] == [2]
    assert all("_loaded_at" in r for r in inserted[0])
