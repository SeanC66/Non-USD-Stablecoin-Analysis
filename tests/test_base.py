from datetime import timezone

import pytest

from ingest.base import TRANSFER_TOPIC, RpcError, block_timestamps, decode_transfer, fetch_logs

FROM = "0x000000000000000000000000" + "ab" * 20
TO = "0x000000000000000000000000" + "cd" * 20


def make_log(**overrides):
    log = {
        "address": "0x16F93eBC5320C89EfC8701577efe49d14A276a06",
        "topics": [TRANSFER_TOPIC, FROM, TO],
        "data": hex(250 * 10**18),
        "transactionHash": "0xABC",
        "logIndex": "0x1f",
        "blockNumber": "0x10",
        "removed": False,
    }
    log.update(overrides)
    return log


def test_decodes_erc20_transfer_and_lowercases_addresses():
    row = decode_transfer(make_log())
    assert row == {
        "token_address": "0x16f93ebc5320c89efc8701577efe49d14a276a06",
        "from_address": "0x" + "ab" * 20,
        "to_address": "0x" + "cd" * 20,
        "value": str(250 * 10**18),
        "transaction_hash": "0xabc",
        "log_index": 31,
        "block_number": 16,
    }


def test_value_beyond_int64_is_kept_exact_as_string():
    row = decode_transfer(make_log(data=hex(2**200)))
    assert row["value"] == str(2**200)


def test_empty_data_is_zero():
    assert decode_transfer(make_log(data="0x"))["value"] == "0"


@pytest.mark.parametrize(
    "overrides",
    [
        {"topics": [TRANSFER_TOPIC, FROM, TO, "0x01"]},  # ERC-721 transfer
        {"topics": ["0x" + "00" * 32, FROM, TO]},  # different event
        {"removed": True},  # reorged-out log
    ],
)
def test_ignores_non_erc20_logs(overrides):
    assert decode_transfer(make_log(**overrides)) is None


class FakeRpc:
    """Refuses getLogs ranges wider than `limit` blocks, like many providers."""

    def __init__(self, limit=500):
        self.limit = limit
        self.ranges = []

    def call(self, method, params):
        assert method == "eth_getLogs"
        lo, hi = int(params[0]["fromBlock"], 16), int(params[0]["toBlock"], 16)
        if hi - lo + 1 > self.limit:
            raise RpcError("query exceeds max block range 500")
        self.ranges.append((lo, hi))
        return []

    def batch(self, calls):
        return [{"timestamp": hex(1_700_000_000 + int(params[0], 16) * 2)} for _, params in calls]


def test_fetch_logs_narrows_range_and_covers_every_block_once():
    rpc = FakeRpc(limit=500)
    list(fetch_logs(rpc, "0xabc", start=1_000, end=9_999, chunk=4_000))
    covered = [b for lo, hi in rpc.ranges for b in range(lo, hi + 1)]
    assert covered == list(range(1_000, 10_000))
    assert all(hi - lo + 1 <= 500 for lo, hi in rpc.ranges)


def test_fetch_logs_reraises_non_range_errors():
    class Broken(FakeRpc):
        def call(self, method, params):
            raise RpcError("execution reverted")

    with pytest.raises(RpcError):
        list(fetch_logs(Broken(), "0xabc", start=0, end=10))


def test_block_timestamps_batches_and_converts_to_utc():
    stamps = block_timestamps(FakeRpc(), {5, 1, 120}, batch_size=2)
    assert set(stamps) == {1, 5, 120}
    assert stamps[5].tzinfo == timezone.utc
    assert stamps[5].timestamp() == 1_700_000_010
