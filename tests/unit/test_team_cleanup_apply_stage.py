"""Tests for the weekly cleanup's serial applier: its gates, the decisions it records first, the pilot and
rest cut files it runs through each stage's applier, the review-queue cards, the change ledger,
RECORD.md and the undo.

Each stage is built by the real producers (propose_week's proposals, the stage's own CSV or snapshot
writer, collect.py), and each applier is stood in for by `_Runner`, which reads the cut file and writes
its log with the applier's own functions. The database double records each request at execute(), where
the real builder sends it, refuses columns its table lacks, an unordered page, an id list too long for
a URL, a second active decision for one subject, an upsert naming one key twice and an upsert on a
column set no unique index covers; revert_team_states takes only the parameters its newest migration
names and writes nothing in a dry run, as the function does; `lost` raises after a write lands, as a
dropped connection does."""

import inspect
import json
import os
import re
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import yaml

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import assign_team_states as ats  # noqa: E402
from scripts import fix_band_cohorts as bands  # noqa: E402
from scripts import hold_unsafe_state_applies as hold  # noqa: E402
from scripts import repair_swapped_club_names as swapped  # noqa: E402
from scripts.team_cleanup import apply_stage as ap  # noqa: E402
from scripts.team_cleanup import collect as col  # noqa: E402
from scripts.team_cleanup import end_run, status  # noqa: E402
from scripts.team_cleanup import propose_week as pw  # noqa: E402
from scripts.team_cleanup.review_page import TEAM_COLS, card_id  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    APPLY_LOCK_FILE,
    MANIFEST_FILE,
    PAGE_MARKER,
    PREFLIGHT_MARKER,
    PROPOSALS_FILE,
    PROPOSE_MARKER,
    STALE_FILE,
    file_hash,
    run_dir,
    stage_dir,
    stage_progress,
    write_run,
)
from src.tournaments.storage._file_lock import _acquire_file_lock  # noqa: E402
from src.tournaments.storage._io import read_json, write_json  # noqa: E402
from tests.unit import test_team_state_provenance_migration as provenance  # noqa: E402
from tests.unit.test_age_rollover_freeze_coverage import _writing_steps  # noqa: E402
from tests.unit.test_agent_doc_references import TRACKED  # noqa: E402
from tests.unit.test_team_cleanup_run_store import _api_error, _holds_term  # noqa: E402

RUN = "2026-10-14-nv"
PAGE_RUN = "20261014T180000Z-a1b2c3"
BUILT = "2026-10-14T18:00:00+00:00"
CREATED = "2026-10-14T18:00:00.123456+00:00"
ACTOR = "team-cleanup:2026-10-14-nv"
FRIDAY_EVENING = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)  # Friday 18:00 in Arizona
MONDAY_MORNING = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # Monday 08:00 in Arizona, outside the window
REAL_GH_RUNS = ap.gh_runs
REAL_PYTHON_PROCESSES = ap.python_processes


def _id(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


# --- the database double -------------------------------------------------------------------------

COLUMNS = {
    "teams": set(TEAM_COLS.split(",")),
    "team_cleanup_runs": {"run_id", "scope", "status", "budgets", "lease_holder", "lease_expires_at"},
    "team_cleanup_decisions": {
        "id",
        "stage",
        "subject_key",
        "team_id_master",
        "other_team_id",
        "field",
        "proposed_value",
        "decision",
        "note",
        "decided_at",
        "source",
        "superseded_at",
    },
    "team_cleanup_changes": {
        "id",
        "run_id",
        "stage",
        "team_id_master",
        "field",
        "old_value",
        "new_value",
        "applier",
        "actor",
        "log_file",
        "applied_at",
        "reverted_at",
    },
    "team_state_review_queue": {
        "id",
        "team_id_master",
        "current_state_code",
        "proposed_state_code",
        "tier",
        "confidence",
        "reason",
        "status",
        "reviewed_by",
        "reviewed_at",
    },
    "team_state_audit": {
        "id",
        "team_id_master",
        "action",
        "old_state_code",
        "new_state_code",
        "applied_at",
        "applied_by",
        "reason",
    },
}
ROW_CAP = 1000
# The unique indexes an upsert can name as its conflict target: Postgres refuses any other column set.
UNIQUE = {"team_cleanup_changes": {"run_id", "stage", "team_id_master", "field", "new_value"}}


def _instant(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _now():
    return datetime.now(timezone.utc).isoformat()


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table, kind, *, columns=(), payload=None, on_conflict=None):
        rows = payload if isinstance(payload, list) else [payload] if payload else []
        unknown = (set(columns) | {c for row in rows for c in row}) - COLUMNS[table]
        assert not unknown, f"PostgREST refuses unknown columns {table}.{unknown}"
        self._db, self._table, self._kind, self._columns = db, table, kind, list(columns)
        self._payload, self._on_conflict = payload, on_conflict
        self._filters, self._order, self._range, self._limit = [], None, None, None

    def _where(self, column, test):
        assert column in COLUMNS[self._table], f"PostgREST refuses unknown column {self._table}.{column}"
        self._filters.append(lambda row: test(row.get(column)))
        return self

    def eq(self, column, value):
        return self._where(column, lambda x: x == value)

    def neq(self, column, value):
        return self._where(column, lambda x: x != value)

    def in_(self, column, values):
        values = list(values)
        assert len(values) <= 100, "an id list this long overflows the URL"
        return self._where(column, lambda x: x in values)

    def is_(self, column, value):
        assert value == "null", "the double models is.null only"
        return self._where(column, lambda x: x is None)

    def gt(self, column, value):
        return self._where(column, lambda x: x is not None and _instant(x) > _instant(value))

    def gte(self, column, value):
        return self._where(column, lambda x: x is not None and _instant(x) >= _instant(value))

    def lt(self, column, value):
        return self._where(column, lambda x: x is not None and _instant(x) < _instant(value))

    def or_(self, expression):
        terms = [term.split(".", 2) for term in expression.split(",")]
        for column, op, _ in terms:
            assert column in COLUMNS[self._table] and op in ("is", "lt"), f"the double does not model {expression}"
        self._filters.append(lambda row: any(_holds_term(row, *term) for term in terms))
        return self

    def order(self, column):
        assert column in COLUMNS[self._table]
        self._order = column
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, count):
        self._limit = count
        return self

    def execute(self):
        db, key = self._db, (self._table, self._kind)
        db.executes.append((self._table, self._kind, self._payload))
        if key in db.refuse:
            raise db.refuse.pop(key)
        result = self._run()
        for hook in db.hooks.pop(key, []):
            hook(db)
        if key in db.lost:
            raise db.lost.pop(key)
        return _Result(result)

    def _matching(self):
        return [row for row in self._db.tables[self._table] if all(test(row) for test in self._filters)]

    def _run(self):
        rows = self._db.tables[self._table]
        if self._kind == "select":
            assert self._order or self._range is None, "a page with no order is arbitrary"
            found = sorted(self._matching(), key=lambda r: r[self._order]) if self._order else self._matching()
            if self._range:
                found = found[self._range[0] : self._range[1] + 1]
            return [{c: r.get(c) for c in self._columns} for r in found[: min(ROW_CAP, self._limit or ROW_CAP)]]
        if self._kind == "update":
            matched = self._matching()
            for row in matched:
                row.update(self._payload)
            return [dict(row) for row in matched]
        if self._kind == "insert":
            return [self._db.insert(self._table, dict(self._payload))]
        keys = self._on_conflict.split(",")
        if set(keys) != UNIQUE.get(self._table):
            raise _api_error(
                "42P10", "there is no unique or exclusion constraint matching the ON CONFLICT specification"
            )
        seen = [tuple(row[k] for k in keys) for row in self._payload]
        if len(seen) != len(set(seen)):
            raise _api_error("21000", "ON CONFLICT DO UPDATE command cannot affect row a second time")
        done = []
        for new in self._payload:
            old = next((r for r in rows if all(r[k] == new[k] for k in keys)), None)
            if old:
                old.update(new)
                done.append(dict(old))
            else:
                done.append(self._db.insert(self._table, dict(new)))
        return done


class _Rpc:
    def __init__(self, db, name, params):
        self._db, self._name, self._params = db, name, params

    def execute(self):
        db, key = self._db, (self._name, "rpc")
        db.executes.append((self._name, "rpc", self._params))
        if key in db.refuse:
            raise db.refuse.pop(key)
        result = getattr(db, f"rpc_{self._name}")(**self._params)
        if key in db.lost:
            raise db.lost.pop(key)
        return _Result(result)


class _Db:
    def __init__(self, teams=(), **tables):
        self.tables = {name: [dict(r) for r in tables.get(name, ())] for name in COLUMNS}
        self.tables["teams"] = [dict(t) for t in teams]
        self.tables["team_cleanup_runs"] = self.tables["team_cleanup_runs"] or [
            {
                "run_id": RUN,
                "scope": {},
                "status": "reviewing",
                "budgets": {},
                "lease_holder": None,
                "lease_expires_at": None,
            }
        ]
        self.executes, self.refuse, self.lost, self.hooks = [], {}, {}, {}
        self.ids = 1000

    def table(self, name):
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, name, "select", columns=[c.strip() for c in columns.split(",")])

            def insert(self, payload):
                return _Query(db, name, "insert", payload=payload)

            def update(self, payload):
                return _Query(db, name, "update", payload=payload)

            def upsert(self, payload, on_conflict):
                return _Query(db, name, "upsert", payload=payload, on_conflict=on_conflict)

        return _T()

    def rpc(self, name, params):
        return _Rpc(self, name, params)

    def insert(self, table, row):
        if table == "team_cleanup_decisions" and any(
            (r["stage"], r["subject_key"]) == (row["stage"], row["subject_key"]) and r["superseded_at"] is None
            for r in self.tables[table]
        ):
            raise _api_error("23505", "duplicate key value violates unique constraint uq_..._active_subject")
        self.ids += 1
        defaults = {
            "team_cleanup_decisions": {"superseded_at": None},
            "team_state_review_queue": {"status": "pending", "reviewed_by": None, "reviewed_at": None},
        }.get(table, {})
        stored = {**defaults, **row, "id": self.ids}
        self.tables[table].append(stored)
        return dict(stored)

    def writes(self):
        return [e for e in self.executes if e[1] != "select"]

    def team(self, team_id):
        return next(t for t in self.tables["teams"] if t["team_id_master"] == team_id)

    def audit(self, team_id, old, new, by, reason, action, at=None):
        self.ids += 1
        row = {"id": self.ids, "team_id_master": team_id, "action": action, "old_state_code": old}
        row.update({"new_state_code": new, "applied_at": at or _now(), "applied_by": by, "reason": reason})
        self.tables["team_state_audit"].append(row)

    def _state_write(self, team_id, expected, new, by, action, reason):
        team = self.team(team_id)
        if (team["state_code"] or None) != expected:
            return False
        team["state_code"] = new
        self.audit(team_id, expected, new, by, reason, action)
        return True

    def rpc_approve_team_state(self, p_review_id, p_approver):
        row = next((r for r in self.tables["team_state_review_queue"] if r["id"] == p_review_id), None)
        if row is None or row["status"] != "pending":
            raise _api_error("P0001", f"State review {p_review_id} not found or already reviewed")
        reason = f"approved review {p_review_id}"
        if not self._state_write(
            row["team_id_master"], row["current_state_code"], row["proposed_state_code"], p_approver, "approve", reason
        ):
            raise _api_error("P0001", f"Team {row['team_id_master']} has moved or gone since review {p_review_id}")
        row.update({"status": "approved", "reviewed_by": p_approver, "reviewed_at": _now()})
        return True

    def rpc_reject_team_state(self, p_review_id, p_reviewer):
        row = next((r for r in self.tables["team_state_review_queue"] if r["id"] == p_review_id), None)
        if row is None or row["status"] != "pending":
            raise _api_error("P0001", f"State review {p_review_id} not found or already reviewed")
        row.update({"status": "rejected", "reviewed_by": p_reviewer, "reviewed_at": _now()})
        return True

    def rpc_revert_team_states(
        self,
        p_applied_by,
        p_applied_after,
        p_applied_before,
        p_reverted_by,
        p_after=None,
        p_batch_size=500,
        p_dry_run=False,
        p_revert_reason=None,
    ):
        batch = sorted(
            (
                r
                for r in self.tables["team_state_audit"]
                if r["applied_by"] == p_applied_by
                and _instant(p_applied_after) <= _instant(r["applied_at"]) < _instant(p_applied_before)
                and r["action"] != "revert"
            ),
            key=lambda r: (r["applied_at"], r["id"]),
        )
        teams = sorted({r["team_id_master"] for r in batch if p_after is None or r["team_id_master"] > p_after})
        teams = teams[:p_batch_size]
        changed = 0
        for team_id in teams:
            rows = [r for r in batch if r["team_id_master"] == team_id]
            if p_dry_run:
                # The function counts the teams it would put back and writes nothing.
                changed += (self.team(team_id)["state_code"] or None) == rows[-1]["new_state_code"]
            elif self._state_write(
                team_id, rows[-1]["new_state_code"], rows[0]["old_state_code"], p_reverted_by, "revert", "undo"
            ):
                changed += 1
        return [{"rows_changed": changed, "last_team_id": teams[-1] if teams else None}]


# --- the appliers, through their own readers and writers ------------------------------------------


def _arg(command, flag):
    return Path(command[command.index(flag) + 1])


class _Runner:
    """Stands in for run_step: records each command and does what the script would to the double,
    reading and writing through the script's own functions. ``codes`` maps a script to its successive
    runs, each None (run it) or an exit code returned without running; ``during`` maps one to a change
    another writer makes once it has run."""

    def __init__(self, db, codes=None, provenance=None, during=None):
        self.db, self.codes, self.provenance, self.during = db, codes or {}, provenance or {}, during or {}
        self.commands, self.at, self.logs = [], [], 0

    def __call__(self, command, log):
        script = Path(command[0]).stem
        self.commands.append(command)
        self.at.append(len(self.db.executes))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"ran {script}\n", encoding="utf-8")
        codes = self.codes.get(script, [])
        code = codes.pop(0) if codes else None
        if code is None:
            code = getattr(self, script)(command, log)
        if script in self.during:
            self.during.pop(script)(self.db)
        return code

    def _log_path(self, command, prefix):
        self.logs += 1
        return _arg(command, "--exports-dir") / f"{prefix}_20261017_0100{self.logs:02d}.csv"

    def repair_swapped_club_names(self, command, log):
        if "--revert" in command:
            for row in pw._read_csv(_arg(command, "--revert")):
                team = self.db.team(row["team_id_master"])
                if row["action"] == "updated" and team["club_name"] == swapped.csv_unsafe(row["after"]):
                    team["club_name"] = swapped.csv_unsafe(row["before"])
            return 0
        rows = [r for r in swapped.load_snapshot(_arg(command, "--execute")) if swapped.is_approved(r)]
        live = {t["team_id_master"]: t["club_name"] for t in self.db.tables["teams"] if not t["is_deprecated"]}
        entries = swapped.plan_replay(rows, live)
        for entry in entries:
            if entry["action"] == "updated":
                self.db.team(entry["team_id_master"])["club_name"] = entry["after"]
        actor = command[command.index("--actor") + 1]
        logged = [swapped.log_row(e, "execute", actor) for e in entries]
        swapped.write_log(logged, self._log_path(command, "repair_swapped_club_names_log"))
        return 0

    def fix_band_cohorts(self, command, log):
        if "--revert" in command:
            for row in bands.read_our_csv(_arg(command, "--revert")):
                team = self.db.team(row["team_id_master"])
                if row["result"] in bands.REVERTABLE and team["age_group"] == row["new_age_group"]:
                    team["age_group"] = row["old_age_group"]
            return 0
        rows = bands.read_our_csv(_arg(command, "--apply"))
        for row in rows:
            held = bands.name_contradiction(row["team_name"], row["new_age_group"])
            row["hold_reason"] = held if "--skip-name-contradictions" in command else ""
            row["actor"] = command[command.index("--actor") + 1]
            team = self.db.team(row["team_id_master"])
            if row["hold_reason"]:
                row["result"] = "held_name_contradicts"
            elif team["age_group"] == row["old_age_group"] and not team["is_deprecated"]:
                team["age_group"] = row["new_age_group"]
                row["result"] = "updated"
            else:
                row["result"] = "skipped_moved"
        bands.write_csv(rows, self._log_path(command, "fix_band_cohorts_apply"), bands.APPLY_LOG_FIELDS)
        return 0

    def hold_unsafe_state_applies(self, command, log):
        snapshot = json.loads(Path(command[1]).read_text(encoding="utf-8"))
        kept, held = hold.split(snapshot["decisions"], self.provenance)
        Path(command[2]).write_text(json.dumps({**snapshot, "decisions": kept}, indent=1), encoding="utf-8")
        Path(command[3]).write_text(json.dumps(held, indent=1), encoding="utf-8")
        return 0

    def assign_team_states(self, command, log):
        snapshot = json.loads(_arg(command, "--snapshot").read_text(encoding="utf-8"))
        if snapshot["rules"] != ap.SNAPSHOT_RULES:
            log.write_text("ERROR: this snapshot was decided under rules 'older'\n", encoding="utf-8")
            return 1
        reason = ats.snapshot_reason(snapshot["created_at"])
        for d in snapshot["decisions"]:
            if d["action"] == "apply":
                kind = "fill" if d["pre_image"] is None else "correct"
                self.db._state_write(d["team_id"], d["pre_image"], d["proposed"], "assign_team_states", kind, reason)
            elif d["action"] == "queue":
                self.db.insert("team_state_review_queue", {"team_id_master": d["team_id"]})
        return 0


# --- a run in review, each stage built and collected by the real producers ------------------------


def _team(name, *, club="Las Vegas Sports Academy", state="NV", age="u12", team_name=None):
    return {
        "team_id_master": _id(name),
        "team_name": team_name or f"Team {name}",
        "team_name_original": None,
        "club_name": club,
        "age_group": age,
        "gender": "Male",
        "state_code": state,
        "provider_id": 1,
        "is_deprecated": False,
    }


def _store(tmp_path):
    store = tmp_path / "store"
    write_run(store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": "reviewing", "budgets": {}, "stages": {}})
    return store


def _page(folder, stage, proposals, auto=()):
    """Stage files as propose_week and pages.py leave them: proposals, a manifest sending the proposals of
    the teams named in ``auto`` to the automatic lane, and page.json's hashes."""
    write_json(folder / PREFLIGHT_MARKER, {"passed": True})
    write_json(folder / PROPOSALS_FILE, proposals, indent=1)
    write_json(folder / STALE_FILE, [], indent=1)
    (folder / PROPOSE_MARKER).write_text("", encoding="utf-8")
    sent = {_id(name) for name in auto}

    def by_card(chosen):
        return {card_id(PAGE_RUN, f"{p['team_id_master']}|{p['field']}|{p['new_value']}"): p for p in chosen}

    cards = by_card(p for p in proposals if p["team_id_master"] not in sent)
    lane = by_card(p for p in proposals if p["team_id_master"] in sent)
    manifest = {"run": PAGE_RUN, "cleanup_run": RUN, "stage": stage, "cards": cards, "auto": lane}
    write_json(folder / MANIFEST_FILE, manifest, indent=1)
    names = (PROPOSALS_FILE, pw.APPLIER_INPUTS[stage], MANIFEST_FILE)
    marker = {"run": PAGE_RUN, "auto": len(lane), "hashes": {n: file_hash(folder / n) for n in names}}
    write_json(folder / PAGE_MARKER, marker, indent=1)


def _choose(tmp_path, store, stage, picks):
    """Save the owner's choices as the page does, picks keyed by team name, and collect them, and the
    automatic lane's changes too when the page sent it some."""
    folder = stage_dir(store, RUN, stage)
    manifest = read_json(folder / MANIFEST_FILE)
    if manifest["auto"]:
        col.collect(store, RUN, stage, None, "auto")
    out = tmp_path / "out" / stage
    saved = out / f"decisions-{PAGE_RUN}"
    saved.mkdir(parents=True, exist_ok=True)
    ids = {p["team_id_master"]: cid for cid, p in manifest["cards"].items()}
    for name, decision in picks.items():
        cid = ids[_id(name)]
        doc = {"id": cid, "data": {"decision": decision, "note": f"note on {name}"}}
        (saved / f"{cid}.json").write_text(json.dumps(doc), encoding="utf-8")
    col.collect(store, RUN, stage, out)
    return folder


def _scan_row(name, stored, proposed):
    return {
        "team_id_master": _id(name),
        "provider": "gotsport",
        "state": "NV",
        "team_name": f"Team {name}",
        "stored_club": stored,
        "proposed_club": proposed,
        "source": "team_name",
        "tier": "swap",
        "needs_review": False,
        "approved": True,
        "state_note": "",
    }


def _clubs(tmp_path, store, rows, picks, auto=()):
    folder = stage_dir(store, RUN, "clubs")
    folder.mkdir(parents=True, exist_ok=True)
    scan = tmp_path / "scan.csv"
    swapped.write_log([swapped.snapshot_csv_row(r) for r in rows], scan)
    kept, proposals = pw.club_proposals(pw._read_csv(scan), ["NV"])
    swapped.write_log(kept, folder / pw.SCOPED_CLUBS)
    _page(folder, "clubs", proposals, auto)
    return _choose(tmp_path, store, "clubs", picks)


def _plan_row(name, old, new, team_name=None):
    return {
        "state_code": "NV",
        "team_id_master": _id(name),
        "team_name": team_name or f"Team {name}",
        "club_name": "Reno APEX Soccer Club",
        "gender": "Female",
        "gotsport_team_name": "",
        "band": new,
        "old_age_group": old,
        "new_age_group": new,
        "action": "would_update",
        "collision_with": "",
        "evidence_tier": "A_own_name_band",
        "fixture_verdict": "",
        "opp_games_proposed": "",
        "opp_games_current": "",
    }


def _ages(tmp_path, store, rows, picks):
    folder = stage_dir(store, RUN, "ages")
    folder.mkdir(parents=True, exist_ok=True)
    bands.write_csv(rows, folder / pw.AGE_PLAN, bands.PLAN_FIELDS)
    _page(folder, "ages", pw.age_proposals(pw._read_csv(folder / pw.AGE_PLAN), []))
    return _choose(tmp_path, store, "ages", picks)


def _decision(name, pre, proposed, action="apply", tier="B", club="Club", confidence=0.9):
    return {
        "team_id": _id(name),
        "team_name": f"Team {name}",
        "club_name": club,
        "pre_image": pre,
        "proposed": proposed,
        "tier": tier,
        "confidence": confidence,
        "action": action,
        "reason": "club-mates",
    }


def _states(tmp_path, store, decisions, picks, rules="authority", elsewhere=(), auto=()):
    """The national run as propose_week saves it, with ``elsewhere``'s decisions outside the NV scope."""
    folder = stage_dir(store, RUN, "states")
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = {"rules": rules, "created_at": CREATED, "live_teams": 9, "decisions": [*decisions, *elsewhere]}
    write_json(folder / "national_snapshot.json", snapshot, indent=1)
    scoped, proposals = pw.state_proposals(snapshot, ["NV"])
    write_json(folder / pw.SCOPED_STATES, scoped, indent=1)
    _page(folder, "states", proposals, auto)
    return _choose(tmp_path, store, "states", picks)


def _wire(monkeypatch, db, runner, *, now=FRIDAY_EVENING, gh=None, processes=None):
    monkeypatch.setattr(ap, "get_client", lambda: db)
    monkeypatch.setattr(ap, "run_step", runner)
    monkeypatch.setattr(ap.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ap, "_now", lambda: now)
    monkeypatch.setattr(ap, "gh_runs", gh or (lambda status: []))
    monkeypatch.setattr(ap, "python_processes", processes or (lambda: []))


def _gh_run(workflow, run_id, status="queued", event="schedule"):
    """A workflow run as the repository's runs listing answers it."""
    return {"id": run_id, "path": f".github/workflows/{workflow}", "status": status, "event": event}


def _busy(workflow, run_id, when=lambda: True):
    """gh_runs answering, while ``when`` holds, that ``workflow`` has a queued run."""
    return lambda status: [_gh_run(workflow, run_id)] if status == "queued" and when() else []


def _after_the_windows(monkeypatch):
    """The applier's clock some minutes on, so that every batch's time window has closed."""
    later = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(ap, "utc_now_iso", lambda: later)


def _main(monkeypatch, capsys, store, stage, *argv):
    monkeypatch.setattr(sys, "argv", ["apply_stage.py", "--run", RUN, "--stage", stage, "--store", str(store), *argv])
    code = ap.main()
    return code, capsys.readouterr().out


def _refused(monkeypatch, capsys, store, stage, *argv):
    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, stage, *argv)
    return str(caught.value)


def _decisions(db):
    return db.tables["team_cleanup_decisions"]


def _ledger(db):
    return sorted(db.tables["team_cleanup_changes"], key=lambda r: r["team_id_master"])


def _team_writes(db):
    return [e for e in db.writes() if e[0] not in ("team_cleanup_runs",)]


def _club_week(tmp_path, n=3):
    store = _store(tmp_path)
    names = [f"c{i:02d}" for i in range(n)]
    rows = [_scan_row(name, "LVSA", f"Club {name}") for name in names]
    _clubs(tmp_path, store, rows, {name: "apply" for name in names})
    db = _Db(teams=[_team(name, club="LVSA") for name in names])
    return store, db, names


# --- the apply window ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "moment, inside",
    [
        (datetime(2026, 10, 14, 17, 59, tzinfo=timezone.utc), False),
        (datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 10, 19, 4, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc), False),
        (datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc), False),
    ],
    ids=["wed-10:59-az", "wed-11:00-az", "sun-21:59-az", "sun-22:00-az", "mon-08:00-az"],
)
def test_the_configured_window_is_wednesday_11_to_sunday_22_arizona(moment, inside):
    window = ap.load_window()

    assert window.text == "Wednesday 11:00 to Sunday 22:00, Arizona time"
    assert ap.in_window(window, moment) is inside


@pytest.mark.parametrize(
    "start, end",
    [
        (("Saturday", "22:00"), ("Friday", "17:00")),
        (("Saturday", "20:00"), ("Sunday", "22:30")),
        (("Monday", "08:00"), ("Monday", "20:00")),
    ],
    ids=["backwards", "past-the-monday-import", "the-monday-window"],
)
def test_a_window_outside_propose_to_hard_stop_is_refused(tmp_path, start, end):
    config = tmp_path / "team_cleanup.json"
    window = {"start": {"weekday": start[0], "time": start[1]}, "end": {"weekday": end[0], "time": end[1]}}
    config.write_text(json.dumps({"apply_window": window}), encoding="utf-8")

    with pytest.raises(ValueError, match="must run forwards between Wednesday 11:00"):
        ap.load_window(config)


def test_an_apply_outside_the_window_is_refused_and_outside_window_lets_it_run(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner, now=MONDAY_MORNING)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == (
        "Outside the apply window (Wednesday 11:00 to Sunday 22:00, Arizona time); "
        "apply inside it, or pass --outside-window."
    )
    assert db.executes == [] and runner.commands == []

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute", "--outside-window")

    assert code == 0 and [db.team(_id(n))["club_name"] for n in names] == ["Club c00", "Club c01", "Club c02"]


def test_an_apply_outside_the_window_with_the_override_runs_the_rest_too(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path, n=51)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner, now=MONDAY_MORNING)

    code, out = _main(monkeypatch, capsys, store, "clubs", "--execute", "--outside-window")

    assert code == 0 and len(runner.commands) == 2 and "rest: 1 written, 1 verified" in out


def test_a_window_that_closes_while_decisions_are_recorded_stops_the_pilot(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    record = ap.record_decisions

    def record_then_close(*args, **kwargs):
        record(*args, **kwargs)
        monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)

    monkeypatch.setattr(ap, "record_decisions", record_then_close)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith("Outside the apply window") and runner.commands == []
    assert [db.team(_id(n))["club_name"] for n in names] == ["LVSA", "LVSA", "LVSA"]


def test_a_lost_answer_outside_the_window_hands_back_the_override(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    _wire(monkeypatch, db, _Runner(db), now=MONDAY_MORNING)
    db.lost[("team_cleanup_decisions", "insert")] = httpx.ReadTimeout("timed out")

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute", "--outside-window")

    assert message.endswith(subprocess.list2cmdline(["--execute", "--outside-window", "--store", str(store)]))


# --- other writers -------------------------------------------------------------------------------


WORKFLOWS = Path(ap.ROOT) / ".github" / "workflows"
# A writer is a workflow with a step that can write teams, states or games, or that reads a field a stage
# writes (club, state or age) into something published, whether a cron or a person starts it. The
# pre-apply check asks gh about every writer but these, each left out for its reason; a workflow in no
# list fails until someone decides which it belongs in.
EXEMPT_WRITERS = {
    "backfill-unknown-team-names.yml": "runs every 15 minutes, so checking it would block every apply; it "
    "names unknown_<id> placeholder teams and fills a club_name only where it is blank, and never changes an "
    "existing team's club, state or age",
    "process-missing-games.yml": "runs every 15 minutes, so checking it would block every apply; it imports "
    "games for queued teams and stamps last_scraped_at, and never changes an existing team's club, state or age",
    "tgs-score-reconcile.yml": "corrects the stored score of TGS games, or hides a row a corrected copy "
    "supersedes, found by provider team ids; it never changes a team's club, state or age and reads none of them. "
    "Its Tuesday and Friday crons sit inside the apply week, before the Monday import the hard stop is set by",
    "refresh-team-scrape-activity.yml": "writes only the teams' derived activity columns (last_played_at, "
    "last_fixture_at, game_row_count, scrape_attempts), which no stage writes or reads; its Sunday cron sits "
    "inside the apply week, before the Monday import the hard stop is set by",
}
# The checked writers the freeze guard's detector does not find, pinned by name with why each is checked,
# since nothing else would notice one moved into NOT_A_WRITER.
UNDETECTED_WRITERS = {
    "auto-gotsport-event-scrape.yml": "imports the event games it scrapes, by default",
    "calculate-rankings.yml": "reads club_name, state_code and age_group into the published rankings, so a run "
    "during an apply publishes the stage half applied",
    "clear-queue.yml": "drain_queue.py imports games and stamps the teams it scraped",
    "fill-team-states-weekly.yml": "fills state_code through apply_team_state, the states stage's own field",
    "scrape-games.yml": "imports the games it scrapes (--auto-import)",
    "scrape-specific-event.yml": "imports the event's games unless auto_import is turned off",
    "sincsports-team-discovery.yml": "creates teams and fills a blank state_code",
    "update-missing-club-and-state.yml": "fills club_name, the clubs stage's own field",
}
# The scripts the checked workflows run that the process check leaves out, each for its reason: none
# writes teams, states or games, or reads a field a stage writes into something published.
EXEMPT_SCRIPTS = {
    "build_modular11_ea_games_csv.py": "reads the database into a CSV that import_games_enhanced.py imports",
    "build_mlsnext_kitman_games_csv.py": "reads the database into a CSV that import_games_enhanced.py imports",
    "due_diligence_unknown_opponents.py": "reads teams, aliases and games into a report CSV",
    "export_unknown_opponents.py": "reads games and teams into a CSV",
    "maintain_gotsport_direct_id_aliases.py": "writes only team_alias_map",
    "maintain_tgs_direct_id_aliases.py": "writes only team_alias_map",
    "match_modular11_ea_teams.py": "reads teams into a match report",
    "match_mlsnext_kitman_teams.py": "reads teams into a match report",
    "scrape_affinity_or_tournament.py": "scrapes into a CSV that import_games_enhanced.py imports",
    "scrape_affinity_ut_tournament.py": "scrapes into a CSV that import_games_enhanced.py imports",
    "scrape_affinity_wa_tournament.py": "scrapes into a CSV that import_games_enhanced.py imports",
    "scrape_modular11_ea.py": "scrapes into CSVs that the EA import steps read",
    "scrape_mlsnext_kitman.py": "scrapes into CSVs that the MLS NEXT import steps read",
    "scrape_playmetrics_league.py": "scrapes into a CSV that import_games_enhanced.py imports",
    "scrape_playmetrics_tournament.py": "scrapes into a CSV that import_games_enhanced.py imports",
    "scrape_tgs_event.py": "scrapes into a CSV that import_games_enhanced.py imports",
}
# A script a workflow step runs, by path or as a module (python -m scripts.<name>).
SCRIPT_IN_RUN = re.compile(r"scripts/(?:[\w-]+/)*(\w+\.py)|-m\s*scripts\.(?:\w+\.)*(\w+)")
NOT_A_WRITER = {
    "auto-gotsport-upcoming-event-scrape.yml": "scrapes upcoming fixtures into an artifact and never imports them",
    "auto-merge-queue.yml": "its one writing step is gated off by QUEUE_AUTO_APPROVE_ENABLED, and writes only "
    "aliases and the match review queue",
    "backfill-prediction-feature-history.yml": "writes prediction feature history",
    "check-stuck-signups.yml": "reads signups",
    "ci.yml": "lints and tests, with no database secrets",
    "claude-code-review.yml": "reviews pull requests, with no database secrets",
    "claude.yml": "answers issue and pull request comments, with no database secrets",
    "contradiction-report-weekly.yml": "runs assign_team_states.py without --execute, so it writes nothing",
    "double-stored-games-report-weekly.yml": "reads games and writes nothing",
    "enqueue-active-teams.yml": "writes scrape_requests",
    "enqueue-discovery.yml": "writes scrape_requests",
    "enqueue-safety-net.yml": "writes scrape_requests",
    "enqueue-viewed-teams.yml": "writes scrape_requests",
    "enqueue-yesterday-games.yml": "writes scrape_requests",
    "enrich-instagram-handles.yml": "writes team_social_profiles",
    "evaluate-prospective-match-predictions.yml": "reads match predictions",
    "marketing-pipeline.yml": "reads the rankings and commits a blog post",
    "prepare-prospective-match-predictions.yml": "writes match predictions",
    "process-match-prediction-shadow.yml": "writes the match prediction shadow log",
    "process-prospective-heuristic-predictions.yml": "writes match predictions",
    "reconcile-stripe-daily.yml": "writes subscriptions and user profiles",
    "settle-prospective-match-predictions.yml": "writes match predictions",
    "smoke-infographics.yml": "reads the infographic routes",
    "train-point-in-time-match-model.yml": "writes model artifacts and training runs",
    "weekly-prospective-refresh.yml": "scrapes upcoming fixtures without importing them, and writes match predictions",
    "weekly-prospective-settle-evaluate.yml": "writes match predictions",
}


def _workflows():
    return {path.name for path in WORKFLOWS.glob("*.y*ml")}


def _crons(workflow):
    """The workflow's live crons. YAML reads the bare `on:` key as True."""
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True)) if isinstance(doc, dict) else None
    schedule = triggers.get("schedule") if isinstance(triggers, dict) else None
    return [entry["cron"] for entry in schedule or [] if isinstance(entry, dict) and entry.get("cron")]


def _scripts_run_by(workflow):
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    runs = [step.get("run") or "" for job in doc["jobs"].values() for step in job.get("steps") or []]
    return {path or f"{module}.py" for run in runs for path, module in SCRIPT_IN_RUN.findall(run)}


def _cron_values(field, low, high):
    values = set()
    for part in field.split(","):
        span, _, step = part.partition("/")
        start, end = (low, high) if span == "*" else (int(span.split("-")[0]), int(span.split("-")[-1]))
        values |= set(range(start, end + 1, int(step or 1)))
    return values


def _fires_after_propose(cron):
    """Minutes from Wednesday's propose to each time ``cron`` fires in a week. A cron runs in UTC, and
    Arizona keeps UTC-7 all year; one naming days of the month can fall on any weekday."""
    minute, hour, days, _, weekdays = cron.split()
    found = set()
    for weekday in range(7) if days != "*" else _cron_values(weekdays, 0, 7):
        for at in (h * 60 + m for h in _cron_values(hour, 0, 23) for m in _cron_values(minute, 0, 59)):
            # cron counts Sunday as 0 (and 7), Python as 6.
            local = (((weekday - 1) % 7) * 24 * 60 + at - 7 * 60) % ap.WEEK_MINUTES
            found.add(ap._after_propose(local // (24 * 60), local % (24 * 60)))
    return found


def test_the_cron_scan_reads_live_crons_and_skips_a_commented_one():
    assert _crons("ut-scraper.yml") == ["30 5 * * 1", "30 6 * * 1"]
    assert _crons("modular11-events-weekly-scrape.yml") == []
    assert _fires_after_propose("0 5 * * 1") == {ap._after_propose(6, 22 * 60)}


def test_every_workflow_is_checked_or_named_as_left_out():
    checked = set(ap.WRITER_WORKFLOWS)

    assert len(checked) == len(ap.WRITER_WORKFLOWS)
    assert not checked & set(NOT_A_WRITER) and not checked & set(EXEMPT_WRITERS)
    assert not set(NOT_A_WRITER) & set(EXEMPT_WRITERS)
    assert _workflows() == checked | set(NOT_A_WRITER) | set(EXEMPT_WRITERS)


def test_every_checked_writer_is_one_the_freeze_guard_finds_or_one_pinned_by_name():
    found = {workflow for workflow, _, _ in _writing_steps()}

    assert found - set(ap.WRITER_WORKFLOWS) == {"auto-merge-queue.yml"}
    assert set(ap.WRITER_WORKFLOWS) - found == set(UNDETECTED_WRITERS)


def test_the_hard_stop_is_the_first_time_a_checked_writer_runs_after_the_propose():
    fires = [at for workflow in ap.WRITER_WORKFLOWS for cron in _crons(workflow) for at in _fires_after_propose(cron)]

    assert fires and min(fires) == ap._after_propose(*ap.HARD_STOP_AT)


def test_every_script_a_checked_workflow_runs_is_one_the_process_check_names_or_left_out():
    run = {script for workflow in ap.WRITER_WORKFLOWS for script in _scripts_run_by(workflow)}

    assert len(set(ap.APPLIER_SCRIPTS)) == len(ap.APPLIER_SCRIPTS)
    assert not set(ap.APPLIER_SCRIPTS) & set(EXEMPT_SCRIPTS)
    assert run - set(ap.APPLIER_SCRIPTS) - set(EXEMPT_SCRIPTS) == set()


def test_every_script_the_process_check_names_or_leaves_out_is_a_tracked_script():
    script = re.compile(r"(\.claude/skills/[^/]+/)?scripts/.+")
    scripts = {path.rsplit("/", 1)[-1] for path in TRACKED if script.fullmatch(path)}

    assert [name for name in [*ap.APPLIER_SCRIPTS, *EXEMPT_SCRIPTS] if name not in scripts] == []


@pytest.mark.parametrize("status", ["queued", "in_progress", "pending", "waiting", "requested"])
def test_a_scheduled_writer_not_completed_refuses_the_apply(tmp_path, monkeypatch, capsys, status):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)

    def gh(asked):
        return [_gh_run("fill-team-states-weekly.yml", 42, status, "workflow_dispatch")] if asked == status else []

    _wire(monkeypatch, db, runner, gh=gh)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == (
        "Not applying while another writer may be running:\n"
        f"  fill-team-states-weekly.yml run 42 is {status} (workflow_dispatch)"
    )
    assert _team_writes(db) == [] and runner.commands == []
    assert db.tables["team_cleanup_runs"][0]["lease_holder"] is None


def test_gh_failing_refuses_the_apply(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    monkeypatch.setattr(ap, "gh_runs", REAL_GH_RUNS)
    calls = []

    def gh(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="HTTP 401: Bad credentials")

    monkeypatch.setattr(ap.subprocess, "run", gh)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == (
        "Not applying: gh api repos/{owner}/{repo}/actions/runs -f status=queued exited 1: HTTP 401: Bad credentials"
    )
    endpoint = "repos/{owner}/{repo}/actions/runs"
    assert calls == [["gh", "api", "-X", "GET", endpoint, "-f", "status=queued", "-f", "per_page=100"]]
    assert _team_writes(db) == [] and runner.commands == []


def _runs_page(command, runs):
    """subprocess.run as gh api answers the repository's runs listing for the status the command asks."""
    assert command[:5] == ["gh", "api", "-X", "GET", "repos/{owner}/{repo}/actions/runs"]
    page = {"total_count": len(runs), "workflow_runs": runs}
    return subprocess.CompletedProcess(command, 0, stdout=json.dumps(page), stderr="")


def test_gh_is_asked_once_per_unfinished_status_for_the_whole_repository_one_at_a_time(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    monkeypatch.setattr(ap, "gh_runs", REAL_GH_RUNS)
    asked = []

    def gh(command, **kwargs):
        status = command[command.index("-f") + 1].removeprefix("status=")
        asked.append((status, kwargs.get("cwd")))
        # Another workflow's run is no writer's; the waiting run is the weekly fill's.
        runs = {
            "in_progress": [_gh_run("ci.yml", 7, "in_progress", "pull_request")],
            "waiting": [_gh_run("fill-team-states-weekly.yml", 99, "waiting", "workflow_dispatch")],
        }.get(status, [])
        return _runs_page(command, runs)

    monkeypatch.setattr(ap.subprocess, "run", gh)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == (
        "Not applying while another writer may be running:\n"
        "  fill-team-states-weekly.yml run 99 is waiting (workflow_dispatch)"
    )
    # gh fills the endpoint's {owner}/{repo} from the checkout it runs in.
    statuses = ["queued", "in_progress", "requested", "waiting", "pending"]
    assert asked == [(status, ap.ROOT) for status in statuses]
    assert runner.commands == []


def test_a_full_page_of_runs_refuses_rather_than_missing_one_past_it(tmp_path, monkeypatch, capsys):
    message = _refused_by_listing(
        tmp_path,
        monkeypatch,
        capsys,
        lambda command, **kwargs: _runs_page(command, [_gh_run("ci.yml", n, "queued", "push") for n in range(100)]),
        gh=True,
    )

    assert message == (
        "Not applying: gh api repos/{owner}/{repo}/actions/runs -f status=queued filled a page of 100 runs, so one "
        "could lie past it"
    )


@pytest.mark.parametrize(
    "line, refused",
    [
        (r'"C:\Python313\python.exe" scripts\fix_band_cohorts.py --apply p.csv', "4242 runs fix_band_cohorts.py"),
        ("python .claude/skills/reconcile-gotsport/scripts/apply_team_fields.py", "4242 runs apply_team_fields.py"),
        ("python -m scripts.fix_band_cohorts --apply p.csv --execute", "4242 runs fix_band_cohorts.py"),
        ("python.exe -mscripts.assign_team_states --execute", "4242 runs assign_team_states.py"),
        (
            r"python scripts\team_cleanup\apply_stage.py --run 2026-10-07-nv --stage clubs --revert --execute",
            "4242 runs apply_stage.py",
        ),
        ("python -m scripts.team_cleanup.apply_stage --run 2026-10-14-nv --stage ages", "4242 runs apply_stage.py"),
        (None, "4242: its command line cannot be read"),
    ],
    ids=[
        "age-applier",
        "skill-applier",
        "as-a-module",
        "as-a-module-unspaced",
        "another-apply",
        "another-apply-as-a-module",
        "unreadable",
    ],
)
def test_a_python_process_running_an_applier_refuses_the_apply(tmp_path, monkeypatch, capsys, line, refused):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner, processes=lambda: [{"ProcessId": 4242, "CommandLine": line}])

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == f"Not applying while another writer may be running:\n  Python process {refused}"
    assert _team_writes(db) == [] and runner.commands == []


@pytest.mark.parametrize(
    "line",
    [
        "python -m pytest tests/unit/test_fix_band_cohorts.py",
        "python -m streamlit run dashboard.py",
        "python -m scripts.fix_band_cohorts_review --out r.csv",
        "python -m pytest tests/unit/test_team_cleanup_apply_stage.py",
    ],
    ids=["a-test-of-an-applier", "the-dashboard", "a-module-named-like-an-applier", "a-test-of-the-apply"],
)
def test_a_python_process_running_no_applier_does_not(tmp_path, monkeypatch, capsys, line):
    store, db, _ = _club_week(tmp_path)
    _wire(monkeypatch, db, _Runner(db), processes=lambda: [{"ProcessId": 4242, "CommandLine": line}])

    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0


APPLY_LINE = r'"C:\venv\Scripts\python.exe" scripts/team_cleanup/apply_stage.py --run 2026-10-14-nv --stage clubs'
DOTENV_LINE = "python -m dotenv run -- python scripts/team_cleanup/apply_stage.py --run 2026-10-14-nv --stage clubs"


def _selected_listing(processes):
    """subprocess.run as Windows answers the process listing: each process with only the properties the
    query's Select-Object names, as ConvertTo-Json writes them."""

    def run(command, **kwargs):
        assert command[:3] == ["powershell", "-NoProfile", "-Command"] and "Win32_Process" in command[3]
        names = re.search(r"Select-Object (\S+)", command[3]).group(1).split(",")
        found = [{name: process.get(name) for name in names} for process in processes]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(found), stderr="")

    return run


def _process(pid, parent, line):
    return {"ProcessId": pid, "ParentProcessId": parent, "CommandLine": line}


def _listed(monkeypatch, processes):
    monkeypatch.setattr(ap, "python_processes", REAL_PYTHON_PROCESSES)
    monkeypatch.setattr(ap.subprocess, "run", _selected_listing(processes))


@pytest.mark.parametrize(
    "launchers",
    [[_process(101, 7, APPLY_LINE)], [_process(101, 100, APPLY_LINE), _process(100, 7, DOTENV_LINE)]],
    ids=["its-venv-launcher", "and-the-dotenv-run-above-that"],
)
def test_the_python_processes_that_launched_this_apply_do_not_refuse_it(tmp_path, monkeypatch, capsys, launchers):
    store, db, _ = _club_week(tmp_path)
    _wire(monkeypatch, db, _Runner(db))
    _listed(monkeypatch, [_process(os.getpid(), 101, APPLY_LINE), *launchers])

    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0


def test_another_apply_its_launcher_also_started_still_refuses(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    sibling = r"python scripts\team_cleanup\apply_stage.py --run 2026-10-07-nv --stage clubs --revert --execute"
    _listed(
        monkeypatch,
        [_process(os.getpid(), 101, APPLY_LINE), _process(101, 7, DOTENV_LINE), _process(202, 101, sibling)],
    )

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == "Not applying while another writer may be running:\n  Python process 202 runs apply_stage.py"
    assert _team_writes(db) == [] and runner.commands == []


def test_a_parent_id_that_leads_back_into_the_chain_ends_the_walk(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    _wire(monkeypatch, db, _Runner(db))
    _listed(monkeypatch, [_process(os.getpid(), 101, APPLY_LINE), _process(101, os.getpid(), APPLY_LINE)])

    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0


def _windows_listing(utf8, oem):
    """subprocess.run as Windows answers the listing: PowerShell writes the OEM code page unless the
    query asks for UTF-8, text mode without an encoding reads cp1252 (no UTF-8 mode), and a decode
    error raised in subprocess's reader thread leaves stdout None."""

    def run(command, **kwargs):
        assert command[:3] == ["powershell", "-NoProfile", "-Command"] and "Win32_Process" in command[3]
        raw = utf8 if command[3].startswith("[Console]::OutputEncoding = [Text.Encoding]::UTF8; ") else oem
        if not (kwargs.get("text") or kwargs.get("encoding") or kwargs.get("errors")):
            return subprocess.CompletedProcess(command, 0, stdout=raw, stderr=b"")
        try:
            stdout = raw.decode(kwargs.get("encoding") or "cp1252", kwargs.get("errors") or "strict")
        except UnicodeDecodeError:
            stdout = None
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return run


def test_the_process_listing_reads_one_process_as_a_list_and_a_non_ascii_command_line_intact(monkeypatch):
    line = 'python x.py "Club Atlético Münster"'
    found = json.dumps({"ProcessId": 7, "CommandLine": line}, ensure_ascii=False)
    monkeypatch.setattr(ap.subprocess, "run", _windows_listing(found.encode("utf-8"), found.encode("cp437")))

    assert REAL_PYTHON_PROCESSES() == [{"ProcessId": 7, "CommandLine": line}]


def test_a_listing_byte_that_is_not_utf_8_reads_as_a_replacement_not_a_failure(monkeypatch):
    found = b'{"ProcessId":7,"CommandLine":"python x.py Atl\x82tico"}'
    monkeypatch.setattr(ap.subprocess, "run", _windows_listing(found, found))

    assert REAL_PYTHON_PROCESSES() == [{"ProcessId": 7, "CommandLine": "python x.py Atl�tico"}]


@pytest.mark.parametrize(
    "stdout, refused",
    [
        (None, "Not applying: the process listing printed nothing that could be read"),
        (" \r\n", "Not applying: the process listing printed nothing that could be read"),
        ("42", "Not applying: the process listing answered 42, not a list of objects"),
        ('["python x.py"]', "Not applying: the process listing answered ['python x.py'], not a list of objects"),
    ],
    ids=["unreadable", "blank", "a-number", "a-list-of-strings"],
)
def test_a_process_listing_that_answers_no_list_of_processes_refuses(tmp_path, monkeypatch, capsys, stdout, refused):
    def listing(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=None)

    assert _refused_by_listing(tmp_path, monkeypatch, capsys, listing) == refused


@pytest.mark.parametrize(
    "stdout, said",
    [
        (None, "printed nothing that could be read"),
        ("", "printed nothing that could be read"),
        ('{"total": 0}x', "failed: JSONDecodeError"),
        ("7", "answered 7, not a list of objects"),
        ("[]", "answered [], not a page of workflow runs"),
        ('{"total_count": 0}', "answered [{'total_count': 0}], not a page of workflow runs"),
        ('{"workflow_runs": [{"id": 1}]}', "answered [{'workflow_runs': [{'id': 1}]}], not a page of workflow runs"),
    ],
    ids=["unreadable", "blank", "not-json", "a-number", "no-page", "a-page-of-no-runs", "a-run-naming-no-workflow"],
)
def test_a_gh_answer_that_is_no_page_of_runs_refuses(tmp_path, monkeypatch, capsys, stdout, said):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=None)

    message = _refused_by_listing(tmp_path, monkeypatch, capsys, run, gh=True)

    assert message.startswith(f"Not applying: gh api repos/{{owner}}/{{repo}}/actions/runs -f status=queued {said}")


def _refused_by_listing(tmp_path, monkeypatch, capsys, behave, gh=False):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    monkeypatch.setattr(ap, "python_processes", REAL_PYTHON_PROCESSES)
    if gh:
        monkeypatch.setattr(ap, "gh_runs", REAL_GH_RUNS)
    monkeypatch.setattr(ap.subprocess, "run", behave)
    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")
    assert runner.commands == [] and _team_writes(db) == []
    return message


def test_a_failing_process_listing_refuses(tmp_path, monkeypatch, capsys):
    def listing(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Get-CimInstance : Access denied")

    message = _refused_by_listing(tmp_path, monkeypatch, capsys, listing)

    assert message == "Not applying: the process listing exited 1: Get-CimInstance : Access denied"


def test_a_missing_powershell_refuses(tmp_path, monkeypatch, capsys):
    def listing(command, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified", "powershell")

    message = _refused_by_listing(tmp_path, monkeypatch, capsys, listing)

    assert message.startswith("Not applying: the process listing failed: FileNotFoundError")


def test_a_missing_gh_refuses(tmp_path, monkeypatch, capsys):
    def run(command, **kwargs):
        if command[0] == "gh":
            raise FileNotFoundError(2, "The system cannot find the file specified", "gh")
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    message = _refused_by_listing(tmp_path, monkeypatch, capsys, run, gh=True)

    assert message.startswith(
        "Not applying: gh api repos/{owner}/{repo}/actions/runs -f status=queued failed: FileNotFoundError"
    )


# --- the files the apply reads -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["vetted.csv", "decisions.json"])
@pytest.mark.parametrize("flags", [("--execute",), ()], ids=["execute", "dry-run"])
def test_a_vetted_or_decisions_file_changed_since_collecting_is_refused(tmp_path, monkeypatch, capsys, name, flags):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    path = stage_dir(store, RUN, "clubs") / name
    path.write_text(path.read_text(encoding="utf-8-sig").replace("c00", "c99"), encoding="utf-8")

    message = _refused(monkeypatch, capsys, store, "clubs", *flags)

    assert message == (
        f"Cannot apply the clubs stage of {RUN}: changed since the choices were collected: {name}; collect again"
    )
    assert db.executes == [] and runner.commands == []


def test_a_file_changed_while_the_lock_was_taken_is_refused_inside_it(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    decisions = stage_dir(store, RUN, "clubs") / "decisions.json"

    def collect_meanwhile(db):
        decisions.write_text("[]", encoding="utf-8")

    db.hooks[("team_cleanup_runs", "update")] = [collect_meanwhile]

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert "changed since the choices were collected: decisions.json" in message
    assert _team_writes(db) == [] and runner.commands == []
    assert db.tables["team_cleanup_runs"][0]["lease_holder"] is None


def test_collect_refuses_while_an_apply_holds_the_run(tmp_path):
    store, _, _ = _club_week(tmp_path)
    out = tmp_path / "out" / "clubs"

    with _acquire_file_lock(run_dir(store, RUN) / APPLY_LOCK_FILE, timeout=0.0):
        with pytest.raises(SystemExit) as caught:
            col.collect(store, RUN, "clubs", out)

    assert str(caught.value) == (
        f"Cannot collect the clubs choices for {RUN}: run {RUN} is in use on this machine (an apply, revert, "
        "collect, page build or end_run holds its lock)"
    )


def test_a_state_snapshot_decided_under_older_rules_is_refused(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("s1", None, "NV")], {"s1": "apply"}, rules="older")
    db = _Db(teams=[_team("s1", state=None)])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message == (
        f"Cannot apply the states stage of {RUN}: the state snapshot was decided under rules 'older', not "
        "'authority', so assign_team_states.py refuses to replay it; next week's proposal decides again"
    )
    assert db.executes == [] and runner.commands == []


# --- the owner's decisions, recorded first -------------------------------------------------------


def _active(db, name, field="club_name", stage="clubs"):
    key = f"{_id(name)}|{field}"
    return [r for r in _decisions(db) if (r["stage"], r["subject_key"]) == (stage, key) and r["superseded_at"] is None]


def test_every_decided_card_is_recorded_before_any_applier_runs(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    rows = [_scan_row("keep", "LVSA", "Club keep"), _scan_row("skip", "LVSA", "Club skip")]
    rows.append(_scan_row("ask", "LVSA", "Club ask"))
    _clubs(tmp_path, store, rows, {"keep": "apply", "skip": "dont_apply", "ask": "unsure"})
    db = _Db(teams=[_team(n, club="LVSA") for n in ("keep", "skip", "ask")])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    _main(monkeypatch, capsys, store, "clubs", "--execute")

    inserts = [i for i, e in enumerate(db.executes) if e[:2] == ("team_cleanup_decisions", "insert")]
    assert len(inserts) == 3 and max(inserts) < runner.at[0]
    recorded = sorted((r["team_id_master"], r["decision"]) for r in _decisions(db))
    assert recorded == sorted([(_id("keep"), "apply"), (_id("skip"), "dont_apply"), (_id("ask"), "unsure")])
    row = _active(db, "skip")[0]
    assert {k: row[k] for k in ("field", "proposed_value", "note", "decided_at", "source", "subject_key")} == {
        "field": "club_name",
        "proposed_value": "Club skip",
        "note": "note on skip",
        "decided_at": BUILT,
        "source": f"page:{PAGE_RUN}",
        "subject_key": f"{_id('skip')}|club_name",
    }


def test_an_earlier_decision_is_superseded_and_the_same_one_is_not_recorded_twice(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=2)
    older = {"stage": "clubs", "subject_key": f"{_id('c00')}|club_name", "team_id_master": _id("c00")}
    older.update({"field": "club_name", "proposed_value": "Club c00", "decision": "dont_apply", "note": None})
    older.update({"decided_at": "2026-10-07T18:00:00+00:00", "source": "page:20261007T180000Z-000000"})
    same = {**older, "subject_key": f"{_id('c01')}|club_name", "team_id_master": _id("c01"), "decision": "apply"}
    same.update({"proposed_value": "Club c01", "decided_at": BUILT, "source": f"page:{PAGE_RUN}"})
    for n, row in enumerate((older, same)):
        db.tables["team_cleanup_decisions"].append({**row, "id": f"d{n}", "other_team_id": None, "superseded_at": None})
    _wire(monkeypatch, db, _Runner(db))

    _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert db.tables["team_cleanup_decisions"][0]["superseded_at"] is not None
    assert [(r["decision"], r["source"]) for r in _active(db, "c00")] == [("apply", f"page:{PAGE_RUN}")]
    assert [r["id"] for r in _active(db, "c01")] == ["d1"]
    assert [e[2]["team_id_master"] for e in db.executes if e[:2] == ("team_cleanup_decisions", "insert")] == [
        _id("c00")
    ]


def test_a_later_decision_already_recorded_is_not_overturned(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=1)
    later = {"id": "d9", "stage": "clubs", "subject_key": f"{_id('c00')}|club_name", "team_id_master": _id("c00")}
    later.update({"other_team_id": None, "field": "club_name", "proposed_value": "Club c00", "decision": "dont_apply"})
    later.update({"note": None, "decided_at": "2026-10-20T00:00:00+00:00", "source": "page:x", "superseded_at": None})
    db.tables["team_cleanup_decisions"].append(later)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == (
        f"Cannot apply the clubs stage of {RUN}: a later decision is already recorded for "
        "'Team c00' (dont_apply on 2026-10-20)"
    )
    assert _team_writes(db) == [] and runner.commands == []


def test_a_lost_answer_while_recording_stops_before_any_applier_with_the_retry(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    db.lost[("team_cleanup_decisions", "insert")] = httpx.ReadTimeout("timed out")

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    retry = subprocess.list2cmdline(
        ["scripts/team_cleanup/apply_stage.py", "--run", RUN, "--stage", "clubs", "--execute", "--store", str(store)]
    )
    assert message.startswith(f"Could not record the owner's decision on {_id('c00')}|club_name: the database's answer")
    assert message.endswith(f"re-run to see where it stands: python {retry}")
    assert runner.commands == []
    assert db.tables["team_cleanup_runs"][0]["lease_holder"] is None

    db.lost.clear()
    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert code == 0 and len(_decisions(db)) == 3 and all(r["superseded_at"] is None for r in _decisions(db))


def test_a_lost_supersede_stops_before_any_applier_and_its_retry_leaves_one_active_decision(
    tmp_path, monkeypatch, capsys
):
    store, db, _ = _club_week(tmp_path, n=1)
    older = {"stage": "clubs", "subject_key": f"{_id('c00')}|club_name", "team_id_master": _id("c00")}
    older.update({"field": "club_name", "proposed_value": "Club c00", "decision": "dont_apply", "note": None})
    db.insert("team_cleanup_decisions", {**older, "decided_at": "2026-10-07T18:00:00+00:00", "source": "page:old"})
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    db.lost[("team_cleanup_decisions", "update")] = httpx.ReadTimeout("timed out")

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert "the database's answer was lost" in message and runner.commands == [] and _active(db, "c00") == []

    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0
    assert [(r["decision"], r["source"]) for r in _active(db, "c00")] == [("apply", f"page:{PAGE_RUN}")]


def test_an_apply_that_stopped_before_writing_a_team_leaves_the_choices_free_to_collect_again(
    tmp_path, monkeypatch, capsys
):
    store, db, _ = _club_week(tmp_path, n=2)
    _wire(monkeypatch, db, _Runner(db))
    db.lost[("team_cleanup_decisions", "insert")] = httpx.ReadTimeout("timed out")
    _refused(monkeypatch, capsys, store, "clubs", "--execute")

    _choose(tmp_path / "again", store, "clubs", {"c00": "apply", "c01": "dont_apply"})
    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert code == 0
    assert (db.team(_id("c00"))["club_name"], db.team(_id("c01"))["club_name"]) == ("Club c00", "LVSA")


# --- pilot and rest ------------------------------------------------------------------------------


def test_the_pilot_and_the_rest_are_cut_files_that_never_overlap(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path, n=60)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, out = _main(monkeypatch, capsys, store, "clubs", "--execute")

    folder = stage_dir(store, RUN, "clubs")
    pilot = [r["team_id_master"] for r in pw._read_csv(folder / "pilot.csv")]
    rest = [r["team_id_master"] for r in pw._read_csv(folder / "rest.csv")]
    assert code == 0 and len(pilot) == 50 and len(rest) == 10
    assert set(pilot).isdisjoint(rest) and sorted(pilot + rest) == sorted(_id(n) for n in names)
    exports = str(store / "exports")
    assert runner.commands == [
        [
            "scripts/repair_swapped_club_names.py",
            "--execute",
            str(folder / "pilot.csv"),
            "--exports-dir",
            exports,
            "--actor",
            ACTOR,
        ],
        [
            "scripts/repair_swapped_club_names.py",
            "--execute",
            str(folder / "rest.csv"),
            "--exports-dir",
            exports,
            "--actor",
            ACTOR,
        ],
    ]
    assert not any("--limit" in command for command in runner.commands)
    assert "pilot: 50 written, 50 verified" in out and "rest: 10 written, 10 verified" in out


def _renewals(db):
    return [
        i
        for i, e in enumerate(db.executes)
        if e[:2] == ("team_cleanup_runs", "update") and set(e[2]) == {"lease_expires_at"}
    ]


def test_the_lease_is_renewed_before_the_pilot_and_before_the_rest(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=51)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    _main(monkeypatch, capsys, store, "clubs", "--execute")

    renewals = _renewals(db)
    assert len(renewals) == 2 and renewals[0] < runner.at[0] < renewals[1] < runner.at[1]


def test_the_pilot_waits_for_a_lease_this_apply_still_holds(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    def expired(db):
        db.tables["team_cleanup_runs"][0]["lease_expires_at"] = "2026-10-14T00:00:00Z"

    db.hooks[("team_cleanup_decisions", "insert")] = [expired]

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith(f"Run {RUN}'s lease is no longer ") and message.endswith("so the pilot was not applied.")
    assert runner.commands == []


def test_a_pilot_whose_writes_the_database_does_not_hold_stops_before_the_rest(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=55)
    pilot_team = sorted(_id(f"c{i:02d}") for i in range(55))[0]

    def another_writer(db):
        db.team(pilot_team)["club_name"] = "Somebody Else FC"

    runner = _Runner(db, during={"repair_swapped_club_names": another_writer})
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith(
        f"Stopped after the pilot batch: 1 written change(s) the database does not hold: {pilot_team}"
    )
    assert len(runner.commands) == 1
    assert len(_ledger(db)) == 49 and pilot_team not in {r["team_id_master"] for r in _ledger(db)}
    assert not (stage_dir(store, RUN, "clubs") / "RECORD.md").exists()


def test_a_rerun_after_a_stop_resumes_without_replaying_a_finished_batch(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=55)
    runner = _Runner(db, codes={"repair_swapped_club_names": [None, 1]})
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")
    assert message.startswith("Stopped after the rest batch: its applier exited 1")

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert code == 0
    cuts = [Path(command[2]).name for command in runner.commands]
    assert cuts == ["pilot.csv", "rest.csv", "rest.csv"]
    assert len(_ledger(db)) == 55


class _WritesThenFails(_Runner):
    """The club applier writes its cut and its log, then exits 1, once."""

    failed = False

    def repair_swapped_club_names(self, command, log):
        code = super().repair_swapped_club_names(command, log)
        if "--revert" not in command and not self.failed:
            self.failed = True
            return 1
        return code


def test_an_earlier_attempt_whose_ledger_write_was_refused_is_ledgered_on_the_rerun(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    _wire(monkeypatch, db, _WritesThenFails(db))
    db.refuse[("team_cleanup_changes", "upsert")] = _api_error("57014", "canceling statement due to statement timeout")

    assert _refused(monkeypatch, capsys, store, "clubs", "--execute").startswith("Could not write team_cleanup_changes")
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0

    assert sorted(r["team_id_master"] for r in _ledger(db)) == sorted(_id(n) for n in names)


def test_the_rest_waits_for_a_lease_this_apply_still_holds(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=51)

    def taken_over(db):
        db.tables["team_cleanup_runs"][0]["lease_holder"] = "another-machine:1"

    runner = _Runner(db, during={"repair_swapped_club_names": taken_over})
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith(f"Run {RUN}'s lease is no longer ") and message.endswith("so the rest was not applied.")
    assert len(runner.commands) == 1 and len(_ledger(db)) == 50


def _their_log(store, team, actor="pitchrank-operator"):
    """Another clubs run's log landing in the store's exports while a batch runs."""

    def write(db):
        entry = {**_entry(team, before="THEIR CLUB", after="Their Club"), "action": "updated"}
        log = store / "exports" / "repair_swapped_club_names_log_20261017_020000.csv"
        swapped.write_log([swapped.log_row(entry, "execute", actor)], log)

    return write


def test_another_writer_s_log_in_the_batch_is_neither_ledgered_nor_undone(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    db.tables["teams"].append(_team("theirs", club="Their Club"))
    runner = _Runner(db, during={"repair_swapped_club_names": _their_log(store, "theirs")})
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    [batch] = read_json(stage_dir(store, RUN, "clubs") / "apply.json")["batches"]
    ours, theirs = batch["logs"]
    assert code == 0 and theirs.endswith("_20261017_020000.csv")
    assert {r["log_file"] for r in _ledger(db)} == {ours} and len(_ledger(db)) == 3
    record = (stage_dir(store, RUN, "clubs") / "RECORD.md").read_text(encoding="utf-8")
    assert f"  - applier log: {ours}\n  - another writer's log, not this batch's: {theirs}\n" in record

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert code == 0 and runner.commands[1:] == [
        ["scripts/repair_swapped_club_names.py", "--revert", ours, "--execute"]
    ]
    assert db.team(_id("theirs"))["club_name"] == "Their Club"
    assert [db.team(_id(n))["club_name"] for n in names] == ["LVSA", "LVSA", "LVSA"]


def test_another_writer_s_log_that_sorts_first_is_neither_ledgered_nor_undone(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    db.tables["teams"].append(_team("theirs", club="Their Club"))

    def their_earlier_log(db):
        entry = {**_entry("theirs", before="THEIR CLUB", after="Their Club"), "action": "updated"}
        log = store / "exports" / "repair_swapped_club_names_log_20261017_000000.csv"
        swapped.write_log([swapped.log_row(entry, "execute", "pitchrank-operator")], log)

    runner = _Runner(db, during={"repair_swapped_club_names": their_earlier_log})
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    [batch] = read_json(stage_dir(store, RUN, "clubs") / "apply.json")["batches"]
    theirs, ours = batch["logs"]
    assert code == 0 and theirs.endswith("_20261017_000000.csv")
    assert {r["log_file"] for r in _ledger(db)} == {ours} and len(_ledger(db)) == 3
    record = (stage_dir(store, RUN, "clubs") / "RECORD.md").read_text(encoding="utf-8")
    assert f"  - another writer's log, not this batch's: {theirs}\n  - applier log: {ours}\n" in record

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert code == 0 and runner.commands[1:] == [
        ["scripts/repair_swapped_club_names.py", "--revert", ours, "--execute"]
    ]
    assert db.team(_id("theirs"))["club_name"] == "Their Club"
    assert [db.team(_id(n))["club_name"] for n in names] == ["LVSA"] * 3


@pytest.mark.parametrize(
    "team, actor",
    [("c00", "pitchrank-operator"), ("theirs", ACTOR)],
    ids=["another-actor-for-a-cut-team", "this-run-for-a-team-outside-the-cut"],
)
def test_a_batch_whose_only_new_log_is_not_its_own_stops_and_its_revert_refuses(
    tmp_path, monkeypatch, capsys, team, actor
):
    store, db, names = _club_week(tmp_path)
    db.tables["teams"].append(_team("theirs", club="Their Club"))
    runner = _Runner(
        db,
        codes={"repair_swapped_club_names": [0]},
        during={"repair_swapped_club_names": _their_log(store, team, actor)},
    )
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    log = str(store / "exports" / "repair_swapped_club_names_log_20261017_020000.csv")
    assert message.startswith(
        "Stopped after the pilot batch: expected one new repair_swapped_club_names_log_*.csv in the exports folder "
        f"written as {ACTOR} for the pilot cut, found {log}"
    )
    assert _ledger(db) == [] and not (stage_dir(store, RUN, "clubs") / "RECORD.md").exists()

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith(f"Not reverting: none of the pilot batch's new logs ({log}) is its own alone")
    assert len(runner.commands) == 1 and db.team(_id("theirs"))["club_name"] == "Their Club"
    assert [db.team(_id(n))["club_name"] for n in names] == ["LVSA", "LVSA", "LVSA"]


def test_two_new_logs_that_each_pass_as_the_batch_s_own_are_neither_ledgered_nor_replayed(
    tmp_path, monkeypatch, capsys
):
    store, db, names = _club_week(tmp_path)
    runner = _Runner(db, during={"repair_swapped_club_names": _their_log(store, "c00", ACTOR)})
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith("Stopped after the pilot batch: expected one new repair_swapped_club_names_log_*.csv")
    assert _ledger(db) == []
    assert _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute").startswith(
        "Not reverting: none of the pilot batch's new logs"
    )
    assert len(runner.commands) == 1


def test_an_empty_log_another_writer_left_is_not_taken_for_the_batch_s_own(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)

    def an_empty_log(db):
        header = ",".join(swapped.log_row({**_entry("x"), "action": "updated"}, "execute", ACTOR))
        log = store / "exports" / "repair_swapped_club_names_log_20261017_020000.csv"
        log.write_text(header + "\n", encoding="utf-8-sig")

    _wire(monkeypatch, db, _Runner(db, during={"repair_swapped_club_names": an_empty_log}))

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert code == 0 and len(_ledger(db)) == 3


def test_an_attempt_with_no_recorded_end_stops_a_rerun(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)

    def killed(command, log):
        raise KeyboardInterrupt

    _wire(monkeypatch, db, killed)
    with pytest.raises(KeyboardInterrupt):
        _main(monkeypatch, capsys, store, "clubs", "--execute")
    monkeypatch.setattr(ap, "run_step", runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith("The pilot batch started ") and "has no recorded end" in message
    assert runner.commands == []


def test_a_revert_refuses_a_batch_with_no_recorded_end_rather_than_skipping_it(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    runner = _Runner(db)

    def killed_once_written(command, log):
        runner(command, log)
        raise KeyboardInterrupt

    _wire(monkeypatch, db, killed_once_written)
    with pytest.raises(KeyboardInterrupt):
        _main(monkeypatch, capsys, store, "clubs", "--execute")
    monkeypatch.setattr(ap, "run_step", runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("The pilot batch started ") and "has no recorded end" in message
    assert len(runner.commands) == 1 and [db.team(_id(n))["club_name"] for n in names] == [
        "Club c00",
        "Club c01",
        "Club c02",
    ]
    assert "Refused. The pilot batch started " in (stage_dir(store, RUN, "clubs") / "REVERT.md").read_text("utf-8")


# --- each stage's applier ------------------------------------------------------------------------


def test_the_age_applier_runs_with_the_name_hold_into_the_store_s_exports(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    rows = [_plan_row("g1", "u13", "u12"), _plan_row("g2", "u13", "u12", team_name="NV Storm 2010 Girls")]
    _ages(tmp_path, store, rows, {"g1": "apply", "g2": "apply"})
    db = _Db(teams=[_team("g1", age="u13"), _team("g2", age="u13", team_name="NV Storm 2010 Girls")])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "ages", "--execute")

    folder = stage_dir(store, RUN, "ages")
    assert code == 0
    assert runner.commands == [
        [
            "scripts/fix_band_cohorts.py",
            "--apply",
            str(folder / "pilot.csv"),
            "--execute",
            "--skip-name-contradictions",
            "--exports-dir",
            str(store / "exports"),
            "--actor",
            ACTOR,
        ]
    ]
    assert [(r["team_id_master"], r["old_value"], r["new_value"]) for r in _ledger(db)] == [(_id("g1"), "u13", "u12")]
    assert db.team(_id("g2"))["age_group"] == "u13"
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'NV Storm 2010 Girls': held_name_contradicts: name has birth year 2010, outside U12" in record


def test_states_split_the_stage_snapshot_with_the_hold_script_before_the_replay(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    decisions = [
        _decision("fill", None, "NV"),
        _decision("operator", "UT", "NV"),
        _decision("yuma-a", "CA", "NV", club="RSL-AZ Yuma"),
        _decision("yuma-b", "NV", "CA", club="RSL-AZ Yuma"),
        _decision("unsure", "WA", "NV", action="queue"),
    ]
    picks = {"fill": "apply", "operator": "apply", "yuma-a": "apply", "yuma-b": "dont_apply", "unsure": "apply"}
    folder = _states(tmp_path, store, decisions, picks)
    teams = [_team("fill", state=None), _team("operator", state="UT"), _team("yuma-a", state="CA")]
    teams += [_team("yuma-b"), _team("unsure", state="WA")]
    db = _Db(teams=teams)
    runner = _Runner(db, provenance={_id("operator"): "operator"})
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0
    assert runner.commands == [
        [
            "scripts/hold_unsafe_state_applies.py",
            str(folder / "national_snapshot.json"),
            str(folder / "safe.json"),
            str(folder / "held.json"),
        ],
        ["scripts/assign_team_states.py", "--execute", "--snapshot", str(folder / "pilot.json")],
    ]
    cut = read_json(folder / "pilot.json")
    assert [(d["team_id"], d["action"]) for d in cut["decisions"]] == [(_id("fill"), "apply")]
    assert (cut["rules"], cut["created_at"]) == ("authority", CREATED)
    assert [r["team_id_master"] for r in _ledger(db) if r["actor"] == "assign_team_states"] == [_id("fill")]
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "'Team operator': held, B would overwrite a operator value" in record
    assert "'Team yuma-a': held, club is sent to ['CA', 'NV'] in the same run (IMP-161)" in record


def test_the_hold_sees_a_club_sent_to_two_states_when_one_is_outside_the_run_s_scope(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    away = _decision("away", "CA", "AZ", club="RSL-AZ Yuma")
    folder = _states(
        tmp_path, store, [_decision("home", "UT", "NV", club="RSL-AZ Yuma")], {"home": "apply"}, elsewhere=[away]
    )
    db = _Db(teams=[_team("home", state="UT")])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and [Path(c[0]).name for c in runner.commands] == ["hold_unsafe_state_applies.py"]
    assert db.team(_id("home"))["state_code"] == "UT"
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "'Team home': held, club is sent to ['AZ', 'NV'] in the same run (IMP-161)" in record


def test_states_without_the_national_run_are_refused_before_the_hold(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("fill", None, "NV")], {"fill": "apply"})
    (folder / "national_snapshot.json").unlink()
    db = _Db(teams=[_team("fill", state=None)])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message == (
        f"Cannot apply the states stage of {RUN}: there is no {folder / 'national_snapshot.json'} for the hold "
        "script to read"
    )
    assert runner.commands == [] and db.team(_id("fill"))["state_code"] is None


def test_a_state_dry_run_runs_no_script_at_all(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("fill", None, "NV")], {"fill": "apply"})
    db = _Db(teams=[_team("fill", state=None)])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, out = _main(monkeypatch, capsys, store, "states")

    assert code == 0 and runner.commands == []
    hold_line = subprocess.list2cmdline(ap.hold_command(folder))
    assert f"  python {hold_line}\n" in out
    assert f"  pilot: scripts/assign_team_states.py over {folder / 'pilot.json'}    (1 rows)\n" in out
    assert "split: a pilot of 1:\n" in out


# --- state cards the rules only queued -----------------------------------------------------------


def _queue_row(name, proposed, status, n, current="WA"):
    return {
        "id": n,
        "team_id_master": _id(name),
        "current_state_code": current,
        "proposed_state_code": proposed,
        "tier": "B",
        "confidence": 0.9,
        "reason": "club-mates",
        "status": status,
        "reviewed_by": None,
        "reviewed_at": None,
    }


def test_queued_cards_are_approved_or_rejected_as_the_dashboard_would(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    names = ("pending-yes", "new-yes", "rejected-yes", "pending-no", "new-no", "approved-no")
    decisions = [_decision(name, "WA", "NV", action="queue", confidence=0.85) for name in names]
    picks = {name: "apply" if name.endswith("yes") else "dont_apply" for name in names}
    folder = _states(tmp_path, store, decisions, picks)
    queue = [_queue_row("pending-yes", "NV", "pending", 1), _queue_row("rejected-yes", "NV", "rejected", 2)]
    queue += [_queue_row("pending-no", "NV ", "pending", 3), _queue_row("approved-no", "NV", "approved", 4)]
    db = _Db(teams=[_team(name, state="WA") for name in names], team_state_review_queue=queue)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and runner.commands == []
    newest = {}
    for row in db.tables["team_state_review_queue"]:
        newest[row["team_id_master"]] = row
    status = {name: newest[_id(name)]["status"] for name in names}
    assert status == {
        "pending-yes": "approved",
        "new-yes": "approved",
        "rejected-yes": "approved",
        "pending-no": "rejected",
        "new-no": "rejected",
        "approved-no": "approved",
    }
    filed = [e[2] for e in db.executes if e[:2] == ("team_state_review_queue", "insert")]
    assert [row["team_id_master"] for row in filed] == [_id("new-yes"), _id("rejected-yes"), _id("new-no")]
    assert filed[2] == {
        "team_id_master": _id("new-no"),
        "current_state_code": "WA",
        "proposed_state_code": "NV",
        "tier": "B",
        "confidence": 0.85,
        "reason": "club-mates",
    }
    assert {name: db.team(_id(name))["state_code"] for name in names} == {
        "pending-yes": "NV",
        "new-yes": "NV",
        "rejected-yes": "NV",
        "pending-no": "WA",
        "new-no": "WA",
        "approved-no": "WA",
    }
    assert {(r["team_id_master"], r["actor"], r["applier"]) for r in _ledger(db)} == {
        (_id(name), ACTOR, "scripts/team_cleanup/apply_stage.py") for name in ("pending-yes", "new-yes", "rejected-yes")
    }
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team approved-no' to NV, dont_apply: already approved; Don't apply does not undo it" in record


def test_a_queued_card_whose_team_moved_is_reported_not_retried(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("moved", "WA", "NV", action="queue")], {"moved": "apply"})
    db = _Db(teams=[_team("moved", state="OR")], team_state_review_queue=[_queue_row("moved", "NV", "pending", 1)])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("moved"))["state_code"] == "OR"
    assert db.tables["team_state_review_queue"][0]["status"] == "pending"
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert f"refused: Team {_id('moved')} has moved or gone since review 1; review 1 stays pending" in record


@pytest.mark.parametrize(
    "current, decision, state, status",
    [("UT", "apply", "UT", "pending"), ("WA", "apply", "NV", "approved"), ("UT", "dont_apply", "UT", "rejected")],
    ids=["refiled-from-another-state", "from-the-card-s-state", "dont-apply-refiled"],
)
def test_apply_approves_a_pending_row_only_from_the_state_the_card_showed(
    tmp_path, monkeypatch, capsys, current, decision, state, status
):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": decision})
    # After the collect another writer may have moved the team, and a later sweep refiled its row from there.
    db = _Db(teams=[_team("q", state=current)], team_state_review_queue=[_queue_row("q", "NV", "pending", 1, current)])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == state
    assert db.tables["team_state_review_queue"][0]["status"] == status
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert ("- 'Team q' to NV, apply: moved since the choices were collected" in record) is (status == "pending")


def _sweep_files(db, name, state):
    """A sweep moving the team to ``state`` and filing its (team, NV) review from there, refreshing a pending
    row in place as assign_team_states does."""
    db.team(_id(name))["state_code"] = state
    pending = {(r["team_id_master"], r["proposed_state_code"]): r for r in db.tables["team_state_review_queue"]}
    ats.queue_decision(db, _decision(name, state, "NV", action="queue"), pending)


@pytest.mark.parametrize("when", ["during-the-queue-s-writer-check", "after-the-queue-is-read"])
def test_a_row_a_sweep_refiles_before_the_approval_is_skipped_as_moved(tmp_path, monkeypatch, capsys, when):
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    asked = []

    def gh(status):
        asked.append(status)
        # The apply's first check asks for each of the five unfinished statuses; the queue's asks again.
        if when == "during-the-queue-s-writer-check" and len(asked) == 6:
            _sweep_files(db, "q", "UT")
        return []

    monkeypatch.setattr(ap, "gh_runs", gh)
    if when == "after-the-queue-is-read":
        db.hooks[("team_state_review_queue", "select")] = [lambda db: _sweep_files(db, "q", "UT")]

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == "UT"
    assert [r["status"] for r in db.tables["team_state_review_queue"]] == ["pending"]
    assert [r for r in db.tables["team_state_audit"] if r["action"] == "approve"] == []
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team q' to NV, apply: moved since the choices were collected" in record


def test_a_row_settled_after_the_queue_is_read_is_skipped_rather_than_sent_for_approval(tmp_path, monkeypatch, capsys):
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    db.hooks[("team_state_review_queue", "select")] = [lambda db: db.rpc_reject_team_state(1, "dashboard-user")]

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == "WA"
    assert [e for e in db.executes if e[:2] == ("approve_team_state", "rpc")] == []
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team q' to NV, apply: moved since the choices were collected" in record


def test_a_row_a_sweep_files_during_the_queue_s_writer_check_is_approved_rather_than_filed_twice(
    tmp_path, monkeypatch, capsys
):
    store, folder, db = _queued_card(tmp_path, monkeypatch, queue=False)
    asked = []

    def gh(status):
        asked.append(status)
        if len(asked) == 6:
            _sweep_files(db, "q", "WA")
        return []

    monkeypatch.setattr(ap, "gh_runs", gh)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == "NV"
    assert [r["status"] for r in db.tables["team_state_review_queue"]] == ["approved"]


@pytest.mark.parametrize("change", ["the-window-closed", "a-writer-started"])
def test_the_queue_waits_for_the_window_and_for_a_writer_that_started_during_the_pilot(
    tmp_path, monkeypatch, capsys, change
):
    store = _store(tmp_path)
    decisions = [_decision("fill", None, "NV"), _decision("q", "WA", "NV", action="queue")]
    folder = _states(tmp_path, store, decisions, {"fill": "apply", "q": "apply"})
    db = _Db(teams=[_team("fill", state=None), _team("q", state="WA")])
    busy = []

    def during_the_pilot(db):
        if change == "the-window-closed":
            monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)
        else:
            busy.append(True)

    gh = _busy("fill-team-states-weekly.yml", 7, lambda: busy)
    _wire(monkeypatch, db, _Runner(db, during={"assign_team_states": during_the_pilot}), gh=gh)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    expected = "Outside the apply window" if change == "the-window-closed" else "Not applying while another writer"
    assert message.startswith(expected)
    assert db.team(_id("q"))["state_code"] == "WA" and not [e for e in db.executes if e[1] == "rpc"]
    assert read_json(folder / "apply.json")["queue"] == []


@pytest.mark.parametrize(
    "rpc, code, message",
    [
        ("approve_team_state", "PGRST202", "Could not find the function public.approve_team_state"),
        ("approve_team_state", "57014", "canceling statement due to statement timeout"),
        ("reject_team_state", "42501", "permission denied for function reject_team_state"),
    ],
    ids=["no-such-function", "timeout", "wrong-key"],
)
def test_a_queue_refusal_that_is_not_the_card_s_stops_the_stage(tmp_path, monkeypatch, capsys, rpc, code, message):
    store = _store(tmp_path)
    decision = "apply" if rpc == "approve_team_state" else "dont_apply"
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": decision})
    db = _Db(teams=[_team("q", state="WA")], team_state_review_queue=[_queue_row("q", "NV", "pending", 1)])
    db.refuse[(rpc, "rpc")] = _api_error(code, message)
    _wire(monkeypatch, db, _Runner(db))

    refused = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert refused.startswith(f"Could not settle 'Team q''s review: {message}")
    assert db.tables["team_state_review_queue"][0]["status"] == "pending" and not (folder / "RECORD.md").exists()


@pytest.mark.parametrize("hours, expected", [(20, "WA"), (-20, "NV")], ids=["since-the-collect", "before-it"])
def test_a_dashboard_reject_made_since_the_choices_were_collected_wins_over_apply(
    tmp_path, monkeypatch, capsys, hours, expected
):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    collected_at = read_json(folder / "collected.json")["collected_at"]
    reviewed = (_instant(collected_at) + timedelta(hours=hours)).isoformat()
    row = {**_queue_row("q", "NV", "rejected", 1), "reviewed_by": "dashboard", "reviewed_at": reviewed}
    db = _Db(teams=[_team("q", state="WA")], team_state_review_queue=[row])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == expected
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert ("- 'Team q' to NV, apply: rejected since the choices were collected" in record) is (expected == "WA")


def test_a_queued_card_left_not_sure_leaves_its_review_pending(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("maybe", "WA", "NV", action="queue")], {"maybe": "unsure"})
    db = _Db(teams=[_team("maybe", state="WA")], team_state_review_queue=[_queue_row("maybe", "NV", "pending", 1)])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.tables["team_state_review_queue"][0]["status"] == "pending"


def test_dont_apply_rejects_the_newest_pending_row_over_an_older_approval(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("back", "WA", "NV", action="queue")], {"back": "dont_apply"})
    queue = [_queue_row("back", "NV", "approved", 1), _queue_row("back", "NV", "pending", 2)]
    db = _Db(teams=[_team("back", state="WA")], team_state_review_queue=queue)
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and [r["status"] for r in db.tables["team_state_review_queue"]] == ["approved", "rejected"]


def test_an_approval_the_database_no_longer_holds_stops_the_stage(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    db = _Db(teams=[_team("q", state="WA")], team_state_review_queue=[_queue_row("q", "NV", "pending", 1)])
    _wire(monkeypatch, db, _Runner(db))
    db.hooks[("team_state_audit", "select")] = [lambda db: db.team(_id("q")).update(state_code="OR")]

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message.startswith("Stopped: 1 approved state(s) the database does not hold")
    assert not (folder / "RECORD.md").exists()


def test_the_queue_is_settled_only_while_the_lease_is_still_this_apply_s(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    decisions = [_decision("fill", None, "NV"), _decision("q", "WA", "NV", action="queue")]
    _states(tmp_path, store, decisions, {"fill": "apply", "q": "apply"})
    db = _Db(teams=[_team("fill", state=None), _team("q", state="WA")])

    def taken_over(db):
        db.tables["team_cleanup_runs"][0].update(lease_holder="other-host:2", lease_expires_at=_now())

    _wire(monkeypatch, db, _Runner(db, during={"assign_team_states": taken_over}))

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message.startswith(f"Run {RUN}'s lease is no longer ") and message.endswith(
        "so the queued cards were not settled."
    )
    assert db.team(_id("q"))["state_code"] == "WA" and db.tables["team_state_review_queue"] == []


def test_a_lost_approval_stops_and_a_rerun_settles_it_once_counting_each_batch_its_own(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    fills = [f"f{n:02d}" for n in range(52)]
    decisions = [_decision(name, None, "NV") for name in fills] + [_decision("q", "WA", "NV", action="queue")]
    folder = _states(tmp_path, store, decisions, {name: "apply" for name in [*fills, "q"]})
    db = _Db(teams=[_team(name, state=None) for name in fills] + [_team("q", state="WA")])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message.startswith("Could not settle 'Team q''s review: the database's answer was lost")
    assert db.team(_id("q"))["state_code"] == "NV" and not (folder / "RECORD.md").exists()

    code, out = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and [Path(c[0]).name for c in runner.commands].count("assign_team_states.py") == 2
    assert "pilot: 50 written" in out and "rest: 2 written" in out
    assert [r["status"] for r in db.tables["team_state_review_queue"]] == ["approved"]
    assert len(_ledger(db)) == 53
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team q' to NV, apply: already approved" in record


def _an_hour_earlier(stamp):
    return (_instant(stamp) - timedelta(hours=1)).isoformat()


def _queued_card(tmp_path, monkeypatch, queue=True):
    """A states stage of one queued card, WA -> NV chosen Apply, with its review row pending unless
    ``queue`` is False."""
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    rows = [_queue_row("q", "NV", "pending", 1)] if queue else []
    db = _Db(teams=[_team("q", state="WA")], team_state_review_queue=rows)
    _wire(monkeypatch, db, _Runner(db))
    return store, folder, db


def _database_clock(monkeypatch, minutes):
    """The database's clock set ``minutes`` off this machine's: it stamps every audit row the double writes."""
    monkeypatch.setattr(
        sys.modules[__name__], "_now", lambda: (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    )


def _outside(row, where, step):
    """An unreachable write as the apply and the revert list it."""
    return (
        f"{row['team_id_master']}: {row['action']} {row['old_state_code']} -> {row['new_state_code']} by "
        f"{row['applied_by']} at {row['applied_at']} (audit row {row['id']}), outside the window of {where}, started "
        f"{step['started_at']}"
    )


def _unreachable(folder, *lines):
    """What the apply and the revert both say of the stage's own writes its revert could not reach."""
    path = folder / "apply.json"
    return (
        f"{len(lines)} of the stage's own state write(s) or approval(s) the revert could not reach, since it reads "
        f"only the windows {path} saves for the steps that made them:\n  " + "\n  ".join(lines) + "\nIf this "
        "machine's clock is wrong, set it right first, or a batch still to run will stop the same way. Then in "
        f"{path} widen each named step's started_at or ended_at to cover the time listed with it, written as a full "
        "ISO time with its offset, or do what a line with no time says, and re-run."
    )


def _widen(folder, steps, n, key, stamp):
    """A step's window widened by hand in apply.json, as the stop asks."""
    path = folder / "apply.json"
    progress = read_json(path)
    progress[steps][n][key] = stamp
    write_json(path, progress, indent=1)


def test_an_approval_from_an_earlier_queue_step_is_ledgered_on_a_later_rerun(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    db = _Db(teams=[_team("q", state="WA")], team_state_review_queue=[_queue_row("q", "NV", "pending", 1)])
    _wire(monkeypatch, db, _Runner(db))
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    # The re-run comes an hour later, so the two queue steps' windows do not touch.
    path = folder / "apply.json"
    progress = read_json(path)
    for key in ("started_at", "ended_at"):
        progress["queue"][0][key] = _an_hour_earlier(progress["queue"][0][key])
    write_json(path, progress, indent=1)
    for row in db.tables["team_state_audit"]:
        row["applied_at"] = _an_hour_earlier(row["applied_at"])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0

    assert [(r["team_id_master"], r["actor"]) for r in _ledger(db)] == [(_id("q"), ACTOR)]


def test_an_approval_refused_once_and_made_by_a_later_step_is_ledgered(tmp_path, monkeypatch, capsys):
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    db.refuse[("approve_team_state", "rpc")] = _api_error("57014", "canceling statement due to statement timeout")
    assert _refused(monkeypatch, capsys, store, "states", "--execute").startswith("Could not settle")
    # The owner re-runs an hour later, so the two queue steps' windows do not touch.
    path = folder / "apply.json"
    progress = read_json(path)
    assert progress["queue"][0]["reviews"] == [1]
    for key in ("started_at", "ended_at"):
        progress["queue"][0][key] = _an_hour_earlier(progress["queue"][0][key])
    write_json(path, progress, indent=1)

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0

    assert [(r["team_id_master"], r["actor"]) for r in _ledger(db)] == [(_id("q"), ACTOR)]


def test_an_unreachable_approval_names_the_nearest_of_the_steps_that_settled_its_review(tmp_path, monkeypatch, capsys):
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    db.refuse[("approve_team_state", "rpc")] = _api_error("57014", "canceling statement due to statement timeout")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    path = folder / "apply.json"
    progress = read_json(path)
    for key in ("started_at", "ended_at"):
        progress["queue"][0][key] = _an_hour_earlier(progress["queue"][0][key])
    write_json(path, progress, indent=1)
    _database_clock(monkeypatch, 5)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    [audit] = db.tables["team_state_audit"]
    steps = read_json(path)["queue"]
    assert [step["reviews"] for step in steps] == [[1], [1]]
    assert message == f"Stopped: {_unreachable(folder, _outside(audit, 'queue[1]', steps[1]))}"


def test_a_dashboard_approval_of_the_stage_s_review_is_not_ledgered_as_the_run_s(tmp_path, monkeypatch, capsys):
    """The dashboard approves review 1 between the stage's last read of it and its own approve, which the
    database then refuses as already reviewed: the dashboard's write is not this run's."""
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    approve = db.rpc_approve_team_state

    def the_dashboard_first(p_review_id, p_approver):
        approve(p_review_id, "dashboard-user")
        return approve(p_review_id, p_approver)

    monkeypatch.setattr(db, "rpc_approve_team_state", the_dashboard_first)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == "NV"
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team q' to NV, apply: refused: State review 1 not found or already reviewed" in record
    assert _ledger(db) == []


def test_an_approval_of_a_review_no_queue_step_settled_is_not_ledgered_and_the_revert_refuses_it(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    db = _Db(teams=[_team("q", state="WA"), _team("other", state="AZ")])
    _wire(monkeypatch, db, _Runner(db))

    def another_approval(db):
        # approve_team_state called under the same approver, for a review the stage never settled
        db.team(_id("other"))["state_code"] = "NV"
        db.audit(_id("other"), "AZ", "NV", ACTOR, "approved review 77", "approve")

    db.hooks[("team_state_review_queue", "insert")] = [another_approval]

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and [r["team_id_master"] for r in _ledger(db)] == [_id("q")]
    _after_the_windows(monkeypatch)
    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")
    assert message.startswith("Not reverting: these writes fall in the stage's windows but are not the stage's own")
    assert f"{_id('other')}: approve AZ -> NV by {ACTOR}" in message


def test_an_approval_audited_outside_its_queue_step_s_window_stops_until_the_window_is_widened_over_it(
    tmp_path, monkeypatch, capsys
):
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    database_clock = _now
    _database_clock(monkeypatch, 5)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    [audit] = db.tables["team_state_audit"]
    [step] = read_json(folder / "apply.json")["queue"]
    unreachable = _unreachable(folder, _outside(audit, "queue[0]", step))
    assert message == f"Stopped: {unreachable}"
    assert _ledger(db) == [] and not (folder / "RECORD.md").exists()
    # The revert refuses the same way, rather than reverting the window and reporting success.
    assert _refused(monkeypatch, capsys, store, "states", "--revert", "--execute") == f"Not reverting: {unreachable}"
    assert _reverts(db) == [] and db.team(_id("q"))["state_code"] == "NV"

    # As the stop says: the clocks set right, then the step's end widened over the listed time.
    monkeypatch.setattr(sys.modules[__name__], "_now", database_clock)
    _widen(folder, "queue", 0, "ended_at", audit["applied_at"])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    assert [(r["team_id_master"], r["actor"]) for r in _ledger(db)] == [(_id("q"), ACTOR)]
    _after_the_windows(monkeypatch)
    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert db.team(_id("q"))["state_code"] == "WA" and all(r["reverted_at"] for r in _ledger(db))


def test_an_approval_audited_before_its_queue_step_s_window_stops_until_its_start_is_widened_over_it(
    tmp_path, monkeypatch, capsys
):
    """The database's clock runs behind, and the apply was killed while the approval's answer was on its way:
    the owner records the step's end as told, and the start bound is what leaves the approval out."""
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    database_clock = _now
    _database_clock(monkeypatch, -5)
    path, saved = folder / "apply.json", []
    approve = db.rpc_approve_team_state

    def approve_as_saved(p_review_id, p_approver):
        saved.append(path.read_text(encoding="utf-8"))
        return approve(p_review_id, p_approver)

    monkeypatch.setattr(db, "rpc_approve_team_state", approve_as_saved)
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    path.write_text(saved[0], encoding="utf-8")  # a hard kill while the approval was sent
    monkeypatch.setattr(sys.modules[__name__], "_now", database_clock)
    [audit] = db.tables["team_state_audit"]
    _widen(folder, "queue", 0, "ended_at", _now())
    [step] = read_json(path)["queue"]
    unreachable = _unreachable(folder, _outside(audit, "queue[0]", step))

    assert _refused(monkeypatch, capsys, store, "states", "--revert", "--execute") == f"Not reverting: {unreachable}"
    assert _refused(monkeypatch, capsys, store, "states", "--execute") == f"Stopped: {unreachable}"
    assert _reverts(db) == [] and db.team(_id("q"))["state_code"] == "NV"

    _widen(folder, "queue", 0, "started_at", audit["applied_at"])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    assert [r["team_id_master"] for r in _ledger(db)] == [_id("q")]
    _after_the_windows(monkeypatch)
    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert db.team(_id("q"))["state_code"] == "WA" and all(r["reverted_at"] for r in _ledger(db))


def test_a_queue_step_end_recorded_too_early_stops_until_it_is_widened_over_the_approval(tmp_path, monkeypatch, capsys):
    """The apply was killed while settling a long queue, and the owner recorded the step's end before the
    approval that landed ten minutes into it."""
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    path, saved = folder / "apply.json", []
    approve = db.rpc_approve_team_state

    def approve_as_saved(p_review_id, p_approver):
        saved.append(path.read_text(encoding="utf-8"))
        return approve(p_review_id, p_approver)

    monkeypatch.setattr(db, "rpc_approve_team_state", approve_as_saved)
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    path.write_text(saved[0], encoding="utf-8")  # a hard kill while the approval was sent
    [audit] = db.tables["team_state_audit"]
    audit["applied_at"] = (_instant(audit["applied_at"]) + timedelta(minutes=10)).isoformat()
    [step] = read_json(path)["queue"]
    _widen(folder, "queue", 0, "ended_at", step["started_at"])
    after_the_approval = (_instant(audit["applied_at"]) + timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(ap, "utc_now_iso", lambda: after_the_approval)
    unreachable = _unreachable(folder, _outside(audit, "queue[0]", step))

    assert _refused(monkeypatch, capsys, store, "states", "--revert", "--execute") == f"Not reverting: {unreachable}"
    assert _refused(monkeypatch, capsys, store, "states", "--execute") == f"Stopped: {unreachable}"
    assert _reverts(db) == [] and db.team(_id("q"))["state_code"] == "NV"

    _widen(folder, "queue", 0, "ended_at", audit["applied_at"])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    assert [r["team_id_master"] for r in _ledger(db)] == [_id("q")]
    every_window_closed = (_instant(audit["applied_at"]) + timedelta(minutes=30)).isoformat()
    monkeypatch.setattr(ap, "utc_now_iso", lambda: every_window_closed)
    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert db.team(_id("q"))["state_code"] == "WA" and all(r["reverted_at"] for r in _ledger(db))


def test_an_approval_with_no_audit_row_stops_every_rerun_until_its_review_leaves_the_step(
    tmp_path, monkeypatch, capsys
):
    store, folder, db = _queued_card(tmp_path, monkeypatch)

    def approve_writing_nothing(p_review_id, p_approver):
        db.tables["team_state_review_queue"][0].update(status="approved", reviewed_by=p_approver, reviewed_at=_now())
        return True

    monkeypatch.setattr(db, "rpc_approve_team_state", approve_writing_nothing)
    stop = "Stopped: " + _unreachable(
        folder,
        "review 1 ('Team q') in queue[0]: approved, with no audit row; if team_state_audit holds none for it, the "
        "approval wrote nothing, so remove 1 from queue[0].reviews",
    )

    assert _refused(monkeypatch, capsys, store, "states", "--execute") == stop
    assert _refused(monkeypatch, capsys, store, "states", "--execute") == stop
    assert not (folder / "RECORD.md").exists()

    # As the stop says: team_state_audit holds no row for review 1, so it leaves the step's reviews.
    _widen(folder, "queue", 0, "reviews", [])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    assert (folder / "RECORD.md").exists() and _ledger(db) == []


def test_a_review_is_saved_before_it_is_settled_and_a_rerun_refuses_a_queue_step_with_no_recorded_end(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    db = _Db(teams=[_team("q", state="WA")], team_state_review_queue=[_queue_row("q", "NV", "pending", 1)])
    _wire(monkeypatch, db, _Runner(db))
    path, saved = folder / "apply.json", []
    approve = db.rpc_approve_team_state

    def approve_as_saved(p_review_id, p_approver):
        saved.append(path.read_text(encoding="utf-8"))
        return approve(p_review_id, p_approver)

    monkeypatch.setattr(db, "rpc_approve_team_state", approve_as_saved)
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    # A hard kill while the approval was sent leaves apply.json as it stood then.
    path.write_text(saved[0], encoding="utf-8")
    [step] = read_json(path)["queue"]
    assert (step["reviews"], step["ended_at"]) == ([1], None)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message == (
        f"The review-queue step started {step['started_at']} has no recorded end: an apply was stopped while it "
        f"settled cards. The reviews it settled are saved in {path}; record there when it stopped as the step's "
        "ended_at, a full ISO time with its offset, before applying or reverting again. Both then check that each "
        "approval it made lies inside its window, and name any that does not."
    )
    assert len(saved) == 1 and len(read_json(path)["queue"]) == 1


def test_recording_the_queue_step_s_end_as_told_lets_the_apply_and_its_revert_finish(tmp_path, monkeypatch, capsys):
    store, folder, db = _queued_card(tmp_path, monkeypatch)
    path, saved = folder / "apply.json", []
    approve = db.rpc_approve_team_state

    def approve_as_saved(p_review_id, p_approver):
        saved.append(path.read_text(encoding="utf-8"))
        return approve(p_review_id, p_approver)

    monkeypatch.setattr(db, "rpc_approve_team_state", approve_as_saved)
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    path.write_text(saved[0], encoding="utf-8")  # a hard kill while the approval was sent
    assert _refused(monkeypatch, capsys, store, "states", "--execute").startswith("The review-queue step started")
    [audit] = db.tables["team_state_audit"]
    _widen(folder, "queue", 0, "ended_at", audit["applied_at"])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0

    assert [r["team_id_master"] for r in _ledger(db)] == [_id("q")]
    _after_the_windows(monkeypatch)
    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert db.team(_id("q"))["state_code"] == "WA" and all(r["reverted_at"] for r in _ledger(db))


@pytest.mark.parametrize("flags", [("--revert", "--execute"), ("--revert",), ("--execute",)])
def test_a_step_time_recorded_without_its_offset_is_refused_naming_it(tmp_path, monkeypatch, capsys, flags):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    path = stage_dir(store, RUN, "states") / "apply.json"
    progress = read_json(path)
    progress["queue"][0]["ended_at"] = "2026-10-17 11:30"
    write_json(path, progress, indent=1)
    (path.parent / "RECORD.md").unlink()

    message = _refused(monkeypatch, capsys, store, "states", *flags)

    what = "revert" if "--revert" in flags else "apply"
    assert message == (
        f"Cannot {what} the states stage of {RUN}: {path} holds queue[0].ended_at '2026-10-17 11:30'; write each as "
        "a full ISO time with its offset, such as 2026-10-17T18:30:00-07:00"
    )
    assert _reverts(db) == [] and db.team(_id("q"))["state_code"] == "NV"


@pytest.mark.parametrize(
    "edit, lacks",
    [
        (lambda step: step.update(endedat=step.pop("ended_at")), "queue[0].ended_at"),
        (lambda step: step["cards"][0].pop("review_id"), "queue[0].cards[0].review_id"),
    ],
    ids=["a-step-key-misspelled", "a-card-without-its-review"],
)
@pytest.mark.parametrize("flags", [("--revert", "--execute"), ("--execute",)], ids=["revert", "apply"])
def test_a_hand_edited_progress_file_is_refused_naming_what_it_lacks(tmp_path, monkeypatch, capsys, edit, lacks, flags):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    path = stage_dir(store, RUN, "states") / "apply.json"
    progress = read_json(path)
    edit(progress["queue"][0])
    write_json(path, progress, indent=1)
    (path.parent / "RECORD.md").unlink()

    message = _refused(monkeypatch, capsys, store, "states", *flags)

    what = "revert" if "--revert" in flags else "apply"
    assert message == f"Cannot {what} the states stage of {RUN}: {path} lacks {lacks}"
    assert _reverts(db) == [] and db.team(_id("q"))["state_code"] == "NV"


def test_a_revert_refuses_a_queue_step_with_no_recorded_end_rather_than_waiting_for_ever(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    path = stage_dir(store, RUN, "states") / "apply.json"
    progress = read_json(path)
    progress["queue"][0]["ended_at"] = None
    write_json(path, progress, indent=1)
    monkeypatch.setattr(ap, "utc_now_iso", lambda: (datetime.now(timezone.utc) + timedelta(days=30)).isoformat())

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    started = progress["queue"][0]["started_at"]
    assert message.startswith(f"The review-queue step started {started} has no recorded end") and str(path) in message
    assert _reverts(db) == [] and db.team(_id("q"))["state_code"] == "NV"
    code, out = _main(monkeypatch, capsys, store, "states", "--revert")
    assert code == 0 and f"It would refuse. The review-queue step started {started}" in out


# --- the ledger ----------------------------------------------------------------------------------


def test_the_ledger_holds_only_what_the_log_marks_applied_and_the_database_holds(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    rows = [_scan_row("done", "LVSA", "=Club done"), _scan_row("moved", "LVSA", "Club moved")]
    _clubs(tmp_path, store, rows, {"done": "apply", "moved": "apply"})
    db = _Db(teams=[_team("done", club="LVSA"), _team("moved", club="Henderson FC")])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    [log] = sorted((store / "exports").glob("repair_swapped_club_names_log_*.csv"))
    assert code == 0
    assert [{k: v for k, v in r.items() if k not in ("id", "applied_at")} for r in _ledger(db)] == [
        {
            "run_id": RUN,
            "stage": "clubs",
            "team_id_master": _id("done"),
            "field": "club_name",
            "old_value": "LVSA",
            "new_value": "=Club done",
            "applier": "scripts/repair_swapped_club_names.py",
            "actor": ACTOR,
            "log_file": str(log),
            "reverted_at": None,
        }
    ]
    record = (stage_dir(store, RUN, "clubs") / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team moved': skipped_changed_since_snapshot" in record


def _entry(name, before="LVSA", after=None):
    team_id = _id(name)
    return {"team_id_master": team_id, "source": "team_name", "tier": "swap", "before": before, "after": after or name}


def _cut_of(tmp_path, names):
    cut = tmp_path / "pilot.csv"
    swapped.write_log([{"team_id_master": _id(name)} for name in names], cut)
    return str(cut)


def test_a_club_log_s_dry_run_rows_are_never_read_as_changes(tmp_path):
    log = tmp_path / "repair_swapped_club_names_log_20261017_010000.csv"
    rows = [
        swapped.log_row({**_entry("a", after="=Club a"), "action": "updated"}, "execute", ACTOR),
        swapped.log_row({**_entry("b"), "action": "updated"}, "dry-run", ACTOR),
        swapped.log_row({**_entry("c"), "action": "skipped_already_applied"}, "execute", ACTOR),
    ]
    swapped.write_log(rows, log)
    batch = {"exit": 0, "logs": [str(log)], "cut": _cut_of(tmp_path, "abc"), "ended_at": "2026-10-17T01:00:00+00:00"}

    changes, skipped = ap.batch_changes(None, RUN, "clubs", batch)

    assert [(c["team_id_master"], c["old_value"], c["new_value"]) for c in changes] == [(_id("a"), "LVSA", "=Club a")]
    assert skipped == [[_id("c"), "skipped_already_applied"]]


class _RealAgeFixer(_Runner):
    """Runs the age fixer's own main() on the command the apply builds, an exception it raises exiting 1 as
    the script's would. The test points the fixer's client at the double."""

    def fix_band_cohorts(self, command, log):
        argv, sys.argv = sys.argv, command
        try:
            bands.main()
        except Exception:
            return 1
        finally:
            sys.argv = argv
        return 0


def _lose_the_answer_to_write(db, n, error):
    """``error`` raised once the ``n``-th write to teams has landed, as a dropped connection does."""
    landed = []

    def count(db):
        landed.append(True)
        if len(landed) == n:
            db.lost[("teams", "update")] = error
        else:
            db.hooks[("teams", "update")] = [count]

    db.hooks[("teams", "update")] = [count]


def test_an_age_apply_stopped_part_way_ledgers_its_writes_and_never_a_row_it_only_planned(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    names = sorted((f"a{n}" for n in range(6)), key=_id)
    kept = "kept"
    _ages(tmp_path, store, [_plan_row(n, "u13", "u12") for n in [*names, kept]], {n: "apply" for n in [*names, kept]})
    teams = [_team(n, age="u13") for n in [*names, kept]]
    # Another writer already set the last team the fixer would reach to the same new age.
    teams[5]["age_group"] = "u12"
    db = _Db(teams=teams)
    monkeypatch.setattr(bands, "load_owner_decisions", lambda sb: {_id(kept): ("keep", "2026-10-01, leave it")})
    monkeypatch.setattr(bands, "load_env", lambda: None)
    monkeypatch.setattr(bands, "get_supabase", lambda: db)
    _lose_the_answer_to_write(db, 3, httpx.RemoteProtocolError("connection closed"))
    _wire(monkeypatch, db, _RealAgeFixer(db))

    message = _refused(monkeypatch, capsys, store, "ages", "--execute")

    [log] = (store / "exports").glob("fix_band_cohorts_apply_*.csv")
    results = Counter(row["result"] for row in bands.read_our_csv(log))
    assert message.startswith("Stopped after the pilot batch: its applier exited 1")
    assert results == {"updated": 2, bands.UNCONFIRMED: 1, "planned_not_applied": 3, "held_owner_decision": 1}
    assert [r["team_id_master"] for r in _ledger(db)] == sorted(_id(n) for n in names[:3])
    [batch] = read_json(stage_dir(store, RUN, "ages") / "apply.json")["batches"]
    assert batch["skipped"] == [
        *([_id(n), "planned_not_applied"] for n in names[3:]),
        [_id(kept), "held_owner_decision: owner decision keep: 2026-10-01, leave it"],
    ]


def test_ledgering_again_clears_reverted_at_rather_than_adding_a_row(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=1)
    stale = {"id": "x1", "run_id": RUN, "stage": "clubs", "team_id_master": _id("c00"), "field": "club_name"}
    stale.update({"old_value": "LVSA", "new_value": "Club c00", "applier": "a", "actor": "b", "log_file": None})
    stale.update({"applied_at": "2026-10-10T00:00:00+00:00", "reverted_at": "2026-10-11T00:00:00+00:00"})
    db.tables["team_cleanup_changes"].append(stale)
    _wire(monkeypatch, db, _Runner(db))

    _main(monkeypatch, capsys, store, "clubs", "--execute")

    [row] = _ledger(db)
    assert row["id"] == "x1" and row["reverted_at"] is None and row["applied_at"] != "2026-10-10T00:00:00+00:00"


# --- the dry run and RECORD.md -------------------------------------------------------------------


def _files(store):
    return {str(p): p.stat().st_mtime_ns for p in store.rglob("*") if p.is_file()}


def _one_change_week(tmp_path, stage):
    """A stage with one card chosen Apply, and for states a queued card chosen Don't apply."""
    store = _store(tmp_path)
    if stage == "clubs":
        _clubs(tmp_path, store, [_scan_row("t1", "LVSA", "Club t1")], {"t1": "apply"})
        return store, _Db(teams=[_team("t1", club="LVSA")])
    if stage == "states":
        decisions = [_decision("t1", None, "NV"), _decision("t2", "WA", "NV", action="queue")]
        _states(tmp_path, store, decisions, {"t1": "apply", "t2": "dont_apply"})
        return store, _Db(teams=[_team("t1", state=None), _team("t2", state="WA")])
    _ages(tmp_path, store, [_plan_row("t1", "u13", "u12")], {"t1": "apply"})
    return store, _Db(teams=[_team("t1", age="u13")])


@pytest.mark.parametrize("stage", ["clubs", "states", "ages"])
def test_a_dry_run_writes_nothing_and_runs_nothing(tmp_path, monkeypatch, capsys, stage):
    store, db = _one_change_week(tmp_path, stage)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner, now=MONDAY_MORNING)
    before = _files(store)

    code, out = _main(monkeypatch, capsys, store, stage)

    assert code == 0 and out.startswith(f"DRY RUN -- {stage} for run {RUN}")
    assert db.writes() == [] and runner.commands == [] and _files(store) == before


@pytest.mark.parametrize(
    "stage, applier",
    [
        ("clubs", "scripts/repair_swapped_club_names.py"),
        ("states", "scripts/assign_team_states.py"),
        ("ages", "scripts/fix_band_cohorts.py"),
    ],
)
def test_a_dry_run_names_each_batch_s_applier_but_hands_out_no_command_that_writes(
    tmp_path, monkeypatch, capsys, stage, applier
):
    store, db = _one_change_week(tmp_path, stage)
    _wire(monkeypatch, db, _Runner(db), now=MONDAY_MORNING)

    _, out = _main(monkeypatch, capsys, store, stage)

    assert f"  pilot: {applier} over " in out
    assert [line for line in out.splitlines() if "--execute" in line] == [
        "Re-run with --execute to apply it, inside the apply window or with --outside-window."
    ]


def test_dry_run_wins_over_execute(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, out = _main(monkeypatch, capsys, store, "clubs", "--execute", "--dry-run")

    assert code == 0 and out.startswith(f"DRY RUN -- clubs for run {RUN}")
    assert db.writes() == [] and runner.commands == []


@pytest.mark.parametrize("flags", [(), ("--execute", "--dry-run")], ids=["dry-run", "dry-run-over-execute"])
def test_a_dry_run_that_loses_an_answer_hands_back_a_dry_run(tmp_path, monkeypatch, capsys, flags):
    store, db, _ = _club_week(tmp_path)
    _wire(monkeypatch, db, _Runner(db))
    db.lost[("team_cleanup_decisions", "select")] = httpx.ReadTimeout("timed out")

    message = _refused(monkeypatch, capsys, store, "clubs", *flags)

    command = ["scripts/team_cleanup/apply_stage.py", "--run", RUN, "--stage", "clubs", "--store", str(store)]
    assert message == (
        f"Cannot apply the clubs stage of {RUN}: the database's answer was lost (ReadTimeout: timed out); re-run to "
        f"see where it stands: python {subprocess.list2cmdline(command)}"
    )


def test_a_revert_dry_run_that_loses_an_answer_hands_back_a_revert_dry_run(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    db.lost[("team_state_audit", "select")] = httpx.ReadTimeout("timed out")

    message = _refused(monkeypatch, capsys, store, "states", "--revert")

    command = ["scripts/team_cleanup/apply_stage.py", "--run", RUN, "--stage", "states", "--revert"]
    command += ["--store", str(store)]
    assert message.endswith(f"re-run to see where it stands: python {subprocess.list2cmdline(command)}")


@pytest.mark.parametrize("flags", [("--execute",), ()], ids=["execute", "dry-run"])
def test_a_ledger_table_not_yet_migrated_stops_the_apply_before_it_records_or_writes(
    tmp_path, monkeypatch, capsys, flags
):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    missing = "Could not find the table 'public.team_cleanup_changes' in the schema cache"
    db.refuse[("team_cleanup_changes", "select")] = _api_error("PGRST205", missing)

    message = _refused(monkeypatch, capsys, store, "clubs", *flags)

    assert message == f"Cannot apply the clubs stage of {RUN}: {missing}; apply the table's migration first"
    assert _decisions(db) == [] and runner.commands == []


def test_a_stage_with_nothing_to_apply_still_records_its_decisions_and_its_record(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    decisions = [_decision("no", None, "NV"), _decision("queued-no", "WA", "NV", action="queue")]
    folder = _states(tmp_path, store, decisions, {"no": "dont_apply", "queued-no": "dont_apply"})
    db = _Db(teams=[_team("no", state=None), _team("queued-no", state="WA")])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and runner.commands == [] and not (folder / "vetted.json").exists()
    assert sorted(r["decision"] for r in _decisions(db)) == ["dont_apply", "dont_apply"]
    assert [r["status"] for r in db.tables["team_state_review_queue"]] == ["rejected"]
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "Nothing to apply: no card was chosen Apply, or the hold script held every one." in record
    assert "- 'Team queued-no' to NV, dont_apply: rejected" in record


# --- undo ----------------------------------------------------------------------------------------


def _applied_states(tmp_path, monkeypatch, capsys, closed=True):
    """A states stage applied: a pilot of two and one queued card approved, its windows closed unless
    ``closed`` is False."""
    store = _store(tmp_path)
    decisions = [
        _decision("fill", None, "NV"),
        _decision("fix", "UT", "NV"),
        _decision("q", "WA", "NV", action="queue"),
    ]
    _states(tmp_path, store, decisions, {"fill": "apply", "fix": "apply", "q": "apply"})
    db = _Db(
        teams=[_team("fill", state=None), _team("fix", state="UT"), _team("q", state="WA"), _team("other", state="AZ")]
    )
    _wire(monkeypatch, db, _Runner(db))
    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    if closed:
        _after_the_windows(monkeypatch)
    return store, db


def _reverts(db):
    return [e for e in db.executes if e[:2] == ("revert_team_states", "rpc")]


def test_a_state_revert_puts_the_batch_and_the_approvals_back_and_stamps_the_ledger(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)

    code, out = _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert code == 0
    assert {n: db.team(_id(n))["state_code"] for n in ("fill", "fix", "q")} == {"fill": None, "fix": "UT", "q": "WA"}
    reverted_by = {r["applied_by"] for r in db.tables["team_state_audit"] if r["action"] == "revert"}
    assert reverted_by == {f"{ACTOR}:revert"}
    assert all(r["reverted_at"] for r in _ledger(db)) and len(_ledger(db)) == 3
    assert "Stamped reverted_at on 3 ledger row(s); 0 whose team is not back at its old value." in out


def test_a_state_revert_walks_every_keyset_page(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ap, "STATE_REVERT_PAGE", 1)

    code, _ = _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert code == 0 and len(_reverts(db)) == 5
    assert {n: db.team(_id(n))["state_code"] for n in ("fill", "fix", "q")} == {"fill": None, "fix": "UT", "q": "WA"}


@pytest.mark.parametrize(
    "team, reason, action",
    [
        ("other", "snapshot weekly", "fill"),
        ("other", f"snapshot {CREATED}", "fill"),
        ("fix", "snapshot weekly", "correct"),
    ],
    ids=["another-sweep-another-team", "this-snapshot-another-team", "another-sweep-a-batch-team"],
)
def test_a_state_revert_refuses_a_window_holding_another_writer_s_write_and_names_it(
    tmp_path, monkeypatch, capsys, team, reason, action
):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    pilot = read_json(stage_dir(store, RUN, "states") / "apply.json")["batches"][0]
    old, new = ("AZ", "NV") if team == "other" else ("NV", "ID")
    db.team(_id(team))["state_code"] = new
    db.audit(_id(team), old, new, "assign_team_states", reason, action, at=pilot["ended_at"])
    audit = db.tables["team_state_audit"][-1]["id"]

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message == (
        "Not reverting: these writes fall in the stage's windows but are not the stage's own, and the revert "
        f"would undo them too:\n  {_id(team)}: {action} {old} -> {new} by assign_team_states at {pilot['ended_at']} "
        f"(audit row {audit}), in the pilot batch window"
    )
    assert _reverts(db) == [] and db.team(_id("fill"))["state_code"] == "NV"
    assert not any(r["reverted_at"] for r in _ledger(db))


@pytest.mark.parametrize(
    "reason, action",
    [("approved review 77", "approve"), (None, "fill")],
    ids=["an-approval-of-another-review", "no-approval-at-all"],
)
def test_a_state_revert_refuses_a_write_under_this_run_s_actor_that_no_queue_step_made(
    tmp_path, monkeypatch, capsys, reason, action
):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    queued = read_json(stage_dir(store, RUN, "states") / "apply.json")["queue"][0]
    reason = reason or f"approved review {queued['reviews'][0]}"
    db.team(_id("other"))["state_code"] = "NV"
    db.audit(_id("other"), "AZ", "NV", ACTOR, reason, action, at=queued["ended_at"])

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message.startswith("Not reverting: these writes fall in the stage's windows but are not the stage's own")
    assert f"{_id('other')}: {action} AZ -> NV by {ACTOR}" in message and _reverts(db) == []


def test_a_state_revert_undoes_the_batch_s_own_write_that_failed_verification(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    names = ["a", "b", "c"]
    _states(tmp_path, store, [_decision(n, None, "NV") for n in names], {n: "apply" for n in names})
    db = _Db(teams=[_team(n, state=None) for n in names])
    operator = {"assign_team_states": lambda db: db.team(_id("b")).update(state_code="ID")}
    _wire(monkeypatch, db, _Runner(db, during=operator))
    assert _refused(monkeypatch, capsys, store, "states", "--execute").startswith("Stopped after the pilot batch")
    _after_the_windows(monkeypatch)

    code, _ = _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert code == 0 and [db.team(_id(n))["state_code"] for n in names] == [None, "ID", None]


def test_a_state_revert_knows_an_approval_whose_answer_was_lost_as_its_own(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    db = _Db(teams=[_team("q", state="WA")])
    _wire(monkeypatch, db, _Runner(db))
    db.lost[("approve_team_state", "rpc")] = httpx.RemoteProtocolError("connection closed")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    _after_the_windows(monkeypatch)

    code, _ = _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == "WA"


def test_a_state_revert_waits_until_every_window_has_closed(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys, closed=False)
    pilot = read_json(stage_dir(store, RUN, "states") / "apply.json")["batches"][0]
    window_end = (_instant(pilot["ended_at"]) + timedelta(minutes=2)).isoformat()

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    # Time alone lifts it, so it exits 75 and the autopilot's next tick tries again.
    assert caught.value.code == 75
    assert str(caught.value).startswith(
        f"Not reverting yet: a write could still land in the pilot batch window, to {window_end}"
    )
    assert _reverts(db) == [] and db.team(_id("fill"))["state_code"] == "NV"


def test_a_foreign_write_landing_after_the_check_is_reported_as_undone(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    pilot = read_json(stage_dir(store, RUN, "states") / "apply.json")["batches"][0]
    revert_window = ap.revert_window

    def lands_first(sb, run_id, actor, window, label):
        if actor == "assign_team_states" and db.team(_id("other"))["state_code"] == "AZ":
            db.team(_id("other"))["state_code"] = "NV"
            db.audit(_id("other"), "AZ", "NV", actor, "snapshot other", "fill", at=pilot["ended_at"])
        return revert_window(sb, run_id, actor, window, label)

    monkeypatch.setattr(ap, "revert_window", lands_first)

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message.startswith(
        "Reverted, but these writes landed in the stage's windows after the check and were undone with them; put "
        f"them back by hand:\n  {_id('other')}: fill AZ -> NV by assign_team_states"
    )
    assert db.team(_id("fill"))["state_code"] is None and all(r["reverted_at"] for r in _ledger(db))


def test_a_foreign_write_in_the_rest_window_refuses_the_revert(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    fills = [f"f{n:02d}" for n in range(52)]
    _states(tmp_path, store, [_decision(n, None, "NV") for n in fills], {n: "apply" for n in fills})
    db = _Db(teams=[_team(n, state=None) for n in fills] + [_team("other", state="AZ")])
    _wire(monkeypatch, db, _Runner(db))
    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    # The pilot ran an hour before the rest, so the two windows do not touch.
    path = stage_dir(store, RUN, "states") / "apply.json"
    progress = read_json(path)
    pilot = progress["batches"][0]
    for key in ("started_at", "ended_at"):
        pilot[key] = (_instant(pilot[key]) - timedelta(hours=1)).isoformat()
    write_json(path, progress, indent=1)
    pilot_teams = {d["team_id"] for d in read_json(Path(pilot["cut"]))["decisions"]}
    for row in db.tables["team_cleanup_changes"] + db.tables["team_state_audit"]:
        if row["team_id_master"] in pilot_teams:
            row["applied_at"] = (_instant(row["applied_at"]) - timedelta(hours=1)).isoformat()
    rest = progress["batches"][1]
    db.team(_id("other"))["state_code"] = "NV"
    db.audit(_id("other"), "AZ", "NV", "assign_team_states", "snapshot weekly", "fill", at=rest["ended_at"])
    _after_the_windows(monkeypatch)

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message.startswith("Not reverting: these writes") and message.endswith("in the rest batch window")
    assert db.team(_id("other"))["state_code"] == "NV" and _reverts(db) == []


def _undo_section(store, stage):
    """RECORD.md's undo: the whole-lane revert, which keeps to the window and the writer checks, and its
    dry run."""
    revert = ["scripts/team_cleanup/apply_stage.py", "--run", RUN, "--stage", stage, "--revert"]
    whole = subprocess.list2cmdline([*revert, "--execute", "--store", str(store)])
    preview = subprocess.list2cmdline([*revert, "--store", str(store)])
    return (
        f"## Undo\n\nEvery batch of the owner's choices: `python {whole}`\n\n"
        f"Its dry run, which writes nothing: `python {preview}`\n"
    )


def test_the_states_record_offers_only_the_whole_stage_revert(tmp_path, monkeypatch, capsys):
    store, _ = _applied_states(tmp_path, monkeypatch, capsys)

    record = (stage_dir(store, RUN, "states") / "RECORD.md").read_text(encoding="utf-8")

    assert record[record.index("## Undo") :] == _undo_section(store, "states")


def test_the_approval_reason_is_the_one_approve_team_state_writes():
    assert "'approved review ' || p_review_id::text" in provenance._function(provenance.APPROVE_FUNCTION)
    assert ap.approval_reason(42) == "approved review 42"


def test_the_revert_double_takes_the_parameters_the_newest_revert_team_states_names():
    header = provenance._header(provenance.REVERT_FUNCTION)
    named = [arg.split()[0] for arg in provenance._split_top_level(provenance._balanced(header, header.index("(")))]
    double = list(inspect.signature(_Db.rpc_revert_team_states).parameters)[1:]

    expected = ["p_applied_by", "p_applied_after", "p_applied_before", "p_reverted_by", "p_after", "p_batch_size"]

    assert named == double == [*expected, "p_dry_run", "p_revert_reason"]


def _after_the_first_window(monkeypatch, then):
    """``then`` runs after each window revert_team_states puts back, newest first."""
    real = ap.revert_window

    def step(sb, run_id, actor, window, label):
        changed = real(sb, run_id, actor, window, label)
        then()
        return changed

    monkeypatch.setattr(ap, "revert_window", step)


def test_a_state_revert_stops_once_its_lease_is_lost_between_windows(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    before = len(_renewals(db))
    _after_the_first_window(
        monkeypatch, lambda: db.tables["team_cleanup_runs"][0].update(lease_holder="another-machine:1")
    )

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message.startswith(f"Run {RUN}'s lease is no longer ")
    assert message.endswith("so the pilot batch revert was not run.")
    assert len(_renewals(db)) == before + 2
    assert db.team(_id("q"))["state_code"] == "WA" and db.team(_id("fill"))["state_code"] == "NV"


def test_a_state_revert_checks_again_for_other_writers_between_windows(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    busy = []
    _after_the_first_window(monkeypatch, lambda: busy.append(True))
    monkeypatch.setattr(ap, "gh_runs", _busy("calculate-rankings.yml", 5, lambda: busy))

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message.startswith("Not applying while another writer may be running")
    assert db.team(_id("fill"))["state_code"] == "NV"


def test_a_state_revert_checks_the_window_again_between_windows(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    _after_the_first_window(monkeypatch, lambda: monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING))

    message = _refused(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert message.startswith("Outside the apply window")
    assert db.team(_id("fill"))["state_code"] == "NV"


def test_a_state_revert_of_a_pilot_and_a_rest_puts_every_team_back(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    fills = [f"f{n:02d}" for n in range(52)]
    _states(tmp_path, store, [_decision(n, None, "NV") for n in fills], {n: "apply" for n in fills})
    db = _Db(teams=[_team(n, state=None) for n in fills])
    _wire(monkeypatch, db, _Runner(db))
    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    _after_the_windows(monkeypatch)

    code, _ = _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert code == 0 and all(db.team(_id(n))["state_code"] is None for n in fills)
    assert len(_ledger(db)) == 52 and all(r["reverted_at"] for r in _ledger(db))


def test_a_state_revert_knows_an_approval_a_later_queue_step_made_as_its_own(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "apply"})
    db = _Db(teams=[_team("q", state="WA")])
    _wire(monkeypatch, db, _Runner(db))
    db.lost[("team_state_review_queue", "insert")] = httpx.ReadTimeout("timed out")
    _refused(monkeypatch, capsys, store, "states", "--execute")
    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    _after_the_windows(monkeypatch)

    code, _ = _main(monkeypatch, capsys, store, "states", "--revert", "--execute")

    assert code == 0 and db.team(_id("q"))["state_code"] == "WA"


def test_a_revert_dry_run_says_it_would_refuse(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys, closed=False)

    code, out = _main(monkeypatch, capsys, store, "states", "--revert")

    assert code == 0 and "It would refuse. Not reverting yet: a write could still land in" in out
    assert "Re-run with --execute" not in out


def _two_club_batches(tmp_path, monkeypatch, capsys, **options):
    store, db, names = _club_week(tmp_path, n=52)
    runner = _Runner(db, **options)
    _wire(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0
    logs = [b["logs"][0] for b in read_json(stage_dir(store, RUN, "clubs") / "apply.json")["batches"]]
    return store, db, names, runner, logs


def test_a_club_revert_replays_each_log_newest_first_and_stamps_the_ledger(tmp_path, monkeypatch, capsys):
    store, db, names, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    db.team(_id("c07"))["club_name"] = "Renamed Since FC"

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert code == 0
    assert runner.commands[2:] == [
        ["scripts/repair_swapped_club_names.py", "--revert", logs[1], "--execute"],
        ["scripts/repair_swapped_club_names.py", "--revert", logs[0], "--execute"],
    ]
    assert {n: db.team(_id(n))["club_name"] for n in names if db.team(_id(n))["club_name"] != "LVSA"} == {
        "c07": "Renamed Since FC"
    }
    assert [r["team_id_master"] for r in _ledger(db) if not r["reverted_at"]] == [_id("c07")]
    record = (stage_dir(store, RUN, "clubs") / "REVERT.md").read_text(encoding="utf-8")
    assert "Stamped reverted_at on 51 ledger row(s); 1 whose team is not back at its old value." in record


def test_a_revert_renews_the_lease_before_each_step_and_stops_once_it_is_lost(tmp_path, monkeypatch, capsys):
    store, db, _, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    before = len(_renewals(db))

    def taken_over(db):
        db.tables["team_cleanup_runs"][0]["lease_holder"] = "another-machine:1"

    runner.during["repair_swapped_club_names"] = taken_over

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith(f"Run {RUN}'s lease is no longer ") and message.endswith(
        "so the pilot revert was not run."
    )
    assert runner.commands[2:] == [["scripts/repair_swapped_club_names.py", "--revert", logs[1], "--execute"]]
    assert len(_renewals(db)) == before + 2


def test_a_revert_checks_again_for_other_writers_before_each_later_step(tmp_path, monkeypatch, capsys):
    store, db, _, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    busy = []
    runner.during["repair_swapped_club_names"] = lambda db: busy.append(True)
    monkeypatch.setattr(ap, "gh_runs", _busy("calculate-rankings.yml", 5, lambda: busy))

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Not applying while another writer may be running")
    assert runner.commands[2:] == [["scripts/repair_swapped_club_names.py", "--revert", logs[1], "--execute"]]


def test_a_revert_checks_the_window_again_before_each_later_step(tmp_path, monkeypatch, capsys):
    store, db, _, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    runner.during["repair_swapped_club_names"] = lambda db: monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Outside the apply window")
    assert runner.commands[2:] == [["scripts/repair_swapped_club_names.py", "--revert", logs[1], "--execute"]]


def test_a_revert_dry_run_runs_no_applier_and_writes_nothing(tmp_path, monkeypatch, capsys):
    store, db, _, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    writes, before = len(db.writes()), _files(store)

    code, out = _main(monkeypatch, capsys, store, "clubs", "--revert")

    undo = [["scripts/repair_swapped_club_names.py", "--revert", log] for log in reversed(logs)]
    assert code == 0 and out.startswith(f"DRY RUN -- would revert clubs for run {RUN}, newest batch first:\n")
    assert (
        f"  rest: python {subprocess.list2cmdline(undo[0])}\n  pilot: python {subprocess.list2cmdline(undo[1])}\n"
        in out
    )
    assert len(runner.commands) == 2 and len(db.writes()) == writes and _files(store) == before


@pytest.mark.parametrize(
    "stage, applier", [("clubs", "scripts/repair_swapped_club_names.py"), ("ages", "scripts/fix_band_cohorts.py")]
)
def test_a_revert_dry_run_shows_each_batch_s_preview_and_no_command_that_writes(
    tmp_path, monkeypatch, capsys, stage, applier
):
    if stage == "clubs":
        store, *_ = _two_club_batches(tmp_path, monkeypatch, capsys)
    else:
        store = _applied_ages(tmp_path, monkeypatch, capsys)
    pilot, rest = (b["logs"][0] for b in read_json(stage_dir(store, RUN, stage) / "apply.json")["batches"])

    code, out = _main(monkeypatch, capsys, store, stage, "--revert")

    assert code == 0
    assert f"  rest: python {subprocess.list2cmdline([applier, '--revert', rest])}\n" in out
    assert f"  pilot: python {subprocess.list2cmdline([applier, '--revert', pilot])}\n" in out
    assert [line for line in out.splitlines() if "--execute" in line] == ["Re-run with --execute to revert it."]


def test_a_state_revert_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    store, db = _applied_states(tmp_path, monkeypatch, capsys)
    writes = len(db.writes())

    code, out = _main(monkeypatch, capsys, store, "states", "--revert")

    assert code == 0 and "  pilot batch: revert_team_states('assign_team_states', " in out
    assert len(db.writes()) == writes and db.team(_id("fill"))["state_code"] == "NV"


def test_a_revert_outside_the_window_is_refused(tmp_path, monkeypatch, capsys):
    store, db, _, runner, _ = _two_club_batches(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Outside the apply window") and len(runner.commands) == 2


def test_a_revert_waits_for_a_busy_scheduled_writer(tmp_path, monkeypatch, capsys):
    store, db, _, runner, _ = _two_club_batches(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ap, "gh_runs", _busy("calculate-rankings.yml", 1))

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Not applying while another writer may be running") and len(runner.commands) == 2


def test_a_failed_rest_revert_stops_before_the_pilot_revert(tmp_path, monkeypatch, capsys):
    store, db, _, runner, _ = _two_club_batches(
        tmp_path, monkeypatch, capsys, codes={"repair_swapped_club_names": [None, None, 1]}
    )

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Stopped: the rest revert exited 1") and len(runner.commands) == 3


def test_a_revert_passes_over_an_attempt_that_failed_before_writing_its_log(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path, n=55)
    _wire(monkeypatch, db, _Runner(db, codes={"repair_swapped_club_names": [None, 1]}))
    _refused(monkeypatch, capsys, store, "clubs", "--execute")
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert code == 0 and all(db.team(_id(n))["club_name"] == "LVSA" for n in names)


def test_a_revert_refuses_a_batch_that_finished_with_no_log_found(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0
    progress_file = stage_dir(store, RUN, "clubs") / "apply.json"
    progress = read_json(progress_file)
    progress["batches"][0]["logs"] = []
    write_json(progress_file, progress)

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Not reverting: the pilot batch's applier finished but no new log was found for it")
    assert len(runner.commands) == 1
    assert [db.team(_id(n))["club_name"] for n in names] == [f"Club {n}" for n in names]


def test_a_revert_outside_the_window_with_the_override_reverts_every_batch(tmp_path, monkeypatch, capsys):
    store, db, names, runner, _ = _two_club_batches(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--revert", "--execute", "--outside-window")

    assert code == 0 and len(runner.commands) == 4
    assert all(db.team(_id(n))["club_name"] == "LVSA" for n in names)


def test_an_ages_revert_replays_the_age_fixer_s_own_revert(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _ages(tmp_path, store, [_plan_row("g1", "u13", "u12")], {"g1": "apply"})
    db = _Db(teams=[_team("g1", age="u13")])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    _main(monkeypatch, capsys, store, "ages", "--execute")
    [log] = read_json(stage_dir(store, RUN, "ages") / "apply.json")["batches"][0]["logs"]

    code, _ = _main(monkeypatch, capsys, store, "ages", "--revert", "--execute")

    assert code == 0 and runner.commands[-1] == ["scripts/fix_band_cohorts.py", "--revert", log, "--execute"]
    assert db.team(_id("g1"))["age_group"] == "u13" and all(r["reverted_at"] for r in _ledger(db))
    assert {r["applier"] for r in _ledger(db)} == {"scripts/fix_band_cohorts.py"}


def test_an_age_log_written_over_an_older_one_of_the_same_name_is_still_the_batch_s(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _ages(tmp_path, store, [_plan_row("g1", "u13", "u12")], {"g1": "apply"})
    db = _Db(teams=[_team("g1", age="u13")])
    _wire(monkeypatch, db, _Runner(db))
    older = store / "exports" / "fix_band_cohorts_apply_20261017_010001.csv"
    older.parent.mkdir(parents=True, exist_ok=True)
    older.write_text("an earlier run's log, same second\n", encoding="utf-8")

    code, _ = _main(monkeypatch, capsys, store, "ages", "--execute")

    assert code == 0 and read_json(stage_dir(store, RUN, "ages") / "apply.json")["batches"][0]["logs"] == [str(older)]
    assert _main(monkeypatch, capsys, store, "ages", "--revert", "--execute")[0] == 0
    assert db.team(_id("g1"))["age_group"] == "u13"


def _applied_ages(tmp_path, monkeypatch, capsys, n=51):
    """An ages stage of ``n`` teams applied, a pilot and a rest when ``n`` passes the pilot's 50."""
    store = _store(tmp_path)
    names = [f"g{k:02d}" for k in range(n)]
    _ages(tmp_path, store, [_plan_row(name, "u13", "u12") for name in names], {name: "apply" for name in names})
    db = _Db(teams=[_team(name, age="u13") for name in names])
    _wire(monkeypatch, db, _Runner(db))
    assert _main(monkeypatch, capsys, store, "ages", "--execute")[0] == 0
    return store


@pytest.mark.parametrize("stage", ["clubs", "ages"])
def test_the_record_offers_only_the_whole_stage_revert_and_no_batch_s_own(tmp_path, monkeypatch, capsys, stage):
    if stage == "clubs":
        store, *_ = _two_club_batches(tmp_path, monkeypatch, capsys)
    else:
        store = _applied_ages(tmp_path, monkeypatch, capsys)
    folder = stage_dir(store, RUN, stage)
    logs = [batch["logs"][0] for batch in read_json(folder / "apply.json")["batches"]]

    record = (folder / "RECORD.md").read_text(encoding="utf-8")

    assert record[record.index("## Undo") :] == _undo_section(store, stage)
    assert [line for line in record.splitlines() if "--execute" in line] == [
        line for line in _undo_section(store, stage).splitlines() if "--execute" in line
    ]
    assert len(logs) == 2 and all(f"  - applier log: {log}\n" in record for log in logs)


# --- a run already ended ---------------------------------------------------------------------------


def _ended(store, db, status="done"):
    """The run closed as end_run leaves it, in run.json and in its row."""
    run = read_json(run_dir(store, RUN) / "run.json")
    write_run(store, {**run, "status": status})
    db.tables["team_cleanup_runs"][0].update(status=status, lease_holder=None, lease_expires_at=None)


@pytest.mark.parametrize("status", ["done", "abandoned"])
def test_a_closed_run_s_revert_holds_only_this_machine_s_file_lock(tmp_path, monkeypatch, capsys, status):
    store, db, names, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    _ended(store, db, status)
    executes = len(db.executes)

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert code == 0 and [db.team(_id(n))["club_name"] for n in names] == ["LVSA"] * 52
    assert [e for e in db.executes[executes:] if e[0] == "team_cleanup_runs"] == []
    assert db.tables["team_cleanup_runs"][0]["status"] == status


def test_a_closed_run_s_revert_still_keeps_to_the_window(tmp_path, monkeypatch, capsys):
    store, db, names, runner, _ = _two_club_batches(tmp_path, monkeypatch, capsys)
    _ended(store, db)
    monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Outside the apply window") and len(runner.commands) == 2


def test_a_closed_run_s_revert_still_waits_for_other_writers_before_each_step(tmp_path, monkeypatch, capsys):
    store, db, _, runner, logs = _two_club_batches(tmp_path, monkeypatch, capsys)
    _ended(store, db)
    busy = []
    runner.during["repair_swapped_club_names"] = lambda db: busy.append(True)
    monkeypatch.setattr(ap, "gh_runs", _busy("calculate-rankings.yml", 5, lambda: busy))

    message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message.startswith("Not applying while another writer may be running")
    assert runner.commands[2:] == [["scripts/repair_swapped_club_names.py", "--revert", logs[1], "--execute"]]


def test_a_closed_run_s_revert_waits_for_another_holder_of_its_file_lock(tmp_path, monkeypatch, capsys):
    store, db, _, runner, _ = _two_club_batches(tmp_path, monkeypatch, capsys)
    _ended(store, db)

    with _acquire_file_lock(run_dir(store, RUN) / APPLY_LOCK_FILE, timeout=0.0):
        message = _refused(monkeypatch, capsys, store, "clubs", "--revert", "--execute")

    assert message == (
        f"Cannot revert the clubs stage of {RUN}: run {RUN} is in use on this machine (an apply, revert, collect, "
        "page build or end_run holds its lock)"
    )
    assert len(runner.commands) == 2


# --- resuming, and the gates the apply opens with --------------------------------------------------


def test_choices_collected_again_after_the_pilot_are_refused(tmp_path, monkeypatch, capsys):
    store, db, names = _club_week(tmp_path, n=55)
    runner = _Runner(db, codes={"repair_swapped_club_names": [None, 1]})
    _wire(monkeypatch, db, runner)
    _refused(monkeypatch, capsys, store, "clubs", "--execute")
    in_rest = max(names, key=_id)
    _choose(tmp_path / "again", store, "clubs", {n: "dont_apply" if n == in_rest else "apply" for n in names})

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert "the choices were collected again after this stage began applying" in message
    assert db.team(_id(in_rest))["club_name"] == "LVSA" and len(runner.commands) == 2


def test_a_cut_file_edited_between_attempts_is_refused(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=55)
    runner = _Runner(db, codes={"repair_swapped_club_names": [None, 1]})
    _wire(monkeypatch, db, runner)
    _refused(monkeypatch, capsys, store, "clubs", "--execute")
    rest = stage_dir(store, RUN, "clubs") / "rest.csv"
    swapped.write_log(pw._read_csv(rest)[:1], rest)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert "changed since this stage began applying: rest.csv" in message and len(runner.commands) == 2


def test_a_failed_hold_script_is_not_read_through_an_earlier_attempt_s_files(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("t1", "UT", "NV")], {"t1": "apply"})
    write_json(folder / "safe.json", read_json(folder / "snapshot.json"), indent=1)
    write_json(folder / "held.json", [], indent=1)
    db = _Db(teams=[_team("t1", state="UT")])
    runner = _Runner(db, codes={"hold_unsafe_state_applies": [1]})
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message.startswith("hold_unsafe_state_applies.py exited 1") and len(runner.commands) == 1


def test_a_stage_the_run_marks_skipped_is_not_applied(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    run = {"run_id": RUN, "scope": {"states": ["NV"]}, "status": "reviewing", "budgets": {}}
    write_run(store, {**run, "stages": {"clubs": "skill_stale"}})
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == f"Cannot apply the clubs stage of {RUN}: clubs has no proposals this run: skill_stale"
    assert runner.commands == [] and db.executes == []


def test_a_closed_run_is_not_applied(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    _ended(store, db)
    _wire(monkeypatch, db, _Runner(db))

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == (
        f"Cannot apply the clubs stage of {RUN}: run {RUN} is done; pages are built and collected while it is "
        "reviewing, and the choices applied then too"
    )


def test_a_state_snapshot_changed_since_the_page_is_refused(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("t1", None, "NV")], {"t1": "apply"})
    snapshot = read_json(folder / "snapshot.json")
    snapshot["decisions"].append(_decision("t2", None, "NV"))
    write_json(folder / "snapshot.json", snapshot, indent=1)
    db = _Db(teams=[_team("t1", state=None), _team("t2", state=None)])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert "changed since the page was built: snapshot.json" in message and runner.commands == []


@pytest.mark.parametrize("key", ["hashes", "collected_at"])
def test_a_collected_json_missing_a_key_is_refused_naming_the_file(tmp_path, monkeypatch, capsys, key):
    store, db, _ = _club_week(tmp_path)
    path = stage_dir(store, RUN, "clubs") / "collected.json"
    marker = read_json(path)
    del marker[key]
    write_json(path, marker, indent=1)
    _wire(monkeypatch, db, _Runner(db))

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message == f"Cannot apply the clubs stage of {RUN}: {path} lacks {key}; collect again"


def test_the_rest_waits_for_a_writer_that_started_during_the_pilot(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=51)
    busy = []
    runner = _Runner(db, during={"repair_swapped_club_names": lambda db: busy.append(True)})
    _wire(monkeypatch, db, runner, gh=_busy("calculate-rankings.yml", 8, lambda: busy))

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith("Not applying while another writer may be running") and len(runner.commands) == 1
    assert len(_ledger(db)) == 50


def test_the_rest_waits_for_the_window_still_to_be_open(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=51)
    runner = _Runner(
        db, during={"repair_swapped_club_names": lambda db: monkeypatch.setattr(ap, "_now", lambda: MONDAY_MORNING)}
    )
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "clubs", "--execute")

    assert message.startswith("Outside the apply window") and len(runner.commands) == 1


# --- the states ledger -----------------------------------------------------------------------------


class _ForeignFirst(_Runner):
    """Another assign_team_states run (the weekly fill, dispatched by hand) writes t1 just before ours."""

    def assign_team_states(self, command, log):
        self.db._state_write(_id("t1"), None, "NV", "assign_team_states", "fill", "snapshot weekly-dispatch")
        return super().assign_team_states(command, log)


def test_another_sweep_s_write_is_not_ledgered_as_this_run_s(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("t1", None, "NV")], {"t1": "apply"})
    db = _Db(teams=[_team("t1", state=None)])
    _wire(monkeypatch, db, _ForeignFirst(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and _ledger(db) == []
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team t1': already at the proposed state, set by another writer" in record


def test_a_cut_team_another_writer_filled_before_the_apply_is_reported_and_the_stage_goes_on(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    names = ["a", "b", "c"]
    decisions = [*(_decision(n, None, "NV") for n in names), _decision("moved", "UT", "NV")]
    folder = _states(tmp_path, store, decisions, {n: "apply" for n in [*names, "moved"]})
    db = _Db(teams=[*(_team(n, state=None) for n in names), _team("moved", state="OR")])
    # The weekly fill, dispatched by hand before the window opened, filled b with the proposed state.
    db._state_write(_id("b"), None, "NV", "assign_team_states", "fill", "snapshot weekly-dispatch")
    db.tables["team_state_audit"][-1]["applied_at"] = "2026-10-01T00:00:00+00:00"
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and sorted(r["team_id_master"] for r in _ledger(db)) == sorted([_id("a"), _id("c")])
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team b': already at the proposed state, set by another writer" in record
    assert "- 'Team moved': not written by the replay: moved, outranked or reverted since the snapshot" in record


def test_a_state_write_another_writer_undid_stops_after_the_pilot(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("t1", None, "NV")], {"t1": "apply"})
    db = _Db(teams=[_team("t1", state=None)])
    runner = _Runner(db, during={"assign_team_states": lambda db: db.team(_id("t1")).update(state_code="OR")})
    _wire(monkeypatch, db, runner)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message.startswith("Stopped after the pilot batch: 1 written change(s) the database does not hold")


def test_a_state_write_the_window_missed_stops_until_the_batch_s_window_is_widened_over_it(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision("fill", None, "NV")], {"fill": "apply"})
    db = _Db(teams=[_team("fill", state=None)])
    _wire(monkeypatch, db, _Runner(db))
    database_clock = _now
    _database_clock(monkeypatch, 5)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    [audit] = db.tables["team_state_audit"]
    [pilot] = read_json(folder / "apply.json")["batches"]
    unreachable = _unreachable(folder, _outside(audit, "batches[0]", pilot))
    assert message.startswith(f"Stopped after the pilot batch: {unreachable}\nRe-run once it is understood: ")
    assert _ledger(db) == [] and not (folder / "RECORD.md").exists()
    why = "not written by the replay: moved, outranked or reverted since the snapshot"
    assert pilot["skipped"] == [[_id("fill"), why]]
    assert _refused(monkeypatch, capsys, store, "states", "--revert", "--execute") == f"Not reverting: {unreachable}"
    assert _reverts(db) == [] and db.team(_id("fill"))["state_code"] == "NV"

    # The clocks agree again, but the batch's window is already saved.
    monkeypatch.setattr(sys.modules[__name__], "_now", database_clock)

    assert _refused(monkeypatch, capsys, store, "states", "--execute").startswith(
        f"Stopped after the pilot batch: {unreachable}"
    )

    _widen(folder, "batches", 0, "ended_at", audit["applied_at"])

    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    assert [(r["team_id_master"], r["applied_at"]) for r in _ledger(db)] == [(_id("fill"), audit["applied_at"])]
    _after_the_windows(monkeypatch)
    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert db.team(_id("fill"))["state_code"] is None and all(r["reverted_at"] for r in _ledger(db))


def test_setting_the_clock_right_before_widening_the_pilot_lets_the_rest_and_the_whole_revert_through(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    fills = [f"f{n:02d}" for n in range(52)]
    folder = _states(tmp_path, store, [_decision(n, None, "NV") for n in fills], {n: "apply" for n in fills})
    db = _Db(teams=[_team(n, state=None) for n in fills])
    _wire(monkeypatch, db, _Runner(db))
    database_clock = _now
    _database_clock(monkeypatch, 5)

    message = _refused(monkeypatch, capsys, store, "states", "--execute")

    assert message.startswith("Stopped after the pilot batch: 50 of the stage's own state write(s) or approval(s)")
    monkeypatch.setattr(sys.modules[__name__], "_now", database_clock)
    _widen(folder, "batches", 0, "ended_at", max(r["applied_at"] for r in db.tables["team_state_audit"]))

    code, out = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and "rest: 2 written, 2 verified" in out and len(_ledger(db)) == 52
    _after_the_windows(monkeypatch)
    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert all(db.team(_id(n))["state_code"] is None for n in fills) and all(r["reverted_at"] for r in _ledger(db))


def test_more_than_a_hundred_cut_teams_another_writer_filled_are_reported(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    fills = [f"f{n:03d}" for n in range(152)]
    folder = _states(tmp_path, store, [_decision(n, None, "NV") for n in fills], {n: "apply" for n in fills})
    # The weekly fill set every team of the cut before the apply ran.
    db = _Db(teams=[_team(n, state="NV") for n in fills])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and _ledger(db) == []
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert record.count(": already at the proposed state, set by another writer") == 152


def test_each_attempt_of_a_batch_names_the_other_writer(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _states(tmp_path, store, [_decision(n, None, "NV") for n in "ab"], {"a": "apply", "b": "apply"})
    db = _Db(teams=[_team("a", state=None), _team("b", state="NV")])
    _wire(monkeypatch, db, _Runner(db, codes={"assign_team_states": [1]}))
    assert _refused(monkeypatch, capsys, store, "states", "--execute").startswith("Stopped after the pilot batch")

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert record.count("- 'Team b': already at the proposed state, set by another writer") == 2
    assert "'Team b': not written" not in record


def test_a_state_team_that_moved_since_the_snapshot_is_reported_and_the_stage_goes_on(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    decisions = [_decision("fill", None, "NV"), _decision("moved", "UT", "NV")]
    folder = _states(tmp_path, store, decisions, {"fill": "apply", "moved": "apply"})
    db = _Db(teams=[_team("fill", state=None), _team("moved", state="OR")])
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and db.team(_id("moved"))["state_code"] == "OR"
    record = (folder / "RECORD.md").read_text(encoding="utf-8")
    assert "- 'Team moved': not written by the replay: moved, outranked or reverted since the snapshot" in record


@pytest.mark.parametrize("skew", [-1, 1], ids=["database-a-minute-behind", "database-a-minute-ahead"])
def test_a_state_write_stamped_inside_the_clock_margin_is_ledgered(tmp_path, monkeypatch, capsys, skew):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("fill", None, "NV")], {"fill": "apply"})
    db = _Db(teams=[_team("fill", state=None)])
    _wire(monkeypatch, db, _Runner(db))
    monkeypatch.setattr(
        sys.modules[__name__], "_now", lambda: (datetime.now(timezone.utc) + timedelta(minutes=skew)).isoformat()
    )

    code, _ = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and [r["team_id_master"] for r in _ledger(db)] == [_id("fill")]


def test_a_state_team_written_by_an_earlier_attempt_of_its_batch_is_not_taken_for_a_missed_one(
    tmp_path, monkeypatch, capsys
):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("a", None, "NV"), _decision("b", None, "NV")], {"a": "apply", "b": "apply"})
    db = _Db(teams=[_team("a", state=None), _team("b", state=None)])

    class _DiesAfterOne(_Runner):
        def assign_team_states(self, command, log):
            if self.dies:
                self.dies = False
                self.db._state_write(_id("a"), None, "NV", "assign_team_states", "fill", ats.snapshot_reason(CREATED))
                return 1
            return super().assign_team_states(command, log)

    runner = _DiesAfterOne(db)
    runner.dies = True
    _wire(monkeypatch, db, runner)
    assert _refused(monkeypatch, capsys, store, "states", "--execute").startswith("Stopped after the pilot batch: its")
    # The first attempt ran an hour before the second, so its window does not reach the second's writes.
    path = stage_dir(store, RUN, "states") / "apply.json"
    progress = read_json(path)
    for key in ("started_at", "ended_at"):
        progress["batches"][0][key] = (_instant(progress["batches"][0][key]) - timedelta(hours=1)).isoformat()
    write_json(path, progress, indent=1)
    for row in db.tables["team_state_audit"]:
        row["applied_at"] = (_instant(row["applied_at"]) - timedelta(hours=1)).isoformat()

    code, out = _main(monkeypatch, capsys, store, "states", "--execute")

    assert code == 0 and "pilot: 1 written, 1 verified" in out
    assert sorted(r["team_id_master"] for r in _ledger(db)) == sorted([_id("a"), _id("b")])


# --- what a stopped apply leaves for status and end_run ----------------------------------------------


def test_status_and_end_run_name_the_batches_a_stopped_apply_left_applied(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path, n=55)
    _wire(monkeypatch, db, _Runner(db, codes={"repair_swapped_club_names": [None, 1]}))
    _refused(monkeypatch, capsys, store, "clubs", "--execute")
    run = read_json(run_dir(store, RUN) / "run.json")

    expected = (
        "the owner runs the apply again; 1 batch(es) applied (pilot) and a failed rest attempt, so revert before "
        "abandoning the run"
    )
    assert f"  clubs      next: {expected}" in status.describe(store, run)
    assert f"clubs: next, {expected}" in end_run.unfinished(store, run)


# --- the automatic lane ---------------------------------------------------------------------------


def _club_lanes(tmp_path, auto, owner):
    """A clubs stage whose page sent ``auto``'s changes to the automatic lane and showed ``owner``'s as cards
    chosen Apply, both lanes collected."""
    store = _store(tmp_path)
    names = (*auto, *owner)
    rows = [_scan_row(name, "LVSA", f"Club {name}") for name in names]
    _clubs(tmp_path, store, rows, dict.fromkeys(owner, "apply"), auto)
    return store, _Db(teams=[_team(name, club="LVSA") for name in names])


def _clubs_of(db, names):
    return {name: db.team(_id(name))["club_name"] for name in names}


def test_the_automatic_lane_applies_its_own_changes_from_its_own_folder(tmp_path, monkeypatch, capsys):
    store, db = _club_lanes(tmp_path, auto=("a1", "a2"), owner=("o1",))
    _wire(monkeypatch, db, _Runner(db))

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--execute")

    folder = stage_dir(store, RUN, "clubs")
    assert code == 0
    assert _clubs_of(db, ("a1", "a2", "o1")) == {"a1": "Club a1", "a2": "Club a2", "o1": "LVSA"}
    assert sorted((r["team_id_master"], r["decision"], r["source"]) for r in _decisions(db)) == sorted(
        [(_id("a1"), "apply", f"auto:{PAGE_RUN}"), (_id("a2"), "apply", f"auto:{PAGE_RUN}")]
    )
    assert [r["team_id_master"] for r in _ledger(db)] == sorted([_id("a1"), _id("a2")])
    record = (folder / "auto" / "RECORD.md").read_text(encoding="utf-8")
    assert record.startswith(f"# the clubs automatic lane applied, run {RUN}")
    assert "Every batch of the automatic lane: `python " in record and "--lane auto --revert --execute" in record
    assert (folder / "auto" / "apply.json").exists()
    assert not (folder / "apply.json").exists() and not (folder / "RECORD.md").exists()

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert code == 0 and _clubs_of(db, ("o1",)) == {"o1": "Club o1"}
    assert stage_progress(store, RUN, "clubs").finished


def test_an_applied_automatic_lane_is_not_applied_again_while_the_owner_s_choices_wait(tmp_path, monkeypatch, capsys):
    store, db = _club_lanes(tmp_path, auto=("a1",), owner=("o1",))
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    assert _main(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--execute")[0] == 0

    message = _refused(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--execute")

    assert message == f"Cannot apply the clubs automatic lane of {RUN}: the clubs automatic lane is already applied"
    assert len(runner.commands) == 1


def test_a_stage_is_finished_only_once_its_automatic_lane_is_applied_too(tmp_path, monkeypatch, capsys):
    store, db = _club_lanes(tmp_path, auto=("a1",), owner=("o1",))
    _wire(monkeypatch, db, _Runner(db))
    assert _main(monkeypatch, capsys, store, "clubs", "--execute")[0] == 0
    run = read_json(run_dir(store, RUN) / "run.json")

    lines = status.describe(store, run)

    waiting = "the owner runs the automatic lane's apply"
    assert not stage_progress(store, RUN, "clubs").finished
    assert "  clubs      the owner's choices are applied" in lines
    assert " " * 13 + f"automatic lane next: {waiting}" in lines
    assert f"clubs: automatic lane next, {waiting}" in end_run.unfinished(store, run)
    with pytest.raises(SystemExit, match="clubs: automatic lane next"):
        end_run.check(store, run, "done")


def test_an_automatic_lane_revert_undoes_only_its_own_changes_and_stamps_only_its_ledger_rows(
    tmp_path, monkeypatch, capsys
):
    store, db = _club_lanes(tmp_path, auto=("a1", "a2"), owner=("o1",))
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    for lane in ("auto", "owner"):
        assert _main(monkeypatch, capsys, store, "clubs", "--lane", lane, "--execute")[0] == 0
    lane = stage_dir(store, RUN, "clubs") / "auto"
    log = read_json(lane / "apply.json")["batches"][0]["logs"][0]

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--revert", "--execute")

    assert code == 0
    assert runner.commands[-1] == ["scripts/repair_swapped_club_names.py", "--revert", log, "--execute"]
    assert _clubs_of(db, ("a1", "a2", "o1")) == {"a1": "LVSA", "a2": "LVSA", "o1": "Club o1"}
    assert [r["team_id_master"] for r in _ledger(db) if not r["reverted_at"]] == [_id("o1")]
    revert = (lane / "REVERT.md").read_text(encoding="utf-8")
    assert "Stamped reverted_at on 2 ledger row(s); 0 whose team is not back at its old value." in revert


def test_the_automatic_lane_s_hold_reads_the_stage_s_national_run_into_its_own_folder(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    decisions = [_decision("sure", None, "NV"), _decision("card", None, "NV")]
    _states(tmp_path, store, decisions, {"card": "apply"}, auto=("sure",))
    db = _Db(teams=[_team("sure", state=None), _team("card", state=None)])
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    code, _ = _main(monkeypatch, capsys, store, "states", "--lane", "auto", "--execute")

    folder = stage_dir(store, RUN, "states")
    assert code == 0
    assert runner.commands[0] == [
        "scripts/hold_unsafe_state_applies.py",
        str(folder / "national_snapshot.json"),
        str(folder / "auto" / "safe.json"),
        str(folder / "auto" / "held.json"),
    ]
    assert [d["team_id"] for d in read_json(folder / "auto" / "pilot.json")["decisions"]] == [_id("sure")]
    assert {n: db.team(_id(n))["state_code"] for n in ("sure", "card")} == {"sure": "NV", "card": None}


@pytest.mark.parametrize("lane", ["auto", "owner"])
def test_choices_collected_from_another_build_of_the_page_are_refused(tmp_path, monkeypatch, capsys, lane):
    store, db = _club_lanes(tmp_path, auto=("a1",), owner=("o1",))
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)
    page = stage_dir(store, RUN, "clubs") / PAGE_MARKER
    write_json(page, {**read_json(page), "run": "20261015T000000Z-ffffff"}, indent=1)

    message = _refused(monkeypatch, capsys, store, "clubs", "--lane", lane, "--execute")

    assert message.endswith(
        f"the choices were collected from page run {PAGE_RUN}, not 20261015T000000Z-ffffff, the page as built; "
        "collect again"
    )
    assert runner.commands == [] and _decisions(db) == []


def _state_lanes(tmp_path, monkeypatch):
    """A states stage whose page sent one fill to the automatic lane and showed another as a card chosen Apply."""
    store = _store(tmp_path)
    decisions = [_decision("sure", None, "NV"), _decision("card", None, "NV")]
    _states(tmp_path, store, decisions, {"card": "apply"}, auto=("sure",))
    db = _Db(teams=[_team("sure", state=None), _team("card", state=None)])
    _wire(monkeypatch, db, _Runner(db))
    return store, db


def _ran_an_hour_ago(store, db, lane):
    """The lane's batches, and the audit rows they wrote, as if it had applied an hour ago."""
    path = stage_dir(store, RUN, "states") / ("auto" if lane == "auto" else "") / "apply.json"
    progress = read_json(path)
    for batch in progress["batches"]:
        batch.update(started_at=_an_hour_earlier(batch["started_at"]), ended_at=_an_hour_earlier(batch["ended_at"]))
    write_json(path, progress, indent=1)
    for row in db.tables["team_state_audit"]:
        row["applied_at"] = _an_hour_earlier(row["applied_at"])


def test_a_state_lane_waits_until_its_undo_window_cannot_reach_the_other_lane_s_writes(tmp_path, monkeypatch, capsys):
    store, db = _state_lanes(tmp_path, monkeypatch)
    assert _main(monkeypatch, capsys, store, "states", "--lane", "auto", "--execute")[0] == 0

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, "states", "--execute")

    assert caught.value.code == 75 and str(caught.value).startswith("Not applying until ")
    assert "the other lane's last state batch ended at " in str(caught.value)
    assert db.team(_id("card"))["state_code"] is None

    _ran_an_hour_ago(store, db, "auto")
    assert _main(monkeypatch, capsys, store, "states", "--execute")[0] == 0
    _after_the_windows(monkeypatch)

    assert _main(monkeypatch, capsys, store, "states", "--lane", "auto", "--revert", "--execute")[0] == 0
    assert {n: db.team(_id(n))["state_code"] for n in ("sure", "card")} == {"sure": None, "card": "NV"}
    assert [r["team_id_master"] for r in _ledger(db) if r["reverted_at"]] == [_id("sure")]

    assert _main(monkeypatch, capsys, store, "states", "--revert", "--execute")[0] == 0
    assert {n: db.team(_id(n))["state_code"] for n in ("sure", "card")} == {"sure": None, "card": None}


def test_a_stopped_automatic_lane_hands_back_its_own_rerun_and_names_what_it_left_applied(
    tmp_path, monkeypatch, capsys
):
    names = tuple(f"a{i:02d}" for i in range(55))
    store, db = _club_lanes(tmp_path, auto=names, owner=("o1",))
    _wire(monkeypatch, db, _Runner(db, codes={"repair_swapped_club_names": [None, 1]}))

    message = _refused(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--execute")

    assert subprocess.list2cmdline(["--stage", "clubs", "--lane", "auto", "--execute"]) in message
    run = read_json(run_dir(store, RUN) / "run.json")
    expected = (
        "the owner runs the automatic lane's apply again; 1 batch(es) applied (pilot) and a failed rest attempt, so "
        "revert before abandoning the run"
    )
    assert " " * 13 + f"automatic lane next: {expected}" in status.describe(store, run)
    assert f"clubs: automatic lane next, {expected}" in end_run.unfinished(store, run)


def test_the_automatic_lane_s_dry_runs_name_the_lane(tmp_path, monkeypatch, capsys):
    store, db = _club_lanes(tmp_path, auto=("a1",), owner=("o1",))
    _wire(monkeypatch, db, _Runner(db))

    _, out = _main(monkeypatch, capsys, store, "clubs", "--lane", "auto")
    assert out.startswith(f"DRY RUN -- the clubs automatic lane for run {RUN}, page run {PAGE_RUN}.")

    assert _main(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--execute")[0] == 0
    _, out = _main(monkeypatch, capsys, store, "clubs", "--lane", "auto", "--revert")
    assert out.startswith(f"DRY RUN -- would revert the clubs automatic lane for run {RUN}, newest batch first:")


# --- refusals that waiting may lift ---------------------------------------------------------------


def _leased_elsewhere(db):
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.tables["team_cleanup_runs"][0].update(lease_holder="another-machine:1", lease_expires_at=expires)


@pytest.mark.parametrize(
    "wait, reason",
    [
        ({"now": MONDAY_MORNING}, "Outside the apply window"),
        ({"gh": _busy("calculate-rankings.yml", 5)}, "Not applying while another writer may be running"),
        ({"db": _leased_elsewhere}, f"Cannot apply the clubs stage of {RUN}: run {RUN} is held by another-machine:1"),
    ],
    ids=["outside-the-window", "another-writer", "another-applier"],
)
def test_a_refusal_that_waiting_may_lift_exits_75_with_its_reason(tmp_path, monkeypatch, capsys, wait, reason):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    wait.get("db", lambda db: None)(db)
    _wire(monkeypatch, db, runner, **{key: value for key, value in wait.items() if key != "db"})

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert caught.value.code == 75
    assert capsys.readouterr().err.startswith(reason) and str(caught.value).startswith(reason)
    assert _team_writes(db) == [] and runner.commands == []


def test_an_apply_holding_the_run_on_this_machine_exits_75(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    runner = _Runner(db)
    _wire(monkeypatch, db, runner)

    with _acquire_file_lock(run_dir(store, RUN) / APPLY_LOCK_FILE, timeout=0.0):
        with pytest.raises(SystemExit) as caught:
            _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert caught.value.code == 75 and f"run {RUN} is in use on this machine" in capsys.readouterr().err
    assert runner.commands == []


def test_a_collect_while_an_apply_holds_the_run_exits_75(tmp_path, monkeypatch, capsys):
    store, _ = _club_lanes(tmp_path, auto=("a1",), owner=("o1",))
    monkeypatch.setattr(
        sys, "argv", ["collect.py", "--run", RUN, "--stage", "clubs", "--lane", "auto", "--store", str(store)]
    )

    with _acquire_file_lock(run_dir(store, RUN) / APPLY_LOCK_FILE, timeout=0.0):
        with pytest.raises(SystemExit) as caught:
            col.main()

    assert caught.value.code == 75
    assert capsys.readouterr().err.startswith(f"Cannot collect the clubs automatic lane for {RUN}: run {RUN} is in use")


def test_a_refusal_that_waiting_cannot_lift_exits_1(tmp_path, monkeypatch, capsys):
    store, db, _ = _club_week(tmp_path)
    _wire(monkeypatch, db, _Runner(db))
    monkeypatch.setattr(ap, "gh_runs", REAL_GH_RUNS)
    failed = subprocess.CompletedProcess([], 1, stdout="", stderr="HTTP 401: Bad credentials")
    monkeypatch.setattr(ap.subprocess, "run", lambda command, **kwargs: failed)

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert caught.value.code == str(caught.value) and str(caught.value).startswith("Not applying: gh api")


def test_a_stage_that_writes_no_team_records_its_decisions_while_another_writer_runs(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    folder = _clubs(tmp_path, store, [_scan_row("no", "LVSA", "Club no")], {"no": "dont_apply"})
    db = _Db(teams=[_team("no", club="LVSA")])
    _wire(monkeypatch, db, _Runner(db), gh=_busy("calculate-rankings.yml", 5))

    code, _ = _main(monkeypatch, capsys, store, "clubs", "--execute")

    assert code == 0 and [r["decision"] for r in _decisions(db)] == ["dont_apply"]
    assert (folder / "RECORD.md").exists() and _clubs_of(db, ("no",)) == {"no": "LVSA"}


def test_a_queued_state_card_to_settle_still_waits_for_another_writer(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    _states(tmp_path, store, [_decision("q", "WA", "NV", action="queue")], {"q": "dont_apply"})
    db = _Db(teams=[_team("q", state="WA")])
    _wire(monkeypatch, db, _Runner(db), gh=_busy("calculate-rankings.yml", 5))

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, "states", "--execute")

    assert caught.value.code == 75 and _decisions(db) == []
