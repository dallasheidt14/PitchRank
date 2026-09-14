"""Unit tests for the SincSports schedule.aspx parser.

The parsers are tested as pure functions against committed fixtures. The live
fetcher runs against a fake session that serves those fixtures by URL, the
driver's bundle path runs end to end with the alias check stubbed, and the
alias check runs against a fake Supabase client.

The ``sched2_*`` fixtures were captured from the live site on 2026-09-14:
Carolina Champions League Spring 2026 (``CARCHLES``) U12 boys, both games
pages, its U17 boys page with three forfeits, its division picker, and the
Fall 2026 (``CARCHLEA``) U12 boys division as it opens, on standings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

import scripts.scrape_sincsports_tournament_schedule as driver
from src.scrapers.sincsports_schedule import (
    SincSportsScheduleScraper,
    parse_division,
    parse_division_pages,
    parse_page_count,
    parse_tournament_index,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sincsports_events"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def puri_u14f01_html() -> str:
    return (FIXTURES / "schedule_puri_u14f01.html").read_text(encoding="utf-8")


class TestParseTournamentIndex:
    def test_extracts_div_codes_from_root(self, puri_u14f01_html):
        # The fixture is a single division page; its own div code is referenced
        # from the URL. Live tournament-root pages reference all 60 divisions —
        # that path is exercised by the live operator dry-run.
        codes = parse_tournament_index(puri_u14f01_html)
        assert "U14F01" in codes

    def test_drops_n_sentinel(self):
        html = "<a href='?div=U14F01'>x</a> <a href='?div=N'>x</a>"
        codes = parse_tournament_index(html)
        assert "U14F01" in codes
        assert "N" not in codes

    def test_empty_html_returns_empty(self):
        assert parse_tournament_index("") == []
        assert parse_tournament_index("<html></html>") == []

    def test_codes_uppercased_and_sorted(self):
        html = "<a href='?div=u14f02'>a</a> <a href='?div=U14F01'>b</a>"
        codes = parse_tournament_index(html)
        assert codes == ["U14F01", "U14F02"]


class TestParseDivision:
    def test_puri_u14f01_extracts_all_games(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        # The Puri Cup U14F01 division is a 6-team round-robin: 9 games.
        assert len(games) == 9

    def test_each_game_has_team_ids_and_perspective(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        for g in games:
            assert g.tournament_id == "TZ2565"
            assert g.division_code == "U14F01"
            assert g.home_id and g.away_id
            assert g.home_id != g.away_id
            assert g.home_id.upper() == g.home_id
            assert g.away_id.upper() == g.away_id
            assert g.home_name and g.away_name

    def test_played_games_have_scores(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        played = [g for g in games if g.status == "Played"]
        assert len(played) >= 5  # 7 played + 2 cancelled in this division
        for g in played:
            assert g.home_score is not None
            assert g.away_score is not None
            assert 0 <= g.home_score <= 30
            assert 0 <= g.away_score <= 30

    def test_cancelled_games_have_no_scores(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        cancelled = [g for g in games if g.status == "Cancelled"]
        assert len(cancelled) == 2
        for g in cancelled:
            assert g.home_score is None
            assert g.away_score is None

    def test_known_game_extracted_correctly(self, puri_u14f01_html):
        """Spot-check #00242 — FC America 1, OSC 3 on 4/18/2026."""
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        match = [g for g in games if g.game_num == "00242"]
        assert len(match) == 1
        g = match[0]
        assert g.home_id == "IAF12039"
        assert g.away_id == "WIF12063"
        assert g.home_score == 1
        assert g.away_score == 3
        assert g.status == "Played"
        assert g.date == "4/18/2026"
        assert "FC America" in g.home_name
        assert "OSC" in g.away_name

    def test_division_name_extracted(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        with_name = [g for g in games if g.division_name]
        assert len(with_name) > 0
        # Heading is "Under 14 Girls First Division.- Crossover" or similar
        assert any("Under 14" in (g.division_name or "") for g in games)

    def test_empty_html_returns_no_games(self):
        assert parse_division("", "TZ2565", "U14F01") == []
        assert parse_division("<html></html>", "TZ2565", "U14F01") == []

    def test_no_team_links_skipped(self):
        """Cards with empty hometeam/awayteam divs are dropped silently."""
        html = (
            "<div class='form-row game-row'>"
            "<div class='col-md-3 d-cell'><span>Saturday</span><span>4/18/2026</span><span>10:40 AM</span><span>#999</span></div>"
            "<div class='col-md-5'><div class='hometeam'></div><div class='awayteam'></div></div>"
            "</div>"
        )
        assert parse_division(html, "TZ2565", "ZZZ") == []

    def test_team_names_read_from_schedule2_links(self):
        """League pages in the old layout link team names to schedule2.aspx rather than schedule.aspx."""

        def team(side: str, team_id: str, name: str) -> str:
            return (
                f"<div class='{side}'><a href='/team/team.aspx?tid=ECSA&year=2026&teamid={team_id}'>H: </a>"
                f"<a href='schedule2.aspx?tid=ECSA&year=2026&team={team_id}&div=U16M01'>{name}</a></div>"
            )

        html = (
            "<div class='form-row game-row'>"
            "<div class='col-md-3 d-cell'><span>9/12/2026</span><span>1:30 PM</span><span>#00229</span></div>"
            f"<div class='col-md-5'>{team('hometeam', 'NCM1100C35', 'EDSC PANTHERS')}"
            f"{team('awayteam', 'NCM1100C31', 'SWSC STALLIONS')}</div>"
            "</div>"
        )
        (g,) = parse_division(html, "ECSA", "U16M01")
        assert (g.home_name, g.away_name) == ("EDSC PANTHERS", "SWSC STALLIONS")


def _sched2_page(*days: str, year: str = "2026") -> str:
    """Minimal sched2 games page carrying the event year in a team link."""
    return (
        f"<a class='sched2-ha sched2-ha-h' href='/team/team.aspx?tid=T&year={year}&teamid=NCM1'>H</a>"
        + "".join(days)
    )


def _sched2_day(dow: str, day: str, *games: str) -> str:
    return (
        "<div class='sched2-daygroup'><div class='sched2-dayhd'>"
        f"<span class='sched2-dayhd-dow'>{dow}</span><span class='sched2-dayhd-date'>{day}</span>"
        "</div>" + "".join(games) + "</div>"
    )


def _sched2_game(home_score: str = "2", away_score: str = "1", extra: str = "", num: str = "7") -> str:
    def team(team_id: str, name: str, score: str) -> str:
        return (
            f"<div class='sched2-team'><a class='sched2-follow' href='#' data-team='{team_id}'></a>"
            f"<a class='sched2-team-lnk' href='schedule.aspx?team={team_id}'>{name}</a>"
            f"<span class='sched2-team-score'>{score}</span></div>"
        )

    return (
        f"<div class='sched2-game'><span class='sched2-game-num'>#{num}</span>"
        f"{team('NCM14001', 'Home FC', home_score)}{team('NCM14002', 'Away FC', away_score)}"
        f"<div class='sched2-game-field'>{extra}</div></div>"
    )


class TestParseSched2Division:
    def test_page_one_holds_the_first_fifty_games(self):
        games = parse_division(_fixture("sched2_carchles_u12m01_p1.html"), "CARCHLES", "U12M01")
        assert len(games) == 50

    def test_known_game_extracted_correctly(self):
        games = parse_division(_fixture("sched2_carchles_u12m01_p1.html"), "CARCHLES", "U12M01")
        match = [g for g in games if g.game_num == "793"]
        assert len(match) == 1
        g = match[0]
        assert g.home_id == "NCM1438B"
        assert g.away_id == "SCM14075"
        assert g.home_name == "LFC IA Carolinas-Mint Hill-WHITE 14"
        assert g.away_name == "FMU '14 Boys EPL"
        assert g.home_score == 3
        assert g.away_score == 1
        assert g.date == "2/14/2026"
        assert g.time == "9:00 AM"
        assert g.venue == "Matthews Sportsplex #08B"
        assert g.status == "Played"
        assert g.division_name == "Under 12 B Div Chelsea"

    def test_both_pages_together_hold_every_game(self):
        pages = [_fixture("sched2_carchles_u12m01_p1.html"), _fixture("sched2_carchles_u12m01_p2.html")]
        games = parse_division_pages(pages, "CARCHLES", "U12M01")
        assert len(games) == 55
        last = [g for g in games if g.game_num == "779"]
        assert len(last) == 1
        assert last[0].date == "5/3/2026"

    def test_page_count_from_captured_pager(self):
        assert parse_page_count(_fixture("sched2_carchles_u12m01_p1.html")) == 2
        assert parse_page_count(_fixture("sched2_carchles_u12m01_p2.html")) == 2

    def test_single_page_division_has_no_pager(self):
        assert parse_page_count(_fixture("sched2_carchles_u17m01_forfeit.html")) == 1

    def test_page_count_reaches_past_the_pages_the_pager_links(self):
        """The pager links only nearby pages, so the games total sets the count."""
        links = "".join(
            f"<a class='sched2-pager-num' href='schedule.aspx?tid=T&div=U10M01&mode=schedule&gpage={n}'>{n}</a>"
            for n in range(1, 5)
        )
        html = f"<div class='sched2-pager'><span class='sched2-pager-info'>312 games</span>{links}</div>"
        assert parse_page_count(html) == 7

    def test_page_count_rounds_up_only_past_a_full_page(self):
        def pager(total: int) -> str:
            return f"<div class='sched2-pager'><span class='sched2-pager-info'>{total} games</span></div>"

        assert [parse_page_count(pager(total)) for total in (50, 100, 101)] == [1, 2, 3]

    def test_old_layout_pager_is_counted(self):
        """The old layout's pager is ``sched-pager`` and links schedule2.aspx."""
        html = (
            "<div class='sched-pager'><span class='sched-pager-info'>60 games</span>"
            "<a class='sched-pager-num active' href='schedule2.aspx?tid=ECSA&div=U10M01&mode=schedule&gpage=1'>1</a>"
            "</div>"
        )
        assert parse_page_count(html) == 2

    def test_forfeit_label_overrides_recorded_score(self):
        games = parse_division(_fixture("sched2_carchles_u17m01_forfeit.html"), "CARCHLES", "U17M01")
        assert len(games) == 33
        assert sum(g.status == "Played" for g in games) == 30
        match = [g for g in games if g.game_num == "1486"]
        assert len(match) == 1
        assert match[0].status == "Forfeit"
        assert (match[0].home_score, match[0].away_score) == (4, 0)

    def test_standings_view_yields_no_games(self):
        assert parse_division(_fixture("sched2_carchlea_u12m01_standings.html"), "CARCHLEA", "U12M01") == []

    def test_root_picker_lists_boys_and_girls_divisions(self):
        codes = parse_tournament_index(_fixture("sched2_carchles_root.html"))
        assert "U12M01" in codes
        assert "U10F01" in codes
        assert "N" not in codes

    def test_year_follows_the_printed_weekday(self):
        """Jan 9 is a Friday in 2026 and a Saturday in 2027; Aug 22 is a Saturday in 2026."""
        html = _sched2_page(
            _sched2_day("SAT", "Aug 22", _sched2_game()),
            _sched2_day("SAT", "Jan 9", _sched2_game()),
            _sched2_day("FRI", "Jan 9", _sched2_game()),
        )
        assert [g.date for g in parse_division(html, "T", "U12M01")] == ["8/22/2026", "1/9/2027", "1/9/2026"]

    def test_day_matching_no_nearby_year_is_left_undated(self):
        """Jan 2 falls on a Monday in neither 2025, 2026 nor 2027."""
        html = _sched2_page(_sched2_day("MON", "Jan 2", _sched2_game()))
        assert [g.date for g in parse_division(html, "T", "U12M01")] == [None]

    def test_jan_1_placeholder_games_are_undated(self):
        """CARCHLES U17M01 files #1492 (0-0, played) and #1486 under THU Jan 1, 1 January 2026's weekday."""
        games = parse_division(_fixture("sched2_carchles_u17m01_forfeit.html"), "CARCHLES", "U17M01")
        placeholders = {g.game_num: (g.date, g.status) for g in games if g.game_num in ("1492", "1486")}
        assert placeholders == {"1492": (None, "Played"), "1486": (None, "Forfeit")}
        assert sum(g.date is None for g in games) == 2

    def test_jan_1_placeholder_is_undated_in_the_old_layout(self):
        def card(day: str, num: str) -> str:
            team = (
                "<div class='{0}'><a href='/team/team.aspx?teamid={1}'>x</a>"
                "<a href='schedule.aspx?team={1}'>n</a></div>"
            )
            return (
                f"<div class='form-row game-row'><div class='col-md-3'><span>{day}</span><span>#{num}</span></div>"
                f"<div class='col-md-5'>{team.format('hometeam', 'NCM1')}{team.format('awayteam', 'NCM2')}</div></div>"
            )

        games = parse_division(card("01/01/2026", "1") + card("1/10/2026", "2"), "T", "U12M01")
        assert [g.date for g in games] == [None, "1/10/2026"]

    def test_year_before_the_event_year(self):
        """Dec 26 is a Sunday in 2027, a Tuesday in 2028 and a Saturday in 2026."""
        html = _sched2_page(_sched2_day("SAT", "Dec 26", _sched2_game()), year="2027")
        assert [g.date for g in parse_division(html, "T", "U12M01")] == ["12/26/2026"]

    def test_leap_day(self):
        """Feb 29 exists only in 2028 of 2027-2029, and is a Tuesday there."""
        leap = _sched2_page(_sched2_day("TUE", "Feb 29", _sched2_game()), year="2028")
        no_leap = _sched2_page(_sched2_day("TUE", "Feb 29", _sched2_game()), year="2026")
        assert [g.date for g in parse_division(leap, "T", "U12M01")] == ["2/29/2028"]
        assert [g.date for g in parse_division(no_leap, "T", "U12M01")] == [None]

    def test_page_without_event_year_leaves_dates_blank(self):
        html = _sched2_day("SAT", "Aug 22", _sched2_game())
        assert [g.date for g in parse_division(html, "T", "U12M01")] == [None]

    def test_status_branches(self):
        html = _sched2_page(
            _sched2_day(
                "SAT",
                "Aug 22",
                _sched2_game("2", "1", num="1"),
                _sched2_game("", "", num="2"),
                _sched2_game("", "3", num="3"),
                _sched2_game("3", "", num="4"),
                _sched2_game("", "", "<span class='sched2-gstat sched2-gstat-off'><i></i> Cancelled</span>", num="5"),
                _sched2_game("", "", "<span class='sched2-gstat sched2-gstat-off'><i></i></span>", num="6"),
                _sched2_game(
                    "1", "1", "<span class='sched2-gstat sched2-gstat-note'><i></i> Kicks from the Mark</span>", num="7"
                ),
            )
        )
        statuses = [g.status for g in parse_division(html, "T", "U12M01")]
        assert statuses == ["Played", "Scheduled", "Scheduled", "Scheduled", "Cancelled", "Cancelled", "Played"]

    def test_rematch_on_one_day_is_kept_and_repeat_is_dropped(self):
        rematch = _sched2_game(num="8")
        html = _sched2_page(_sched2_day("SAT", "Aug 22", _sched2_game(), rematch))
        assert [g.game_num for g in parse_division_pages([html, html], "T", "U12M01")] == ["7", "8"]

    def test_unnumbered_rematches_at_different_times_are_both_kept(self):
        def unnumbered(kickoff: str) -> str:
            number = "<span class='sched2-game-num'>#7</span>"
            return _sched2_game().replace(number, f"<span class='sched2-game-time'>{kickoff}</span>")

        html = _sched2_page(_sched2_day("SAT", "Aug 22", unnumbered("9:00 AM"), unnumbered("3:00 PM")))
        assert [g.time for g in parse_division(html, "T", "U12M01")] == ["9:00 AM", "3:00 PM"]

    def test_malformed_team_id_skips_the_game(self):
        html = _sched2_page(_sched2_day("SAT", "Aug 22", _sched2_game().replace("NCM14002", "NCM-14002")))
        assert parse_division(html, "T", "U12M01") == []

    def test_non_ascii_digits_are_not_scores(self):
        html = _sched2_page(_sched2_day("SAT", "Aug 22", _sched2_game("٣", "1")))
        g = parse_division(html, "T", "U12M01")[0]
        assert g.home_score is None
        assert g.status == "Scheduled"


class _PagedSession:
    """Serves the CARCHLES U12M01 games pages by exact URL, recording each request and its timeout.

    Any other URL answers 404, and ``raise_for_status`` raises on 400 and above as ``requests`` does.
    """

    BASE = (
        "https://soccer.sincsports.com/schedule.aspx?tid=CARCHLES&year=2026&stid=CARCHLES&syear=2026"
        "&div=U12M01&mode=schedule"
    )

    def __init__(self, statuses: dict | None = None):
        self.requested: list = []
        self.statuses = statuses or {}
        self.pages = {
            self.BASE: _fixture("sched2_carchles_u12m01_p1.html"),
            f"{self.BASE}&gpage=2": _fixture("sched2_carchles_u12m01_p2.html"),
        }

    def get(self, url, timeout=None):
        self.requested.append((url, timeout))
        status = self.statuses.get(url, 200 if url in self.pages else 404)
        text = self.pages.get(url, "")

        class _Response:
            status_code = status

            def __init__(self):
                self.text = text

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code} for {url}")

        return _Response()


class TestFetchDivision:
    def test_fetches_every_games_page(self):
        scraper = SincSportsScheduleScraper(delay_min=0, delay_max=0, timeout=17)
        scraper.session = _PagedSession()
        games = scraper.fetch_division("CARCHLES", "U12M01", year=2026)
        assert scraper.session.requested == [(_PagedSession.BASE, 17), (f"{_PagedSession.BASE}&gpage=2", 17)]
        assert len(games) == 55

    def test_blocked_later_page_fails_the_division(self):
        scraper = SincSportsScheduleScraper(delay_min=0, delay_max=0)
        scraper.session = _PagedSession(statuses={f"{_PagedSession.BASE}&gpage=2": 403})
        with pytest.raises(requests.HTTPError):
            scraper.fetch_division("CARCHLES", "U12M01", year=2026)


CARCHLES_U12 = ("sched2_carchles_u12m01_p1.html", "sched2_carchles_u12m01_p2.html")


def _bundle(tmp_path: Path, *pages: str, errors: list | None = None) -> Path:
    """Write a divisions capture holding ``pages`` (HTML, in gpage order) as CARCHLES U12M01."""
    path = tmp_path / "divisions.json"
    path.write_text(
        json.dumps(
            {
                "mode": "divisions",
                "events": [{"tid": "CARCHLES", "name": "Carolina Champions League - Spring"}],
                "divisions": [
                    {"tid": "CARCHLES", "div": "U12M01", "page": page, "html": html}
                    for page, html in enumerate(pages, 1)
                ],
                "errors": errors or [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _fixtures(*names: str) -> list:
    return [_fixture(name) for name in names]


class TestLoadBundle:
    def test_complete_division_parses_every_page_once(self, tmp_path):
        p1, p2 = _fixtures(*CARCHLES_U12)
        games, problems = driver.load_bundle(_bundle(tmp_path, p1, p2, p2))
        assert problems == []
        assert len(games) == 55
        assert {g.division_name for g in games} == {"Carolina Champions League - Spring - U12M01"}

    def test_missing_page_is_reported(self, tmp_path):
        games, problems = driver.load_bundle(_bundle(tmp_path, _fixture(CARCHLES_U12[0])))
        assert len(games) == 50
        assert problems == ["CARCHLES U12M01: pager spans 2 pages, bundle is missing [2]"]

    def test_capture_error_is_reported(self, tmp_path):
        errors = [{"tid": "CARCHLES", "div": "(event root)", "page": 1, "error": "HTTP 503"}]
        path = _bundle(tmp_path, _fixture("sched2_carchles_u17m01_forfeit.html"), errors=errors)
        _, problems = driver.load_bundle(path)
        assert problems == ["CARCHLES (event root) page 1: HTTP 503"]

    def test_leagues_capture_is_refused(self, tmp_path):
        path = tmp_path / "leagues.json"
        path.write_text(json.dumps({"mode": "leagues", "leagues": [{"tid": "CARCHLEA"}]}), encoding="utf-8")
        assert driver.load_bundle(path) == (
            [],
            ["leagues.json is a 'leagues' capture; --from-bundle needs a 'divisions' capture"],
        )


class _FakeResult:
    def __init__(self, data: list):
        self.data = data


class _FakeProvidersQuery:
    def __init__(self, client: "_FakeSupabase"):
        self.client, self.filters = client, {}

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        rows = [p for p in self.client.providers if all(p[c] == v for c, v in self.filters.items())]
        return _FakeResult([{"id": p["id"]} for p in rows])


class _FakeRpc:
    def __init__(self, client: "_FakeSupabase", params: dict):
        self.client, self.params, self.limit_value = client, params, None

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        """Mirror get_approved_aliases: the provider's approved rows only, and at most ``limit`` of them."""
        self.client.executed_rpc.append((self.params, self.limit_value))
        rows = [
            {"provider_team_id": a["provider_team_id"]}
            for a in self.client.aliases
            if a["provider_id"] == self.params["p_provider_id"] and a["review_status"] == "approved"
        ]
        return _FakeResult(rows if self.limit_value is None else rows[: self.limit_value])


class _FakeSupabase:
    """The two calls find_unlinked_team_ids makes: a providers lookup and the get_approved_aliases RPC."""

    def __init__(self, aliases: list):
        self.providers = [{"id": "p-sinc", "code": "sincsports"}, {"id": "p-gs", "code": "gotsport"}]
        self.aliases = aliases
        self.executed_rpc: list = []

    def table(self, name):
        assert name == "providers"
        return _FakeProvidersQuery(self)

    def rpc(self, name, params):
        assert name == "get_approved_aliases"
        return _FakeRpc(self, params)


class TestFindUnlinkedTeamIds:
    def _run(self, monkeypatch, aliases: list, team_ids: list) -> tuple:
        client = _FakeSupabase(aliases)
        monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(driver, "create_client", lambda url, key: client)
        return driver.find_unlinked_team_ids(team_ids), client

    def test_only_this_providers_approved_aliases_link_a_team(self, monkeypatch):
        aliases = [
            {"provider_id": "p-sinc", "provider_team_id": "NCM1", "review_status": "approved"},
            {"provider_id": "p-sinc", "provider_team_id": "NCM2", "review_status": "pending"},
            {"provider_id": "p-gs", "provider_team_id": "NCM3", "review_status": "approved"},
        ]
        unlinked, client = self._run(monkeypatch, aliases, ["NCM1", "NCM2", "NCM3"])
        assert unlinked == {"NCM2", "NCM3"}
        assert client.executed_rpc == [({"p_provider_id": "p-sinc"}, 200000)]

    def test_merged_alias_links_each_listed_id_exactly(self, monkeypatch):
        aliases = [{"provider_id": "p-sinc", "provider_team_id": "NCM10; NCM20", "review_status": "approved"}]
        unlinked, _ = self._run(monkeypatch, aliases, ["NCM10", "NCM20", "NCM1"])
        assert unlinked == {"NCM1"}

    def test_missing_credentials_stop_the_run(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
        monkeypatch.setattr(driver, "create_client", lambda url, key: pytest.fail("client built without a key"))
        with pytest.raises(SystemExit, match="SUPABASE_SERVICE_ROLE_KEY"):
            driver.find_unlinked_team_ids(["NCM1"])


class TestWriteUnlinkedTeamsCsv:
    def test_formula_leading_cells_are_defanged(self, tmp_path):
        game = parse_division(_sched2_page(_sched2_day("SAT", "Aug 22", _sched2_game())), "=T", "U12M01")[0]
        game.home_name = '=HYPERLINK("https://example.test")'
        out = tmp_path / "unlinked.csv"
        driver.write_unlinked_teams_csv(out, [game], {"NCM14001"})
        assert out.read_text(encoding="utf-8").splitlines()[1] == (
            'NCM14001,"\'=HYPERLINK(""https://example.test"")",\'=T/U12M01'
        )


class TestDriverFromBundle:
    def _run(self, monkeypatch, tmp_path, *argv: str) -> int:
        monkeypatch.setattr(driver, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(sys, "argv", ["scrape_sincsports_tournament_schedule.py", *argv])
        return driver.main()

    def _rows(self, tmp_path: Path) -> list:
        (out,) = (tmp_path / "raw").glob("*.jsonl")
        return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    def test_since_keeps_games_on_that_day(self, monkeypatch, tmp_path):
        path = _bundle(tmp_path, *_fixtures(*CARCHLES_U12))
        assert self._run(monkeypatch, tmp_path, "--from-bundle", str(path), "--since", "2026-04-11") == 0
        rows = self._rows(tmp_path)
        assert len(rows) == 20
        assert min(r["game_date"] for r in rows) == "2026-04-11"
        assert {r["competition"] for r in rows} == {"Carolina Champions League - Spring - U12M01"}

    def test_incomplete_bundle_writes_nothing(self, monkeypatch, tmp_path):
        path = _bundle(tmp_path, _fixture(CARCHLES_U12[0]))
        assert self._run(monkeypatch, tmp_path, "--from-bundle", str(path)) == 1
        assert not (tmp_path / "raw").exists()

    def test_incomplete_bundle_fails_dry_run(self, monkeypatch, tmp_path):
        path = _bundle(tmp_path, _fixture(CARCHLES_U12[0]))
        assert self._run(monkeypatch, tmp_path, "--from-bundle", str(path), "--dry-run") == 1

    def _only_unlinked(self, monkeypatch, *team_ids: str) -> list:
        requested: list = []

        def find(ids):
            requested.append(set(ids))
            return set(ids) & set(team_ids)

        monkeypatch.setattr(driver, "find_unlinked_team_ids", find)
        return requested

    def test_unlinked_teams_are_held_back_and_listed(self, monkeypatch, tmp_path):
        """SCM14075 plays 14 of the 55 games."""
        path = _bundle(tmp_path, *_fixtures(*CARCHLES_U12))
        self._only_unlinked(monkeypatch, "SCM14075")
        assert self._run(monkeypatch, tmp_path, "--from-bundle", str(path), "--check-aliases") == 0
        rows = self._rows(tmp_path)
        assert len(rows) == 41
        assert all("SCM14075" not in (r["team_id"], r["opponent_id"]) for r in rows)
        (listing,) = (tmp_path / "raw").glob("*_unlinked_teams.csv")
        lines = listing.read_text(encoding="utf-8").splitlines()
        assert lines == ["team_id,team_name,divisions", "SCM14075,FMU '14 Boys EPL,CARCHLES/U12M01"]

    def test_team_seen_only_away_is_checked_and_held_back(self, monkeypatch, tmp_path):
        linked_game = _sched2_game()
        away_only_game = _sched2_game(num="8").replace("NCM14002", "NCM14009")
        path = _bundle(tmp_path, _sched2_page(_sched2_day("SAT", "Aug 22", linked_game, away_only_game)))
        requested = self._only_unlinked(monkeypatch, "NCM14009")
        assert self._run(monkeypatch, tmp_path, "--from-bundle", str(path), "--check-aliases") == 0
        assert requested == [{"NCM14001", "NCM14002", "NCM14009"}]
        assert [(r["team_id"], r["opponent_id"]) for r in self._rows(tmp_path)] == [("NCM14001", "NCM14002")]

    def test_successful_dry_run_lists_teams_but_writes_no_games(self, monkeypatch, tmp_path):
        path = _bundle(tmp_path, *_fixtures(*CARCHLES_U12))
        self._only_unlinked(monkeypatch, "SCM14075")
        monkeypatch.setattr(driver.subprocess, "run", lambda *a, **k: pytest.fail("dry run started the importer"))
        argv = ("--from-bundle", str(path), "--check-aliases", "--dry-run", "--auto-import")
        assert self._run(monkeypatch, tmp_path, *argv) == 0
        assert list((tmp_path / "raw").glob("*.jsonl")) == []
        assert len(list((tmp_path / "raw").glob("*_unlinked_teams.csv"))) == 1
