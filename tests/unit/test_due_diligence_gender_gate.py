"""The weekly unknown-opponent gate holds a record whose gender contradicts the team it would join,
or whose gender nothing reads.

This drives ``main`` itself: a team stored under the wrong gender is caught only by its names, which
reach the check only if the team select asks for them, and a test of the verdict alone would hand
them over regardless.
"""

import csv
import sys
from types import SimpleNamespace

import pytest

from scripts import due_diligence_unknown_opponents as dd

PROVIDER_ID = "gotsport-uuid"


class _Query:
    """Applies its filters, returns only the selected columns, and records at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._columns = None
        self._filters = []

    def select(self, columns="*"):
        self._columns = None if columns.strip() == "*" else [c.strip() for c in columns.split(",")]
        return self

    def eq(self, column, value):
        self._filters.append(lambda r, c=column, v=value: r.get(c) == v)
        return self

    def ilike(self, column, pattern):
        self._filters.append(lambda r, c=column, p=pattern.strip("%").lower(): str(r.get(c) or "").lower() == p)
        return self

    def in_(self, column, values):
        self._filters.append(lambda r, c=column, v=list(values): r.get(c) in v)
        return self

    def or_(self, expression):
        clauses = [part.split(".", 2) for part in expression.split(",")]
        if any(op != "eq" for _, op, _ in clauses):
            raise AssertionError(f"or_ clause this double does not model: {expression}")
        self._filters.append(lambda r, cs=clauses: any(str(r.get(c)) == v for c, _, v in cs))
        return self

    def limit(self, _count):
        return self

    def __getattr__(self, name):
        raise AssertionError(f"_Query.{name} is not modelled; model it or the test proves nothing")

    def execute(self):
        self._db.executed.append(self._table)
        rows = [r for r in self._db.tables[self._table] if all(f(r) for f in self._filters)]
        if self._columns:
            rows = [{c: r.get(c) for c in self._columns} for r in rows]
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, tables):
        self.tables = tables
        self.executed = []

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"unexpected table {name!r}")
        return _Query(self, name)


def _team(team_id, name, gender, original=None):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": original,
        "club_name": "Lou Fusz Athletic",
        "age_group": "u9",
        "gender": gender,
        "state_code": "MO",
    }


def _record(name, gender):
    return {"name": name, "club_name": "Lou Fusz Athletic", "state": "MO", "age_group": "u9", "gender": gender}


def _report_row(pid, team_id, name_used, gender_used="", provider_gender=""):
    """A match-report row. ``gender_used`` is what the matcher filled, the opponent's gender when
    nothing else answered; ``provider_gender`` is the export's GotSport gender for the record."""
    return {
        "provider_code": "gotsport",
        "provider_id": PROVIDER_ID,
        "unknown_provider_team_id": pid,
        "missing_side": "away",
        "games_count": "3",
        "unknown_team_name_used": name_used,
        "unknown_gender_used": gender_used,
        "unknown_provider_gender": provider_gender,
        "action": "auto_link",
        "best_score": "0.9700",
        "matched_team_id_master": team_id,
    }


@pytest.fixture
def run_gate(tmp_path, monkeypatch):
    def run(teams, answers, report_rows):
        report = tmp_path / "match_report.csv"
        with report.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0]))
            writer.writeheader()
            writer.writerows(report_rows)
        db = _DB({"teams": teams, "team_alias_map": [], "games": []})
        monkeypatch.setattr(dd, "load_env", lambda: None)
        monkeypatch.setattr(dd, "get_supabase", lambda: db)
        # GotSport's team_details as the gate's resolver returns it; {} is a failed lookup.
        resolver = SimpleNamespace(resolve=lambda pid: answers.get(pid, {}))
        monkeypatch.setattr(dd, "GotSportResolver", lambda: resolver)
        prefix = tmp_path / "dd"
        monkeypatch.setattr(sys, "argv", ["dd", "--match-report", str(report), "--output-prefix", str(prefix)])
        dd.main()

        def read(kind):
            path = tmp_path / f"dd_{kind}.csv"
            with path.open(encoding="utf-8") as f:
                return {r["unknown_provider_team_id"]: r for r in csv.DictReader(f)}

        return read("approved"), read("needs_review")

    return run


def test_a_girls_record_is_held_from_a_boys_named_row_stored_as_girls(run_gate):
    """LFA, 2026-09-15: GotSport said girls, the row was stored as girls, and its name said boys."""
    approved, review = run_gate(
        teams=[_team("lfa-boys", "LFA 17/18B Red Star Swift (2036)", "Female")],
        answers={"750465": _record("LFA 17/18G Red Star Swift (2036)", "female")},
        report_rows=[_report_row("750465", "lfa-boys", "LFA 17/18G Red Star Swift (2036)")],
    )

    assert approved == {}
    assert review["750465"]["gender_check"] == "mismatch"
    assert review["750465"]["row_gender_readings"] == "Female/Male"


def test_the_registered_name_is_read_when_the_current_one_states_nothing(run_gate):
    """Only team_name_original says boys here, so the gate sees it only if the select asks for it."""
    approved, review = run_gate(
        teams=[_team("rush-boys", "Chicago Rush South Premier", "Female", "2019 Chicago Rush South Boys Premier")],
        answers={"799502": _record("U10 Chicago Rush South Premier Girls", "female")},
        report_rows=[_report_row("799502", "rush-boys", "U10 Chicago Rush South Premier Girls")],
    )

    assert approved == {}
    assert review["799502"]["gender_check"] == "mismatch"


def test_a_record_whose_gender_nothing_reads_is_held(run_gate):
    """GotSport did not answer and the name states no gender: held a week, not linked. The matcher
    filled unknown_gender_used from the opponent, as it does in production, and that is not a reading."""
    approved, review = run_gate(
        teams=[_team("blue-boys", "Lou Fusz 2018 Boys Blue", "Male")],
        answers={},
        report_rows=[_report_row("700001", "blue-boys", "unknown_700001", gender_used="Male")],
    )

    assert approved == {}
    assert review["700001"]["gender_check"] == "unknown"


def test_the_export_s_gender_lets_a_record_through_when_this_script_s_lookup_fails(run_gate):
    """In CI the gate's own lookups go unanswered; the export's, made earlier in the run, answer."""
    approved, review = run_gate(
        teams=[_team("blue-boys", "Lou Fusz 2018 Boys Blue", "Male")],
        answers={},
        report_rows=[_report_row("700001", "blue-boys", "Lou Fusz Blue", gender_used="Male", provider_gender="Male")],
    )

    assert review == {}
    assert approved["700001"]["gender_check"] == "ok"


def test_a_record_gotsport_files_as_coed_is_not_held(run_gate):
    """Coed is GotSport answering, not GotSport failing to."""
    approved, review = run_gate(
        teams=[_team("rangers", "FC Rangers 16/17", "Male")],
        answers={},
        report_rows=[_report_row("479970", "rangers", "FC Rangers 16/17", gender_used="Male", provider_gender="Coed")],
    )

    assert review == {}
    assert approved["479970"]["gender_check"] == "coed"


def test_a_coed_record_is_still_held_from_a_row_its_name_contradicts(run_gate):
    approved, review = run_gate(
        teams=[_team("rangers", "FC Rangers 16/17 Boys", "Male")],
        answers={},
        report_rows=[_report_row("479971", "rangers", "FC Rangers G16/17", gender_used="Male", provider_gender="Coed")],
    )

    assert approved == {}
    assert review["479971"]["gender_check"] == "mismatch"


def test_the_export_s_gender_holds_a_record_it_contradicts(run_gate):
    approved, review = run_gate(
        teams=[_team("blue-boys", "Lou Fusz 2018 Boys Blue", "Male")],
        answers={},
        report_rows=[_report_row("700002", "blue-boys", "Lou Fusz Blue", gender_used="Male", provider_gender="Female")],
    )

    assert approved == {}
    assert review["700002"]["gender_check"] == "mismatch"


def test_a_record_of_the_same_gender_is_still_approved(run_gate):
    approved, review = run_gate(
        teams=[_team("lfa-girls", "LFA 17/18G Red Star Swift (2036)", "Female")],
        answers={"750465": _record("LFA 17/18G Red Star Swift (2036)", "female")},
        report_rows=[_report_row("750465", "lfa-girls", "LFA 17/18G Red Star Swift (2036)")],
    )

    assert review == {}
    assert approved["750465"]["gender_check"] == "ok"
    assert approved["750465"]["record_gender_readings"] == "Female/Female/Female"
