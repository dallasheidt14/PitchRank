"""Linking EA teams: plan from the report and decisions, write only with --execute, undo safely."""

import csv
import json

import pytest
from postgrest.exceptions import APIError

from scripts import link_modular11_ea_teams as link

PROVIDER = "prov-ea"
TEAM_COLUMNS = ["provider_team_id", "academy_id", "club_name", "display_name", "age_group", "name_tier", "tiers", "regions", "gender", "season"]
REPORT_COLUMNS = ["provider_team_id", "club_name", "display_name", "tiers", "bucket", "reason", "candidate_ids", "candidate_names", "candidate_clubs", "candidate_providers", "candidate_states"]


class _Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    """Builds lazily and records only at execute(); a zero-row .single() raises like postgrest."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.filters, self.payload, self.single_row = "select", [], None, False
        self.window = None

    def select(self, *_cols, count=None):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _n):
        return self

    def single(self):
        self.single_row = True
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def _matching(self):
        return [r for r in self.db.rows[self.table] if all(r.get(c) == v for c, v in self.filters)]

    def execute(self):
        self.db.executed.append((self.op, self.table, list(self.filters), self.payload))
        if self.op == "insert":
            self.db.rows[self.table].append(dict(self.payload))
            return _Result([self.payload])
        rows = self._matching()
        if self.op == "update":
            for row in rows:
                row.update(self.payload)
            return _Result(rows)
        if self.op == "delete":
            for row in rows:
                self.db.rows[self.table].remove(row)
            return _Result(rows)
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        rows = [dict(r) for r in rows]  # PostgREST returns copies, never the stored rows
        if self.single_row:
            if len(rows) != 1:
                raise APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})
            return _Result(rows[0])
        return _Result(rows, count=len(rows))


class _Db:
    def __init__(self, teams=(), aliases=(), games=()):
        self.rows = {"teams": list(teams), "team_alias_map": list(aliases), "games": list(games)}
        self.executed = []

    def table(self, name):
        return _Query(self, name)

    def writes(self):
        return [e for e in self.executed if e[0] in ("insert", "delete", "update")]


@pytest.fixture
def alias_calls(monkeypatch):
    """Stands in for upsert_team_alias with its outcomes: an approved alias to another team is a
    conflict, an approved one at no lower confidence is skipped, anything else is overwritten."""
    calls = []

    def fake_upsert(sb, **kwargs):
        calls.append(kwargs)
        existing = [
            a
            for a in sb.rows["team_alias_map"]
            if a["provider_id"] == kwargs["provider_uuid"] and a["provider_team_id"] == kwargs["provider_team_id"]
        ]
        if existing:
            row = existing[0]
            if row.get("review_status") == "approved" and row["team_id_master"] != kwargs["team_id_master"]:
                return {"action": "conflict"}
            if row.get("review_status") == "approved" and kwargs["confidence"] <= (row.get("match_confidence") or 0):
                return {"action": "skipped_weaker_metadata"}
            row.update(team_id_master=kwargs["team_id_master"], match_method=kwargs["match_method"],
                       match_confidence=kwargs["confidence"], review_status="approved")
            return {"action": "updated"}
        sb.rows["team_alias_map"].append(
            {
                "id": 1000 + len(sb.rows["team_alias_map"]),
                "provider_id": kwargs["provider_uuid"],
                "provider_team_id": kwargs["provider_team_id"],
                "team_id_master": kwargs["team_id_master"],
                "review_status": "approved",
            }
        )
        return {"action": "created"}

    monkeypatch.setattr(link, "upsert_team_alias", fake_upsert)
    return calls


def _live(team_id_master, age_group="u17", gender="Male", deprecated=None):
    return {"team_id_master": team_id_master, "age_group": age_group, "gender": gender, "is_deprecated": deprecated}


def _team(tid, name="Emerald City FC", club="Emerald City FC"):
    return {"provider_team_id": tid, "academy_id": "9", "club_name": club, "display_name": name, "age_group": "u17",
            "name_tier": "EA", "tiers": "EA", "regions": "PACNW", "gender": "Male", "season": "2026"}


def _report(tid, bucket, ids="", names=""):
    return {"provider_team_id": tid, "club_name": "Emerald City FC", "display_name": "Emerald City FC", "tiers": "EA",
            "bucket": bucket, "reason": "", "candidate_ids": ids, "candidate_names": names, "candidate_clubs": "",
            "candidate_providers": "", "candidate_states": ""}


def _actions(plan):
    return {a.provider_team_id: (a.action, a.team_id_master, a.match_method) for a in plan}


def _write(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_plan_follows_buckets():
    teams = [_team("1"), _team("2"), _team("3")]
    report = [_report("1", "confident", "M1", "Emerald 2010 EA"), _report("2", "no_match"), _report("3", "review", "M3|M4")]
    assert _actions(link.plan_links(teams, report, {})) == {
        "1": ("link", "M1", "fuzzy_auto"),
        "2": ("create", "", "direct_id"),
        "3": ("hold", "", ""),
    }


def test_decisions_override_buckets():
    teams = [_team("1"), _team("2"), _team("3")]
    report = [_report("1", "confident", "M1"), _report("2", "review", "M3|M4"), _report("3", "review", "M5")]
    decisions = {"1": "skip", "2": "M4", "3": "new"}
    assert _actions(link.plan_links(teams, report, decisions)) == {
        "1": ("hold", "", ""),
        "2": ("link", "M4", "manual"),
        "3": ("create", "", "direct_id"),
    }


def test_execute_creates_team_and_direct_id_alias(tmp_path, alias_calls):
    db = _Db()
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {})
    counts, created = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    [team] = db.rows["teams"]
    new_id = created["7155"]
    assert team == {
        "team_id_master": new_id,
        "team_name": "Emerald City FC",
        "club_name": "Emerald City FC",
        "age_group": "u17",
        "gender": "Male",
        "state_code": "WA",
        "state": "Washington",
        "provider_id": PROVIDER,
        "provider_team_id": "7155:2026",
        "distinction": team["distinction"],
    }
    assert [(c["provider_team_id"], c["team_id_master"], c["match_method"], c["confidence"]) for c in alias_calls] == [
        ("7155:2026", new_id, "direct_id", 1.0)
    ]
    assert counts == {
        "teams_created": 1,
        "teams_reused": 0,
        "aliases_written": 1,
        "conflicts": 0,
        "held": 0,
        "already_linked": 0,
        "needs_merge": 0,
        "links_rejected": 0,
    }
    log = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log == [
        {"kind": "team", "team_id_master": new_id},
        {"kind": "alias", "provider_team_id": "7155:2026", "team_id_master": new_id, "result": "created"},
    ]


def test_confident_link_writes_fuzzy_auto_alias(tmp_path, alias_calls):
    db = _Db(teams=[_live("M1")])
    plan = link.plan_links([_team("1")], [_report("1", "confident", "M1")], {})
    link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert db.rows["teams"] == [_live("M1")]
    assert [(c["team_id_master"], c["match_method"], c["confidence"]) for c in alias_calls] == [("M1", "fuzzy_auto", 0.95)]


def test_rerun_reuses_existing_team(tmp_path, alias_calls):
    existing = {"team_id_master": "OLD", "provider_id": PROVIDER, "provider_team_id": "7155:2026"}
    db = _Db(teams=[existing])
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {})
    counts, created = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert db.rows["teams"] == [existing]
    assert [c["team_id_master"] for c in alias_calls] == ["OLD"]
    assert (counts["teams_created"], counts["teams_reused"], created) == (0, 1, {"7155": "OLD"})


def test_hold_writes_nothing(tmp_path, alias_calls):
    db = _Db()
    plan = link.plan_links([_team("1")], [_report("1", "review", "M1|M2")], {})
    counts, _ = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (db.writes(), alias_calls, counts["held"]) == ([], [], 1)


def test_undo_removes_created_aliases_and_empty_teams(tmp_path, alias_calls):
    keep = {"id": 1, "provider_id": PROVIDER, "provider_team_id": "9:2026", "team_id_master": "KEEP",
            "match_confidence": 0.95, "review_status": "approved"}
    db = _Db(aliases=[keep], teams=[_live("KEEP")])
    plan = link.plan_links([_team("7155"), _team("9")], [_report("7155", "no_match"), _report("9", "confident", "KEEP")], {})
    log = tmp_path / "log.jsonl"
    link.apply_plan(db, PROVIDER, plan, log)
    assert link.undo(db, PROVIDER, log) == {"aliases_removed": 1, "aliases_restored": 0, "teams_removed": 1, "teams_refused": 0}
    assert db.rows["teams"] == [_live("KEEP")]
    assert db.rows["team_alias_map"] == [keep]


def test_undo_refuses_team_with_games(tmp_path, alias_calls):
    db = _Db()
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {})
    log = tmp_path / "log.jsonl"
    _, created = link.apply_plan(db, PROVIDER, plan, log)
    db.rows["games"].append({"home_team_master_id": "X", "away_team_master_id": created["7155"]})
    assert link.undo(db, PROVIDER, log) == {"aliases_removed": 1, "aliases_restored": 0, "teams_removed": 0, "teams_refused": 1}
    assert [t["team_id_master"] for t in db.rows["teams"]] == [created["7155"]]


def test_dry_run_touches_no_database(tmp_path, monkeypatch):
    age_dir = tmp_path / "u17"
    age_dir.mkdir()
    _write(age_dir / "teams.csv", TEAM_COLUMNS, [_team("1"), _team("2")])
    _write(age_dir / "match_report.csv", REPORT_COLUMNS, [_report("1", "no_match"), _report("2", "review", "M1|M2", "A|B")])
    monkeypatch.setattr(link, "_new_client", lambda: (_ for _ in ()).throw(AssertionError("dry run opened a client")))
    assert link.main(["--age", "u17", "--in-dir", str(tmp_path)]) == 0
    plan_rows = list(csv.DictReader((age_dir / "link_plan.csv").open(encoding="utf-8")))
    assert [(r["provider_team_id"], r["action"]) for r in plan_rows] == [("1", "create"), ("2", "hold")]


def test_handback_lists_created_and_review_teams(tmp_path):
    plan = link.plan_links([_team("1"), _team("2"), _team("3")],
                           [_report("1", "no_match"), _report("2", "review", "M1|M2", "Emerald B10 EA|Emerald 2010"),
                            _report("3", "confident", "M9")], {})
    report = [_report("1", "no_match"), _report("2", "review", "M1|M2", "Emerald B10 EA|Emerald 2010"),
              _report("3", "confident", "M9")]
    link.write_handback(tmp_path / "handback.csv", plan, report, {"1": "NEW1"})
    rows = list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))
    assert [(r["provider_team_id"], r["status"], r["pitchrank_team_id"], r["candidates"], r["your_pick"]) for r in rows] == [
        ("1", "created", "NEW1", "", ""),
        ("2", "needs review", "", "Emerald B10 EA (M1) | Emerald 2010 (M2)", ""),
    ]
    legend = (tmp_path / "handback_legend.txt").read_text(encoding="utf-8")
    assert "your_pick" in legend and "skip" in legend and "new" in legend


def test_create_reuses_an_existing_approved_alias_and_writes_nothing(tmp_path, alias_calls):
    alias = {"provider_id": PROVIDER, "provider_team_id": "7155:2026", "team_id_master": "SURVIVOR", "review_status": "approved"}
    deprecated = {"team_id_master": "OLD", "provider_id": PROVIDER, "provider_team_id": "7155:2026", "is_deprecated": True}
    db = _Db(teams=[deprecated], aliases=[alias])
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {"7155": "new"})
    counts, created = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (db.writes(), alias_calls, created) == ([], [], {})
    assert (counts["already_linked"], counts["teams_created"], counts["teams_reused"]) == (1, 0, 0)


def test_pick_for_an_already_linked_team_is_reported_not_written(tmp_path, alias_calls):
    alias = {"provider_id": PROVIDER, "provider_team_id": "7155:2026", "team_id_master": "CREATED", "review_status": "approved"}
    db = _Db(teams=[_live("CREATED"), _live("OTHER")], aliases=[alias])
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {"7155": "OTHER"})
    counts, _ = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (db.writes(), alias_calls, counts["needs_merge"]) == ([], [], 1)


@pytest.mark.parametrize(
    "target",
    [_live("P", age_group="u16"), _live("P", gender="Female"), _live("P", deprecated=True)],
    ids=["other-age", "other-gender", "deprecated"],
)
def test_link_to_an_unusable_team_is_held(tmp_path, alias_calls, target):
    db = _Db(teams=[target])
    plan = link.plan_links([_team("1")], [_report("1", "review", "P|Q")], {"1": "P"})
    counts, _ = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (alias_calls, counts["links_rejected"]) == ([], 1)


def test_link_to_a_missing_team_is_held(tmp_path, alias_calls):
    db = _Db()
    plan = link.plan_links([_team("1")], [_report("1", "review", "P|Q")], {"1": "NOPE"})
    counts, _ = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (alias_calls, counts["links_rejected"]) == ([], 1)


def test_legend_offers_skip_only_for_review_rows(tmp_path):
    report = [_report("1", "no_match"), _report("2", "review", "M1", "A")]
    plan = link.plan_links([_team("1"), _team("2")], report, {})
    link.write_handback(tmp_path / "handback.csv", plan, report, {})
    legend = (tmp_path / "handback_legend.txt").read_text(encoding="utf-8")
    assert "Needs review rows" in legend and "Created rows" in legend
    created_part = legend.split("Created rows", 1)[1].split("Needs review rows", 1)[0]
    assert "skip" not in created_part and "merge" in created_part


def test_last_seasons_link_does_not_count_for_this_season(tmp_path, alias_calls):
    old = {"provider_id": PROVIDER, "provider_team_id": "7155:2025", "team_id_master": "LAST_YEAR", "review_status": "approved"}
    db = _Db(aliases=[old])
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {})
    counts, created = link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (counts["already_linked"], counts["teams_created"]) == (0, 1)
    assert [c["provider_team_id"] for c in alias_calls] == ["7155:2026"]


def test_raw_uid_decision_applies_to_the_season_key():
    plan = link.plan_links([_team("7155")], [_report("7155", "review", "M1|M2")], {"7155": "M2"})
    assert [(a.provider_team_id, a.key, a.action, a.team_id_master) for a in plan] == [("7155", "7155:2026", "link", "M2")]


def test_execute_refuses_while_raw_ids_remain(tmp_path, alias_calls):
    raw = {"id": 1, "provider_id": PROVIDER, "provider_team_id": "7155", "team_id_master": "OLD", "review_status": "approved"}
    db = _Db(aliases=[raw])
    plan = link.plan_links([_team("7155")], [_report("7155", "no_match")], {})
    with pytest.raises(SystemExit, match="migrate_modular11_ea_season_keys.py"):
        link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")
    assert (db.writes(), alias_calls) == ([], [])


def test_team_missing_from_the_report_is_held_not_created():
    plan = link.plan_links([_team("1"), _team("2")], [_report("1", "no_match")], {})
    assert _actions(plan) == {"1": ("create", "", "direct_id"), "2": ("hold", "", "")}
    assert [a.reason for a in plan if a.provider_team_id == "2"] == ["not in match report"]


def test_mismatched_roster_and_report_stop_the_run(tmp_path, monkeypatch):
    age_dir = tmp_path / "u17"
    age_dir.mkdir()
    _write(age_dir / "teams.csv", TEAM_COLUMNS, [_team("1"), _team("2")])
    _write(age_dir / "match_report.csv", REPORT_COLUMNS, [_report("1", "no_match"), _report("9", "no_match")])
    monkeypatch.setattr(link, "_new_client", lambda: (_ for _ in ()).throw(AssertionError("opened a client")))
    with pytest.raises(SystemExit, match="match_report.csv"):
        link.main(["--age", "u17", "--in-dir", str(tmp_path), "--execute"])


def test_undo_restores_an_alias_the_run_updated(tmp_path, alias_calls):
    pending = {"id": 7, "provider_id": PROVIDER, "provider_team_id": "1:2026", "team_id_master": "OTHER",
               "match_method": "fuzzy_review", "match_confidence": 0.8, "review_status": "pending"}
    db = _Db(aliases=[dict(pending)], teams=[_live("M1")])
    plan = link.plan_links([_team("1")], [_report("1", "confident", "M1")], {})
    log = tmp_path / "log.jsonl"
    link.apply_plan(db, PROVIDER, plan, log)
    assert db.rows["team_alias_map"][0]["team_id_master"] == "M1"
    assert link.undo(db, PROVIDER, log) == {"aliases_removed": 0, "aliases_restored": 1, "teams_removed": 0, "teams_refused": 0}
    assert db.rows["team_alias_map"] == [pending]


def test_undo_leaves_an_updated_alias_that_moved_since(tmp_path, alias_calls):
    pending = {"id": 7, "provider_id": PROVIDER, "provider_team_id": "1:2026", "team_id_master": "OTHER",
               "match_method": "fuzzy_review", "match_confidence": 0.8, "review_status": "pending"}
    db = _Db(aliases=[dict(pending)], teams=[_live("M1")])
    plan = link.plan_links([_team("1")], [_report("1", "confident", "M1")], {})
    log = tmp_path / "log.jsonl"
    link.apply_plan(db, PROVIDER, plan, log)
    db.rows["team_alias_map"][0]["team_id_master"] = "LATER"
    assert link.undo(db, PROVIDER, log)["aliases_restored"] == 0
    assert db.rows["team_alias_map"][0]["team_id_master"] == "LATER"
