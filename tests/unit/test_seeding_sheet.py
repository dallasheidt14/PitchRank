"""Unit tests for ``src.tournaments.seeding_sheet``.

Pins how a resolved roster becomes a printable cohort sheet: strongest first,
teams with no rating held below the line, and the operator-supplied event name
escaped before it reaches the page.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_sheet import (
    build_cohort_sheets,
    fetch_ranking_run_date,
    render_sheet_html,
)
from src.tournaments.seeding_tiers import TierAnalysis, TierGroup, TierPolicy

PASTE = (
    "Male U14\nClub\tTeam\tState\n"
    "Barcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX\n"
    "Laredo Youth Soccer Assn\tLaredo Heat 2013 Red\tTX\n"
    "STX Elevate FC\tSTX Elevate FC 2012/13 JG\tTX\n"
    "Male U13\nClub\tTeam\tState\n"
    "Tyler FC\tTyler FC 15B*\tTX"
)

RESOLVED = (
    ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="m-barca"),
    ResolvedTeam(source_index=1, status="gotsport_id", team_id_master="m-laredo"),
    ResolvedTeam(source_index=2, status="gotsport_id", team_id_master="m-stx"),
    ResolvedTeam(source_index=3, status="unresolved"),
)

RATINGS = {
    "m-barca": {"team_name": "Barcelona SC Aztecas U14", "club_name": "Barcelona Soccer Club",
                "power_score_final": 0.4810, "status": "Active",
                "rank_in_cohort_final": 585, "rank_in_state_final": 72, "state": "TX"},
    "m-laredo": {"team_name": "Laredo Heat Red U14", "club_name": "Laredo Youth Soccer Assn",
                 "power_score_final": 0.5347, "status": "Active",
                 "rank_in_cohort_final": 315, "rank_in_state_final": 33, "state": "TX"},
}


def _sheets(ratings=None):
    parsed = parse_roster(PASTE)
    return build_cohort_sheets(parsed.rows, RESOLVED, {}, ratings if ratings is not None else RATINGS)


# -------- grouping and ordering -------------------------------------------


def test_one_sheet_per_cohort():
    assert [(sheet.age_group, sheet.gender) for sheet in _sheets()] == [("u14", "Male"), ("u13", "Male")]


def test_rated_teams_are_ordered_strongest_first():
    u14 = _sheets()[0]

    assert [team.team_name for team in u14.rated] == ["Laredo Heat Red U14", "Barcelona SC Aztecas U14"]


def test_a_team_with_no_rating_falls_below_the_line():
    u14 = _sheets()[0]

    assert [team.team_name for team in u14.unrated] == ["STX Elevate FC 2012/13 JG"]


def test_an_unresolved_row_still_appears_under_its_roster_name():
    u13 = _sheets()[1]

    assert [team.team_name for team in u13.unrated] == ["Tyler FC 15B"]


def test_total_teams_counts_both_sides_of_the_line():
    assert _sheets()[0].total_teams == 3


def test_a_ranked_team_carries_its_score_and_state_rank():
    top = _sheets()[0].rated[0]

    assert top.power_score == 0.5347
    assert top.state_rank == 33


def test_the_teams_own_name_is_used_when_we_have_a_rating_for_it():
    """The roster calls it `Barcelona SC 13B Aztecas`; we hold `Barcelona SC Aztecas U14`."""
    assert _sheets()[0].rated[1].team_name == "Barcelona SC Aztecas U14"


def test_an_inactive_team_with_a_score_but_no_rank_falls_below_the_line():
    """PitchRank publishes no rank for an Inactive team, so it is not a ranked team.

    It keeps its PowerScore below the line, since that is still worth seeing.
    """
    ratings = dict(RATINGS)
    ratings["m-stx"] = {"team_name": "STX Elevate FC 2012/13 JG", "club_name": "STX Elevate FC",
                        "power_score_final": 0.30, "status": "Inactive",
                        "rank_in_cohort_final": None, "rank_in_state_final": None}

    u14 = _sheets(ratings)[0]

    assert [team.team_name for team in u14.unrated] == ["STX Elevate FC 2012/13 JG"]
    assert u14.unrated[0].power_score == 0.30
    assert u14.unrated[0].status == "Inactive"


def test_an_override_supplies_the_team_id_used_for_the_rating():
    parsed = parse_roster(PASTE)
    sheets = build_cohort_sheets(parsed.rows, RESOLVED, {3: {"team_id_master": "m-laredo"}}, RATINGS)

    assert [team.team_name for team in sheets[1].rated] == ["Laredo Heat Red U14"]


# -------- rendering -------------------------------------------------------


def test_rendered_page_carries_the_brand_and_the_event_name():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "MatchBalance" in html
    assert "PitchRank" in html
    assert "STX Cup 2026" in html


def test_rendered_page_escapes_an_event_name_containing_markup():
    html = render_sheet_html("<script>x</script>", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_each_cohort_gets_its_own_printed_page():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert html.count('class="sheet"') == 2


def test_rendered_page_states_the_cohort_and_team_count():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "U14" in html
    assert "Boys" in html


def test_rendered_page_is_a_standalone_document():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "@page" in html


def test_the_two_groups_are_labelled_ranked_and_unranked():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "Ranked Teams" in html
    assert "Unranked Teams" in html


def test_the_unranked_heading_is_absent_when_every_team_is_rated():
    ratings = dict(RATINGS)
    ratings["m-stx"] = {"team_name": "STX Elevate FC 2012/13 JG", "club_name": "STX Elevate FC",
                        "power_score_final": 0.30, "status": "Active",
                        "rank_in_cohort_final": 900, "rank_in_state_final": 120}
    ratings["m-tyler"] = {"team_name": "Tyler FC 2015", "club_name": "Tyler FC",
                          "power_score_final": 0.41, "status": "Active",
                          "rank_in_cohort_final": 700, "rank_in_state_final": 95}
    parsed = parse_roster(PASTE)
    sheets = build_cohort_sheets(parsed.rows, RESOLVED, {3: {"team_id_master": "m-tyler"}}, ratings)

    html = render_sheet_html("STX Cup 2026", sheets, generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "Unranked Teams" not in html


# -------- ranking run date ------------------------------------------------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, count):
        self._rows = self._rows[:count]
        return self

    def execute(self):
        class _R:
            data = self._rows

        return _R()


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _FakeQuery(list(self._rows))


def test_ranking_run_date_is_read_from_the_latest_calculation():
    client = _FakeClient([{"last_calculated": "2026-08-31T12:00:00+00:00"}])

    assert fetch_ranking_run_date(client) == "2026-08-31"


def test_ranking_run_date_falls_back_when_nothing_is_calculated():
    assert fetch_ranking_run_date(_FakeClient([])) == "unknown"


# -------- columns and copy ------------------------------------------------


def test_the_sheet_shows_state_rank_and_not_ranked_games():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "State rank" in html
    assert "Ranked games" not in html


def test_a_ranked_teams_state_rank_reaches_the_page_with_its_state():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "TX #33" in html


def test_the_unranked_note_does_not_tell_the_reader_to_rescrape():
    html = render_sheet_html("STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31")

    assert "run this again" not in html
    assert "scrape" not in html.lower()


def _analysis(**changes):
    return replace(TierAnalysis(
        tiers=(
            TierGroup(1, ("1",), 0.0, 0.0, None),
            TierGroup(2, ("0",), 0.0, 0.0, None),
        ),
        review={"2": "Too few recent games to place confidently."},
        borderline={"0": (1,)},
        boundaries=("Keep Tier 1 and Tier 2 in separate flights where possible.",),
        ordered_ids=("1", "0"),
        warnings=("Review this single-team tier before assigning a flight.",),
    ), **changes)


def _tier_sheets(analysis=None):
    return build_cohort_sheets(
        parse_roster(PASTE).rows, RESOLVED, {}, RATINGS,
        tier_analyses={("u14", "Male"): analysis or _analysis()},
    )


def _render_tier(analysis=None, **kwargs):
    return render_sheet_html(
        "Competitive Cup", _tier_sheets(analysis),
        generated_on="2026-09-15", ranking_run="2026-09-14", **kwargs,
    )


def test_tier_sheet_carries_identity_and_preserves_every_accepted_row_once():
    sheets = _tier_sheets()
    assert [(team.entrant_id, team.team_id_master) for team in sheets[0].rated] == [
        ("1", "m-laredo"), ("0", "m-barca"),
    ]
    assert sheets[0].unrated[0].review_reason == "Too few recent games to place confidently."
    assert re.findall(r'data-entrant="([^"]+)"', _render_tier()) == ["1", "0", "2", "3"]


def test_tier_order_controls_print_order_and_seeds_continue_across_tiers():
    analysis = _analysis(tiers=(
        TierGroup(1, ("0",), 0.0, 0.0, None),
        TierGroup(2, ("1",), 0.0, 0.0, None),
    ), ordered_ids=("0", "1"))
    document = _render_tier(analysis)
    assert re.findall(r'data-entrant="([^"]+)"><td class="pos">([^<]+)', document) == [
        ("0", "1"), ("1", "2"), ("2", "-"), ("3", "-"),
    ]


def test_missing_analysis_member_is_kept_for_review_instead_of_dropped():
    document = _render_tier(_analysis(review={}))
    assert document.count('data-entrant="2"') == 1
    assert "Placement has not been assessed." in document


@pytest.mark.parametrize("analysis", [
    _analysis(tiers=(
        TierGroup(1, ("1",), 0.0, 0.0, None),
        TierGroup(2, ("1",), 0.0, 0.0, None),
    )),
    _analysis(review={"1": "Review"}),
    _analysis(review={"999": "Review"}),
])
def test_stale_or_duplicate_analysis_cannot_produce_a_misleading_sheet(analysis):
    with pytest.raises(ValueError):
        _render_tier(analysis)


def test_customer_pdf_shows_score_scale_review_reason_boundaries_and_manual_warnings():
    document = _render_tier(policy=TierPolicy(1.5, 0.2))
    assert ">53.5</td>" in document
    assert ">0.535</td>" not in document
    assert "Needs placement review" in document
    assert "Too few recent games to place confidently." in document
    assert "Borderline: also fits Tier 1." in document
    assert "no within-tier matchup to assess" in document
    assert "Keep Tier 1 and Tier 2 in separate flights where possible." in document
    assert "Review this single-team tier before assigning a flight." in document
    assert "expected goal gap up to 1.5" in document
    assert "chance of a 4+ goal margin up to 20%" in document


def test_customer_notes_and_prediction_text_are_escaped():
    document = _render_tier(
        _analysis(warnings=("<script>warning</script>",)),
        operator_notes={("u14", "Male"): "<b>Local knowledge & notes</b>"},
    )
    assert "<script>warning</script>" not in document
    assert "&lt;script&gt;warning&lt;/script&gt;" in document
    assert "&lt;b&gt;Local knowledge &amp; notes&lt;/b&gt;" in document


def test_printable_document_uses_no_remote_font_or_image_requests():
    document = _render_tier()
    assert "https://" not in document
    assert "http://" not in document


def test_repeated_master_id_does_not_silently_remove_a_roster_entrant():
    parsed = parse_roster(PASTE)
    sheets = build_cohort_sheets(parsed.rows, RESOLVED, {2: {"team_id_master": "m-laredo"}}, RATINGS)
    assert sum(sheet.total_teams for sheet in sheets) == 4
    assert [team.entrant_id for team in sheets[0].rated] == ["1", "2", "0"]


def test_duplicate_source_indexes_fail_instead_of_overwriting_an_entrant():
    row = parse_roster(PASTE).rows[0]
    with pytest.raises(ValueError, match="unique source index"):
        build_cohort_sheets([row, row], RESOLVED, {}, RATINGS)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1, "unknown", "0.55", True, False])
def test_invalid_score_is_not_printed_as_a_ranked_number(score):
    ratings = {**RATINGS, "m-stx": {"power_score_final": score, "rank_in_cohort_final": 1}}
    stx = next(team for team in _sheets(ratings)[0].unrated if team.entrant_id == "2")
    assert stx.power_score is None


@pytest.mark.parametrize("score", ["unknown", True, False])
def test_invalid_score_still_renders_team_with_its_placement_review_reason(score):
    ratings = {**RATINGS, "m-stx": {"power_score_final": score, "rank_in_cohort_final": 1}}
    sheets = build_cohort_sheets(
        parse_roster(PASTE).rows, RESOLVED, {}, ratings,
        tier_analyses={("u14", "Male"): _analysis(review={"2": "No current published PowerScore."})},
    )
    document = render_sheet_html("Test Cup", sheets, generated_on="2026-09-15", ranking_run="2026-09-14")
    assert document.count('data-entrant="2"') == 1
    assert "No current published PowerScore." in document
    row = document.split('data-entrant="2"', 1)[1].split("</tr>", 1)[0]
    assert '<td class="num score">-</td>' in row
