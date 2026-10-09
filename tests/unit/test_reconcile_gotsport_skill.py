# ruff: noqa: E501 -- expected reasons are literal strings, kept whole so a test reads as the rule it pins
"""Decision rules and guarded writes of the reconcile-gotsport skill's scripts.

The fixtures are teams from the 2026-10-09 Arizona run: Bala FC and RSL Arizona South's
reused records, 15B OMolina's relabel, Brazas FC 2016 Black's colour match, Utah Royals'
girls squad that plays boys, and the dormant teams the owner left as stored.
"""

import csv
import importlib
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / ".claude/skills/reconcile-gotsport/scripts"
sys.path.insert(0, str(TOOLS))
triage = importlib.import_module("triage_reconcile")
fields = importlib.import_module("apply_team_fields")

DORMANT = ("hold", "no games since Aug 1; likely dormant, stored age kept")
STORED = ("hold", "this season's opponents back the stored age")


# ----------------------------------------------------------------------------- classify


@pytest.mark.parametrize(
    "args,expected",
    [
        # stored, theirs, same_squad, pre, fall, fall_games, fall_read, band
        ((13, 12, True, None, None, 0, 0, None), DORMANT),
        ((11, 12, True, 11.0, 12.0, 0, 0, None), DORMANT),  # GotSport older, dormant
        ((13, 12, True, 13.0, 12.0, 1, 1, 13), ("hold", "the band in our own name backs the stored age")),
        ((11, 13, True, 11.0, 13.0, 8, 8, 12), ("hold", "the band in our own name says U12, neither ours nor GotSport's")),
        ((11, 10, True, 11.0, 10.0, 4, 2, None), ("hold", "only 2 game(s) this season with a readable opponent age")),
        ((11, 10, True, 11.0, 11.5, 5, 5, None), STORED),
        ((11, 10, True, 11.0, 11.5001, 5, 5, None), ("hold", "this season's opponents sit at U11.5001, neither ours nor GotSport's")),
        # 15B OMolina: same squad, did not age up
        ((12, 11, True, 12.0, 11.0, 12, 12, None), ("relabel", "same squad; this season's opponents sit at GotSport's age")),
        # 16B Wagner, now U10B Etgar: GotSport younger
        ((11, 10, False, 11.0, 10.0, 4, 4, None), ("reused_id", "GotSport's name is another squad; opponents dropped a group at Aug 1")),
        # CCV Stars 2016 North Orange, now a 2014/15 squad: GotSport older
        ((11, 12, False, 11.0, 12.5, 16, 16, None), ("reused_id", "GotSport's name is another squad; opponents dropped a group at Aug 1")),
        ((11, 10, False, 10.0, 10.0, 6, 6, None), ("hold", "GotSport's name is another squad but last season does not show the old cohort")),
        # Bala FC - 2016: no squad word survives the club and the year
        ((11, 10, None, 11.0, 10.0, 4, 4, None), ("hold", "a name carries no squad word to compare; decide from the club's other teams")),
    ],
)
def test_classify(args, expected):
    assert triage.classify(*args) == expected


def test_classify_counts_dormancy_by_games_not_readable_opponents():
    # Three fall games against opponents whose age nothing states: active, not dormant.
    assert triage.classify(11, 10, True, 11.0, None, 3, 0, None) == (
        "hold",
        "only 0 game(s) this season with a readable opponent age",
    )


# ----------------------------------------------------------------------- classify_gender

FIX_NAME_OPP = ("gender_fix", "GotSport's gender, backed by our name and opponents' names")


@pytest.mark.parametrize(
    "args,expected",
    [
        # ours, theirs, spelled, affix, opponents, seasons_split, fall_games
        (("Female", "Male", "Male", "Male", "Male", False, 5), FIX_NAME_OPP),
        # "18 Boys Soul Warriors #2": the spelled word alone suffices
        (("Female", "Male", "Male", "Male", "", False, 2), ("gender_fix", "GotSport's gender, backed by our name")),
        # "U10B Saxelby": the affix counts beside agreeing opponents
        (("Female", "Male", "", "Male", "Male", False, 4), FIX_NAME_OPP),
        # an affix alone is a single letter: not enough
        (("Female", "Male", "", "Male", "", False, 4), ("hold", "GotSport's gender differs from ours, and neither our name nor opponents' names say which")),
        # an affix agreeing with ours is a witness against
        (("Female", "Male", "", "Female", "Male", False, 4), ("hold", "GotSport's gender differs from ours, but our name back ours")),
        # Utah Royals FC AZ PRE ECNL U11: stored Male, boys opponents
        (("Male", "Female", "", "", "Male", False, 25), ("hold", "GotSport's gender differs from ours, but opponents' names back ours")),
        # Leoncitos FC Blue: opponents alone, no games since Aug 1
        (("Female", "Male", "", "", "Male", False, 0), ("hold", "GotSport's gender rests on opponents alone and no games since Aug 1; likely dormant")),
        # a name that spells the gender is not held for dormancy
        (("Female", "Male", "Male", "Male", "", False, 0), ("gender_fix", "GotSport's gender, backed by our name")),
        (("Female", "Male", "", "", "Male", True, 5), ("hold", "opponents' names point one way last season and the other this season; the record may be reused")),
        (("Female", "Male", "", "", "", False, 5), ("hold", "GotSport's gender differs from ours, and neither our name nor opponents' names say which")),
    ],
)
def test_classify_gender(args, expected):
    assert triage.classify_gender(*args) == expected


def test_majority_gender_needs_a_strict_majority():
    assert triage.majority_gender(["U10 Boys Red", "U10 Girls Blue"])[0] == ""
    assert triage.majority_gender(["U10 Boys Red", "U10 Girls Blue", "B2016 Copa"])[0] == "Male"
    assert triage.majority_gender(["Leoncitos FC", "Angeles F.C"])[0] == ""


# ------------------------------------------------------------------- names and cohorts


def test_cohort_years_2026_27():
    assert triage.cohort_years(13, season=2026) == {2014, 2013}
    assert triage.cohort_years(17, season=2026) == {2010, 2009}
    # u19 holds the U18 band PitchRank files into it, and nothing younger
    assert triage.cohort_years(19, season=2026) == {2008, 2007, 2009}


def test_squad_words():
    assert triage.squad_words("16B Wagner", "RSL Arizona South") == {"wagner"}
    assert triage.squad_words("U10B Etgar", "RSL Arizona South") == {"etgar"}
    # "south" is a compass word, not a squad: it alone made two RSL squads look like one
    assert triage.squad_words("RSL AZ South U10B Wagner", "RSL Arizona") == {"wagner"}
    assert triage.squad_words("Bala FC - 2016", "Bala FC") == set()
    assert triage.squad_words("BU12 Red", "") == {"red"}


def test_group_number_folds_u18_into_u19():
    assert triage.group_number("U18") == 19
    assert triage.group_number("u10") == 10
    assert triage.group_number("u") is None


@pytest.mark.parametrize(
    "bands,expected",
    [
        (["u10", "u10", "u11"], ("mixed", 2, 1)),
        (["u10", "u10", "u10", None], ("backs_move", 3, 0)),
        (["u11", "u11", "u11", "u10"], ("backs_current", 1, 3)),
        (["u10", None, "u9"], ("thin", 1, 0)),
    ],
)
def test_fixture_verdict_matches_fix_band_cohorts(bands, expected):
    assert triage.fixture_verdict(bands, "u10", "u11") == expected


# --------------------------------------------------------------- apply_team_fields


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Applies every .eq filter, projects selected columns, records at execute()."""

    def __init__(self, db, columns=None, payload=None):
        self._db, self._columns, self._payload, self._filters = db, columns, payload, {}

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def limit(self, _n):
        return self

    def execute(self):
        rows = [t for t in self._db.teams.values() if all(t.get(c) == v for c, v in self._filters.items())]
        if self._payload is None:
            return _Result([{c: t.get(c) for c in self._columns} for t in rows])
        for t in rows:
            t.update(self._payload)
        self._db.writes.append((dict(self._filters), dict(self._payload)))
        return _Result([dict(t) for t in rows])


class _Db:
    def __init__(self, *teams):
        self.teams = {t["team_id_master"]: dict(t) for t in teams}
        self.writes = []

    def table(self, name):
        assert name == "teams"
        db = self

        class _T:
            def select(self, cols):
                return _Query(db, columns=[c.strip() for c in cols.split(",")])

            def update(self, payload):
                return _Query(db, payload=payload)

        return _T()


def _team(tid, **kw):
    return {"team_id_master": tid, "team_name": "U10B Saxelby", "gender": "Female", "is_deprecated": False, **kw}


@pytest.mark.parametrize(
    "team,expected,changed",
    [
        (_team("a"), "updated", True),
        (_team("a", gender="Male"), "already_applied", False),
        (_team("a", gender="Other"), "skipped_changed_since", False),  # old-value guard
        (_team("a", is_deprecated=True), "skipped_deprecated", False),  # deprecated guard
    ],
)
def test_set_field_writes_only_where_every_guard_holds(team, expected, changed):
    db = _Db(team)
    assert fields.set_field(db, "a", "gender", "Female", "Male") == expected
    assert (db.teams["a"]["gender"] == "Male" and team["gender"] != "Male") is changed


def test_set_field_reports_a_missing_team():
    assert fields.set_field(_Db(), "nope", "gender", "Female", "Male") == "skipped_missing"


def test_set_field_never_writes_another_team():
    db = _Db(_team("a"), _team("b"))
    fields.set_field(db, "a", "gender", "Female", "Male")
    assert db.teams["b"]["gender"] == "Female"


def _log(path, rows):
    fields.write_rows(rows, path, fields.LOG_COLUMNS)
    return path


def test_revert_undoes_a_chain_last_write_first(tmp_path):
    db = _Db(_team("a", team_name="C"))
    log = _log(
        tmp_path / "log.csv",
        [
            {"team_id_master": "a", "team_name": "A", "field": "team_name", "old_value": "A", "new_value": "B", "result": "updated"},
            {"team_id_master": "a", "team_name": "B", "field": "team_name", "old_value": "B", "new_value": "C", "result": "updated"},
        ],
    )
    fields.revert(db, log, execute=True)
    assert db.teams["a"]["team_name"] == "A"


def test_revert_of_an_unapplied_row_writes_nothing_visible(tmp_path):
    db = _Db(_team("a"))
    log = _log(
        tmp_path / "log.csv",
        [{"team_id_master": "a", "team_name": "U10B Saxelby", "field": "gender", "old_value": "Female", "new_value": "Male", "result": "planned_not_applied"}],
    )
    # The guard on the value this run would have written matches nothing.
    assert fields.revert(db, log, execute=True) == {"already_applied": 1}
    assert db.teams["a"]["gender"] == "Female"
    assert db.writes == [({"team_id_master": "a", "is_deprecated": False, "gender": "Male"}, {"gender": "Female"})]


def test_plan_text_round_trips_through_escaping(tmp_path):
    rows = [{"team_id_master": "a", "team_name": "=HYPERLINK(1)", "field": "team_name", "old_value": "'quoted", "new_value": "+x"}]
    path = tmp_path / "plan.csv"
    fields.write_rows(rows, path, list(fields.PLAN_COLUMNS))
    raw = next(csv.DictReader(path.open(encoding="utf-8")))
    assert raw["team_name"] == "'=HYPERLINK(1)"
    back = fields.read_rows(path)[0]
    assert (back["team_name"], back["old_value"], back["new_value"]) == ("=HYPERLINK(1)", "'quoted", "+x")


def test_read_rows_accepts_an_excel_bom_and_refuses_bad_values(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text("﻿team_id_master,team_name,field,old_value,new_value\na,X,gender,Female,Male\n", encoding="utf-8")
    assert fields.read_rows(path)[0]["team_id_master"] == "a"
    path.write_text("team_id_master,team_name,field,old_value,new_value\na,X,gender,Female,Boys\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        fields.read_rows(path)
    path.write_text("team_id_master,team_name,field,old_value,new_value\na,X,age_group,u11,u10\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        fields.read_rows(path)
