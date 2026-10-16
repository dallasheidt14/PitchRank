"""The unknown-opponent auto-match never links one squad of a club's birth-year band to another.

The shared scorer compares one variant word, so "Cincy SC B18-19 Elite" against "Cincy SC
B18-19 Premier", a squad number against another, or "Gold" against "Gold II" all score a
perfect match, and the weekly run linked such pairs. match_row now passes over a candidate
whose squad words after the year differ, so the next candidate can win and a row with none
left is a no-match, which discovery turns into the squad's own team.
"""

import re
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from scripts import auto_match_unknown_opponents as amu

# The live teams columns (information_schema, 2026-10-16). PostgREST refuses a select naming
# any other, so the double does too.
_TEAMS_COLUMNS = frozenset(
    "age_group birth_year club_name created_at distinction game_row_count gender id is_deprecated"
    " last_fixture_at last_played_at last_scraped_at league provider_id provider_team_id"
    " scrape_attempts state state_assigned_at state_code state_confidence state_source"
    " team_id_master team_name team_name_original updated_at".split()
)


def _like(value, pattern):
    if value is None:
        return False
    regex = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern)
    return re.fullmatch(regex, str(value), re.I) is not None


def _clause(row, field, op, value):
    if op == "eq":
        return str(row.get(field)) == value
    raise AssertionError(f"filter the double does not model: {field}.{op}.{value}")


class _Query:
    """Applies its filters, returns only the selected columns, and records at execute()."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.tests, self.columns, self.cap = [], None, None

    def select(self, *columns, **_k):
        names = [name.strip() for arg in columns for name in arg.split(",")]
        self.columns = None if names in ([], ["*"]) else names
        return self

    def eq(self, field, value):
        self.tests.append(lambda row: row.get(field) == value)
        return self

    def ilike(self, field, pattern):
        self.tests.append(lambda row: _like(row.get(field), pattern))
        return self

    def or_(self, expression):
        clauses = [clause.split(".", 2) for clause in expression.split(",")]
        self.tests.append(lambda row: any(_clause(row, *clause) for clause in clauses))
        return self

    def limit(self, n):
        self.cap = n
        return self

    def execute(self):
        unknown = sorted(set(self.columns or ()) - _TEAMS_COLUMNS) if self.table == "teams" else []
        if unknown:
            raise APIError({"code": "42703", "message": f"column teams.{unknown[0]} does not exist"})
        self.db.executed.append(self.table)
        rows = [row for row in self.db.rows.get(self.table, []) if all(test(row) for test in self.tests)]
        if self.columns is not None:
            rows = [{name: row.get(name) for name in self.columns} for row in rows]
        return SimpleNamespace(data=rows[: self.cap] if self.cap is not None else rows)


class _DB:
    def __init__(self, teams):
        self.rows = {"teams": list(teams)}
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _team(team_id, name, club, age_group, gender="Male"):
    return {
        "id": 1,
        "team_id_master": team_id,
        "team_name": name,
        "club_name": club,
        "age_group": age_group,
        "gender": gender,
        "state_code": "MO",
        "is_deprecated": False,
        "provider_team_id": "999999",
    }


def _decide(unknown_name, club, age_group, candidates, gender="Male"):
    db = _DB(candidates)
    row = {
        "provider_code": "gotsport",
        "unknown_provider_team_id": "754784",
        "unknown_team_name": unknown_name,
        "unknown_club_name": club,
        "unknown_age": age_group,
        "unknown_gender": gender,
    }
    result = amu.match_row(row, db, None, False, 160, 0.95, 0.90, {})
    assert db.executed, "match_row must fetch its candidates through the database"
    best = result["best_match"]
    return result["action"], best["team_id_master"] if best else None


@pytest.mark.parametrize(
    "unknown,candidate,club,age_group,gender",
    [
        ("SLSG MO B 2016/2017 Rennes", "SLSG MO B 2016/2017 Flamengo", "St. Louis Scott Gallagher", "u10", "Male"),
        ("Cincy SC B18-19 Elite", "Cincy SC B18-19 Premier", "Cincy SC", "u8", "Male"),
        ("TCSL Blue B2017/18 7", "TCSL Blue B2017/18 5", "St. Paul Blackhawks", "u9", "Male"),
        (
            "Legends FC (CA) PRE ECNL B2014/15 Gold",
            "Legends FC (CA) PRE ECNL B2014/15 Gold II",
            "Legends FC (CA)",
            "u12",
            "Male",
        ),
        # GA is a program here, not Georgia, so it is a squad word like any other tier.
        ("Club B2014/15 GA", "Club B2014/15 ECNL", "Club", "u12", "Male"),
    ],
)
def test_another_squad_of_the_band_is_not_linked(unknown, candidate, club, age_group, gender):
    candidates = [_team("wrong", candidate, club, age_group, gender)]
    assert _decide(unknown, club, age_group, candidates, gender) == ("no_match", None)


@pytest.mark.parametrize(
    "unknown,candidate,club,age_group,gender",
    [
        (
            "East Valley NSFC N1 B11/12 Walden AZ",
            "East Valley NSFC 11/12 Boys Walden",
            "East Valley/NSFC",
            "u15",
            "Male",
        ),
        (
            "East Valley FC N1 G09/10 McMullin AZ",
            "East Valley FC 09/10 Girls McMullin",
            "East Valley/NSFC",
            "u17",
            "Female",
        ),
        (
            "East Valley NSFC N1 G08/09 Walsh AZ",
            "East Valley FC 08/09 Girls Walsh",
            "East Valley/NSFC",
            "u19",
            "Female",
        ),
        (
            "MISSISSIPPI RUSH 2016/2017 BOYS MADISON PREMIER U10",
            "MS Rush 16/17B Madison Premier",
            "Mississippi Rush",
            "u10",
            "Male",
        ),
        ("TCSL Blue B2018/19 Red U8", "TCSL Blue B2018/19 Red", "Centennial Soccer Club", "u8", "Male"),
        (
            "St. Louis Fire FC - 18/19B Inferno (7v7)",
            "St. Louis Fire FC - 18/19B Inferno",
            "Saint Louis Fire FC",
            "u8",
            "Male",
        ),
        # A program written before the year on one side and after it on the other.
        ("Club ECNL B2014/15 Blue", "Club B2014/15 ECNL Blue", "Club", "u12", "Male"),
        # A second band after the first is dropped whole, leaving no "15" to read as a squad.
        ("PDA G2014 Pre-ECNL G2014/15 Mon", "PDA Pre-ECNL G2014/15 Mon", "PDA", "u12", "Female"),
        ("Kirkwood United 18/19B Red Hart", "Kirkwood United 18/19B Hart Red", "Kirkwood United SC", "u8", "Male"),
        ("Kirkwood United 18/19B Hart Red", "Kirkwood United 18/19B Red Hart", "Kirkwood United SC", "u8", "Male"),
    ],
)
def test_the_same_squad_written_another_way_still_links(unknown, candidate, club, age_group, gender):
    candidates = [_team("same", candidate, club, age_group, gender)]
    assert _decide(unknown, club, age_group, candidates, gender) == ("auto_link", "same")


def test_another_squad_does_not_block_the_squads_own_row():
    candidates = [
        _team("premier", "Cincy SC B18-19 Premier", "Cincy SC", "u8"),
        _team("elite", "Cincy SC 2018/19 Boys Elite", "Cincy SC", "u8"),
    ]
    assert _decide("Cincy SC B18-19 Elite", "Cincy SC", "u8", candidates) == ("auto_link", "elite")


@pytest.mark.parametrize(
    "unknown,candidate",
    [("SLSG MO B 2016/2017", "SLSG MO B 2016/2017 Elite"), ("SLSG MO B 2016/2017 Elite", "SLSG MO B 2016/2017")],
)
def test_a_name_with_no_squad_after_its_year_is_left_to_the_scorer(unknown, candidate):
    candidates = [_team("slsg", candidate, "St. Louis Scott Gallagher", "u10")]
    assert _decide(unknown, "St. Louis Scott Gallagher", "u10", candidates) == ("auto_link", "slsg")


@pytest.mark.parametrize(
    "unknown,candidate", [("Cincy SC B18-19 Elite", "Cincy SC Elite"), ("Cincy SC Elite", "Cincy SC B18-19 Elite")]
)
def test_a_name_with_no_year_is_left_to_the_scorer(unknown, candidate):
    candidates = [_team("elite", candidate, "Cincy SC", "u8")]
    assert _decide(unknown, "Cincy SC", "u8", candidates) == ("review", "elite")
