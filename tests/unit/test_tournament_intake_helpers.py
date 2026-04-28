"""Unit tests for ``tournament_intake`` pure helpers.

Pins the disabled-mode constant + coercion helper, the canonical/display
gender swap, the cohort grouping/sort/toggle-key contract, and the tint
threshold that drives the green/amber/red strip. Pure helpers — no
Streamlit runtime is required.
"""

from __future__ import annotations

from datetime import date

from src.tournaments.triage import ProjectedTeamState
from tournament_intake import (
    _DISABLED_MODES,
    _build_division_groups,
    _cohort_sort_key,
    _cohort_toggle_key,
    _default_snapshot,
    _display_gender,
    _group_cohorts,
    _resolve_intake_mode,
    _resolve_team_id_master,
    _safe_float,
    _scrape_state_counts,
    _scraper_tint,
    _state_tint_level,
)

# -------- _DISABLED_MODES + _resolve_intake_mode --------------------------


def test_disabled_modes_is_seeding_only():
    assert _DISABLED_MODES == ("seeding",)


def test_resolve_intake_mode_maps_seeding_to_backtest():
    assert _resolve_intake_mode("seeding") == "backtest"


def test_resolve_intake_mode_passes_backtest_through():
    assert _resolve_intake_mode("backtest") == "backtest"


# -------- _display_gender -------------------------------------------------


def test_display_gender_translates_male_to_boys():
    assert _display_gender("Male") == "Boys"


def test_display_gender_translates_female_to_girls():
    assert _display_gender("Female") == "Girls"


def test_display_gender_passes_unknown_through():
    assert _display_gender("Coed") == "Coed"
    assert _display_gender("") == ""


# -------- _scrape_state_counts -------------------------------------------


def _record(state: str | None) -> dict:
    return {"canonical": {"scraper_state": state} if state is not None else {}}


def test_scrape_state_counts_empty_records():
    assert _scrape_state_counts([]) == {
        "alias_written": 0,
        "review_queued": 0,
        "unresolved": 0,
    }


def test_scrape_state_counts_tallies_known_states():
    records = [
        _record("alias_written"),
        _record("alias_written"),
        _record("review_queued"),
        _record("unresolved"),
    ]
    counts = _scrape_state_counts(records)
    assert counts["alias_written"] == 2
    assert counts["review_queued"] == 1
    assert counts["unresolved"] == 1


def test_scrape_state_counts_treats_missing_canonical_as_unresolved():
    records = [{}, {"canonical": None}, _record(None)]
    counts = _scrape_state_counts(records)
    assert counts["unresolved"] == 3


# -------- _scraper_tint --------------------------------------------------


def test_scraper_tint_all_alias_written_is_green_ready():
    records = [_record("alias_written")] * 3
    assert _scraper_tint(records) == ("green", "ready")


def test_scraper_tint_any_review_queued_is_amber():
    records = [
        _record("alias_written"),
        _record("alias_written"),
        _record("review_queued"),
    ]
    assert _scraper_tint(records) == ("amber", "1 review")


def test_scraper_tint_minority_unresolved_is_red_with_count():
    records = [_record("alias_written")] * 4 + [_record("unresolved")]
    assert _scraper_tint(records) == ("red", "1 ext")


def test_scraper_tint_majority_unresolved_is_mostly_ext():
    records = [_record("unresolved")] * 3 + [_record("alias_written")] * 2
    assert _scraper_tint(records) == ("red", "mostly ext")


# -------- _group_cohorts -------------------------------------------------


def test_group_cohorts_empty_records():
    assert _group_cohorts([]) == {}


def test_group_cohorts_normalizes_age_and_gender():
    records = [
        {"cohort_age_group": "U14", "cohort_gender": "Boys"},
        {"cohort_age_group": "u14", "cohort_gender": "Male"},
        {"cohort_age_group": "U15", "cohort_gender": "Girls"},
    ]
    grouped = _group_cohorts(records)
    assert set(grouped) == {("u14", "Male"), ("u15", "Female")}
    assert len(grouped[("u14", "Male")]) == 2
    assert len(grouped[("u15", "Female")]) == 1


def test_group_cohorts_drops_unparseable_age():
    records = [
        {"cohort_age_group": "U14", "cohort_gender": "Boys"},
        {"cohort_age_group": "", "cohort_gender": "Boys"},
        {"cohort_age_group": "varsity", "cohort_gender": "Boys"},
    ]
    grouped = _group_cohorts(records)
    assert set(grouped) == {("u14", "Male")}


# -------- _cohort_sort_key -----------------------------------------------


def test_cohort_sort_key_oldest_to_youngest():
    cohorts = [("u12", "Male"), ("u15", "Male"), ("u14", "Male")]
    assert sorted(cohorts, key=_cohort_sort_key) == [
        ("u15", "Male"),
        ("u14", "Male"),
        ("u12", "Male"),
    ]


def test_cohort_sort_key_female_before_male_within_age():
    cohorts = [("u14", "Male"), ("u14", "Female")]
    assert sorted(cohorts, key=_cohort_sort_key) == [
        ("u14", "Female"),
        ("u14", "Male"),
    ]


# -------- _cohort_toggle_key ---------------------------------------------


def test_cohort_toggle_key_format_is_stable():
    assert _cohort_toggle_key("u14", "Male") == "_cohort_expanded_u14_Male"
    assert _cohort_toggle_key("u19", "Female") == "_cohort_expanded_u19_Female"


# -------- _resolve_team_id_master ----------------------------------------


def test_resolve_team_id_master_prefers_projection():
    projected = ProjectedTeamState(state="resolved", team_id_master="proj_abc")
    registry_row = {"resolved_team_id_master": "reg_xyz"}
    assert _resolve_team_id_master(projected, registry_row) == "proj_abc"


def test_resolve_team_id_master_falls_back_to_registry():
    projected = None
    registry_row = {"resolved_team_id_master": "reg_xyz"}
    assert _resolve_team_id_master(projected, registry_row) == "reg_xyz"


def test_resolve_team_id_master_handles_empty_projection():
    projected = ProjectedTeamState(state="external", team_id_master=None)
    registry_row = {"resolved_team_id_master": "reg_xyz"}
    assert _resolve_team_id_master(projected, registry_row) == "reg_xyz"


def test_resolve_team_id_master_returns_none_when_both_empty():
    assert _resolve_team_id_master(None, {}) is None
    assert _resolve_team_id_master(None, None) is None


# -------- _safe_float ----------------------------------------------------


def test_safe_float_handles_normal_inputs():
    assert _safe_float(1.5) == 1.5
    assert _safe_float("2.0") == 2.0
    assert _safe_float(3) == 3.0


def test_safe_float_returns_none_for_empty_or_unparseable():
    assert _safe_float(None) is None
    assert _safe_float("") is None
    assert _safe_float("not a number") is None
    assert _safe_float([1, 2]) is None


# -------- _state_tint_level ----------------------------------------------


def test_state_tint_level_resolved_is_green():
    assert _state_tint_level("resolved") == "green"


def test_state_tint_level_external_is_amber():
    assert _state_tint_level("external") == "amber"


def test_state_tint_level_blockers_default_red():
    assert _state_tint_level("candidates") == "red"
    assert _state_tint_level("placeholder") == "red"
    assert _state_tint_level("unknown") == "red"
    assert _state_tint_level("not-a-state") == "red"


# -------- _default_snapshot ---------------------------------------------


def test_default_snapshot_uses_day_before_event_start():
    assert _default_snapshot("2026-04-15") == date(2026, 4, 14)


def test_default_snapshot_falls_back_to_today_when_date_missing():
    assert _default_snapshot(None) == date.today()


def test_default_snapshot_falls_back_to_today_on_unparseable_date():
    assert _default_snapshot("not-a-date") == date.today()


# -------- _build_division_groups (resolver wiring) ----------------------


class _StubDivision:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubStructure:
    def __init__(self, names: list[str]) -> None:
        self.divisions = [_StubDivision(n) for n in names]


def test_build_division_groups_explicit_assignment_wins_over_prefix():
    """Operator override-projected ``assigned_division_name`` must beat
    the prefix heuristic when both could match."""
    structure = _StubStructure(["BU14 Premier", "BU14 Champions"])
    records = [
        {"provider_team_id": "pid-1", "bracket_name": "BU14 Premier Phoenix Rising"},
    ]
    team_state = {
        "pid-1": ProjectedTeamState(state="resolved", assigned_division_name="BU14 Champions"),
    }
    groups = _build_division_groups(records, structure, team_state)
    assert groups["BU14 Champions"] == ["pid-1"]
    assert groups["BU14 Premier"] == []


def test_build_division_groups_default_empty_team_state_is_prefix_only():
    """Calls without ``team_state`` (or with an empty mapping) must
    behave identically to the prior prefix-only path — keeps existing
    test/render callers safe even though the resolver is wired in."""
    structure = _StubStructure(["BU14 Premier", "BU14 Champions"])
    records = [
        {"provider_team_id": "pid-1", "bracket_name": "BU14 Premier Phoenix Rising"},
    ]
    groups = _build_division_groups(records, structure)
    assert groups["BU14 Premier"] == ["pid-1"]
    assert groups["BU14 Champions"] == []


def test_build_division_groups_unknown_bracket_falls_back_to_first_division():
    """When neither override nor prefix resolves, the team lands in the
    first division — preserves the prior fallback behavior at this site."""
    structure = _StubStructure(["BU14 Premier", "BU14 Champions"])
    records = [
        {"provider_team_id": "pid-1", "bracket_name": "Unrelated Bracket"},
    ]
    groups = _build_division_groups(records, structure)
    assert groups["BU14 Premier"] == ["pid-1"]


def test_build_division_groups_unstructured_when_no_structure():
    """``structure_for_cohort=None`` short-circuits to a single virtual
    ``_unstructured`` bucket — preserves the "ship before Shell 05" path."""
    records = [{"provider_team_id": "pid-1", "bracket_name": "anything"}]
    groups = _build_division_groups(records, None)
    assert groups == {"_unstructured": ["pid-1"]}
