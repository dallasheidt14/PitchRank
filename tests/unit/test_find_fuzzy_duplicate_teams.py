"""Tests for the fuzzy duplicate finder's cohort fetch.

The Supabase double here evaluates its filters rather than recording them. A double
that returns canned rows would pass green for a fetch that read the wrong cohort, and
-- the defect this file exists for -- for one that pages a table with no sort key. This
one:

  - applies eq / ilike / or_ rather than recording them,
  - projects rows down to the selected columns, so reading a column the query did not
    ask for raises here exactly as it would in production,
  - requires order() before range(), because PostgREST leaves row order unspecified
    without it and paging then drops and duplicates part of the input,
  - serves each page from the ordering the caller actually asked for, so a test can
    observe the rows a real pager would have lost.
"""

import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import find_fuzzy_duplicate_teams as ffdt  # noqa: E402

COLUMNS = ("team_id_master", "team_name", "club_name", "state_code", "age_group", "gender")


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, name, rows):
        self.name = name
        self._rows = rows
        self._eq = []
        self._ilike = []
        self._or = None
        self._columns = None
        self._order = None

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def ilike(self, column, value):
        self._ilike.append((column, value))
        return self

    def or_(self, expression):
        self._or = expression
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def _or_matches(self, row):
        if self._or is None:
            return True
        for clause in self._or.split(","):
            column, op, value = clause.split(".", 2)
            if op != "eq":
                raise AssertionError(f"double models only eq inside or_, got {op!r}")
            if row[column] == value:
                return True
        return False

    def _matching(self):
        rows = []
        for row in self._rows:
            if any(row[c] != v for c, v in self._eq):
                continue
            if any(str(row[c]).lower() != str(v).lower() for c, v in self._ilike):
                continue
            if not self._or_matches(row):
                continue
            rows.append(row)
        return rows

    def range(self, start, end):
        if self._order is None:
            raise AssertionError(f"{self.name}: range() without order() pages a table unstably")
        column, desc = self._order
        rows = sorted(self._matching(), key=lambda r: r[column], reverse=desc)
        self._page = rows[start : end + 1]
        return self

    def execute(self):
        return _Result([{c: r[c] for c in self._columns} for r in self._page])


class _Supabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        if name != "teams":
            raise AssertionError(f"no rows seeded for table {name!r}")
        return _Table(name, self._rows)


def team(index, *, age_group="u16", gender="Male", state_code="OR", is_deprecated=False):
    """A row as `teams` holds it -- including the columns the query filters on but
    does not select, since PostgREST filters those the same way."""
    return {
        "team_id_master": f"team-{index:05d}",
        "team_name": f"Team {index}",
        "club_name": f"Club {index}",
        "state_code": state_code,
        "age_group": age_group,
        "gender": gender,
        "is_deprecated": is_deprecated,
    }


def test_fetch_teams_orders_before_paging():
    """Removing the .order() makes the double raise, exactly as unstable paging deserves."""
    sb = _Supabase([team(i) for i in range(5)])

    rows = ffdt.fetch_teams(sb, "u16", "male")

    assert len(rows) == 5


def test_fetch_teams_returns_every_row_across_page_boundaries():
    """The whole cohort arrives, not a floor of it.

    2,500 rows spans three pages. An unordered pager loses part of its own input here
    rather than merely returning it out of order, which is why the count is the assertion.
    """
    sb = _Supabase([team(i) for i in range(2500)])

    rows = ffdt.fetch_teams(sb, "u16", "male")

    assert len(rows) == 2500
    assert len({r["team_id_master"] for r in rows}) == 2500


def test_fetch_teams_stops_on_a_short_final_page():
    sb = _Supabase([team(i) for i in range(1000)])

    rows = ffdt.fetch_teams(sb, "u16", "male")

    assert len(rows) == 1000


def test_fetch_teams_reads_only_the_named_cohort():
    sb = _Supabase(
        [team(0), team(1, age_group="u15"), team(2, gender="Female"), team(3, age_group="U16")]
    )

    rows = ffdt.fetch_teams(sb, "u16", "male")

    assert {r["team_id_master"] for r in rows} == {"team-00000", "team-00003"}


def test_fetch_teams_folds_u18_into_the_u19_cohort():
    sb = _Supabase([team(0, age_group="u18"), team(1, age_group="u19"), team(2, age_group="u17")])

    rows = ffdt.fetch_teams(sb, "u19", "male")

    assert {r["team_id_master"] for r in rows} == {"team-00000", "team-00001"}


def test_fetch_teams_scopes_to_state_when_given():
    sb = _Supabase([team(0, state_code="OR"), team(1, state_code="WA")])

    rows = ffdt.fetch_teams(sb, "u16", "male", state="or")

    assert {r["team_id_master"] for r in rows} == {"team-00000"}


def test_fetch_teams_rejects_a_gender_that_is_neither():
    with pytest.raises(ValueError):
        ffdt.fetch_teams(_Supabase([]), "u16", "other")
