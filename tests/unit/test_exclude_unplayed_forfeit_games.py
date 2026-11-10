"""The cleanup must hide only GotSport results that were never played, and the copies they left.

The double extends the merge-duplicate cleanup's: it evaluates filters at execute(), returns only the
columns select() asked for, refuses a range() that no order() precedes, an .in_() longer than the
100-id URI limit and any builder method it does not model, truncates an unpaged read at a max-rows
cap, and excludes every included game sharing a newly excluded game's trg_propagate_game_exclusion
key, as the trigger does. The clock is frozen, because the default sweep and the ranking window the
report counts against are read from today's date.
"""

import json
import sys
from datetime import UTC, date, datetime, timedelta

import pytest

import scripts.exclude_merge_duplicate_games as merge_duplicates
import scripts.exclude_unplayed_forfeit_games as cleanup
import scripts.exclude_unscored_fixture_twins as twins
import scripts.reconcile_tgs_scores as reconcile
from tests.unit.test_exclude_merge_duplicate_games import _Db as _MergeDb
from tests.unit.test_exclude_merge_duplicate_games import _Query as _MergeQuery
from tests.unit.test_find_cross_provider_duplicates import _Result

TODAY = date(2026, 11, 9)
DAY, LATER, FUTURE = "2026-08-01", "2026-09-10", "2027-01-08"
LAST_SEASON = "2026-04-11"
N1, OTHER_COMP = "National 1 League", "Fall League"
GOTSPORT, TGS = "prov-gotsport", "prov-tgs"
QUITTER, OLD_QUITTER = "a0000000-0000-4000-8000-000000000000", "0a000000-0000-4000-8000-000000000000"
OTHER_QUITTER = "a1000000-0000-4000-8000-000000000000"
EXCLUDED_TEAM = "e0000000-0000-4000-8000-000000000000"
OPPONENTS = [f"b{n:02d}00000-0000-4000-8000-000000000000" for n in range(12)]
MAX_ROWS = 1000


class _Frozen(date):
    @classmethod
    def today(cls):
        return cls(TODAY.year, TODAY.month, TODAY.day)


def _at(day: str, days: float = 0) -> str:
    return (datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(days=days)).isoformat()


def game(gid, home, away, score=(3, 0), *, day=DAY, comp=N1, saved=None, provider=GOTSPORT, excluded=False):
    return {
        "id": gid,
        "game_uid": f"uid-{gid}",
        "provider_id": provider,
        "game_date": day,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_provider_id": "1",
        "away_provider_id": "2",
        "home_score": score[0],
        "away_score": score[1],
        "competition": comp,
        "scraped_at": saved or _at(day, 20),
        "is_excluded": excluded,
        "source_url": None,
    }


def slate(n=5, team=QUITTER, prefix="s", first=0, **kw):
    """`team` loses n league games 0-3 on one day to n opponents, home and away mixed."""
    rows = []
    for i in range(n):
        opponent = OPPONENTS[first + i]
        if i % 2:
            rows.append(game(f"{prefix}{i}", team, opponent, (0, 3), **kw))
        else:
            rows.append(game(f"{prefix}{i}", opponent, team, (3, 0), **kw))
    return rows


def correction(gid, approved_at, *, status="approved", kind="score"):
    return {"id": f"c-{gid}-{approved_at}", "original_game_uid": f"uid-{gid}", "approved_at": approved_at,
            "correction_type": kind, "status": status}


class _Query(_MergeQuery):
    def __init__(self, db, name):
        super().__init__(db, name)
        self._limit = None

    def gte(self, column, value):
        self._filters.append(lambda row, c=column, v=value: row[c] >= v)
        return self

    def lte(self, column, value):
        self._filters.append(lambda row, c=column, v=value: row[c] <= v)
        return self

    def is_(self, column, value):
        assert value == "null"
        self._filters.append(lambda row, c=column: row[c] is None)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def __getattr__(self, name):
        raise AssertionError(f"unmodeled builder method {name!r}")

    def execute(self):
        if self._update is not None and self._db.silent_updates:
            # A key with the UPDATE grant but no UPDATE policy: an empty 200, nothing written
            self._db.update_calls += 1
            return _Result([])
        result = super().execute()
        if self._update is not None:
            return result
        return _Result(result.data[: self._limit if self._limit is not None else MAX_ROWS])


class _Db(_MergeDb):
    def __init__(self, games, merge_map=(), corrections=(), ranking_exclusions=()):
        super().__init__(list(games), [{"deprecated_team_id": d, "canonical_team_id": c} for d, c in merge_map])
        self.tables.update(
            providers=[{"id": GOTSPORT, "code": "gotsport"}, {"id": TGS, "code": "tgs"}],
            game_corrections=list(corrections),
            team_ranking_exclusions=[{"team_id_master": t} for t in ranking_exclusions],
        )
        self.silent_updates = False

    def table(self, name):
        return _Query(self, name)


@pytest.fixture(autouse=True)
def _frozen_clock_and_log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "date", _Frozen)
    monkeypatch.setattr(cleanup, "LOG_DIR", tmp_path / "backups")


def run(monkeypatch, db, *flags):
    monkeypatch.setattr(cleanup, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["exclude_unplayed_forfeit_games.py", *flags])
    return cleanup.main()


def execute(monkeypatch, tmp_path, db, *flags):
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, *flags, "--execute", "--out", str(out)) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def assert_nothing_hidden(monkeypatch, tmp_path, db, *flags):
    assert run(monkeypatch, db, *flags, "--execute", "--out", str(tmp_path / "log.json")) == 0
    assert hidden(db) == []


def hidden(db):
    return sorted(g["id"] for g in db.tables["games"] if g["is_excluded"])


def labels(log):
    return {row["id"]: row["labels"] for row in log["rows"]}


SLATE = ["s0", "s1", "s2", "s3", "s4"]


# Whole slate: a team that lost 3-0 to WHOLE_SLATE_MIN or more opponents on one date


def test_a_team_losing_five_league_games_3_0_on_one_date_has_all_five_hidden(monkeypatch, tmp_path):
    db = _Db(slate(5))
    log = execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE
    assert set(map(tuple, labels(log).values())) == {("whole_slate",)}


def test_four_such_losses_are_kept(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db(slate(4)))


def test_three_losses_each_stored_twice_under_a_merge_are_kept(monkeypatch, tmp_path):
    """Six rows, but only three matches: the merge left each loss under both team ids."""
    rows = []
    for n in range(3):
        rows += [game(f"a{n}", OPPONENTS[n], QUITTER), game(f"b{n}", OPPONENTS[n], OLD_QUITTER)]
    assert_nothing_hidden(monkeypatch, tmp_path, _Db(rows, [(OLD_QUITTER, QUITTER)]))


def test_a_real_result_the_same_day_in_the_same_competition_keeps_the_slate(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db([*slate(5), game("real", QUITTER, OPPONENTS[6], (2, 1))]))


def test_a_real_away_loss_the_same_day_keeps_the_slate(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db([*slate(5), game("real", OPPONENTS[6], QUITTER, (2, 1))]))


def test_a_real_result_against_an_unlinked_opponent_keeps_the_slate(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db([*slate(5), game("real", QUITTER, None, (2, 1))]))


def test_a_real_result_that_day_saved_under_a_merged_away_id_keeps_the_slate(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("real", OLD_QUITTER, OPPONENTS[6], (2, 1))], [(OLD_QUITTER, QUITTER)])
    assert_nothing_hidden(monkeypatch, tmp_path, db)


def test_a_3_0_win_the_same_day_keeps_the_slate(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db([*slate(5), game("win", QUITTER, OPPONENTS[6], (3, 0))]))


def test_a_real_result_that_day_in_another_competition_does_not_save_the_slate(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("real", QUITTER, OPPONENTS[6], (2, 1), comp=OTHER_COMP)])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_another_providers_result_that_day_does_not_save_the_slate(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("tgs-real", QUITTER, OPPONENTS[6], (2, 1), provider=TGS)])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_losses_split_across_two_competitions_are_kept(monkeypatch, tmp_path):
    rows = slate(5)
    rows[3]["competition"] = rows[4]["competition"] = OTHER_COMP
    assert_nothing_hidden(monkeypatch, tmp_path, _Db(rows))


def test_five_3_0_wins_on_one_date_are_kept(monkeypatch, tmp_path):
    rows = slate(5)
    for row in rows:
        row["home_score"], row["away_score"] = row["away_score"], row["home_score"]
    assert_nothing_hidden(monkeypatch, tmp_path, _Db(rows))


def test_losses_saved_under_a_merged_away_id_count_toward_the_slate(monkeypatch, tmp_path):
    rows = slate(5)
    rows[0]["away_team_master_id"] = rows[1]["home_team_master_id"] = OLD_QUITTER
    db = _Db(rows, [(OLD_QUITTER, QUITTER)])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_another_providers_slate_is_kept(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db(slate(5, provider=TGS)))


def test_each_slate_date_is_judged_on_its_own_results(monkeypatch, tmp_path):
    later = [*slate(5, prefix="t", first=5, day=LATER), game("real", OPPONENTS[11], QUITTER, (2, 1), day=LATER)]
    db = _Db([*slate(5), *later])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_two_teams_with_slates_on_one_day_are_both_hidden(monkeypatch, tmp_path):
    db = _Db([*slate(5), *slate(5, team=OTHER_QUITTER, prefix="o", first=5)])
    execute(monkeypatch, tmp_path, db)
    assert len(hidden(db)) == 10


# Early: a 3-0 whose current score was saved more than a day before the game's own date


def test_a_3_0_saved_two_days_before_its_date_is_hidden(monkeypatch, tmp_path):
    db = _Db([game("early", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -2))])
    log = execute(monkeypatch, tmp_path, db)
    assert hidden(db) == ["early"]
    assert labels(log) == {"early": ["early"]}


@pytest.mark.parametrize(("days_before", "expected"), [(0.5, []), (0.75, []), (1.25, ["early"])])
def test_the_early_margin_is_one_day(monkeypatch, tmp_path, days_before, expected):
    db = _Db([game("early", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -days_before))])
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 0
    assert hidden(db) == expected


@pytest.mark.parametrize("score", [(1, 0), (0, 0)])
def test_a_score_other_than_3_0_saved_early_is_kept(monkeypatch, tmp_path, score):
    db = _Db([game("odd", QUITTER, OPPONENTS[0], score, day=LATER, saved=_at(LATER, -5))])
    assert_nothing_hidden(monkeypatch, tmp_path, db)


def test_another_providers_early_3_0_is_kept(monkeypatch, tmp_path):
    db = _Db([game("tgs", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -5), provider=TGS)])
    assert_nothing_hidden(monkeypatch, tmp_path, db)


def test_a_future_dated_result_saved_months_ahead_is_hidden(monkeypatch, tmp_path):
    db = _Db([game("ahead", QUITTER, OPPONENTS[0], (3, 0), day=FUTURE, saved=_at(LATER))])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == ["ahead"]


def test_a_row_with_no_save_time_is_not_early(monkeypatch, tmp_path):
    row = game("unknown", QUITTER, OPPONENTS[0], (0, 3), day=LATER)
    row["scraped_at"] = None
    assert_nothing_hidden(monkeypatch, tmp_path, _Db([row]))


@pytest.mark.parametrize(
    ("fix", "expected"),
    [
        (correction("early", _at(LATER, 2)), []),
        (correction("early", _at(LATER, -3)), ["early"]),
        (correction("early", _at(LATER, 2), status="rejected"), ["early"]),
        (correction("early", _at(LATER, 2), kind="teams"), ["early"]),
    ],
)
def test_only_an_approved_score_correction_after_the_date_clears_early(monkeypatch, tmp_path, fix, expected):
    """A correction changes the score without touching scraped_at, so the save time alone would mislead."""
    db = _Db([game("early", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -20))], corrections=[fix])
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 0
    assert hidden(db) == expected


# Copies of the same pairing on other dates


def test_a_3_0_copy_with_the_same_loser_and_host_on_another_date_is_hidden(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("copy", OPPONENTS[0], QUITTER, (3, 0), day=LATER)])
    log = execute(monkeypatch, tmp_path, db)
    assert labels(log)["copy"] == ["copy"]


def test_a_same_loser_3_0_with_the_home_team_swapped_is_kept_as_a_possible_return_leg(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("return-leg", QUITTER, OPPONENTS[0], (0, 3), day=LATER)])
    execute(monkeypatch, tmp_path, db)
    assert "return-leg" not in hidden(db)


def test_a_3_0_on_another_date_with_the_other_loser_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("rematch", OPPONENTS[0], QUITTER, (0, 3), day=LATER)])
    execute(monkeypatch, tmp_path, db)
    assert "rematch" not in hidden(db)


def test_a_copy_in_another_competition_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("cup", OPPONENTS[0], QUITTER, (3, 0), day=LATER, comp=OTHER_COMP)])
    execute(monkeypatch, tmp_path, db)
    assert "cup" not in hidden(db)


def test_a_same_loser_and_host_3_0_last_season_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("last-season", OPPONENTS[0], QUITTER, (3, 0), day=LAST_SEASON)])
    execute(monkeypatch, tmp_path, db)
    assert "last-season" not in hidden(db)


def test_another_providers_copy_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("tgs-copy", OPPONENTS[0], QUITTER, (3, 0), day=LATER, provider=TGS)])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_a_copy_dated_before_since_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5, day=LATER), game("early-copy", OPPONENTS[0], QUITTER, (3, 0), day=DAY)])
    execute(monkeypatch, tmp_path, db, "--since", "2026-08-15")
    assert hidden(db) == SLATE


def test_a_blank_fixture_of_a_whole_slate_team_is_hidden(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("blank", QUITTER, OPPONENTS[0], (None, None), day=FUTURE)])
    log = execute(monkeypatch, tmp_path, db)
    assert labels(log)["blank"] == ["copy"]


def test_a_blank_fixture_of_a_whole_slate_team_last_season_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("old-blank", QUITTER, OPPONENTS[0], (None, None), day=LAST_SEASON)])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_a_blank_fixture_beside_an_early_result_alone_is_kept(monkeypatch, tmp_path):
    db = _Db([
        game("early", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -2)),
        game("second-leg", OPPONENTS[0], QUITTER, (None, None), day=FUTURE),
    ])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == ["early"]


def test_a_blank_fixture_of_a_whole_slate_team_in_another_competition_is_kept(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("cup", QUITTER, OPPONENTS[0], (None, None), day=FUTURE, comp=OTHER_COMP)])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_a_blank_on_the_results_own_date_is_left_to_the_twin_cleanup(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("twin", QUITTER, OPPONENTS[0], (None, None))])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == SLATE


def test_a_blank_in_a_competition_the_team_did_not_leave_is_kept_beside_an_early_result(monkeypatch, tmp_path):
    db = _Db([
        *slate(5),
        game("cup-early", QUITTER, OPPONENTS[0], (0, 3), day=LATER, comp=OTHER_COMP, saved=_at(LATER, -2)),
        game("cup-leg", OPPONENTS[0], QUITTER, (None, None), day=FUTURE, comp=OTHER_COMP),
    ])
    execute(monkeypatch, tmp_path, db)
    assert "cup-early" in hidden(db)
    assert "cup-leg" not in hidden(db)


def test_copies_saved_under_merged_away_ids_are_hidden(monkeypatch, tmp_path):
    db = _Db(
        [*slate(5), game("copy", OPPONENTS[0], OLD_QUITTER, (3, 0), day=LATER),
         game("blank", OLD_QUITTER, OPPONENTS[1], (None, None), day=FUTURE)],
        [(OLD_QUITTER, QUITTER)],
    )
    execute(monkeypatch, tmp_path, db)
    assert {"copy", "blank"} <= set(hidden(db))


def test_two_early_results_for_one_pairing_keep_their_own_label(monkeypatch, tmp_path):
    db = _Db([
        game("early-1", QUITTER, OPPONENTS[0], (0, 3), day=DAY, saved=_at(DAY, -2)),
        game("early-2", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -2)),
    ])
    log = execute(monkeypatch, tmp_path, db)
    assert labels(log) == {"early-1": ["early"], "early-2": ["early"]}


# The exclusion trigger


@pytest.mark.parametrize(
    "neighbour",
    [
        game("tgs-copy", QUITTER, OPPONENTS[1], (0, 3), provider=TGS),
        game("tgs-blank", QUITTER, OPPONENTS[0], (None, None), day=FUTURE, provider=TGS),
    ],
)
def test_a_row_the_trigger_would_also_hide_is_refused(monkeypatch, tmp_path, capsys, neighbour):
    db = _Db([*slate(5), game("blank", QUITTER, OPPONENTS[0], (None, None), day=FUTURE), dict(neighbour)])
    assert run(monkeypatch, db) == 0
    assert "cascade collisions: 1" in capsys.readouterr().out
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 1
    assert "would also exclude the collisions above" in capsys.readouterr().out
    assert hidden(db) == [] and not (tmp_path / "log.json").exists()


# Writing, logging and undoing


def test_a_dry_run_writes_nothing_and_leaves_no_file(monkeypatch, tmp_path, capsys):
    db = _Db(slate(5))
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--out", str(out)) == 0
    assert db.writes == []
    assert not out.exists() and not cleanup.LOG_DIR.exists()
    assert "DRY RUN — nothing written." in capsys.readouterr().out


def test_without_out_the_log_goes_to_the_backups_folder(monkeypatch):
    assert run(monkeypatch, _Db(slate(5)), "--execute") == 0
    [log] = cleanup.LOG_DIR.glob("exclude_unplayed_forfeit_games_*.json")
    assert len(json.loads(log.read_text(encoding="utf-8"))["rows"]) == 5


def test_out_creates_only_its_own_folder(monkeypatch, tmp_path):
    out = tmp_path / "elsewhere" / "log.json"
    assert run(monkeypatch, _Db(slate(5)), "--execute", "--out", str(out)) == 0
    assert out.exists() and not cleanup.LOG_DIR.exists()


def test_the_log_names_every_row_before_the_first_update(monkeypatch, tmp_path):
    out = tmp_path / "log.json"
    seen = []
    db = _Db(slate(5))

    class _Watching(_Query):
        def execute(self):
            if self._update is not None:
                seen.append(len(json.loads(out.read_text(encoding="utf-8"))["rows"]))
            return super().execute()

    monkeypatch.setattr(db, "table", lambda name: _Watching(db, name))
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    assert seen and set(seen) == {5}


def test_each_batch_is_recorded_before_it_is_sent(monkeypatch, tmp_path):
    """A run killed outright skips the closing write, so the batch in flight must already be on disk."""
    db = _Db(slate(5))
    writes = []
    real_write = cleanup.write_log

    def recording_write(path, log):
        writes.append((log["applied"], log["sent"], len(log["inflight"]), len(log["changed"]), db.update_calls))
        real_write(path, log)

    monkeypatch.setattr(cleanup, "write_log", recording_write)
    execute(monkeypatch, tmp_path, db)
    assert writes == [(False, 0, 0, 0, 0), (False, 3, 3, 0, 0), (False, 5, 2, 3, 1), (True, 5, 0, 5, 2)]


def test_an_existing_log_is_never_overwritten(monkeypatch, tmp_path):
    db = _Db(slate(5))
    out = tmp_path / "log.json"
    out.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        run(monkeypatch, db, "--execute", "--out", str(out))
    assert db.writes == []
    assert out.read_text(encoding="utf-8") == "{}"


def test_a_change_between_the_dry_run_reading_and_the_write_refuses_the_run(monkeypatch, tmp_path, capsys):
    db = _Db(slate(5))
    select = cleanup.select_unplayed
    calls = []

    def select_then_rescore(*args):
        chosen = select(*args)
        if not calls:
            db.tables["games"][0].update(home_score=2, away_score=1)
        calls.append(1)
        return chosen

    monkeypatch.setattr(cleanup, "select_unplayed", select_then_rescore)
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 1
    assert hidden(db) == [] and db.writes == []
    assert "the games changed while the run was reading them" in capsys.readouterr().out


def change_before_first_update(monkeypatch, db, gid, change):
    real = cleanup.guarded_update
    calls = []

    def changing_update(sb, ids, shape):
        if not calls:
            next(g for g in db.tables["games"] if g["id"] == gid).update(change)
        calls.append(1)
        return real(sb, ids, shape)

    monkeypatch.setattr(cleanup, "guarded_update", changing_update)


@pytest.mark.parametrize("change", [{"home_score": 2}, {"away_score": 1}, {"home_score": None}])
def test_a_row_whose_score_changed_just_before_its_update_is_not_hidden(monkeypatch, tmp_path, capsys, change):
    db = _Db(slate(5))
    change_before_first_update(monkeypatch, db, "s0", change)
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 1
    assert hidden(db) == ["s1", "s2", "s3", "s4"]
    out = capsys.readouterr().out
    assert "4 of 5 logged rows now read back hidden" in out
    assert "WARNING: 1 logged rows are not hidden" in out


@pytest.mark.parametrize("change", [{"home_score": 2}, {"away_score": 2}])
def test_a_blank_scored_just_before_its_update_is_not_hidden(monkeypatch, tmp_path, change):
    db = _Db([*slate(5), game("blank", QUITTER, OPPONENTS[0], (None, None), day=FUTURE)])
    change_before_first_update(monkeypatch, db, "blank", change)
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 1
    assert "blank" not in hidden(db)


def test_an_already_hidden_row_is_not_logged_again(monkeypatch, tmp_path):
    rows = slate(6)
    rows[5]["is_excluded"] = True
    log = execute(monkeypatch, tmp_path, _Db(rows))
    assert sorted(labels(log)) == SLATE


def test_a_run_longer_than_one_request_is_batched(monkeypatch, tmp_path):
    rows = [game(f"e{n:03d}", QUITTER, f"c{n:03d}", (0, 3), day=LATER, saved=_at(LATER, -3)) for n in range(101)]
    db = _Db(rows)
    log = execute(monkeypatch, tmp_path, db)
    assert len(hidden(db)) == 101 and len(log["changed"]) == 101 and log["sent"] == 101


def test_every_reader_follows_its_pages(monkeypatch, tmp_path):
    """Small pages push the forfeit, team-game, neighbour and merge-map reads past their first page."""
    for module in (twins, reconcile, merge_duplicates):
        monkeypatch.setattr(module, "PAGE", 2)
    db = _Db(
        [*slate(5), game("real", OPPONENTS[6], QUITTER, (2, 1)),
         *slate(5, team=OTHER_QUITTER, prefix="o", first=5),
         game("blank", OTHER_QUITTER, OPPONENTS[5], (None, None), day=FUTURE)],
        [(f"gone-{n}", f"kept-{n}") for n in range(5)],
    )
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == ["blank", "o0", "o1", "o2", "o3", "o4"]


def test_games_older_than_the_ranking_window_are_left_alone(monkeypatch, tmp_path):
    assert_nothing_hidden(monkeypatch, tmp_path, _Db(slate(5, day="2025-10-01")))


@pytest.mark.parametrize(("days_ago", "expected"), [(365, SLATE), (366, [])])
def test_the_default_sweep_is_the_ranking_window(monkeypatch, tmp_path, days_ago, expected):
    db = _Db(slate(5, day=(TODAY - timedelta(days=days_ago)).isoformat()))
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 0
    assert hidden(db) == expected


def test_since_widens_the_sweep(monkeypatch, tmp_path):
    db = _Db(slate(5, day="2025-10-01"))
    execute(monkeypatch, tmp_path, db, "--since", "2025-09-01")
    assert len(hidden(db)) == 5


def test_each_date_window_reads_only_its_own_dates(monkeypatch, tmp_path):
    early = game("early", QUITTER, OPPONENTS[0], (0, 3), day=LATER, saved=_at(LATER, -2))
    db = _Db([*slate(5, day="2025-10-01"), early])
    execute(monkeypatch, tmp_path, db)
    assert hidden(db) == ["early"]


def test_slates_on_both_sides_of_a_window_boundary_and_in_a_last_one_day_window_are_found(monkeypatch, tmp_path):
    since = "2026-08-10"
    db = _Db([*slate(5, day="2026-08-16"), *slate(5, team=OTHER_QUITTER, prefix="o", first=5, day="2026-08-17")])
    execute(monkeypatch, tmp_path, db, "--since", since)
    assert len(hidden(db)) == 10


def test_the_report_counts_what_the_ranking_loader_reads(monkeypatch, capsys):
    floor = cleanup.GlickoConfig.MIN_GAMES_PROVISIONAL
    rows = slate(5)
    rows[1]["home_team_master_id"] = rows[2]["away_team_master_id"] = OLD_QUITTER
    played = [
        game(f"p{n}", OLD_QUITTER if n < 4 else QUITTER, OPPONENTS[7], (2, 1), comp=OTHER_COMP,
             day=(TODAY - timedelta(days=10 + n)).isoformat())
        for n in range(floor - 1)
    ]
    uncounted = [
        *[game(f"old{n}", QUITTER, OPPONENTS[8], (2, 1), comp=OTHER_COMP, day="2025-10-01") for n in range(10)],
        *[game(f"fut{n}", QUITTER, OPPONENTS[8], (2, 1), comp=OTHER_COMP, day=f"2027-02-{n + 1:02d}")
          for n in range(10)],
        *[game(f"nil{n}", QUITTER, OPPONENTS[8], (None, None), comp=OTHER_COMP, day=f"2026-10-{n + 1:02d}")
          for n in range(10)],
        *[game(f"exc{n}", QUITTER, EXCLUDED_TEAM, (2, 1), comp=OTHER_COMP, day=f"2026-09-{n + 1:02d}")
          for n in range(3)],
    ]
    blank = game("blank", QUITTER, OPPONENTS[0], (None, None), day=FUTURE)
    db = _Db([*rows, *played, *uncounted, blank], [(OLD_QUITTER, QUITTER)], ranking_exclusions=[EXCLUDED_TEAM])
    assert run(monkeypatch, db) == 0
    out = capsys.readouterr().out
    for line in [
        "   whole_slate: 5\n", "   early: 0\n", "   copy: 1\n", "rows to hide: 6\n",
        "   counted by rankings now: 5\n", "   future-dated: 1\n", "   unscored fixtures: 1\n",
        "   saved under a team since merged away: 2\n", "   2026-08: 5\n", "   2027-01: 1\n",
        "teams losing a counted game: 6 (5 games)\n",
        f"   falling below {floor} games in the ranking window: 1\n",
        f"      {QUITTER}  {floor + 4} -> {floor - 1}\n",
        "   left with no games in the ranking window: 5\n",
    ]:
        assert line in out, line


def test_rows_the_ranking_loader_never_reads_are_not_counted_as_removed(monkeypatch, capsys):
    """One case per bound: a slate before the window, a result after today, an unscored fixture inside it, and a
    result against a team the ranking leaves out."""
    db = _Db([
        *slate(5, day="2025-10-01"),
        game("ahead", QUITTER, OPPONENTS[9], (0, 3), day=FUTURE, saved=_at(LATER)),
        game("blank", QUITTER, OPPONENTS[0], (None, None), day="2026-02-01"),
        game("excluded", QUITTER, EXCLUDED_TEAM, (0, 3), day=LATER, saved=_at(LATER, -2)),
    ], ranking_exclusions=[EXCLUDED_TEAM])
    assert run(monkeypatch, db, "--since", "2025-09-01") == 0
    out = capsys.readouterr().out
    assert "rows to hide: 8\n" in out
    assert "   counted by rankings now: 0\n" in out


def test_show_group_lists_every_row_in_that_group(monkeypatch, capsys):
    rows = [game(f"e{n}", QUITTER, OPPONENTS[n], (0, 3), day=LATER, saved=_at(LATER, -2)) for n in range(8)]
    db = _Db(rows)
    assert run(monkeypatch, db) == 0
    assert capsys.readouterr().out.count("\n   early       ") == 5
    assert run(monkeypatch, db, "--show-group", "early") == 0
    assert capsys.readouterr().out.count("\n   early       ") == 8


def test_revert_restores_every_row_the_run_hid_and_stamps_the_log(monkeypatch, tmp_path):
    db = _Db([*slate(5), game("blank", QUITTER, OPPONENTS[0], (None, None), day=FUTURE)])
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    assert len(hidden(db)) == 6
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert hidden(db) == []
    assert json.loads(out.read_text(encoding="utf-8"))["reverted_at"]


def test_a_revert_restores_the_lost_batch_and_the_copy_the_trigger_hid_ahead_of_its_own_batch(monkeypatch, tmp_path):
    """s0 is also stored the other way round; the first batch hides it, its reply is lost, the run stops."""
    db = _Db([*slate(5), game("s0-flip", QUITTER, OPPONENTS[0], (0, 3))])
    db.update_faults = {0: "lost"}
    out = tmp_path / "log.json"
    with pytest.raises(RuntimeError, match="504"):
        run(monkeypatch, db, "--execute", "--out", str(out))
    logged = json.loads(out.read_text(encoding="utf-8"))
    assert (logged["changed"], logged["inflight"]) == ([], ["s0", "s2", "s4"]) and "s0-flip" in db.cascaded
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert hidden(db) == []


def test_a_revert_leaves_a_row_another_writer_hid_first(monkeypatch, tmp_path):
    db = _Db(slate(5))
    change_before_first_update(monkeypatch, db, "s2", {"is_excluded": True})
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    assert "s2" not in json.loads(out.read_text(encoding="utf-8"))["changed"]
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert hidden(db) == ["s2"]


def test_revert_counts_only_the_rows_still_hidden(monkeypatch, tmp_path, capsys):
    db = _Db(slate(5))
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    db.tables["games"][0]["is_excluded"] = False
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert "Restored 4 game rows." in capsys.readouterr().out


def test_a_revert_that_restores_nothing_it_found_is_not_stamped(monkeypatch, tmp_path, capsys):
    db = _Db(slate(5))
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    db.silent_updates = True
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 1
    assert "reverted_at" not in json.loads(out.read_text(encoding="utf-8"))
    assert "is not stamped" in capsys.readouterr().out
    db.silent_updates = False
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert hidden(db) == []


def test_a_run_whose_updates_write_nothing_fails(monkeypatch, tmp_path):
    db = _Db(slate(5))
    db.silent_updates = True
    assert run(monkeypatch, db, "--execute", "--out", str(tmp_path / "log.json")) == 1
    assert hidden(db) == []


def test_a_reverted_log_is_not_replayed(monkeypatch, tmp_path, capsys):
    db = _Db(slate(5))
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    db.tables["games"][0]["is_excluded"] = True
    assert run(monkeypatch, db, "--revert", str(out), "--execute") == 0
    assert hidden(db) == ["s0"]
    assert "was reverted at" in capsys.readouterr().out


def test_a_dry_run_revert_writes_nothing(monkeypatch, tmp_path):
    db = _Db(slate(5))
    out = tmp_path / "log.json"
    assert run(monkeypatch, db, "--execute", "--out", str(out)) == 0
    writes = len(db.writes)
    assert run(monkeypatch, db, "--revert", str(out)) == 0
    assert len(db.writes) == writes
    assert "reverted_at" not in json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("log", "message"),
    [
        ({"applied": True, "sent": 1, "changed": [], "inflight": [], "rows": []},
         "holds no exclude_unplayed_forfeit_games.py log"),
        ({"stem": "exclude_unplayed_forfeit_games", "applied": True, "sent": 1, "rows": []}, "records no rows changed"),
    ],
)
def test_revert_refuses_a_log_it_cannot_trust(monkeypatch, tmp_path, log, message):
    path = tmp_path / "other.json"
    path.write_text(json.dumps(log), encoding="utf-8")
    with pytest.raises(SystemExit, match=message):
        run(monkeypatch, _Db([]), "--revert", str(path), "--execute")


@pytest.mark.parametrize("flags", [["--since", "2026-01-01"], ["--out", "x.json"], ["--show-group", "copy"]])
def test_revert_takes_only_execute(monkeypatch, flags):
    with pytest.raises(SystemExit):
        run(monkeypatch, _Db([]), "--revert", "x.json", *flags)
