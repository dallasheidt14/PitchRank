"""Unit tests for the YSSL driver."""

import csv
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
    ):
        _FakeMatcher.instances = []
        _FakeMatcher.results = results or {}
        imports = []
        walked = []
        mapped = club_map if club_map is not None else _club_map(AAC="AAC Eagles", ECL="Eclipse Select Soccer Club")

        def fake_collect(_fetch, clubs, season, pause=None):
            walked.append((clubs, season))
            if collect_error:
                raise collect_error
            return CLUBS, SIDES, list(collect_problems)

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
        monkeypatch.setattr(yssl, "collect_league", fake_collect)
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
        assert result.walked == [(["AAC", "ECL"], 2026)]

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

    def test_lookups_go_out_100_ids_at_a_time(self):
        db = _DB()
        yssl.existing_aliases(db, "P", [f"2026-C{i:03d}" for i in range(250)])
        assert [len(filters["provider_team_id"]) for filters, _, _ in db.reads("team_alias_map")] == [100, 100, 50]
