"""Unit tests for ``src.tournaments.reports.compute``.

The fixture builds a minimal scenario layout under ``tmp_path``: an
event metadata file, a registry CSV, and a run dir under
``runs/<run_id>/`` with the auxiliary artifacts Shell 06 emits
(``done.json``, ``run_metadata.json``, ``summary.json``,
``division_recommendations.json``, optionally ``fallbacks.jsonl`` and
``run_overrides_audit.jsonl``). Tests assert exact metric values, exact
risk-flag categories, top-reason ordering, and the run-completion gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.tournaments.reports.compute import (
    LOW_GAMES_THRESHOLD,
    STALE_SNAPSHOT_DAYS,
    ReportCardError,
    compute_report_card,
)
from src.tournaments.reports.schema import RiskFlag
from src.tournaments.storage import (
    EventMetadata,
    TeamRegistryEntry,
    append_override,
    ensure_scenario,
    write_event_metadata,
    write_registry,
)
from src.tournaments.storage._io import append_jsonl, write_json
from src.tournaments.storage.event_key import run_dir
from src.tournaments.storage.schema_version import stamp_schema_version
from src.tournaments.triage import build_override_record

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"
RUN_ID = "u14_boys_20260430T120000_aaaaaaaaaaaa"

DEFAULT_EXTRAS: dict[str, Any] = {
    "capped_gd_limit": 3,
    "balance_score_weights": {"preset_id": "default"},
    "ranking_snapshot_date": "2026-04-26",
    "model_version_pin": "poisson_draw_gate_v1",
}


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _bootstrap(
    base: Path,
    *,
    extras: dict[str, Any] | None = None,
    extra_registry_rows: list[TeamRegistryEntry] | None = None,
    event_start: str = "2026-05-01",
) -> Path:
    """Set up event metadata + registry + the run dir scaffold."""
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
            extras=DEFAULT_EXTRAS if extras is None else extras,
        ),
        base_dir=base,
    )
    rows = [
        TeamRegistryEntry(
            event_team_name="FC Dallas 2012",
            event_age_group="u14",
            event_gender="Boys",
            resolved_gotsport_provider_team_id="pid-1",
            resolved_team_id_master="tim-1",
            in_scope_u10_u19="True",
            event_club_name="FC Dallas",
        ),
        TeamRegistryEntry(
            event_team_name="LUSA 2012 BCSPL",
            event_age_group="u14",
            event_gender="Boys",
            resolved_gotsport_provider_team_id="pid-2",
            resolved_team_id_master="tim-2",
            in_scope_u10_u19="True",
            event_club_name="LUSA",
        ),
        TeamRegistryEntry(
            event_team_name="Tuzos Royals",
            event_age_group="u14",
            event_gender="Boys",
            resolved_gotsport_provider_team_id="pid-3",
            resolved_team_id_master="tim-3",
            in_scope_u10_u19="True",
            event_club_name="Tuzos",
        ),
        TeamRegistryEntry(
            event_team_name="State 48 FC 2012",
            event_age_group="u14",
            event_gender="Boys",
            resolved_gotsport_provider_team_id="pid-4",
            resolved_team_id_master="tim-4",
            in_scope_u10_u19="True",
            event_club_name="State 48 FC",
        ),
    ]
    if extra_registry_rows:
        rows.extend(extra_registry_rows)
    write_registry(EVENT_KEY, SCENARIO, rows, base_dir=base)
    return _build_run_dir(base)


def _build_run_dir(
    base: Path,
    *,
    with_done: bool = True,
    with_metadata: bool = True,
) -> Path:
    run_path = run_dir(EVENT_KEY, SCENARIO, RUN_ID, base_dir=base)
    run_path.mkdir(parents=True, exist_ok=True)
    if with_done:
        write_json(
            run_path / "done.json",
            stamp_schema_version({"run_id": RUN_ID, "promoted_at": "2026-04-30T12:00:00+00:00"}),
        )
    if with_metadata:
        write_json(
            run_path / "run_metadata.json",
            stamp_schema_version(
                {
                    "run_id": RUN_ID,
                    "event_key": EVENT_KEY,
                    "scenario": SCENARIO,
                    "cohort_age_group": "u14",
                    "cohort_gender": "Boys",
                    "event_name": "Phoenix Cup 2026",
                    "started_at": "2026-04-30T12:00:00+00:00",
                    "ended_at": "2026-04-30T12:01:00+00:00",
                }
            ),
        )
    return run_path


def _entrants() -> list[dict[str, Any]]:
    """Four entrants — all with games_played >= LOW_GAMES_THRESHOLD."""
    return [
        {
            "entrant_id": "e1",
            "canonical_team_id": "tim-1",
            "provider_team_id": "pid-1",
            "event_team_name": "FC Dallas 2012",
            "club_name": "FC Dallas",
            "games_played": 12,
            "ranking_status": "Active",
            "actual_division_name": "Super Elite",
            "event_age_group": "u14",
            "event_gender": "Male",
            "power_score": 1700,
        },
        {
            "entrant_id": "e2",
            "canonical_team_id": "tim-2",
            "provider_team_id": "pid-2",
            "event_team_name": "LUSA 2012 BCSPL",
            "club_name": "LUSA",
            "games_played": 8,
            "ranking_status": "Active",
            "actual_division_name": "Super Elite",
            "event_age_group": "u14",
            "event_gender": "Male",
            "power_score": 1650,
        },
        {
            "entrant_id": "e3",
            "canonical_team_id": "tim-3",
            "provider_team_id": "pid-3",
            "event_team_name": "Tuzos Royals",
            "club_name": "Tuzos",
            "games_played": 10,
            "ranking_status": "Active",
            "actual_division_name": "Super Pro",
            "event_age_group": "u14",
            "event_gender": "Male",
            "power_score": 1500,
        },
        {
            "entrant_id": "e4",
            "canonical_team_id": "tim-4",
            "provider_team_id": "pid-4",
            "event_team_name": "State 48 FC 2012",
            "club_name": "State 48 FC",
            "games_played": 9,
            "ranking_status": "Active",
            "actual_division_name": "Super Pro",
            "event_age_group": "u14",
            "event_gender": "Male",
            "power_score": 1480,
        },
    ]


def _default_pool_matches() -> list[dict[str, Any]]:
    """Round-robin among 4 teams = 6 pool matches, varied goal differentials."""
    return [
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e3", "goal_differential": 2},
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e4", "goal_differential": 3},
        {"stage": "Pool", "home_team_id": "e2", "away_team_id": "e3", "goal_differential": 1},
        {"stage": "Pool", "home_team_id": "e2", "away_team_id": "e4", "goal_differential": 2},
        {"stage": "Pool", "home_team_id": "e3", "away_team_id": "e4", "goal_differential": 0},
    ]


def _write_summary(
    run_path: Path,
    *,
    entrants: list[dict[str, Any]] | None = None,
    matches: list[dict[str, Any]] | None = None,
    actual_overrides: dict[str, Any] | None = None,
) -> None:
    entrants = entrants if entrants is not None else _entrants()
    matches = matches if matches is not None else _default_pool_matches()
    n = len(matches)
    one_goal = sum(1 for m in matches if m["goal_differential"] <= 1)
    blow3 = sum(1 for m in matches if m["goal_differential"] >= 3)
    blow5 = sum(1 for m in matches if m["goal_differential"] >= 5)
    avg_gd = sum(m["goal_differential"] for m in matches) / n if n else 0.0
    actual: dict[str, Any] = {
        "actual_game_count": n,
        "average_goal_differential": 2.09,
        "median_goal_differential": 2.0,
        "close_game_rate": 0.22,
        "blowout_3plus_rate": 0.31,
        "blowout_5plus_rate": 0.10,
        "draw_rate": 0.05,
        "divisions": {},
    }
    if actual_overrides:
        actual.update(actual_overrides)
    payload = {
        "event_name": "Phoenix Cup 2026",
        "cohort": {"age_group": "u14", "gender": "Male"},
        "actual_results": actual,
        "optimized_projection": {
            "simulated_schedule": {
                "match_count": n,
                "average_goal_differential": float(avg_gd),
                "median_goal_differential": 1.5,
                "close_game_rate": one_goal / n if n else 0.0,
                "blowout_3plus_rate": blow3 / n if n else 0.0,
                "blowout_5plus_rate": blow5 / n if n else 0.0,
                "draw_rate": sum(1 for m in matches if m["goal_differential"] == 0) / n if n else 0.0,
                "divisions": [{"name": "Super Elite", "matches": matches}],
            }
        },
        "comparison_to_actual": {},
        "entrants": entrants,
        "predictor": {"snapshot_resolution_counts": {}},
        "notes": [],
    }
    write_json(run_path / "summary.json", payload)


def _write_division_recommendations(run_path: Path, rows: list[dict[str, Any]] | None = None) -> None:
    if rows is None:
        rows = [
            {
                "event_team_name": "FC Dallas 2012",
                "canonical_team_name": "FC Dallas 2012",
                "club_name": "FC Dallas",
                "provider_team_id": "pid-1",
                "actual_division": "Super Elite",
                "recommended_division": "Super Pro",
                "move": "move_down",
                "power_score": 1700,
                "ranking_source_team_id": "tim-1",
                "canonical_team_id": "tim-1",
                "ranking_status": "Active",
            },
            {
                "event_team_name": "Tuzos Royals",
                "canonical_team_name": "Tuzos Royals",
                "club_name": "Tuzos",
                "provider_team_id": "pid-3",
                "actual_division": "Super Pro",
                "recommended_division": "Super Pro",
                "move": "stay",
                "power_score": 1500,
                "ranking_source_team_id": "tim-3",
                "canonical_team_id": "tim-3",
                "ranking_status": "Active",
            },
        ]
    write_json(run_path / "division_recommendations.json", rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _flag_categories(flags: tuple[RiskFlag, ...]) -> list[str]:
    return [f.category for f in flags]


def test_compute_report_card_basic_metrics(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    assert rc.event_key == EVENT_KEY
    assert rc.scenario == SCENARIO
    assert rc.run_id == RUN_ID
    assert rc.age_group == "u14"
    assert rc.gender == "Boys"  # registry vocab — not summary's "Male"
    assert rc.event_name == "Phoenix Cup 2026"
    assert len(rc.metrics) == 8

    metric_labels = [m.label for m in rc.metrics]
    assert "Expected avg GD (raw)" == metric_labels[0]
    # 8 metrics, in the locked order; capped GD is metric #2
    assert "capped at 3" in metric_labels[1]


def test_balance_score_actual_is_none_in_v1(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    assert rc.balance_score.actual is None
    assert rc.balance_score.delta is None
    assert rc.balance_score.preset_id == "default"
    # Optimized side: 50*one_goal + 30*(1-blow5) + 10*(1-same_club) + 10*(1-rematch)
    # 6 matches with GDs [1,2,3,1,2,0]: one_goal (GD<=1) count=3 → 3/6, blow5=0,
    # same_club=0 (different clubs), rematch=0.
    expected = 50 * (3 / 6) + 30 * 1.0 + 10 * 1.0 + 10 * 1.0
    assert rc.balance_score.optimized == pytest.approx(expected)


def test_capped_gd_uses_extras_limit(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    matches = [
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e3", "goal_differential": 5},
        {"stage": "Pool", "home_team_id": "e2", "away_team_id": "e4", "goal_differential": 7},
        {"stage": "Pool", "home_team_id": "e3", "away_team_id": "e4", "goal_differential": 0},
    ]
    _write_summary(run_path, matches=matches)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    # capped at 3: clamped values are [1, 3, 3, 0]; mean = 7/4 = 1.75
    capped_metric = next(m for m in rc.metrics if "capped at 3" in m.label)
    assert capped_metric.actual is None
    assert capped_metric.optimized == pytest.approx(1.75)
    assert capped_metric.delta is None


def test_stage_filter_excludes_final_and_third_place(tmp_path: Path):
    """Same-club early-meeting count counts only Pool / Semi Final A / Semi Final B."""
    run_path = _bootstrap(tmp_path)
    entrants = _entrants()
    # Make e1 and e2 same club.
    entrants[0]["club_name"] = "Same Club"
    entrants[1]["club_name"] = "Same Club"
    # e1-e2 in Final stage should NOT count; e1-e2 in Pool should.
    matches = [
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
        {"stage": "Final", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
        {"stage": "Third Place", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
    ]
    _write_summary(run_path, entrants=entrants, matches=matches)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    same_club_metric = next(m for m in rc.metrics if m.label.startswith("Same-club"))
    assert same_club_metric.optimized == 1


def test_intra_event_rematches_pool_only(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    matches = [
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
        {"stage": "Pool", "home_team_id": "e2", "away_team_id": "e1", "goal_differential": 0},  # rematch
        {"stage": "Pool", "home_team_id": "e3", "away_team_id": "e4", "goal_differential": 2},
        {"stage": "Final", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},  # not counted
    ]
    _write_summary(run_path, matches=matches)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    rematch_metric = next(m for m in rc.metrics if m.label.startswith("Intra-event rematches"))
    assert rematch_metric.optimized == 1


def test_low_games_flag_fires_below_threshold(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    entrants = _entrants()
    entrants[0]["games_played"] = LOW_GAMES_THRESHOLD - 1  # 5 games
    _write_summary(run_path, entrants=entrants)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)

    low_games_flags = [f for f in rc.risk_flags if f.category == "low_games"]
    assert len(low_games_flags) == 1
    assert low_games_flags[0].affected_teams == ("FC Dallas 2012",)


def test_stale_snapshot_boundary(tmp_path: Path):
    """At the exact threshold (= 7 days) → no flag; > 7 days → flag."""
    extras = {**DEFAULT_EXTRAS, "ranking_snapshot_date": "2026-04-24"}  # exactly 7 days before 2026-05-01
    run_path = _bootstrap(tmp_path, extras=extras)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "stale_ranking_snapshot" not in _flag_categories(rc.risk_flags)


def test_stale_snapshot_fires_above_threshold(tmp_path: Path):
    extras = {**DEFAULT_EXTRAS, "ranking_snapshot_date": "2026-04-23"}  # 8 days before 2026-05-01
    run_path = _bootstrap(tmp_path, extras=extras)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    stale = [f for f in rc.risk_flags if f.category == "stale_ranking_snapshot"]
    assert len(stale) == 1
    assert "8 days" in stale[0].message


def test_snapshot_freshness_unknown_when_no_event_start(tmp_path: Path):
    extras = dict(DEFAULT_EXTRAS)
    run_path = _bootstrap(tmp_path, extras=extras, event_start=None)  # type: ignore[arg-type]
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "snapshot_freshness_unknown" in _flag_categories(rc.risk_flags)


def test_extras_none_uses_defaults(tmp_path: Path):
    run_path = _bootstrap(tmp_path, extras=None)
    # extras=None on the meta is the "no extras" case; helper above passes
    # DEFAULT_EXTRAS when extras is None, so override here directly.
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
            extras=None,
        ),
        base_dir=tmp_path,
    )
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    # Should not raise on missing capped_gd_limit / preset_id; both default.
    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    capped_metric = next(m for m in rc.metrics if "capped at" in m.label)
    assert "capped at 3" in capped_metric.label  # default limit
    # event_start exists but ranking_snapshot_date is missing → freshness_unknown
    assert "snapshot_freshness_unknown" in _flag_categories(rc.risk_flags)


def test_unsupported_balance_score_preset_raises(tmp_path: Path):
    extras = {
        **DEFAULT_EXTRAS,
        "balance_score_weights": {"preset_id": "experimental_v2"},
    }
    run_path = _bootstrap(tmp_path, extras=extras)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    with pytest.raises(ValueError, match="Unsupported balance_score_weights"):
        compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)


def test_no_early_meetings_forces_zero_rates_and_flags(tmp_path: Path):
    """All-Final cohort: no Pool / Semi early-meeting matches → flag fires."""
    run_path = _bootstrap(tmp_path)
    matches = [
        {"stage": "Final", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
    ]
    _write_summary(run_path, matches=matches)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "no_early_meetings" in _flag_categories(rc.risk_flags)


def test_external_no_override_flag(tmp_path: Path):
    """An entrant that's been mark_external'd without a recompute_medians cohort
    override fires ``external_no_override``."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        build_override_record(
            ts="2026-04-29T10:00:00+00:00",
            actor="dallas@pitchrank.io",
            scope="team",
            type="mark_external",
            team_ref="pid-1",
            before={},
            after={},
            reason="external club",
        ),
        base_dir=tmp_path,
    )

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    cats = _flag_categories(rc.risk_flags)
    assert "external_no_override" in cats
    assert "external_with_assumed_median" not in cats


def test_external_with_assumed_median_flag(tmp_path: Path):
    """Adding a recompute_medians cohort override flips external flag."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        build_override_record(
            ts="2026-04-29T10:00:00+00:00",
            actor="dallas@pitchrank.io",
            scope="team",
            type="mark_external",
            team_ref="pid-1",
            before={},
            after={},
            reason="external club",
        ),
        base_dir=tmp_path,
    )
    append_override(
        EVENT_KEY,
        SCENARIO,
        build_override_record(
            ts="2026-04-29T10:01:00+00:00",
            actor="dallas@pitchrank.io",
            scope="cohort",
            type="recompute_medians",
            team_ref="u14_Boys",
            before={"medians_by_division": {}},
            after={"medians_by_division": {"Super Elite": 1700.0}},
            reason="recompute",
        ),
        base_dir=tmp_path,
    )

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    cats = _flag_categories(rc.risk_flags)
    assert "external_with_assumed_median" in cats
    assert "external_no_override" not in cats


def test_placeholder_match_flag(tmp_path: Path):
    """Entrant whose name matches ``unknown_<provider_team_id>`` fires placeholder."""
    run_path = _bootstrap(tmp_path)
    entrants = _entrants()
    entrants[0]["event_team_name"] = "unknown_pid-1"
    _write_summary(run_path, entrants=entrants)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "placeholder_match" in _flag_categories(rc.risk_flags)


def test_placeholder_helper_short_circuits_on_empty_pid(tmp_path: Path):
    """Empty provider_team_id with name ``unknown_`` does NOT fire placeholder."""
    run_path = _bootstrap(tmp_path)
    entrants = _entrants()
    # First entrant: empty pid + name "unknown_". Should NOT fire placeholder.
    entrants[0]["provider_team_id"] = ""
    entrants[0]["event_team_name"] = "unknown_"
    _write_summary(run_path, entrants=entrants)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "placeholder_match" not in _flag_categories(rc.risk_flags)


def test_orphan_override_flag_fires_for_genuine_orphan(tmp_path: Path):
    """An override whose team_ref isn't in the registry fires the orphan flag."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        build_override_record(
            ts="2026-04-29T10:00:00+00:00",
            actor="dallas@pitchrank.io",
            scope="team",
            type="mark_external",
            team_ref="pid-orphan-99",
            before={},
            after={"event_team_name": "Ghost Team FC"},
            reason="orphan",
        ),
        base_dir=tmp_path,
    )

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    orphan_flags = [f for f in rc.risk_flags if f.category == "rescrape_orphan_override"]
    assert len(orphan_flags) == 1
    assert orphan_flags[0].affected_teams == ("Ghost Team FC",)


def test_manual_add_override_does_not_fire_orphan_flag(tmp_path: Path):
    """``manual_add`` overrides have ``team_ref`` starting with ``manual_`` and
    are excluded from orphan detection."""
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        build_override_record(
            ts="2026-04-29T10:00:00+00:00",
            actor="dallas@pitchrank.io",
            scope="team",
            type="manual_add",
            team_ref="manual_xyz",
            before={},
            after={
                "event_team_name": "Manual Team",
                "cohort_age_group": "u14",
                "cohort_gender": "Boys",
                "state": "external",
            },
            reason="manual entry",
        ),
        base_dir=tmp_path,
    )

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "rescrape_orphan_override" not in _flag_categories(rc.risk_flags)


def test_cohort_scoping_no_u17_team_in_u14_run(tmp_path: Path):
    """Registry has both U14 boys and U17 girls; U14 run should not surface
    U17 teams in any flag."""
    extra = TeamRegistryEntry(
        event_team_name="U17 Other Team",
        event_age_group="u17",
        event_gender="Girls",
        resolved_gotsport_provider_team_id="pid-u17",
        resolved_team_id_master="tim-u17",
        in_scope_u10_u19="True",
        event_club_name="Other Club",
    )
    run_path = _bootstrap(tmp_path, extra_registry_rows=[extra])
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    for flag in rc.risk_flags:
        assert "U17 Other Team" not in (flag.message + " ".join(flag.affected_teams))


def test_missing_done_json_raises_report_card_error(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    (run_path / "done.json").unlink()
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    with pytest.raises(ReportCardError, match="not completed"):
        compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)


def test_missing_run_metadata_raises_report_card_error(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    (run_path / "run_metadata.json").unlink()
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    with pytest.raises(ReportCardError, match="run_metadata.json"):
        compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)


def test_top_reasons_ordered_by_magnitude(tmp_path: Path):
    """The largest absolute delta lands first."""
    run_path = _bootstrap(tmp_path)
    # Force a big drop in 5+ blowout (1.0 → 0.0) so it dominates.
    matches = [
        {"stage": "Pool", "home_team_id": "e1", "away_team_id": "e2", "goal_differential": 1},
    ]
    actual_overrides = {
        "actual_game_count": 1,
        "average_goal_differential": 5.0,
        "close_game_rate": 0.0,
        "blowout_3plus_rate": 1.0,
        "blowout_5plus_rate": 1.0,
    }
    _write_summary(run_path, matches=matches, actual_overrides=actual_overrides)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    # Magnitudes (rates as percentage-point delta, gd as raw):
    #   blowout_5plus: |0 - 1| = 1.0
    #   one_goal_rate: |1 - 0| = 1.0   (tied with blowout_5plus)
    #   avg_gd: |5 - 1| = 4.0
    # Expected order: avg_gd, blowout_5plus, one_goal_rate
    # (Tied blowout_5plus / one_goal: insertion-order in TOP_REASON_TEMPLATES
    # places blowout_5plus before one_goal_rate.)
    assert len(rc.top_reasons) >= 3
    assert "Tightened average goal differential" in rc.top_reasons[0].text
    assert "5+ goal mismatches" in rc.top_reasons[1].text
    assert "one-goal games" in rc.top_reasons[2].text


def test_team_movements_filtered_to_non_stay(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    # Fixture writes 1 move_down + 1 stay; only the move_down survives.
    assert len(rc.team_movements) == 1
    assert rc.team_movements[0].move == "move_down"
    assert rc.team_movements[0].team_name == "FC Dallas 2012"


def test_fallbacks_jsonl_emits_one_flag_per_row(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    append_jsonl(
        run_path / "fallbacks.jsonl",
        stamp_schema_version(
            {
                "team_name": "FC Dallas 2012",
                "fallback_kind": "synthetic_snapshot_fallback",
                "raw_note": "FC Dallas 2012: no point-in-time snapshots found",
            }
        ),
    )

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    fallback_flags = [f for f in rc.risk_flags if f.category == "snapshot_fallback"]
    assert len(fallback_flags) == 1
    assert fallback_flags[0].affected_teams == ("FC Dallas 2012",)


def test_run_overrides_audit_loaded_into_report_card(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)
    append_jsonl(
        run_path / "run_overrides_audit.jsonl",
        stamp_schema_version(
            {
                "ts": "2026-04-29T10:00:00+00:00",
                "actor": "dallas@pitchrank.io",
                "scope": "team",
                "type": "accept_match",
                "team_ref": "pid-1",
                "before": {},
                "after": {},
                "reason": "accepted",
                "run_id": RUN_ID,
                "applied_at": "2026-04-30T12:00:00+00:00",
                "delta_balance_score": None,
            }
        ),
    )

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert len(rc.override_audit) == 1
    assert rc.override_audit[0].record["type"] == "accept_match"


def test_coach_data_unavailable_flag_always_emitted(tmp_path: Path):
    run_path = _bootstrap(tmp_path)
    _write_summary(run_path)
    _write_division_recommendations(run_path)

    rc = compute_report_card(EVENT_KEY, SCENARIO, RUN_ID, base_dir=tmp_path)
    assert "coach_data_unavailable" in _flag_categories(rc.risk_flags)
