"""Unit tests for the outreach verification result mapping and invalid-rate gate."""

import pytest

from src.outreach import verify
from src.outreach.verify import _map_result, decide_gate


def _rows(*statuses):
    return [{"id": i, "verification_status": s} for i, s in enumerate(statuses)]


def test_map_result_covers_neverbounce_results():
    assert _map_result("valid") == "valid"
    assert _map_result("invalid") == "invalid"
    assert _map_result("disposable") == "invalid"
    assert _map_result("catchall") == "risky"
    assert _map_result("unknown") == "risky"
    assert _map_result("brand_new_result") == "risky"  # unmapped vendor result -> risky


def test_clean_slice_promotes_valid_holds_risky_and_no_email():
    rows = _rows("valid", "valid", "risky", None)  # None = no-email / unverified
    decision = decide_gate(rows, threshold=0.03)
    assert decision["gate"] == "passed"
    assert set(decision["promote_ids"]) == {0, 1}
    assert set(decision["hold_ids"]) == {2, 3}
    assert decision["invalid_fraction"] == 0.0  # 0 invalid / 3 verified


def test_dirty_slice_holds_everything():
    rows = _rows("valid", "valid", "invalid")  # 1/3 = 33% > 3%
    decision = decide_gate(rows, threshold=0.03)
    assert decision["gate"] == "held_slice"
    assert decision["promote_ids"] == []
    assert set(decision["hold_ids"]) == {0, 1, 2}


def test_denominator_is_rows_actually_verified():
    # 10 verified rows, 1 invalid -> 10%, not diluted by anything else.
    rows = _rows(*(["valid"] * 9 + ["invalid"]))
    decision = decide_gate(rows, threshold=0.03)
    assert decision["verified_count"] == 10
    assert decision["invalid_fraction"] == 0.1
    assert decision["gate"] == "held_slice"


def test_threshold_boundary_promotes():
    # Exactly at threshold: 1/100 = 1% <= 3% -> promote the valids.
    rows = _rows(*(["valid"] * 99 + ["invalid"]))
    decision = decide_gate(rows, threshold=0.03)
    assert decision["gate"] == "passed"
    assert len(decision["promote_ids"]) == 99
    assert decision["hold_ids"] == [99]


def test_all_no_email_holds_all_without_divide_by_zero():
    rows = _rows(None, None, None)
    decision = decide_gate(rows, threshold=0.03)
    assert decision["invalid_fraction"] is None
    assert decision["promote_ids"] == []
    assert set(decision["hold_ids"]) == {0, 1, 2}


# --- verify_email status guard (monkeypatch the HTTP call, no network) ---


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_verify_email_raises_on_non_success_status(monkeypatch):
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "x")
    monkeypatch.setattr(
        verify, "retry_session_get", lambda *a, **k: _FakeResp({"status": "auth_failure", "message": "bad key"})
    )
    with pytest.raises(RuntimeError):
        verify.verify_email("a@b.com")


def test_verify_email_maps_result_on_success(monkeypatch):
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "x")
    monkeypatch.setattr(
        verify, "retry_session_get", lambda *a, **k: _FakeResp({"status": "success", "result": "valid"})
    )
    assert verify.verify_email("a@b.com") == "valid"


def test_verify_email_maps_catchall_to_risky(monkeypatch):
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "x")
    monkeypatch.setattr(
        verify, "retry_session_get", lambda *a, **k: _FakeResp({"status": "success", "result": "catchall"})
    )
    assert verify.verify_email("a@b.com") == "risky"
