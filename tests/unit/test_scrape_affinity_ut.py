"""Tests for the Affinity UT (UYSA) scraper and matcher.

The UT scraper runs the OR scraper's engine, so these cover only what Utah adds:
UYSA's division labels, its tournament config, filing games by team name, and
the matcher's Utah state and name spellings.
"""

import re
import sys
from types import SimpleNamespace

import pytest

from scripts import scrape_affinity_or_tournament as engine
from scripts import scrape_affinity_ut_tournament as scraper
from src.models.affinity_or_matcher import AffinityORGameMatcher
from src.models.affinity_ut_matcher import AffinityUTGameMatcher, _normalize_for_affinity_ut
from src.utils import team_utils
from tests.unit.test_scrape_affinity_or import FUTURE_HEADER, PLAYED, WIDE_WINDOW, _schedule_html

PINNED_SEASON = 2026

FLIGHT = {
    "flight_guid": "0B7E2D1C-3A4F-4E5D-9C8B-7A6F5E4D3C2B",
    "division_name": "Boys 13U Premier",
    "birth_year": 2014,
    "age_u": 13,
    "gender": "Male",
}


class TestDivisionLabels:
    """UYSA writes the age after the gender word, with the U trailing."""

    @pytest.mark.parametrize(
        "division, gender, age_u",
        [
            ("Boys 12U Premier", "Male", 12),
            ("Girls 15U North A", "Female", 15),
            ("Boys  15U North B", "Male", 15),
            ("Boys 15U  Metro A", "Male", 15),
            ("Boys 9u North Green B", "Male", 9),
            ("Girls 18U Premier", "Female", 18),
            ("Girls 19U Premier", "Female", 19),
        ],
    )
    def test_gender_and_age_come_from_the_label(self, division, gender, age_u):
        assert engine._extract_age_gender_from_division(division) == (gender, age_u)

    @pytest.mark.parametrize("division", ["Boys 18/19U Premier", "Boys 18/19 N1", "Boys 18/19U Division 4"])
    def test_the_18_19_pair_is_one_cohort(self, division):
        """U18 folds into u19, so the pair names a single board."""
        assert engine._extract_age_gender_from_division(division) == ("Male", 19)

    @pytest.mark.parametrize("division", ["Boys 13/14U Premier", "Boys 17/18U Premier"])
    def test_a_pair_spanning_two_boards_is_skipped(self, division):
        """17/18 spans u17 and u19, so only a pair whose younger age also folds is one board."""
        assert engine._extract_age_gender_from_division(division) == ("Male", None)

    def test_a_birth_year_is_not_read_as_an_age(self):
        assert engine._extract_age_gender_from_division("Boys 2014 Elite") == ("Male", None)

    @pytest.mark.parametrize(
        "division, expected_age_group",
        [("Boys 13U Premier", "U13"), ("Boys 16U North A", "U16"), ("Boys 18/19U Premier", "U19")],
    )
    def test_division_lands_on_its_own_number(self, division, expected_age_group):
        """Checked against UYSA's team names: 'Peak SC 13/14B' plays 13U, 'B10/11' plays 16U."""
        _, age_u = engine._extract_age_gender_from_division(division)

        birth_year = engine._age_u_to_birth_year(age_u, PINNED_SEASON)

        assert team_utils.calculate_age_group_from_birth_year(birth_year, PINNED_SEASON) == expected_age_group


class TestTournamentConfig:
    """Derived from the list itself, so a new league cannot omit a field silently."""

    @pytest.mark.parametrize("field", ["tournament_guid", "base_url", "season_year", "provider", "state", "state_code"])
    def test_every_tournament_carries_the_field(self, field):
        assert [t["name"] for t in scraper.TOURNAMENTS if not t.get(field)] == []

    def test_every_tournament_files_into_utah(self):
        assert {(t["provider"], t["state_code"]) for t in scraper.TOURNAMENTS} == {("affinity_ut", "UT")}

    def test_the_scraper_walks_only_the_tournaments_it_is_given(self, monkeypatch, tmp_path):
        """The Utah entry point hands its own list in, so Oregon's league is never scraped as Utah's."""
        walked = []
        monkeypatch.setattr(engine, "discover_flights", lambda t, age, gender: walked.append(t["name"]) or [])
        out = tmp_path / "out.csv"
        monkeypatch.setattr(sys, "argv", ["x", "--age", "u13", "--gender", "male", "--output", str(out)])

        engine.main(scraper.TOURNAMENTS)

        assert walked == [t["name"] for t in scraper.TOURNAMENTS]


class TestRecordFields:
    def test_rows_carry_utahs_provider_and_state(self, monkeypatch):
        html = _schedule_html([PLAYED], FUTURE_HEADER)
        monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: html)

        records = engine.scrape_flight_games(scraper.TOURNAMENTS[0], FLIGHT, *WIDE_WINDOW)

        assert len(records) == 2
        assert {r["provider"] for r in records} == {"affinity_ut"}
        assert {(r["state_code"], r["state"]) for r in records} == {("UT", "Utah")}
        assert {r["age_group"] for r in records} == {"u13"}
        assert all(r["team_id"].startswith("affinity_ut:") for r in records)
        assert all(r["opponent_id"].startswith("affinity_ut:") for r in records)


def _game(home, away):
    return ["672228", "Crescent MS", "12:00 PM", "3023", "A5 vs A8", home, "2", "vs.", away, "1"]


def _scrape_game(monkeypatch, home, away):
    html = _schedule_html([_game(home, away)], FUTURE_HEADER)
    monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: html)
    return engine.scrape_flight_games(scraper.TOURNAMENTS[0], FLIGHT, *WIDE_WINDOW)


class TestAgeFromTeamNames:
    """A game is filed by its teams' own names; the 13U division only bounds them."""

    def test_names_that_agree_with_the_division_are_kept(self, monkeypatch):
        records = _scrape_game(monkeypatch, "Peak SC 13/14B MH Black", "Wasatch SC 14/13B - AM")

        assert {r["age_group"] for r in records} == {"u13"}

    def test_two_teams_playing_up_together_are_filed_by_their_names(self, monkeypatch):
        records = _scrape_game(monkeypatch, "La Roca U12B- J Walker", "Avalanche Pre-ECNL B2014/15 North")

        assert {r["age_group"] for r in records} == {"u12"}
        assert {r["age_year"] for r in records} == {2015}

    def test_a_team_playing_up_against_its_division_is_held(self, monkeypatch):
        assert _scrape_game(monkeypatch, "La Roca U12B- J Walker", "Peak SC 13/14B MH Black") == []

    def test_a_name_with_two_ages_is_held(self, monkeypatch):
        assert _scrape_game(monkeypatch, "Celtic BU12/U13 - Carvajal", "Peak SC 13/14B MH Black") == []

    def test_two_names_neither_on_a_board_are_held(self, monkeypatch):
        """Both read U9, which has no board; they agree with each other, so only the board check holds them."""
        assert _scrape_game(monkeypatch, "Rampage U9B CC", "Rampage U9B TS") == []

    def test_a_team_with_no_age_in_its_name_takes_the_division(self, monkeypatch):
        records = _scrape_game(monkeypatch, "Copper Mountain 7 JM", "Peak SC 13/14B MH Black")

        assert {r["age_group"] for r in records} == {"u13"}


class _Query:
    """PostgREST double that applies every filter it is given and yields rows only at execute().

    ilike is a case-insensitive pattern in which %, * and _ are wildcards, as PostgREST reads it.
    """

    def __init__(self, rows):
        self._rows = rows
        self._negate = False

    @property
    def not_(self):
        self._negate = True
        return self

    def is_(self, field, value):
        assert value == "null"
        keep = (lambda r: r.get(field) is not None) if self._negate else (lambda r: r.get(field) is None)
        self._rows, self._negate = [r for r in self._rows if keep(r)], False
        return self

    def neq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) != value]
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def ilike(self, field, value):
        pattern = re.compile(
            "".join(".*" if ch in "%*" else "." if ch == "_" else re.escape(ch) for ch in value), re.IGNORECASE
        )
        self._rows = [r for r in self._rows if pattern.fullmatch(r.get(field) or "")]
        return self

    def in_(self, field, values):
        self._rows = [r for r in self._rows if r.get(field) in values]
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=[dict(r) for r in self._rows])


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Query(list(self.rows))


def _team(name, club, state="UT", age_group="u13", team_id=None, deprecated=False):
    return {
        "team_id_master": team_id or name,
        "team_name": name,
        "club_name": club,
        "age_group": age_group,
        "gender": "Male",
        "state_code": state,
        "is_deprecated": deprecated,
    }


def _matcher(rows=()):
    return AffinityUTGameMatcher(_DB(list(rows)), provider_id="p")


class TestMatcherState:
    def test_an_unknown_club_takes_utah(self):
        assert _matcher()._state_for_new_team("Brand New Club") == ("UT", "Utah")

    def test_an_unknown_club_is_searched_in_utah(self):
        assert _matcher()._state_for_club("Brand New Club") == "UT"

    def test_a_club_known_only_outside_the_region_is_still_utahs(self):
        """'Avalanche' is stored only in Virginia; Utah's Avalanche is stored as 'Utah Avalanche'."""
        matcher = _matcher([_team("Avalanche 14B Red", "Avalanche", state="VA")])

        assert matcher._state_for_club("Avalanche") == "UT"
        assert matcher._state_for_new_team("Avalanche") == ("UT", "Utah")

    def test_a_neighbouring_club_keeps_its_state(self):
        matcher = _matcher([_team("Rock Springs 14B", "Rock Springs Avengers", state="WY")] * 3)

        assert matcher._state_for_club("Rock Springs Avengers") == "WY"
        assert matcher._state_for_new_team("Rock Springs Avengers") == ("WY", "Wyoming")

    def test_a_club_carrying_a_like_wildcard_is_not_looked_up(self):
        """'%' would match every club in the region and turn a Utah team's state into a regional vote."""
        rows = [_team("Rush 14B", "Rush", state="ID")]

        assert _matcher(rows)._state_for_new_team("%") == ("UT", "Utah")

    def test_a_placeholder_club_is_not_asked_for_a_state(self):
        rows = [_team("Rush 14B", "No Club Selection", state="ID")]

        assert _matcher(rows)._state_for_new_team("No Club Selection") == ("UT", "Utah")

    def test_a_club_split_across_the_region_stores_no_state(self):
        rows = [_team("Rush 14B", "Rush", state="UT"), _team("Rush 14B Boise", "Rush", state="ID")]

        assert _matcher(rows)._state_for_new_team("Rush") == (None, None)


class TestMatcherNames:
    @pytest.mark.parametrize(
        "team_name, club",
        [
            ("Peak SC 13/14B MH Black", "Peak SC"),
            ("Wasatch SC 14/13B - AM", "Wasatch SC"),
            ("Athletic SC B10/11 JS", "Athletic SC"),
            ("Aggies FC 17/18B X", "Aggies FC"),
            ("Avalanche U13B Black DW", "Avalanche"),
            ("Impact PT BU13", "Impact"),
            ("Strikers BB", "Strikers"),
            ("Copper Mountain 7 JM", "Copper Mountain"),
        ],
    )
    def test_the_club_is_read_without_age_colour_or_coach(self, team_name, club):
        """Read through the OR normalizer and club extractor alone, 'Peak SC 13/14B' yields the club 'Peak SC 13/'."""
        assert _matcher()._club_for(team_name, None) == club

    def test_a_glued_u_age_is_not_read_as_part_of_the_club(self):
        assert "U12" not in _matcher()._club_for("La Roca U12B- J Walker", None)

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("Cottonwood FC B1314 White JN", "CFC B13/14 White MC"),
            ("Strikers DH 14", "Strikers JH 14B"),
            ("Strikers DH 11", "Strikers JD B11"),
            ("Avalanche U13B Black SL", "Avalanche 2014 Black SL 2"),
            ("Utah Glory BU13 Black NV", "UTAH GLORY B14 BLACK JV"),
            ("Peak SC 13/14B ZZ Black", "Peak SC 13/14B MH Black"),
            ("Avalanche 13/14B Black 2 DW", "Avalanche 2014 Black 1 DW"),
        ],
    )
    def test_different_coaches_or_squad_numbers_are_different_squads(self, provider, stored):
        assert _matcher()._squads_conflict(provider, stored)

    def test_the_same_coach_behind_an_age_token_is_one_squad(self):
        assert not _matcher()._squads_conflict("Strikers JH 14", "Strikers JH 14B")

    def test_the_state_word_in_a_club_name_is_not_a_coach(self):
        assert not _matcher()._squads_conflict("Avalanche U13B Black DW", "Avalanche 14B Black DW UT")

    def test_a_league_tag_is_not_read_as_part_of_the_club(self):
        assert _matcher()._club_for("Copper Mountain JM (SFC)", None) == "Copper Mountain"

    @pytest.mark.parametrize(
        "name, present, absent",
        [
            ("Cottonwood FC B1314 White JN", "2014", "B1314"),
            ("Peak SC 13/14B MH Black", "2014", "13/"),
            ("La Roca U12B- J Walker", "La Roca", "U12"),
            ("Club 12/14 Red", "12/14", "2014"),
        ],
    )
    def test_the_name_the_or_gates_read(self, name, present, absent):
        """A one-year band becomes its younger year, a glued U-age goes, and a two-year gap is left alone."""
        normalized = _normalize_for_affinity_ut(name)

        assert present in normalized
        assert absent not in normalized


class TestSquadKeyMatch:
    """A UYSA name finds its stored team by squad key, as merging-duplicate-teams pairs rows."""

    SIBLINGS = [
        _team("Avalanche 14B Black DW", "Utah Avalanche"),
        _team("Avalanche 14B Black SL", "Utah Avalanche"),
        _team("Avalanche 14B White DW", "Utah Avalanche"),
        _team("Metasport FC 14B ML", "MetaSport FC"),
        _team("Metasport FC 14B KR", "MetaSport FC"),
        _team("Strikers JH 14B", "Strikers FC"),
    ]

    def _match(self, name, rows=None):
        return _matcher(self.SIBLINGS if rows is None else rows)._squad_key_match(name, "u13", "Male", None)

    def test_a_squad_finds_its_stored_row_among_its_clubs_siblings(self):
        assert self._match("Avalanche U13B Black DW")["team_id_master"] == "Avalanche 14B Black DW"

    def test_a_league_tag_does_not_hide_the_squad(self):
        assert self._match("Metasport FC 13/14B U13 ML (SFC)")["team_id_master"] == "Metasport FC 14B ML"

    def test_a_different_coach_finds_nothing(self):
        assert self._match("Strikers DH 14") is None

    def test_two_stored_rows_for_one_squad_find_nothing(self):
        rows = self.SIBLINGS + [_team("Avalanche 2014 Black DW", "Utah Avalanche", team_id="twin")]

        assert self._match("Avalanche U13B Black DW", rows) is None

    def test_a_stored_row_of_another_cohort_is_not_taken(self):
        rows = [_team("Avalanche 2012 Black DW", "Utah Avalanche")]

        assert self._match("Avalanche U13B Black DW", rows) is None

    def test_a_band_is_compared_as_one_cohort(self):
        """Rewritten to a bare 2014, '13/14B' would read as U12 or U13 and pair with a U12 name."""
        rows = [_team("Avalanche U12B Black DW", "Utah Avalanche")]

        assert self._match("Avalanche 13/14B Black DW", rows) is None

    def test_a_band_pairs_with_its_older_year(self):
        rows = [_team("Avalanche 2013 Black DW", "Utah Avalanche")]

        assert self._match("Avalanche 13/14B Black DW", rows)["team_id_master"] == "Avalanche 2013 Black DW"

    def test_a_glued_band_finds_its_squad(self):
        rows = [_team("CFC B13/14 White JN", "Cottonwood FC"), _team("CFC B13/14 White MC", "Cottonwood FC")]

        assert self._match("Cottonwood FC B1314 White JN", rows)["team_id_master"] == "CFC B13/14 White JN"

    def test_another_clubs_squad_with_the_same_words_is_not_taken(self):
        assert self._match("Avalanche U13B Black", [_team("Celtic 14B Black", "Utah Celtic FC")]) is None

    def test_a_bracketed_rl_squad_is_not_a_bracketed_ecnl_squad(self):
        """In brackets neither name yields a tier token, so only the league check tells them apart."""
        rows = [_team("Avalanche 14B Black DW (ECNL)", "Utah Avalanche")]

        assert self._match("Avalanche U13B Black DW (ECNL RL)", rows) is None

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("Avalanche U13B Black DW (MLS NEXT)", "Avalanche 14B Black DW"),
            ("Avalanche U13B Black DW", "Avalanche 14B Black DW (MLS NEXT)"),
        ],
    )
    def test_a_bracketed_mls_next_squad_is_left_out_on_either_side(self, provider, stored):
        assert self._match(provider, [_team(stored, "Utah Avalanche")]) is None

    def test_a_stored_squad_in_another_state_is_not_taken(self):
        rows = [_team("Avalanche 14B Black DW", "Avalanche", state="VA")]

        assert self._match("Avalanche U13B Black DW", rows) is None

    def test_a_name_with_no_squad_words_takes_nothing(self):
        assert self._match("Avalanche U13B", [_team("Avalanche 14B", "Utah Avalanche")]) is None

    def test_a_stored_row_with_no_club_is_read_from_its_name(self):
        rows = [_team("Avalanche 14B Black DW", None)]

        assert self._match("Avalanche U13B Black DW", rows)["team_id_master"] == "Avalanche 14B Black DW"

    def test_a_stored_glued_band_is_read_as_a_band(self):
        rows = [_team("CFC B1314 White JN", "Cottonwood FC")]

        assert self._match("Cottonwood FC 13/14B White JN", rows)["team_id_master"] == "CFC B1314 White JN"

    def test_a_glued_birth_year_is_not_read_as_a_band(self):
        rows = [_team("Avalanche 14B Black DW", "Utah Avalanche")]

        assert self._match("Avalanche B2014 Black DW", rows)["team_id_master"] == "Avalanche 14B Black DW"

    def test_an_rl_squad_is_not_an_ecnl_squad(self):
        rows = [_team("Avalanche 14B Black DW ECNL", "Utah Avalanche")]

        assert self._match("Avalanche U13B Black DW RL", rows) is None

    def test_a_tier_named_on_one_side_only_is_a_different_squad(self):
        rows = [_team("La Roca U13B C Santos", "La Roca FC")]

        assert self._match("La Roca U13B- C Santos ECNL RL", rows) is None

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("Avalanche U13B Black DW MLS NEXT", "Avalanche 14B Black DW"),
            ("Avalanche U13B Black DW", "Avalanche 14B Black DW MLS NEXT"),
        ],
    )
    def test_an_mls_next_squad_is_left_out_on_either_side(self, provider, stored):
        assert self._match(provider, [_team(stored, "Utah Avalanche")]) is None

    def test_a_merged_away_row_is_not_a_candidate(self):
        rows = [
            _team("Avalanche 14B Black DW", "Utah Avalanche", team_id="survivor"),
            _team("Avalanche 2014 Black DW", "Utah Avalanche", team_id="gone", deprecated=True),
        ]

        assert self._match("Avalanche U13B Black DW", rows)["team_id_master"] == "survivor"

    def test_a_row_whose_name_says_girls_is_not_taken(self):
        assert self._match("Avalanche U13B Black DW", [_team("Avalanche 14G Black DW", "Utah Avalanche")]) is None

    def test_initials_the_key_drops_still_tell_squads_apart(self):
        """'AS' reads as Avalanche's initials and 'SA' as a noise word, so both keys are {black}."""
        assert self._match("Avalanche U13B Black AS", [_team("Avalanche 14B Black SA", "Utah Avalanche")]) is None


class TestFuzzyMatchTeam:
    """The full match path, through the real constructor and the OR gate loop."""

    def _match(self, name, rows, cls=AffinityUTGameMatcher, squad_key=True, age_group="u13"):
        matcher = cls(_DB(rows), provider_id="p")
        if not squad_key:
            matcher._squad_key_match = lambda *a: None
        return matcher, matcher._fuzzy_match_team(name, age_group, "Male")

    def test_the_squad_key_answers_first(self):
        _, match = self._match("Avalanche U13B Black DW", [_team("Avalanche 14B Black DW", "Utah Avalanche")])

        assert (match["team_id"], match["confidence"]) == ("Avalanche 14B Black DW", 0.95)

    def test_an_exact_name_under_another_club_field_scores_past_auto_approve(self):
        matcher, match = self._match(
            "Avalanche U13B Black DW", [_team("Avalanche U13B Black DW", "Utah Avalanche")], squad_key=False
        )

        assert match["confidence"] >= matcher.auto_approve_threshold

    def test_the_gates_read_utahs_spelling_rewritten(self):
        matcher = AffinityUTGameMatcher(_DB([]), provider_id="p")

        assert matcher._normalize_provider_name("Peak SC 13/14B MH Black") == "Peak SC 2014 MH Black"

    def test_the_gate_loop_refuses_initials_in_the_middle_of_a_name(self):
        _, match = self._match(
            "Peak SC 13/14B ZZ Black", [_team("Peak SC 13/14B MH Black", "Peak SC")], squad_key=False
        )

        assert match is None

    def test_two_squads_tied_for_best_take_neither(self):
        rows = [_team("Avalanche 2014 Black DW", "Utah Avalanche"), _team("Avalanche 2014 Black MC", "Utah Avalanche")]

        _, match = self._match("Avalanche U13B Black", rows)

        assert match is None

    def test_oregon_still_breaks_a_tie(self):
        rows = [
            _team("FC Portland 2013 Red", "FC Portland", state="OR", team_id="first"),
            _team("FC Portland 2013 Red", "FC Portland", state="OR", team_id="second"),
        ]

        _, match = self._match("FC Portland 13B Red", rows, cls=AffinityORGameMatcher)

        assert match["team_id"] == "first"

    def test_the_gate_loop_refuses_a_different_coach(self):
        _, match = self._match("Strikers DH 14", [_team("Strikers JH 14B", "Strikers FC")], squad_key=False)

        assert match is None

    def test_oregon_matches_its_own_club(self):
        rows = [_team("FC Portland 2013 Red", "FC Portland", state="OR", age_group="u13")]

        _, match = self._match("FC Portland 13B Red", rows, cls=AffinityORGameMatcher)

        assert match["team_id"] == "FC Portland 2013 Red"
