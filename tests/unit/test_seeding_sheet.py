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
    CohortSheet,
    SheetTeam,
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

    assert [team.team_name for team in u14.rated] == ["Laredo Heat 2013 Red", "Barcelona SC 13B Aztecas"]


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


def test_registered_name_stays_primary_and_a_different_pitchrank_name_is_secondary():
    """The roster calls it `Barcelona SC 13B Aztecas`; we hold `Barcelona SC Aztecas U14`."""
    team = _sheets()[0].rated[1]

    assert team.team_name == "Barcelona SC 13B Aztecas"
    assert team.pitchrank_team_name == "Barcelona SC Aztecas U14"

    document = render_sheet_html(
        "STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31"
    )
    row = document.split('data-entrant="0"', 1)[1].split("</tr>", 1)[0]
    assert row.index("Barcelona SC 13B Aztecas") < row.index("PitchRank: Barcelona SC Aztecas U14")


def test_equivalent_pitchrank_name_is_not_repeated():
    ratings = dict(RATINGS)
    ratings["m-barca"] = {**RATINGS["m-barca"], "team_name": "BARCELONA SC 13B AZTECAS!"}

    assert _sheets(ratings)[0].rated[1].pitchrank_team_name is None


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


def test_provisional_score_status_is_not_shown_as_a_customer_warning():
    ratings = dict(RATINGS)
    ratings["m-stx"] = {
        "team_name": "STX Elevate FC 2012/13 JG", "club_name": "STX Elevate FC",
        "power_score_final": 0.30, "status": "Not Enough Ranked Games",
        "rank_in_cohort_final": None, "rank_in_state_final": None,
    }

    sheets = _sheets(ratings)
    document = render_sheet_html(
        "STX Cup 2026", sheets[:1], generated_on="2026-09-02", ranking_run="2026-08-31"
    )

    assert [team.team_name for team in sheets[0].rated] == [
        "Laredo Heat 2013 Red",
        "Barcelona SC 13B Aztecas",
        "STX Elevate FC 2012/13 JG",
    ]
    assert sheets[0].unrated == ()
    assert "Not yet ranked" not in document
    assert "Not Enough Ranked Games" not in document
    assert "Unranked Teams" not in document
    assert ">30.0<span class=\"score-track\"" in document
    assert "Limited history" in document


def test_an_override_supplies_the_team_id_used_for_the_rating():
    parsed = parse_roster(PASTE)
    sheets = build_cohort_sheets(parsed.rows, RESOLVED, {3: {"team_id_master": "m-laredo"}}, RATINGS)

    assert [team.team_name for team in sheets[1].rated] == ["Tyler FC 15B"]
    assert sheets[1].rated[0].pitchrank_team_name == "Laredo Heat Red U14"


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

    assert "MatchBalance Suggested Seeding" in html
    assert "Unseeded teams" in html


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


def test_play_up_marker_becomes_a_plain_language_badge_with_ranked_age():
    ratings = {
        **RATINGS,
        "m-tyler": {
            "team_name": "Tyler FC 2015 Boys",
            "club_name": "Tyler FC",
            "power_score_final": 0.41,
            "status": "Active",
            "rank_in_state_final": 95,
            "state": "TX",
            "age": 12,
        },
    }
    parsed = parse_roster(PASTE)
    sheets = build_cohort_sheets(parsed.rows, RESOLVED, {3: {"team_id_master": "m-tyler"}}, ratings)

    assert sheets[1].rated[0].plays_up is True
    assert sheets[1].rated[0].play_up_from_age_group == "u12"
    document = render_sheet_html(
        "STX Cup 2026", sheets, generated_on="2026-09-02", ranking_run="2026-08-31"
    )
    row = document.split('data-entrant="3"', 1)[1].split("</tr>", 1)[0]
    assert "Tyler FC 15B" in row
    assert "Plays up from U12" in row
    assert "Tyler FC 15B*" not in row


@pytest.mark.parametrize("ranked_age", [14, 15])
def test_play_up_badge_does_not_claim_same_age_or_older_team_is_the_origin(ranked_age):
    ratings = {
        **RATINGS,
        "m-tyler": {
            "team_name": "Tyler FC",
            "club_name": "Tyler FC",
            "power_score_final": 0.41,
            "status": "Active",
            "rank_in_state_final": 95,
            "state": "TX",
            "age": ranked_age,
        },
    }
    parsed = parse_roster(PASTE)
    sheets = build_cohort_sheets(parsed.rows, RESOLVED, {3: {"team_id_master": "m-tyler"}}, ratings)

    assert sheets[1].rated[0].play_up_from_age_group is None
    document = render_sheet_html(
        "STX Cup 2026", sheets, generated_on="2026-09-02", ranking_run="2026-08-31"
    )
    row = document.split('data-entrant="3"', 1)[1].split("</tr>", 1)[0]
    assert "Plays up" in row
    assert "Plays up from" not in row


def test_registered_name_keeps_unknown_c_suffix_while_replacing_only_the_star_marker():
    parsed = parse_roster("Male U14\nClub\tFire 13B*-c\tTX")
    resolved = (ResolvedTeam(source_index=0, status="exact_name", team_id_master="fire"),)
    ratings = {
        "fire": {
            "team_name": "Fire 13B",
            "club_name": "Club",
            "power_score_final": 0.50,
            "status": "Active",
            "rank_in_state_final": 50,
            "state": "TX",
            "age": 13,
        }
    }

    sheet = build_cohort_sheets(parsed.rows, resolved, {}, ratings)[0]
    assert sheet.rated[0].team_name == "Fire 13B-c"
    document = render_sheet_html(
        "STX Cup 2026", (sheet,), generated_on="2026-09-02", ranking_run="2026-08-31"
    )
    row = document.split('data-entrant="0"', 1)[1].split("</tr>", 1)[0]
    assert "Fire 13B-c" in row
    assert "Fire 13B*-c" not in row


def test_requested_flight_and_event_listed_division_are_labeled_separately_beside_score():
    sheet = CohortSheet(
        age_group="u14",
        gender="Male",
        rated=(
            SheetTeam("Requested Team", "Club", power_score=0.55, entrant_id="1", requested_flight="Gold"),
            SheetTeam("Listed Team", "Club", power_score=0.50, entrant_id="2", listed_division="Premier"),
        ),
        unrated=(),
    )
    document = render_sheet_html(
        "STX Cup 2026", (sheet,), generated_on="2026-09-02", ranking_run="2026-08-31"
    )

    requested_row = document.split('data-entrant="1"', 1)[1].split("</tr>", 1)[0]
    listed_row = document.split('data-entrant="2"', 1)[1].split("</tr>", 1)[0]
    assert "55.0" in requested_row and "Requested: Gold" in requested_row
    assert "Listed: Premier" not in requested_row
    assert "50.0" in listed_row and "Listed: Premier" in listed_row
    assert "Requested: Gold" not in listed_row


def test_roster_flight_fields_reach_the_sheet_model_without_changing_their_meaning():
    parsed = parse_roster(
        "Male U14\nClub\tTeam\tState\tRequested flight\n"
        "Barcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX\tGold"
    )
    pasted_sheet = build_cohort_sheets(parsed.rows, RESOLVED[:1], {}, RATINGS)[0]
    event_row = replace(parsed.rows[0], requested_flight="", listed_division="U14 Boys Premier")
    event_sheet = build_cohort_sheets((event_row,), RESOLVED[:1], {}, RATINGS)[0]

    assert pasted_sheet.rated[0].requested_flight == "Gold"
    assert pasted_sheet.rated[0].listed_division is None
    assert event_sheet.rated[0].requested_flight is None
    assert event_sheet.rated[0].listed_division == "U14 Boys Premier"


def test_score_explanation_handles_play_up_teams_and_own_cohort_state_rank():
    plain_document = render_sheet_html(
        "STX Cup 2026", _sheets(), generated_on="2026-09-02", ranking_run="2026-08-31"
    )
    tier_document = _render_tier()

    for document in (plain_document, tier_document):
        assert "PitchRank score already adjusts for age" in document
        assert "younger team playing up can be compared" in document
        assert "own PitchRank age and gender group" in document
        assert "Rankings are specific to each age group and gender" not in document


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
        review={"2": "Confirm the club, team name, and age group before seeding."},
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
    assert sheets[0].unrated[0].review_reason == "Confirm the club, team name, and age group before seeding."
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
    assert "Data review required" in document


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


def test_customer_pdf_prioritizes_seeding_actions_over_model_jargon():
    document = _render_tier(policy=TierPolicy(1.5, 0.2))
    assert ">53.5<span class=\"score-track\"" in document
    assert ">0.535</td>" not in document
    assert "they do not assign divisions or pools." in document
    assert "MatchBalance Seed" in document
    assert "Competitive Breaks" in document
    assert "Close ranges" not in document
    assert "MatchBalance Seed" in document
    assert "PitchRank score" in document
    assert "What to know" in document
    assert "Placement status" not in document
    assert "Data review required" in document
    assert "Limited recent results" not in document
    assert "Boundary option" not in document
    assert "No close peer was found at this level." not in document
    assert "Keep Tier 1 and Tier 2" not in document
    assert "Review this single-team tier" not in document
    assert "expected goal gap" not in document
    assert "chance of a 4+ goal margin" not in document


def test_all_manual_cohort_does_not_instruct_director_to_use_missing_tiers():
    analysis = _analysis(
        tiers=(),
        review={str(index): "Confirm the team match before seeding." for index in range(3)},
        borderline={},
        boundaries=(),
        ordered_ids=(),
        warnings=(),
    )
    document = _render_tier(analysis)

    assert "0 teams in the effective seed order · 3 held for placement review." in document
    assert "MatchBalance Suggested Seeding" in document
    assert "Build flights from the same tier" not in document
    assert "Tier 1 is strongest" not in document
    assert "Use a Boundary option" not in document


def test_multiple_boundary_options_use_an_or_list():
    analysis = _analysis(
        tiers=(
            TierGroup(1, ("1",), 0.0, 0.0, None),
            TierGroup(2, ("0",), 0.0, 0.0, None),
            TierGroup(3, ("2",), 0.0, 0.0, None),
        ),
        review={},
        borderline={"0": (1, 3)},
        boundaries=("Keep these groups separate.", "Keep these groups separate."),
        ordered_ids=("1", "0", "2"),
        warnings=(),
    )
    document = _render_tier(analysis)

    assert "Boundary options" not in document
    assert "they do not assign divisions or pools." in document


def test_customer_pdf_translates_system_diagnostics_into_seeding_actions():
    analysis = _analysis(
        borderline={"1": (2,)},
        boundaries=(
            "Tier 1 / Tier 2: Overlapping matchups; review the boundary. Upper tier favored in 3/5 "
            "matchups, with an average expected edge of 0.70 goals; 1/5 exceed the within-tier limits.",
        ),
        warnings=(
            "Tier 2 has one team; there is no within-tier matchup to assess.",
            "Tiers 1 and 2 have a strength-order exception: at least one lower-tier team is favored.",
            "3/6 matchups have low outcome confidence. This can reflect closely matched teams.",
        ),
    )
    document = _render_tier(analysis)

    assert "MatchBalance Suggested Seeding" in document
    assert "Tier 2 has one team" not in document
    assert "A lower-tier team may compete well with an upper tier" not in document
    assert "Several projected matchups are too close to call" not in document
    assert "expected edge" not in document
    assert "within-tier limits" not in document
    assert "low outcome confidence" not in document
    assert "strength-order exception" not in document


def test_customer_pdf_does_not_recommend_a_missing_boundary_option():
    analysis = _analysis(
        borderline={},
        boundaries=(
            "Tier 1 / Tier 2: Overlapping matchups; review the boundary. Upper tier favored in 3/5 "
            "matchups, with an average expected edge of 0.70 goals; 1/5 exceed the within-tier limits.",
        ),
    )

    document = _render_tier(analysis)

    assert "they do not assign divisions or pools." in document
    assert "use the team marked Boundary option" not in document


def test_customer_pdf_explains_a_ranking_matchup_order_conflict_plainly():
    analysis = _analysis(
        borderline={},
        boundaries=(
            "Tier 1 / Tier 2: Ranking/matchup order conflict; review the boundary. Upper tier favored in 0/1 "
            "matchups, with an average expected edge of -4.00 goals; 1/1 exceed the within-tier limits.",
        ),
    )

    document = _render_tier(analysis)

    assert "they do not assign divisions or pools." in document
    assert "Ranking/matchup order conflict" not in document
    assert "use the team marked Boundary option" not in document


def test_tier_headings_repeat_and_review_table_stays_together_when_it_fits():
    document = _render_tier()

    seed_table = document.split('<table class="grid tier-table">', 1)[1].split("</table>", 1)[0]
    assert seed_table.index("MatchBalance Suggested Seeding") < seed_table.index("</thead>")
    assert seed_table.index("MatchBalance Seed") < seed_table.index("</thead>")
    assert "table.grid thead { display: table-header-group; }" in document
    assert "table.review { break-inside: avoid-page; page-break-inside: avoid; }" in document


def test_customer_notes_and_prediction_text_are_escaped():
    document = _render_tier(
        _analysis(),
        operator_notes={("u14", "Male"): "<b>Local knowledge & notes</b>"},
    )
    assert "<script>warning</script>" not in document
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
        tier_analyses={("u14", "Male"): _analysis(
            review={"2": "No current PitchRank score. Use recent results or club input."}
        )},
    )
    document = render_sheet_html("Test Cup", sheets, generated_on="2026-09-15", ranking_run="2026-09-14")
    assert document.count('data-entrant="2"') == 1
    assert "Data review required" in document
    row = document.split('data-entrant="2"', 1)[1].split("</tr>", 1)[0]
    assert '<td class="num score">-<span class="state">—</span></td>' in row
