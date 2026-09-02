"""Unit tests for ``src.tournaments.seeding_sheet``.

Pins how a resolved roster becomes a printable cohort sheet: strongest first,
teams with no rating held below the line, and the operator-supplied event name
escaped before it reaches the page.
"""

from __future__ import annotations

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_sheet import (
    build_cohort_sheets,
    fetch_ranking_run_date,
    render_sheet_html,
)

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
                "power_score_final": 0.4810, "games_played": 22, "status": "Active"},
    "m-laredo": {"team_name": "Laredo Heat Red U14", "club_name": "Laredo Youth Soccer Assn",
                 "power_score_final": 0.5347, "games_played": 15, "status": "Active"},
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


def test_a_rated_team_carries_its_score_and_game_count():
    top = _sheets()[0].rated[0]

    assert top.power_score == 0.5347
    assert top.ranked_games == 15


def test_the_teams_own_name_is_used_when_we_have_a_rating_for_it():
    """The roster calls it `Barcelona SC 13B Aztecas`; we hold `Barcelona SC Aztecas U14`."""
    assert _sheets()[0].rated[1].team_name == "Barcelona SC Aztecas U14"


def test_an_inactive_team_stays_above_the_line_but_is_flagged():
    ratings = dict(RATINGS)
    ratings["m-stx"] = {"team_name": "STX Elevate FC 2012/13 JG", "club_name": "STX Elevate FC",
                        "power_score_final": 0.30, "games_played": 3, "status": "Inactive"}

    u14 = _sheets(ratings)

    assert [team.team_name for team in u14[0].unrated] == []
    assert u14[0].rated[-1].status == "Inactive"


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
                        "power_score_final": 0.30, "games_played": 3, "status": "Active"}
    ratings["m-tyler"] = {"team_name": "Tyler FC 2015", "club_name": "Tyler FC",
                          "power_score_final": 0.41, "games_played": 9, "status": "Active"}
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
