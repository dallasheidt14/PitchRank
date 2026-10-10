"""Tests for the vetted-merge applier's refusals: pairs the owner kept apart, and pairs whose teams
changed after the list was built.

The double applies a merge only at execute(), refuses one that names a deprecated row as the
real RPC does, and raises PGRST205 for a table it was not given, as PostgREST does for a table
missing from its schema cache. A successful merge raises too, as postgrest-py does: the real RPC's
success payload holds a `message` key, which the client reads as an error and wraps whole.
"""

import json
import os
import sys

import httpx
import pytest
from postgrest.exceptions import APIError, generate_default_error_message

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import apply_vetted_team_merges as avtm  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import _Result  # noqa: E402
from tests.unit.test_team_cleanup_carry_forward import _Writable  # noqa: E402

GONE, KEPT = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"
OTHER_GONE, OTHER_KEPT = "cccccccc-0000-4000-8000-000000000003", "dddddddd-0000-4000-8000-000000000004"
EARLIER = "eeeeeeee-0000-4000-8000-000000000005"

AS_VETTED = {"age_group": "u12", "gender": "Male", "state_code": "CO", "club_name": "Colorado EDGE"}
CHANGED = {"age_group": "u13", "gender": "Female", "state_code": "WY", "club_name": "Edge FC"}


def team(tid, **changes):
    return {"team_id_master": tid, "team_name": f"Team {tid[:4]}", "is_deprecated": False, **AS_VETTED, **changes}


def pair(merge_id, keep_id, **stamps):
    return {
        "merge_id": merge_id, "keep_id": keep_id,
        "merge_name": f"Team {merge_id[:4]}", "keep_name": f"Team {keep_id[:4]}",
        "merge_as_vetted": dict(AS_VETTED), "keep_as_vetted": dict(AS_VETTED), **stamps,
    }


def keep_separate(team_id, other_team_id, superseded_at=None):
    return {
        "id": f"d-{team_id[:4]}-{other_team_id[:4]}", "team_id_master": team_id, "other_team_id": other_team_id,
        "decision": "keep_separate", "decided_at": "2026-09-24T00:00:00+00:00", "superseded_at": superseded_at,
    }


class _Rpc:
    def __init__(self, db, name, params):
        self._db, self._name, self._params = db, name, params

    def execute(self):
        deprecated, canonical = self._params["p_deprecated_team_id"], self._params["p_canonical_team_id"]
        rows = self._db.rows()
        if rows[deprecated]["is_deprecated"] or rows[canonical]["is_deprecated"]:
            return _Result({"success": False, "error": "team is already deprecated"})
        self._db.merged.append((self._name, dict(self._params)))
        rows[deprecated]["is_deprecated"] = True
        merge_map = self._db._tables["team_merge_map"]
        merge_map.append({"id": f"m{len(merge_map)}", "deprecated_team_id": deprecated, "canonical_team_id": canonical})
        if self._db.after_merge:
            self._db.after_merge(self._db)
        payload = {"message": "Team merged", "success": True, "merge_id": f"m{len(merge_map)}"}
        raise APIError(generate_default_error_message(httpx.Response(200, content=json.dumps(payload).encode())))


class _MergeDb(_Writable):
    """`after_merge` stands in for another writer acting between two of the batch's merges, and
    `unreadable` maps a table to the error reading it raises."""

    def __init__(self, teams, *, merge_map=(), decisions=(), with_decisions=True, after_merge=None):
        tables = {"teams": list(teams), "team_merge_map": list(merge_map)}
        if with_decisions:
            tables["team_cleanup_decisions"] = list(decisions)
        super().__init__(tables)
        self.merged = []
        self.after_merge = after_merge
        self.unreadable = {}

    def rows(self):
        return {t["team_id_master"]: t for t in self._tables["teams"]}

    def table(self, name):
        if name in self.unreadable:
            raise self.unreadable[name]
        return super().table(name)

    def rpc(self, name, params):
        return _Rpc(self, name, params)


def run(tmp_path, monkeypatch, db, pairs, *flags):
    vetted = tmp_path / "vetted.json"
    vetted.write_text(json.dumps(pairs), encoding="utf-8")
    monkeypatch.setattr(avtm, "get_client", lambda: db)
    argv = ["prog", "--file", str(vetted), "--out", str(tmp_path / "log.json"), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    return avtm.main()


def merged_pairs(db):
    return [(params["p_deprecated_team_id"], params["p_canonical_team_id"]) for _, params in db.merged]


def two_pairs():
    teams = [team(GONE), team(KEPT), team(OTHER_GONE), team(OTHER_KEPT)]
    return teams, [pair(GONE, KEPT), pair(OTHER_GONE, OTHER_KEPT)]


def test_unchanged_pairs_merge_as_the_operator(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    out = capsys.readouterr().out
    assert "Done: 2 merged, 0 failed, 0 refused" in out
    assert "revert_fuzzy_auto_merges.py --dry-run --since <today> --merged-by pitchrank-operator" in out
    assert db.merged == [
        ("execute_team_merge", {
            "p_deprecated_team_id": GONE, "p_canonical_team_id": KEPT,
            "p_merged_by": "pitchrank-operator", "p_merge_reason": avtm.MERGE_REASON,
        }),
        ("execute_team_merge", {
            "p_deprecated_team_id": OTHER_GONE, "p_canonical_team_id": OTHER_KEPT,
            "p_merged_by": "pitchrank-operator", "p_merge_reason": avtm.MERGE_REASON,
        }),
    ]


def test_a_dry_run_merges_nothing(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs) == 0
    assert db.merged == []
    assert "would merge 2 pairs" in capsys.readouterr().out


# --- the owner's Keep separate ---------------------------------------------------------------


def test_a_pair_the_owner_kept_apart_is_not_merged(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, decisions=[keep_separate(KEPT, GONE)])
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, OTHER_KEPT)]
    assert "SKIP (the owner chose Keep separate on 2026-09-24)" in capsys.readouterr().out


def test_a_keep_separate_holds_after_one_of_its_teams_was_merged_elsewhere(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True))
    merge_map = [{"id": "m0", "deprecated_team_id": EARLIER, "canonical_team_id": KEPT}]
    db = _MergeDb(teams, merge_map=merge_map, decisions=[keep_separate(GONE, EARLIER)])
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, OTHER_KEPT)]


@pytest.mark.parametrize("second", [(OTHER_GONE, KEPT), (KEPT, OTHER_GONE)], ids=["both-into-one", "chain"])
def test_two_merges_that_would_join_a_kept_apart_pair_through_a_third_row_stop_at_the_second(
    tmp_path, monkeypatch, capsys, second
):
    teams, _ = two_pairs()
    pairs = [pair(GONE, KEPT), pair(*second)]
    db = _MergeDb(teams, decisions=[keep_separate(GONE, OTHER_GONE)])
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT)]
    assert "SKIP (the owner chose Keep separate on 2026-09-24)" in capsys.readouterr().out


def test_a_chain_of_three_merges_stops_before_joining_its_kept_apart_ends(tmp_path, monkeypatch):
    teams, _ = two_pairs()
    pairs = [pair(GONE, KEPT), pair(KEPT, OTHER_GONE), pair(OTHER_GONE, OTHER_KEPT)]
    db = _MergeDb(teams, decisions=[keep_separate(GONE, OTHER_KEPT)])
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT), (KEPT, OTHER_GONE)]


def test_three_merges_into_one_row_stop_before_joining_the_first_and_third(tmp_path, monkeypatch):
    teams, _ = two_pairs()
    pairs = [pair(GONE, OTHER_KEPT), pair(KEPT, OTHER_KEPT), pair(OTHER_GONE, OTHER_KEPT)]
    db = _MergeDb(teams, decisions=[keep_separate(GONE, OTHER_GONE)])
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, OTHER_KEPT), (KEPT, OTHER_KEPT)]


def test_a_team_claimed_by_two_merges_stays_unmerged_when_the_owner_kept_one_claim_apart(tmp_path, monkeypatch):
    teams, _ = two_pairs()
    db = _MergeDb(teams, decisions=[keep_separate(GONE, OTHER_KEPT)])
    assert run(tmp_path, monkeypatch, db, [pair(GONE, KEPT), pair(GONE, OTHER_KEPT)], "--execute") == 0
    assert db.merged == []


def test_a_superseded_keep_separate_no_longer_refuses(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, decisions=[keep_separate(GONE, KEPT, superseded_at="2026-10-01T00:00:00+00:00")])
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT), (OTHER_GONE, OTHER_KEPT)]


def test_nothing_merges_while_the_decisions_cannot_be_read(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, with_decisions=False)
    with pytest.raises(SystemExit, match="Merges wait until the owner's Keep-separate decisions can be read"):
        run(tmp_path, monkeypatch, db, pairs, "--execute")
    assert db.merged == []


def test_nothing_merges_when_reading_the_decisions_fails_for_any_other_reason(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, decisions=[keep_separate(GONE, KEPT)])
    db.unreadable["team_cleanup_decisions"] = RuntimeError("canceling statement due to statement timeout")
    with pytest.raises(SystemExit, match="Merges wait until the owner's Keep-separate decisions can be read"):
        run(tmp_path, monkeypatch, db, pairs, "--execute")
    assert db.merged == []


# --- teams changed since the list was built --------------------------------------------------


@pytest.mark.parametrize("side", ["merge", "keep"])
@pytest.mark.parametrize("field", ["age_group", "gender", "state_code", "club_name"])
def test_a_change_to_any_one_field_on_either_team_refuses_the_pair(tmp_path, monkeypatch, capsys, side, field):
    teams, pairs = two_pairs()
    teams[0 if side == "merge" else 1][field] = CHANGED[field]
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, OTHER_KEPT)]
    assert f"changed since it was vetted: {side} {field} {AS_VETTED[field]!r} -> {CHANGED[field]!r}" in (
        capsys.readouterr().out
    )


def test_a_blank_filled_since_the_list_was_built_counts_as_a_change(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    pairs[0]["keep_as_vetted"]["state_code"] = None
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, OTHER_KEPT)]


@pytest.mark.parametrize("missing", ["merge_as_vetted", "keep_as_vetted"])
def test_a_pair_that_records_nothing_about_its_teams_is_refused(tmp_path, monkeypatch, capsys, missing):
    teams, pairs = two_pairs()
    del pairs[0][missing]
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, OTHER_KEPT)]
    assert "the list does not record the teams as they were vetted" in capsys.readouterr().out


def test_a_redirected_pair_is_checked_against_the_row_it_now_points_at(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True))
    teams[1]["club_name"] = CHANGED["club_name"]
    merge_map = [{"id": "m0", "deprecated_team_id": EARLIER, "canonical_team_id": KEPT}]
    pairs[0]["keep_id"] = EARLIER
    db = _MergeDb(teams, merge_map=merge_map)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, OTHER_KEPT)]


def test_a_change_made_while_the_batch_runs_refuses_the_later_merge(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()

    def another_writer(db):
        db.rows()[OTHER_KEPT]["club_name"] = CHANGED["club_name"]

    db = _MergeDb(teams, after_merge=another_writer)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT)]
    assert "1 refused by the check before each merge" in capsys.readouterr().out


def test_a_dry_run_names_the_changed_pair_it_would_refuse(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    teams[1]["gender"] = CHANGED["gender"]
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs) == 0
    out = capsys.readouterr().out
    assert "changed since it was vetted: keep gender 'Male' -> 'Female'" in out
    assert "would merge 1 pairs" in out


def test_each_team_is_compared_with_its_own_recorded_values(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    teams[0]["club_name"] = pairs[0]["merge_as_vetted"]["club_name"] = "COLORADO EDGE"
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT), (OTHER_GONE, OTHER_KEPT)]


@pytest.mark.parametrize("gone", ["deprecated", "deleted"])
def test_a_row_gone_while_the_batch_runs_refuses_the_later_merge(tmp_path, monkeypatch, capsys, gone):
    teams, pairs = two_pairs()

    def another_writer(db):
        if gone == "deprecated":
            db.rows()[OTHER_GONE]["is_deprecated"] = True
        else:
            db._tables["teams"].remove(db.rows()[OTHER_GONE])

    db = _MergeDb(teams, after_merge=another_writer)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT)]
    out = capsys.readouterr().out
    assert "SKIP (a row is missing or already deprecated)" in out
    assert "1 refused by the check before each merge" in out


def test_a_failed_read_before_a_merge_refuses_it_and_the_log_is_still_written(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()

    def read_fails(db):
        db.unreadable["teams"] = RuntimeError("502 Bad Gateway")

    db = _MergeDb(teams, after_merge=read_fails)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(GONE, KEPT)]
    assert "SKIP (its rows could not be read again: 502 Bad Gateway)" in capsys.readouterr().out
    assert [entry["merge_id"] for entry in json.loads((tmp_path / "log.json").read_text())] == [GONE]


def test_a_stale_list_is_refused_outright(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    teams[0]["is_deprecated"] = True
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 1
    assert db.merged == []
    assert "REFUSING: 1 pairs are stale" in capsys.readouterr().out


def test_limit_applies_only_the_first_pairs(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    assert run(tmp_path, monkeypatch, db, pairs, "--execute", "--limit", "1") == 0
    assert merged_pairs(db) == [(GONE, KEPT)]


@pytest.mark.parametrize("side", ["merge", "keep"])
@pytest.mark.parametrize("redirected_first", [True, False])
def test_a_pair_redirected_onto_another_keeps_the_copy_that_was_not_redirected(
    tmp_path, monkeypatch, side, redirected_first
):
    teams, _ = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True, state_code=None))
    absorbed_by = OTHER_GONE if side == "merge" else KEPT
    merge_map = [{"id": "m0", "deprecated_team_id": EARLIER, "canonical_team_id": absorbed_by}]
    if side == "merge":
        redirected = pair(EARLIER, KEPT, merge_as_vetted={**AS_VETTED, "state_code": None})
    else:
        redirected = pair(OTHER_GONE, EARLIER, keep_as_vetted={**AS_VETTED, "state_code": None})
    direct = pair(OTHER_GONE, KEPT)
    db = _MergeDb(teams, merge_map=merge_map)
    pairs = [redirected, direct] if redirected_first else [direct, redirected]
    assert run(tmp_path, monkeypatch, db, pairs, "--execute") == 0
    assert merged_pairs(db) == [(OTHER_GONE, KEPT)]


def test_a_list_too_long_for_one_request_is_read_in_batches(tmp_path, monkeypatch, capsys):
    ids = [f"{n:08x}-0000-4000-8000-{n:012x}" for n in range(130)]
    db = _MergeDb([team(tid) for tid in ids])
    assert run(tmp_path, monkeypatch, db, [pair(ids[n], ids[n + 65]) for n in range(65)]) == 0
    assert "would merge 65 pairs" in capsys.readouterr().out


def test_a_file_that_holds_no_list_is_refused(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    with pytest.raises(SystemExit, match="holds no list of pairs"):
        run(tmp_path, monkeypatch, db, {"proposed": pairs, "held": [], "rejected": []}, "--execute")
    assert db.merged == []
