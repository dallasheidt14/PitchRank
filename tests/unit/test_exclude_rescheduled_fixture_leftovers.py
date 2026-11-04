"""The cleanup must hide only the fixture a rescheduled game left on its original date."""

import json
import sys
from datetime import date

import pytest

import scripts.exclude_rescheduled_fixture_leftovers as cleanup
from scripts.exclude_rescheduled_fixture_leftovers import select_leftovers
from tests.unit.test_exclude_unscored_fixture_twins import _DB as _TwinDB
from tests.unit.test_exclude_unscored_fixture_twins import _Query as _TwinQuery

HOME = "b5000000-0000-0000-0000-000000000000"
AWAY = "5b000000-0000-0000-0000-000000000000"
THIRD = "c1000000-0000-0000-0000-000000000000"
FIXTURE_DATE = "2026-09-20"
PLAYED_DATE = "2026-09-13"
SCHEDULED_AT = "2026-08-10T22:02:59.681194+00:00"
RESCHEDULED_AT = "2026-09-11T08:09:25.669007+00:00"
SINCE = "2026-08-01"


def _game(
    gid,
    home=HOME,
    away=AWAY,
    home_score=None,
    away_score=None,
    excluded=False,
    game_date=FIXTURE_DATE,
    provider="prov-gotsport",
    created_at=SCHEDULED_AT,
):
    return {
        "id": gid,
        "provider_id": provider,
        "game_date": game_date,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": excluded,
        "created_at": created_at,
    }


def _played(gid="res", game_date=PLAYED_DATE, created_at=RESCHEDULED_AT, **kw):
    kw.setdefault("home_score", 5)
    kw.setdefault("away_score", 3)
    return _game(gid, game_date=game_date, created_at=created_at, **kw)


def _selected(fixtures, scored, blanks=(), merge_map=None):
    blanks = [*fixtures, *blanks]
    return [(f["id"], r["id"]) for f, r in select_leftovers(fixtures, scored, blanks, merge_map or {})]


def test_a_fixture_is_selected_beside_its_result_on_another_date_whichever_side_is_home():
    assert _selected([_game("fx")], [_played(home=AWAY, away=HOME)]) == [("fx", "res")]


def test_a_result_saved_before_the_fixture_is_another_leg_not_the_moved_game():
    assert _selected([_game("fx")], [_played(created_at="2026-08-01T00:00:00+00:00")]) == []


def test_a_result_saved_with_the_fixture_is_another_leg_not_the_moved_game():
    assert _selected([_game("fx")], [_played(created_at=SCHEDULED_AT)]) == []


def test_a_result_saved_within_a_day_of_the_fixture_came_from_the_same_schedule():
    almost = _played("res-23h", created_at="2026-08-11T21:02:59.681194+00:00")
    a_day = _played("res-24h", created_at="2026-08-11T22:02:59.681194+00:00")

    assert _selected([_game("fx")], [almost]) == []
    assert _selected([_game("fx")], [a_day]) == [("fx", "res-24h")]


def test_a_result_on_the_fixtures_own_date_is_left_to_the_twin_cleanup():
    assert _selected([_game("fx")], [_played(game_date=FIXTURE_DATE)]) == []


def test_a_result_22_days_away_does_not_count():
    results = [_played(game_date="2026-10-12"), _played("res-early", game_date="2026-08-29")]

    assert _selected([_game("fx")], results) == []


def test_a_result_for_another_pair_does_not_count():
    assert _selected([_game("fx")], [_played(away=THIRD)]) == []


def test_one_result_explains_only_the_nearest_of_two_fixtures():
    near = _game("fx-near", game_date="2026-09-20")
    far = _game("fx-far", game_date="2026-10-04")

    assert _selected([far, near], [_played(game_date="2026-09-25")]) == [("fx-near", "res")]


def test_two_fixtures_each_take_their_own_result():
    fixtures = [_game("fx-1", game_date="2026-09-20"), _game("fx-2", game_date="2026-10-04")]
    results = [_played("res-1", game_date="2026-09-19"), _played("res-2", game_date="2026-10-03")]

    assert sorted(_selected(fixtures, results)) == [("fx-1", "res-1"), ("fx-2", "res-2")]


def test_a_fixture_with_two_results_is_selected_once():
    results = [_played("res-1", game_date="2026-09-19"), _played("res-2", game_date="2026-09-22")]

    assert _selected([_game("fx")], results) == [("fx", "res-1")]


def test_a_match_stored_twice_explains_only_one_fixture():
    fixtures = [_game("fx-near", game_date="2026-09-20"), _game("fx-far", game_date="2026-09-27")]
    copies = [_played("res-copy-1"), _played("res-copy-2")]

    assert _selected(fixtures, copies) == [("fx-near", "res-copy-1")]


def test_a_result_on_a_date_the_pair_was_already_scheduled_is_the_other_leg():
    # Leg one's result was saved beside its own fixture, after leg two's fixture was listed
    leg_two = _game("fx-leg2", game_date="2026-10-04")
    leg_one_result = _played("res-leg1", game_date=FIXTURE_DATE, created_at="2026-09-21T10:00:00+00:00")
    leg_one_fixture = _game("fx-leg1", game_date=FIXTURE_DATE, excluded=True)

    assert _selected([leg_two], [leg_one_result], blanks=[leg_one_fixture]) == []


def test_a_blank_listed_on_the_new_date_after_the_fixture_does_not_rule_out_a_move():
    moved_fixture = _game("fx-new-date", game_date=PLAYED_DATE, created_at="2026-09-01T10:00:00+00:00")

    assert _selected([_game("fx")], [_played()], blanks=[moved_fixture]) == [("fx", "res")]


class _Query(_TwinQuery):
    def lte(self, field, value):
        self._predicates.append(lambda r: r.get(field) <= value)
        return self

    def in_(self, field, values):
        assert len(values) <= 100, "PostgREST rejects a URI this long"
        return super().in_(field, values)


class _DB(_TwinDB):
    def __init__(self, games):
        super().__init__(games)
        self.rows["providers"].append({"id": "prov-tgs", "code": "tgs"})

    def table(self, name):
        return _Query(self, name)


def _run_main(monkeypatch, db, argv):
    monkeypatch.setattr(cleanup, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["exclude_rescheduled_fixture_leftovers.py", *argv])
    return cleanup.main()


def _excluded(db):
    return sorted(g["id"] for g in db.rows["games"] if g["is_excluded"])


def _execute(monkeypatch, tmp_path, db, *argv):
    since = [] if "--since" in argv else ["--since", SINCE]
    return _run_main(monkeypatch, db, [*since, *argv, "--execute", "--out", str(tmp_path / "log.json")])


def test_default_run_is_a_dry_run(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _played()])
    log = tmp_path / "log.json"

    assert _run_main(monkeypatch, db, ["--out", str(log)]) == 0

    assert [call for call in db.executed if call[1] == "update"] == []
    assert _excluded(db) == []
    assert not log.exists()


def test_execute_hides_only_the_leftover_and_logs_it(monkeypatch, tmp_path):
    db = _DB(
        [
            _game("fx"),
            _played(),
            _game("fx-unexplained", away=THIRD),
            _game("fx-unlinked", away=None, game_date="2026-09-15"),
            _played("res-unlinked", away=None, game_date="2026-09-16"),
        ]
    )
    log = tmp_path / "log.json"

    assert _run_main(monkeypatch, db, ["--since", SINCE, "--execute", "--out", str(log)]) == 0

    assert _excluded(db) == ["fx"]
    assert json.loads(log.read_text(encoding="utf-8")) == {"applied": True, "game_ids": ["fx"], "games_excluded": 1}


def test_the_rollback_log_is_written_before_the_first_update(monkeypatch, tmp_path):
    log = tmp_path / "log.json"
    seen = []

    class _Watching(_Query):
        def execute(self):
            if self._op == "update":
                seen.append(json.loads(log.read_text(encoding="utf-8")))
            return super().execute()

    db = _DB([_game("fx"), _played()])
    monkeypatch.setattr(db, "table", lambda name: _Watching(db, name))

    assert _run_main(monkeypatch, db, ["--since", SINCE, "--execute", "--out", str(log)]) == 0

    assert seen == [{"applied": False, "game_ids": ["fx"]}]


@pytest.mark.parametrize(
    ("played_on", "expected"),
    [("2026-10-11", ["fx"]), ("2026-08-30", ["fx"]), ("2026-10-12", []), ("2026-08-29", [])],
)
def test_a_result_up_to_21_days_either_side_is_fetched_and_counts(monkeypatch, tmp_path, played_on, expected):
    db = _DB([_game("fx"), _played(game_date=played_on)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == expected


def test_a_result_played_at_the_other_club_is_fetched(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _played(home=AWAY, away=HOME)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx"]


def test_a_fixture_from_the_last_week_is_left_alone(monkeypatch, tmp_path):
    class _Nov3(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 3)

    monkeypatch.setattr(cleanup, "date", _Nov3)
    db = _DB(
        [
            _game("fx-7-days", game_date="2026-10-27"),
            _played("res-7-days", game_date="2026-10-24"),
            _game("fx-8-days", away=THIRD, game_date="2026-10-26"),
            _played("res-8-days", away=THIRD, game_date="2026-10-23"),
        ]
    )

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx-8-days"]


def test_a_fixture_from_another_provider_is_left_alone(monkeypatch, tmp_path):
    db = _DB([_game("fx", provider="prov-tgs"), _played()])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == []


def test_a_result_from_another_provider_is_not_evidence(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _played(provider="prov-tgs")])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == []


def test_an_already_excluded_result_does_not_count(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _played(excluded=True)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["res"]


def test_a_later_saved_blank_is_not_a_result(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _game("fx-later", game_date="2026-10-04", created_at=RESCHEDULED_AT)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == []


@pytest.mark.parametrize("score", [{"home_score": 5}, {"away_score": 3}])
def test_a_half_scored_row_is_neither_result_nor_fixture(monkeypatch, tmp_path, score):
    half = _game("half", game_date=PLAYED_DATE, created_at=RESCHEDULED_AT, **score)
    db = _DB([_game("fx"), half])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == []


@pytest.mark.parametrize("score", [{"home_score": 2, "away_score": 1}, {"home_score": 2}, {"away_score": 1}])
def test_a_scored_row_does_not_compete_as_a_fixture(monkeypatch, tmp_path, score):
    # Saved with the schedule, so it is no result for fx either; as a fixture it would take res
    leg_one = _game("leg1", game_date="2026-09-11", **score)
    db = _DB([_game("fx"), leg_one, _played()])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx"]


def test_a_fixture_hidden_by_an_earlier_run_keeps_its_result(monkeypatch, tmp_path):
    db = _DB([_game("fx-hidden", game_date="2026-09-14", excluded=True), _game("fx"), _played()])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx-hidden"]


def test_a_hidden_fixture_keeps_its_result_from_a_nearer_one_that_became_eligible(monkeypatch, tmp_path):
    # The earlier run hid fx-hidden; fx-newer was then too recent to compete, and is nearer
    db = _DB([_game("fx-hidden", game_date="2026-09-05", excluded=True), _game("fx-newer"), _played()])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx-hidden"]


def test_an_already_hidden_fixture_is_not_logged_again(monkeypatch, tmp_path):
    db = _DB(
        [
            _game("fx-hidden", away=THIRD, excluded=True),
            _played("res-third", away=THIRD),
            _game("fx"),
            _played(),
        ]
    )
    log = tmp_path / "log.json"

    assert _run_main(monkeypatch, db, ["--since", SINCE, "--execute", "--out", str(log)]) == 0

    assert json.loads(log.read_text(encoding="utf-8"))["game_ids"] == ["fx"]


def test_a_result_scheduled_on_its_own_date_before_the_since_window_is_still_seen(monkeypatch, tmp_path):
    db = _DB(
        [
            _game("fx", game_date="2026-08-05"),
            _game("fx-own-date", game_date="2026-07-25", excluded=True),
            _played(game_date="2026-07-25", created_at="2026-08-20T00:00:00+00:00"),
        ]
    )

    assert _execute(monkeypatch, tmp_path, db, "--since", "2026-08-01") == 0

    assert _excluded(db) == ["fx-own-date"]


def test_execute_needs_since(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _played()])
    log = tmp_path / "log.json"

    with pytest.raises(SystemExit, match="--since"):
        _run_main(monkeypatch, db, ["--execute", "--out", str(log)])

    assert db.executed == []
    assert not log.exists()


def test_execute_refuses_to_overwrite_a_rollback_log(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _played()])
    log = tmp_path / "log.json"
    log.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db, ["--since", SINCE, "--execute", "--out", str(log)])

    assert _excluded(db) == []
    assert log.read_text(encoding="utf-8") == "{}"


def test_since_limits_the_sweep_to_its_own_date_and_later(monkeypatch, tmp_path):
    db = _DB(
        [
            _game("fx-before", away=THIRD, game_date="2026-09-19"),
            _played("res-before", away=THIRD, game_date="2026-09-12"),
            _game("fx"),
            _played(),
        ]
    )

    assert _execute(monkeypatch, tmp_path, db, "--since", "2026-09-20") == 0

    assert _excluded(db) == ["fx"]


def test_every_fixture_is_found_when_the_teams_span_several_batches(monkeypatch, tmp_path):
    games = []
    for n in range(101):
        home, away = f"h{n:03d}", f"a{n:03d}"
        games += [_game(f"fx{n:03d}", home=home, away=away), _played(f"res{n:03d}", home=home, away=away)]
    db = _DB(games)

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == [f"fx{n:03d}" for n in range(101)]


@pytest.mark.parametrize("score", [{"home_score": 0}, {"away_score": 3}])
def test_a_fixture_scored_after_selection_is_not_excluded(monkeypatch, tmp_path, score):
    db = _DB([_game("fx"), _played()])
    select = cleanup.select_leftovers

    def select_then_score(*args):
        chosen = select(*args)
        db.rows["games"][0].update(score)
        return chosen

    monkeypatch.setattr(cleanup, "select_leftovers", select_then_score)

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == []


# A merge leaves games saved under the merged-away team's id

OLD_HOME = "0d000000-0000-0000-0000-000000000000"
OLD_AWAY = "0a000000-0000-0000-0000-000000000000"


def _merged_db(games):
    db = _DB(games)
    db.rows["team_merge_map"] = [{"deprecated_team_id": OLD_HOME, "canonical_team_id": HOME}]
    return db


def test_a_fixture_under_a_merged_away_team_is_hidden_beside_its_result_under_the_survivor(
    monkeypatch, tmp_path, capsys
):
    # The result's home side is the survivor, so it is read only once the survivor's id is looked up
    db = _merged_db([_game("fx", home=OLD_HOME), _played(home=HOME, away=AWAY)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx"]
    assert "saved under a team since merged away: 1" in capsys.readouterr().out


def test_a_fixture_under_the_survivor_is_hidden_beside_its_result_under_a_merged_away_team(
    monkeypatch, tmp_path, capsys
):
    # The result's home side is the merged-away team, so it is read only once the survivor's
    # merged-away ids are looked up
    db = _merged_db([_game("fx"), _played(home=OLD_HOME, away=AWAY)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx"]
    assert "saved under a team since merged away: 0" in capsys.readouterr().out


def test_a_fixture_with_both_teams_merged_away_counts_once(monkeypatch, tmp_path, capsys):
    db = _merged_db([_game("fx", home=OLD_HOME, away=OLD_AWAY), _played(home=HOME, away=AWAY)])
    db.rows["team_merge_map"].append({"deprecated_team_id": OLD_AWAY, "canonical_team_id": AWAY})

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == ["fx"]
    assert "saved under a team since merged away: 1" in capsys.readouterr().out


def test_a_fixture_under_a_merged_away_team_without_a_result_is_left_alone(monkeypatch, tmp_path):
    db = _merged_db([_game("fx", home=OLD_HOME), _played(home=HOME, away=THIRD)])

    assert _execute(monkeypatch, tmp_path, db) == 0

    assert _excluded(db) == []


def test_a_fixture_whose_exclusion_would_cascade_to_another_providers_blank_is_refused(monkeypatch, tmp_path):
    # The trigger matches date, saved pair and scores whatever the provider
    db = _DB([_game("fx"), _game("fx-tgs", provider="prov-tgs"), _played()])

    assert _execute(monkeypatch, tmp_path, db) == 1

    assert _excluded(db) == []
