"""The placeholder team name, and the readers that select or group teams by it.

A team GotSport cannot name is stored as "Unknown team"; older ones are named
``unknown_<provider_team_id>``. Every reader must treat both as "no name": the scrape paths skip
them, the resolver selects them, and no duplicate finder may group them, since a placeholder
carries no identity.

The Supabase double here evaluates the filters it is given, ``or`` and ``like`` included, the way
PostgREST does, so a reader whose filter misses one placeholder form misses it here too.
"""

import importlib
import os
import re
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import backfill_unknown_team_names as backfill  # noqa: E402
from scripts import find_regid_duplicate_merges as regid  # noqa: E402
from src.utils.placeholder_team_names import (  # noqa: E402
    PLACEHOLDER_TEAM_NAME,
    PLACEHOLDER_TEAM_NAME_FILTER,
    is_placeholder_team_name,
)

GOTSPORT = "prov-gotsport"

# --------------------------------------------------------------------------- #
# The predicate
# --------------------------------------------------------------------------- #


def test_the_placeholder_name_is_unknown_team():
    assert PLACEHOLDER_TEAM_NAME == "Unknown team"


@pytest.mark.parametrize(
    "name, provider_team_id, placeholder",
    [
        ("Unknown team", "3912096", True),
        ("  unknown TEAM ", None, True),
        ("Unknown team", "", True),
        ("unknown_3912096", "3912096", True),
        ("UNKNOWN_3912096", "3912096", True),
        ("unknown_3912096", "3912097", False),
        ("unknown_3912096", "", False),
        ("unknown_3912096", None, True),
        (" Unknown_12 ", None, True),
        ("unknown_elite", "3912096", False),
        ("unknown_elite", None, False),
        ("unknown_FC Dallas", None, False),
        ("unknown_12 Blue", None, False),
        ("unknown_", None, False),
        ("unknown_٣٢", None, False),
        ("unknown_1234567890123", None, False),
        ("Unknown team Blue", None, False),
        ("Phoenix Rising 2014B", "3912096", False),
        (None, "3912096", False),
        ("", None, False),
    ],
    ids=[
        "new-name",
        "new-name-padded-any-case",
        "new-name-blank-id",
        "legacy-own-id",
        "legacy-upper",
        "legacy-another-id",
        "legacy-blank-id",
        "legacy-no-id",
        "legacy-no-id-padded",
        "real-unknown-word-with-id",
        "real-unknown-word-no-id",
        "real-unknown-club",
        "legacy-then-name",
        "bare-prefix",
        "non-ascii-digits",
        "unbounded-digits",
        "new-name-then-squad",
        "real-name",
        "null",
        "empty",
    ],
)
def test_a_placeholder_is_either_form_and_nothing_else(name, provider_team_id, placeholder):
    assert is_placeholder_team_name(name, provider_team_id) is placeholder


def test_the_candidate_filter_selects_both_forms():
    assert PLACEHOLDER_TEAM_NAME_FILTER == r"team_name.like.unknown\_%,team_name.eq.Unknown team"


# --------------------------------------------------------------------------- #
# A Supabase double that evaluates PostgREST filters
# --------------------------------------------------------------------------- #


def _like(pattern: str) -> re.Pattern:
    """SQL LIKE with backslash escapes; PostgREST also reads ``*`` as ``%``."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch in "%*" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def _term(term: str):
    column, op, value = term.split(".", 2)
    if op == "eq":
        return lambda row: row[column] == value
    if op == "like":
        regex = _like(value)
        return lambda row: row[column] is not None and bool(regex.fullmatch(row[column]))
    raise AssertionError(f"the double does not model the {op!r} filter")


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []
        self._columns = None
        self._order = None
        self._range = None
        self._negate = False

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def _add(self, check):
        negate, self._negate = self._negate, False
        self._filters.append((lambda row: not check(row)) if negate else check)
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def eq(self, column, value):
        return self._add(lambda row: row[column] == value)

    def is_(self, column, value):
        assert value == "null"
        return self._add(lambda row: row[column] is None)

    def like(self, column, pattern):
        return self._add(_term(f"{column}.like.{pattern}"))

    def or_(self, filters):
        checks = [_term(t) for t in filters.split(",")]
        return self._add(lambda row: any(check(row) for check in checks))

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def range(self, start, end):
        if self._order is None:
            raise AssertionError("range() without order() pages unstably")
        self._range = (start, end)
        return self

    def execute(self):
        rows = [r for r in self._rows if all(check(r) for check in self._filters)]
        if self._order:
            column, desc = self._order
            rows.sort(key=lambda r: r[column], reverse=desc)
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        return _Result([{c: r[c] for c in self._columns} for r in rows])


class _Supabase:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Query(self._tables[name])


def _team(team_id, name, provider_team_id, *, club=None, age_group="u12", state="CO", deprecated=False):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "provider_team_id": provider_team_id,
        "provider_id": GOTSPORT,
        "club_name": club,
        "age_group": age_group,
        "gender": "Male",
        "state_code": state,
        "is_deprecated": deprecated,
        "created_at": f"2026-11-{int(team_id[-2:]):02d}T00:00:00+00:00",
    }


# --------------------------------------------------------------------------- #
# The readers that select placeholders by name
# --------------------------------------------------------------------------- #

SELECTION = [
    _team("t01", "Unknown team", "640173"),
    _team("t02", "unknown_640174", "640174"),
    _team("t03", "Unknown team", "3912096"),
    _team("t04", "unknown_3912097", "3912097"),
    _team("t05", "unknown_elite", "640175"),
    _team("t06", "Rush 2015B Red", "640176"),
    _team("t07", "Unknown team", "640177", deprecated=True),
]


def test_the_name_backfill_selects_both_placeholder_forms():
    teams = backfill.fetch_placeholder_teams(
        _Supabase({"teams": SELECTION}), 100, None, None, backfill.DEFAULT_MAX_PROVIDER_ID, GOTSPORT
    )
    assert sorted(t["team_id_master"] for t in teams) == ["t01", "t02"]


def test_the_name_backfill_never_takes_a_placeholder_for_a_resolved_name():
    assert not backfill._is_valid_name("Unknown team", "640173")
    assert not backfill._is_valid_name("unknown_640173", "640173")
    assert backfill._is_valid_name("Rush 2015B Red", "640173")


def test_the_registration_id_scan_selects_both_placeholder_forms():
    placeholders = regid.load_placeholders(_Supabase({"teams": SELECTION}), GOTSPORT)
    assert sorted(placeholders) == ["t03", "t04"]


# --------------------------------------------------------------------------- #
# The exact-name duplicate finders, which group by name without score_team_pair
# --------------------------------------------------------------------------- #

COHORT = [
    _team("t11", "Unknown team", "3912096"),
    _team("t12", "Unknown team", "3912097"),
    _team("t13", "unknown_3912098", "3912098"),
    _team("t14", "unknown_3912098", "3912098"),
    _team("t15", "Rush 2015B Red", "640176", club="Rush"),
    _team("t16", "Rush 2015B Red", "640177", club="Rush"),
]


@pytest.fixture
def exact_name_finder(monkeypatch):
    """Both modules build a Supabase client at import, so give them credentials it accepts."""
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setenv("SUPABASE_KEY", "dummy.key.value")

    def load(module_name):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "supabase", _Supabase({"teams": COHORT, "team_alias_map": []}))
        return module

    return load


def test_the_all_cohort_exact_name_merge_never_groups_placeholders(exact_name_finder):
    run_all_merges = exact_name_finder("scripts.run_all_merges")

    duplicates, scanned = run_all_merges.find_duplicates_for_cohort("CO", "Male", "u12")

    assert scanned == len(COHORT)
    assert [(d["deprecated_name"], d["canonical_name"]) for d in duplicates] == [("Rush 2015B Red", "Rush 2015B Red")]


def test_the_exact_name_report_never_groups_placeholders(exact_name_finder, capsys):
    find_duplicates = exact_name_finder("scripts.find_duplicates")

    find_duplicates.find_duplicates("CO", "Male", "u12")

    out = capsys.readouterr().out
    assert "Exact duplicates (safe): 1" in out
    assert "Unknown team" not in out and "unknown_3912098" not in out
