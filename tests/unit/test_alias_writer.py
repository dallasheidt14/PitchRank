"""Unit tests for ``src.tournaments.alias_writer``.

Covers the routing table scenarios Shell-01 Step 7 validates against live DB:
method-tier protection, conflict detection, clamp, dedupe-across-statuses, and
multi-conflict insertion.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.tournaments.alias_writer import (
    METHOD_TIER,
    enqueue_match_review,
    upsert_team_alias,
)


class _FakeQuery:
    """Chainable ``.eq().select().execute()`` stub that filters ``_store`` in-memory."""

    def __init__(self, table: "_FakeTable", op: str, payload: dict[str, Any] | None = None):
        self._table = table
        self._op = op
        self._payload = payload or {}
        self._filters: list[tuple[str, Any]] = []
        self._select: str | None = None
        self._single = False

    def select(self, columns: str = "*") -> "_FakeQuery":
        self._select = columns
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self._filters.append((column, value))
        return self

    def single(self) -> "_FakeQuery":
        self._single = True
        return self

    def execute(self) -> Any:
        store = self._table._store
        if self._op == "select":
            matched = [row for row in store if all(row.get(c) == v for c, v in self._filters)]
            if self._single:
                return _FakeExecResult(matched[0] if matched else None)
            return _FakeExecResult(matched)
        if self._op == "insert":
            new = dict(self._payload)
            new.setdefault("id", f"row-{len(store)+1}")
            store.append(new)
            self._table._log.append(("insert", dict(new)))
            return _FakeExecResult([new])
        if self._op == "update":
            matched = [row for row in store if all(row.get(c) == v for c, v in self._filters)]
            for row in matched:
                row.update(self._payload)
                self._table._log.append(("update", dict(row)))
            return _FakeExecResult(matched)
        raise AssertionError(f"Unknown op: {self._op}")


class _FakeExecResult:
    def __init__(self, data: Any):
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self._store: list[dict[str, Any]] = list(rows) if rows else []
        self._log: list[tuple[str, dict[str, Any]]] = []

    def select(self, columns: str = "*") -> _FakeQuery:
        return _FakeQuery(self, "select").select(columns)

    def insert(self, payload: dict[str, Any]) -> _FakeQuery:
        return _FakeQuery(self, "insert", payload)

    def update(self, payload: dict[str, Any]) -> _FakeQuery:
        return _FakeQuery(self, "update", payload)


class _FakeSupabase:
    def __init__(
        self,
        *,
        providers: list[dict[str, Any]],
        team_alias_map: list[dict[str, Any]] | None = None,
        team_match_review_queue: list[dict[str, Any]] | None = None,
    ):
        self.tables = {
            "providers": _FakeTable(providers),
            "team_alias_map": _FakeTable(team_alias_map),
            "team_match_review_queue": _FakeTable(team_match_review_queue),
        }

    def table(self, name: str) -> _FakeTable:
        return self.tables[name]


def _gotsport_supabase(**overrides: Any) -> _FakeSupabase:
    return _FakeSupabase(
        providers=[{"id": "uuid-gotsport", "code": "gotsport"}],
        **overrides,
    )


def test_method_tier_ordering_manual_beats_direct_id():
    assert METHOD_TIER["manual"] > METHOD_TIER["manual_review"]
    assert METHOD_TIER["manual_review"] > METHOD_TIER["manual_queue"]
    assert METHOD_TIER["manual_queue"] > METHOD_TIER["import"]
    assert METHOD_TIER["import"] > METHOD_TIER["direct_id"]
    assert METHOD_TIER["direct_id"] > METHOD_TIER["fuzzy_auto"]
    assert METHOD_TIER["fuzzy_auto"] > METHOD_TIER["fuzzy_review"]


def test_upsert_alias_creates_new_row_with_fuzzy_ceiling_clamp():
    supabase = _gotsport_supabase()
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-1",
        provider_team_name="Team One",
        confidence=1.0,
        match_method="fuzzy_auto",
        priority_score=1.0,
    )
    assert result["action"] == "created"
    # ceiling clamp applies because fuzzy_auto is not in ("direct_id", "import")
    assert result["match_confidence"] == 0.99
    alias_rows = supabase.tables["team_alias_map"]._store
    assert len(alias_rows) == 1
    assert alias_rows[0]["match_confidence"] == 0.99


def test_upsert_alias_direct_id_preserves_confidence_above_ceiling():
    supabase = _gotsport_supabase()
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-1",
        provider_team_name="Team One",
        confidence=1.0,
        match_method="direct_id",
        priority_score=1.0,
    )
    assert result["action"] == "created"
    assert result["match_confidence"] == 1.0


def test_upsert_alias_approved_manual_beats_incoming_direct_id():
    existing = {
        "id": "alias-1",
        "provider_id": "uuid-gotsport",
        "provider_team_id": "t1",
        "team_id_master": "master-1",
        "match_confidence": 1.0,
        "match_method": "manual",
        "review_status": "approved",
    }
    supabase = _gotsport_supabase(team_alias_map=[existing])
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-1",
        provider_team_name="Team One",
        confidence=1.0,
        match_method="direct_id",
        priority_score=1.0,
    )
    assert result["action"] == "skipped_weaker_metadata"
    assert supabase.tables["team_alias_map"]._store[0]["match_method"] == "manual"


def test_upsert_alias_approved_direct_id_beats_incoming_fuzzy_auto():
    existing = {
        "id": "alias-1",
        "provider_id": "uuid-gotsport",
        "provider_team_id": "t1",
        "team_id_master": "master-1",
        "match_confidence": 1.0,
        "match_method": "direct_id",
        "review_status": "approved",
    }
    supabase = _gotsport_supabase(team_alias_map=[existing])
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-1",
        provider_team_name="Team One",
        confidence=0.92,
        match_method="fuzzy_auto",
        priority_score=0.92,
    )
    assert result["action"] == "skipped_weaker_metadata"


def test_upsert_alias_pending_row_overwritten():
    existing = {
        "id": "alias-1",
        "provider_id": "uuid-gotsport",
        "provider_team_id": "t1",
        "team_id_master": "master-1",
        "match_confidence": 0.91,
        "match_method": "fuzzy_auto",
        "review_status": "pending",
    }
    supabase = _gotsport_supabase(team_alias_map=[existing])
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-2",
        provider_team_name="Team One",
        confidence=0.95,
        match_method="fuzzy_auto",
        priority_score=0.95,
    )
    assert result["action"] == "updated"
    stored = supabase.tables["team_alias_map"]._store[0]
    assert stored["team_id_master"] == "master-2"


def test_upsert_alias_approved_conflict_routes_to_queue():
    existing_alias = {
        "id": "alias-1",
        "provider_id": "uuid-gotsport",
        "provider_team_id": "t1",
        "team_id_master": "master-prior",
        "match_confidence": 1.0,
        "match_method": "direct_id",
        "review_status": "approved",
    }
    supabase = _gotsport_supabase(team_alias_map=[existing_alias])
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-candidate",
        provider_team_name="Team One",
        confidence=0.97,
        match_method="direct_id",
        priority_score=0.97,
    )
    assert result["action"] == "conflict"
    assert result["queue_result"]["action"] == "queued"
    queue_rows = supabase.tables["team_match_review_queue"]._store
    assert len(queue_rows) == 1
    details = queue_rows[0]["match_details"]
    assert details["conflict"]["prior_master"] == "master-prior"
    assert details["conflict"]["candidate_master"] == "master-candidate"
    # confidence clamp preserves priority_score
    assert queue_rows[0]["confidence_score"] == 0.89
    assert queue_rows[0]["priority_score"] == 0.97


def test_upsert_alias_conflict_skipped_rejected_when_queue_has_rejected_row():
    existing_alias = {
        "id": "alias-1",
        "provider_id": "uuid-gotsport",
        "provider_team_id": "t1",
        "team_id_master": "master-prior",
        "match_confidence": 1.0,
        "match_method": "direct_id",
        "review_status": "approved",
    }
    existing_queue = {
        "id": "rev-1",
        "provider_id": "gotsport",
        "provider_team_id": "t1",
        "status": "rejected",
        "match_details": {
            "conflict": {
                "prior_master": "master-prior",
                "candidate_master": "master-candidate",
            }
        },
        "suggested_master_team_id": "master-candidate",
    }
    supabase = _gotsport_supabase(
        team_alias_map=[existing_alias],
        team_match_review_queue=[existing_queue],
    )
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-candidate",
        provider_team_name="Team One",
        confidence=0.97,
        match_method="direct_id",
        priority_score=0.97,
    )
    assert result["action"] == "conflict_skipped_rejected"
    # no new queue row inserted
    assert len(supabase.tables["team_match_review_queue"]._store) == 1


def test_enqueue_match_review_clamps_confidence_to_089_and_stores_priority_score():
    supabase = _gotsport_supabase()
    result = enqueue_match_review(
        supabase,
        provider_code="gotsport",
        provider_team_id="t1",
        provider_team_name="Team One",
        suggested_master_team_id="master-1",
        confidence=0.92,
        priority_score=0.92,
        match_details={"true_confidence": 0.92, "age_group": "U14"},
    )
    assert result["action"] == "queued"
    row = supabase.tables["team_match_review_queue"]._store[0]
    assert row["confidence_score"] == 0.89
    assert row["priority_score"] == 0.92
    assert row["match_details"]["true_confidence"] == 0.92


def test_enqueue_match_review_dedupes_into_existing_pending_row():
    existing = {
        "id": "rev-1",
        "provider_id": "gotsport",
        "provider_team_id": "t1",
        "provider_team_name": "Team One",
        "status": "pending",
        "match_details": {"reason": "first_pass"},
    }
    supabase = _gotsport_supabase(team_match_review_queue=[existing])
    result = enqueue_match_review(
        supabase,
        provider_code="gotsport",
        provider_team_id="t1",
        provider_team_name="Team One",
        suggested_master_team_id="master-1",
        confidence=0.92,
        priority_score=0.92,
        match_details={"also_appears_in_brackets": ["A", "B"]},
    )
    assert result["action"] == "deduped_pending"
    row = supabase.tables["team_match_review_queue"]._store[0]
    assert row["match_details"]["also_appears_in_brackets"] == ["A", "B"]
    assert row["match_details"]["reason"] == "first_pass"  # preserved
    # still one row total
    assert len(supabase.tables["team_match_review_queue"]._store) == 1


def test_enqueue_match_review_multi_conflict_inserts_new_row():
    existing = {
        "id": "rev-1",
        "provider_id": "gotsport",
        "provider_team_id": "t1",
        "status": "pending",
        "match_details": {
            "conflict": {"prior_master": "master-A", "candidate_master": "master-B"}
        },
        "suggested_master_team_id": "master-B",
    }
    supabase = _gotsport_supabase(team_match_review_queue=[existing])
    result = enqueue_match_review(
        supabase,
        provider_code="gotsport",
        provider_team_id="t1",
        provider_team_name="Team One",
        suggested_master_team_id="master-C",
        confidence=0.95,
        priority_score=0.95,
        match_details={
            "conflict": {"prior_master": "master-A", "candidate_master": "master-C"},
        },
    )
    assert result["action"] == "queued"
    assert result.get("multi_conflict") is True
    assert len(supabase.tables["team_match_review_queue"]._store) == 2


def test_enqueue_match_review_skipped_rejected_for_historical_match():
    existing = {
        "id": "rev-1",
        "provider_id": "gotsport",
        "provider_team_id": "t1",
        "status": "rejected",
        "match_details": {
            "conflict": {"prior_master": "A", "candidate_master": "B"}
        },
        "suggested_master_team_id": "B",
    }
    supabase = _gotsport_supabase(team_match_review_queue=[existing])
    result = enqueue_match_review(
        supabase,
        provider_code="gotsport",
        provider_team_id="t1",
        provider_team_name="Team One",
        suggested_master_team_id="B",
        confidence=0.95,
        priority_score=0.95,
        match_details={"conflict": {"prior_master": "A", "candidate_master": "B"}},
    )
    assert result["action"] == "skipped_rejected"
    assert len(supabase.tables["team_match_review_queue"]._store) == 1


def test_enqueue_match_review_skipped_already_approved_when_status_approved():
    existing = {
        "id": "rev-1",
        "provider_id": "gotsport",
        "provider_team_id": "t1",
        "status": "approved",
        "match_details": {
            "conflict": {"prior_master": "A", "candidate_master": "B"}
        },
        "suggested_master_team_id": "B",
    }
    supabase = _gotsport_supabase(team_match_review_queue=[existing])
    result = enqueue_match_review(
        supabase,
        provider_code="gotsport",
        provider_team_id="t1",
        provider_team_name="Team One",
        suggested_master_team_id="B",
        confidence=0.95,
        priority_score=0.95,
        match_details={"conflict": {"prior_master": "A", "candidate_master": "B"}},
    )
    assert result["action"] == "skipped_already_approved"


def test_resolve_provider_identity_requires_at_least_one():
    supabase = _gotsport_supabase()
    # neither uuid nor code → falls to ValueError caught as db_error
    result = upsert_team_alias(
        supabase,
        provider_team_id="t1",
        team_id_master="m1",
        provider_team_name="T1",
        confidence=1.0,
        match_method="direct_id",
        priority_score=1.0,
    )
    assert result["action"] == "db_error"
    assert "provider_uuid or provider_code" in result["error"]


def test_db_error_propagates_when_queue_insert_fails():
    class _RaisingTable(_FakeTable):
        def insert(self, payload: dict[str, Any]) -> _FakeQuery:
            raise RuntimeError("db down")

    supabase = _gotsport_supabase()
    supabase.tables["team_match_review_queue"] = _RaisingTable()
    result = enqueue_match_review(
        supabase,
        provider_code="gotsport",
        provider_team_id="t1",
        provider_team_name="T1",
        suggested_master_team_id="m1",
        confidence=0.9,
        priority_score=0.9,
        match_details={},
    )
    assert result["action"] == "db_error"
    assert result["exc_type"] == "RuntimeError"


def test_conflict_loop_detected_when_nested_returns_skipped_already_approved():
    existing_alias = {
        "id": "alias-1",
        "provider_id": "uuid-gotsport",
        "provider_team_id": "t1",
        "team_id_master": "master-prior",
        "match_confidence": 1.0,
        "match_method": "direct_id",
        "review_status": "approved",
    }
    existing_queue = {
        "id": "rev-1",
        "provider_id": "gotsport",
        "provider_team_id": "t1",
        "status": "approved",
        "match_details": {
            "conflict": {"prior_master": "master-prior", "candidate_master": "master-candidate"}
        },
        "suggested_master_team_id": "master-candidate",
    }
    supabase = _gotsport_supabase(
        team_alias_map=[existing_alias],
        team_match_review_queue=[existing_queue],
    )
    result = upsert_team_alias(
        supabase,
        provider_uuid="uuid-gotsport",
        provider_code="gotsport",
        provider_team_id="t1",
        team_id_master="master-candidate",
        provider_team_name="Team One",
        confidence=0.97,
        match_method="direct_id",
        priority_score=0.97,
    )
    assert result["action"] == "conflict_loop_detected"
