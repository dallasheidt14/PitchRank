"""Completed-event capture identity, preservation and tournament-cohort totals."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.tournaments.backtest_intake_state import (
    BacktestSnapshot,
    CaptureVerification,
    CohortDecision,
    DivisionReview,
    IntakeOverwriteRefused,
    effective_roster,
    entrant_key,
    read_snapshot,
    structure_hash,
    tournament_totals,
    write_snapshot,
)
from src.tournaments.gotsport_event_roster import EventRoster, EventRosterTeam
from src.tournaments.gotsport_event_structure import Fixture, Pool, PoolMember, ScrapedDivision
from src.tournaments.roster_resolver import ResolvedTeam


def sample_snapshot(event_id="51783", *, generation="capture-one"):
    teams = tuple(
        EventRosterTeam(index, group, label, "u11", gender, name, registration, provider,
                        published_age_group=age)
        for index, group, label, gender, name, registration, provider, age in (
            (0, "10", "BU12 Gold", "Male", "Alpha", "100", "501", "u12"),
            (1, "10", "BU12 Gold", "Male", "Bravo", "101", None, "u12"),
            (2, "20", "GU13 Silver", "Female", "Charlie", "102", "502", "u13"),
        )
    )
    fixture = Fixture("7", "Final", "bracket", "100", "101", 2, 2, "10:00 AM", "Field 1",
                      home_label="Alpha", away_label="Bravo", result_text="2 (4) - 2 (3)",
                      home_shootout_score=4, away_shootout_score=3, winner_side="home",
                      winner_registration_id="100", result_status="played", date_label="May 10, 2025")
    divisions = (
        ScrapedDivision("10", "BU12 Gold",
                        (Pool("A", "Bracket A", (PoolMember("100", "Alpha", 1), PoolMember("101", "Bravo", 2))),),
                        (fixture,), True, True, (), "u12", "Male"),
        ScrapedDivision("20", "GU13 Silver", (Pool("B", "Bracket B", (PoolMember("102", "Charlie", 1),)),),
                        (), True, True, (), "u13", "Female"),
    )
    roster = EventRoster(event_id, teams, (), divisions_found=2, divisions_walked=2, divisions=divisions,
                         completed_event=True, event_name="Spring Invitational", event_start_date="2025-05-10",
                         event_end_date="2025-05-11", event_season_year=2025)
    resolved = (ResolvedTeam(0, "gotsport_id", "canonical-a", "501"), ResolvedTeam(1, "unresolved"),
                ResolvedTeam(2, "review", candidates=({"team_id_master": "candidate-c"},)))
    return BacktestSnapshot(roster, resolved, generation, "2026-09-11T10:00:00+00:00")


def test_snapshot_round_trip_preserves_all_divisions_entrants_scores_and_reviews(tmp_path):
    snapshot = sample_snapshot()
    review = DivisionReview("10", structure_hash(snapshot.roster.divisions[0]), "Top two advance", checked=True)
    snapshot = replace(snapshot, reviews=(review,))

    write_snapshot("gotsport__51783__2025", snapshot, base_dir=tmp_path)
    loaded = read_snapshot("gotsport__51783__2025", base_dir=tmp_path)

    assert loaded == snapshot
    assert len(loaded.roster.teams) == 3
    assert len(loaded.roster.divisions) == 2
    assert loaded.roster.divisions[0].fixtures[0].home_shootout_score == 4
    assert loaded.roster.divisions[0].fixtures[0].date_label == "May 10, 2025"
    assert loaded.resolved[2].candidates == ({"team_id_master": "candidate-c"},)


def test_optional_verification_and_sourced_cohort_decision_round_trip(tmp_path):
    snapshot = sample_snapshot()
    decision = CohortDecision("10", "u12/u13", "Male", "Published combined bracket", "https://example.test")
    verification = CaptureVerification(("10", "20"), (1, 2, 2), "2026-09-11T12:00:00+00:00", True)
    snapshot = replace(snapshot, cohort_decisions=(decision,), verification=verification)

    write_snapshot("gotsport__51783__2025", snapshot, base_dir=tmp_path)
    loaded = read_snapshot("gotsport__51783__2025", base_dir=tmp_path)

    assert loaded.cohort_decisions == (decision,)
    assert loaded.verification == verification
    effective = effective_roster(loaded)
    assert effective.divisions[0].published_age_group == "u12/u13"
    assert effective.teams[0].published_age_group == "u12/u13"


def test_tournament_totals_use_entered_age_and_gender_with_multidivision_registrations_and_unknowns():
    snapshot = sample_snapshot()
    roster = snapshot.roster
    other_cohort = replace(roster.teams[0], source_index=3, group_id="20", division_label="GU13 Silver")
    duplicate_entry = replace(roster.teams[0], source_index=4)
    unknowns = tuple(replace(roster.teams[0], source_index=index, group_id="missing", registration_id="",
                             published_age_group="", gender="") for index in (5, 6))
    roster = replace(roster, teams=roster.teams + (other_cohort, duplicate_entry) + unknowns)

    totals = tournament_totals(roster)

    assert totals["total_teams"] == 5
    assert totals["division_entries"] == 6
    assert totals["cohort_entries"] == 6
    assert totals["cohorts"] == [
        {"Tournament cohort": "U12", "Gender": "Boys", "Teams": 2},
        {"Tournament cohort": "U13", "Gender": "Girls", "Teams": 2},
        {"Tournament cohort": "Not stated", "Gender": "Not stated", "Teams": 2},
    ]


def test_missing_registration_totals_use_stable_source_entries_without_inventing_provider_ids():
    snapshot = sample_snapshot()
    first = replace(snapshot.roster.teams[0], registration_id="", provider_team_id=None,
                    source_entry_key="source:10:pool-a:alpha")
    repeated = replace(first, source_index=4)
    distinct = replace(first, source_index=5, source_entry_key="source:10:pool-b:alpha")
    roster = replace(snapshot.roster, teams=(first, repeated, distinct))

    totals = tournament_totals(roster)

    assert entrant_key(first) == entrant_key(repeated) == "source:10:pool-a:alpha"
    assert totals["total_teams"] == 2
    assert totals["unidentified_teams"] == 2
    assert totals["division_entries"] == 2
    assert totals["cohorts"] == [{"Tournament cohort": "U12", "Gender": "Boys", "Teams": 2}]
    assert all(team.registration_id == "" and team.provider_team_id is None for team in roster.teams)


def test_a_smaller_probe_cannot_replace_a_saved_full_capture(tmp_path):
    original = sample_snapshot()
    key = "gotsport__51783__2025"
    path = write_snapshot(key, original, base_dir=tmp_path)
    before = path.read_bytes()
    smaller = replace(original, roster=replace(original.roster, teams=original.roster.teams[:2],
                                               divisions=original.roster.divisions[:1], divisions_walked=1),
                      resolved=original.resolved[:2], limit_groups=1)

    with pytest.raises(IntakeOverwriteRefused):
        write_snapshot(key, smaller, base_dir=tmp_path)

    assert path.read_bytes() == before


def test_an_empty_division_is_not_discarded_by_a_later_smaller_capture(tmp_path):
    original = sample_snapshot()
    original = replace(original, roster=replace(original.roster, teams=original.roster.teams[:2]),
                       resolved=original.resolved[:2])
    key = "gotsport__51783__2025"
    path = write_snapshot(key, original, base_dir=tmp_path)
    before = path.read_bytes()
    smaller = replace(original, roster=replace(original.roster, divisions=original.roster.divisions[:1],
                                               divisions_found=1, divisions_walked=1))

    with pytest.raises(IntakeOverwriteRefused):
        write_snapshot(key, smaller, base_dir=tmp_path)

    assert path.read_bytes() == before


def test_capture_dry_run_creates_nothing_and_wrong_event_is_refused(tmp_path):
    snapshot = sample_snapshot()
    write_snapshot("gotsport__51783__2025", snapshot, base_dir=tmp_path, dry_run=True)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError, match="another event"):
        write_snapshot("gotsport__99999__2025", snapshot, base_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("loss", ["pool_member", "fixtures", "source_only_team"])
def test_recovery_preserves_richer_incomplete_captures(tmp_path, monkeypatch, loss):
    import tournament_intake as app

    original = replace(sample_snapshot().roster, divisions_unreadable=1)
    source_only = replace(original.teams[0], source_index=3, registration_id="",
                          source_entry_key="pool:10:A:3", provider_team_id=None)
    original = replace(original, teams=original.teams + (source_only,))
    monkeypatch.setattr(app, "reports_dir", lambda: tmp_path)
    app._write_backtest_recovery(original, None)
    path = app._event_recovery_path(original.event_id, completed_event=True)
    before = path.read_bytes()
    division = original.divisions[0]
    if loss == "pool_member":
        changed_pool = replace(division.pools[0], members=division.pools[0].members[:1])
        division = replace(division, pools=(changed_pool,))
    elif loss == "fixtures":
        division = replace(division, fixtures=(), fixtures_readable=False)
    reduced = replace(original, divisions=(division,) + original.divisions[1:])
    if loss == "source_only_team":
        reduced = replace(reduced, teams=reduced.teams[:-1])

    app._write_backtest_recovery(reduced, None)

    assert path.read_bytes() == before
    recovered, limit = app._recovered_walk(original.event_id, completed_event=True)
    assert recovered == original
    assert limit is None


def test_future_recovery_schema_is_not_loaded_or_overwritten(tmp_path, monkeypatch):
    import tournament_intake as app

    monkeypatch.setattr(app, "reports_dir", lambda: tmp_path)
    roster = sample_snapshot().roster
    path = app._event_recovery_path(roster.event_id, completed_event=True)
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 999}', encoding="utf-8")
    assert app._recovered_walk(roster.event_id, completed_event=True) is None
    app._write_backtest_recovery(roster, None)
    assert path.read_text(encoding="utf-8") == '{"schema_version": 999}'


@pytest.mark.parametrize("empty", [False, True])
def test_backtest_offers_saved_structure_even_with_no_additional_teams(monkeypatch, empty):
    import tournament_intake as app

    saved = sample_snapshot()
    current = replace(saved, roster=replace(saved.roster, divisions=()))
    state = {app._BACKTEST_KEYS.snapshot: current}
    if empty:
        saved = replace(saved, roster=replace(saved.roster, teams=()), resolved=())
        state = {}
    labels = []
    monkeypatch.setattr(app, "_recovered_walk", lambda *args, **kwargs: (saved.roster, None))
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state=state, caption=lambda *args: None,
                                                  button=lambda label, **kwargs: labels.append(label)))

    app._render_recovered_walk("https://system.gotsport.com/org_event/events/51783", None,
                               in_progress=False, keys=app._BACKTEST_KEYS)

    assert labels == ["Load the walk already paid for"]


def test_same_named_roster_from_another_capture_cannot_replace_matching_outcomes():
    current = sample_snapshot()
    previous = sample_snapshot("52975", generation="previous-event")
    previous = replace(previous, roster=replace(previous.roster, teams=tuple(
        replace(team, registration_id="old-" + team.registration_id) for team in previous.roster.teams
    )))
    assert current.parsed.rows == previous.parsed.rows

    with pytest.raises(ValueError, match="capture|generation"):
        current.with_resolution(previous.parsed, previous.resolved, generation=previous.generation)


@pytest.mark.parametrize("stop_after_publication", [False, True])
def test_interrupted_parking_keeps_event_identity_structure_and_results_together(monkeypatch, stop_after_publication):
    import tournament_intake as app

    class Interrupted(BaseException):
        pass

    class InterruptibleState(dict):
        def __setitem__(self, key, value):
            if key == app._BACKTEST_KEYS.snapshot:
                if not stop_after_publication:
                    raise Interrupted()
                super().__setitem__(key, value)
                raise Interrupted()
            super().__setitem__(key, value)

    old = sample_snapshot("52975", generation="old")
    new = sample_snapshot()
    state = InterruptibleState({app._BACKTEST_KEYS.snapshot: old, "_seeding_result": "untouched"})
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(app, "_write_backtest_recovery", lambda *args: None)
    monkeypatch.setattr(app, "resolve_master_ids", lambda *args, **kwargs: ({"501": "new-team-id"}, ()))

    with pytest.raises(Interrupted):
        app._park_event_roster("https://system.gotsport.com/org_event/events/51783", new.roster, None, None,
                               keys=app._BACKTEST_KEYS)

    captured = state[app._BACKTEST_KEYS.snapshot]
    assert captured.roster.event_id == ("51783" if stop_after_publication else "52975")
    assert captured.roster == (new.roster if stop_after_publication else old.roster)
    assert captured.resolved[0].team_id_master == ("new-team-id" if stop_after_publication else "canonical-a")
    assert state["_seeding_result"] == "untouched"


@pytest.mark.parametrize("replace_generation_during_lookup", [False, True])
def test_backtest_name_lookup_uses_current_capture_and_discards_obsolete_completion(
    monkeypatch, replace_generation_during_lookup
):
    import tournament_intake as app
    from src.tournaments import event_roster_intake

    current = sample_snapshot(generation="current")
    stale = sample_snapshot("52975", generation="stale")
    stale = replace(stale, resolved=tuple(replace(item, provider_team_id="old-id") for item in stale.resolved))
    next_capture = sample_snapshot("60000", generation="newer")
    state = {app._BACKTEST_KEYS.snapshot: current, app._BACKTEST_KEYS.result_event_id: "52975",
             "_seeding_result": "untouched"}
    observed = []
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state=state, spinner=lambda *args: nullcontext()))
    monkeypatch.setattr(app, "_seeding_merge_resolver", lambda client: SimpleNamespace(version="ok"))
    monkeypatch.setattr(app, "_seeding_provider_id_lookup", lambda client: lambda value: None)
    monkeypatch.setattr(event_roster_intake, "make_historical_name_lookup", lambda *args: lambda *args: [])

    def finish_lookup(parsed, resolved, **kwargs):
        observed.append((parsed, resolved, kwargs["historical_context"]))
        if replace_generation_during_lookup:
            state[app._BACKTEST_KEYS.snapshot] = next_capture
        return tuple(replace(item, team_id_master="this-capture-match") for item in resolved)

    monkeypatch.setattr(app, "resolve_unlinked", finish_lookup)
    app._run_seeding_name_lookup(stale.parsed, stale.resolved, None, keys=app._BACKTEST_KEYS)

    assert observed == [(current.parsed, current.resolved, True)]
    if replace_generation_during_lookup:
        assert state[app._BACKTEST_KEYS.snapshot] is next_capture
    else:
        assert state[app._BACKTEST_KEYS.snapshot].roster.event_id == "51783"
        assert state[app._BACKTEST_KEYS.snapshot].resolved[0].team_id_master == "this-capture-match"
        assert state[app._BACKTEST_KEYS.result_event_id] == "51783"
    assert state["_seeding_result"] == "untouched"
