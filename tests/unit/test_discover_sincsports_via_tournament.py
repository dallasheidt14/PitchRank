"""Unit tests for the SincSports tournament discovery driver's bundle input."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.discover_sincsports_via_tournament as driver
from src.models.sincsports_matcher import SincSportsGameMatcher
from src.scrapers.sincsports_clubs import TeamRecord
from src.scrapers.sincsports_events import CANONICAL_AGE_GROUPS
from tests.unit.test_sincsports_schedule import _sched2_day, _sched2_game, _sched2_page

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sincsports_events"
SEASON = 2026


def _team(name: str, younger: int, older: int, team_id: str = "NCM1") -> TeamRecord:
    return TeamRecord(team_id, name, "Club", f"u{younger}", "Male", "NC", (younger, older))


class TestResolveTeamAge:
    @pytest.mark.parametrize(
        "name, division, expected, how",
        [
            # Each name sits in a division whose own age differs, so reading the division
            # instead of the name fails the case.
            ("CVFC U14B NAL", (15, 15), "u14", "name"),
            ("CISC 14 (12U) North Meck State Blue", (14, 14), "u12", "name"),
            ("HFC 13U RED G", (14, 15), "u13", "name"),
            ("CVFC U16 Boys NAL", (14, 15), "u16", "name"),
            ("VA Velocity FC N1 B2012/13 Academy", (15, 15), "u14", "name"),
            ("ARSC 2015/16b Storm", (12, 12), "u11", "name"),
            ("Augusta Arsenal Under 12G Navy", (11, 12), "u12", "name"),
            ("PISA Hurricanes 10UG Red", (11, 11), "u10", "name"),
            ("NCRT 14UB Central", (15, 15), "u14", "name"),
            ("CF UN16B West Black", (17, 17), "u16", "name"),
            # A band typed with an extra zero.
            ("United Futbol Academy ECNL RL B20011/12", (13, 13), "u15", "name"),
            ("CF UN12G West Elite", (13, 13), "u12", "name"),
            # Joined up before the year rule, which would otherwise read "15" as 2015.
            ("Grove United U-15", (14, 14), "u15", "name"),
            ("Radnor SC U 13 Boys", (14, 14), "u13", "name"),
            ("FC GU-12 Blue", (13, 13), "u12", "name"),
            ("Beaufort United '10", (19, 19), "u17", "birth year 2010"),
            ("PR-12 Lightning/ Angels  FC", (16, 16), "u15", "birth year 2012"),
            ("Lexington SA 16B Red", (10, 10), "u11", "birth year 2016"),
            ("Pitt Greenville SA P1 2013", (13, 13), "u14", "birth year 2013"),
        ],
    )
    def test_only_the_name_sets_the_age(self, name, division, expected, how):
        assert driver.resolve_team_age(_team(name, *division), SEASON, SEASON) == (expected, how)

    @pytest.mark.parametrize("name", ["DISA Thorns", "Purple United"])
    def test_name_without_an_age_is_held(self, name):
        assert driver.resolve_team_age(_team(name, 12, 13), SEASON, SEASON) == (None, "no age in name")

    def test_odd_year_span_is_held(self):
        assert driver.resolve_team_age(_team("FC 2012/14 Red", 13, 13), SEASON, SEASON) == (None, "odd year span")

    def test_two_u_ages_are_held(self):
        assert driver.resolve_team_age(_team("MPFC Vipers U11/12", 11, 12), SEASON, SEASON) == (
            None,
            "two U-ages, left out",
        )

    def test_team_below_u10_has_no_board(self):
        assert driver.resolve_team_age(_team("Forest 2017/18B Black", 9, 10), SEASON, SEASON) == (
            None,
            driver.BELOW_BOARDS,
        )

    def test_board_follows_the_board_season(self):
        """A 2025-26 event's U13 team sits on the u14 board in 2026-27."""
        assert driver.resolve_team_age(_team("CVFC U13 Boys NAL", 13, 13), 2025, 2026) == ("u14", "name")


def _bundle(tmp_path: Path, day: str, teamlists: bool = True) -> Path:
    path = tmp_path / "divisions.json"
    page = _sched2_page(_sched2_day("SAT", day, _sched2_game()))
    bundle = {
        "mode": "divisions",
        "events": [{"tid": "VELOSC", "name": "Velocity Super Cup 2026 Schedules - NC | Youth Soccer"}],
        "divisions": [{"tid": "VELOSC", "div": "U12M01", "page": 1, "html": page}],
        "errors": [],
    }
    if teamlists:
        html = (FIXTURES / "teamlist_velosc.html").read_text(encoding="utf-8")
        bundle["teamlists"] = [{"tid": "VELOSC", "html": html}]
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


class TestLoadBundleTeams:
    def test_reads_every_listed_team_and_the_events_season(self, tmp_path):
        teams = driver.load_bundle_teams(_bundle(tmp_path, "Oct 3"))
        assert len(teams) == 119
        assert {season for _, season in teams} == {2026}

    def test_spring_games_belong_to_the_season_before(self, tmp_path):
        teams = driver.load_bundle_teams(_bundle(tmp_path, "Apr 11"))
        assert {season for _, season in teams} == {2025}

    def test_each_event_is_dated_from_its_own_games(self, tmp_path):
        """A capture of a fall and a spring event: the spring one's teams keep its season."""
        path = _bundle(tmp_path, "Oct 3")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        spring = _sched2_page(_sched2_day("SAT", "Apr 11", _sched2_game()))
        bundle["divisions"].append({"tid": "SPRING", "div": "U09M01", "page": 1, "html": spring})
        pages = json.loads((FIXTURES / "teampages_sample.json").read_text(encoding="utf-8"))
        bundle["teampages"] = [dict(pages[0], tid="SPRING")]
        path.write_text(json.dumps(bundle), encoding="utf-8")

        season_of = {record.provider_team_id: season for record, season in driver.load_bundle_teams(path)}

        assert season_of["NCM18002CD"] == 2025
        assert season_of["NCM1300A73"] == 2026

    def test_bundle_without_a_team_list_stops(self, tmp_path):
        with pytest.raises(SystemExit, match="no team list"):
            driver.load_bundle_teams(_bundle(tmp_path, "Oct 3", teamlists=False))

    def _hidden_columns_bundle(self, tmp_path: Path, teampages: list) -> Path:
        """Explosion Cup 2026: the host hid the list's Club and State columns."""
        path = _bundle(tmp_path, "Oct 3")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        bundle["teamlists"][0]["html"] = (
            "<h3>Under 09 Boys</h3><table><tr><td>Team</td><td>Nationals</td></tr>"
            "<tr><td><a onclick=\"eo_Callback('cpTeamSummary', 'NCM18002CD'); return false;\">"
            "PISA Hurricanes 9UB</a></td><td>&nbsp;</td></tr></table>"
        )
        bundle["teampages"] = teampages
        path.write_text(json.dumps(bundle), encoding="utf-8")
        return path

    def test_team_pages_fill_in_a_list_without_club_and_state(self, tmp_path):
        pages = json.loads((FIXTURES / "teampages_sample.json").read_text(encoding="utf-8"))
        teams = driver.load_bundle_teams(self._hidden_columns_bundle(tmp_path, [dict(p, tid="VELOSC") for p in pages]))
        by_id = {r.provider_team_id: r for r, _ in teams}
        assert sorted(by_id) == ["GAF150028F", "NCF12006BE", "NCM18002CD"]
        assert (by_id["NCM18002CD"].club_name, by_id["NCM18002CD"].state_code) == (
            "Pleasure Island Soccer Assn (PISA)",
            "NC",
        )

    def test_team_list_for_an_event_without_games_stops(self, tmp_path):
        path = _bundle(tmp_path, "Oct 3")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        bundle["teamlists"][0]["tid"] = "OTHER"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        with pytest.raises(SystemExit, match="no dated games for OTHER"):
            driver.load_bundle_teams(path)

    def test_capture_problems_are_reported(self, tmp_path, capsys):
        path = _bundle(tmp_path, "Oct 3")
        bundle = json.loads(path.read_text(encoding="utf-8"))
        bundle["errors"] = [{"tid": "VELOSC", "div": "(team NCM1)", "page": 1, "error": "no team header"}]
        path.write_text(json.dumps(bundle), encoding="utf-8")
        driver.load_bundle_teams(path)
        assert "Capture problem: VELOSC (team NCM1) page 1: no team header" in capsys.readouterr().out

    def test_capture_naming_no_team_stops(self, tmp_path):
        with pytest.raises(SystemExit, match="names none of its 2 scheduled teams"):
            driver.load_bundle_teams(self._hidden_columns_bundle(tmp_path, []))


class _FakeMatcher:
    instances: list = []

    def __init__(self, supabase, **kwargs):
        self.kwargs, self.matched = kwargs, []
        _FakeMatcher.instances.append(self)

    def _match_team(self, **kwargs):
        self.matched.append(kwargs)
        return {"created": True, "method": "direct_id", "suppressed_review_method": None}


class TestDryRun:
    def test_dry_run_matches_every_resolved_team_without_writing(self, monkeypatch, tmp_path, capsys):
        _FakeMatcher.instances = []
        monkeypatch.setattr(driver, "_soccer_season_year", lambda today=None: SEASON)
        monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(driver, "EXPORTS_DIR", tmp_path / "exports")
        monkeypatch.setattr(driver, "create_client", lambda url, key: _Db())
        monkeypatch.setattr(driver, "ensure_provider_exists", lambda supabase, dry_run: "pid")
        monkeypatch.setattr(driver, "bulk_existing_aliases", lambda supabase, pid, ids: {})
        monkeypatch.setattr(driver, "SincSportsGameMatcher", _FakeMatcher)
        argv = ["discover_sincsports_via_tournament.py", "--from-bundle", str(_bundle(tmp_path, "Oct 3")), "--dry-run"]
        monkeypatch.setattr(sys, "argv", argv)

        assert driver.main() == 0
        (matcher,) = _FakeMatcher.instances
        assert matcher.kwargs == {"provider_id": "pid", "discovery_mode": True, "dry_run": True}
        matched = {m["provider_team_id"]: m for m in matcher.matched}
        assert matched["NCM15006D6"]["age_group"] == "u12"
        assert (matched["NCM1300A73"]["club_name"], matched["NCM1300A73"]["state_code"]) == (
            "Carolina Velocity FC",
            "NC",
        )
        assert all(m["age_group"] in CANONICAL_AGE_GROUPS for m in matcher.matched)
        assert len(matcher.matched) == 106
        assert matched["NCM17265"]["age_group"] == "u10"
        assert "ACFC STINGRAYS" not in {m["team_name"] for m in matcher.matched}
        out = capsys.readouterr().out
        assert "ACFC STINGRAYS" in out
        # Below the boards: not created, and not held for review either.
        assert "GTSC Royal U9G" not in out
        assert "VAF1800055" not in matched

    def test_a_spring_events_teams_move_up_to_this_seasons_boards(self, monkeypatch, tmp_path):
        """CVFC U14B NAL played an April 2026 event as U14 (2025-26), so it is u15 in 2026-27."""
        _FakeMatcher.instances = []
        event_season = driver._soccer_season_year

        def season(today=None):
            return SEASON if today is None else event_season(today)

        monkeypatch.setattr(driver, "_soccer_season_year", season)
        monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(driver, "EXPORTS_DIR", tmp_path / "exports")
        monkeypatch.setattr(driver, "create_client", lambda url, key: _Db())
        monkeypatch.setattr(driver, "ensure_provider_exists", lambda supabase, dry_run: "pid")
        monkeypatch.setattr(driver, "bulk_existing_aliases", lambda supabase, pid, ids: {})
        monkeypatch.setattr(driver, "SincSportsGameMatcher", _FakeMatcher)
        argv = ["discover_sincsports_via_tournament.py", "--from-bundle", str(_bundle(tmp_path, "Apr 11")), "--dry-run"]
        monkeypatch.setattr(sys, "argv", argv)

        assert driver.main() == 0
        (matcher,) = _FakeMatcher.instances
        matched = {m["provider_team_id"]: m for m in matcher.matched}
        assert matched["NCM1300A73"]["age_group"] == "u15"

    def test_tid_fetch_reads_each_age_from_the_name(self, monkeypatch, tmp_path):
        """--tid takes the live team list; the division heading sets no age there either."""
        _FakeMatcher.instances = []
        listed = [
            _team("CISC 14 (12U) North Meck State Blue", 14, 14, "NCM15006D6"),
            _team("ACFC STINGRAYS", 12, 12, "NCM2"),
        ]

        class _Scraper:
            def fetch_teamlist(self, tid, include_ages=None):
                assert tid == "VELOSC"
                return listed

        monkeypatch.setattr(driver, "_soccer_season_year", lambda today=None: SEASON)
        monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(driver, "EXPORTS_DIR", tmp_path / "exports")
        monkeypatch.setattr(driver, "create_client", lambda url, key: _Db())
        monkeypatch.setattr(driver, "ensure_provider_exists", lambda supabase, dry_run: "pid")
        monkeypatch.setattr(driver, "bulk_existing_aliases", lambda supabase, pid, ids: {})
        monkeypatch.setattr(driver, "SincSportsGameMatcher", _FakeMatcher)
        monkeypatch.setattr(driver, "SincSportsEventsScraper", _Scraper)
        monkeypatch.setattr(sys, "argv", ["discover_sincsports_via_tournament.py", "--tid", "VELOSC", "--dry-run"])

        assert driver.main() == 0
        (matcher,) = _FakeMatcher.instances
        assert [(m["provider_team_id"], m["age_group"]) for m in matcher.matched] == [("NCM15006D6", "u12")]


class _Query:
    """Serves the rows as they stand when the query is built, applying only ``eq``."""

    def __init__(self, rows: list):
        self.rows = rows

    def eq(self, column, value):
        return _Query([row for row in self.rows if row.get(column) == value])

    def __getattr__(self, method):
        return lambda *args, **kwargs: self

    def execute(self):
        return SimpleNamespace(data=list(self.rows))


class _Db:
    """``teams`` is live, so a row one registration creates is a candidate for the next."""

    def __init__(self, teams=(), merges=(), broken=()):
        self.tables = {"teams": list(teams), "team_merge_map": list(merges)}
        self.broken = broken

    def table(self, name):
        if name in self.broken:
            raise RuntimeError(f"{name} unavailable")
        return _Query(self.tables.get(name, []))


class TestTwoRegistrationsOfOneEvent:
    """Beachfest 2026: "ACES 2015B" fuzzy-linked to the "ACES 14/15" row made moments earlier,
    filing one squad's games under the other. The real matcher runs here, because the failure
    needs a row one call writes to reach the next call's candidates."""

    CLUB = "ACES Soccer Club (FL)"
    NAME = "ACES U12 Boys Blue"
    MERGED = [{"deprecated_team_id": "merged", "canonical_team_id": "survivor"}]

    def _row(self, team_id, name=NAME, is_deprecated=False):
        return {
            "team_id_master": team_id,
            "team_name": name,
            "club_name": self.CLUB,
            "age_group": "u12",
            "gender": "Male",
            "state_code": "FL",
            "is_deprecated": is_deprecated,
        }

    def _record(self, team_id, name=NAME):
        return TeamRecord(
            provider_team_id=team_id,
            team_name=name,
            club_name=self.CLUB,
            age_group="u12",
            gender="Male",
            state_code="FL",
            division_ages=(),
        )

    def _wire(self, monkeypatch, tmp_path, db, records, aliases=None):
        aliases = aliases or {}
        links = {}

        def create(matcher, **kwargs):
            team_id = f"new-{kwargs['provider_team_id']}"
            db.tables["teams"].append(self._row(team_id, kwargs["team_name"]))
            return team_id, True

        def alias(matcher, **kwargs):
            links[kwargs["provider_team_id"]] = kwargs["team_id_master"]

        monkeypatch.setattr(driver, "_soccer_season_year", lambda today=None: SEASON)
        monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(driver, "EXPORTS_DIR", tmp_path / "exports")
        monkeypatch.setattr(driver, "create_client", lambda url, key: db)
        monkeypatch.setattr(driver, "ensure_provider_exists", lambda supabase, dry_run: "pid")
        monkeypatch.setattr(
            driver, "bulk_existing_aliases", lambda supabase, pid, ids: {i: aliases[i] for i in ids if i in aliases}
        )
        monkeypatch.setattr(driver, "load_bundle_teams", lambda path: [(r, SEASON) for r in records])
        monkeypatch.setattr(SincSportsGameMatcher, "_match_by_provider_id", lambda self, *args: None)
        monkeypatch.setattr(SincSportsGameMatcher, "_match_by_alias", lambda self, *args: None)
        monkeypatch.setattr(SincSportsGameMatcher, "_create_new_sincsports_team", create)
        monkeypatch.setattr(SincSportsGameMatcher, "_create_alias", alias)
        argv = ["discover_sincsports_via_tournament.py", "--from-bundle", str(tmp_path / "b.json")]
        monkeypatch.setattr(sys, "argv", argv)
        return links

    def _run(self, monkeypatch, tmp_path, db, records, aliases=None):
        links = self._wire(monkeypatch, tmp_path, db, records, aliases)
        assert driver.main() == 0
        return links

    def test_a_team_created_this_run_is_not_linked_to_by_the_next(self, monkeypatch, tmp_path):
        records = [self._record("FLM1"), self._record("FLM2")]
        links = self._run(monkeypatch, tmp_path, _Db(), records)
        assert links == {"FLM1": "new-FLM1", "FLM2": "new-FLM2"}

    def test_two_registrations_cannot_both_link_to_one_free_team(self, monkeypatch, tmp_path):
        records = [self._record("FLM1"), self._record("FLM2")]
        links = self._run(monkeypatch, tmp_path, _Db(teams=[self._row("free")]), records)
        assert links == {"FLM1": "free", "FLM2": "new-FLM2"}

    def test_a_team_a_linked_registration_holds_is_not_linked_to(self, monkeypatch, tmp_path):
        records = [self._record("FLM1"), self._record("FLM2")]
        links = self._run(monkeypatch, tmp_path, _Db(teams=[self._row("held")]), records, {"FLM1": "held"})
        assert links == {"FLM2": "new-FLM2"}

    def test_a_registration_left_out_for_its_age_still_claims_its_team(self, monkeypatch, tmp_path):
        records = [self._record("FLM1", "ACES Boys Blue"), self._record("FLM2")]
        links = self._run(monkeypatch, tmp_path, _Db(teams=[self._row("held")]), records, {"FLM1": "held"})
        assert links == {"FLM2": "new-FLM2"}

    def test_the_survivor_of_a_merged_alias_is_claimed(self, monkeypatch, tmp_path):
        records = [self._record("FLM1"), self._record("FLM2")]
        db = _Db(teams=[self._row("survivor")], merges=self.MERGED)
        links = self._run(monkeypatch, tmp_path, db, records, {"FLM1": "merged"})
        assert links == {"FLM2": "new-FLM2"}

    def test_a_merged_away_row_of_a_claimed_team_is_not_linked_to(self, monkeypatch, tmp_path):
        records = [self._record("FLM1"), self._record("FLM2")]
        db = _Db(teams=[self._row("merged", is_deprecated=True)], merges=self.MERGED)
        links = self._run(monkeypatch, tmp_path, db, records, {"FLM1": "survivor"})
        assert links == {"FLM2": "new-FLM2"}

    def test_a_team_no_registration_holds_still_links(self, monkeypatch, tmp_path):
        records = [self._record("FLM1"), self._record("FLM2")]
        links = self._run(monkeypatch, tmp_path, _Db(teams=[self._row("free")]), records, {"FLM1": "other"})
        assert links == {"FLM2": "free"}

    def test_a_failed_merge_map_read_stops_before_anything_is_written(self, monkeypatch, tmp_path):
        db = _Db(teams=[self._row("survivor")], broken=["team_merge_map"])
        links = self._wire(monkeypatch, tmp_path, db, [self._record("FLM2")])
        with pytest.raises(SystemExit, match="Merge map failed to load"):
            driver.main()
        assert links == {}

    def test_a_failed_alias_read_is_not_swallowed(self):
        with pytest.raises(RuntimeError, match="team_alias_map unavailable"):
            driver.bulk_existing_aliases(_Db(broken=["team_alias_map"]), "pid", ["FLM1"])


class TestEnsureProviderExists:
    class _Db:
        def __init__(self, rows):
            self.rows, self.inserted = rows, []

        def table(self, name):
            db = self

            class _Query:
                def select(self, *_):
                    return self

                def eq(self, *_):
                    return self

                def insert(self, row):
                    db.inserted.append(row)
                    return self

                def execute(self):
                    return type("R", (), {"data": db.rows})()

            return _Query()

    def test_dry_run_creates_no_missing_provider(self):
        db = self._Db([])
        assert driver.ensure_provider_exists(db, dry_run=True) is None
        assert db.inserted == []

    def test_real_run_creates_a_missing_provider(self):
        db = self._Db([])
        driver.ensure_provider_exists(db, dry_run=False)
        assert [row["code"] for row in db.inserted] == ["sincsports"]
