"""Tests for scripts/team_cleanup/undo_card.py: undoing one card's change from an applied lane.

Each stage is applied first through apply_stage.py against the same database double and stand-in appliers
its own tests use, so the undo replays the logs and windows a real apply leaves.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import apply_vetted_team_merges as merger  # noqa: E402
from scripts.team_cleanup import undo_card as uc  # noqa: E402
from scripts.team_cleanup.propose_week import _read_csv  # noqa: E402
from scripts.team_cleanup.run_store import stage_dir  # noqa: E402
from src.tournaments.storage._io import read_json  # noqa: E402
from tests.unit.test_team_cleanup_apply_stage import (  # noqa: E402
    ACTOR,
    MONDAY_MORNING,
    RUN,
    _after_the_windows,
    _applied_states,
    _club_lanes,
    _club_week,
    _decisions,
    _id,
    _ledger,
    _main,
    _merge_week,
    _Runner,
    _wire,
)


def _undo(monkeypatch, capsys, store, card, *argv):
    monkeypatch.setattr(sys, "argv", ["undo_card.py", "--run", RUN, "--card", card, "--store", str(store), *argv])
    code = uc.main()
    return code, capsys.readouterr().out


def _refused(monkeypatch, capsys, store, card, *argv):
    with pytest.raises(SystemExit) as caught:
        _undo(monkeypatch, capsys, store, card, *argv)
    return str(caught.value)


def _wired(monkeypatch, db, runner, **kwargs):
    _wire(monkeypatch, db, runner, **kwargs)
    monkeypatch.setattr(uc, "get_client", lambda: db)
    monkeypatch.setattr(uc, "run_step", runner)


def _card(store, stage, name, lane="cards"):
    """The card id of the team, or for merges the retiring row, named ``name`` on the stage's page."""
    manifest = read_json(stage_dir(store, RUN, stage) / "page.manifest.json")
    team = _id(name)
    for card_id, proposal in manifest[lane].items():
        if proposal.get("merge_id", proposal.get("team_id_master")) == team:
            return card_id
    raise AssertionError(f"no card for {name}")


def _active(db, name):
    return [
        (r["decision"], r["source"])
        for r in _decisions(db)
        if r["team_id_master"] == _id(name) and r["superseded_at"] is None
    ]


def _undone(db):
    return sorted(r["team_id_master"] for r in _ledger(db) if r["reverted_at"])


# --- clubs ---------------------------------------------------------------------------------------------


def _applied_clubs(tmp_path, monkeypatch, capsys, n=3):
    store, db, names = _club_week(tmp_path, n=n)
    runner = _Runner(db)
    _wired(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0
    return store, db, names, runner


def test_a_club_card_s_undo_replays_a_copy_of_its_batch_log_holding_its_team_alone(tmp_path, monkeypatch, capsys):
    store, db, names, runner = _applied_clubs(tmp_path, monkeypatch, capsys)
    card = _card(store, "clubs", "c01")
    applied = len(runner.commands)

    code, out = _undo(monkeypatch, capsys, store, card, "--execute")

    assert code == 0
    assert {n: db.team(_id(n))["club_name"] for n in names} == {"c00": "Club c00", "c01": "LVSA", "c02": "Club c02"}
    command = runner.commands[applied:]
    copy = stage_dir(store, RUN, "clubs") / "undo" / card / Path(runner.commands[0][-1]).name
    assert len(command) == 1 and command[0][:2] == ["scripts/repair_swapped_club_names.py", "--revert"]
    replayed = Path(command[0][2])
    assert replayed.parent == stage_dir(store, RUN, "clubs") / "undo" / card and replayed.name.endswith(".csv")
    assert [row["team_id_master"] for row in _read_csv(replayed)] == [_id("c01")]
    assert _undone(db) == [_id("c01")]
    assert "Stamped reverted_at on 1 ledger row(s)." in out
    assert f"## Undo of card {card}" in (stage_dir(store, RUN, "clubs") / "REVERT.md").read_text(encoding="utf-8")
    assert copy.parent.exists()


def test_a_declined_undo_records_don_t_apply_so_the_change_is_not_proposed_again(tmp_path, monkeypatch, capsys):
    store, db, _, _ = _applied_clubs(tmp_path, monkeypatch, capsys)
    card = _card(store, "clubs", "c01")

    assert _undo(monkeypatch, capsys, store, card, "--decline", "--execute")[0] == 0

    assert _active(db, "c01") == [("dont_apply", f"undo:{card}")]
    assert _active(db, "c00")[0][0] == "apply"


def test_an_automatic_lane_s_card_is_undone_from_that_lane(tmp_path, monkeypatch, capsys):
    store, db = _club_lanes(tmp_path, auto=("a1", "a2"), owner=("o1",))
    runner = _Runner(db)
    _wired(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--execute")[0] == 0

    assert _undo(monkeypatch, capsys, store, _card(store, "clubs", "a1", lane="auto"), "--execute")[0] == 0

    assert {n: db.team(_id(n))["club_name"] for n in ("a1", "a2")} == {"a1": "LVSA", "a2": "Club a2"}
    assert (stage_dir(store, RUN, "clubs") / "auto" / "REVERT.md").exists()


def test_a_card_whose_team_was_changed_again_since_is_reported_not_stamped(tmp_path, monkeypatch, capsys):
    store, db, _, _ = _applied_clubs(tmp_path, monkeypatch, capsys)
    db.team(_id("c01"))["club_name"] = "Renamed Since FC"

    message = _refused(monkeypatch, capsys, store, _card(store, "clubs", "c01"), "--execute")

    assert "does not hold its old value again" in message
    assert db.team(_id("c01"))["club_name"] == "Renamed Since FC" and _undone(db) == []


def test_a_card_already_undone_is_refused(tmp_path, monkeypatch, capsys):
    store, db, _, runner = _applied_clubs(tmp_path, monkeypatch, capsys)
    card = _card(store, "clubs", "c01")
    assert _undo(monkeypatch, capsys, store, card, "--execute")[0] == 0
    ran = len(runner.commands)

    message = _refused(monkeypatch, capsys, store, card, "--execute")

    assert "no change of card" in message and "it is undone" in message and len(runner.commands) == ran


def test_a_card_the_owner_did_not_choose_apply_changed_nothing_and_is_refused(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path, n=2)
    from tests.unit.test_team_cleanup_apply_stage import _choose

    _choose(tmp_path / "again", store, "clubs", {"c00": "apply", "c01": "dont_apply"})
    runner = _Runner(db)
    _wired(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0

    message = _refused(monkeypatch, capsys, store, _card(store, "clubs", "c01"), "--execute")

    assert "was decided dont_apply, so its lane changed nothing for it" in message


def test_a_decline_a_later_decision_would_overturn_refuses_before_undoing_anything(tmp_path, monkeypatch, capsys):
    store, db, _, runner = _applied_clubs(tmp_path, monkeypatch, capsys)
    active = next(r for r in _decisions(db) if r["team_id_master"] == _id("c01") and r["superseded_at"] is None)
    active["decided_at"] = "2099-01-01T00:00:00+00:00"
    ran = len(runner.commands)

    message = _refused(monkeypatch, capsys, store, _card(store, "clubs", "c01"), "--decline", "--execute")

    assert "a later decision is already recorded" in message
    assert len(runner.commands) == ran and db.team(_id("c01"))["club_name"] == "Club c01"


def test_a_card_on_no_page_of_the_run_is_refused(tmp_path, monkeypatch, capsys):
    store, _, _, _ = _applied_clubs(tmp_path, monkeypatch, capsys)

    assert "is on none of run" in _refused(monkeypatch, capsys, store, "nope", "--execute")


def test_a_dry_run_writes_nothing_and_runs_nothing(tmp_path, monkeypatch, capsys):
    store, db, _, runner = _applied_clubs(tmp_path, monkeypatch, capsys)
    card = _card(store, "clubs", "c01")
    ran, writes = len(runner.commands), len(db.writes())

    code, out = _undo(monkeypatch, capsys, store, card, "--decline")

    assert code == 0 and "DRY RUN -- would undo card" in out and "records Don't apply" in out
    assert len(runner.commands) == ran and len(db.writes()) == writes
    assert not (stage_dir(store, RUN, "clubs") / "undo").exists()


def test_an_undo_outside_the_apply_window_is_refused(tmp_path, monkeypatch, capsys):
    store, db, _, runner = _applied_clubs(tmp_path, monkeypatch, capsys)
    _wired(monkeypatch, db, runner, now=MONDAY_MORNING)

    assert "Outside the apply window" in _refused(monkeypatch, capsys, store, _card(store, "clubs", "c01"), "--execute")


# --- merges --------------------------------------------------------------------------------------------


def test_a_merge_card_s_undo_shows_its_own_hidden_games_then_undoes_that_merge_alone(tmp_path, monkeypatch, capsys):
    store, db, names = _merge_week(tmp_path, n=3)
    runner = _Runner(db)
    _wired(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "merges", "--execute")[0] == 0
    card = _card(store, "merges", "m01")
    applied = len(runner.commands)

    assert _undo(monkeypatch, capsys, store, card, "--decline", "--execute")[0] == 0

    assert [db.team(_id(n))["is_deprecated"] for n in names] == [True, False, True]
    assert runner.excluded == {f"doubled-{_id('m00')}", f"doubled-{_id('m02')}"}
    exclusion, merge = runner.commands[applied:]
    assert exclusion[:2] == ["scripts/exclude_merge_duplicate_games.py", "--revert"]
    assert [row["home_team_master_id"] for row in json.loads(Path(exclusion[2]).read_text())["rows"]] == [_id("m01")]
    assert merge[:2] == ["scripts/apply_vetted_team_merges.py", "--revert"] and "--out" in merge
    assert [entry["merge_id"] for entry in merger.read_log(Path(merge[2]))] == [_id("m01")]
    assert _undone(db) == [_id("m01")]
    assert _active(db, "m01") == [("keep_separate", f"undo:{card}")]


def test_an_exclusion_cut_keeps_the_copies_the_trigger_hid_with_the_retired_row_s_games():
    retired, other = "r", "o"
    game = {"game_date": "2026-10-10", "home_team_master_id": retired, "away_team_master_id": "x", "score": "2-1"}
    logged = {
        "applied": True,
        "sent": 2,
        "confirmed": 2,
        "rows": [
            {**game, "id": "g1"},
            {**game, "id": "g2", "home_team_master_id": other},
            # The trigger hid the swapped copy of g1 along with it, and an unrelated game too.
            {**game, "id": "g3", "home_team_master_id": "x", "away_team_master_id": retired, "score": "1-2"},
            {**game, "id": "g4", "home_team_master_id": other, "away_team_master_id": "y"},
        ],
        "reverted_at": "2026-10-11T00:00:00+00:00",
    }

    cut = uc.pair_exclusions(logged, retired)

    assert [row["id"] for row in cut["rows"]] == ["g1", "g3"] and cut["sent"] == 1 and "reverted_at" not in cut


# --- states --------------------------------------------------------------------------------------------


def test_a_state_card_s_undo_puts_back_its_team_alone_after_a_dry_run_names_it(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    _wired(monkeypatch, db, _Runner(db))

    assert _undo(monkeypatch, capsys, store, _card(store, "states", "fix"), "--execute")[0] == 0

    assert {n: db.team(_id(n))["state_code"] for n in ("fill", "fix", "q")} == {"fill": "NV", "fix": "UT", "q": "NV"}
    calls = [e for e in db.executes if e[:2] == ("revert_team_states", "rpc")]
    assert [call[2]["p_dry_run"] for call in calls] == [True, False]
    assert all(call[2]["p_batch_size"] == 1 and call[2]["p_after"] < _id("fix") for call in calls)
    assert {r["applied_by"] for r in db.tables["team_state_audit"] if r["action"] == "revert"} == {f"{ACTOR}:revert"}
    assert _undone(db) == [_id("fix")]


def test_a_state_card_approved_from_the_queue_is_undone_through_its_approval_window(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    _wired(monkeypatch, db, _Runner(db))

    assert _undo(monkeypatch, capsys, store, _card(store, "states", "q"), "--execute")[0] == 0

    assert {n: db.team(_id(n))["state_code"] for n in ("fill", "fix", "q")} == {"fill": "NV", "fix": "NV", "q": "WA"}


def test_a_state_window_holding_another_writer_s_write_to_the_team_is_refused(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys, closed=False)
    db.audit(_id("fix"), "NV", "NV", "assign_team_states", "someone else's", "correct")
    _after_the_windows(monkeypatch)
    _wired(monkeypatch, db, _Runner(db))

    message = _refused(monkeypatch, capsys, store, _card(store, "states", "fix"), "--execute")

    assert "not the stage's own" in message
    assert db.team(_id("fix"))["state_code"] == "NV"


def test_a_state_revert_page_of_one_never_names_another_team():
    assert uc._before("00000000-0000-0000-0000-000000000010") == "00000000-0000-0000-0000-00000000000f"
    assert uc._before("12345678-0000-0000-0001-000000000000") == "12345678-0000-0000-0000-ffffffffffff"


def test_a_state_revert_whose_dry_run_names_another_team_writes_nothing(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    window = ("2000-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00")
    before = [dict(t) for t in db.tables["teams"]]

    with pytest.raises(ValueError, match="would put back"):
        # No write by this actor names the team, so the page of one starting at it names the next team.
        uc.revert_state(db, RUN, _id("nobody"), "assign_team_states", window, "test")

    assert db.tables["teams"] == before
    assert [e[2]["p_dry_run"] for e in db.executes if e[:2] == ("revert_team_states", "rpc")] == [True]
