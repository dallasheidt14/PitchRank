"""Unit tests for ``src.tournaments.triage.is_ready``.

The readiness predicate is what Shell 06 calls before allowing a run to
launch. This file pins the per-team blockers (candidates / placeholder /
unknown) and per-cohort blockers (no structure / partial games coverage),
plus the all-green ``ready=True`` happy path.

FakeSupabase is colocated — no precedent for shared fakes in
``tests/unit/`` and the inline shape mirrors
``tests/unit/test_storage_games_import.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tournaments.storage._io import append_jsonl
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.event_metadata import (
    EventMetadata,
    write_event_metadata,
)
from src.tournaments.storage.overrides import append_override
from src.tournaments.storage.registry import TeamRegistryEntry, write_registry
from src.tournaments.storage.scenario import ensure_scenario
from src.tournaments.storage.structure import (
    CohortStructure,
    DivisionStructure,
    write_structure,
)
from src.tournaments.triage import is_ready

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"
EVENT_NAME = "Phoenix Cup 2026"


# -------- FakeSupabase ---------------------------------------------------


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self._eq: list[tuple[str, Any]] = []
        self._in: list[tuple[str, list[Any]]] = []

    def select(self, columns: str = "*") -> "_FakeQuery":
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self._eq.append((column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "_FakeQuery":
        self._in.append((column, list(values)))
        return self

    def execute(self) -> Any:
        out = []
        for row in self._rows:
            if any(row.get(c) != v for c, v in self._eq):
                continue
            if any(row.get(c) not in vs for c, vs in self._in):
                continue
            out.append(row)
        return _FakeExecResult(out)


class _FakeExecResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _FakeSupabase:
    def __init__(
        self,
        *,
        teams: list[dict[str, Any]] | None = None,
        games: list[dict[str, Any]] | None = None,
    ):
        self._teams = teams or []
        self._games = games or []

    def table(self, name: str) -> _FakeQuery:
        if name == "teams":
            return _FakeQuery(self._teams)
        if name == "games":
            return _FakeQuery(self._games)
        raise AssertionError(f"unexpected table {name!r}")


# -------- fixtures helpers ------------------------------------------------


def _seed_event(
    base: Path,
    *,
    raw_records: list[dict],
    registry_entries: list[TeamRegistryEntry],
    structure: list[CohortStructure],
) -> None:
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=base)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name=EVENT_NAME,
            event_slug="phoenix-cup-2026",
            event_start_date="2026-04-01",
            scrape_ts="2026-04-26T12:00:00+00:00",
            season_year=2026,
        ),
        base_dir=base,
    )
    journal_path = intake_dir(EVENT_KEY, base_dir=base) / "raw_scrape.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    for record in raw_records:
        append_jsonl(journal_path, record)
    write_registry(EVENT_KEY, SCENARIO, registry_entries, base_dir=base)
    write_structure(EVENT_KEY, SCENARIO, structure, base_dir=base)


def _raw(pid: str, scraper_state: str, *, age: str = "u14", gender: str = "Male") -> dict:
    return {
        "run_id": "2026-04-26T12:00:00",
        "provider_team_id": pid,
        "team_name": f"Team {pid}",
        "club_name": "Phoenix Rising",
        "cohort_age_group": age,
        "cohort_gender": gender,
        "division": "Premier",
        "bracket_name": "Premier A",
        "playing_up": False,
        "has_view_rankings_link": True,
        "provider_id_resolution_status": "matched",
        "also_appears_in_brackets": [],
        "canonical": {
            "team_id_master": f"m_{pid}" if scraper_state == "alias_written" else None,
            "confidence": 1.0,
            "resolved_status": "high_confidence",
            "match_method": "direct_id" if scraper_state == "alias_written" else None,
            "scraper_state": scraper_state,
        },
        "alias_writer_action": "created",
        "scrape_ts": "2026-04-26T12:00:00",
        "source_url": "https://example.com",
        "provider_event_id": "45224",
    }


def _registry(
    pid: str,
    *,
    age: str = "u14",
    gender: str = "Male",
    canonical_status: str = "high_confidence",
    resolved_team_id: str | None = None,
) -> TeamRegistryEntry:
    return TeamRegistryEntry(
        event_registration_id=f"reg_{pid}",
        event_team_name=f"Team {pid}",
        event_age_group=age,
        display_age_group=age.upper(),
        event_gender=gender,
        display_gender="Boys" if gender == "Male" else "Girls",
        event_club_name="Phoenix Rising",
        resolved_gotsport_provider_team_id=pid,
        canonical_resolution_status=canonical_status,
        in_scope_u10_u19="True",
        resolved_team_id_master=resolved_team_id or (f"m_{pid}" if canonical_status != "review" else ""),
    )


def _structure(age: str = "u14", gender: str = "Male") -> list[CohortStructure]:
    return [
        CohortStructure(
            age_group=age,
            gender=gender,
            divisions=(DivisionStructure(name="Premier", team_count=2),),
        )
    ]


# -------- tests -----------------------------------------------------------


def test_ready_when_all_resolved_with_complete_games(tmp_path: Path):
    raw = [_raw("p1", "alias_written"), _raw("p2", "alias_written")]
    registry = [_registry("p1"), _registry("p2")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    supabase = _FakeSupabase(
        teams=[
            {"team_id_master": "m_p1", "team_name": "Real Team 1"},
            {"team_id_master": "m_p2", "team_name": "Real Team 2"},
        ],
        games=[
            {
                "event_name": EVENT_NAME,
                "is_excluded": False,
                "home_team_master_id": "m_p1",
                "away_team_master_id": "m_p2",
            },
        ],
    )
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is True
    assert result.blockers == ()


def test_blocked_by_candidates_state(tmp_path: Path):
    raw = [_raw("p1", "review_queued"), _raw("p2", "alias_written")]
    registry = [_registry("p1", canonical_status="review"), _registry("p2")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    supabase = _FakeSupabase(
        teams=[{"team_id_master": "m_p2", "team_name": "Real Team 2"}],
        games=[
            {
                "event_name": EVENT_NAME,
                "is_excluded": False,
                "home_team_master_id": "m_p2",
                "away_team_master_id": "other",
            },
        ],
    )
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is False
    assert any("pending review" in blocker for blocker in result.blockers)


def test_blocked_by_placeholder_state(tmp_path: Path):
    raw = [_raw("p1", "alias_written"), _raw("p2", "alias_written")]
    registry = [_registry("p1"), _registry("p2")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    supabase = _FakeSupabase(
        teams=[
            {"team_id_master": "m_p1", "team_name": "unknown_p1"},  # placeholder
            {"team_id_master": "m_p2", "team_name": "Real Team 2"},
        ],
        games=[
            {
                "event_name": EVENT_NAME,
                "is_excluded": False,
                "home_team_master_id": "m_p1",
                "away_team_master_id": "m_p2",
            },
        ],
    )
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is False
    assert any("placeholder" in blocker for blocker in result.blockers)


def test_blocked_by_unknown_state(tmp_path: Path):
    raw = [
        # Missing canonical → unknown state
        {
            "run_id": "2026-04-26T12:00:00",
            "provider_team_id": "p1",
            "team_name": "Team p1",
            "cohort_age_group": "u14",
            "cohort_gender": "Male",
        }
    ]
    registry = [_registry("p1", canonical_status="")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    supabase = _FakeSupabase(teams=[], games=[])
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is False
    assert any("state unknown" in blocker for blocker in result.blockers)


def test_blocked_by_missing_structure(tmp_path: Path):
    raw = [_raw("p1", "alias_written")]
    registry = [_registry("p1")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=[],  # no structure entered
    )
    supabase = _FakeSupabase(
        teams=[{"team_id_master": "m_p1", "team_name": "Real Team 1"}],
        games=[],
    )
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is False
    assert any("structure not entered" in blocker for blocker in result.blockers)


def test_blocked_by_partial_games_coverage(tmp_path: Path):
    raw = [_raw("p1", "alias_written"), _raw("p2", "alias_written")]
    registry = [_registry("p1"), _registry("p2")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    supabase = _FakeSupabase(
        teams=[
            {"team_id_master": "m_p1", "team_name": "Real Team 1"},
            {"team_id_master": "m_p2", "team_name": "Real Team 2"},
        ],
        games=[
            # Only p1 has a game; p2 has none → partial
            {
                "event_name": EVENT_NAME,
                "is_excluded": False,
                "home_team_master_id": "m_p1",
                "away_team_master_id": "other_team",
            },
        ],
    )
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is False
    assert any("games coverage partial" in blocker for blocker in result.blockers)


def test_manual_add_resolved_blocks_when_games_partial(tmp_path: Path):
    """Manual-add resolved teams must be visible to the games-coverage gate.
    Before the manual_add visibility fix, ``is_ready`` could return ``True``
    even when a manual-add team had zero games in the DB."""
    raw = [_raw("p1", "alias_written")]
    registry = [_registry("p1")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    # Operator manually added a second team via the +Add team form.
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-26T13:00:00+00:00",
            "actor": "dallas@example.com",
            "scope": "team",
            "type": "manual_add",
            "team_ref": "manual_abc123",
            "before": {},
            "after": {
                "state": "resolved",
                "team_id_master": "m_manual_abc",
                "manual_seed_group": "Premier",
                "cohort_age_group": "u14",
                "cohort_gender": "Male",
            },
            "reason": "manual add — DB match",
        },
        base_dir=tmp_path,
    )
    supabase = _FakeSupabase(
        teams=[
            {"team_id_master": "m_p1", "team_name": "Real Team 1"},
            {"team_id_master": "m_manual_abc", "team_name": "Manual Team"},
        ],
        # p1 has a game; the manual-add team does NOT — coverage should be
        # partial.
        games=[
            {
                "event_name": EVENT_NAME,
                "is_excluded": False,
                "home_team_master_id": "m_p1",
                "away_team_master_id": "other",
            },
        ],
    )
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is False
    assert any("games coverage partial" in blocker for blocker in result.blockers)


def test_is_ready_returns_blocker_when_event_metadata_missing(tmp_path: Path):
    """When ``event_metadata.json`` is missing, ``is_ready`` returns a
    blocker rather than crashing with ``FileNotFoundError``."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    write_registry(EVENT_KEY, SCENARIO, [], base_dir=tmp_path)
    write_structure(EVENT_KEY, SCENARIO, [], base_dir=tmp_path)
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=None)
    assert result.ready is False
    assert any("event metadata missing" in blocker for blocker in result.blockers)


def test_override_accept_match_unblocks_candidate(tmp_path: Path):
    raw = [_raw("p1", "review_queued")]
    registry = [_registry("p1", canonical_status="review")]
    _seed_event(
        tmp_path,
        raw_records=raw,
        registry_entries=registry,
        structure=_structure(),
    )
    # Operator accepted the top match — projection should mark p1 resolved.
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-26T13:00:00+00:00",
            "actor": "dallas@example.com",
            "scope": "team",
            "type": "accept_match",
            "team_ref": "p1",
            "before": {"state": "candidates"},
            "after": {"state": "resolved", "team_id_master": "m_p1", "match_rank": 1},
            "reason": "best match",
        },
        base_dir=tmp_path,
    )
    supabase = _FakeSupabase(
        teams=[{"team_id_master": "m_p1", "team_name": "Real Team 1"}],
        games=[
            {
                "event_name": EVENT_NAME,
                "is_excluded": False,
                "home_team_master_id": "m_p1",
                "away_team_master_id": "other",
            },
        ],
    )
    structure = [
        CohortStructure(
            age_group="u14",
            gender="Male",
            divisions=(DivisionStructure(name="Premier", team_count=1),),
        )
    ]
    write_structure(EVENT_KEY, SCENARIO, structure, base_dir=tmp_path)
    result = is_ready(EVENT_KEY, SCENARIO, base_dir=tmp_path, supabase_client=supabase)
    assert result.ready is True
