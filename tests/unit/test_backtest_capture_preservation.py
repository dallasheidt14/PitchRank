"""A repeated fixture row is not proof that its captured evidence survived."""

from dataclasses import replace

import pytest

from src.tournaments.backtest_intake_state import (
    BacktestSnapshot,
    IntakeOverwriteRefused,
    assert_capture_preserved,
    write_snapshot,
)
from src.tournaments.gotsport_event_roster import EventRoster, event_roster_to_dict
from src.tournaments.gotsport_event_structure import Fixture, ScrapedDivision


def fixture(**changes):
    captured = Fixture(
        match_number="7", bracket_label="Final", kind="bracket",
        home_registration_id="100", away_registration_id="101",
        home_score=0, away_score=0, kickoff="10:00 AM", location="Field 1",
        home_label="Alpha", away_label="Bravo", result_text="0 - 0 PKS: 0 - 1",
        home_shootout_score=0, away_shootout_score=1,
        winner_side="away", winner_registration_id="101", result_status="played",
        date_label="May 10, 2025",
        source_url="https://system.gotsport.com/org_event/events/51783/schedules?group=10&match=55",
    )
    return replace(captured, **changes)


def roster(*fixtures):
    division = ScrapedDivision(
        "10", "U12 Boys Gold", (), tuple(fixtures), True, True, (), "u12", "Male"
    )
    return EventRoster(
        "51783", (), (), divisions_found=1, divisions_walked=1,
        divisions=(division,), completed_event=True,
    )


# Each case removes exactly one field, including both sides independently.
# Scores of zero are deliberately the rich baseline, not missing evidence.
@pytest.mark.parametrize(
    "field,missing",
    [
        ("match_number", ""), ("bracket_label", ""), ("kind", "unknown"),
        ("home_registration_id", None), ("away_registration_id", None),
        ("home_score", None), ("away_score", None), ("kickoff", ""), ("location", ""),
        ("home_label", ""), ("away_label", ""), ("result_text", ""),
        ("home_shootout_score", None), ("away_shootout_score", None),
        ("winner_side", ""), ("winner_registration_id", None),
        ("result_status", "not_captured"), ("result_status", "unrecognized"),
        ("result_status", "unplayed"), ("date_label", ""), ("source_url", ""),
    ],
)
def test_same_numbered_fixture_cannot_erase_individual_evidence(field, missing):
    old = fixture()
    with pytest.raises(IntakeOverwriteRefused):
        assert_capture_preserved(roster(old), roster(replace(old, **{field: missing})))


def test_source_match_identity_cannot_downgrade_to_a_division_link():
    old = fixture()
    new = replace(old, source_url=old.source_url.removesuffix("&match=55"))
    with pytest.raises(IntakeOverwriteRefused):
        assert_capture_preserved(roster(old), roster(new))


def test_identified_fixture_allows_nonempty_source_corrections():
    old = fixture()
    corrected = replace(
        old, home_score=1, away_score=1, result_text="1 - 1 PKS: 3 - 2",
        home_shootout_score=3, away_shootout_score=2, winner_side="home",
        winner_registration_id="100", date_label="May 11, 2025", kickoff="11:00 AM",
        location="Field 2", home_label="Alpha FC", bracket_label="Third Place",
    )
    assert_capture_preserved(roster(old), roster(corrected))


def test_a_corrected_draw_can_clear_the_derived_winner():
    old = fixture(home_shootout_score=None, away_shootout_score=None, home_score=0,
                  away_score=1, result_text="0 - 1")
    corrected = replace(old, home_score=1, result_text="1 - 1", winner_side="", winner_registration_id=None)
    assert_capture_preserved(roster(old), roster(corrected))


def test_unique_published_number_allows_a_score_correction_without_a_provider_link():
    old = fixture(source_url="")
    corrected = replace(old, home_shootout_score=2, away_shootout_score=3, result_text="0 - 0 PKS: 2 - 3")
    assert_capture_preserved(roster(old), roster(corrected))


def test_new_provider_match_cannot_replace_an_old_game_with_the_same_printed_number():
    old = fixture()
    replacement = replace(old, source_url=old.source_url.replace("match=55", "match=99"))
    with pytest.raises(IntakeOverwriteRefused):
        assert_capture_preserved(roster(old), roster(replacement))


def test_unnumbered_rows_are_paired_by_evidence_not_list_position():
    first = fixture(match_number="", source_url="")
    second = replace(first, home_registration_id="102", home_label="Charlie", kickoff="11:00 AM")
    assert_capture_preserved(roster(first, second), roster(second, first))


def test_duplicate_printed_numbers_are_paired_without_losing_a_distinct_row():
    first = fixture(source_url="")
    second = replace(first, home_registration_id="102", home_label="Charlie")
    assert_capture_preserved(roster(first, second), roster(second, first))
    with pytest.raises(IntakeOverwriteRefused):
        assert_capture_preserved(roster(first, second), roster(second, second))


def test_distinct_provider_links_disambiguate_duplicate_numbers_during_source_correction():
    first = fixture()
    second = replace(first, home_registration_id="102", home_label="Charlie",
                     source_url=first.source_url.replace("match=55", "match=56"))
    corrected_first = replace(first, match_number="8", home_score=1, away_score=1,
                              result_text="1 - 1 PKS: 0 - 1")
    assert_capture_preserved(roster(first, second), roster(second, corrected_first))


def test_unnumbered_fixture_with_provider_identity_can_receive_a_corrected_result():
    first = fixture(match_number="")
    corrected = replace(first, match_number="8", home_score=1, away_score=1,
                        result_text="1 - 1 PKS: 0 - 1")
    assert_capture_preserved(roster(first), roster(corrected))


def test_duplicate_rows_cannot_reuse_one_rich_fresh_row_to_cover_two_old_rows():
    rich = fixture()
    reduced = replace(rich, result_text="", home_score=None, away_score=None,
                      home_shootout_score=None, away_shootout_score=None,
                      winner_side="", winner_registration_id=None, result_status="not_captured")
    with pytest.raises(IntakeOverwriteRefused):
        assert_capture_preserved(roster(rich, rich), roster(rich, reduced))


def test_matching_can_reassign_a_broad_enrichment_candidate_to_preserve_a_richer_row():
    rich = fixture(source_url="")
    unknown = replace(rich, result_text="", home_score=None, away_score=None,
                      home_shootout_score=None, away_shootout_score=None,
                      winner_side="", winner_registration_id=None, kind="unknown", result_status="not_captured")
    enriched = replace(rich, home_score=2, away_score=2, result_text="2 - 2 PKS: 3 - 4",
                       home_shootout_score=3, away_shootout_score=4)
    assert_capture_preserved(roster(unknown, rich), roster(rich, enriched))


def test_unnumbered_unknown_fixture_can_gain_number_source_identity_and_result():
    rich = fixture()
    unknown = replace(rich, match_number="", kind="unknown", result_text="-",
                      home_score=None, away_score=None, home_shootout_score=None, away_shootout_score=None,
                      winner_side="", winner_registration_id=None, result_status="unplayed",
                      source_url=rich.source_url.removesuffix("&match=55"))
    assert_capture_preserved(roster(unknown), roster(rich))


def test_unknown_fields_can_enrich_but_unnumbered_identity_cannot_be_guessed():
    old = fixture(match_number="", source_url="", home_score=None, away_score=None,
                  kind="unknown", result_status="not_captured")
    assert_capture_preserved(roster(old), roster(replace(old, home_score=0, away_score=0, kind="bracket",
                                                        result_status="played")))
    with pytest.raises(IntakeOverwriteRefused):
        assert_capture_preserved(roster(old), roster(replace(old, home_label="Different team")))


def test_same_row_evidence_loss_preserves_saved_snapshot_and_recovery_bytes(tmp_path, monkeypatch):
    import tournament_intake as app

    original = roster(fixture())
    degraded = roster(fixture(home_score=None))
    key = "gotsport__51783__unknown"
    path = write_snapshot(key, BacktestSnapshot.create(original, ()), base_dir=tmp_path)
    before = path.read_bytes()
    with pytest.raises(IntakeOverwriteRefused):
        write_snapshot(key, BacktestSnapshot.create(degraded, ()), base_dir=tmp_path)
    assert path.read_bytes() == before

    monkeypatch.setattr(app, "reports_dir", lambda: tmp_path)
    app._write_backtest_recovery(original, None)
    recovery_path = app._event_recovery_path("51783", completed_event=True)
    before_recovery = recovery_path.read_bytes()
    app._write_backtest_recovery(degraded, None)
    assert recovery_path.read_bytes() == before_recovery


def test_completed_cli_uses_the_same_evidence_guard(tmp_path):
    from scripts.scrape_event_roster import _write_completed_roster

    path = tmp_path / "last_walk.json"
    _write_completed_roster(path, event_roster_to_dict(roster(fixture())), force=False)
    before = path.read_bytes()
    with pytest.raises(SystemExit):
        _write_completed_roster(path, event_roster_to_dict(roster(fixture(home_score=None))), force=False)
    assert path.read_bytes() == before
