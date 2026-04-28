"""Unit tests for ``tournament_intake._recompute_medians_inner``.

Pins Shell 09's stale-assignment skip behavior: teams whose
``assigned_division_name`` no longer matches a current structure
division must be excluded from the medians and surfaced via
``st.warning``, not silently bucketed into the prefix-resolved division.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tournaments.storage import (
    EventMetadata,
    TeamRegistryEntry,
    append_override,
    ensure_scenario,
    load_overrides,
    read_structure,
    write_event_metadata,
    write_registry,
    write_structure,
)
from src.tournaments.storage.structure import CohortStructure, DivisionStructure
from tournament_intake import _recompute_medians_inner

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def _bootstrap(base: Path) -> None:
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=base)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name="Phoenix Cup 2026",
            event_slug="phoenix-cup-2026",
            event_start_date="2026-05-01",
            scrape_ts="2026-04-15T00:00:00+00:00",
            season_year=2026,
        ),
        base_dir=base,
    )
    write_structure(
        EVENT_KEY,
        SCENARIO,
        [
            CohortStructure(
                age_group="u14",
                gender="Boys",
                divisions=(DivisionStructure(name="BU14 Premier", team_count=2, pool_sizes=(2,)),),
            )
        ],
        base_dir=base,
    )
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="BU14 Premier Phoenix Rising",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
            TeamRegistryEntry(
                event_registration_id="reg-2",
                event_team_name="BU14 Premier Real Madrid",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-2",
                resolved_team_id_master="tim-2",
            ),
        ],
        base_dir=base,
    )


class _FakeQueryBuilder:
    """Minimal Supabase query-builder stub for the rankings_full read.

    Records the requested ``team_id`` ``in_`` filter and returns rows for
    only those ids. The test sets ``rows_by_id`` so each test can stage
    its own per-team powerscores.
    """

    def __init__(self, rows_by_id: dict[str, dict[str, Any]]) -> None:
        self._rows_by_id = rows_by_id
        self._wanted_ids: list[str] = []

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQueryBuilder":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_FakeQueryBuilder":
        return self

    def ilike(self, *_args: Any, **_kwargs: Any) -> "_FakeQueryBuilder":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_FakeQueryBuilder":
        return self

    def in_(self, _column: str, ids: list[str]) -> "_FakeQueryBuilder":
        self._wanted_ids = list(ids)
        return self

    def execute(self) -> Any:
        rows = [self._rows_by_id[tid] for tid in self._wanted_ids if tid in self._rows_by_id]
        return type("Resp", (), {"data": rows})()


class _FakeSupabase:
    def __init__(self, rows_by_id: dict[str, dict[str, Any]]) -> None:
        self._rows_by_id = rows_by_id

    def table(self, _name: str) -> _FakeQueryBuilder:
        return _FakeQueryBuilder(self._rows_by_id)


def test_recompute_medians_skips_stale_assigned_team(tmp_path: Path, monkeypatch: Any) -> None:
    """Team with ``assigned_division_name="BU14 Removed"`` must NOT
    contribute to the BU14 Premier bucket — operator explicitly
    de-assigned it from this division."""
    _bootstrap(tmp_path)
    # pid-2 carries a stale assignment to a since-removed division.
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:00:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "assign_division",
            "team_ref": "pid-2",
            "before": {},
            "after": {"assigned_division_name": "BU14 Removed"},
            "reason": "operator removed",
        },
        base_dir=tmp_path,
    )

    rows_by_id = {
        "tim-1": {"team_id": "tim-1", "powerscore_ml": 14.0},
        "tim-2": {"team_id": "tim-2", "powerscore_ml": 99.0},  # would skew medians badly
    }

    captured_buckets: dict[str, list[float]] = {}
    captured_warnings: list[str] = []

    import tournament_intake

    def _fake_compute(buckets: dict[str, list[float]]) -> Any:
        captured_buckets.update(buckets)
        return type("Medians", (), {"medians_by_division": {k: sum(v) / len(v) for k, v in buckets.items() if v}})()

    monkeypatch.setattr(tournament_intake, "compute_frozen_medians", _fake_compute)
    monkeypatch.setattr(tournament_intake, "write_frozen_medians", lambda *a, **k: None)
    monkeypatch.setattr(
        tournament_intake, "read_frozen_medians", lambda *a, **k: type("FM", (), {"medians_by_division": {}})()
    )

    class _StWarn:
        @staticmethod
        def warning(msg: str) -> None:
            captured_warnings.append(msg)

        @staticmethod
        def error(msg: str) -> None:  # pragma: no cover — surfaces test bugs
            captured_warnings.append(f"ERROR: {msg}")

    monkeypatch.setattr(tournament_intake, "st", _StWarn)
    monkeypatch.setattr(tournament_intake, "_load_registry_cached", _LoadCacheStub(tmp_path))
    monkeypatch.setattr(tournament_intake, "_rankings_full_age_form", lambda age, _sb: age)

    fake_sb = _FakeSupabase(rows_by_id)

    # Patch base_dir for the storage helpers — they default to ``"reports"``
    # so we must monkeypatch the rebound module-level imports inside
    # tournament_intake. ``append_override`` also defaults to ``"reports"``
    # and would write outside ``tmp_path`` if not patched (test would
    # leak audit records into the repo's ``reports/`` directory).
    captured_overrides: list[dict[str, Any]] = []

    def _capture_append_override(event_key: str, scenario: str, record: dict[str, Any], **kwargs: Any) -> None:
        captured_overrides.append({"record": record, "kwargs": kwargs})

    monkeypatch.setattr(
        tournament_intake,
        "load_overrides",
        lambda event_key, scenario: load_overrides(event_key, scenario, base_dir=tmp_path),
    )
    monkeypatch.setattr(
        tournament_intake,
        "read_structure",
        lambda event_key, scenario: read_structure(event_key, scenario, base_dir=tmp_path),
    )
    monkeypatch.setattr(tournament_intake, "append_override", _capture_append_override)

    _recompute_medians_inner(
        event_key=EVENT_KEY,
        scenario=SCENARIO,
        age="u14",
        gender="Boys",
        supabase_client=fake_sb,
        reviewer_email="ops@example.com",
    )

    # Audit-log write fired with the lock-elision flag (recompute is
    # nested inside an outer scenario lock).
    assert len(captured_overrides) == 1
    assert captured_overrides[0]["kwargs"].get("_already_locked") is True
    assert captured_overrides[0]["record"]["type"] == "recompute_medians"

    # Only tim-1 contributed to the bucket; tim-2 (stale) was skipped.
    assert captured_buckets == {"BU14 Premier": [14.0]}
    # Operator was warned about the stale-assignment skip.
    assert any("stale-assigned" in w for w in captured_warnings)
    assert any("BU14 Premier Real Madrid" in w for w in captured_warnings)


class _LoadCacheStub:
    """Drop-in stub for the ``@st.cache_data`` ``_load_registry_cached`` wrapper.

    The real cache wrapper is callable AND has a ``.clear`` method; the
    test cohort uses two registry rows from ``_bootstrap``. Re-reading
    via ``read_registry`` keeps the test in lockstep with the on-disk
    fixture.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def __call__(self, event_key: str, scenario: str) -> list[dict[str, Any]]:
        from src.tournaments.storage import read_registry

        return [entry.to_row() for entry in read_registry(event_key, scenario, base_dir=self._base_dir)]

    def clear(self) -> None:
        return None
