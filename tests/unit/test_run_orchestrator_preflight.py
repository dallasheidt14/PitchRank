"""Unit tests for ``src.tournaments.run_orchestrator.preflight``.

Validates the per-cohort blocker filter (drops blockers naming OTHER
cohorts, keeps cohort-agnostic + this-cohort + manual-add blockers) and
the warnings axis (stale snapshot, high external-team ratio).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tournaments import run_orchestrator
from src.tournaments.run_orchestrator import preflight
from src.tournaments.storage import (
    EventMetadata,
    TeamRegistryEntry,
    append_override,
    ensure_scenario,
    write_event_metadata,
    write_registry,
    write_structure,
)
from src.tournaments.storage.structure import CohortStructure, DivisionStructure
from src.tournaments.triage import ReadinessResult

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def _bootstrap(
    base: Path,
    *,
    extras: dict | None = None,
    event_start: str = "2026-05-01",
    registry: list[TeamRegistryEntry] | None = None,
) -> None:
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=base)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name="Phoenix Cup 2026",
            event_slug="phoenix-cup-2026",
            event_start_date=event_start,
            scrape_ts="2026-04-15T00:00:00+00:00",
            season_year=2026,
            extras=extras or {},
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
                divisions=(DivisionStructure(name="A", team_count=2, pool_sizes=(2,)),),
            )
        ],
        base_dir=base,
    )
    write_registry(
        EVENT_KEY,
        SCENARIO,
        registry
        or [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="A Alpha",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
        ],
        base_dir=base,
    )


def test_preflight_filters_blockers_to_requested_cohort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap(tmp_path)
    monkeypatch.setattr(
        run_orchestrator,
        "is_ready",
        lambda *a, **k: ReadinessResult(
            ready=False,
            blockers=(
                "Boys u14: A Alpha pending review",
                "Boys u10: ghost-team pending review",
                "event metadata missing or unreadable: oops",
                "manual-add manual_x: cohort attribution missing (rewrite override)",
            ),
        ),
    )
    result = preflight(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        supabase_client=None,
    )
    blockers = set(result.blockers)
    assert "Boys u14: A Alpha pending review" in blockers
    assert "Boys u10: ghost-team pending review" not in blockers
    assert "event metadata missing or unreadable: oops" in blockers
    assert "manual-add manual_x: cohort attribution missing (rewrite override)" in blockers


def test_preflight_warns_on_stale_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap(
        tmp_path,
        extras={"ranking_snapshot_date": "2025-12-01"},
        event_start="2026-01-15",
    )
    monkeypatch.setattr(
        run_orchestrator,
        "is_ready",
        lambda *a, **k: ReadinessResult(ready=True, blockers=()),
    )
    result = preflight(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        supabase_client=None,
    )
    assert any("older than 14 days" in w for w in result.warnings)


def test_preflight_no_warnings_when_snapshot_recent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap(
        tmp_path,
        extras={"ranking_snapshot_date": "2026-01-08"},
        event_start="2026-01-15",
    )
    monkeypatch.setattr(
        run_orchestrator,
        "is_ready",
        lambda *a, **k: ReadinessResult(ready=True, blockers=()),
    )
    result = preflight(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        supabase_client=None,
    )
    assert result.warnings == ()


def test_preflight_warns_on_high_external_ratio_for_this_cohort_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Cohort u14 with 4 external out of 10
    u14_entries = [
        TeamRegistryEntry(
            event_registration_id=f"reg-u14-{i}",
            event_team_name=f"U14 Team {i}",
            event_age_group="u14",
            event_gender="Boys",
            resolved_gotsport_provider_team_id=f"pid-u14-{i}",
            resolved_team_id_master=f"tim-u14-{i}",
        )
        for i in range(10)
    ]
    u10_entries = [
        TeamRegistryEntry(
            event_registration_id=f"reg-u10-{i}",
            event_team_name=f"U10 Team {i}",
            event_age_group="u10",
            event_gender="Boys",
            resolved_gotsport_provider_team_id=f"pid-u10-{i}",
            resolved_team_id_master=f"tim-u10-{i}",
        )
        for i in range(8)
    ]
    _bootstrap(tmp_path, registry=u14_entries + u10_entries)
    # Mark 4 of u14 external via mark_external override
    for i in range(4):
        append_override(
            EVENT_KEY,
            SCENARIO,
            {
                "ts": f"2026-04-20T00:00:0{i}+00:00",
                "actor": "ops@example.com",
                "scope": "team",
                "type": "mark_external",
                "team_ref": f"pid-u14-{i}",
                "before": {},
                "after": {},
                "reason": "test",
            },
            base_dir=tmp_path,
        )

    monkeypatch.setattr(
        run_orchestrator,
        "is_ready",
        lambda *a, **k: ReadinessResult(ready=True, blockers=()),
    )

    result_u14 = preflight(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        supabase_client=None,
    )
    assert any("high external-team ratio" in w for w in result_u14.warnings)

    result_u10 = preflight(
        EVENT_KEY,
        SCENARIO,
        "u10",
        "Boys",
        base_dir=tmp_path,
        supabase_client=None,
    )
    assert not any("high external-team ratio" in w for w in result_u10.warnings)
