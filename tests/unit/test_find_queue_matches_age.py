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
