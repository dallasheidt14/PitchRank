"""Linking Kitman squads: plan from the report and decisions, write only with --execute, undo safely."""

import csv
import json

import pytest
from postgrest.exceptions import APIError

from scripts import link_mlsnext_kitman_teams as link
from src.models import mlsnext_kitman_keys as keys

PROVIDER = "prov-kitman"


class _Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    """Builds lazily and records only at execute(); a zero-row .single() raises like postgrest."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.filters, self.payload, self.single_row = "select", [], None, False
        self.columns, self.want_count = None, False

    def select(self, columns="*", count=None):
        self.columns = None if columns == "*" else [c.strip() for c in columns.split(",")]
        self.want_count = count == "exact"
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
        total = len(rows)
        rows = [{c: r.get(c) for c in self.columns} if self.columns else dict(r) for r in rows]
        if self.single_row:
            if len(rows) != 1:
                raise APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})
            return _Result(rows[0])
        return _Result(rows, count=total if self.want_count else None)


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


def _live(team_id_master, age_group="u16", gender="Male", deprecated=None):
    return {"team_id_master": team_id_master, "age_group": age_group, "gender": gender, "is_deprecated": deprecated}


def _squad(sid="10", club="Alpha SC", age="u16", division="HD"):
    return {
        "provider_team_id": sid,
        "key": f"{sid}:2026",
        "club_name": club,
        "display_name": f"{club} U{age[1:]} {division}",
        "age_group": age,
        "division": division,
    }


def _row(sid="10", bucket="confident", candidates="T1", reason=""):
    return {"provider_team_id": sid, "bucket": bucket, "reason": reason, "candidate_ids": candidates,
            "candidate_names": "Name", "candidate_providers": "modular11"}


@pytest.fixture(autouse=True)
def states(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "Alpha SC", "AZ")
    monkeypatch.delitem(keys.CLUB_STATES, "Stateless FC", raising=False)


def _plan(squads, report, decisions=None):
    return link.plan_links(squads, report, decisions or {})


def test_buckets_become_actions():
    squads = [_squad("1"), _squad("2"), _squad("3"), _squad("4"), _squad("5")]
    report = [_row("1", "confident"), _row("2", "new", ""), _row("3", "review"), _row("4", "linked"), _row("5", "confident")]
    plan = _plan(squads[:4], report[:4])
    assert [(a.action, a.reason, a.match_method) for a in plan] == [
        ("link", "confident", "fuzzy_auto"),
        ("create", "no match", "direct_id"),
        ("hold", "needs review", ""),
        ("keep", "already linked", ""),
    ]
    assert plan[0].team_id_master == "T1" and plan[0].key == "1:2026"


def test_a_pick_overrides_the_bucket():
    squads, report = [_squad("1"), _squad("2"), _squad("3")], [_row("1", "review"), _row("2", "review"), _row("3", "confident")]
    plan = _plan(squads, report, {"1": "T9", "2": "new", "3": "skip"})
    assert [(a.action, a.team_id_master, a.match_method, a.reason) for a in plan] == [
        ("link", "T9", "manual", "your pick"),
        ("create", "", "direct_id", "your pick: new"),
        ("hold", "", "", "your pick: skip"),
    ]


def test_a_squad_missing_from_the_report_is_held():
    assert _plan([_squad()], [])[0].reason == "not in match report"


def test_a_new_squad_of_a_club_with_no_state_is_held_not_created():
    plan = _plan([_squad(club="Stateless FC")], [_row(bucket="new", candidates="")])
    assert (plan[0].action, plan[0].reason) == ("hold", "club has no state in the club table")


def test_a_picked_new_team_also_needs_a_state():
    plan = _plan([_squad(club="Stateless FC")], [_row(bucket="review")], {"10": "new"})
    assert plan[0].action == "hold"


def test_a_link_does_not_need_a_state():
    assert _plan([_squad(club="Stateless FC")], [_row()])[0].action == "link"


def _create_action(division="HD", state="AZ"):
    return link.LinkAction("10", "10:2026", "create", "", "direct_id", "Alpha SC U16 HD", "Alpha SC", "u16", division, state, "no match")


def _link_action(target="T1", sid="10", age="u16", method="fuzzy_auto", division="HD"):
    return link.LinkAction(sid, f"{sid}:2026", "link", target, method, "Alpha SC U16 HD", "Alpha SC", age, division, "AZ", "confident")


def _apply(db, plan, tmp_path):
    return link.apply_plan(db, PROVIDER, plan, tmp_path / "log.jsonl")


def test_create_writes_the_team_the_alias_and_the_division(alias_calls, tmp_path):
    db = _Db()
    counts, created = _apply(db, [_create_action("AD")], tmp_path)
    assert counts["teams_created"] == 1 and counts["aliases_written"] == 1 and counts["division_unset"] == 0
    team = db.rows["teams"][0]
    assert {k: team[k] for k in ("team_name", "club_name", "age_group", "gender", "state_code", "state", "provider_id", "provider_team_id", "league")} == {
        "team_name": "Alpha SC U16 HD",
        "club_name": "Alpha SC",
        "age_group": "u16",
        "gender": "Male",
        "state_code": "AZ",
        "state": "Arizona",
        "provider_id": PROVIDER,
        "provider_team_id": "10:2026",
        "league": "MLS_NEXT_AD",
    }
    alias = db.rows["team_alias_map"][0]
    assert (alias["provider_team_id"], alias["team_id_master"], alias["division"]) == ("10:2026", team["team_id_master"], "AD")
    assert created == {"10": team["team_id_master"]}
    assert alias_calls[0]["match_method"] == "direct_id" and alias_calls[0]["confidence"] == 1.0


def test_the_league_follows_the_division(alias_calls, tmp_path):
    db = _Db()
    _apply(db, [_create_action("HD")], tmp_path)
    assert db.rows["teams"][0]["league"] == "MLS_NEXT_HD"


def test_a_province_code_creates_a_team_without_a_state_name(alias_calls, tmp_path):
    db = _Db()
    _apply(db, [_create_action(state="ON")], tmp_path)
    assert db.rows["teams"][0]["state_code"] == "ON" and "state" not in db.rows["teams"][0]


def test_link_adds_an_alias_to_the_existing_team_and_creates_nothing(alias_calls, tmp_path):
    db = _Db(teams=[_live("T1")])
    counts, _ = _apply(db, [_link_action()], tmp_path)
    assert counts["aliases_written"] == 1 and counts["teams_created"] == 0
    assert [t["team_id_master"] for t in db.rows["teams"]] == ["T1"]
    assert db.rows["team_alias_map"][0]["division"] == "HD"
    assert alias_calls[0]["match_method"] == "fuzzy_auto" and alias_calls[0]["confidence"] == 0.95


@pytest.mark.parametrize(
    "target",
    [_live("T1", age_group="u15"), _live("T1", gender="Female"), _live("T1", deprecated=True)],
)
def test_a_link_to_an_unusable_team_is_rejected(alias_calls, tmp_path, target):
    db = _Db(teams=[target])
    counts, _ = _apply(db, [_link_action()], tmp_path)
    assert counts["links_rejected"] == 1 and db.rows["team_alias_map"] == []


def test_a_link_to_a_missing_team_is_rejected(alias_calls, tmp_path):
    counts, _ = _apply(_Db(), [_link_action()], tmp_path)
    assert counts["links_rejected"] == 1


def test_an_approved_alias_is_never_repointed(alias_calls, tmp_path):
    db = _Db(teams=[_live("T1"), _live("T2")],
             aliases=[{"id": 1, "provider_id": PROVIDER, "provider_team_id": "10:2026", "team_id_master": "T2", "review_status": "approved"}])
    counts, _ = _apply(db, [_link_action("T1")], tmp_path)
    assert counts["needs_merge"] == 1 and db.rows["team_alias_map"][0]["team_id_master"] == "T2" and alias_calls == []


def test_a_create_over_an_existing_link_reuses_it(alias_calls, tmp_path):
    db = _Db(teams=[_live("T2")],
             aliases=[{"id": 1, "provider_id": PROVIDER, "provider_team_id": "10:2026", "team_id_master": "T2", "review_status": "approved"}])
    counts, _ = _apply(db, [_create_action()], tmp_path)
    assert counts["already_linked"] == 1 and counts["teams_created"] == 0 and db.writes() == []


def test_a_create_reuses_a_team_an_earlier_run_made(alias_calls, tmp_path):
    db = _Db(teams=[{**_live("T3"), "provider_id": PROVIDER, "provider_team_id": "10:2026"}])
    counts, created = _apply(db, [_create_action()], tmp_path)
    assert counts["teams_reused"] == 1 and counts["teams_created"] == 0 and created == {"10": "T3"}
    assert db.rows["team_alias_map"][0]["team_id_master"] == "T3"


def test_keep_and_hold_write_nothing(alias_calls, tmp_path):
    keep = link.LinkAction("10", "10:2026", "keep", "T1", "", "n", "c", "u16", "HD", "AZ", "already linked")
    hold = link.LinkAction("11", "11:2026", "hold", "", "", "n", "c", "u16", "HD", "AZ", "needs review")
    db = _Db()
    counts, _ = _apply(db, [keep, hold], tmp_path)
    assert (counts["already_linked"], counts["held"]) == (1, 1) and db.writes() == [] and alias_calls == []


def test_an_unchanged_alias_counts_as_unchanged_not_a_conflict(alias_calls, tmp_path):
    alias = {"id": 1, "provider_id": PROVIDER, "provider_team_id": "10:2026", "team_id_master": "T1",
             "review_status": "approved", "match_confidence": 1.0}
    db = _Db(teams=[_live("T1")], aliases=[alias])
    counts, _ = _apply(db, [_link_action()], tmp_path)
    assert counts["unchanged"] == 1 and counts["conflicts"] == 0 and counts["aliases_written"] == 0


def test_a_division_that_does_not_read_back_is_reported(alias_calls, tmp_path, monkeypatch):
    monkeypatch.setattr(link, "_set_division", lambda *a, **k: False)
    counts, _ = _apply(_Db(teams=[_live("T1")]), [_link_action()], tmp_path)
    assert counts["division_unset"] == 1


def test_a_run_refuses_a_key_without_a_season(alias_calls, tmp_path):
    bad = link.LinkAction("10", "10", "link", "T1", "fuzzy_auto", "n", "c", "u16", "HD", "AZ", "confident")
    with pytest.raises(SystemExit, match="not season-keyed"):
        _apply(_Db(teams=[_live("T1")]), [bad], tmp_path)


def test_undo_removes_what_the_run_created_and_keeps_teams_with_games(alias_calls, tmp_path):
    db = _Db()
    _, created = _apply(db, [_create_action(), link.LinkAction("11", "11:2026", "create", "", "direct_id", "n2", "Alpha SC", "u16", "HD", "AZ", "no match")], tmp_path)
    keep_id = created["11"]
    db.rows["games"].append({"home_team_master_id": keep_id, "away_team_master_id": "X"})
    counts = link.undo(db, PROVIDER, tmp_path / "log.jsonl")
    assert counts == {"aliases_removed": 2, "aliases_restored": 0, "teams_removed": 1, "teams_refused": 1}
    assert [t["team_id_master"] for t in db.rows["teams"]] == [keep_id]


def test_undo_restores_an_alias_the_run_overwrote(alias_calls, tmp_path):
    old = {"id": 1, "provider_id": PROVIDER, "provider_team_id": "10:2026", "team_id_master": "T1",
           "review_status": "approved", "match_method": "fuzzy_auto", "match_confidence": 0.5, "division": None}
    db = _Db(teams=[_live("T1")], aliases=[dict(old)])
    _apply(db, [_link_action(method="manual")], tmp_path)
    assert db.rows["team_alias_map"][0]["match_method"] == "manual"
    counts = link.undo(db, PROVIDER, tmp_path / "log.jsonl")
    assert counts["aliases_restored"] == 1
    assert db.rows["team_alias_map"][0]["match_method"] == "fuzzy_auto" and db.rows["team_alias_map"][0]["division"] is None


def _write(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _inputs(tmp_path, squads, report):
    _write(tmp_path / "squads.csv", list(squads[0]), squads)
    _write(tmp_path / "match_report.csv", list(report[0]), report)


def test_a_dry_run_opens_no_client_and_writes_the_plan_and_handback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(link, "_new_client", lambda: (_ for _ in ()).throw(AssertionError("dry run must not connect")))
    _inputs(tmp_path, [_squad("1"), _squad("2"), _squad("3", club="Stateless FC"), _squad("4")],
            [_row("1"), _row("2", "review", "T1|T2"), _row("3", "new", ""), _row("4", "new", "")])
    assert link.main(["--in-dir", str(tmp_path)]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    plan = list(csv.DictReader((tmp_path / "link_plan.csv").open(encoding="utf-8")))
    assert [p["action"] for p in plan] == ["link", "hold", "hold", "create"]
    handback = list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))
    assert [(h["provider_team_id"], h["status"]) for h in handback] == [
        ("2", "needs review"),
        ("3", "needs state"),
        ("4", "would create"),
    ]
    assert (tmp_path / "handback_legend.txt").read_text(encoding="utf-8").startswith("How to fill in handback.csv")
    assert not list(tmp_path.glob("link_log_*"))


def test_squads_and_report_must_list_the_same_squads(tmp_path):
    _inputs(tmp_path, [_squad("1"), _squad("2")], [_row("1")])
    with pytest.raises(SystemExit, match="list different squads"):
        link.main(["--in-dir", str(tmp_path)])


def test_the_handback_shows_candidate_providers(tmp_path):
    plan = [link.LinkAction("2", "2:2026", "hold", "", "", "n", "c", "u16", "HD", "AZ", "needs review")]
    report = [{"provider_team_id": "2", "candidate_ids": "G1|G2", "candidate_names": "A|B", "candidate_providers": "gotsport|"}]
    link.write_handback(tmp_path / "handback.csv", plan, report, {})
    assert list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))[0]["candidates"] == "A (G1, gotsport) | B (G2)"


def test_the_log_is_json_lines(alias_calls, tmp_path):
    _apply(_Db(), [_create_action()], tmp_path)
    kinds = [json.loads(line)["kind"] for line in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kinds == ["team", "alias"]


def test_undo_leaves_an_alias_a_merge_moved_since_the_run(alias_calls, tmp_path):
    db = _Db(teams=[_live("T1"), _live("T2")])
    _apply(db, [_link_action("T1")], tmp_path)
    db.rows["team_alias_map"][0]["team_id_master"] = "T2"
    counts = link.undo(db, PROVIDER, tmp_path / "log.jsonl")
    assert counts["aliases_removed"] == 0
    assert db.rows["team_alias_map"][0]["team_id_master"] == "T2"


def test_undo_does_not_restore_over_an_alias_a_merge_moved_since_the_run(alias_calls, tmp_path):
    old = {"id": 1, "provider_id": PROVIDER, "provider_team_id": "10:2026", "team_id_master": "T1",
           "review_status": "approved", "match_method": "fuzzy_auto", "match_confidence": 0.5, "division": None}
    db = _Db(teams=[_live("T1"), _live("T2")], aliases=[dict(old)])
    _apply(db, [_link_action(method="manual")], tmp_path)
    db.rows["team_alias_map"][0]["team_id_master"] = "T2"
    counts = link.undo(db, PROVIDER, tmp_path / "log.jsonl")
    assert counts["aliases_restored"] == 0
    assert db.rows["team_alias_map"][0]["team_id_master"] == "T2" and db.rows["team_alias_map"][0]["match_method"] == "manual"


def _handback(tmp_path, plan, created, dry_run):
    link.write_handback(tmp_path / "handback.csv", plan, [], created, dry_run=dry_run)
    return list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))


def test_the_handback_names_a_created_team_and_a_would_create_team(tmp_path):
    plan = [_create_action()]
    assert [(r["status"], r["pitchrank_team_id"]) for r in _handback(tmp_path, plan, {"10": "T7"}, dry_run=False)] == [
        ("created", "T7")
    ]
    assert [(r["status"], r["pitchrank_team_id"]) for r in _handback(tmp_path, plan, {}, dry_run=True)] == [
        ("would create", "")
    ]


def test_the_handback_defangs_feed_text_a_spreadsheet_would_run(tmp_path):
    plan = [
        link.LinkAction("2", "2:2026", "hold", "", "", "=cmd U16 HD", "=cmd", "u16", "HD", "", "needs review"),
    ]
    report = [{"provider_team_id": "2", "candidate_ids": "G1", "candidate_names": "=other", "candidate_providers": "gotsport"}]
    link.write_handback(tmp_path / "handback.csv", plan, report, {})
    row = list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))[0]
    assert (row["team_name"], row["club"]) == ("'=cmd U16 HD", "'=cmd")
    assert row["candidates"].startswith("'=other")


def test_main_executes_a_returned_handback_and_undo_reverses_the_run(alias_calls, tmp_path, monkeypatch, capsys):
    db = _Db(teams=[_live("T1")])
    db.rows["providers"] = [{"id": PROVIDER, "code": "mlsnext_kitman"}]
    monkeypatch.setattr(link, "_new_client", lambda: db)
    _inputs(tmp_path, [_squad("1"), _squad("2"), _squad("3")],
            [_row("1"), _row("2", "review", "T1"), _row("3", "review", "T1")])
    assert link.main(["--in-dir", str(tmp_path)]) == 0
    assert db.writes() == []
    handback = list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))
    assert [h["provider_team_id"] for h in handback] == ["2", "3"]
    handback[0]["your_pick"], handback[1]["your_pick"] = "new", "skip"
    decisions = tmp_path / "decisions.csv"
    _write(decisions, list(handback[0]), handback)

    assert link.main(["--in-dir", str(tmp_path), "--decisions", str(decisions), "--execute"]) == 0
    out = capsys.readouterr().out
    assert "teams_created=1" in out and "aliases_written=2" in out and "Undo with:" in out
    keys_written = sorted(a["provider_team_id"] for a in db.rows["team_alias_map"])
    assert keys_written == ["1:2026", "2:2026"]
    created = [t for t in db.rows["teams"] if t.get("provider_team_id") == "2:2026"]
    assert len(created) == 1
    handback_after = list(csv.DictReader((tmp_path / "handback.csv").open(encoding="utf-8")))
    assert [(h["provider_team_id"], h["status"]) for h in handback_after] == [("2", "created"), ("3", "needs review")]
    assert handback_after[0]["pitchrank_team_id"] == created[0]["team_id_master"]

    log = next(tmp_path.glob("link_log_*.jsonl"))
    assert link.main(["--undo", str(log)]) == 0
    assert db.rows["team_alias_map"] == [] and [t["team_id_master"] for t in db.rows["teams"]] == ["T1"]
