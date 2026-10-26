"""Tests for excluding the doubled fixtures a merge leaves, scoped to one batch's merges, and for
undoing a run from its own log.

The double evaluates its filters at execute(), returns only the columns select() asked for, refuses
a range() that no order() precedes and an .in_() longer than the 100-id URI limit, and records an
update at execute(), applying it to the rows its filters match. As trg_propagate_game_exclusion does,
an update that newly excludes a game also excludes every other included game sharing its cascade key.
"""

import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import exclude_merge_duplicate_games as emdg  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import IN_BATCH_LIMIT, _Result  # noqa: E402

GONE, KEEP = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"
OTHER_GONE, OTHER_KEEP = "cccccccc-0000-4000-8000-000000000003", "dddddddd-0000-4000-8000-000000000004"
OPPONENT = "eeeeeeee-0000-4000-8000-000000000005"


def trigger_key(row):
    """What trg_propagate_game_exclusion matches on, read from its migration rather than borrowed from the
    code under test: the date, the unordered pair of raw team ids, and each team's own score."""
    home, away = row["home_team_master_id"], row["away_team_master_id"]
    if home is None or away is None:
        return None
    scores = (row["home_score"], row["away_score"]) if home < away else (row["away_score"], row["home_score"])
    return (row["game_date"], *sorted((home, away)), *scores)


class _Not:
    def __init__(self, query):
        self._query = query

    def is_(self, column, value):
        assert value == "null"
        self._query._filters.append(lambda row, c=column: row[c] is not None)
        return self._query


class _Query:
    def __init__(self, db, name):
        self._db, self._name = db, name
        self._columns, self._filters, self._order, self._range, self._update = None, [], None, None, None

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def update(self, values):
        self._update = values
        return self

    def eq(self, column, value):
        self._filters.append(lambda row, c=column, v=value: row[c] == v)
        return self

    def in_(self, column, values):
        values = list(values)
        if len(values) > IN_BATCH_LIMIT:
            raise AssertionError(f"{self._name}: .in_() with {len(values)} ids exceeds the URI limit")
        self._filters.append(lambda row, c=column, v=values: row[c] in v)
        return self

    @property
    def not_(self):
        return _Not(self)

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def range(self, start, end):
        if self._order is None:
            raise AssertionError(f"{self._name}: range() without order() pages a table unstably")
        self._range = (start, end)
        return self

    def execute(self):
        rows = [row for row in self._db.tables[self._name] if all(f(row) for f in self._filters)]
        if self._update is not None:
            fault = self._db.update_faults.get(self._db.update_calls)
            self._db.update_calls += 1
            if fault == "refused":
                raise RuntimeError("503 Service Unavailable")
            newly = [row for row in rows if self._update.get("is_excluded") is True and not row["is_excluded"]]
            for row in rows:
                row.update(self._update)
            self._db.writes.append((self._name, dict(self._update), sorted(row["id"] for row in rows)))
            self._db.propagate_exclusion(newly)
            if fault == "lost":
                raise RuntimeError("504 Gateway Timeout")
            return _Result([dict(row) for row in rows])
        if self._order:
            rows.sort(key=lambda row: row[self._order[0]], reverse=self._order[1])
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        return _Result([{c: row[c] for c in self._columns} for row in rows])


class _Db:
    """`update_faults` maps the n-th update sent, from 0, to "refused" (nothing written) or "lost" (written,
    its reply lost, as a gateway timeout loses one)."""

    def __init__(self, games, merge_map):
        self.tables = {"games": games, "team_merge_map": merge_map}
        self.writes, self.cascaded = [], []
        self.update_faults, self.update_calls = {}, 0

    def table(self, name):
        return _Query(self, name)

    def propagate_exclusion(self, rows):
        keys = {trigger_key(row) for row in rows} - {None}
        for other in self.tables["games"]:
            if not other["is_excluded"] and trigger_key(other) in keys:
                other["is_excluded"] = True
                self.cascaded.append(other["id"])


def game(game_id, home, away, score=(2, 1), *, excluded=False, date="2026-09-01"):
    return {
        "id": game_id,
        "game_date": date,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": score[0],
        "away_score": score[1],
        "event_name": None,
        "competition": None,
        "division_name": None,
        "venue": None,
        "source_url": None,
        "created_at": "2026-09-02T00:00:00+00:00",
        "game_uid": f"uid-{game_id}",
        "is_excluded": excluded,
    }


def two_merged_clusters():
    """Each merge left one fixture recorded twice, once under the retired row and once under the survivor."""
    games = [
        game("g1", GONE, OPPONENT),
        game("g2", KEEP, OPPONENT),
        game("g3", OTHER_GONE, OPPONENT, (3, 0)),
        game("g4", OTHER_KEEP, OPPONENT, (3, 0)),
    ]
    merge_map = [
        {"deprecated_team_id": GONE, "canonical_team_id": KEEP},
        {"deprecated_team_id": OTHER_GONE, "canonical_team_id": OTHER_KEEP},
    ]
    return _Db(games, merge_map)


def on_day(n):
    return f"2026-{n // 28 + 1:02d}-{n % 28 + 1:02d}"


def doubled_fixtures(count):
    """`count` fixtures on distinct days, each recorded under the retired row and again under the survivor."""
    games = []
    for n in range(count):
        games += [game(f"g{n:03d}", GONE, OPPONENT, date=on_day(n)), game(f"k{n:03d}", KEEP, OPPONENT, date=on_day(n))]
    return _Db(games, [{"deprecated_team_id": GONE, "canonical_team_id": KEEP}])


def hidden_outside_the_log(db, out):
    """Games the trigger excluded that the run's log does not name, which no revert of it could restore."""
    logged = {row["id"] for row in json.loads(out.read_text(encoding="utf-8"))["rows"]}
    return sorted(set(db.cascaded) - logged)


MERGED, PENDING = {"success": True}, {"pending": True}


def merge_log(tmp_path, *merges):
    path = tmp_path / "merge_results.json"
    entries = [{"merge_id": m, "keep_id": k, "merge_name": m, "keep_name": k, "result": r} for m, k, r in merges]
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def run(monkeypatch, db, *flags):
    monkeypatch.setattr(emdg, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["prog", *flags])
    return emdg.main()


def excluded(db):
    return sorted(g["id"] for g in db.tables["games"] if g["is_excluded"])


def test_without_a_merge_log_every_cluster_is_repaired(tmp_path, monkeypatch):
    db = two_merged_clusters()
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "excluded.json")) == 0
    assert excluded(db) == ["g1", "g3"]


def test_a_merge_log_repairs_only_the_clusters_of_the_merges_it_records(tmp_path, monkeypatch):
    db = two_merged_clusters()
    log = merge_log(tmp_path, (GONE, KEEP, MERGED))
    out = tmp_path / "excluded.json"
    assert run(monkeypatch, db, "--merge-log", str(log), "--execute", "--out", str(out)) == 0
    assert excluded(db) == ["g1"]
    assert [row["id"] for row in json.loads(out.read_text(encoding="utf-8"))["rows"]] == ["g1"]


def test_a_merge_log_repairs_the_cluster_of_a_merge_it_could_not_confirm(tmp_path, monkeypatch):
    db = two_merged_clusters()
    log = merge_log(tmp_path, (OTHER_GONE, OTHER_KEEP, PENDING))
    assert run(monkeypatch, db, "--merge-log", str(log), "--execute", "--out", str(tmp_path / "excluded.json")) == 0
    assert excluded(db) == ["g3"]


def test_a_merge_log_recording_no_merge_repairs_nothing(tmp_path, monkeypatch, capsys):
    db = two_merged_clusters()
    log = merge_log(tmp_path)
    assert run(monkeypatch, db, "--merge-log", str(log), "--execute", "--out", str(tmp_path / "excluded.json")) == 0
    assert db.writes == []
    assert "records no merge — nothing to do" in capsys.readouterr().out


LEFT_IN_PLACE = "left in place, the exclusion trigger would also hide another copy: {}"


def test_a_same_id_copy_of_the_kept_copy_is_never_excluded(tmp_path, monkeypatch, capsys):
    """Excluding it would make trg_propagate_game_exclusion exclude the kept copy too."""
    db = _Db(
        [game("g1", GONE, OPPONENT), game("g2", KEEP, OPPONENT), game("g2b", KEEP, OPPONENT)],
        [{"deprecated_team_id": GONE, "canonical_team_id": KEEP}],
    )
    out = tmp_path / "excluded.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    assert excluded(db) == ["g1"]
    assert hidden_outside_the_log(db, out) == []
    assert LEFT_IN_PLACE.format(1) in capsys.readouterr().out


def test_a_copy_whose_reversed_twin_the_trigger_would_hide_is_never_excluded(tmp_path, monkeypatch, capsys):
    """The trigger matches a copy stored the other way round, which no log of this run would name."""
    db = _Db(
        [game("g1", GONE, OPPONENT), game("g2", KEEP, OPPONENT), game("g3", OPPONENT, GONE, (1, 2))],
        [{"deprecated_team_id": GONE, "canonical_team_id": KEEP}],
    )
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "excluded.json")) == 0
    assert excluded(db) == []
    assert LEFT_IN_PLACE.format(1) in capsys.readouterr().out


def four_copies():
    """One fixture recorded twice under the retired row and twice under the survivor."""
    return _Db(
        [
            game("g1", GONE, OPPONENT),
            game("g1b", GONE, OPPONENT),
            game("g2", KEEP, OPPONENT),
            game("g2b", KEEP, OPPONENT),
        ],
        [{"deprecated_team_id": GONE, "canonical_team_id": KEEP}],
    )


def test_four_copies_lose_both_retired_row_copies_and_keep_both_survivor_copies(tmp_path, monkeypatch, capsys):
    db = four_copies()
    out = tmp_path / "excluded.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    assert excluded(db) == ["g1", "g1b"]
    assert hidden_outside_the_log(db, out) == []
    assert LEFT_IN_PLACE.format(1) in capsys.readouterr().out


def test_a_limit_never_splits_copies_the_trigger_would_exclude_together(tmp_path, monkeypatch):
    """The limit is taken before the trigger check, so a copy whose twin the limit cut off is left too."""
    db = four_copies()
    out = tmp_path / "excluded.json"
    assert run(monkeypatch, db, "--execute", "--limit", "2", "--out", str(out)) == 0
    assert excluded(db) == []
    assert hidden_outside_the_log(db, out) == []


def test_an_existing_log_is_never_overwritten(tmp_path, monkeypatch):
    db = two_merged_clusters()
    out = tmp_path / "excluded.json"
    out.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        run(monkeypatch, db, "--execute", "--out", str(out))
    assert db.writes == []
    assert out.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("case", ["no merge on record", "a merge log naming none", "no fixture recorded twice"])
def test_a_run_that_excludes_nothing_leaves_a_log_its_revert_reads(tmp_path, monkeypatch, case):
    db, flags = two_merged_clusters(), []
    if case == "no merge on record":
        db.tables["team_merge_map"] = []
    elif case == "a merge log naming none":
        flags = ["--merge-log", str(merge_log(tmp_path))]
    else:
        db.tables["games"] = [g for g in db.tables["games"] if g["home_team_master_id"] in (KEEP, OTHER_KEEP)]
    out = tmp_path / "excluded.json"
    assert run(monkeypatch, db, *flags, "--execute", "--out", str(out)) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"applied": True, "confirmed": 0, "sent": 0, "rows": []}
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert db.writes == []


def test_a_batch_whose_reply_is_lost_is_still_reverted(tmp_path, monkeypatch):
    db = doubled_fixtures(101)
    db.update_faults = {1: "lost"}
    out = tmp_path / "excluded.json"
    with pytest.raises(RuntimeError, match="504"):
        run(monkeypatch, db, "--execute", "--out", str(out))
    logged = json.loads(out.read_text(encoding="utf-8"))
    assert (logged["confirmed"], logged["sent"]) == (100, 101)
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert excluded(db) == []


def test_each_batch_is_counted_as_sent_before_it_is_sent(tmp_path, monkeypatch):
    """A run killed outright skips the closing write, so the count must already be on disk."""
    db = doubled_fixtures(101)
    writes = []
    real_write = emdg.write_log

    def recording_write(path, log):
        writes.append((log["applied"], log["sent"], db.update_calls))
        real_write(path, log)

    monkeypatch.setattr(emdg, "write_log", recording_write)
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "excluded.json")) == 0
    assert writes == [(False, 0, 0), (False, 100, 0), (False, 101, 1), (True, 101, 2)]


def test_a_revert_restores_a_copy_the_trigger_excluded_ahead_of_its_batch(tmp_path, monkeypatch):
    """Two retired-row copies of one fixture fall either side of a batch boundary: excluding the first makes
    the trigger exclude the second, whose own batch is never sent."""
    db = doubled_fixtures(99)
    db.tables["games"] += [
        game("x1", GONE, OPPONENT, date="2026-12-01"),
        game("x1b", GONE, OPPONENT, date="2026-12-01"),
        game("y1", KEEP, OPPONENT, date="2026-12-01"),
    ]
    db.update_faults = {0: "lost"}
    out = tmp_path / "excluded.json"
    with pytest.raises(RuntimeError, match="504"):
        run(monkeypatch, db, "--execute", "--out", str(out))
    logged = json.loads(out.read_text(encoding="utf-8"))
    assert ([row["id"] for row in logged["rows"][99:]], logged["sent"]) == (["x1b", "x1"], 100)
    assert db.cascaded == ["x1"]
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert excluded(db) == []


def test_a_merge_log_follows_a_survivor_merged_again_since(tmp_path, monkeypatch):
    db = _Db(
        [game("g1", GONE, OPPONENT), game("g2", OTHER_KEEP, OPPONENT)],
        [
            {"deprecated_team_id": GONE, "canonical_team_id": OTHER_KEEP},
            {"deprecated_team_id": KEEP, "canonical_team_id": OTHER_KEEP},
        ],
    )
    log = merge_log(tmp_path, (GONE, KEEP, MERGED))
    assert run(monkeypatch, db, "--merge-log", str(log), "--execute", "--out", str(tmp_path / "excluded.json")) == 0
    assert excluded(db) == ["g1"]


def excluded_games(count):
    return [game(f"g{n:03d}", GONE, OPPONENT, excluded=True, date=on_day(n)) for n in range(count)]


def exclude_log(tmp_path, games, **fields):
    """A log naming `games` in order, as a run that excluded them writes it."""
    rows = [
        {
            "id": g["id"],
            "game_date": g["game_date"],
            "kept_id": "k",
            "home_team_master_id": g["home_team_master_id"],
            "away_team_master_id": g["away_team_master_id"],
            "score": f"{g['home_score']}-{g['away_score']}",
        }
        for g in games
    ]
    path = tmp_path / "excluded.json"
    path.write_text(json.dumps({"applied": True, "rows": rows, **fields}), encoding="utf-8")
    return path


def test_revert_un_excludes_only_the_logged_games_still_excluded(tmp_path, monkeypatch, capsys):
    games = excluded_games(3)
    games[2]["is_excluded"] = False
    db = _Db(games, [])
    log = exclude_log(tmp_path, [games[0], games[2]], confirmed=2)
    assert run(monkeypatch, db, "--revert", str(log), "--execute") == 0
    assert db.writes == [("games", {"is_excluded": False}, ["g000"])]
    assert excluded(db) == ["g001"]
    assert "Restored 1 game rows." in capsys.readouterr().out


def test_revert_leaves_the_rows_a_stopped_run_never_wrote(tmp_path, monkeypatch):
    db = _Db(excluded_games(2), [])
    log = exclude_log(tmp_path, db.tables["games"], confirmed=1)
    assert run(monkeypatch, db, "--revert", str(log), "--execute") == 0
    assert excluded(db) == ["g001"]


def test_revert_refuses_a_log_that_never_recorded_what_it_sent(tmp_path, monkeypatch):
    db = _Db(excluded_games(1), [])
    log = exclude_log(tmp_path, db.tables["games"], applied=False)
    with pytest.raises(SystemExit, match="records no count of rows sent"):
        run(monkeypatch, db, "--revert", str(log), "--execute")
    assert db.writes == []


def test_a_revert_stopped_part_way_is_not_stamped(tmp_path, monkeypatch):
    db = _Db(excluded_games(101), [])
    db.update_faults = {1: "refused"}
    log = exclude_log(tmp_path, db.tables["games"], confirmed=101)
    with pytest.raises(RuntimeError, match="503"):
        run(monkeypatch, db, "--revert", str(log), "--execute")
    assert "reverted_at" not in json.loads(log.read_text(encoding="utf-8"))
    assert run(monkeypatch, db, "--revert", str(log), "--execute") == 0
    assert excluded(db) == []


def test_a_reverted_log_is_not_replayed(tmp_path, monkeypatch, capsys):
    db = _Db(excluded_games(1), [])
    log = exclude_log(tmp_path, db.tables["games"], confirmed=1)
    assert run(monkeypatch, db, "--revert", str(log), "--execute") == 0
    db.tables["games"][0]["is_excluded"] = True
    capsys.readouterr()
    assert run(monkeypatch, db, "--revert", str(log), "--execute") == 0
    assert excluded(db) == ["g000"]
    assert "was reverted at" in capsys.readouterr().out


def test_revert_restores_a_log_longer_than_one_request(tmp_path, monkeypatch, capsys):
    db = _Db(excluded_games(101), [])
    log = exclude_log(tmp_path, db.tables["games"], confirmed=101)
    assert run(monkeypatch, db, "--revert", str(log), "--execute") == 0
    assert excluded(db) == []
    assert "Restored 101 game rows." in capsys.readouterr().out


def test_revert_refuses_a_file_that_is_not_its_log(tmp_path, monkeypatch):
    log = tmp_path / "excluded.json"
    log.write_text(json.dumps([{"merge_id": GONE}]), encoding="utf-8")
    with pytest.raises(SystemExit, match="holds no exclude_merge_duplicate_games.py log"):
        run(monkeypatch, _Db([], []), "--revert", str(log), "--execute")


def test_a_dry_run_revert_writes_nothing(tmp_path, monkeypatch, capsys):
    games = excluded_games(2)
    games[1]["is_excluded"] = False
    db = _Db(games, [])
    log = exclude_log(tmp_path, games, confirmed=2)
    assert run(monkeypatch, db, "--revert", str(log)) == 0
    assert db.writes == []
    assert "excluded: 2, of which still excluded: 1" in capsys.readouterr().out
    assert "reverted_at" not in json.loads(log.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "flags",
    [
        ["--merge-log", "x.json", "--scope", "all"],
        ["--revert", "x.json", "--merge-log", "y.json"],
        ["--revert", "x.json", "--limit", "5"],
        ["--revert", "x.json", "--out", "y.json"],
    ],
)
def test_conflicting_flags_are_refused(monkeypatch, flags):
    with pytest.raises(SystemExit):
        run(monkeypatch, _Db([], []), *flags)
