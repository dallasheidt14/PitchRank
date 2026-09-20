"""The weekly age-group re-check derives its population fresh and writes nothing.

Two claims are load-bearing and neither is visible in the run's own output. The
population is rebuilt from the reconcile logs on every run rather than kept by hand, so
each exclusion is tested on a row violating that exclusion alone. And the whole pass is
read-only: it reports what *would* qualify, and applying is a separate approved step.
A double that recorded nothing at ``execute()`` could not tell the two apart.
"""

import csv

import pytest

from scripts import fix_band_cohorts as fbc
from scripts import weekly_age_recheck as war

RECONCILE_ROW = {
    "run_mode": "execute",
    "team_id_master": "22222222-2222-4222-8222-222222222222",
    "stored_age_group": "u14",
    "gotsport_age_group": "u13",
    "gotsport_team_name": "Queen City 2013/2014 B",
}


def _reconcile_row(**overrides):
    return {**RECONCILE_ROW, **overrides}


def _live(row, **overrides):
    team = {
        "team_id_master": row["team_id_master"],
        "team_name": "Queen City 2013/14 Boys",
        "club_name": "Queen City FC",
        "gender": "Male",
        "state_code": "NC",
        "age_group": row["stored_age_group"],
        "is_deprecated": False,
    }
    team.update(overrides)
    return team


class _Db:
    """Records every executed call, so a write is visible even when it changes nothing."""

    def __init__(self):
        self.executed = []

    def table(self, name):
        self.executed.append(("table", name))
        raise AssertionError(f"the weekly re-check queried {name!r}; it is meant to be read-only here")

    @property
    def writes(self):
        return [call for call in self.executed if call[0] in ("update", "insert")]


@pytest.fixture
def exports(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    exports_dir = root / "data" / "exports"
    exports_dir.mkdir(parents=True)
    monkeypatch.setattr(war, "ROOT", root)
    monkeypatch.setattr(war, "EXPORTS", exports_dir)
    return exports_dir


def _write_reconcile(exports_dir, rows, name="reconcile_teams_with_gotsport_20260915.csv"):
    path = exports_dir / name
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _population(monkeypatch, exports_dir, reconcile_rows, live_rows):
    _write_reconcile(exports_dir, reconcile_rows)
    monkeypatch.setattr(fbc, "fetch_live", lambda sb, ids: {t["team_id_master"]: t for t in live_rows})
    return war.pending_population(_Db())


def test_a_team_gotsport_files_younger_is_pending(exports, monkeypatch):
    row = _reconcile_row()

    pending = _population(monkeypatch, exports, [row], [_live(row)])

    assert [p["team_id_master"] for p in pending] == [row["team_id_master"]]
    assert pending[0]["old_age_group"] == "u14"
    assert pending[0]["new_age_group"] == "u13"


def test_a_team_gotsport_files_older_is_not_pending(exports, monkeypatch):
    """Violates the younger-than-stored rule alone.

    The live row sits a group *above* the reconcile row, so the later
    still-disagrees rule would admit this team. Only the audit filter excludes it,
    which is what makes this fixture a test of that filter rather than of both.
    """
    row = _reconcile_row(stored_age_group="u13", gotsport_age_group="u14")

    assert _population(monkeypatch, exports, [row], [_live(row, age_group="u15")]) == []


def test_a_deprecated_team_is_not_pending(exports, monkeypatch):
    """Violates the deprecation rule alone; GotSport still files it younger."""
    row = _reconcile_row()

    assert _population(monkeypatch, exports, [row], [_live(row, is_deprecated=True)]) == []


def test_a_team_already_moved_to_the_target_is_not_pending(exports, monkeypatch):
    """The correction already landed, so nothing is left to decide.

    The rule reads ``current == target or age_num(target) >= age_num(current)``, and
    the first disjunct cannot be isolated: equal cohorts satisfy the second as well.
    It survives as a short-circuit that keeps a malformed cohort away from age_num,
    so no fixture kills it on its own.
    """
    row = _reconcile_row()

    assert _population(monkeypatch, exports, [row], [_live(row, age_group="u13")]) == []


def test_a_team_the_live_table_no_longer_holds_is_not_pending(exports, monkeypatch):
    row = _reconcile_row()

    assert _population(monkeypatch, exports, [row], []) == []


def test_only_execute_mode_reconcile_rows_are_read(exports, monkeypatch):
    """A dry-run audit row describes a run that wrote nothing, so it names no candidate."""
    row = _reconcile_row(run_mode="dry-run")

    assert _population(monkeypatch, exports, [row], [_live(row)]) == []


def test_the_latest_reconcile_row_per_team_wins(exports, monkeypatch):
    """Later logs supersede earlier ones, so a team corrected since stops qualifying."""
    row = _reconcile_row()
    _write_reconcile(exports, [row], "reconcile_teams_with_gotsport_20260901.csv")
    later = _reconcile_row(stored_age_group="u13", gotsport_age_group="u14")
    _write_reconcile(exports, [later], "reconcile_teams_with_gotsport_20260916.csv")
    monkeypatch.setattr(fbc, "fetch_live", lambda sb, ids: {row["team_id_master"]: _live(row)})

    assert war.pending_population(_Db()) == []


def test_the_run_writes_no_database_rows(exports, monkeypatch, capsys):
    """The whole pass is read-only; applying is a separate, approved step."""
    row = _reconcile_row()
    _write_reconcile(exports, [row])
    db = _Db()

    monkeypatch.setattr(fbc, "load_env", lambda: None)
    monkeypatch.setattr(fbc, "get_supabase", lambda: db)
    monkeypatch.setattr(fbc, "fetch_live", lambda sb, ids: {row["team_id_master"]: _live(row)})
    monkeypatch.setattr(fbc, "fetch_all_live_teams", lambda sb: [])

    def _evidence(sb, rows):
        for r in rows:
            r["fixture_verdict"] = "backs_move"
            r["opp_games_proposed"] = 6
            r["opp_games_current"] = 0

    monkeypatch.setattr(fbc, "attach_fixture_evidence", _evidence)

    war.main()

    assert db.writes == []
    assert db.executed == []
    assert "Nothing was written to the database" in capsys.readouterr().out


def test_a_team_without_enough_opponent_games_does_not_qualify(exports, monkeypatch):
    """``MIN_GAMES`` is its own conjunct: the verdict can back the move and still be thin."""
    row = _reconcile_row()
    _write_reconcile(exports, [row])
    db = _Db()

    monkeypatch.setattr(fbc, "load_env", lambda: None)
    monkeypatch.setattr(fbc, "get_supabase", lambda: db)
    monkeypatch.setattr(fbc, "fetch_live", lambda sb, ids: {row["team_id_master"]: _live(row)})
    monkeypatch.setattr(fbc, "fetch_all_live_teams", lambda sb: [])

    def _thin(sb, rows):
        for r in rows:
            r["fixture_verdict"] = "backs_move"
            r["opp_games_proposed"] = war.MIN_GAMES - 1
            r["opp_games_current"] = 0

    monkeypatch.setattr(fbc, "attach_fixture_evidence", _thin)

    war.main()

    plans = sorted(exports.glob("weekly_age_recheck_plan_*.csv"))
    assert plans, "no plan written"
    with plans[-1].open(encoding="utf-8-sig", newline="") as f:
        assert list(csv.DictReader(f)) == []
