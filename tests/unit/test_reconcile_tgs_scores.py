"""The reconcile job must correct a stored TGS score only once TGS has repeated the change.

TGS edits scores after posting them and has shown a correct result replaced by an unrelated one, so a
change is applied only when the previous run saw the same live score, and one that moves both sides of
the score (other than the stored pair swapped) is held for an operator.
"""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import scripts.reconcile_tgs_scores as rec
from scripts.exclude_none_opponent_games import cascade_key
from tests.unit.test_enhanced_pipeline_changed_score import _ApplyCorrection, _CorrectionsTable

TGS = "prov-tgs"
EVENT = "4300"
SOURCE = f"https://public.totalglobalsports.com/public/event/{EVENT}"
DATE = "2026-10-04"
HOME_MASTER = "b5000000-0000-0000-0000-000000000000"
AWAY_MASTER = "5b000000-0000-0000-0000-000000000000"


def _stored(
    gid,
    home_score=2,
    away_score=0,
    home_pid="111",
    away_pid="222",
    game_date=DATE,
    excluded=False,
    uid=None,
    source=SOURCE,
    provider=TGS,
):
    return {
        "id": gid,
        "game_uid": uid or f"tgs:{game_date}:{gid}",
        "provider_id": provider,
        "game_date": game_date,
        "home_team_master_id": HOME_MASTER,
        "away_team_master_id": AWAY_MASTER,
        "home_provider_id": home_pid,
        "away_provider_id": away_pid,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": excluded,
        "source_url": source,
    }


def _live(*games):
    """{(date, home pid, away pid): [(home, away), ...]} from (home pid, away pid, home, away) tuples."""
    out = {}
    for home_pid, away_pid, home, away in games:
        out.setdefault((DATE, home_pid, away_pid), []).append((home, away))
    return out


class _Not:
    def __init__(self, query):
        self._query = query

    def is_(self, field, value):
        assert value == "null", value
        self._query._predicates.append(lambda r: r.get(field) is not None)
        return self._query


class _Query:
    """games/providers double: records writes at execute(), projects columns, refuses what production refuses."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._columns = None
        self._payload = None
        self._predicates = []
        self._ordered = False
        self._window = None

    @property
    def not_(self):
        return _Not(self)

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, field, value):
        self._predicates.append(lambda r: r.get(field) == value)
        return self

    def gte(self, field, value):
        self._predicates.append(lambda r: r.get(field) >= value)
        return self

    def in_(self, field, values):
        assert len(values) <= 100, "URI length"
        self._predicates.append(lambda r: r.get(field) in values)
        return self

    def is_(self, field, value):
        assert value == "null", value
        self._predicates.append(lambda r: r.get(field) is None)
        return self

    def order(self, field, desc=False):
        assert field == "id"
        self._ordered = True
        return self

    def range(self, start, end):
        assert self._ordered, "range() without order() can skip or repeat rows"
        self._window = (start, end)
        return self

    def __getattr__(self, name):
        raise AssertionError(f"unmodeled builder method {name!r}")

    def execute(self):
        source = {"games": self._db.games, "providers": [{"id": TGS, "code": "tgs"}]}[self._table]
        rows = [r for r in source if all(p(r) for p in self._predicates)]
        if self._op == "update":
            assert self._table == "games"
            assert set(self._payload) == {"is_excluded"}, "a hide writes only is_excluded"
            self._db.writes.append(("hide", sorted(r["id"] for r in rows), self._payload))
            for row in rows:
                row.update(self._payload)
                # trg_propagate_game_exclusion: the same date, master pair and aligned scores, any provider
                for other in self._db.games:
                    if (
                        cascade_key(row) is not None
                        and not other["is_excluded"]
                        and cascade_key(other) == cascade_key(row)
                    ):
                        other["is_excluded"] = True
                        self._db.cascaded.append(other["id"])
            return SimpleNamespace(data=[dict(r) for r in rows])
        rows = sorted(rows, key=lambda r: r["id"])
        if self._window:
            rows = rows[self._window[0] : self._window[1] + 1]
        return SimpleNamespace(data=[{c: r[c] for c in self._columns} for r in rows])


class _DB:
    def __init__(self, games):
        self.games = games
        self.corrections = []
        self.writes = []
        self.cascaded = []
        self.apply_error = None
        self.error_after_apply = None

    def table(self, name):
        if name == "game_corrections":
            return _CorrectionsTable(self)
        assert name in ("games", "providers"), name
        return _Query(self, name)

    def rpc(self, name, params):
        assert name == "apply_game_correction", name
        return _RecordedApply(self, params)


class _RecordedApply(_ApplyCorrection):
    """Records at execute(): a caller that builds the request and never sends it wrote nothing."""

    def execute(self):
        self._db.writes.append(("correct", self._params["correction_id"]))
        return super().execute()


def _run_main(monkeypatch, db, live_by_event, argv):
    monkeypatch.setattr(rec, "get_client", lambda: db)
    monkeypatch.setattr(rec, "fetch_live_event", lambda event_id: live_by_event[event_id])
    monkeypatch.setattr(sys, "argv", ["reconcile_tgs_scores.py", *argv])
    return rec.main()


def _confirmed(tmp_path, *changes):
    """A snapshot from a previous run that saw each (game id, stored pair, live pair)."""
    path = tmp_path / "previous.json"
    path.write_text(
        json.dumps({"changes": {gid: {"stored": list(s), "live": list(v)} for gid, s, v in changes}}),
        encoding="utf-8",
    )
    return str(path)


# classify


@pytest.mark.parametrize(
    "stored, live_games, expected",
    [
        ((2, 0), [(2, 0)], ("unchanged", None)),
        ((2, 0), [(0, 2)], ("reversed", (0, 2))),
        ((2, 0), [(3, 0)], ("one_side", (3, 0))),
        ((2, 0), [(2, 1)], ("one_side", (2, 1))),
        ((2, 0), [(3, 1)], ("both_sides", (3, 1))),
        ((1, 1), [(0, 2)], ("both_sides", (0, 2))),
        ((2, 0), [(None, None)], ("live_unscored", None)),
        ((2, 0), [(3, 0), (1, 0)], ("ambiguous", None)),
        ((2, 0), [], ("not_found", None)),
    ],
)
def test_classify_reads_a_stored_game_against_the_live_schedule(stored, live_games, expected):
    live = {(DATE, "111", "222"): live_games} if live_games else {}

    assert rec.classify(_stored("g", *stored), live) == expected


def test_classify_does_not_match_a_game_on_another_date_or_with_the_teams_swapped():
    live = {("2026-10-05", "111", "222"): [(3, 0)], (DATE, "222", "111"): [(3, 0)]}

    assert rec.classify(_stored("g"), live) == ("not_found", None)


# the two-run gate and the plan


def _plan(rows, live, snapshot=None, excluded=()):
    return rec.build_plan(rows, list(excluded), {EVENT: _live(*live)}, snapshot or {})


def test_a_change_seen_for_the_first_time_waits_for_a_second_sighting():
    row = _stored("g")

    plan = _plan([row], [("111", "222", 3, 0)])

    assert (plan["correct"], plan["hide"]) == ([], [])
    assert plan["waiting"] == [row]
    assert plan["observed"] == {"g": {"stored": [2, 0], "live": [3, 0]}}


def test_a_change_the_previous_run_also_saw_is_applied(tmp_path):
    row = _stored("g")
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("g", (2, 0), (3, 0))))

    plan = _plan([row], [("111", "222", 3, 0)], snapshot)

    assert [(i["row"]["id"], i["live"]) for i in plan["correct"]] == [("g", (3, 0))]
    assert plan["waiting"] == []


def test_a_live_score_that_differs_from_the_one_the_previous_run_saw_waits_again(tmp_path):
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("g", (2, 0), (3, 0))))

    plan = _plan([_stored("g")], [("111", "222", 4, 0)], snapshot)

    assert plan["correct"] == []
    assert len(plan["waiting"]) == 1


def test_a_stored_score_that_differs_from_the_one_the_previous_run_saw_waits_again(tmp_path):
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("g", (1, 0), (3, 0))))

    plan = _plan([_stored("g", 2, 0)], [("111", "222", 3, 0)], snapshot)

    assert plan["correct"] == []
    assert len(plan["waiting"]) == 1


def test_a_change_that_moved_both_sides_is_held_even_when_the_previous_run_saw_it(tmp_path):
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("g", (1, 1), (0, 2))))

    plan = _plan([_stored("g", 1, 1)], [("111", "222", 0, 2)], snapshot)

    assert (plan["correct"], plan["hide"], plan["waiting"]) == ([], [], [])
    assert plan["counts"]["both_sides"] == 1


def test_a_game_with_a_second_stored_row_and_no_row_at_the_live_score_is_left_alone(tmp_path):
    first, second = _stored("a", 2, 0), _stored("b", 1, 0)
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("a", (2, 0), (3, 0)), ("b", (1, 0), (3, 0))))

    plan = _plan([first, second], [("111", "222", 3, 0)], snapshot)

    assert (plan["correct"], plan["hide"]) == ([], [])
    assert plan["counts"]["ambiguous_stored"] == 2


def test_the_stale_row_is_hidden_when_a_second_row_already_carries_the_live_score(tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("stale", (2, 0), (3, 0))))

    plan = _plan([stale, twin], [("111", "222", 3, 0)], snapshot)

    assert [i["row"]["id"] for i in plan["hide"]] == ["stale"]
    assert plan["correct"] == []


def test_a_row_of_another_game_at_the_live_score_is_not_a_twin(tmp_path):
    stale = _stored("stale", 2, 0)
    other_teams = _stored("other-teams", 3, 0, home_pid="9", away_pid="8")
    other_day = _stored("other-day", 3, 0, game_date="2026-10-11")
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("stale", (2, 0), (3, 0))))

    plan = _plan([stale, other_teams, other_day], [("111", "222", 3, 0)], snapshot)

    assert [i["row"]["id"] for i in plan["correct"]] == ["stale"]
    assert plan["hide"] == []


def test_a_twin_stored_the_other_way_round_is_still_a_twin(tmp_path):
    stale = _stored("stale", 2, 0)
    twin = _stored("twin", 0, 3, home_pid="222", away_pid="111")
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("stale", (2, 0), (3, 0))))

    plan = _plan([stale, twin], [("111", "222", 3, 0)], snapshot)

    assert [i["row"]["id"] for i in plan["hide"]] == ["stale"]


def test_games_that_are_not_changes_never_reach_the_plan(tmp_path):
    rows = [_stored("same", 2, 0, "1", "2"), _stored("unscored", 2, 0, "3", "4"), _stored("gone", 2, 0, "5", "6")]
    live = [("1", "2", 2, 0), ("3", "4", None, None)]

    plan = _plan(rows, live)

    assert (plan["correct"], plan["hide"], plan["waiting"], plan["observed"]) == ([], [], [], {})
    assert plan["counts"] == {"unchanged": 1, "live_unscored": 1, "not_found": 1}


def test_a_game_of_an_event_that_could_not_be_read_is_skipped_not_compared():
    plan = rec.build_plan([_stored("g")], [], {}, {})

    assert plan["counts"] == {"event_skipped": 1}
    assert plan["waiting"] == []


# reading the live schedule


class _Response:
    def __init__(self, status, payload=None, fails_to_parse=False):
        self.status_code = status
        self._payload = payload
        self._fails = fails_to_parse

    def json(self):
        if self._fails:
            raise ValueError("not json")
        return self._payload


def _structure():
    return {"data": {"girlsDivAndFlightList": [{"flightList": [{"flightID": 7}]}], "boysDivAndFlightList": []}}


def _flight(*games):
    return {
        "data": [
            {
                "gameDate": f"{DATE}T14:00:00",
                "hometeamID": h,
                "awayteamID": a,
                "hometeamscore": hs,
                "awayteamscore": a_s,
            }
            for h, a, hs, a_s in games
        ]
    }


def _serve(monkeypatch, responder):
    monkeypatch.setattr(rec.requests, "get", lambda url, **kw: responder(url))
    monkeypatch.setattr(rec.time, "sleep", lambda s: None)


def test_the_live_schedule_is_keyed_by_date_and_team_ids(monkeypatch):
    def responder(url):
        if "schedule-or-standings" in url:
            return _Response(200, _structure())
        return _Response(200, _flight((111, 222, 3, 0), (5, 6, None, None)))

    _serve(monkeypatch, responder)

    assert rec.fetch_live_event(EVENT) == {(DATE, "111", "222"): [(3, 0)], (DATE, "5", "6"): [(None, None)]}


def test_a_game_without_a_date_is_not_keyed(monkeypatch):
    def responder(url):
        if "schedule-or-standings" in url:
            return _Response(200, _structure())
        return _Response(200, {"data": [{"gameDate": None, "hometeamID": 1, "awayteamID": 2}]})

    _serve(monkeypatch, responder)

    assert rec.fetch_live_event(EVENT) == {}


@pytest.mark.parametrize("failure", ["status", "exception", "unparseable"])
def test_a_flight_that_cannot_be_read_fails_the_event_rather_than_reading_as_empty(monkeypatch, failure):
    def responder(url):
        if "schedule-or-standings" in url:
            return _Response(200, _structure())
        if failure == "exception":
            raise requests.ConnectionError("down")
        return _Response(503) if failure == "status" else _Response(200, fails_to_parse=True)

    _serve(monkeypatch, responder)

    with pytest.raises(rec.LiveFetchError):
        rec.fetch_live_event(EVENT)


def test_a_request_is_retried_before_the_event_is_given_up(monkeypatch):
    calls = []

    def responder(url):
        calls.append(url)
        return _Response(503) if len(calls) < rec.FETCH_TRIES else _Response(200, {"data": {}})

    _serve(monkeypatch, responder)

    assert rec.fetch_live_event(EVENT) == {}
    assert len(calls) == 3


# main


def _tgs_games():
    return [_stored("g", 2, 0)]


def test_a_dry_run_is_the_default_and_writes_nothing(monkeypatch, tmp_path, capsys):
    db = _DB(_tgs_games())
    previous = _confirmed(tmp_path, ("g", (2, 0), (3, 0)))

    code = _run_main(
        monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, ["--since", DATE, "--snapshot-in", previous]
    )

    assert code == 0
    assert db.writes == [] and db.corrections == []
    assert "DRY RUN" in capsys.readouterr().out


def test_a_first_run_applies_nothing_even_with_execute(monkeypatch, tmp_path):
    db = _DB(_tgs_games())
    out = tmp_path / "log.json"

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        ["--since", DATE, "--execute", "--out", str(out), "--snapshot-out", str(tmp_path / "now.json")],
    )

    assert code == 0
    assert db.writes == [] and not out.exists()
    seen = json.loads((tmp_path / "now.json").read_text())
    assert seen["changes"] == {"g": {"stored": [2, 0], "live": [3, 0]}}


def test_a_confirmed_change_is_corrected_in_place_and_logged(monkeypatch, tmp_path):
    game = _stored("g", 2, 0)
    db = _DB([game])
    out = tmp_path / "log.json"

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        ["--since", DATE, "--execute", "--out", str(out), "--snapshot-in", _confirmed(tmp_path, ("g", (2, 0), (3, 0)))],
    )

    assert code == 0
    assert (game["home_score"], game["away_score"], game["result"]) == (3, 0, "W")
    [correction] = db.corrections
    assert correction["original_game_uid"] == game["game_uid"]
    assert correction["original_values"] == {"home_score": 2, "away_score": 0}
    assert correction["corrected_values"] == {"home_score": 3, "away_score": 0, "result": "W"}
    assert correction["submitted_by"] == "reconcile_tgs_scores"
    log = json.loads(out.read_text())
    assert log["applied"] is True and log["hidden"] == []
    assert log["corrections"] == [
        {"game_id": "g", "game_uid": game["game_uid"], "from": [2, 0], "to": [3, 0], "outcome": "applied"}
    ]


def test_the_result_follows_the_live_score(monkeypatch, tmp_path):
    game = _stored("g", 2, 0)
    db = _DB([game])

    _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 0, 2))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("g", (2, 0), (0, 2))),
        ],
    )

    assert (game["home_score"], game["away_score"], game["result"]) == (0, 2, "L")


def test_the_rollback_log_exists_before_the_first_write(monkeypatch, tmp_path):
    game = _stored("g", 2, 0)
    db = _DB([game])
    out = tmp_path / "log.json"
    seen_at_first_write = []
    original = _ApplyCorrection.execute

    def watch(self):
        seen_at_first_write.append(json.loads(out.read_text()))
        return original(self)

    monkeypatch.setattr(_ApplyCorrection, "execute", watch)

    _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        ["--since", DATE, "--execute", "--out", str(out), "--snapshot-in", _confirmed(tmp_path, ("g", (2, 0), (3, 0)))],
    )

    [log_then] = seen_at_first_write
    assert log_then["applied"] is False
    assert [(c["game_id"], c["outcome"]) for c in log_then["corrections"]] == [("g", "pending")]


def test_an_existing_rollback_log_is_never_overwritten(monkeypatch, tmp_path):
    db = _DB([_stored("g", 2, 0)])
    out = tmp_path / "log.json"
    out.write_text("earlier run", encoding="utf-8")

    with pytest.raises(SystemExit):
        _run_main(
            monkeypatch,
            db,
            {EVENT: _live(("111", "222", 3, 0))},
            [
                "--since",
                DATE,
                "--execute",
                "--out",
                str(out),
                "--snapshot-in",
                _confirmed(tmp_path, ("g", (2, 0), (3, 0))),
            ],
        )

    assert out.read_text() == "earlier run"
    assert db.writes == []


def test_a_game_whose_score_moved_after_it_was_read_is_skipped(monkeypatch, tmp_path):
    game = _stored("g", 2, 0)
    db = _DB([game])
    real_fetch = rec.fetch_stored

    def fetch_then_move(sb, since, excluded=False):
        rows = real_fetch(sb, since, excluded)
        if not excluded:
            game["home_score"] = 4
        return rows

    monkeypatch.setattr(rec, "fetch_stored", fetch_then_move)

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("g", (2, 0), (3, 0))),
        ],
    )

    assert code == 0
    assert db.corrections == [] and game["home_score"] == 4
    assert [c["outcome"] for c in json.loads((tmp_path / "log.json").read_text())["corrections"]] == ["skipped"]


def test_a_stale_row_beside_its_corrected_twin_is_hidden_not_corrected(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    db = _DB([stale, twin])

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("stale", (2, 0), (3, 0))),
        ],
    )

    assert code == 0
    assert (stale["is_excluded"], twin["is_excluded"]) == (True, False)
    assert db.corrections == []
    assert db.writes == [("hide", ["stale"], {"is_excluded": True})]
    assert json.loads((tmp_path / "log.json").read_text())["hidden"] == [
        {"game_id": "stale", "score": [2, 0], "twin_id": "twin", "outcome": "applied"}
    ]


def _hide_argv(tmp_path):
    return [
        "--since",
        DATE,
        "--execute",
        "--out",
        str(tmp_path / "log.json"),
        "--snapshot-in",
        _confirmed(tmp_path, ("stale", (2, 0), (3, 0))),
    ]


def _after_first_read(monkeypatch, change):
    """Run `change` once the stored rows have been read, as another writer would."""
    real_fetch = rec.fetch_stored

    def fetch_then_change(sb, since, excluded=False):
        rows = real_fetch(sb, since, excluded)
        if not excluded:
            change()
        return rows

    monkeypatch.setattr(rec, "fetch_stored", fetch_then_change)


def test_a_stale_row_hidden_after_it_was_read_is_skipped_not_hidden_again(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    db = _DB([stale, twin])
    _after_first_read(monkeypatch, lambda: stale.update(is_excluded=True))

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert [h["outcome"] for h in json.loads((tmp_path / "log.json").read_text())["hidden"]] == ["skipped"]


def test_a_stale_row_corrected_to_the_live_score_after_it_was_read_is_not_hidden(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    db = _DB([stale, twin])
    _after_first_read(monkeypatch, lambda: stale.update(home_score=3))

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert (stale["is_excluded"], twin["is_excluded"], db.cascaded) == (False, False, [])
    assert [h["outcome"] for h in json.loads((tmp_path / "log.json").read_text())["hidden"]] == ["skipped"]


def test_a_hide_that_would_also_hide_another_game_is_refused_and_reported(monkeypatch, tmp_path, capsys):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    same_score_elsewhere = _stored("bystander", 2, 0, home_pid="9", away_pid="8")
    db = _DB([stale, twin, same_score_elsewhere])

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0), ("9", "8", 2, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("stale", (2, 0), (3, 0))),
        ],
    )

    assert code == 0
    assert db.writes == []
    assert (stale["is_excluded"], same_score_elsewhere["is_excluded"]) == (False, False)
    assert "hides refused because they would also hide another game: 1" in capsys.readouterr().out


def test_a_refused_hide_does_not_stop_the_corrections_beside_it(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    bystander = _stored("bystander", 2, 0, home_pid="9", away_pid="8")
    fixable = _stored("fixable", 1, 0, home_pid="5", away_pid="6")
    db = _DB([stale, twin, bystander, fixable])

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0), ("9", "8", 2, 0), ("5", "6", 2, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("stale", (2, 0), (3, 0)), ("fixable", (1, 0), (2, 0))),
        ],
    )

    assert code == 0
    assert (fixable["home_score"], stale["is_excluded"]) == (2, False)


def test_a_correction_that_fails_to_apply_fails_the_run(monkeypatch, tmp_path):
    game = _stored("g", 2, 0)
    db = _DB([game])
    db.apply_error = RuntimeError("Game not found")

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("g", (2, 0), (3, 0))),
        ],
    )

    assert code == 1
    assert (game["home_score"], game["away_score"]) == (2, 0)
    assert [c["status"] for c in db.corrections] == ["rejected"]


def test_an_event_that_cannot_be_read_leaves_its_games_alone(monkeypatch, tmp_path):
    db = _DB([_stored("g", 2, 0)])

    def fail(event_id):
        raise rec.LiveFetchError("down")

    monkeypatch.setattr(rec, "get_client", lambda: db)
    monkeypatch.setattr(rec, "fetch_live_event", fail)
    monkeypatch.setattr(sys, "argv", ["reconcile_tgs_scores.py", "--since", DATE, "--execute"])

    assert rec.main() == 1
    assert db.writes == []


def test_only_unexcluded_scored_tgs_games_inside_the_window_are_read(monkeypatch, tmp_path):
    rows = [
        _stored("kept"),
        _stored("excluded", excluded=True),
        _stored("old", game_date="2026-09-01"),
        _stored("unscored", home_score=None, away_score=None),
        _stored("home-unscored", home_score=None, away_score=1),
        _stored("away-unscored", home_score=1, away_score=None),
        _stored("other-provider", provider="prov-gotsport"),
        _stored("no-event", source="https://example.com/x"),
    ]

    assert [g["id"] for g in rec.fetch_stored(_DB(rows), DATE)] == ["kept"]


def test_the_stored_games_are_paged_in_id_order(monkeypatch):
    rows = [_stored(f"{i:05d}") for i in range(rec.PAGE + 5)]

    assert len(rec.fetch_stored(_DB(rows), DATE)) == rec.PAGE + 5


def test_classify_treats_a_second_meeting_listed_the_other_way_round_as_ambiguous():
    live = {(DATE, "111", "222"): [(2, 0)], (DATE, "222", "111"): [(0, 2)]}

    assert rec.classify(_stored("g", 0, 0), live) == ("ambiguous", None)


def test_a_pool_game_and_a_final_listed_with_the_teams_reversed_are_left_alone():
    pool, final = _stored("pool", 2, 0), _stored("final", 0, 0, home_pid="222", away_pid="111")

    plan = _plan([pool, final], [("111", "222", 2, 0), ("222", "111", 0, 2)])

    assert (plan["correct"], plan["hide"], plan["waiting"], plan["observed"]) == ([], [], [], {})
    assert plan["counts"] == {"ambiguous": 2}


def test_a_stale_row_beside_an_excluded_twin_at_the_live_score_is_left_alone(tmp_path):
    stale, dead = _stored("stale", 2, 0), _stored("dead", 3, 0, excluded=True)
    snapshot = rec.load_snapshot(_confirmed(tmp_path, ("stale", (2, 0), (3, 0))))

    plan = _plan([stale], [("111", "222", 3, 0)], snapshot, excluded=[dead])

    assert (plan["correct"], plan["hide"], plan["waiting"]) == ([], [], [])
    assert plan["counts"]["blocked_by_excluded_twin"] == 1


# reading scores


def _live_from(monkeypatch, game):
    def responder(url):
        if "schedule-or-standings" in url:
            return _Response(200, _structure())
        base = {"gameDate": f"{DATE}T14:00:00", "hometeamID": 111, "awayteamID": 222}
        return _Response(200, {"data": [{**base, **game}]})

    _serve(monkeypatch, responder)
    return rec.fetch_live_event(EVENT)


@pytest.mark.parametrize(
    "home, away, expected",
    [
        ("", 1, (None, None)),
        (None, 1, (None, None)),
        (3, "", (None, None)),
        ("x", 1, (None, None)),
        (3.5, 1, (None, None)),
        (99, 0, (None, None)),
        (51, 0, (None, None)),
        (0, 51, (None, None)),
        (-1, 0, (None, None)),
        (50, 0, (50, 0)),
        (0, 0, (0, 0)),
        ("3", "1", (3, 1)),
    ],
)
def test_a_live_score_counts_only_when_it_is_a_plausible_integer(monkeypatch, home, away, expected):
    live = _live_from(monkeypatch, {"hometeamscore": home, "awayteamscore": away})

    assert live == {(DATE, "111", "222"): [expected]}


def test_a_live_score_is_read_from_the_camel_case_keys_when_the_lowercase_ones_are_absent(monkeypatch):
    live = _live_from(monkeypatch, {"homeScore": 3, "awayScore": 1})

    assert live == {(DATE, "111", "222"): [(3, 1)]}


def test_a_blank_live_score_is_not_a_change_and_does_not_stop_the_run(monkeypatch):
    game = _stored("g", 2, 0)
    db = _DB([game])

    code = _run_main(monkeypatch, db, {EVENT: {(DATE, "111", "222"): [(None, None)]}}, ["--since", DATE, "--execute"])

    assert code == 0 and db.writes == [] and game["home_score"] == 2


@pytest.mark.parametrize("stored, live, result", [((2, 0), (3, 0), "W"), ((2, 0), (2, 3), "L"), ((2, 0), (2, 2), "D")])
def test_the_result_is_worked_out_from_the_live_score_for_the_home_side(monkeypatch, tmp_path, stored, live, result):
    game = _stored("g", *stored)
    db = _DB([game])

    _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", *live))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("g", stored, live)),
        ],
    )

    assert (game["home_score"], game["away_score"], game["result"]) == (*live, result)


# the snapshot


def test_a_snapshot_path_that_does_not_exist_is_an_error(tmp_path):
    with pytest.raises(SystemExit):
        rec.load_snapshot(str(tmp_path / "missing.json"))


def test_no_snapshot_path_means_nothing_is_confirmed():
    assert rec.load_snapshot(None) == {}


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"changes": []}', '{"changes": {"g": "x"}}', '{"changes": {"g": {"stored": [1, 0]}}}', "{}"],
)
def test_a_snapshot_of_another_shape_confirms_nothing(tmp_path, content):
    path = tmp_path / "odd.json"
    path.write_text(content, encoding="utf-8")

    assert rec.load_snapshot(str(path)) == {}


def test_a_dry_run_writes_no_snapshot_file(monkeypatch, tmp_path, capsys):
    out = tmp_path / "now.json"

    _run_main(
        monkeypatch,
        _DB(_tgs_games()),
        {EVENT: _live(("111", "222", 3, 0))},
        ["--since", DATE, "--snapshot-out", str(out)],
    )

    assert not out.exists()
    assert "would write 1 observations" in capsys.readouterr().out


# what a hide can reach


def test_a_hide_is_refused_when_another_providers_game_would_be_hidden_with_it(monkeypatch, tmp_path, capsys):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    gotsport = _stored(
        "gotsport", 2, 0, home_pid="g1", away_pid="g2", provider="prov-gotsport", source="https://example.com/g"
    )
    db = _DB([stale, twin, gotsport])

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert db.writes == [] and db.cascaded == []
    assert (stale["is_excluded"], gotsport["is_excluded"]) == (False, False)
    assert "hides refused because they would also hide another game: 1" in capsys.readouterr().out


def test_a_hide_is_refused_when_this_runs_own_correction_would_make_it_collide(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    fixable = _stored("fixable", 1, 0, home_pid="5", away_pid="6")
    db = _DB([stale, twin, fixable])

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0), ("5", "6", 2, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("stale", (2, 0), (3, 0)), ("fixable", (1, 0), (2, 0))),
        ],
    )

    assert code == 0
    assert fixable["home_score"] == 2
    assert (stale["is_excluded"], fixable["is_excluded"], db.cascaded) == (False, False, [])


def test_a_hide_is_refused_when_the_trigger_would_also_take_a_copy_stored_the_other_way_round(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    mirrored = _stored("mirrored", 0, 2, home_pid="222", away_pid="111")
    mirrored.update(home_team_master_id=AWAY_MASTER, away_team_master_id=HOME_MASTER)
    db = _DB([stale, twin, mirrored])

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert db.writes == [] and db.cascaded == []
    assert (stale["is_excluded"], mirrored["is_excluded"]) == (False, False)


# outcomes and exit codes


def _two_games():
    return [_stored("a", 2, 0, "1", "2"), _stored("b", 2, 0, "3", "4")]


def _two_games_argv(tmp_path):
    return [
        "--since",
        DATE,
        "--execute",
        "--out",
        str(tmp_path / "log.json"),
        "--snapshot-in",
        _confirmed(tmp_path, ("a", (2, 0), (3, 0)), ("b", (2, 0), (3, 0))),
    ]


def test_the_log_records_each_entrys_own_outcome(monkeypatch, tmp_path):
    outcomes = iter([False, True])
    monkeypatch.setattr(rec, "apply_score_correction", lambda *a, **k: next(outcomes))

    code = _run_main(
        monkeypatch,
        _DB(_two_games()),
        {EVENT: _live(("1", "2", 3, 0), ("3", "4", 3, 0))},
        _two_games_argv(tmp_path),
    )

    assert code == 1
    corrections = json.loads((tmp_path / "log.json").read_text())["corrections"]
    assert [(c["game_id"], c["outcome"]) for c in corrections] == [("a", "failed"), ("b", "applied")]


def test_a_crash_partway_leaves_the_log_with_the_untried_entries_pending(monkeypatch, tmp_path):
    calls = []

    def die_on_the_second(*args, **kwargs):
        calls.append(kwargs["game_uid"])
        if len(calls) == 2:
            raise RuntimeError("lost the connection")
        return True

    monkeypatch.setattr(rec, "apply_score_correction", die_on_the_second)

    with pytest.raises(RuntimeError):
        _run_main(
            monkeypatch,
            _DB(_two_games()),
            {EVENT: _live(("1", "2", 3, 0), ("3", "4", 3, 0))},
            _two_games_argv(tmp_path),
        )

    log = json.loads((tmp_path / "log.json").read_text())
    assert log["applied"] is True
    assert [c["outcome"] for c in log["corrections"]] == ["applied", "pending"]


def test_a_window_with_no_stored_tgs_games_is_a_clean_run(monkeypatch):
    assert _run_main(monkeypatch, _DB([]), {}, ["--since", DATE, "--execute"]) == 0


def test_an_event_that_cannot_be_read_does_not_fail_the_run_or_stop_the_others(monkeypatch, tmp_path):
    readable = _stored("a", 2, 0, "1", "2")
    unreadable = _stored("b", 2, 0, "3", "4", source=SOURCE.replace(EVENT, "4301"))
    db = _DB([readable, unreadable])

    def fetch(event_id):
        if event_id == "4301":
            raise rec.LiveFetchError("down")
        return _live(("1", "2", 3, 0))

    monkeypatch.setattr(rec, "get_client", lambda: db)
    monkeypatch.setattr(rec, "fetch_live_event", fetch)
    monkeypatch.setattr(sys, "argv", ["reconcile_tgs_scores.py", *_two_games_argv(tmp_path)])

    assert rec.main() == 0
    assert (readable["home_score"], unreadable["home_score"]) == (3, 2)


def test_the_summary_lines_the_workflow_reads_are_printed(monkeypatch, tmp_path, capsys):
    games = [_stored("a", 2, 0, "1", "2"), _stored("b", 1, 1, "3", "4")]
    previous = _confirmed(tmp_path, ("a", (2, 0), (3, 0)))

    _run_main(
        monkeypatch,
        _DB(games),
        {EVENT: _live(("1", "2", 3, 0), ("3", "4", 0, 2))},
        ["--since", DATE, "--execute", "--out", str(tmp_path / "log.json"), "--snapshot-in", previous],
    )

    out = capsys.readouterr().out
    assert re.search(r"Corrected ([\d,]+)", out).group(1) == "1"
    assert re.search(r"hid ([\d,]+)", out).group(1) == "0"
    assert re.search(r"another game: ([\d,]+)", out).group(1) == "0"
    assert re.search(r"altered: ([\d,]+)", out).group(1) == "0"
    assert re.search(r"both_sides: ([\d,]+)", out).group(1) == "1"


def test_a_stale_row_whose_away_score_was_corrected_after_it_was_read_is_not_hidden(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 3, 1), _stored("twin", 3, 0)
    db = _DB([stale, twin])
    _after_first_read(monkeypatch, lambda: stale.update(away_score=0))

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(("111", "222", 3, 0))},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("stale", (3, 1), (3, 0))),
        ],
    )

    assert code == 0
    assert (stale["is_excluded"], twin["is_excluded"], db.cascaded) == (False, False, [])


def test_a_stale_row_is_not_hidden_when_its_twin_was_excluded_after_the_read(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    db = _DB([stale, twin])
    _after_first_read(monkeypatch, lambda: twin.update(is_excluded=True))

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert (stale["is_excluded"], twin["is_excluded"]) == (False, True)
    assert [h["outcome"] for h in json.loads((tmp_path / "log.json").read_text())["hidden"]] == ["skipped"]


def test_a_stale_row_is_not_hidden_when_its_twin_no_longer_carries_the_live_score(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    db = _DB([stale, twin])
    _after_first_read(monkeypatch, lambda: twin.update(home_score=4))

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert stale["is_excluded"] is False


def test_a_twin_stored_the_other_way_round_still_lets_the_stale_row_be_hidden(monkeypatch, tmp_path):
    stale = _stored("stale", 2, 0)
    twin = _stored("twin", 0, 3, home_pid="222", away_pid="111")
    twin.update(home_team_master_id=AWAY_MASTER, away_team_master_id=HOME_MASTER)
    db = _DB([stale, twin])

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert (stale["is_excluded"], twin["is_excluded"]) == (True, False)


def test_a_stale_row_whose_live_score_sits_on_an_excluded_row_is_left_alone_by_main(monkeypatch, tmp_path):
    stale, dead = _stored("stale", 2, 0), _stored("dead", 3, 0, excluded=True)
    db = _DB([stale, dead])

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _hide_argv(tmp_path))

    assert code == 0
    assert db.corrections == [] and db.writes == []
    assert (stale["home_score"], stale["away_score"]) == (2, 0)


def test_the_double_refuses_a_correction_onto_a_row_that_already_holds_the_score():
    stale, dead = _stored("stale", 2, 0), _stored("dead", 3, 0, excluded=True)
    db = _DB([stale, dead])

    applied = rec.apply_score_correction(
        db,
        game_uid=stale["game_uid"],
        original={"home_score": 2, "away_score": 0},
        corrected={"home_score": 3, "away_score": 0, "result": "W"},
        reason="test",
        submitted_by="test",
    )

    assert applied is False
    assert (stale["home_score"], stale["away_score"]) == (2, 0)


def test_a_correction_whose_response_was_lost_after_it_committed_is_logged_applied(monkeypatch, tmp_path):
    game = _stored("g", 2, 0)
    db = _DB([game])
    db.error_after_apply = TimeoutError("response lost")

    code = _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0))}, _g_argv(tmp_path))

    assert code == 0
    assert (game["home_score"], game["away_score"]) == (3, 0)
    assert [c["outcome"] for c in json.loads((tmp_path / "log.json").read_text())["corrections"]] == ["applied"]


def _g_argv(tmp_path):
    return [
        "--since",
        DATE,
        "--execute",
        "--out",
        str(tmp_path / "log.json"),
        "--snapshot-in",
        _confirmed(tmp_path, ("g", (2, 0), (3, 0))),
    ]


def test_a_hide_is_refused_for_a_bystander_whose_teams_fall_past_the_first_batch_of_ids(monkeypatch, tmp_path):
    rows, live, confirmed = [], [], []
    for i in range(51):
        home_master, away_master = f"m{i:04d}h", f"m{i:04d}a"
        stale = _stored(f"stale{i:02d}", 2, 0, home_pid=str(i), away_pid=str(i + 1000))
        twin = _stored(f"twin{i:02d}", 3, 0, home_pid=str(i), away_pid=str(i + 1000))
        for row in (stale, twin):
            row.update(home_team_master_id=home_master, away_team_master_id=away_master)
        rows += [stale, twin]
        live.append((str(i), str(i + 1000), 3, 0))
        confirmed.append((f"stale{i:02d}", (2, 0), (3, 0)))
    bystander = _stored(
        "bystander", 2, 0, home_pid="g1", away_pid="g2", provider="prov-gotsport", source="https://example.com/g"
    )
    bystander.update(home_team_master_id="m0050h", away_team_master_id="m0050a")
    db = _DB([*rows, bystander])

    code = _run_main(
        monkeypatch,
        db,
        {EVENT: _live(*live)},
        [
            "--since",
            DATE,
            "--execute",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, *confirmed),
        ],
    )

    assert code == 0
    assert bystander["is_excluded"] is False and db.cascaded == []
    assert [r["is_excluded"] for r in rows if r["id"] == "stale50"] == [False]
    assert sum(r["is_excluded"] for r in rows if r["id"].startswith("stale")) == 50


def test_limit_events_limits_what_an_execute_run_writes(monkeypatch, tmp_path):
    first = _stored("first", 2, 0, "1", "2")
    second = _stored("second", 2, 0, "3", "4", source=SOURCE.replace(EVENT, "4301"))
    db = _DB([first, second])
    lives = {EVENT: _live(("1", "2", 3, 0)), "4301": _live(("3", "4", 3, 0))}

    code = _run_main(
        monkeypatch,
        db,
        lives,
        [
            "--since",
            DATE,
            "--execute",
            "--limit-events",
            "1",
            "--out",
            str(tmp_path / "log.json"),
            "--snapshot-in",
            _confirmed(tmp_path, ("first", (2, 0), (3, 0)), ("second", (2, 0), (3, 0))),
        ],
    )

    assert code == 0
    assert (first["home_score"], second["home_score"]) == (3, 2)


def test_the_double_does_not_cascade_between_rows_whose_masters_are_unresolved(monkeypatch, tmp_path):
    stale, twin = _stored("stale", 2, 0), _stored("twin", 3, 0)
    unrelated = _stored("unrelated", 2, 0, home_pid="7", away_pid="8")
    for row in (stale, twin, unrelated):
        row.update(home_team_master_id=None, away_team_master_id=None)
    db = _DB([stale, twin, unrelated])

    _run_main(monkeypatch, db, {EVENT: _live(("111", "222", 3, 0), ("7", "8", 2, 0))}, _hide_argv(tmp_path))

    assert stale["is_excluded"] is True
    assert (unrelated["is_excluded"], db.cascaded) == (False, [])


# reading the live schedule


def _structure_of(flight_ids, key="girlsDivAndFlightList"):
    return {"data": {key: [{"flightList": [{"flightID": fid} for fid in flight_ids]}]}}


def _serve_flights(monkeypatch, structure, flights):
    requested = []

    def responder(url):
        requested.append(url)
        if "schedule-or-standings" in url:
            return _Response(200, structure)
        return _Response(200, flights)

    _serve(monkeypatch, responder)
    return requested


def test_a_flight_in_the_boys_list_is_read_too(monkeypatch):
    _serve_flights(monkeypatch, _structure_of([7], key="boysDivAndFlightList"), _flight((111, 222, 3, 0)))

    assert rec.fetch_live_event(EVENT) == {(DATE, "111", "222"): [(3, 0)]}


@pytest.mark.parametrize("wrapper", ["schedules", "games"])
def test_a_flight_payload_wrapped_in_schedules_or_games_is_read(monkeypatch, wrapper):
    games = _flight((111, 222, 3, 0))["data"]
    _serve_flights(monkeypatch, _structure_of([7]), {"data": {wrapper: games}})

    assert rec.fetch_live_event(EVENT) == {(DATE, "111", "222"): [(3, 0)]}


def test_a_flight_id_that_is_not_an_integer_fails_the_event_before_any_flight_request(monkeypatch):
    hostile = "7\n::warning::forged"
    requested = _serve_flights(monkeypatch, _structure_of([hostile]), _flight())

    with pytest.raises(rec.LiveFetchError) as raised:
        rec.fetch_live_event(EVENT)

    assert "::warning::" not in str(raised.value)
    assert all("schedules-by-flight" not in url for url in requested)


@pytest.mark.parametrize(
    "structure",
    [
        [],
        "text",
        {"data": {"girlsDivAndFlightList": ["x"]}},
        {"data": {"girlsDivAndFlightList": [{"flightList": [{}]}]}},
    ],
)
def test_a_schedule_structure_of_another_shape_fails_the_event_instead_of_the_run(monkeypatch, structure):
    _serve_flights(monkeypatch, structure, _flight())

    with pytest.raises(rec.LiveFetchError):
        rec.fetch_live_event(EVENT)


@pytest.mark.parametrize(
    "structure",
    [
        {"data": None},
        {"data": []},
        {"data": {"girlsDivAndFlightList": None}},
        {"data": {"girlsDivAndFlightList": [{"flightList": None}]}},
    ],
)
def test_an_event_with_no_flights_reads_as_an_empty_schedule(monkeypatch, structure):
    _serve_flights(monkeypatch, structure, _flight())

    assert rec.fetch_live_event(EVENT) == {}


def test_a_game_that_is_not_an_object_is_skipped(monkeypatch):
    _serve_flights(monkeypatch, _structure_of([7]), {"data": ["x", None, _flight((111, 222, 3, 0))["data"][0]]})

    assert rec.fetch_live_event(EVENT) == {(DATE, "111", "222"): [(3, 0)]}


def test_a_failed_event_is_reported_by_repr_so_its_text_cannot_split_the_log(monkeypatch, tmp_path, capsys):
    def fail(event_id):
        raise rec.LiveFetchError("a\n::warning::b")

    monkeypatch.setattr(rec, "get_client", lambda: _DB(_tgs_games()))
    monkeypatch.setattr(rec, "fetch_live_event", fail)
    monkeypatch.setattr(sys, "argv", ["reconcile_tgs_scores.py", "--since", DATE])

    rec.main()

    out = capsys.readouterr().out
    assert "::warning::b" in out and "\n::warning::" not in out


# the lines the workflow reads, taken from the workflow itself

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tgs-score-reconcile.yml"


def _workflow_greps():
    return dict(re.findall(r"(\w+)=\$\(grep -oP '([^']+)'", WORKFLOW.read_text(encoding="utf-8")))


def _grep_tail(pattern, text):
    """What `grep -oP 'prefix \\K value' | tail -1` yields: the last match of `value` after `prefix`."""
    prefix, _, value = pattern.partition("\\K")
    matches = [m.group(1) for m in re.finditer(f"{prefix}({value})", text)]
    return matches[-1] if matches else ""


def test_every_summary_value_the_workflow_greps_for_is_in_the_scripts_output(monkeypatch, tmp_path, capsys):
    def masters(row, tag):
        row.update(home_team_master_id=f"home-{tag}", away_team_master_id=f"away-{tag}")
        return row

    a = masters(_stored("a", 2, 0, "1", "2"), "a")
    b = masters(_stored("b", 2, 0, "3", "4"), "b")
    c = masters(_stored("c", 1, 1, "5", "6"), "c")
    d = masters(_stored("d", 2, 0, "7", "8"), "d")
    stale_h, twin_h = (
        masters(_stored("stale-h", 2, 0, "9", "10"), "h"),
        masters(_stored("twin-h", 3, 0, "9", "10"), "h"),
    )
    stale_r, twin_r = (
        masters(_stored("stale-r", 2, 0, "11", "12"), "r"),
        masters(_stored("twin-r", 3, 0, "11", "12"), "r"),
    )
    bystander = masters(
        _stored("bystander", 2, 0, "g1", "g2", provider="prov-gotsport", source="https://example.com/g"), "r"
    )
    db = _DB([a, b, c, d, stale_h, twin_h, stale_r, twin_r, bystander])
    _after_first_read(monkeypatch, lambda: b.update(home_score=5))
    live = _live(
        ("1", "2", 3, 0), ("3", "4", 3, 0), ("5", "6", 0, 2), ("7", "8", 3, 0), ("9", "10", 3, 0), ("11", "12", 3, 0)
    )
    previous = _confirmed(
        tmp_path, ("a", (2, 0), (3, 0)), ("b", (2, 0), (3, 0)), ("stale-h", (2, 0), (3, 0)), ("stale-r", (2, 0), (3, 0))
    )

    _run_main(
        monkeypatch,
        db,
        {EVENT: live},
        ["--since", DATE, "--execute", "--out", str(tmp_path / "log.json"), "--snapshot-in", previous],
    )

    out = capsys.readouterr().out
    got = {name: _grep_tail(pattern, out) for name, pattern in _workflow_greps().items()}
    assert got == {
        "CORRECTED": "1",
        "HID": "1",
        "REFUSED": "1",
        "WAITING": "1",
        "HELD": "1",
        "SKIPPED": "1",
        "FAILED": "0",
    }
