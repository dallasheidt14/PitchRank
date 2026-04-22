"""Unit tests for `src.etl.bulk_ops`."""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from postgrest.exceptions import APIError

from src.etl.bulk_ops import (
    BULK_UPDATE_CHUNK_SIZE,
    BULK_UPDATE_MIN_CHUNK,
    RPC_RESULT_LIMIT,
    bulk_update_last_scraped_at,
    call_rpc_with_fallback,
)


def _api_error(*, code=None, message="boom") -> APIError:
    """Construct an APIError the same way postgrest-py does internally."""
    return APIError({"code": code, "message": message, "hint": None, "details": None})


class StubRpc:
    def __init__(self, supabase, fn_name, params):
        self.supabase = supabase
        self.fn_name = fn_name
        self.params = params
        self.limit_arg: Optional[int] = None

    def limit(self, n: int) -> "StubRpc":
        self.limit_arg = n
        return self

    def execute(self):
        self.supabase.calls.append((self.fn_name, self.params, self.limit_arg))
        reaction = self.supabase._next_reaction()
        if callable(reaction):
            return reaction(self.params)
        return reaction


class StubSupabase:
    """Scriptable stub for `supabase.rpc(fn, params).execute()`."""

    def __init__(self, reactions: Optional[List[Any]] = None):
        self.calls: List[tuple] = []
        # Each reaction is either:
        #   * a SimpleNamespace/dict returned from execute()
        #   * an Exception instance (raised when consumed)
        #   * a callable(params) -> SimpleNamespace
        self._reactions: List[Any] = list(reactions or [])

    def _next_reaction(self):
        if not self._reactions:
            return SimpleNamespace(data=None)
        reaction = self._reactions.pop(0)
        if isinstance(reaction, Exception):
            raise reaction
        return reaction

    def rpc(self, fn_name: str, params: Dict[str, Any]):
        return StubRpc(self, fn_name, params)


# ---------- bulk_update_last_scraped_at ----------


def test_empty_payload_short_circuits_without_calling_supabase():
    sb = StubSupabase()
    assert bulk_update_last_scraped_at(sb, []) == 0
    assert sb.calls == []


def test_single_chunk_happy_path_returns_rpc_rowcount():
    sb = StubSupabase([SimpleNamespace(data=10)])
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(10)]
    assert bulk_update_last_scraped_at(sb, payload) == 10
    assert len(sb.calls) == 1
    assert sb.calls[0][0] == "bulk_update_last_scraped_at"
    assert len(sb.calls[0][1]["updates"]) == 10


def test_multiple_chunks_sum_returned_counts():
    # chunk_size=10 → 2 calls of 10 and 5
    sb = StubSupabase([SimpleNamespace(data=10), SimpleNamespace(data=5)])
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(15)]
    total = bulk_update_last_scraped_at(sb, payload, chunk_size=10)
    assert total == 15
    assert [len(call[1]["updates"]) for call in sb.calls] == [10, 5]


def test_partial_rowcount_warns_but_still_accumulates(caplog):
    sb = StubSupabase([SimpleNamespace(data=8)])  # RPC says 8 of 10 rows matched
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(10)]
    import logging

    caplog.set_level(logging.WARNING, logger="src.etl.bulk_ops")
    assert bulk_update_last_scraped_at(sb, payload) == 8
    assert any("8 of 10 rows updated" in rec.message for rec in caplog.records)


def test_42883_without_fallback_reraises():
    sb = StubSupabase([_api_error(code="42883")])
    payload = [{"team_id_master": "t0", "last_scraped_at": "2026-04-22T00:00:00"}]
    with pytest.raises(APIError) as excinfo:
        bulk_update_last_scraped_at(sb, payload)
    assert getattr(excinfo.value, "code", None) == "42883"


def test_42883_with_fallback_invokes_fallback_and_returns_its_count():
    sb = StubSupabase([_api_error(code="42883")])
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(3)]
    fallback_invocations = []

    def fallback():
        fallback_invocations.append(True)
        return 42

    total = bulk_update_last_scraped_at(sb, payload, on_missing_function=fallback)
    assert total == 42
    assert len(fallback_invocations) == 1
    # Only one RPC attempt — the helper gives up immediately on 42883 because
    # all subsequent chunks would also fail.
    assert len(sb.calls) == 1


def test_413_halves_chunk_and_retries():
    # First call (size=200) raises 413. `max(200 // 2, 125) = 125`, so the
    # retry chunk is 125, then size resets to chunk_size=200 on success, so
    # the remaining 75 rows ship as one final chunk.
    sb = StubSupabase(
        [
            _api_error(code=413, message="payload too large 413"),
            SimpleNamespace(data=125),
            SimpleNamespace(data=75),
        ]
    )
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(200)]
    total = bulk_update_last_scraped_at(sb, payload, chunk_size=200)
    assert total == 200
    assert [len(c[1]["updates"]) for c in sb.calls] == [200, 125, 75]


def test_413_halving_floors_at_min_chunk():
    assert BULK_UPDATE_MIN_CHUNK == 125
    # A non-halvable 413 on a sub-floor chunk must not loop forever.
    # Size starts at 125, a 413 at that size bypasses halving (size > floor check).
    sb = StubSupabase([_api_error(code=413, message="413 still too big")])
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(125)]
    # Even with a 413, the helper advances past the chunk (it does not infinite-loop)
    # because size > BULK_UPDATE_MIN_CHUNK is False at floor.
    total = bulk_update_last_scraped_at(sb, payload, chunk_size=125)
    # The chunk is skipped with a warning; returned count is 0.
    assert total == 0
    assert len(sb.calls) == 1


def test_non_413_api_error_skips_chunk_and_continues():
    sb = StubSupabase(
        [
            _api_error(code="23505", message="unique violation"),  # chunk 1 fails
            SimpleNamespace(data=5),  # chunk 2 succeeds
        ]
    )
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(10)]
    total = bulk_update_last_scraped_at(sb, payload, chunk_size=5)
    assert total == 5
    assert len(sb.calls) == 2


def test_non_int_response_data_falls_back_to_chunk_length():
    # PostgREST REST may return `null` or a list for some shapes; the helper
    # treats non-int responses as "count == chunk length".
    sb = StubSupabase([SimpleNamespace(data=None)])
    payload = [{"team_id_master": f"t{i}", "last_scraped_at": "2026-04-22T00:00:00"} for i in range(4)]
    assert bulk_update_last_scraped_at(sb, payload) == 4


# ---------- call_rpc_with_fallback ----------


def test_call_rpc_with_fallback_happy_path_returns_data():
    sb = StubSupabase([SimpleNamespace(data=[{"id": 1}, {"id": 2}])])
    result = call_rpc_with_fallback(
        sb, "get_foo", {"p_id": 1}, fallback=lambda: pytest.fail("fallback should not fire")
    )
    assert result == [{"id": 1}, {"id": 2}]


def test_call_rpc_with_fallback_on_42883_invokes_fallback():
    sb = StubSupabase([_api_error(code="42883")])
    result = call_rpc_with_fallback(sb, "get_foo", {}, fallback=lambda: [{"fallback": True}])
    assert result == [{"fallback": True}]


def test_call_rpc_with_fallback_reraises_non_42883():
    sb = StubSupabase([_api_error(code="42P01", message="relation does not exist")])
    with pytest.raises(APIError):
        call_rpc_with_fallback(sb, "get_foo", {}, fallback=lambda: pytest.fail("should not fire"))


def test_bulk_update_chunk_size_constant_is_2000():
    # Guards against accidental renames / tuning of the performance contract.
    assert BULK_UPDATE_CHUNK_SIZE == 2000


def test_call_rpc_with_fallback_applies_default_row_limit():
    # Guards against the PostgREST 1000-row silent truncation on SETOF RPCs.
    sb = StubSupabase([SimpleNamespace(data=[1, 2, 3])])
    call_rpc_with_fallback(sb, "get_foo", {}, fallback=lambda: pytest.fail("unused"))
    # Recorded call is (fn_name, params, limit_arg)
    assert sb.calls[0][2] == RPC_RESULT_LIMIT


def test_call_rpc_with_fallback_accepts_explicit_limit():
    sb = StubSupabase([SimpleNamespace(data=[1, 2])])
    call_rpc_with_fallback(sb, "get_foo", {}, fallback=lambda: pytest.fail("unused"), limit=5000)
    assert sb.calls[0][2] == 5000


def test_call_rpc_with_fallback_omits_limit_when_none():
    sb = StubSupabase([SimpleNamespace(data=[])])
    call_rpc_with_fallback(sb, "get_foo", {}, fallback=lambda: pytest.fail("unused"), limit=None)
    assert sb.calls[0][2] is None


def test_rpc_result_limit_covers_current_alias_count():
    # Guards against accidentally lowering RPC_RESULT_LIMIT below the largest
    # current RPC payload (get_approved_aliases at ~136K rows for gotsport).
    assert RPC_RESULT_LIMIT >= 150_000
