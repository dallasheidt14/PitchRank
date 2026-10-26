"""Tests for the vetted-merge applier's refusals: pairs the owner kept apart, and pairs whose teams
changed after the list was built; and for --revert, which undoes a log's merges.

The double applies a merge or a revert only at execute(), refuses a merge that names a deprecated
row as the real RPC does, and raises PGRST205 for a table it was not given, as PostgREST does for a
table missing from its schema cache. A successful merge or revert raises too, as postgrest-py does:
the real RPCs' success payloads hold a `message` key, which the client reads as an error and wraps
whole. Like the real ones, the merge repoints the merges into the retired team and every alias of
it to the survivor, and the revert restores neither: it moves back only the aliases whose ids the
retired team's games carry, which these fixtures' gameless teams have none of. Either RPC can be set
to lose its reply after committing, as a gateway timeout does. An update applies its filters at
execute() and refuses an .in_() longer than the 100-id URI limit.
"""

import itertools
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from postgrest.exceptions import APIError, generate_default_error_message

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import apply_vetted_team_merges as avtm  # noqa: E402
from tests.unit.test_find_cross_provider_duplicates import _Result  # noqa: E402
from tests.unit.test_team_cleanup_carry_forward import _Writable, _WritableTable  # noqa: E402

LOST_REPLY = RuntimeError("504 Gateway Timeout")

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


def _committed(payload):
    raise APIError(generate_default_error_message(httpx.Response(200, content=json.dumps(payload).encode())))


class _Rpc:
    def __init__(self, db, name, params):
        self._db, self._name, self._params = db, name, params

    def execute(self):
        if self._name == "revert_team_merge":
            return self._revert()
        deprecated, canonical = self._params["p_deprecated_team_id"], self._params["p_canonical_team_id"]
        if deprecated in self._db.unreachable_merges:
            raise LOST_REPLY
        rows = self._db.rows()
        if rows[deprecated]["is_deprecated"] or rows[canonical]["is_deprecated"]:
            return _Result({"success": False, "error": "team is already deprecated"})
        self._db.merged.append((self._name, dict(self._params)))
        rows[deprecated]["is_deprecated"] = True
        merge_map = self._db._tables["team_merge_map"]
        for incoming in merge_map:
            if incoming["canonical_team_id"] == deprecated:
                incoming["canonical_team_id"] = canonical
        for alias in self._db._tables["team_alias_map"]:
            if alias["team_id_master"] == deprecated:
                alias["team_id_master"] = canonical
        map_id = f"m{next(self._db.map_ids)}"
        merge_map.append(
            {
                "id": map_id,
                "deprecated_team_id": deprecated,
                "canonical_team_id": canonical,
                "merged_by": self._params["p_merged_by"],
            }
        )
        if self._db.after_merge:
            self._db.after_merge(self._db)
        if deprecated in self._db.lost_merge_replies:
            raise LOST_REPLY
        _committed({"message": "Team merged", "success": True, "merge_id": map_id})

    def _revert(self):
        merge_map = self._db._tables["team_merge_map"]
        found = [m for m in merge_map if m["id"] == self._params["p_merge_id"]]
        if not found or self._params["p_merge_id"] in self._db.failing_reverts:
            return _Result({"success": False, "error": f"Merge {self._params['p_merge_id']} not found"})
        self._db.reverted.append(dict(self._params))
        merge_map.remove(found[0])
        if not self._db.revert_leaves_deprecated:
            self._db.rows()[found[0]["deprecated_team_id"]]["is_deprecated"] = False
        if self._params["p_merge_id"] in self._db.lost_revert_replies:
            self._db.lost_revert_replies.discard(self._params["p_merge_id"])
            raise LOST_REPLY
        _committed({"message": "Successfully reverted", "success": True})


class _Update(_WritableTable):
    """An update, matched by the read double's own filters and applied at execute(). On team_merge_map it
    refuses what the check_merge_chains trigger (prevent_merge_chains) refuses: a row pointing at
    a team that is itself merged away or deprecated, or retiring a team others are merged into."""

    def __init__(self, name, rows, cap, log, values, db):
        super().__init__(name, rows, cap, log)
        self._values, self._db = values, db

    def execute(self):
        rows = self._matching()
        if self.name == "team_merge_map":
            for r in rows:
                self._db.check_merge_chains({**r, **self._values})
        for r in rows:
            r.update(self._values)
        self._log.append((self.name, dict(self._values), [r["id"] for r in rows]))
        return _Result([dict(r) for r in rows])


class _MergeTable(_WritableTable):
    def __init__(self, name, rows, cap, log, db):
        super().__init__(name, rows, cap, log)
        self._db = db

    def update(self, values):
        return _Update(self.name, self._rows, self._cap, self._db.updated, values, self._db)


class _MergeDb(_Writable):
    """`after_merge` runs once a merge has committed, before its reply returns -- another writer acting
    mid-batch, a read failing, or the run being stopped -- and `unreadable` maps a table to the error
    reading it raises. `unreachable_merges` names retired teams
    whose merge never reaches the database and `lost_merge_replies` those whose merge commits but whose
    reply is lost; `failing_reverts` names merge rows whose revert the RPC refuses, `lost_revert_replies`
    those whose revert commits once with its reply lost, and `revert_leaves_deprecated` makes it answer
    success while leaving the team deprecated."""

    def __init__(self, teams, *, merge_map=(), decisions=(), aliases=(), with_decisions=True, after_merge=None):
        tables = {"teams": list(teams), "team_merge_map": list(merge_map), "team_alias_map": list(aliases)}
        if with_decisions:
            tables["team_cleanup_decisions"] = list(decisions)
        super().__init__(tables)
        self.merged, self.reverted, self.updated = [], [], []
        self.after_merge = after_merge
        self.unreadable = {}
        self.unreachable_merges, self.lost_merge_replies = set(), set()
        self.failing_reverts, self.lost_revert_replies = set(), set()
        self.revert_leaves_deprecated = False
        # A merge row's id is a fresh uuid in production, so one is never reused after a revert.
        self.map_ids = itertools.count(len(merge_map))

    def rows(self):
        return {t["team_id_master"]: t for t in self._tables["teams"]}

    def check_merge_chains(self, new):
        merge_map, teams = self._tables["team_merge_map"], self.rows()
        if any(m["deprecated_team_id"] == new["canonical_team_id"] for m in merge_map):
            raise RuntimeError(f"Cannot merge into team {new['canonical_team_id']} (check_merge_chains rule 1)")
        if any(m["canonical_team_id"] == new["deprecated_team_id"] for m in merge_map):
            raise RuntimeError(f"Cannot deprecate team {new['deprecated_team_id']} (check_merge_chains rule 2)")
        if teams[new["canonical_team_id"]]["is_deprecated"]:
            raise RuntimeError(f"Cannot merge into deprecated team {new['canonical_team_id']} (check_merge_chains)")

    def table(self, name):
        if name in self.unreadable:
            raise self.unreadable[name]
        super().table(name)
        return _MergeTable(name, self._tables[name], self._cap, self.inserted, self)

    def rpc(self, name, params):
        return _Rpc(self, name, params)


def run(tmp_path, monkeypatch, db, pairs, *flags, out="log.json"):
    vetted = tmp_path / "vetted.json"
    vetted.write_text(json.dumps(pairs), encoding="utf-8")
    monkeypatch.setattr(avtm, "get_client", lambda: db)
    argv = ["prog", "--file", str(vetted), "--out", str(tmp_path / out), *flags]
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
    log = tmp_path / "log.json"
    assert f"To undo: python scripts/apply_vetted_team_merges.py --revert {log}  (a dry run; add --execute)" in out
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


# --- the log --revert replays ------------------------------------------------------------------

RUN_ACTOR = "team-cleanup:2026-10-28-all"


def alias(alias_id, team_id):
    return {"id": alias_id, "team_id_master": team_id, "provider_id": "prov-gs", "provider_team_id": alias_id}


def aliases_of(db):
    return {a["id"]: a["team_id_master"] for a in db._tables["team_alias_map"]}


def run_revert(tmp_path, monkeypatch, db, *flags, out="reverts.json"):
    monkeypatch.setattr(avtm, "get_client", lambda: db)
    argv = ["prog", "--revert", str(tmp_path / "log.json"), "--out", str(tmp_path / out), *flags]
    monkeypatch.setattr(sys, "argv", argv)
    return avtm.main()


def applied(tmp_path, monkeypatch, db, pairs, *flags, code=0):
    assert run(tmp_path, monkeypatch, db, pairs, "--execute", "--actor", RUN_ACTOR, *flags) == code
    return json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))


def outcomes(tmp_path, out="reverts.json"):
    return [e["outcome"] for e in json.loads((tmp_path / out).read_text(encoding="utf-8"))]


def earlier_merge(into):
    return {"id": "m-earlier", "deprecated_team_id": EARLIER, "canonical_team_id": into, "merged_by": "pitchrank-bot"}


NOTHING_POINTED_BACK = "reverted, with 0 merge(s) into it and 0 alias row(s) pointed back"


def test_a_merge_is_recorded_as_the_actor_and_logs_what_it_repoints(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    aliases = [alias("al-1", GONE), alias("al-2", GONE), alias("al-3", KEPT)]
    db = _MergeDb(teams, merge_map=[earlier_merge(GONE)], aliases=aliases)
    log = applied(tmp_path, monkeypatch, db, pairs)
    assert [params["p_merged_by"] for _, params in db.merged] == [RUN_ACTOR, RUN_ACTOR]
    assert [(e["merge_id"], e["merged_by"], e["map_id"], e["alias_ids"], e["incoming_ids"]) for e in log] == [
        (GONE, RUN_ACTOR, "m1", ["al-1", "al-2"], ["m-earlier"]),
        (OTHER_GONE, RUN_ACTOR, "m2", [], []),
    ]


def test_each_merge_is_logged_before_it_is_sent(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    seen = []

    def read_log(db):
        seen.append([e["result"] for e in json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))])

    db = _MergeDb(teams, after_merge=read_log)
    applied(tmp_path, monkeypatch, db, pairs)
    recovered = {"success": True, "note": "recovered from postgrest-py's message-key error"}
    assert seen == [[{"pending": True}], [recovered, {"pending": True}]]


def test_an_existing_log_is_never_overwritten(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs[:1])
    before = (tmp_path / "log.json").read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        run(tmp_path, monkeypatch, db, pairs[1:], "--execute")
    assert (tmp_path / "log.json").read_text(encoding="utf-8") == before
    assert merged_pairs(db) == [(GONE, KEPT)]


def test_an_existing_revert_log_is_never_overwritten(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs)
    (tmp_path / "reverts.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="already exists"):
        run_revert(tmp_path, monkeypatch, db, "--execute")
    assert db.reverted == []


def test_a_merge_whose_reply_is_lost_is_logged_from_its_merge_row(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    db.lost_merge_replies = {GONE}
    log = applied(tmp_path, monkeypatch, db, pairs)
    assert (log[0]["map_id"], log[0]["result"]["success"]) == ("m0", True)
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert db.rows()[GONE]["is_deprecated"] is False


def test_a_merge_that_never_reached_the_database_is_logged_as_failed(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    db.unreachable_merges = {GONE}
    log = applied(tmp_path, monkeypatch, db, pairs, code=1)
    assert (log[0]["map_id"], log[0]["result"]) == (None, {"success": False, "error": "504 Gateway Timeout"})
    assert "FAILED 'Team aaaa' -> 'Team bbbb': 504 Gateway Timeout" in capsys.readouterr().out
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert outcomes(tmp_path) == [NOTHING_POINTED_BACK, "nothing of this run's to revert"]


UNSETTLED = "its merge may have committed, but its run never read back a merge row; settle {} by hand"


def test_a_merge_whose_row_was_not_read_back_stops_the_revert(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()

    def unreadable(db):
        db.unreadable["team_merge_map"] = RuntimeError("502 Bad Gateway")

    db = _MergeDb(teams, after_merge=unreadable)
    log = applied(tmp_path, monkeypatch, db, pairs[:1])
    assert (log[0]["map_id"], log[0]["map_read"], log[0]["result"]["success"]) == (None, False, True)
    db.unreadable = {}
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert db.reverted == []
    assert UNSETTLED.format(GONE) in capsys.readouterr().out


def test_a_merge_cut_off_before_its_log_entry_was_finished_stops_the_revert(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()

    def killed(db):
        raise KeyboardInterrupt

    db = _MergeDb(teams, after_merge=killed)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, monkeypatch, db, pairs, "--execute", "--actor", RUN_ACTOR)
    log = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert [entry["result"] for entry in log] == [{"pending": True}]
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert db.reverted == []
    assert UNSETTLED.format(GONE) in capsys.readouterr().out


def test_a_merge_row_another_actor_wrote_is_left_alone_by_the_revert(tmp_path, monkeypatch):
    teams, pairs = two_pairs()

    def someone_else(db):
        db._tables["team_merge_map"][-1]["merged_by"] = "pitchrank-bot"

    db = _MergeDb(teams, after_merge=someone_else)
    log = applied(tmp_path, monkeypatch, db, pairs, "--limit", "1")
    assert log[0]["map_id"] is None
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert db.reverted == []
    assert outcomes(tmp_path) == ["nothing of this run's to revert"]


def test_revert_undoes_the_newest_merge_first_as_the_merges_actor(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs)
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert db.reverted == [
        {"p_merge_id": "m1", "p_reverted_by": f"{RUN_ACTOR}:revert", "p_revert_reason": avtm.REVERT_REASON},
        {"p_merge_id": "m0", "p_reverted_by": f"{RUN_ACTOR}:revert", "p_revert_reason": avtm.REVERT_REASON},
    ]
    assert {tid: t["is_deprecated"] for tid, t in db.rows().items()} == {
        GONE: False,
        KEPT: False,
        OTHER_GONE: False,
        OTHER_KEPT: False,
    }
    assert outcomes(tmp_path) == [NOTHING_POINTED_BACK, NOTHING_POINTED_BACK]


def test_revert_unwinds_a_chain_merged_in_one_log(tmp_path, monkeypatch):
    teams, _ = two_pairs()
    db = _MergeDb(teams, aliases=[alias("al-gone", GONE), alias("al-kept", KEPT)])
    applied(tmp_path, monkeypatch, db, [pair(GONE, KEPT), pair(KEPT, OTHER_KEPT)])
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert aliases_of(db) == {"al-gone": GONE, "al-kept": KEPT}
    assert db._tables["team_merge_map"] == []
    assert [tid for tid, t in db.rows().items() if t["is_deprecated"]] == []


def test_revert_points_an_earlier_merge_into_the_retired_team_back_at_it(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True))
    db = _MergeDb(teams, merge_map=[earlier_merge(GONE)], aliases=[alias("al-earlier", GONE)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    assert db._tables["team_merge_map"][0]["canonical_team_id"] == KEPT
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert db._tables["team_merge_map"] == [earlier_merge(GONE)]
    assert aliases_of(db) == {"al-earlier": GONE}
    assert outcomes(tmp_path) == ["reverted, with 1 merge(s) into it and 1 alias row(s) pointed back"]


def test_revert_finds_the_aliases_where_a_later_merge_of_the_survivor_moved_them(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, aliases=[alias("al-gone", GONE), alias("al-kept", KEPT)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    later = run(tmp_path, monkeypatch, db, [pair(KEPT, OTHER_KEPT)], "--execute", out="later.json")
    assert later == 0
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert aliases_of(db) == {"al-gone": GONE, "al-kept": OTHER_KEPT}
    assert outcomes(tmp_path) == ["reverted, with 0 merge(s) into it and 1 alias row(s) pointed back"]


def test_a_replayed_revert_leaves_a_team_merged_again_since_alone(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, aliases=[alias("al-1", GONE)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert run(tmp_path, monkeypatch, db, pairs[:1], "--execute", out="again.json") == 0
    capsys.readouterr()
    assert run_revert(tmp_path, monkeypatch, db, "--execute", out="reverts-again.json") == 0
    assert outcomes(tmp_path, "reverts-again.json") == ["already reverted, and merged again since; left as it is"]
    assert aliases_of(db) == {"al-1": KEPT}
    assert db.rows()[GONE]["is_deprecated"] is True


def test_revert_points_back_only_the_aliases_the_merge_moved_that_are_still_on_the_survivor(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, aliases=[alias("al-1", GONE), alias("al-2", GONE), alias("al-3", KEPT)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    db._tables["team_alias_map"][1]["team_id_master"] = OTHER_KEPT
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    assert aliases_of(db) == {"al-1": GONE, "al-2": OTHER_KEPT, "al-3": KEPT}


def test_a_revert_whose_reply_is_lost_is_complete_on_the_rerun(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True))
    db = _MergeDb(teams, merge_map=[earlier_merge(GONE)], aliases=[alias("al-1", GONE)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    db.lost_revert_replies = {"m1"}
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert run_revert(tmp_path, monkeypatch, db, "--execute", out="reverts-again.json") == 0
    assert outcomes(tmp_path, "reverts-again.json") == [
        "already reverted, with 1 merge(s) into it and 1 alias row(s) pointed back"
    ]
    assert db._tables["team_merge_map"] == [earlier_merge(GONE)]
    assert aliases_of(db) == {"al-1": GONE}
    assert db.rows()[GONE]["is_deprecated"] is False


def test_a_resumed_revert_finds_the_aliases_where_a_later_merge_of_the_survivor_moved_them(tmp_path, monkeypatch):
    teams, pairs = two_pairs()
    db = _MergeDb(teams, aliases=[alias("al-gone", GONE)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    assert run(tmp_path, monkeypatch, db, [pair(KEPT, OTHER_KEPT)], "--execute", out="later.json") == 0
    db.lost_revert_replies = {"m0"}
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert run_revert(tmp_path, monkeypatch, db, "--execute", out="reverts-again.json") == 0
    assert aliases_of(db) == {"al-gone": GONE}


def test_a_dry_run_revert_writes_nothing(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True))
    db = _MergeDb(teams, merge_map=[earlier_merge(GONE)], aliases=[alias("al-1", GONE)])
    applied(tmp_path, monkeypatch, db, pairs)
    assert run_revert(tmp_path, monkeypatch, db) == 0
    assert (db.reverted, db.updated) == ([], [])
    assert not (tmp_path / "reverts.json").exists()
    assert "would revert it, then point back 1 merge(s) into it and 1 alias row(s)" in capsys.readouterr().out


def test_a_dry_run_after_a_lost_revert_reply_would_only_point_back(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    teams.append(team(EARLIER, is_deprecated=True))
    db = _MergeDb(teams, merge_map=[earlier_merge(GONE)], aliases=[alias("al-1", GONE)])
    applied(tmp_path, monkeypatch, db, pairs[:1])
    db.lost_revert_replies = {"m1"}
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    capsys.readouterr()
    assert run_revert(tmp_path, monkeypatch, db) == 0
    assert db.updated == []
    assert "already reverted; would point back 1 merge(s) into it and 1 alias row(s)" in capsys.readouterr().out


def test_a_log_write_cut_off_leaves_the_previous_copy(tmp_path, monkeypatch):
    path = tmp_path / "log.json"
    avtm.write_log(path, [{"merge_id": GONE}])
    real_write = Path.write_text

    def cut_off(self, text, *args, **kwargs):
        real_write(self, text[: len(text) // 2], *args, **kwargs)
        raise OSError("the run was stopped")

    monkeypatch.setattr(Path, "write_text", cut_off)
    with pytest.raises(OSError):
        avtm.write_log(path, [{"merge_id": GONE}, {"merge_id": OTHER_GONE}])
    monkeypatch.undo()
    assert json.loads(path.read_text(encoding="utf-8")) == [{"merge_id": GONE}]


def test_a_replayed_revert_sends_no_second_revert(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs)
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 0
    capsys.readouterr()
    assert run_revert(tmp_path, monkeypatch, db, "--execute", out="reverts-again.json") == 0
    assert len(db.reverted) == 2
    assert capsys.readouterr().out.count(": already reverted") == 2


def test_revert_stops_at_the_first_failure_and_leaves_the_earlier_merges(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs)
    db.failing_reverts = {"m1"}
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert db.reverted == []
    assert db.rows()[GONE]["is_deprecated"] is True
    assert "revert_team_merge failed: Merge m1 not found" in capsys.readouterr().out
    assert outcomes(tmp_path) == ["revert_team_merge failed: Merge m1 not found"]


def test_a_revert_the_database_does_not_show_is_a_failure(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs[:1])
    db.revert_leaves_deprecated = True
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert "still deprecated after revert_team_merge answered success" in capsys.readouterr().out


def test_a_merge_row_that_retires_another_team_is_not_reverted(tmp_path, monkeypatch, capsys):
    teams, pairs = two_pairs()
    db = _MergeDb(teams)
    applied(tmp_path, monkeypatch, db, pairs[:1])
    db._tables["team_merge_map"][0]["deprecated_team_id"] = OTHER_GONE
    assert run_revert(tmp_path, monkeypatch, db, "--execute") == 1
    assert db.reverted == []
    assert "team_merge_map row m0 retires another team" in capsys.readouterr().out


def test_a_log_from_before_revert_existed_is_refused(tmp_path, monkeypatch, capsys):
    teams, _ = two_pairs()
    entry = {**{key: pair(GONE, KEPT)[key] for key in avtm.LOGGED}, "result": {"success": True}}
    (tmp_path / "log.json").write_text(json.dumps([entry]), encoding="utf-8")
    assert run_revert(tmp_path, monkeypatch, _MergeDb(teams)) == 1
    assert "the log predates --revert and records no merge row to undo" in capsys.readouterr().out


@pytest.mark.parametrize("flags", [["--limit", "1"], ["--actor", RUN_ACTOR]])
def test_revert_takes_neither_a_limit_nor_an_actor(tmp_path, monkeypatch, flags):
    with pytest.raises(SystemExit):
        run_revert(tmp_path, monkeypatch, _MergeDb([]), *flags)
