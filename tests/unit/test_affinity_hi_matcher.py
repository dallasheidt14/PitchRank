"""Tests for the Affinity HI (HYSA Oahu League) matcher.

The HI matcher is the state league matcher with Hawaii's state and HYSA's name spellings,
so these cover what Hawaii adds and the rules that base holds: the age label, the club
spellings, what makes two names one squad, the Hawaii-only club state, and the path the
importer takes through them.
"""

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from src.models.affinity_hi_matcher import AffinityHIGameMatcher
from tests.unit.test_scrape_affinity_ut import _DB
from tests.unit.test_scrape_affinity_ut import _Query as _FilteringQuery

NO_ROWS = APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})


def _team(name, club, state="HI", age_group="u10", team_id=None, gender="Male"):
    return {
        "team_id_master": team_id or name,
        "team_name": name,
        "club_name": club,
        "age_group": age_group,
        "gender": gender,
        "state_code": state,
        "is_deprecated": False,
    }


def _matcher(rows=()):
    return AffinityHIGameMatcher(_DB(list(rows)), provider_id="p")


class TestClub:
    @pytest.mark.parametrize(
        "team_name, club",
        [
            ("13UB - HSC Bulls 13/14B - II", "Honolulu Bulls Soccer Club"),
            ("13UG - 13/14G Surf Hawaii Academy I", "Hawaii Surf Soccer Club"),
            ("14UB - Leahi Na Koa 12/13 Windward", "Leahi Soccer Club"),
            ("14UG - Leahi 12/13 Maile Blue", "Leahi Soccer Club"),
            ("12UB -RUSH Cinza 14/15B", "Hawaii Rush"),
            ("10UB Hawaii RUSH Azul", "Hawaii Rush"),
            ("BI RUSH 2014", "BI Rush"),
            ("12UB - BVB IA Hawaii Yellow", "BVB International Academy Hawaii"),
            ("11UG - 808FC Black", "808 Futbol Club"),
            ("10UB - 808 FC Gold", "808 Futbol Club"),
            ("12UB - Universal SC", "Universal Soccer League"),
            ("15UB - Hawaii United FC Gold", "Hawaii United FC"),
            ("13UB - FC Hawaii Red", "FC Hawaii"),
            ("18UB - Inter Ohana CF Blanco", "Inter Ohana CF"),
            ("15UB - ALBION SC Hawaii HNL BU14/U15 Academy", "ALBION SC Hawaii"),
            ("10UB - Ballistic Blaze U10B", "Ballistic Soccer Hawaii"),
            ("13UB - Hoomau White", "Ho'omau FC"),
            ("12UB - Arsenal FC", "Arsenal FC Hawaii"),
            ("11UB - Ke Ahi O Pele FC", "Ke Ahi O Pele FC"),
            ("10UB - Some Club U10B", "Some Club"),
            ("13UB - Hawai'i Soccer", "Hawai'i Soccer"),
            ("13UB - Ke I Ola FC", "Ke I Ola FC"),
        ],
    )
    def test_the_club_is_read_as_pitchrank_stores_it(self, team_name, club):
        assert _matcher()._club_for(team_name, None) == club

    def test_normalizing_drops_the_age_label(self):
        assert _matcher()._normalize_provider_name("13UB - Hoomau") == "Hoomau"


class TestSquadMarks:
    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("10UB - HSC Bulls 16/17B - I", "10UB - HSC Bulls 16/17B - II"),
            ("12UB - ALBION SC Hawaii HNL BU12 Academy", "12UB - ALBION SC Hawaii HNL BU12 Academy I"),
            ("12UB - ALBION SC Hawaii HNL BU12 Academy", "12UB - ALBION SC Hawaii WND BU12 Academy"),
            ("13UB - Inter Ohana CF Rosa", "13UB - Inter Ohana CF Rosa II"),
        ],
    )
    def test_different_squads_conflict(self, provider, stored):
        assert _matcher()._squads_conflict(provider, stored)

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("11UG - RUSH Azul 15/16G", "Hawaii Rush - Hawaii Rush 2016"),
            ("11UG - RUSH Lightning Salt Lake 15/16G", "Hawaii Rush - Hawaii Rush 2016"),
            ("12UB - ALBION SC Hawaii HNL BU12 Academy", "WND BU12 Academy"),
            ("14UG - Leahi 12/13 Maile Blue", "Leahi ‘12/13 Premier Blue 14UG"),
        ],
    )
    def test_a_stored_name_naming_another_squad_or_none_conflicts(self, provider, stored):
        """Utah's squad check passes every pair, so only this rule keeps them apart."""
        assert _matcher()._squads_conflict(provider, stored)

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("18UB - FC Hawaii Red", "19UB - FC Hawaii Red"),
            ("18UB - ALBION SC Hawaii WND BU18 Academy", "WND BU19 Academy"),
        ],
    )
    def test_two_stated_u_ages_on_one_board_are_two_squads(self, provider, stored):
        """U18 and U19 share the u19 board, and their words agree once the ages are gone."""
        assert _matcher()._squads_conflict(provider, stored)

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("10UB - HSC Bulls 16/17B - I", "10UB - HSC Bulls 16/17B - I"),
            ("12UB - BVB IA Hawaii Yellow", "BVB IA Hawaii 2015 Yellow"),
            ("15UB - Inter Ohana CF Rosa", "Inter Ohana CF - 12B Rosa"),
            ("14UG - Leahi 12/13G Premier Blue", "Leahi ‘12/13 Premier Blue 14UG"),
            ("12UB - RUSH Azul 14/15B", "Hawaii RUSH 2015 Azul"),
            ("11UB - HSC Bulls 15/16B - I", "HSC Bulls 16B-I"),
            ("12UB - ALBION SC Hawaii WND BU12 Academy", "WND BU12 Academy"),
            ("10UB - HSC Bulls 16/17B - I", "Honolulu Bulls 16/17B - I"),
            ("13UB - Leahi Na Koa 13/14 Windward Blue", "Leahi 13/14B Windward Blue"),
            ("10UB - HSC Bulls 16/17B - II", "Honolulu Bulls 2017 2"),
            ("13UG - 13/14G Surf Hawaii Academy I", "Hawaii Surf Academy 1 2014"),
            ("12UG - HSC Bulls 14/15G", "Honolulu Bulls Soccer Club 2015G"),
            ("12UB - RUSH Azul 14/15B", "Hawaii Rush 2015B Azul"),
            ("19UB - Leahi Na Koa 08/09 Blue", "Leahi Na Koa 08/09B Blue"),
            ("11UB - Ballistic Burst U11B", "Ballistic U11B Burst"),
            ("13UB - Hoomau White", "Ho'omau 2014 White"),
        ],
    )
    def test_one_squad_written_two_ways_does_not_conflict(self, provider, stored):
        assert not _matcher()._squads_conflict(provider, stored)

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("13UG - 13/14G Surf Hawaii Academy I", "Hawaii Surf SC 2014 Academy 1"),
            ("12UB - RUSH Azul 14/15B", "Hawaii Rush Boys 2015 Azul"),
            ("13UB - Leahi Na Koa 13/14 Windward Blue", "Leahi Youth Soccer 13/14B Windward Blue"),
            ("15UB - Inter Ohana CF Rosa", "Inter Ohana Football Club 12B Rosa"),
        ],
    )
    def test_a_generic_club_word_is_not_a_squad_word(self, provider, stored):
        assert not _matcher()._squads_conflict(provider, stored)


class TestFuzzyMatch:
    SQUADS = [
        _team("10UB - HSC Bulls 16/17B - I", "Honolulu Bulls Soccer Club"),
        _team("10UB - HSC Bulls 16/17B - II", "Honolulu Bulls Soccer Club"),
    ]

    def test_a_numbered_squad_finds_its_own_row(self):
        match = _matcher(self.SQUADS)._fuzzy_match_team("10UB - HSC Bulls 16/17B - II", "u10", "Male")

        assert match["team_id"] == "10UB - HSC Bulls 16/17B - II"

    def test_a_squad_with_no_stored_row_takes_neither_sibling(self):
        assert _matcher(self.SQUADS)._fuzzy_match_team("10UB - HSC Bulls 16/17B - III", "u10", "Male") is None

    def test_a_stored_squad_outside_hawaii_is_not_taken(self):
        rows = [_team("10UB - HSC Bulls 16/17B - I", "Honolulu Bulls Soccer Club", state="CA")]

        assert _matcher(rows)._fuzzy_match_team("10UB - HSC Bulls 16/17B - I", "u10", "Male") is None

    def test_a_19u_squad_does_not_take_its_clubs_18u_row(self):
        rows = [_team("18UB - FC Hawaii Red", "FC Hawaii", age_group="u19")]

        assert _matcher(rows)._fuzzy_match_team("19UB - FC Hawaii Red", "u19", "Male") is None


class TestState:
    def test_an_unknown_club_takes_hawaii(self):
        assert _matcher()._state_for_new_team("Hoomau") == ("HI", "Hawaii")

    def test_a_club_known_only_outside_hawaii_is_still_hawaiis(self):
        """An 'Arsenal FC' stored in Nevada says nothing about HYSA's Arsenal FC."""
        matcher = _matcher([_team("Arsenal FC 2014", "Arsenal FC", state="NV")] * 2)

        assert matcher._state_for_club("Arsenal FC") == "HI"
        assert matcher._state_for_new_team("Arsenal FC") == ("HI", "Hawaii")


class _RecordingQuery(_FilteringQuery):
    """The filtering double held to production: select() projects, single() needs one row, insert() records."""

    def __init__(self, rows, table, inserted):
        super().__init__(rows)
        self._table = table
        self._inserted = inserted
        self._columns = None
        self._single = False
        self._row = None

    def select(self, columns="*", **_k):
        self._columns = None if columns == "*" else [c.strip() for c in columns.split(",")]
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, row):
        self._row = row
        return self

    def execute(self):
        if self._row is not None:
            self._inserted.append((self._table, self._row))
            return SimpleNamespace(data=[self._row])
        rows = [dict(r) if self._columns is None else {c: r.get(c) for c in self._columns} for r in self._rows]
        if self._single:
            if len(rows) != 1:
                raise NO_ROWS
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class _RecordingDB:
    def __init__(self, teams=()):
        self.teams = list(teams)
        self.inserted = []

    def table(self, name):
        return _RecordingQuery(self.teams if name == "teams" else [], name, self.inserted)

    def written(self, table):
        return [row for written_to, row in self.inserted if written_to == table]


class TestMatchTeam:
    """The path the importer takes, which is handed the blank club every scraped row carries."""

    @pytest.mark.parametrize(
        "team_name, club",
        [
            ("13UB - HSC Bulls 13/14B - II", "Honolulu Bulls Soccer Club"),
            ("13UB - Ke Ahi O Pele FC", "Ke Ahi O Pele FC"),
        ],
    )
    def test_a_new_team_keeps_its_full_name_takes_its_club_and_is_filed_in_hawaii(self, team_name, club):
        db = _RecordingDB()
        matcher = AffinityHIGameMatcher(db, provider_id="p")

        result = matcher._match_team("p", "affinity_hi:0123456789ab", team_name, "u13", "Male", "")

        assert result["created"] is True
        assert [(r["team_name"], r["club_name"], r["state_code"], r["state"]) for r in db.written("teams")] == [
            (team_name, club, "HI", "Hawaii")
        ]
        assert [(r["provider_team_id"], r["team_id_master"]) for r in db.written("team_alias_map")] == [
            ("affinity_hi:0123456789ab", result["team_id"])
        ]

    def test_a_stored_squad_is_linked_past_auto_approve_without_a_new_team(self):
        db = _RecordingDB([_team("BVB IA Hawaii 2015 Yellow", "BVB International Academy Hawaii", age_group="u12")])
        matcher = AffinityHIGameMatcher(db, provider_id="p")

        result = matcher._match_team("p", "affinity_hi:abcdef012345", "12UB - BVB IA Hawaii Yellow", "u12", "Male", "")

        assert (result["matched"], result["method"], result["team_id"]) == (
            True,
            "fuzzy_auto",
            "BVB IA Hawaii 2015 Yellow",
        )
        assert db.written("teams") == []
        assert [r["team_id_master"] for r in db.written("team_alias_map")] == ["BVB IA Hawaii 2015 Yellow"]
