"""Fixture evidence counts a survivor's absorbed games, and the CSVs it writes are inert.

Both guards here answer a way the tool could move a team onto a wrong age board while
looking right. A merge leaves the absorbed row's games under the deprecated id, and
reading only the survivor's id does not merely undercount: if the games it drops are the
ones backing the current cohort, the ratio tips and a mixed schedule reads as backing the
move. And the plan CSV exists to be opened in a spreadsheet, so a provider-written name
beginning with a formula character is executable there whatever the quoting.

The double models ``.in_()`` because the defect is about *which* ids the query asks for.
One that returned the absorbed row's games regardless of the id filter would pass whether
or not the code resolved the merge.
"""

import csv

import pytest

from scripts import fix_band_cohorts as fbc

SURVIVOR = "aaaaaaaa-0000-4000-8000-000000000001"
ABSORBED = "bbbbbbbb-0000-4000-8000-000000000002"

# Verified against band_of: a band is named by its younger year.
U13_OPPONENT = "Riverside 2013/2014 Boys"
U14_OPPONENT = "Riverside 2012/2013 Boys"


class _Query:
    def __init__(self, db, table, columns):
        self._db, self._table, self._columns = db, table, columns
        self._in = []
        self._gte = []

    def in_(self, column, values):
        self._in.append((column, list(values)))
        return self

    def gte(self, column, value):
        self._gte.append((column, value))
        return self

    def _keep(self, row):
        return all(row.get(c) in vals for c, vals in self._in) and all(
            str(row.get(c) or "") >= v for c, v in self._gte
        )

    def execute(self):
        rows = [r for r in self._db.rows.get(self._table, []) if self._keep(r)]
        self._db.executed.append((self._table, list(self._in)))
        return _Result([{c: r.get(c) for c in self._columns} for r in rows])


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, db, name):
        self._db, self._name = db, name

    def select(self, columns):
        return _Query(self._db, self._name, [c.strip() for c in columns.split(",")])


class _EvidenceDb:
    def __init__(self, games, teams, merges):
        self.rows = {"games": games, "teams": teams, "team_merge_map": merges}
        self.executed = []

    def table(self, name):
        return _Table(self, name)


def _game(home, away):
    return {
        "home_team_master_id": home,
        "away_team_master_id": away,
        "game_date": "2026-09-01",
    }


def _opponents(*specs):
    teams, games = [], []
    for i, (owner, name) in enumerate(specs):
        opp_id = f"cccccccc-0000-4000-8000-{i:012d}"
        teams.append({"team_id_master": opp_id, "team_name": name})
        games.append(_game(owner, opp_id))
    return teams, games


def _row():
    return {
        "team_id_master": SURVIVOR,
        "team_name": "Queen City 2013/14 Boys",
        "old_age_group": "u14",
        "new_age_group": "u13",
    }


def _run(games, teams, merges):
    row = _row()
    fbc.attach_fixture_evidence(_EvidenceDb(games, teams, merges), [row])
    return row


def test_a_mixed_schedule_on_one_id_reads_as_mixed():
    teams, games = _opponents(
        *[(SURVIVOR, U13_OPPONENT)] * 3,
        *[(SURVIVOR, U14_OPPONENT)] * 3,
    )

    row = _run(games, teams, [])

    assert (row["opp_games_proposed"], row["opp_games_current"]) == (3, 3)
    assert row["fixture_verdict"] == "mixed"


def test_absorbed_games_backing_the_current_cohort_still_count():
    """The flip this guard exists for.

    The same true schedule, with the current-cohort games left under the deprecated id.
    Counting only the survivor's id sees 3 proposed against 0 current and calls it
    ``backs_move`` — a move onto a cohort the fixtures do not actually support.
    """
    teams, games = _opponents(
        *[(SURVIVOR, U13_OPPONENT)] * 3,
        *[(ABSORBED, U14_OPPONENT)] * 3,
    )
    merges = [{"deprecated_team_id": ABSORBED, "canonical_team_id": SURVIVOR}]

    row = _run(games, teams, merges)

    assert (row["opp_games_proposed"], row["opp_games_current"]) == (3, 3)
    assert row["fixture_verdict"] == "mixed"


def test_absorbed_games_backing_the_move_count_toward_it():
    teams, games = _opponents(
        (SURVIVOR, U13_OPPONENT),
        *[(ABSORBED, U13_OPPONENT)] * 3,
    )
    merges = [{"deprecated_team_id": ABSORBED, "canonical_team_id": SURVIVOR}]

    row = _run(games, teams, merges)

    assert (row["opp_games_proposed"], row["opp_games_current"]) == (4, 0)
    assert row["fixture_verdict"] == "backs_move"


def test_another_teams_deprecated_row_is_not_counted():
    """Only ids the merge map points at this survivor are gathered under it."""
    teams, games = _opponents(
        (SURVIVOR, U13_OPPONENT),
        *[(ABSORBED, U13_OPPONENT)] * 4,
    )

    row = _run(games, teams, [])

    assert (row["opp_games_proposed"], row["opp_games_current"]) == (1, 0)
    assert row["fixture_verdict"] == "thin"


def test_the_merge_map_is_queried_for_the_candidates():
    teams, games = _opponents((SURVIVOR, U13_OPPONENT))
    db = _EvidenceDb(games, teams, [])

    fbc.attach_fixture_evidence(db, [_row()])

    assert ("team_merge_map", [("canonical_team_id", [SURVIVOR])]) in db.executed


@pytest.mark.parametrize(
    "raw",
    ["=cmd|' /c calc'!A1", "+1+1", "-2+3", "@SUM(A1)", "\tlead", "\rlead", "\nlead", "'=already"],
)
def test_a_formula_leading_name_is_escaped_on_disk_and_restored_on_read(raw, tmp_path):
    plan = tmp_path / "plan.csv"
    fbc.write_csv([{**_row(), "team_name": raw, "action": "would_update"}], plan, fbc.PLAN_FIELDS)

    with plan.open(encoding="utf-8-sig", newline="") as f:
        on_disk = list(csv.DictReader(f))[0]["team_name"]
    assert on_disk.startswith("'"), on_disk
    assert fbc.read_our_csv(plan)[0]["team_name"] == raw


def test_an_ordinary_name_is_written_unchanged(tmp_path):
    plan = tmp_path / "plan.csv"
    fbc.write_csv([{**_row(), "action": "would_update"}], plan, fbc.PLAN_FIELDS)

    with plan.open(encoding="utf-8-sig", newline="") as f:
        assert list(csv.DictReader(f))[0]["team_name"] == "Queen City 2013/14 Boys"


def test_writing_the_same_rows_twice_does_not_escape_them_twice(tmp_path):
    """The apply log is rewritten as the run progresses, from the same row objects."""
    plan = tmp_path / "plan.csv"
    rows = [{**_row(), "team_name": "=x", "action": "would_update"}]
    fbc.write_csv(rows, plan, fbc.PLAN_FIELDS)
    fbc.write_csv(rows, plan, fbc.PLAN_FIELDS)

    assert fbc.read_our_csv(plan)[0]["team_name"] == "=x"


def test_a_reconcile_log_is_read_without_unescaping(tmp_path):
    """Another script writes those, never escaped, so a leading quote there belongs."""
    log = tmp_path / "reconcile_teams_with_gotsport_20260901.csv"
    with log.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["team_id_master", "team_name"])
        w.writeheader()
        w.writerow({"team_id_master": SURVIVOR, "team_name": "''=kept"})

    assert fbc.read_csv(log)[0]["team_name"] == "''=kept"
