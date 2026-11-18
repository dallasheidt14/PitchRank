"""Unit tests for the YSSL driver."""

import csv
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import import_yssl as yssl
from tests.unit.test_yssl_matcher import _DB

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "yssl"
TEAM_URL = "https://www.yssl.org/team.php?tea_id=130243"


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseClubList:
    def test_reads_every_club_code(self):
        codes = yssl.parse_club_list(_fixture("clublinks.html"))
        assert len(codes) == 136
        assert codes[0] == "AAC"
        assert "FC1" in codes
        assert codes == sorted(set(codes))


class TestParseClubPage:
    def test_reads_club_name_and_teams(self):
        name, listings = yssl.parse_club_page(_fixture("club_AAC.html"))
        assert name == "AAC EAGLES CHICAGO"
        assert [(x.tea_id, x.division, x.team_name, x.team_code) for x in listings] == [
            ("130249", "U10/1", "AAC EAGLES CHICAGO 16/17 GOLD", "AACM101"),
            ("130250", "U10/5NW2", "AAC EAGLES CHICAGO 16/17 SILVER", "AACM102"),
            ("130243", "U12/1", "AAC EAGLES CHICAGO 14/15 GOLD", "AACM121"),
        ]

    def test_small_sided_division_label_is_kept_whole(self):
        _, listings = yssl.parse_club_page(_fixture("club_BRB.html"))
        assert [x.division for x in listings if x.division.startswith("U07")] == ["U07-4V4/E"]


class TestGameDate:
    @pytest.mark.parametrize(
        ("month", "day", "expected"),
        [(9, 13, date(2026, 9, 13)), (11, 1, date(2026, 11, 1)), (4, 10, date(2027, 4, 10))],
    )
    def test_fall_is_season_year_spring_is_next(self, month, day, expected):
        assert yssl.game_date(month, day, 2026) == expected


class TestParseTeamGames:
    def _games(self):
        return yssl.parse_team_games(_fixture("team_130243.html"), "AACM121", 2026, TEAM_URL)

    def test_keeps_scored_games_only(self):
        games, problems = self._games()
        assert problems == []
        assert [g.game_no for g in games] == ["4267", "503", "1840", "3529", "1294"]

    def test_changed_game_uses_the_unstruck_date(self):
        games, _ = self._games()
        assert (games[0].game_date, games[0].game_time) == (date(2026, 9, 13), "4:00pm")

    def test_score_is_from_this_teams_side(self):
        games, _ = self._games()
        seen = {g.game_no: (g.home_away, g.opponent_code, g.goals_for, g.goals_against) for g in games}
        assert seen["4267"] == ("H", "ECLM121", 2, 3)
        assert seen["503"] == ("A", "WZDM125", 2, 7)
        assert sum(g.goals_for for g in games) == 10  # the page's own GF
        assert sum(g.goals_against for g in games) == 34  # the page's own GA

    def test_venue_is_the_current_field(self):
        games, _ = self._games()
        assert [g.venue for g in games[:3]] == [
            "HUNTINGTON CHASE",
            "CENTRAL PARK NORTH - KENSINGTON RD. ENTRANCE - TURF",
            "OAK BROOK POLO FIELDS - A 9V9",
        ]

    def test_no_games_table_is_a_problem_not_silence(self):
        games, problems = yssl.parse_team_games("<html><body>nothing</body></html>", "AACM121", 2026, "u")
        assert games == []
        assert problems == ["AACM121: games table not found"]

    @pytest.mark.parametrize(
        ("date_cell", "problem"),
        [
            (
                '<td> <font color="#0000AA">rainout</font><br/><del>Fri 10/2 10:10am<br/>Fri 10/2 5:30pm</del></td>',
                "AACM121 game 4267: rained out",
            ),
            ("<td>&nbsp;TBD</td>", "AACM121 game 4267: unreadable row"),
        ],
        ids=["rainout", "unreadable"],
    )
    def test_a_row_without_a_date_is_a_problem_naming_why(self, date_cell, problem):
        original = "<td>&nbsp;Sun 9/13 4:00pm<br><del><font color=#999999>Sat 10/17 2:00pm</font></del></td>"
        html = _fixture("team_130243.html")
        assert html.count(original) == 1
        _, problems = yssl.parse_team_games(html.replace(original, date_cell), "AACM121", 2026, TEAM_URL)
        assert problems == [problem]


def _side(no, team, opp, ha, gf, ga, day=date(2026, 9, 13)):
    return yssl.SideGame(no, day, "4:00pm", team, opp, ha, gf, ga, "FIELD", f"u/{team}")


class TestMergeGames:
    def test_two_agreeing_sides_make_one_game(self):
        games, problems = yssl.merge_games(
            [_side("1", "AACM121", "ECLM121", "H", 2, 3), _side("1", "ECLM121", "AACM121", "A", 3, 2)]
        )
        assert problems == []
        assert [(g.game_no, g.home_code, g.away_code, g.home_score, g.away_score) for g in games] == [
            ("1", "AACM121", "ECLM121", 2, 3)
        ]

    def test_one_side_is_enough(self):
        games, problems = yssl.merge_games([_side("7", "ECLM121", "AACM121", "A", 3, 2)])
        assert problems == []
        assert [(g.home_code, g.away_code, g.home_score, g.away_score) for g in games] == [("AACM121", "ECLM121", 2, 3)]

    @pytest.mark.parametrize(
        "other",
        [
            _side("1", "ECLM121", "AACM121", "A", 4, 2),
            _side("1", "ECLM121", "AACM121", "A", 3, 2, day=date(2026, 9, 14)),
            _side("1", "ECLM121", "PGSM121", "A", 3, 2),
            _side("1", "ECLM121", "AACM121", "H", 3, 2),
        ],
        ids=["score", "date", "opponent", "both-home"],
    )
    def test_disagreeing_sides_hold_the_game(self, other):
        games, problems = yssl.merge_games([_side("1", "AACM121", "ECLM121", "H", 2, 3), other])
        assert games == []
        assert problems == ["game 1: the two teams' pages disagree"]

    def test_three_sides_hold_the_game(self):
        side = _side("1", "AACM121", "ECLM121", "H", 2, 3)
        games, problems = yssl.merge_games([side, _side("1", "ECLM121", "AACM121", "A", 3, 2), side])
        assert games == []
        assert problems == ["game 1: listed 3 times"]


class _Pages:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def __call__(self, url):
        self.fetched.append(url)
        if url not in self.pages:
            raise yssl.ScrapeFetchError(f"HTTP 404 for {url}")
        return self.pages[url]


class TestCollectLeague:
    def _pages(self):
        team = _fixture("team_130243.html")
        return _Pages(
            {
                f"{yssl.BASE_URL}/clublinks.php": _fixture("clublinks.html"),
                f"{yssl.BASE_URL}/club.php?clu_code=AAC": _fixture("club_AAC.html"),
                f"{yssl.BASE_URL}/team.php?tea_id=130249": team.replace("AACM121", "AACM101"),
                f"{yssl.BASE_URL}/team.php?tea_id=130250": team.replace("AACM121", "AACM102"),
                f"{yssl.BASE_URL}/team.php?tea_id=130243": team,
            }
        )

    def test_walks_only_the_named_clubs(self):
        pages = self._pages()
        clubs, sides, problems = yssl.collect_league(pages, ["AAC"], 2026)
        assert problems == []
        assert list(clubs) == ["AAC"]
        assert clubs["AAC"][0] == "AAC EAGLES CHICAGO"
        assert len(pages.fetched) == 5
        assert {s.team_code for s in sides} == {"AACM101", "AACM102", "AACM121"}

    def test_a_named_club_not_on_the_list_is_a_problem(self):
        _, _, problems = yssl.collect_league(self._pages(), ["AAC", "ZZZ"], 2026)
        assert problems == ["club ZZZ is not on the club list"]

    def test_a_failed_page_stops_the_run(self):
        pages = self._pages()
        del pages.pages[f"{yssl.BASE_URL}/team.php?tea_id=130250"]
        with pytest.raises(yssl.ScrapeFetchError):
            yssl.collect_league(pages, ["AAC"], 2026)

    def test_a_club_page_listing_another_season_stops_the_walk(self):
        with pytest.raises(yssl.StaleSeasonError):
            yssl.collect_league(self._pages(), ["AAC"], 2027)

    def _club_pages(self, aac_term, brb_term):
        """The AAC and BRB club pages headed by the given terms; None leaves a heading that names no term."""
        heading = "Fall 2026 Teams"
        aac, brb = _fixture("club_AAC.html"), _fixture("club_BRB.html")
        assert (aac.count(heading), brb.count(heading)) == (1, 1)
        return _Pages(
            {
                f"{yssl.BASE_URL}/clublinks.php": _fixture("clublinks.html"),
                f"{yssl.BASE_URL}/club.php?clu_code=AAC": aac.replace(heading, f"{aac_term or 'Our'} Teams"),
                f"{yssl.BASE_URL}/club.php?clu_code=BRB": brb.replace(heading, f"{brb_term or 'Our'} Teams"),
            }
        )

    def test_an_archive_run_reads_only_the_club_pages(self):
        pages = self._club_pages("Spring 2027", "Fall 2026")
        clubs, sides, problems = yssl.collect_league(pages, ["AAC", "BRB"], 2026, archive="FALL2026")
        assert pages.fetched == [
            f"{yssl.BASE_URL}/clublinks.php",
            f"{yssl.BASE_URL}/club.php?clu_code=AAC",
            f"{yssl.BASE_URL}/club.php?clu_code=BRB",
        ]
        assert (sorted(clubs), len(clubs["AAC"][1]), sides, problems) == (["AAC", "BRB"], 3, [], [])

    @pytest.mark.parametrize("brb_term", ["Spring 2026", None], ids=["earlier-season", "no-heading"])
    def test_an_archive_run_reads_past_a_club_page_on_no_term_of_this_season(self, brb_term):
        pages = self._club_pages("Spring 2027", brb_term)
        clubs, _, _ = yssl.collect_league(pages, ["AAC", "BRB"], 2026, archive="FALL2026")
        assert sorted(clubs) == (["AAC"] if brb_term else ["AAC", "BRB"])

    @pytest.mark.parametrize(
        ("aac_term", "brb_term"),
        [("Fall 2026", "Fall 2026"), ("Spring 2026", "Spring 2026"), (None, None)],
        ids=["term-still-live", "season-not-posted", "no-term-listed"],
    )
    def test_an_archive_run_stops_unless_a_later_term_is_listed(self, aac_term, brb_term):
        with pytest.raises(yssl.LiveTermError):
            yssl.collect_league(self._club_pages(aac_term, brb_term), ["AAC", "BRB"], 2026, archive="FALL2026")

    def test_a_weekly_run_reads_past_a_club_page_with_no_heading(self):
        pages = self._pages()
        url = f"{yssl.BASE_URL}/club.php?clu_code=AAC"
        pages.pages[url] = pages.pages[url].replace("Fall 2026 Teams", "Our Teams")
        clubs, sides, problems = yssl.collect_league(pages, ["AAC"], 2026)
        assert (list(clubs), problems) == (["AAC"], [])
        assert sides


INDEX_URL = f"{yssl.BASE_URL}/pastscores.php?l=FALL+2026&d=FALL2026"
ARCHIVE_URL = f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U11-1S.TXT"
U11_1S = {
    "EVOLUTION SC 15/16 PRE ACADEMY BOYS PFC": "EVLM111",
    "ORLAND PARK STING FC 2015/16 PRE EA": "OPSM111",
    "LTSC 2015/16B PRE EA SELECT": "LTSM111",
    "RUSH OSWEGO 15/16 PREMIER": "CHRM111",
    "CFA - COSMOS FC 15/16": "CFAM111",
    "ACADEMIA ATLAS FC 15/16 SELECT": "AAFM111",
}


def _codes(names=U11_1S):
    return {name: {code} for name, code in names.items()}


@pytest.mark.parametrize(
    ("code", "season"),
    [
        ("FALL2026", 2026),
        ("SPRING2027", 2026),
        ("fall2026", None),
        ("FALL 2026", None),
        ("SUMMER2026", None),
        ("FALL2026\n", None),
    ],
)
def test_archive_season_reads_the_archive_code(code, season):
    assert yssl.archive_season(code) == season


@pytest.mark.parametrize(
    ("code", "dates"),
    [("FALL2026", (date(2026, 8, 1), date(2027, 1, 1))), ("SPRING2027", (date(2027, 1, 1), date(2027, 8, 1)))],
)
def test_term_dates_bound_the_archives_term(code, dates):
    assert yssl.term_dates(code) == dates


def test_the_live_term_is_read_from_the_club_page_heading():
    assert (yssl.site_term(_fixture("club_AAC.html")), yssl.site_term("<div>Teams</div>")) == ("FALL2026", None)


class TestParseArchiveIndex:
    def test_lists_the_scores_file_of_each_division_on_a_board(self):
        assert yssl.parse_archive_index(_fixture("pastscores_FALL2026.html"), "FALL2026") == [
            ("U10/1", f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U10-1.TXT"),
            ("U11/1S", ARCHIVE_URL),
            ("U11/5W", f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U11-5W.TXT"),
        ]

    def test_another_seasons_files_are_not_listed(self):
        assert yssl.parse_archive_index(_fixture("pastscores_FALL2026.html"), "SPRING2026") == []

    def test_a_link_naming_another_host_is_not_listed(self):
        html = _fixture("pastscores_FALL2026.html").replace(
            'href="/PASTSCORES/FALL2026/U11-1S.TXT"', 'href="@other.example/PASTSCORES/FALL2026/U11-1S.TXT"'
        )
        assert "U11/1S" not in [division for division, _ in yssl.parse_archive_index(html, "FALL2026")]


class TestParseArchiveScores:
    def _parse(self, text=None, codes=None):
        text = _fixture("FALL2026_U11-1S.TXT") if text is None else text
        return yssl.parse_archive_scores(text, "U11/1S", ARCHIVE_URL, _codes() if codes is None else codes)

    def test_reads_each_scored_game_from_the_home_side(self):
        games, problems = self._parse()
        assert problems == []
        assert len(games) == 20
        assert games[0] == yssl.SideGame(
            "117", date(2026, 9, 12), "", "EVLM111", "OPSM111", "H", 3, 2, "", ARCHIVE_URL, "U11/1S"
        )

    def test_a_game_takes_the_saturday_of_its_week(self):
        dates = {g.game_no: g.game_date for g in self._parse()[0]}
        assert (dates["1434"], dates["2357"], dates["5530"]) == (
            date(2026, 9, 19),
            date(2026, 10, 3),
            date(2026, 10, 31),
        )

    def test_a_tie_and_a_double_digit_score_read_whole(self):
        scores = {g.game_no: (g.goals_for, g.goals_against) for g in self._parse()[0]}
        assert (scores["908"], scores["1598"], scores["313"]) == ((2, 2), (11, 0), (10, 2))

    def test_forfeits_and_unscored_games_are_not_results(self):
        games, problems = self._parse()
        assert {"2273", "3837", "4632", "4047"}.isdisjoint(g.game_no for g in games)
        assert problems == []

    def test_a_home_sides_forfeit_is_not_a_result(self):
        visitors_forfeit = "  2273 RUSH OSWEGO 15/16 PREMIER       1 Win*    ACADEMIA ATLAS FC 15/16 SELECT -2 Forf"
        home_forfeit = "  2273 ACADEMIA ATLAS FC 15/16 SELECT -2 Forf    RUSH OSWEGO 15/16 PREMIER       1 Win*"
        text = _fixture("FALL2026_U11-1S.TXT")
        assert text.count(visitors_forfeit) == 1
        games, problems = self._parse(text.replace(visitors_forfeit, home_forfeit))
        assert "2273" not in {g.game_no for g in games}
        assert problems == []

    @pytest.mark.parametrize(
        ("archive_name", "listed_name"),
        [("CFA - COSMOS  FC 15/16", "CFA - COSMOS FC 15/16"), ("CFA - COSMOS FC 15/16", "Cfa - Cosmos  FC 15/16")],
        ids=["archive-spacing", "listed-case-and-spacing"],
    )
    def test_names_match_uppercased_with_spaces_collapsed(self, archive_name, listed_name):
        text = _fixture("FALL2026_U11-1S.TXT").replace("   313 CFA - COSMOS FC 15/16", f"   313 {archive_name}")
        listings = [yssl.Listing(str(i), "U11/1S", name, code) for i, (name, code) in enumerate(U11_1S.items())]
        listings[4] = yssl.Listing("4", "U11/1S", listed_name, "CFAM111")
        games, problems = self._parse(text, yssl.codes_by_name({"X": ("", listings)}, {}))
        assert problems == []
        assert {g.game_no: g.team_code for g in games}["313"] == "CFAM111"

    def test_a_name_naming_no_team_or_two_teams_holds_the_game(self):
        codes = _codes({**U11_1S, "CFA - COSMOS FC 15/16": "CFAM111"})
        codes["CFA - COSMOS FC 15/16"].add("CFAM112")
        del codes["ACADEMIA ATLAS FC 15/16 SELECT"]
        games, problems = self._parse(codes=codes)
        assert (
            "game 313: not one team by that name: "
            "CFA - COSMOS FC 15/16 (2 teams), ACADEMIA ATLAS FC 15/16 SELECT (0 teams)"
        ) in problems
        assert not {"CFAM111", "CFAM112", "AAFM111"} & {code for g in games for code in (g.team_code, g.opponent_code)}

    def test_an_unreadable_line_is_a_problem(self):
        text = _fixture("FALL2026_U11-1S.TXT").replace(
            "FC 15/16           2 Win*    RUSH", "FC 15/16           2 Won*    RUSH"
        )
        games, problems = self._parse(text)
        assert problems == [
            "U11/1S: unreadable line '3316 CFA - COSMOS FC 15/16 2 Won* RUSH OSWEGO 15/16 PREMIER 0 Lose*'"
        ]
        assert "3316" not in {g.game_no for g in games}

    def test_a_game_before_any_week_is_a_problem(self):
        games, problems = self._parse("   117 CFA - COSMOS FC 15/16  1 Win  RUSH OSWEGO 15/16 PREMIER  0 Lose\n")
        assert (games, len(problems)) == ([], 1)


class TestCollectArchive:
    def _pages(self):
        return _Pages(
            {
                INDEX_URL: _fixture("pastscores_FALL2026.html"),
                f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U10-1.TXT": "",
                ARCHIVE_URL: _fixture("FALL2026_U11-1S.TXT"),
                f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U11-5W.TXT": "",
            }
        )

    def test_reads_the_index_then_each_board_divisions_scores(self):
        pages = self._pages()
        sides, problems = yssl.collect_archive(pages, "FALL2026", _codes())
        assert problems == []
        assert pages.fetched == list(pages.pages)
        assert {s.division for s in sides} == {"U11/1S"}
        assert len(sides) == 20

    def test_an_archive_listing_no_division_is_a_problem(self):
        pages = _Pages({f"{yssl.BASE_URL}/pastscores.php?l=SPRING+2027&d=SPRING2027": "<html></html>"})
        assert yssl.collect_archive(pages, "SPRING2027", {}) == (
            [],
            ["the SPRING2027 archive lists no U10-or-older division"],
        )

    def test_a_failed_file_stops_the_run(self):
        pages = self._pages()
        del pages.pages[ARCHIVE_URL]
        with pytest.raises(yssl.ScrapeFetchError):
            yssl.collect_archive(pages, "FALL2026", _codes())


@pytest.mark.parametrize(
    ("heading", "season"),
    [("Fall 2026 Teams", 2026), ("Spring 2027 Teams", 2026), ("Teams", None)],
    ids=["fall", "spring", "none"],
)
def test_site_season_reads_the_club_page_heading(heading, season):
    assert yssl.site_season(f"<div>&nbsp;{heading}&nbsp;</div>") == season


class _Response:
    def __init__(self, status, body, content_type="text/html"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = body
        self.encoding = None

    @property
    def text(self):
        return self.content.decode(self.encoding or "ISO-8859-1")


class _Session:
    def __init__(self, response):
        self.response = response

    def get(self, url, timeout):
        return self.response


class TestFetch:
    def test_undeclared_charset_decodes_as_utf8(self):
        response = yssl._get(_Session(_Response(200, "CAFÉ".encode("utf-8"))), "u")
        assert response.text == "CAFÉ"

    def test_non_200_raises(self):
        with pytest.raises(yssl.ScrapeFetchError):
            yssl._get(_Session(_Response(503, b"")), "u")


class TestTeamAge:
    @pytest.mark.parametrize(
        ("name", "division", "expected"),
        [
            ("AAC EAGLES CHICAGO 14/15 GOLD", "U12/1", ("u12", "band 14/15")),
            ("WCOB FC 2014/15 ACADEMY BLACK", "U12/3", ("u12", "band 2014/15")),
            ("BERBER CITY FC 12/13", "U14/5CITY", ("u14", "band 12/13")),
            ("EAGLES 13/14 PREMIER", "U14/1", ("u13", "band 13/14")),
            ("EAGLES RED", "U11/2", ("u11", "division U11")),
            ("EAGLES RED", "U18/1", ("u19", "division U18")),
        ],
        ids=["two-digit", "four-digit", "older", "plays-up", "division", "u18-folds"],
    )
    def test_band_first_then_division(self, name, division, expected):
        assert yssl.team_age(name, division, 2026) == expected

    @pytest.mark.parametrize(
        ("name", "division"),
        [("RUSH - WILMETTE WINGS 18/19B PREMIER", "U08-7V7/4N"), ("EAGLES", "U09/4S"), ("EAGLES", "")],
        ids=["band-u8", "division-u9", "nothing"],
    )
    def test_no_board_is_none(self, name, division):
        assert yssl.team_age(name, division, 2026)[0] is None


def _club_map(**names):
    return {code: [yssl.ClubEntry(code, code, name, "owner")] for code, name in names.items()}


RUSH = {
    "CHR": [
        yssl.ClubEntry("CHR", "CHICAGO RUSH", "Chicago Rush Soccer Club", "owner"),
        yssl.ClubEntry("CHR", "CHICAGO RUSH", "Chicago Rush North Shore", "owner", team_prefix="RUSH NORTH"),
    ]
}


class TestBuildRoster:
    def test_maps_club_and_reads_gender_from_code(self):
        listing = yssl.Listing("130243", "U12/1", "AAC EAGLES CHICAGO 14/15 GOLD", "AACM121")
        in_scope, left_out = yssl.build_roster(
            {"AAC": ("AAC EAGLES CHICAGO", [listing])}, _club_map(AAC="AAC Eagles"), 2026
        )
        assert left_out == []
        row = in_scope[0]
        assert (row.team_code, row.club_name, row.club_as_written, row.age_group, row.gender, row.state_code) == (
            "2026-AACM121",
            "AAC Eagles",
            "AAC EAGLES CHICAGO",
            "u12",
            "Male",
            "IL",
        )

    def test_the_team_id_is_scoped_to_the_season(self):
        listing = yssl.Listing("1", "U12/1", "X 14/15", "AACM121")
        clubs = {"AAC": ("AAC", [listing])}
        assert yssl.build_roster(clubs, _club_map(AAC="AAC Eagles"), 2026)[0][0].team_code == "2026-AACM121"
        assert yssl.build_roster(clubs, _club_map(AAC="AAC Eagles"), 2027)[0][0].team_code == "2027-AACM121"

    def test_a_branch_row_claims_the_teams_named_for_it(self):
        listings = [
            yssl.Listing("1", "U10/3N", "RUSH NORTH 16/17 PREMIER", "CHRM105"),
            yssl.Listing("2", "U10/3SW", "RUSH OSWEGO 16/17 PREMIER", "CHRM102"),
        ]
        in_scope, _ = yssl.build_roster({"CHR": ("CHICAGO RUSH", listings)}, RUSH, 2026)
        assert [(r.team_name, r.club_name, r.club_as_written) for r in in_scope] == [
            ("RUSH NORTH 16/17 PREMIER", "Chicago Rush North Shore", "RUSH NORTH"),
            ("RUSH OSWEGO 16/17 PREMIER", "Chicago Rush Soccer Club", "RUSH"),
        ]

    def test_a_branch_keeps_its_own_words_out_of_the_written_club(self):
        entries = yssl.load_club_map(yssl.CLUB_MAP_PATH)["CHR"]
        names = ("RUSH NORTH SHORE 15/16B BLUE", "RUSH - WILMETTE WINGS 15/16B BLUE")
        written = [yssl.written_club(n, "CHICAGO RUSH", yssl.club_entry_for(entries, n)) for n in names]
        assert written == ["RUSH", "RUSH - WILMETTE WINGS"]

    def test_the_longest_fitting_prefix_row_wins(self):
        entries = [
            yssl.ClubEntry("CHR", "CHICAGO RUSH", "Chicago Rush Soccer Club", "owner", team_prefix="RUSH"),
            yssl.ClubEntry("CHR", "CHICAGO RUSH", "Wilmette Wings SC", "owner", team_prefix="RUSH NORTH SHORE"),
        ]
        entry = yssl.club_entry_for(entries, "RUSH NORTH SHORE 13/14B BLUE")
        assert entry.pitchrank_club_name == "Wilmette Wings SC"

    def test_with_only_branch_rows_an_unclaimed_team_is_left_out(self):
        branch_only = {"CHR": RUSH["CHR"][1:]}
        listing = yssl.Listing("2", "U10/3SW", "RUSH OSWEGO 16/17 PREMIER", "CHRM102")
        in_scope, left_out = yssl.build_roster({"CHR": ("CHICAGO RUSH", [listing])}, branch_only, 2026)
        assert in_scope == []
        assert left_out[0].skip_reason == "no CHR club-map row fits this team"
        assert left_out[0].club_name is None

    def test_a_club_takes_its_mapped_state(self):
        club_map = {"NWI": [yssl.ClubEntry("NWI", "NWI LIONS UNITED", "NWI Lions United", "owner", state_code="IN")]}
        listing = yssl.Listing("1", "U12/1", "NWI LIONS 14/15 BLUE", "NWIM121")
        in_scope, _ = yssl.build_roster({"NWI": ("NWI LIONS UNITED", [listing])}, club_map, 2026)
        assert in_scope[0].state_code == "IN"

    def test_a_skipped_club_is_left_out_without_counting_as_unmapped(self):
        club_map = {"TBD": [yssl.ClubEntry("TBD", "TBD", yssl.SKIP_CLUB, "owner")]}
        listing = yssl.Listing("1", "U13/1", "TBD 2013 RED", "TBDM131")
        in_scope, left_out = yssl.build_roster({"TBD": ("TBD", [listing])}, club_map, 2026)
        assert in_scope == []
        assert left_out[0].skip_reason == "club TBD is skipped in the club map"
        assert left_out[0].club_name is not None

    def test_a_team_named_girls_is_filed_as_girls_whatever_its_code_says(self):
        listing = yssl.Listing("1", "U11/5SW1", "RUSH SOUTH 15/16 GIRLS", "CHRM1112")
        in_scope, _ = yssl.build_roster({"CHR": ("CHICAGO RUSH", [listing])}, RUSH, 2026)
        assert (in_scope[0].gender, in_scope[0].age_group) == ("Female", "u11")

    @pytest.mark.parametrize(
        ("team_name", "site_club", "mapped_club", "written"),
        [
            (
                "HAWTHORN WOODS ELITE 16/17 BLACK",
                "HAWTHORN WOODS ELITE SOCCER CLUB",
                "Hawthorn Woods Elite SC",
                "HAWTHORN WOODS ELITE",
            ),
            ("AAC EAGLES CHICAGO 14/15 GOLD", "AAC EAGLES CHICAGO", "AAC Eagles", "AAC EAGLES CHICAGO"),
            ("PEGASUS FC 12 /13 BLACK", "PEGASUS FC", "Pegasus FC", "PEGASUS FC"),
            ("UESC - BSC RAIDERS 16/17 BLACK", "UNITED ELITE SOCCER CLUB", "United Elite", "UNITED ELITE SOCCER CLUB"),
        ],
        ids=["shorter-than-site", "whole-site-name", "with-fc", "no-club-words"],
    )
    def test_the_written_club_is_the_club_words_leading_the_team_name(self, team_name, site_club, mapped_club, written):
        club_map = {"XYZ": [yssl.ClubEntry("XYZ", site_club, mapped_club, "owner")]}
        listing = yssl.Listing("1", "U10/1", team_name, "XYZM101")
        in_scope, _ = yssl.build_roster({"XYZ": (site_club, [listing])}, club_map, 2026)
        assert in_scope[0].club_as_written == written

    def test_f_code_is_female(self):
        listing = yssl.Listing("1", "U12/1", "X 14/15", "AACF121")
        in_scope, _ = yssl.build_roster({"AAC": ("AAC", [listing])}, _club_map(AAC="AAC Eagles"), 2026)
        assert in_scope[0].gender == "Female"

    @pytest.mark.parametrize(
        ("listing", "club_map", "reason"),
        [
            (yssl.Listing("1", "U12/1", "X 14/15", "AACM121"), {}, "club AAC not in club map"),
            (
                yssl.Listing("1", "U12/1", "X 14/15", "AACX121"),
                _club_map(AAC="AAC Eagles"),
                "team code AACX121 names no gender",
            ),
            (
                yssl.Listing("1", "U08-5V5/4S", "X 18/19", "AACM081"),
                _club_map(AAC="AAC Eagles"),
                "no U10-U19 board (band 18/19)",
            ),
        ],
        ids=["unmapped-club", "bad-gender", "no-board"],
    )
    def test_left_out_with_reason(self, listing, club_map, reason):
        in_scope, left_out = yssl.build_roster({"AAC": ("AAC EAGLES CHICAGO", [listing])}, club_map, 2026)
        assert in_scope == []
        assert left_out[0].skip_reason == reason


class TestLoadClubMap:
    def test_undecided_rows_are_omitted(self, tmp_path):
        path = tmp_path / "map.csv"
        path.write_text(
            "yssl_code,yssl_name,team_prefix,pitchrank_club_name,decided_by,note\n"
            "AAC,AAC EAGLES CHICAGO,,AAC Eagles,auto-exact,\n"
            "CHR,CHICAGO RUSH,,Chicago Rush Soccer Club,owner,\n"
            "CHR,CHICAGO RUSH,RUSH NORTH,Chicago Rush North Shore,owner,\n"
            "RSN,RUSH SOUTH,,,,candidates: Chicago Rush Soccer Club\n"
            "XYZ,XYZ FC,,Xyz FC,,\n",
            encoding="utf-8",
        )
        club_map = yssl.load_club_map(path)
        assert sorted(club_map) == ["AAC", "CHR"]
        assert [(e.team_prefix, e.pitchrank_club_name) for e in club_map["CHR"]] == [
            ("", "Chicago Rush Soccer Club"),
            ("RUSH NORTH", "Chicago Rush North Shore"),
        ]

    def test_state_defaults_to_il_and_reads_a_listed_state(self, tmp_path):
        path = tmp_path / "map.csv"
        path.write_text(
            "yssl_code,yssl_name,team_prefix,pitchrank_club_name,state_code,decided_by,note\n"
            "AAC,AAC EAGLES CHICAGO,,AAC Eagles,,auto-exact,\n"
            "NWI,NWI LIONS UNITED,,NWI Lions United,IN,owner,\n",
            encoding="utf-8",
        )
        club_map = yssl.load_club_map(path)
        assert (club_map["AAC"][0].state_code, club_map["NWI"][0].state_code) == ("IL", "IN")

    def test_the_committed_map_loads(self):
        yssl.load_club_map(yssl.CLUB_MAP_PATH)

    def test_wilmette_wings_and_north_shore_teams_map_to_wilmette_wings_sc(self):
        club_map = yssl.load_club_map(yssl.CLUB_MAP_PATH)
        names = ["RUSH - WILMETTE WINGS 15/16B BLUE", "RUSH NORTH SHORE 13/14B BLUE", "RUSH NORTH 16/17 PREMIER"]
        assert [yssl.club_entry_for(club_map["CHR"], n).pitchrank_club_name for n in names] == [
            "Wilmette Wings SC",
            "Wilmette Wings SC",
            "Chicago Rush Soccer Club",
        ]

    def test_every_club_on_the_saved_club_list_is_decided(self):
        club_map = yssl.load_club_map(yssl.CLUB_MAP_PATH)
        listed = yssl.parse_club_list(_fixture("clublinks.html"))
        assert [code for code in listed if code not in club_map] == []


def _write_csv(path, columns, rows):
    yssl.write_csv(path, columns, rows)
    return path


def _report_row(team_code, name, club_code, division="U11/2C", tea_id="9"):
    return {"team_code": team_code, "tea_id": tea_id, "team_name": name, "club_code": club_code, "division": division}


JAKES = yssl.Listing("9", "U11/2C", "JAKE'S STARS FC 2015/16 STORM", "JSFM111")
AAC_GOLD = yssl.Listing("130249", "U10/1", "AAC EAGLES CHICAGO 16/17 GOLD", "AACM101")


class TestRoster:
    def test_a_report_row_is_a_listing_under_its_club(self, tmp_path):
        path = _write_csv(
            tmp_path / "r.csv", yssl.REPORT_COLUMNS, [_report_row("2026-JSFM111", JAKES.team_name, "JSF")]
        )
        assert yssl.load_roster([path], 2026) == {"JSF": [JAKES]}

    def test_another_seasons_rows_are_left_out(self, tmp_path):
        path = _write_csv(
            tmp_path / "r.csv", yssl.REPORT_COLUMNS, [_report_row("2025-JSFM111", JAKES.team_name, "JSF")]
        )
        assert yssl.load_roster([path], 2026) == {}

    def test_a_team_a_club_page_lists_keeps_that_listing(self):
        clubs = {"AAC": ("AAC EAGLES CHICAGO", [AAC_GOLD])}
        fall_name = yssl.Listing("1", "U10/2", "AAC EAGLES CHICAGO 16/17 GOLD FALL", "AACM101")
        red = yssl.Listing("2", "U10/3", "AAC EAGLES CHICAGO 16/17 RED", "AACM103")
        merged = yssl.with_roster(clubs, {"AAC": [fall_name, red], "JSF": [JAKES]})
        assert merged == {"AAC": ("AAC EAGLES CHICAGO", [AAC_GOLD, red]), "JSF": ("", [JAKES])}
        assert clubs == {"AAC": ("AAC EAGLES CHICAGO", [AAC_GOLD])}

    def test_a_team_in_two_rosters_is_listed_once(self, tmp_path):
        path = _write_csv(
            tmp_path / "r.csv", yssl.REPORT_COLUMNS, [_report_row("2026-JSFM111", JAKES.team_name, "JSF")]
        )
        assert yssl.with_roster({}, yssl.load_roster([path, path], 2026)) == {"JSF": ("", [JAKES])}

    def test_a_renamed_team_answers_to_both_names_and_a_shared_name_to_both_teams(self):
        fall_name = yssl.Listing("1", "U10/2", "AAC EAGLES CHICAGO 16/17 GOLD FALL", "AACM101")
        namesake = yssl.Listing("3", "U10/4", "AAC EAGLES CHICAGO 16/17 GOLD", "AACM104")
        codes = yssl.codes_by_name({"AAC": ("AAC EAGLES CHICAGO", [AAC_GOLD])}, {"AAC": [fall_name, namesake]})
        assert codes == {
            "AAC EAGLES CHICAGO 16/17 GOLD": {"AACM101", "AACM104"},
            "AAC EAGLES CHICAGO 16/17 GOLD FALL": {"AACM101"},
        }


def _row(code, age="u12"):
    return yssl.TeamRow(
        code, "1", f"TEAM {code} 14/15", "U12/1", code[:3], code[:3], code[:3], age, "band 14/15", "Male"
    )


def _game(no, home, away, day=date(2026, 10, 3)):
    return yssl.Game(no, day, "10:00am", home, away, 2, 1, "FIELD", "https://www.yssl.org/team.php?tea_id=1")


def _linked(*codes):
    return {code: yssl.Outcome("already_linked", f"m-{code}", 1.0) for code in codes}


TODAY = date(2026, 10, 7)
PAIR = [_row("AACM121"), _row("ECLM121")]


class TestBuildCsvRows:
    def test_two_rows_per_linked_game_with_il_and_scores(self):
        game = _game("4267", "AACM121", "ECLM121")
        rows, held, _ = yssl.build_csv_rows([game], PAIR, _linked("AACM121", "ECLM121"), 14, TODAY)
        assert held == []
        assert [
            (r["team_id"], r["opponent_id"], r["home_away"], r["goals_for"], r["goals_against"], r["state_code"])
            for r in rows
        ] == [("AACM121", "ECLM121", "H", 2, 1, "IL"), ("ECLM121", "AACM121", "A", 1, 2, "IL")]
        assert {(r["provider"], r["schedule_id"], r["event_name"], r["state"]) for r in rows} == {
            ("yssl", "yssl-4267", "YSSL Fall 2026 - U12/1", "Illinois")
        }

    def test_a_spring_game_is_named_spring(self):
        game = _game("9", "AACM121", "ECLM121", day=date(2027, 4, 18))
        rows, _, _ = yssl.build_csv_rows([game], PAIR, _linked("AACM121", "ECLM121"), 14, date(2027, 4, 20))
        assert rows[0]["event_name"] == "YSSL Spring 2027 - U12/1"

    def test_an_unlinked_team_holds_the_game(self):
        outcomes = {**_linked("AACM121"), "ECLM121": yssl.Outcome("review")}
        rows, held, _ = yssl.build_csv_rows([_game("1", "AACM121", "ECLM121")], PAIR, outcomes, 14, TODAY)
        assert rows == []
        assert [g.game_no for g in held] == ["1"]

    def test_an_opponent_outside_the_roster_holds_the_game(self):
        game = _game("1", "AACM121", "ZZZM121")
        rows, held, _ = yssl.build_csv_rows([game], [_row("AACM121")], _linked("AACM121"), 14, TODAY)
        assert rows == []
        assert [g.game_no for g in held] == ["1"]

    @pytest.mark.parametrize("day", [date(2026, 9, 22), date(2026, 10, 8)], ids=["too-old", "future"])
    def test_games_outside_the_window_are_dropped(self, day):
        game = _game("1", "AACM121", "ECLM121", day=day)
        rows, held, _ = yssl.build_csv_rows([game], PAIR, _linked("AACM121", "ECLM121"), 14, TODAY)
        assert (rows, held) == ([], [])

    def test_a_cross_age_game_is_imported_and_listed(self):
        roster = [_row("AACM121"), _row("ECLM131", age="u13")]
        game = _game("1", "AACM121", "ECLM131")
        rows, _, cross_age = yssl.build_csv_rows([game], roster, _linked("AACM121", "ECLM131"), 14, TODAY)
        assert len(rows) == 2
        assert [(c["home_age_group"], c["away_age_group"]) for c in cross_age] == [("u12", "u13")]

    def test_an_archive_game_is_named_for_its_own_division(self):
        game = replace(_game("1", "AACM121", "ECLM131"), division="U12/3W")
        roster = [_row("AACM121"), _row("ECLM131", age="u13")]
        rows, _, cross_age = yssl.build_csv_rows([game], roster, _linked("AACM121", "ECLM131"), 14, TODAY)
        assert {r["event_name"] for r in rows} == {"YSSL Fall 2026 - U12/3W"}
        assert [c["division"] for c in cross_age] == ["U12/3W"]


def _scored(no, home, away, home_score, away_score, day=date(2026, 10, 3)):
    return replace(_game(no, home, away, day=day), home_score=home_score, away_score=away_score)


def _stored(home, away, home_score, away_score, day="2026-09-13"):
    return {
        "game_date": day,
        "home_provider_id": home,
        "away_provider_id": away,
        "home_score": home_score,
        "away_score": away_score,
    }


def _receipt(home, away, home_score, away_score, day="2026-09-13"):
    return (day, home, away, home_score, away_score)


ONE_DAY = "game {}: another game between these teams is dated 2026-10-03, and the importer keeps one a day"


class TestAlreadyStored:
    def test_an_imported_games_csv_gives_each_number_every_copy_it_recorded(self, tmp_path):
        first = [
            {"schedule_id": "yssl-117", "team_id": "2026-EVLM111", "opponent_id": "2026-OPSM111", "home_away": "H"}
            | {"game_date": "2026-09-13", "goals_for": 3, "goals_against": 2},
            {"schedule_id": "yssl-117", "team_id": "2026-OPSM111", "opponent_id": "2026-EVLM111", "home_away": "A"}
            | {"game_date": "2026-09-13", "goals_for": 2, "goals_against": 3},
        ]
        later = [first[0] | {"goals_against": 1}]
        paths = [
            _write_csv(tmp_path / "first.csv", yssl.REQUIRED_COLUMNS, first),
            _write_csv(tmp_path / "later.csv", yssl.REQUIRED_COLUMNS, later),
        ]
        assert yssl.imported_games(paths) == {
            "117": {
                ("2026-09-13", "2026-EVLM111", "2026-OPSM111", 3, 2),
                ("2026-09-13", "2026-EVLM111", "2026-OPSM111", 3, 1),
            }
        }

    def test_an_imported_number_claims_its_stored_copy(self):
        game = _scored("1", "A", "B", 4, 0)
        assert yssl.unstored_games([game], {"1": {_receipt("A", "B", 4, 0)}}, [_stored("A", "B", 4, 0)]) == ([], 1, [])

    def test_a_receipt_claims_whichever_recorded_copy_is_stored(self):
        receipts = {"1": {_receipt("A", "B", 4, 1), _receipt("A", "B", 4, 0)}}
        assert yssl.unstored_games([_scored("1", "A", "B", 4, 0)], receipts, [_stored("A", "B", 4, 0)]) == ([], 1, [])

    def test_a_receipt_written_with_home_and_away_the_other_way_still_claims_its_copy(self):
        receipts = {"1": {_receipt("B", "A", 0, 4)}}
        assert yssl.unstored_games([_scored("1", "A", "B", 4, 0)], receipts, [_stored("B", "A", 0, 4)]) == ([], 1, [])

    def test_an_imported_number_with_other_teams_is_held_as_a_problem(self):
        receipts = {"1": {_receipt("A", "C", 2, 1)}}
        fresh, already, problems = yssl.unstored_games([_scored("1", "A", "B", 2, 1)], receipts, [])
        assert (fresh, already, problems) == ([], 0, ["game 1: the archive's teams are not the imported game's"])

    @pytest.mark.parametrize(
        "stored", [[], [_stored("A", "B", 2, 1, "2026-10-18")]], ids=["nothing-stored", "stored-on-another-date"]
    )
    def test_an_imported_number_whose_recorded_game_is_not_stored_is_held_as_a_problem(self, stored):
        receipts = {"1": {_receipt("A", "B", 2, 1)}}
        fresh, already, problems = yssl.unstored_games([_scored("1", "A", "B", 2, 1)], receipts, stored)
        assert (fresh, already) == ([], 0)
        assert problems[0] == "game 1: listed as imported, but no stored game matches it"

    def test_an_imported_game_claims_its_recorded_copy_when_the_archive_score_has_changed(self):
        corrected = _scored("1", "A", "B", 1, 2)
        rematch = _scored("9", "A", "B", 2, 1, day=date(2026, 10, 17))
        receipts = {"1": {_receipt("A", "B", 2, 1)}}
        fresh, already, _ = yssl.unstored_games([rematch, corrected], receipts, [_stored("A", "B", 2, 1)])
        assert (fresh, already) == ([rematch], 1)

    def test_a_stored_game_with_the_same_sides_and_score_is_stored_whatever_its_date(self):
        assert yssl.unstored_games([_scored("7", "A", "B", 2, 1)], {}, [_stored("A", "B", 2, 1)]) == ([], 1, [])

    @pytest.mark.parametrize(
        "first_leg", [("B", "A", 1, 2), ("A", "B", 1, 2)], ids=["home-and-away-swapped", "another-score"]
    )
    def test_another_meeting_of_the_same_teams_is_a_new_game(self, first_leg):
        game = _scored("7", "A", "B", 2, 1)
        receipts = {"1": {_receipt(*first_leg)}}
        games = [_scored("1", *first_leg, day=date(2026, 9, 12)), game]
        assert yssl.unstored_games(games, receipts, [_stored(*first_leg)]) == ([game], 1, [])

    def test_a_stored_game_that_answers_for_no_archive_game_holds_its_teams_new_games(self):
        fresh, already, problems = yssl.unstored_games([_scored("7", "A", "B", 3, 1)], {}, [_stored("A", "B", 2, 1)])
        assert (fresh, already, problems) == (
            [],
            0,
            ["game 7: a stored game between these teams answers for no archive game"],
        )

    def test_a_stored_game_matched_by_teams_and_score_frees_its_teams_new_games(self):
        stored_leg, new_leg = _scored("7", "A", "B", 2, 1), _scored("9", "B", "A", 3, 3, day=date(2026, 10, 17))
        assert yssl.unstored_games([stored_leg, new_leg], {}, [_stored("A", "B", 2, 1)]) == ([new_leg], 1, [])

    @pytest.mark.parametrize(
        ("copies", "expected"),
        [(1, ([], 0, 2)), (2, ([], 2, 0)), (3, ([], 2, 0))],
        ids=["unclear", "covered", "more-copies-than-games"],
    )
    def test_games_sharing_teams_and_score_are_stored_only_when_every_one_has_a_copy(self, copies, expected):
        games = [_scored("7", "A", "B", 2, 1), _scored("9", "A", "B", 2, 1, day=date(2026, 10, 17))]
        fresh, already, problems = yssl.unstored_games(games, {}, [_stored("A", "B", 2, 1)] * copies)
        assert (fresh, already, len(problems)) == expected
        assert all("share these teams and score" in problem for problem in problems)

    def test_a_game_held_on_its_receipt_still_competes_for_the_stored_copies(self):
        held = _scored("1", "A", "B", 2, 1)
        other = _scored("9", "A", "B", 2, 1, day=date(2026, 10, 17))
        receipts = {"1": {_receipt("A", "B", 3, 0)}}
        fresh, already, problems = yssl.unstored_games([held, other], receipts, [_stored("A", "B", 2, 1)])
        assert (fresh, already, len(problems)) == ([], 0, 2)
        assert "share these teams and score" in problems[1]

    @pytest.mark.parametrize("home_away", [("A", "B", 5, 2), ("B", "A", 0, 3)], ids=["same-sides", "swapped"])
    def test_a_new_game_on_a_stored_games_date_between_its_teams_is_held(self, home_away):
        stored = [_stored(*home_away, day="2026-10-03")]
        games = [_scored("1", *home_away, day=date(2026, 9, 26)), _scored("7", "A", "B", 2, 1)]
        receipts = {"1": {_receipt(*home_away, day="2026-10-03")}}
        assert yssl.unstored_games(games, receipts, stored) == ([], 1, [ONE_DAY.format(7)])

    def test_a_second_new_game_between_the_same_teams_on_one_date_is_held(self):
        first, second = _scored("7", "A", "B", 2, 1), _scored("9", "B", "A", 3, 3)
        fresh, _, problems = yssl.unstored_games([first, second], {}, [])
        assert (fresh, problems) == ([first], [ONE_DAY.format(9)])


class _FakeMatcher:
    instances = []
    results = {}

    def __init__(self, supabase, provider_id=None, registration_mode=False, dry_run=False):
        self.dry_run = dry_run
        self.registration_mode = registration_mode
        self.calls = []
        _FakeMatcher.instances.append(self)

    def _match_team(self, **kwargs):
        self.calls.append(kwargs)
        code = kwargs["provider_team_id"]
        created = {"matched": True, "team_id": f"new-{code}", "method": "direct_id", "created": True, "confidence": 1.0}
        return _FakeMatcher.results.get(code, created)


class _ProvidersClient:
    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "yssl-provider"}])


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


CLUBS = {
    "AAC": ("AAC EAGLES CHICAGO", [yssl.Listing("1", "U12/1", "AAC EAGLES CHICAGO 14/15 GOLD", "AACM121")]),
    "ECL": ("ECLIPSE", [yssl.Listing("2", "U12/1", "ECLIPSE 14/15 DARIEN", "ECLM121")]),
    "XYZ": ("XYZ FC", [yssl.Listing("3", "U12/1", "XYZ FC 14/15", "XYZM121")]),
}
SIDES = [
    _side("1", "AACM121", "ECLM121", "H", 2, 3, day=date(2026, 10, 3)),
    _side("1", "ECLM121", "AACM121", "A", 3, 2, day=date(2026, 10, 3)),
    _side("2", "AACM121", "XYZM121", "A", 1, 1, day=date(2026, 10, 4)),
]
EVERY_CLUB = {"AAC": "AAC Eagles", "ECL": "Eclipse Select Soccer Club", "XYZ": "Xyz FC"}


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    def run(
        *flags,
        club_map=None,
        import_rc=0,
        results=None,
        already=None,
        saved=None,
        queued=None,
        teams=None,
        collect_error=None,
        collect_problems=(),
        pages=None,
        stored=(),
        sides=SIDES,
        real_collect=False,
    ):
        _FakeMatcher.instances = []
        _FakeMatcher.results = results or {}
        imports = []
        walked = []
        stored_reads = []
        mapped = club_map if club_map is not None else _club_map(AAC="AAC Eagles", ECL="Eclipse Select Soccer Club")

        def fake_collect(_fetch, clubs, season, pause=None, archive=None):
            walked.append((clubs, season, archive))
            if collect_error:
                raise collect_error
            return CLUBS, [] if archive else sides, list(collect_problems)

        def fake_stored_games(_client, _provider_id, start, end):
            stored_reads.append((start, end))
            return list(stored)

        def fake_get(_session, url):
            if url not in (pages or {}):
                raise yssl.ScrapeFetchError(f"HTTP 404 for {url}")
            return SimpleNamespace(text=pages[url])

        def fake_existing_aliases(_client, _provider_id, codes):
            if not (_FakeMatcher.instances and not _FakeMatcher.instances[-1].dry_run):
                return {code: team for code, team in (already or {}).items() if code in codes}
            if saved is not None:
                return saved
            linked = {code: r["team_id"] for code, r in (results or {}).items() if r.get("team_id")}
            return {code: linked.get(code, f"new-{code}") for code in codes}

        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(yssl, "create_client", lambda *_a: _ProvidersClient())
        monkeypatch.setattr(yssl, "make_session", lambda: None)
        monkeypatch.setattr(yssl, "_get", fake_get)
        if not real_collect:
            monkeypatch.setattr(yssl, "collect_league", fake_collect)
        monkeypatch.setattr(yssl, "stored_games", fake_stored_games)
        monkeypatch.setattr(yssl, "load_club_map", lambda _path: mapped)
        monkeypatch.setattr(yssl, "YSSLGameMatcher", _FakeMatcher)
        monkeypatch.setattr(yssl, "existing_aliases", fake_existing_aliases)
        monkeypatch.setattr(yssl, "pending_reviews", lambda _c, codes: set(codes) if queued is None else queued)
        monkeypatch.setattr(yssl, "teams_by_id", lambda _c, ids: {i: t for i, t in (teams or {}).items() if i in ids})
        monkeypatch.setattr(yssl, "_soccer_season_year", lambda now=None: 2026)
        monkeypatch.setattr(yssl, "date", _FixedDate)
        monkeypatch.setattr(
            yssl.subprocess, "run", lambda cmd, check: imports.append(cmd) or SimpleNamespace(returncode=import_rc)
        )
        argv = ["import_yssl.py", "--output-dir", str(tmp_path), "--delay-min", "0", "--delay-max", "0"]
        monkeypatch.setattr(yssl.sys, "argv", [*argv, *flags])
        code = yssl.main()
        reports = list(tmp_path.glob("*_teams.csv"))
        games_csvs = list(tmp_path.glob("*_games.csv"))
        return SimpleNamespace(
            code=code,
            imports=imports,
            walked=walked,
            stored_reads=stored_reads,
            outcomes={r["team_code"]: r for p in reports for r in csv.DictReader(p.open(encoding="utf-8"))},
            games=[r for p in games_csvs for r in csv.DictReader(p.open(encoding="utf-8"))],
        )

    return run


class TestMain:
    def test_a_dry_run_builds_only_dry_run_matchers_and_starts_no_import(self, run_main):
        result = run_main(club_map=_club_map(**EVERY_CLUB))
        assert result.code == 0
        assert result.imports == []
        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True)]

    def test_the_matcher_gets_the_mapped_club_and_the_written_one(self, run_main):
        run_main()
        aac = next(c for c in _FakeMatcher.instances[0].calls if c["provider_team_id"] == "2026-AACM121")
        assert (aac["club_name"], aac["written_club"], aac["state_code"], aac["age_group"], aac["gender"]) == (
            "AAC Eagles",
            "AAC EAGLES CHICAGO",
            "IL",
            "u12",
            "Male",
        )

    def test_execute_imports_the_games_csv(self, run_main):
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB))
        assert result.code == 0
        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True), (False, True)]
        [command] = result.imports
        assert command[1] == "scripts/import_games_enhanced.py"
        assert command[2].endswith("_games.csv")
        assert command[3] == "yssl"
        assert sorted({r["schedule_id"] for r in result.games}) == ["yssl-1", "yssl-2"]

    def test_an_unmapped_club_is_left_out_and_fails_the_run(self, run_main):
        result = run_main("--execute")
        assert result.code == 1
        assert result.outcomes["2026-XYZM121"]["outcome"] == "skipped"
        assert result.outcomes["2026-XYZM121"]["reason"] == "club XYZ not in club map"
        assert {r["schedule_id"] for r in result.games} == {"yssl-1"}
        assert len(result.imports) == 1

    def test_an_unmapped_club_fails_a_dry_run_too(self, run_main):
        assert run_main().code == 1

    def test_the_importers_failure_is_the_runs_failure(self, run_main):
        assert run_main("--execute", club_map=_club_map(**EVERY_CLUB), import_rc=3).code == 3

    def test_named_clubs_are_passed_to_the_walk(self, run_main):
        result = run_main("--club", "AAC", "--club", "ECL")
        assert result.walked == [(["AAC", "ECL"], 2026, None)]

    @pytest.mark.parametrize(
        ("problem", "code"),
        [
            ("AACM121 game 7: unreadable row", 1),
            ("AACM121: games table not found", 1),
            ("game 7: the two teams' pages disagree", 1),
            ("AACM121 game 7: rained out", 0),
        ],
        ids=["unreadable", "no-table", "disagree", "rainout"],
    )
    def test_a_game_that_could_not_be_read_fails_the_run_unless_rained_out(self, run_main, problem, code):
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), collect_problems=[problem])
        assert (result.code, len(result.imports)) == (code, 1)

    def test_a_site_still_listing_another_season_registers_and_imports_nothing(self, run_main):
        stale = yssl.StaleSeasonError("yssl.org lists the 2025 season's teams")
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), collect_error=stale)
        assert (result.code, result.imports, _FakeMatcher.instances, result.outcomes) == (0, [], [], {})

    def test_a_weekly_run_reads_no_stored_games_and_imports_a_game_whose_result_is_stored(self, run_main):
        stored = [_stored("2026-AACM121", "2026-ECLM121", 2, 3)]
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), stored=stored)
        assert result.stored_reads == []
        assert "yssl-1" in {r["schedule_id"] for r in result.games}

    def test_a_weekly_run_registers_a_team_with_no_games(self, run_main):
        result = run_main(club_map=_club_map(**EVERY_CLUB), sides=SIDES[:2])
        assert "2026-XYZM121" in result.outcomes

    def test_a_weekly_run_keeps_its_window(self, run_main):
        sides = [_side("1", "AACM121", "ECLM121", "H", 2, 3, day=date(2026, 9, 12))]
        result = run_main(club_map=_club_map(**EVERY_CLUB), sides=sides)
        assert result.games == []


AAC_ID, ECL_ID, XYZ_ID = "2026-AACM121", "2026-ECLM121", "2026-XYZM121"
LINKED = {"matched": True, "method": "fuzzy_auto", "confidence": 0.95}


class TestMainGuards:
    def test_two_teams_on_one_pitchrank_team_are_held_as_conflicts_and_fail_the_run(self, run_main):
        results = {AAC_ID: {**LINKED, "team_id": "T1"}, ECL_ID: {**LINKED, "team_id": "T1"}}
        teams = {"T1": {"team_id_master": "T1", "team_name": "X", "age_group": "u12", "gender": "Male"}}
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), results=results, teams=teams)
        assert [result.outcomes[c]["outcome"] for c in (AAC_ID, ECL_ID)] == ["conflict", "conflict"]
        assert result.outcomes[AAC_ID]["reason"] == f"same PitchRank team as YSSL team {ECL_ID}"
        writer = _FakeMatcher.instances[1]
        assert [c["provider_team_id"] for c in writer.calls] == [XYZ_ID]
        assert result.games == []
        assert result.code == 1

    def test_a_link_that_was_not_saved_is_an_error(self, run_main):
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), saved={ECL_ID: f"new-{ECL_ID}"})
        aac = result.outcomes[AAC_ID]
        assert (aac["outcome"], aac["reason"]) == ("error", "link was not saved")
        assert result.code == 1

    def test_a_review_with_no_queue_row_is_an_error(self, run_main):
        results = {AAC_ID: {"matched": False, "method": "fuzzy_review", "review": True, "confidence": 0.8}}
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), results=results, queued=set())
        assert (result.outcomes[AAC_ID]["outcome"], result.outcomes[AAC_ID]["reason"]) == (
            "error",
            "review item was not saved",
        )

    def test_a_link_to_a_team_on_another_board_is_an_error(self, run_main):
        teams = {"T9": {"team_id_master": "T9", "team_name": "OLD", "age_group": "u13", "gender": "Male"}}
        result = run_main(club_map=_club_map(**EVERY_CLUB), already={AAC_ID: "T9"}, teams=teams)
        assert (result.outcomes[AAC_ID]["outcome"], result.outcomes[AAC_ID]["reason"]) == (
            "error",
            "linked team is on the u13 board, this team is u12",
        )
        assert result.games == []  # both games involve AAC
        assert result.code == 1

    def test_a_link_to_a_team_of_the_other_gender_is_an_error(self, run_main):
        teams = {"T9": {"team_id_master": "T9", "team_name": "OLD", "age_group": "u12", "gender": "Female"}}
        result = run_main(club_map=_club_map(**EVERY_CLUB), already={AAC_ID: "T9"}, teams=teams)
        assert (result.outcomes[AAC_ID]["outcome"], result.outcomes[AAC_ID]["reason"]) == (
            "error",
            "linked team is Female, this team is Male",
        )

    def test_a_link_to_a_missing_team_is_an_error(self, run_main):
        result = run_main(club_map=_club_map(**EVERY_CLUB), already={AAC_ID: "T9"}, teams={})
        assert (result.outcomes[AAC_ID]["outcome"], result.outcomes[AAC_ID]["reason"]) == (
            "error",
            "linked team not found",
        )

    def test_an_approved_link_keeps_its_team_when_a_new_match_lands_on_it(self, run_main):
        teams = {"T1": {"team_id_master": "T1", "team_name": "X", "age_group": "u12", "gender": "Male"}}
        results = {ECL_ID: {**LINKED, "team_id": "T1"}}
        result = run_main(
            "--execute", club_map=_club_map(**EVERY_CLUB), already={AAC_ID: "T1"}, results=results, teams=teams
        )
        assert [result.outcomes[c]["outcome"] for c in (AAC_ID, ECL_ID)] == ["already_linked", "conflict"]

    def test_a_link_saved_to_another_team_is_an_error(self, run_main):
        teams = {"T1": {"team_id_master": "T1", "team_name": "X", "age_group": "u12", "gender": "Male"}}
        saved = {AAC_ID: "OTHER", ECL_ID: f"new-{ECL_ID}", XYZ_ID: f"new-{XYZ_ID}"}
        results = {AAC_ID: {**LINKED, "team_id": "T1"}}
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB), results=results, teams=teams, saved=saved)
        assert (result.outcomes[AAC_ID]["outcome"], result.outcomes[AAC_ID]["reason"]) == (
            "error",
            "link was not saved",
        )

    def test_game_rows_carry_the_season_scoped_ids(self, run_main):
        result = run_main("--execute", club_map=_club_map(**EVERY_CLUB))
        assert {(r["team_id"], r["opponent_id"]) for r in result.games if r["schedule_id"] == "yssl-1"} == {
            (AAC_ID, ECL_ID),
            (ECL_ID, AAC_ID),
        }


ARCHIVE_TEXT = """\
                   FALL 2026 - AGE GROUP  U11/1S

Week: 1     Date: 09/12/2026      *Denotes Guest Player/s played game
 Game # Home Team                 Score    Visiting Team             Score
   101 AAC EAGLES CHICAGO 14/15 GOLD   2 Lose    ECLIPSE 14/15 DARIEN       3 Win
   102 XYZ FC 14/15                    1 Tie     JAKE'S STARS FC 2014/15 STORM  1 Tie
   103 ECLIPSE 14/15 DARIEN            4 Win*    JAKE'S STARS FC 2014/15 STORM  0 Lose
   104 AAC EAGLES CHICAGO 14/15 GOLD   5 Win     XYZ FC 14/15               0 Lose
"""
ARCHIVE_PAGES = {
    INDEX_URL: _fixture("pastscores_FALL2026.html"),
    f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U10-1.TXT": "",
    ARCHIVE_URL: ARCHIVE_TEXT,
    f"{yssl.BASE_URL}/PASTSCORES/FALL2026/U11-5W.TXT": "",
}
JSF_ID = "2026-JSFM121"


def _archive_flags(tmp_path, imported_no="101"):
    roster = _write_csv(
        tmp_path / "in" / "roster.csv",
        yssl.REPORT_COLUMNS,
        [_report_row(JSF_ID, "JAKE'S STARS FC 2014/15 STORM", "JSF", division="U12/2")],
    )
    imported_row = {"schedule_id": f"yssl-{imported_no}", "team_id": AAC_ID, "opponent_id": ECL_ID}
    imported = _write_csv(
        tmp_path / "in" / "imported.csv",
        yssl.REQUIRED_COLUMNS,
        [imported_row | {"home_away": "H", "game_date": "2026-09-13", "goals_for": 2, "goals_against": 3}],
    )
    return ["--archive", "FALL2026", "--roster", str(roster), "--imported", str(imported)]


@pytest.fixture
def archive_inputs(tmp_path):
    return _archive_flags(tmp_path)


ARCHIVE_STORED = [_stored(AAC_ID, ECL_ID, 2, 3), _stored(AAC_ID, XYZ_ID, 5, 0)]


class TestMainArchive:
    def _run(self, run_main, flags, *extra, **overrides):
        options = {"club_map": _club_map(**EVERY_CLUB, JSF="Jake's Stars FC"), "stored": ARCHIVE_STORED}
        return run_main(*flags, *extra, pages=ARCHIVE_PAGES, **{**options, **overrides})

    def test_reads_club_pages_only_and_imports_the_unstored_games(self, run_main, archive_inputs):
        result = self._run(run_main, archive_inputs, "--execute")
        assert result.code == 0
        assert result.walked == [(None, 2026, "FALL2026")]
        assert result.stored_reads == [(date(2026, 8, 1), date(2027, 1, 1))]
        assert sorted({r["schedule_id"] for r in result.games}) == ["yssl-102", "yssl-103"]
        assert len(result.imports) == 1

    def test_game_rows_carry_the_archive_week_and_division_whatever_the_window(self, run_main, archive_inputs):
        result = self._run(run_main, archive_inputs)
        assert {(r["game_date"], r["event_name"], r["game_time"], r["venue"]) for r in result.games} == {
            ("2026-09-12", "YSSL Fall 2026 - U11/1S", "", "")
        }

    def test_the_window_reaches_back_to_the_start_of_the_season(self, run_main, archive_inputs, monkeypatch):
        monkeypatch.setitem(ARCHIVE_PAGES, ARCHIVE_URL, ARCHIVE_TEXT.replace("09/12/2026", "08/01/2026"))
        result = self._run(run_main, archive_inputs)
        assert {r["game_date"] for r in result.games} == {"2026-08-01"}

    def test_only_the_teams_of_games_to_import_are_registered(self, run_main, archive_inputs):
        result = self._run(run_main, archive_inputs)
        assert set(result.outcomes) == {ECL_ID, XYZ_ID, JSF_ID}
        assert result.outcomes[JSF_ID]["outcome"] == "created"
        assert {c["provider_team_id"] for c in _FakeMatcher.instances[0].calls} == {ECL_ID, XYZ_ID, JSF_ID}

    def test_a_linked_team_with_no_games_still_holds_its_team_against_a_new_link(self, run_main, archive_inputs):
        teams = {"T1": {"team_id_master": "T1", "team_name": "X", "age_group": "u12", "gender": "Male"}}
        results = {ECL_ID: {**LINKED, "team_id": "T1"}}
        result = self._run(run_main, archive_inputs, already={AAC_ID: "T1"}, results=results, teams=teams)
        assert [result.outcomes[code]["outcome"] for code in (AAC_ID, ECL_ID)] == ["already_linked", "conflict"]
        assert result.code == 1

    def test_an_unmapped_club_playing_an_archive_game_is_left_out_and_fails_the_run(self, run_main, archive_inputs):
        club_map = _club_map(AAC="AAC Eagles", ECL="Eclipse Select Soccer Club", JSF="Jake's Stars FC")
        result = self._run(run_main, archive_inputs, club_map=club_map)
        assert (result.outcomes[XYZ_ID]["outcome"], result.outcomes[XYZ_ID]["reason"]) == (
            "skipped",
            "club XYZ not in club map",
        )
        assert result.code == 1

    def test_an_unmapped_club_with_no_game_to_import_does_not_fail_the_run(self, run_main, archive_inputs):
        club_map = _club_map(AAC="AAC Eagles", ECL="Eclipse Select Soccer Club", JSF="Jake's Stars FC")
        stored = [*ARCHIVE_STORED, _stored(XYZ_ID, JSF_ID, 1, 1)]
        result = self._run(run_main, archive_inputs, club_map=club_map, stored=stored)
        assert XYZ_ID not in result.outcomes
        assert result.code == 0

    def test_a_club_page_still_listing_the_term_stops_the_run(self, run_main, archive_inputs):
        live = yssl.LiveTermError("yssl.org still lists the FALL2026 teams")
        result = self._run(run_main, archive_inputs, "--execute", collect_error=live)
        assert (result.code, result.imports, _FakeMatcher.instances, result.games) == (1, [], [], [])

    def test_a_name_naming_no_team_holds_its_game_and_fails_the_run(self, run_main, archive_inputs, monkeypatch):
        unknown = "   105 NOBODY FC 14/15                 1 Win     XYZ FC 14/15               0 Lose\n"
        monkeypatch.setitem(ARCHIVE_PAGES, ARCHIVE_URL, ARCHIVE_TEXT + unknown)
        result = self._run(run_main, archive_inputs)
        assert result.code == 1
        assert sorted({r["schedule_id"] for r in result.games}) == ["yssl-102", "yssl-103"]

    def test_an_imported_number_naming_other_teams_holds_its_game_and_fails_the_run(self, run_main, tmp_path):
        result = self._run(run_main, _archive_flags(tmp_path, imported_no="102"))
        assert result.code == 1
        assert sorted({r["schedule_id"] for r in result.games}) == ["yssl-103"]

    @pytest.mark.parametrize("code", ["FALL2025", "SPRING2027", "fall2026"])
    def test_an_archive_other_than_this_seasons_fall_term_stops_before_anything_is_read(self, run_main, code):
        result = self._run(run_main, ["--archive", code])
        assert (result.code, result.walked, _FakeMatcher.instances, result.games) == (1, [], [], [])

    def test_an_archive_run_takes_no_named_clubs(self, run_main, archive_inputs):
        with pytest.raises(SystemExit) as stopped:
            self._run(run_main, archive_inputs, "--club", "AAC")
        assert stopped.value.code == 2


LEAGUE = {
    "AAC": ("AAC EAGLES CHICAGO", "AAC EAGLES CHICAGO 14/15 GOLD", "AACM121"),
    "ECL": ("ECLIPSE", "ECLIPSE 14/15 DARIEN", "ECLM121"),
    "XYZ": ("XYZ FC", "XYZ FC 14/15", "XYZM121"),
}


def _club_page(term, club, team_name, team_code):
    heading = f"<div>&nbsp;{term} Teams&nbsp;</div>" if term else ""
    listing = f'<tr><td><a href="team.php?tea_id=1">U12/1&nbsp;{team_name}</a></td><td>{team_code}</td></tr>'
    return f"<html><body>{heading}<span><b>Club</b></span>: {club}<br><table>{listing}</table></body></html>"


def _league_pages(term, straggler=None):
    """The archive pages plus a club list and club pages on ``term``; a straggler club shows its own."""
    clubs = {code: (term, *club) for code, club in LEAGUE.items()}
    if straggler:
        clubs["ZZZ"] = (straggler, "ZZZ FC", "ZZZ FC 14/15", "ZZZM121")
    pages = dict(ARCHIVE_PAGES)
    pages[f"{yssl.BASE_URL}/clublinks.php"] = "".join(f'<a href="club.php?clu_code={c}">{c}</a>' for c in clubs)
    for code, page in clubs.items():
        pages[f"{yssl.BASE_URL}/club.php?clu_code={code}"] = _club_page(*page)
    return pages


class TestMainArchiveThroughTheClubPages:
    def _run(self, run_main, flags, pages):
        club_map = _club_map(**EVERY_CLUB, JSF="Jake's Stars FC")
        return run_main(*flags, real_collect=True, pages=pages, club_map=club_map, stored=ARCHIVE_STORED)

    @pytest.mark.parametrize("straggler", [None, "Fall 2026", "Spring 2026"], ids=["none", "on-fall", "earlier-season"])
    def test_a_finished_fall_term_imports_once_the_club_pages_list_spring(self, run_main, archive_inputs, straggler):
        result = self._run(run_main, archive_inputs, _league_pages("Spring 2027", straggler))
        assert result.code == 0
        assert sorted({r["schedule_id"] for r in result.games}) == ["yssl-102", "yssl-103"]

    def test_a_fall_term_the_club_pages_still_list_stops_the_run(self, run_main, archive_inputs):
        result = self._run(run_main, ["--execute", *archive_inputs], _league_pages("Fall 2026"))
        assert (result.code, result.imports, _FakeMatcher.instances, result.games) == (1, [], [], [])


class TestQueries:
    def test_only_approved_aliases_of_this_provider_count_as_links(self):
        db = _DB()
        db.rows["team_alias_map"] = [
            {"provider_id": "P", "provider_team_id": AAC_ID, "team_id_master": "T1", "review_status": "approved"},
            {"provider_id": "P", "provider_team_id": ECL_ID, "team_id_master": "T2", "review_status": "pending"},
            {"provider_id": "Q", "provider_team_id": XYZ_ID, "team_id_master": "T3", "review_status": "approved"},
        ]
        assert yssl.existing_aliases(db, "P", [AAC_ID, ECL_ID, XYZ_ID]) == {AAC_ID: "T1"}

    def test_only_pending_yssl_reviews_count_as_queued(self):
        db = _DB()
        db.rows["team_match_review_queue"] = [
            {"provider_id": "yssl", "provider_team_id": AAC_ID, "status": "pending"},
            {"provider_id": "yssl", "provider_team_id": ECL_ID, "status": "approved"},
            {"provider_id": "athletes2events", "provider_team_id": XYZ_ID, "status": "pending"},
        ]
        assert yssl.pending_reviews(db, [AAC_ID, ECL_ID, XYZ_ID]) == {AAC_ID}

    def test_teams_are_read_by_master_id(self):
        db = _DB([{"team_id_master": t, "team_name": t, "age_group": "u12", "gender": "Male"} for t in ("T1", "T2")])
        assert list(yssl.teams_by_id(db, ["T1"])) == ["T1"]

    def test_stored_games_are_this_providers_games_in_the_term_read_in_id_order(self):
        db = _DB()
        dates = ["2026-07-31", "2026-08-01", "2026-12-31", "2027-01-01"]
        db.rows["games"] = [
            {"id": f"{i}", "provider_id": "P", "game_date": day} | _stored(f"2026-H{i}", "2026-A", 1, 0, day)
            for i, day in enumerate(dates)
        ] + [{"id": "9", "provider_id": "Q"} | _stored("2026-Q", "2026-A", 1, 0, "2026-10-03")]
        found = yssl.stored_games(db, "P", date(2026, 8, 1), date(2027, 1, 1))
        assert found == [
            _stored("2026-H1", "2026-A", 1, 0, "2026-08-01"),
            _stored("2026-H2", "2026-A", 1, 0, "2026-12-31"),
        ]
        assert [(filters, order) for filters, _, order in db.reads("games")] == [({"provider_id": "P"}, "id")] * 2

    def test_lookups_go_out_100_ids_at_a_time(self):
        db = _DB()
        yssl.existing_aliases(db, "P", [f"2026-C{i:03d}" for i in range(250)])
        assert [len(filters["provider_team_id"]) for filters, _, _ in db.reads("team_alias_map")] == [100, 100, 50]
