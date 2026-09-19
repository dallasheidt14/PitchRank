"""Unit tests for find_queue_matches season-year and age-cohort derivation.

The 2026-27 season moves youth soccer onto an Aug 1 - Jul 31 window, so a birth
year converts to a cohort as ``season_year - birth_year + 1``. These tests pin
the +1, the Aug 1 cutoff that feeds it, and the cohort the DB filter ends up
querying -- ``build_age_group_filter_clause`` hard-filters the candidate pool,
so an off-by-one here matches every team against the wrong cohort.
"""

import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from find_queue_matches import (  # noqa: E402
    UNMATCHABLE_AGE_GROUP,
    _age_group_from_birth_year,
    _current_season_year,
    build_age_group_filter_clause,
    extract_age_group,
    find_best_match,
)

from src.utils import team_utils  # noqa: E402


class TestAgeGroupFromBirthYear:
    def test_applies_season_year_plus_one(self):
        assert _age_group_from_birth_year(2016, 2026) == "u11"
        assert _age_group_from_birth_year(2014, 2026) == "u13"

    def test_folds_eighteen_into_nineteen(self):
        # Nothing stores u18: age_group_to_age folds 18 into 19 at write time,
        # so a u18 filter would match zero rows.
        assert _age_group_from_birth_year(2009, 2026) == "u19"
        assert _age_group_from_birth_year(2008, 2026) == "u19"

    def test_out_of_band_year_is_unmatchable(self):
        # Ages outside U7-U19 are not birth years. They must not resolve to a
        # real label: u3-u7 and u20-u21 all hold teams, and None would drop the
        # age filter and widen find_best_match to every cohort.
        assert _age_group_from_birth_year(2026, 2026) == UNMATCHABLE_AGE_GROUP  # age 1
        assert _age_group_from_birth_year(2021, 2026) == UNMATCHABLE_AGE_GROUP  # age 6
        assert _age_group_from_birth_year(2006, 2026) == UNMATCHABLE_AGE_GROUP  # age 21
        assert _age_group_from_birth_year(2003, 2026) == UNMATCHABLE_AGE_GROUP  # age 24

    def test_band_edges_are_inclusive(self):
        assert _age_group_from_birth_year(2020, 2026) == "u7"
        assert _age_group_from_birth_year(2008, 2026) == "u19"

    def test_year_one_past_the_season_is_unmatchable(self):
        # age == 0. Without the guard this reaches normalize_filter_age_group,
        # which reads 0 as falsy and returns None -- and None drops the age
        # filter, widening the candidate search to every cohort.
        assert _age_group_from_birth_year(2027, 2026) == UNMATCHABLE_AGE_GROUP

    def test_negative_age_does_not_land_on_a_real_cohort(self):
        # The sign is stripped downstream, so 2030 would otherwise resolve to
        # u3 -- a cohort that holds real teams.
        for birth_year in (2028, 2029, 2030, 2035):
            assert _age_group_from_birth_year(birth_year, 2026) == UNMATCHABLE_AGE_GROUP

    def test_sentinel_filters_to_a_cohort_no_team_holds(self):
        # Stored labels run u0..u21. The filter normalizer strips the trailing
        # letter, so the emitted clause still targets a single absent cohort.
        clause = build_age_group_filter_clause(UNMATCHABLE_AGE_GROUP)
        numbers = [int(n) for n in re.findall(r"age_group\.eq\.[uU](\d+)", clause)]
        assert numbers, f"sentinel produced no usable filter: {clause!r}"
        assert all(n > 21 for n in numbers), clause

    def test_u18_is_asked_for_as_u19_because_that_is_where_the_rows_are(self):
        # teams holds no u18 row -- the band is filed under u19 -- so a clause naming
        # u18 returns an empty candidate pool and the caller finds no match for a team
        # that exists. 466 live names resolve to u18.
        numbers = [int(n) for n in re.findall(r"age_group\.eq\.[uU](\d+)", build_age_group_filter_clause("u18"))]
        assert numbers == [19, 19]

    def test_u20_is_not_folded_because_teams_are_stored_there(self):
        numbers = [int(n) for n in re.findall(r"age_group\.eq\.[uU](\d+)", build_age_group_filter_clause("u20"))]
        assert numbers == [20, 20]

    def test_sentinel_is_refused_by_the_persistence_normalizer(self):
        # The regression this guards: a filter-only value reaching a teams INSERT.
        # discover_teams_from_opponents accepts "u" followed only by digits, so
        # the trailing letter is what stops the sentinel from being stored.
        assert not UNMATCHABLE_AGE_GROUP.removeprefix("u").isdigit()


class TestSoccerSeasonYearCutoff:
    """The Aug 1 cutoff itself, pinned without freezegun."""

    def _pin_clock(self, monkeypatch, when):
        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return when

        monkeypatch.setattr(team_utils, "datetime", _FixedDatetime)

    def test_july_31_is_previous_season_year(self, monkeypatch):
        self._pin_clock(monkeypatch, datetime(2026, 7, 31))
        assert team_utils._soccer_season_year() == 2025

    def test_august_1_rolls_the_season_year(self, monkeypatch):
        self._pin_clock(monkeypatch, datetime(2026, 8, 1))
        assert team_utils._soccer_season_year() == 2026

    def test_current_season_year_reads_module_attribute(self, monkeypatch):
        monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2031)
        assert _current_season_year() == 2031


class TestExtractAgeGroupSeasonBoundary:
    """A 2016-born team is u10 through Jul 31 2026 and u11 from Aug 1."""

    def test_standalone_year_before_cutover(self):
        assert extract_age_group("Dynamos SC 2016 SC", {}, season_year=2025) == "u10"

    def test_standalone_year_after_cutover(self):
        assert extract_age_group("Dynamos SC 2016 SC", {}, season_year=2026) == "u11"

    def test_gender_prefixed_four_digit_crosses_cutover(self):
        assert extract_age_group("Dynamos B2016 SC", {}, season_year=2025) == "u10"
        assert extract_age_group("Dynamos B2016 SC", {}, season_year=2026) == "u11"

    def test_gender_prefixed_two_digit_crosses_cutover(self):
        assert extract_age_group("Dynamos G16 SC", {}, season_year=2025) == "u10"
        assert extract_age_group("Dynamos G16 SC", {}, season_year=2026) == "u11"

    def test_u_age_token_is_not_shifted(self):
        # The U-age path reads a stated cohort rather than deriving one, so the
        # season year must not touch it.
        assert extract_age_group("Dynamos SC U11 SC", {}, season_year=2025) == "u11"
        assert extract_age_group("Dynamos SC 11U SC", {}, season_year=2026) == "u11"

    def test_defaults_to_the_live_season_year(self, monkeypatch):
        monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2026)
        assert extract_age_group("Dynamos SC 2016 SC", {}) == "u11"


class TestExtractAgeGroupTwoYearBand:
    """A band is named by its younger year: 2013/14 is u13 in 2026-27, never u14."""

    @pytest.mark.parametrize(
        "name",
        [
            "Dynamos 2013/2014 SC",
            "Dynamos 2013/14 SC",
            "Dynamos 13/14 SC",
            "Dynamos 14/13 SC",
            "Dynamos 2013-2014 SC",
            "Dynamos B13/14 SC",
            "Dynamos G2013/14 SC",
        ],
    )
    def test_every_spelling_reads_the_younger_year(self, name):
        assert extract_age_group(name, {}, season_year=2026) == "u13"

    def test_a_band_crosses_the_cutover_like_a_birth_year(self):
        assert extract_age_group("Dynamos 2013/14 SC", {}, season_year=2025) == "u12"

    def test_a_longer_run_of_years_falls_back_to_the_first_year(self):
        assert extract_age_group("Dynamos 2014 / 2015 / 2016 SC", {}, season_year=2026) == "u13"

    def test_a_stated_u_age_still_outranks_a_band(self):
        assert extract_age_group("Stingers U17 07/08", {}, season_year=2026) == "u17"

    def test_a_gender_attached_u_age_still_outranks_a_band(self):
        assert extract_age_group("Stingers BU17 07/08", {}, season_year=2026) == "u17"

    def test_a_season_written_into_the_name_does_not_stop_the_search(self):
        # "22/23" is a season, too young for a band, so B08 still decides.
        assert extract_age_group("Orange County B08 FC 22/23", {}, season_year=2026) == "u19"

    @pytest.mark.parametrize("name", ["FC Example 2006/2007 Boys", "FC Example B06/07", "FC Example 2007/2006"])
    def test_an_aged_out_band_is_unmatchable_rather_than_folded_into_u19(self, name):
        # A lone 2007 folds into U19, but the band 2007/06 is the group above it, and a
        # band that names no cohort must not fall through to the single-year rungs:
        # "2007/2006" is the spelling where they would read 2007 first.
        assert extract_age_group(name, {}, season_year=2026) == UNMATCHABLE_AGE_GROUP


class TestExtractAgeGroupGenderAttachedUAge:
    """A gender letter touching the U-age must not hide the cohort.

    ``BU9`` and ``U9B`` are ordinary GotSport spellings, and Priority 1 anchors both
    ends on ``\\b``, which cannot match between two word characters. The cohort went
    unparsed and ``build_unknown_profile`` fell through to its last resort -- the
    cohort of the team this one played -- so an eight-year-old squad was stored on
    whichever board its opponent sat on.

    Every case below kills a mutation no other case here kills: dropping ``[bg]?`` on
    either branch, narrowing it to ``[b]``, re-anchoring either right-hand side on
    ``\\b``, unbounding the digits, and dropping the U-first rung below the birth-year
    priorities.

    The two rungs are deliberately not symmetric: only the digit-first one carries a
    leading boundary and a gender class, because the U-first rung needs neither -- with
    nothing anchoring its left side, "BU9" matches at its own U. Both of the
    digit-first rung's bounds are pinned below.

    The digit-first rung's trailing guard is not, and cannot be from here: the U-first
    rung answers first for every "NuM" shape that would exercise it, so a fixture would
    pass whichever way that guard went. It is checked by mutating both rungs together,
    not by a case in this class.
    """

    def test_gender_letter_before_the_u_age(self):
        assert extract_age_group("New Canaan FC BU9 Black", {}, season_year=2026) == "u9"

    def test_gender_letter_after_the_u_age(self):
        assert extract_age_group("GCKA U8B Red", {}, season_year=2026) == "u8"

    def test_a_girls_prefix_resolves_like_a_boys_prefix(self):
        # Narrowing [bg] to [b] leaves every other case in this class green while
        # 3,568 girls-prefixed names fall back to the opponent's cohort again.
        assert extract_age_group("Spokane Shadow - GU11 Pre GA", {}, season_year=2026) == "u11"

    def test_a_gender_letter_before_the_digit_then_u_form(self):
        # With the U-age hidden, Priority 2b would read "g18" as birth year 2018 and
        # return u9, nine cohorts from the U18 stated here.
        # u18 rather than u19 because this branch preserves U18 by design, as the
        # comment on Priority 1b records; the fold happens at persistence.
        assert extract_age_group("Mankato United Soccer Club G18U", {}, season_year=2026) == "u18"

    def test_a_gender_letter_after_the_digit_then_u_form(self):
        assert extract_age_group("14UB - Inter Ohana CF Blanco", {}, season_year=2026) == "u14"

    def test_the_digit_then_u_form_outranks_a_birth_year_band(self):
        # The trailing "u" is the whole difference between a cohort and a birth year,
        # so it has to be read before the band is.
        # The band must disagree with the U-age, or the fixture passes either way:
        # B2014/15 names u12, B11U names u11.
        assert extract_age_group("Kernow Storm FC Spot B2014/15 B11U Leonard", {}, season_year=2026) == "u11"

    def test_a_gender_prefixed_two_digit_year_is_still_a_birth_year(self):
        # No trailing "u", so this stays with Priority 2b: B14 is the 2014 birth year.
        assert extract_age_group("Dynamos B14 Red", {}, season_year=2026) == "u13"

    def test_a_digit_run_inside_a_word_is_not_a_digit_then_u_age(self):
        # Only the digit-first rung's leading boundary declines this; its two-digit cap
        # does not, since "4" is one digit. Without the boundary the club's "SB4U"
        # reads as u4.
        assert extract_age_group("SB4U Milan RB 2014 EDP", {}, season_year=2026) == "u13"

    def test_a_four_digit_year_running_into_a_u_is_not_a_digit_then_u_age(self):
        # The digit-first cap declines "2014U" so Priority 3 reads the birth year.
        # Unbounded it answers the cohort "u2014", which no board holds.
        assert extract_age_group("2014USC Storm G", {}, season_year=2026) == "u13"


    def test_a_gender_prefixed_birth_year_is_still_a_birth_year(self):
        # The digits are capped at two so this is not a U-age. Unbounded it yields the
        # cohort "u2015", which the persistence normalizer refuses -- and discovery
        # reads that refusal as "the name said nothing" and stamps the opponent's
        # cohort, the very fallback this rung exists to close.
        assert extract_age_group("LAFC BU2015 - GOLD", {}, season_year=2026) == "u12"

    def test_a_gender_attached_u_age_outranks_a_birth_year_in_the_same_name(self):
        # The stated age group wins: a birth year needs a convention to resolve and
        # spans two cohorts either way. Dropping this rung below the birth-year
        # priorities reads the 2011 instead and answers u16.
        assert extract_age_group("Oakville Soccer Club - BU14C 2011", {}, season_year=2026) == "u14"


class _FakeQuery:
    """Chainable supabase query-builder stub that records its filters.

    ``not_`` sets a flag the next filter consumes, mirroring postgrest's
    negate_next.
    """

    def __init__(self, rows, recorder):
        self._rows = rows
        self._recorder = recorder
        self._select = ""
        self._negate_next = False

    def _record(self, op, *args):
        if self._negate_next:
            op = f"not.{op}"
            self._negate_next = False
        self._recorder.append((op, *args))
        return self

    def select(self, *cols, **_kwargs):
        self._select = ",".join(cols)
        return self

    def ilike(self, col, val):
        return self._record("ilike", col, val)

    def or_(self, clause, reference_table=None):
        # postgrest writes or= directly and never consumes negate_next, so the
        # flag must survive this call rather than being spent on it.
        self._recorder.append(("or", clause))
        return self

    def eq(self, col, val):
        return self._record("eq", col, val)

    def is_(self, col, val):
        return self._record("is", col, val)

    @property
    def not_(self):
        self._negate_next = True
        return self

    def limit(self, size, *, foreign_table=None):
        self._recorder.append(("limit", size))
        return self

    def execute(self):
        # The state lookup selects a single column; only the candidate fetch
        # should receive team rows.
        rows = [] if self._select.strip() == "state_code" else self._rows
        return type("R", (), {"data": rows})()


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.filters = []

    def table(self, _name):
        return _FakeQuery(self._rows, self.filters)


class TestFindBestMatchEndToEnd:
    """The derived cohort has to survive all the way to the DB filter."""

    QUEUE_ENTRY = {
        "provider_team_name": "Dynamos SC 2016",
        "match_details": {"club_name": "Dynamos SC", "gender": "male"},
    }

    def _candidate(self, age_group):
        return {
            "id": 1,
            "team_id_master": "dynamos-2016",
            "team_name": "Dynamos SC 2016",
            "club_name": "Dynamos SC",
            "gender": "male",
            "age_group": age_group,
            "state_code": "AZ",
        }

    def test_filters_candidates_on_the_rolled_cohort(self, monkeypatch):
        monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2026)
        monkeypatch.setattr(find_best_match, "_disable_tiebreaks", True, raising=False)
        client = _FakeClient([self._candidate("u11")])

        match, score, method = find_best_match(self.QUEUE_ENTRY, client, {})

        age_clauses = [f[1] for f in client.filters if f[0] == "or"]
        assert age_clauses, "expected an age_group filter on the candidate query"
        assert all("age_group.eq.u11" in clause for clause in age_clauses)
        assert all("age_group.eq.u10" not in clause for clause in age_clauses)
        assert match is not None and match["team_id_master"] == "dynamos-2016"
        assert score > 0.0

    def test_pre_cutover_season_year_filters_one_cohort_lower(self, monkeypatch):
        monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2025)
        monkeypatch.setattr(find_best_match, "_disable_tiebreaks", True, raising=False)
        client = _FakeClient([self._candidate("u10")])

        find_best_match(self.QUEUE_ENTRY, client, {})

        age_clauses = [f[1] for f in client.filters if f[0] == "or"]
        assert age_clauses
        assert all("age_group.eq.u10" in clause for clause in age_clauses)
