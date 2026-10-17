"""The merge decider's band check reads a band in every spelling, and only a band: a name
holding one against a name without one goes to a person, and a season tag, a club number or
two years written apart is no band."""

import os
import sys
from collections import Counter

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.decide_team_merges import decide, states_a_band  # noqa: E402

MERGE_ID, KEEP_ID = "mmmmmmmm-0000-4000-8000-000000000001", "kkkkkkkk-0000-4000-8000-000000000002"
ONE_SIDED = "a two-year band on one side only, visible in the registered name"
RE_REGISTRATION = "same birth year, schedules never overlap — a re-registration"


def judge(merge_name, keep_name, age_group="u19", merge_original=None, keep_original=None):
    """Last season's row against this season's: no shared date, opponent or season, so a pair
    whose names resolve to one birth-year set merges unless the band check holds it."""

    def row(team_id, name, original=None):
        return {
            "team_id_master": team_id,
            "team_name": name,
            "team_name_original": original or name,
            "club_name": "Rush Soccer",
            "state_code": "CO",
            "gender": "Male",
            "is_deprecated": False,
        }

    ev = {
        "expanded": {MERGE_ID: [MERGE_ID], KEEP_ID: [KEEP_ID]},
        "canonical": lambda tid: tid,
        "games": {MERGE_ID: [("2025-10-04", "opp-last-season")], KEEP_ID: [("2026-09-12", "opp-this-season")]},
        "aliases": {MERGE_ID: Counter({"gotsport": 1}), KEEP_ID: Counter({"gotsport": 1})},
        "teams": {
            MERGE_ID: row(MERGE_ID, merge_name, merge_original),
            KEEP_ID: row(KEEP_ID, keep_name, keep_original),
        },
    }
    pair = {
        "merge_id": MERGE_ID,
        "keep_id": KEEP_ID,
        "merge_name": merge_name,
        "keep_name": keep_name,
        "age_group": age_group,
        "gender": "male",
    }
    decision = decide(pair, ev)
    return decision["verdict"], decision["why"]


def test_an_en_dash_band_against_a_u19_label_goes_to_review():
    assert judge("Rush B08–09 Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_band_with_a_four_digit_second_year_goes_to_review():
    assert judge("Rush 09/2008 Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_four_digit_pair_goes_to_review():
    assert judge("Rush 2009/2008 Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_band_with_an_apostrophe_s_goes_to_review():
    assert judge("Rush 2008/09's Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_four_digit_year_pairs_with_any_year_after_it():
    assert judge("Rush B2007/2009 Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_gender_letter_marks_a_two_digit_pair():
    assert judge("Rush B07–09 Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_trailing_gender_letter_marks_a_two_digit_pair():
    assert judge("Rush 07–09B Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_an_apostrophe_marks_a_two_digit_pair():
    assert judge("Rush '07–'09 Red", "Rush U19 Red") == ("REVIEW", ONE_SIDED)


def test_a_band_after_a_squad_number_is_read():
    assert judge("Rush Elite 10 – 14–15 Red", "Rush 2015 Red", age_group="u12") == ("REVIEW", ONE_SIDED)


def test_the_merge_records_band_is_read_from_its_registered_name():
    assert judge("Rush U19 Red", "Rush U19 Red", merge_original="Rush B08–09 Red") == ("REVIEW", ONE_SIDED)


def test_the_keep_records_band_is_read_from_its_registered_name():
    assert judge("Rush 2014 Red", "Rush U13 Red", age_group="u13", keep_original="Rush B13/14 Red") == (
        "REVIEW",
        ONE_SIDED,
    )


def test_a_u_age_band_counts_as_a_band():
    assert judge("Rush 2014 Red", "Rush U13/14 Red", age_group="u13") == ("REVIEW", ONE_SIDED)


def test_a_u_age_range_without_a_second_u_counts_as_a_band():
    assert judge("Rush 2018 Red", "Rush U9/10 Red", age_group="u9") == ("REVIEW", ONE_SIDED)


def test_a_season_tag_does_not_cancel_a_band():
    assert judge("Rush B2008/2009 Red", "Rush U19 Red (26/27)") == ("REVIEW", ONE_SIDED)


def test_a_season_tag_does_not_hold_a_re_registration():
    assert judge("Rush 2014 Red", "Rush 2014 Red 25/26", age_group="u13") == ("MERGE", RE_REGISTRATION)


def test_years_written_apart_are_not_a_band():
    assert judge("Rush B08/09 Red", "Rush (est. 2009) B2008 Red") == ("REVIEW", ONE_SIDED)


def test_a_squad_number_beside_a_year_is_not_a_band():
    assert judge("Rush B08/09 Red", "Rush Elite 11 - 2008 (est. 2009) Red") == ("REVIEW", ONE_SIDED)


def test_a_club_number_joined_to_a_year_is_not_a_band():
    assert judge("Rush 2014 Red", "Rush T11 - 2014 Red", age_group="u13") == ("MERGE", RE_REGISTRATION)


def test_a_club_number_beside_a_year_is_not_a_band():
    assert judge("Rush 2014 Red", "Rush R45-14G Red", age_group="u13") == ("MERGE", RE_REGISTRATION)


def test_a_band_after_a_club_number_is_read():
    assert judge("Rush 2017 Red", "Rush SSE90 - 16–17 Red", age_group="u10") == ("REVIEW", ONE_SIDED)


def test_a_club_number_dashed_onto_a_marked_year_is_not_a_band():
    assert judge("Rush 2013 Red", "Rush CF10 – '13B Red", age_group="u14") == ("MERGE", RE_REGISTRATION)


def test_a_letter_glued_to_a_run_stays_glued():
    assert judge("RB10 B10/13 Red", "RB10/2013 (est. 2010) Red", age_group="u16") == ("REVIEW", ONE_SIDED)


def test_a_curly_apostrophe_band_counts_as_a_band():
    assert judge("Rush 2013 Red", "Rush 2013 Red", age_group="u14", merge_original="Rush ’12–’13 Red") == (
        "REVIEW",
        ONE_SIDED,
    )


def test_a_squad_number_after_a_u_age_is_not_a_band():
    assert judge("Rush 2016 Red", "Rush U11-2 Red", age_group="u11") == ("MERGE", RE_REGISTRATION)


def test_a_game_format_is_not_a_u_age():
    assert judge("Rush 2014 Red", "Rush U13/11 v 11 Red", age_group="u13") == ("MERGE", RE_REGISTRATION)


def test_one_band_spelled_two_ways_merges():
    assert judge("Rush B2015/2016 Red", "Rush B15/16 Red", age_group="u11") == ("MERGE", RE_REGISTRATION)


def test_a_single_year_against_its_u_label_still_merges():
    assert judge("Rush 2014 Red", "Rush U13 Red", age_group="u13") == ("MERGE", RE_REGISTRATION)


def test_one_year_on_each_side_still_merges():
    assert judge("Rush 2014 Red", "Rush B2014 Red", age_group="u13") == ("MERGE", RE_REGISTRATION)


def test_past_the_scan_limit_only_the_band_regex_reads():
    padding = " x" * 100
    assert (states_a_band("Rush 08/09 Red" + padding), states_a_band("Rush U9/10 Red" + padding)) == (True, False)
