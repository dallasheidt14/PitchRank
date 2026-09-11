"""Actual-result metrics guard the later Backtest comparison's baseline."""

import json
from dataclasses import replace

import pytest

from src.tournaments.backtest_result_summary import tournament_result_summary
from src.tournaments.gotsport_event_roster import EventRoster, EventRosterTeam
from src.tournaments.gotsport_event_structure import Fixture, ScrapedDivision


def fixture(number="1", home=4, away=0, **changes):
    return replace(Fixture(number, "", "pool", "home", "away", home, away, "10:00 AM", "Field 1",
                           result_status="played"), **changes)


def division(group="10", fixtures=(), age="u12", gender="Male"):
    return ScrapedDivision(group, f"{gender} {age} Gold", (), tuple(fixtures), True, True, (), age, gender)


def roster(*divisions, **changes):
    return replace(EventRoster("51783", (), (), divisions_found=len(divisions), divisions_walked=len(divisions),
                               divisions=tuple(divisions), completed_event=True), **changes)


def linked(number="1", match_id="100", **changes):
    return fixture(number, source_url=f"https://system.gotsport.com/org_event/events/51783/schedules?match={match_id}",
                   **changes)


def test_margin_threshold_zero_draws_and_shootouts():
    summary = tournament_result_summary(roster(division(fixtures=(
        fixture("1", 3, 0), fixture("2", 0, 4), fixture("3", 0, 0),
        fixture("4", 2, 2, home_shootout_score=8, away_shootout_score=3),
    ))))
    assert summary["scored_games"] == 4
    assert summary["total_goal_margin"] == 7
    assert summary["average_goal_margin"] == 1.75
    assert summary["blowout_games"] == 1
    assert summary["blowout_percentage"] == 25.0
    assert summary["excluded_games"] == 0
    assert summary["is_partial"] is False
    assert summary["summary_version"] == 1
    assert summary["blowout_margin"] == 4
    assert summary["score_basis"] == "published_excluding_shootout"
    json.dumps(summary, allow_nan=False)


def test_event_average_and_percentage_weight_games_not_divisions():
    summary = tournament_result_summary(roster(
        division("10", (fixture("1", 8, 0),)),
        division("20", (fixture("1", 0, 0), fixture("2", 0, 0), fixture("3", 0, 0))),
    ))
    assert summary["scored_games"] == 4
    assert summary["average_goal_margin"] == 2.0
    assert summary["blowout_percentage"] == 25.0
    assert summary["by_cohort"][0]["average_goal_margin"] == 2.0
    assert [row["average_goal_margin"] for row in summary["by_division"]] == [8.0, 0.0]


@pytest.mark.parametrize("status", ["forfeit", "cancelled", "postponed", "unplayed", "unrecognized", "unknown", ""])
def test_nonplayed_status_excluded_even_when_stale_numeric_scores_exist(status):
    summary = tournament_result_summary(roster(division(fixtures=(fixture(result_status=status),))))
    assert summary["scored_games"] == 0
    assert summary["excluded_games"] == 1
    assert summary["total_goal_margin"] == 0
    assert summary["average_goal_margin"] is None
    assert summary["blowout_percentage"] is None
    assert summary["exclusion_reasons"] == {status or "unknown": 1}


@pytest.mark.parametrize("field", ["home_score", "away_score"])
@pytest.mark.parametrize("value", [None, -1, True, 4.0, "4"])
def test_each_score_must_be_a_nonnegative_integer(field, value):
    summary = tournament_result_summary(roster(division(fixtures=(fixture(**{field: value}),))))
    assert summary["scored_games"] == 0
    assert summary["exclusion_reasons"] == {"invalid_score": 1}


def test_valid_legacy_scores_count_with_explicit_coverage():
    summary = tournament_result_summary(roster(division(fixtures=(
        fixture("1", 0, 0, result_status="not_captured"),
        fixture("2", 5, 1, result_status="not_captured"),
        fixture("3", None, None, result_status="not_captured"),
    ))))
    assert summary["scored_games"] == 2
    assert summary["legacy_scored_games"] == 2
    assert summary["total_goal_margin"] == 4
    assert summary["excluded_games"] == 1


def test_empty_complete_division_and_partial_capture_remain_explicit():
    empty = tournament_result_summary(roster(division()))
    assert empty["fixture_rows"] == empty["scored_games"] == empty["blowout_games"] == 0
    assert empty["average_goal_margin"] is None
    assert empty["blowout_percentage"] is None
    assert empty["is_partial"] is False
    partial = tournament_result_summary(roster(division(fixtures=(fixture(),)), divisions_found=3))
    assert partial["is_partial"] is True
    assert partial["scored_games"] == 1
    assert partial["by_division"][0]["is_partial"] is True
    assert tournament_result_summary(roster())["is_partial"] is True


def test_identical_rows_deduplicate_by_provider_id_even_if_printed_number_changes():
    summary = tournament_result_summary(roster(division(fixtures=(linked("1"), linked("2")))))
    assert summary["fixture_rows"] == 2
    assert summary["unique_fixtures"] == summary["scored_games"] == summary["blowout_games"] == 1
    assert summary["duplicate_rows"] == 1


def test_plain_division_url_and_match_link_deduplicate_through_unique_local_number():
    plain = replace(linked(), source_url="https://system.gotsport.com/org_event/events/51783/schedules?group=10")
    summary = tournament_result_summary(roster(division(fixtures=(plain, linked()))))
    assert summary["scored_games"] == 1
    assert summary["duplicate_rows"] == 1


def test_shared_printed_number_does_not_merge_distinct_provider_matches():
    summary = tournament_result_summary(roster(division(fixtures=(linked(match_id="100"), linked(match_id="101")))))
    assert summary["scored_games"] == 2
    assert summary["duplicate_rows"] == 0


def test_ambiguous_plain_link_is_excluded_without_guessing_provider_match():
    summary = tournament_result_summary(roster(division(fixtures=(
        linked(match_id="100"), linked(match_id="101"), fixture(),
    ))))
    assert summary["scored_games"] == 2
    assert summary["conflicting_games"] == 1
    assert summary["exclusion_reasons"] == {"ambiguous_identity": 1}


@pytest.mark.parametrize("change", [
    {"home_score": 3}, {"away_score": 1}, {"result_status": "unplayed"},
    {"home_shootout_score": 4}, {"away_shootout_score": 2}, {"home_registration_id": "other"},
])
def test_conflicting_duplicate_is_excluded_in_both_orders(change):
    original = linked()
    altered = replace(original, **change)
    results = [tournament_result_summary(roster(division(fixtures=rows)))
               for rows in ((original, altered), (altered, original))]
    assert results[0] == results[1]
    assert results[0]["scored_games"] == 0
    assert results[0]["excluded_games"] == results[0]["conflicting_games"] == 1
    assert results[0]["duplicate_rows"] == 1
    assert results[0]["exclusion_reasons"] == {"conflicting_results": 1}


def test_legacy_and_modern_duplicate_agree_on_actual_result():
    summary = tournament_result_summary(roster(division(fixtures=(
        linked(result_status="not_captured"), linked(),
    ))))
    assert summary["scored_games"] == 1
    assert summary["legacy_scored_games"] == 0
    assert summary["conflicting_games"] == 0


def test_cross_division_provider_identity_is_counted_once_and_attribution_is_flagged():
    second = replace(linked(), source_url=linked().source_url + "&group=20")
    summary = tournament_result_summary(roster(
        division("10", (linked(),), age="u12"), division("20", (second,), age="u13", gender="Female"),
    ))
    assert summary["fixture_rows"] == 2
    assert summary["unique_fixtures"] == 1
    assert summary["scored_games"] == 0
    assert summary["conflicting_games"] == summary["excluded_games"] == 1
    assert summary["exclusion_reasons"] == {"attribution_conflict": 1}
    assert [row["conflicting_games"] for row in summary["by_division"]] == [1, 1]
    assert [row["conflicting_games"] for row in summary["by_cohort"]] == [1, 1]


def test_match_number_fallback_is_scoped_to_division_and_rematches_are_real_games():
    summary = tournament_result_summary(roster(
        division("10", (fixture("1"), fixture("1"), fixture("2"))),
        division("20", (fixture("1"),)),
    ))
    assert summary["fixture_rows"] == 4
    assert summary["unique_fixtures"] == summary["scored_games"] == 3
    assert summary["duplicate_rows"] == 1


def test_unidentified_rows_remain_visible_and_do_not_inflate_game_totals():
    no_id = fixture(number="", source_url="https://system.gotsport.com/schedules?group=10")
    summary = tournament_result_summary(roster(division(fixtures=(no_id, no_id, linked(number="")))))
    assert summary["fixture_rows"] == 3
    assert summary["unique_fixtures"] == summary["scored_games"] == 1
    assert summary["fixtures_without_identity"] == summary["excluded_games"] == 2
    assert summary["duplicate_rows"] == 0
    assert summary["exclusion_reasons"] == {"missing_identity": 2}


def test_tournament_cohort_and_gender_ignore_team_database_lookup_age():
    team = EventRosterTeam(0, "10", "Boys U12 Gold", "u11", "Male", "Playing up", "home")
    capture = roster(division("10", (fixture(),), age="u12"),
                     division("20", (fixture("1", 1, 0),), age="u12", gender="Female"), teams=(team,))
    summary = tournament_result_summary(capture)
    assert {(row["age_group"], row["gender"], row["total_goal_margin"]) for row in summary["by_cohort"]} == {
        ("u12", "Male", 4), ("u12", "Female", 1),
    }
    assert summary["by_division"][0]["group_id"] == "10"
    assert summary["by_division"][0]["division_label"] == "Male u12 Gold"


def test_unstated_cohorts_stay_unstated_and_known_cohorts_sort_numerically():
    summary = tournament_result_summary(roster(
        division("1", (fixture(),), age=""), division("2", age="u12"), division("3", age="u9"),
    ))
    assert [row["age_group"] for row in summary["by_cohort"]] == ["u9", "u12", ""]
