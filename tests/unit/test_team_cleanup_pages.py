"""Tests for the weekly cleanup's single-team review pages and the collector that reads them back."""

import hashlib
import json
import os
import sys
from datetime import date

import pytest
from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import fix_band_cohorts as bands  # noqa: E402
from scripts import repair_swapped_club_names as swapped  # noqa: E402
from scripts.team_cleanup import collect as col  # noqa: E402
from scripts.team_cleanup import pages  # noqa: E402
from scripts.team_cleanup import propose_week as pw  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    MANIFEST_FILE,
    PREFLIGHT_MARKER,
    PROPOSALS_FILE,
    PROPOSE_MARKER,
    STALE_FILE,
    stage_dir,
    stage_progress,
    write_run,
)
from src.tournaments.storage._io import write_json  # noqa: E402

RUN = "2026-10-14-nv"
ROW_CAP = 1000
COLUMNS = {
    "teams": {
        "team_id_master",
        "team_name",
        "team_name_original",
        "club_name",
        "age_group",
        "gender",
        "state_code",
        "provider_id",
        "is_deprecated",
    },
    "team_merge_map": {"id", "deprecated_team_id", "canonical_team_id"},
    "team_cleanup_decisions": {
        "id",
        "stage",
        "subject_key",
        "team_id_master",
        "field",
        "proposed_value",
        "decision",
        "decided_at",
        "superseded_at",
    },
    "providers": {"id", "code"},
    "games": {"id", "home_team_master_id", "away_team_master_id", "game_date", "is_excluded"},
    "watchlist_items": {"id", "team_id_master"},
    "report_card_leads": {"id", "team_id"},
    "scrape_requests": {"id", "team_id_master", "priority", "request_type", "requested_at"},
}


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records each read at execute(), where the real builder sends it. It answers at most ROW_CAP
    rows, refuses an unknown column and a ranged page with no order. A page build only reads, so
    there is no insert, update or delete to call."""

    def __init__(self, db, table, columns):
        for column in columns:
            assert column in COLUMNS[table], f"PostgREST refuses unknown column {table}.{column}"
        self._db, self._table, self._columns = db, table, columns
        self._filters, self._order, self._range = [], None, None

    def _where(self, column, test):
        assert column in COLUMNS[self._table], f"PostgREST refuses unknown column {self._table}.{column}"
        self._filters.append((column, test))
        return self

    def eq(self, column, value):
        return self._where(column, lambda x: x == value)

    def in_(self, column, values):
        values = list(values)
        assert len(values) <= 100, "an id list this long overflows the URL"
        return self._where(column, lambda x: x in values)

    def gte(self, column, value):
        return self._where(column, lambda x: x >= value)

    def order(self, column):
        assert column in COLUMNS[self._table]
        self._order = column
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        self._db.executes.append(self._table)
        if self._table in self._db.broken:
            raise self._db.broken[self._table]
        assert self._order or self._range is None, "a page with no order is arbitrary"
        found = [r for r in self._db.tables[self._table] if all(test(r[c]) for c, test in self._filters)]
        if self._order:
            found.sort(key=lambda r: r[self._order])
        if self._range:
            found = found[self._range[0] : self._range[1] + 1]
        return _Result([{c: r[c] for c in self._columns} for r in found[:ROW_CAP]])


class _Db:
    def __init__(self, **tables):
        self.tables = {name: [dict(r) for r in tables.get(name, ())] for name in COLUMNS}
        self.tables["providers"] = self.tables["providers"] or [{"id": 1, "code": "gotsport"}]
        self.broken, self.executes = {}, []

    def table(self, name):
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, name, [c.strip() for c in columns.split(",")])

        return _T()


def _team(tid, *, state="NV", club="Las Vegas Sports Academy", age="u12", deprecated=False, name=None):
    return {
        "team_id_master": tid,
        "team_name": name or f"Team {tid}",
        "team_name_original": None,
        "club_name": club,
        "age_group": age,
        "gender": "Male",
        "state_code": state,
        "provider_id": 1,
        "is_deprecated": deprecated,
    }


def _merged(deprecated, canonical, n=1):
    return {"id": n, "deprecated_team_id": deprecated, "canonical_team_id": canonical}


def _declined(tid, value, *, n=1, superseded=None, stage="states", field="state_code", decision="dont_apply"):
    return {
        "id": f"d{n}",
        "stage": stage,
        "subject_key": f"{tid}|{field}",
        "team_id_master": tid,
        "field": field,
        "proposed_value": value,
        "decision": decision,
        "decided_at": "2026-10-01T12:00:00+00:00",
        "superseded_at": superseded,
    }


def _game(n, home, away, day, excluded=False):
    return {
        "id": n,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "game_date": day,
        "is_excluded": excluded,
    }


def _decision(team_id, pre, proposed, action="apply", tier="B"):
    return {
        "team_id": team_id,
        "team_name": f"Team {team_id}",
        "club_name": "Club",
        "pre_image": pre,
        "proposed": proposed,
        "tier": tier,
        "confidence": 0.9,
        "action": action,
        "reason": "club-mates",
    }


# --- a run in review, its stage files written by the propose step's own code -----------------


def _reviewing(store, stages=None):
    write_run(
        store,
        {"run_id": RUN, "scope": {"states": ["NV"]}, "status": "reviewing", "budgets": {}, "stages": stages or {}},
    )


def _folder(store, stage, proposals, stale=()):
    folder = stage_dir(store, RUN, stage)
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / PREFLIGHT_MARKER, {"passed": True})
    write_json(folder / PROPOSALS_FILE, proposals, indent=1)
    write_json(folder / STALE_FILE, list(stale), indent=1)
    (folder / PROPOSE_MARKER).write_text("", encoding="utf-8")
    return folder


def _states(store, decisions, stale=()):
    snapshot = {"rules": "authority", "created_at": "2026-10-14T18:00:00", "live_teams": 9, "decisions": decisions}
    scoped, proposals = pw.state_proposals(snapshot, ["NV"])
    folder = _folder(store, "states", proposals, stale)
    write_json(folder / pw.SCOPED_STATES, scoped, indent=1)


def _scan_row(team_id, stored, proposed, tier="swap", needs_review=False):
    return {
        "team_id_master": team_id,
        "provider": "gotsport",
        "state": "NV",
        "team_name": f"Team {team_id}",
        "stored_club": stored,
        "proposed_club": proposed,
        "source": "team_name",
        "tier": tier,
        "needs_review": needs_review,
        "approved": tier == "swap",
        "state_note": "",
    }


def _clubs(store, rows, tmp_path):
    scan = tmp_path / "scan.csv"
    swapped.write_log([swapped.snapshot_csv_row(r) for r in rows], scan)
    kept, proposals = pw.club_proposals(pw._read_csv(scan), ["NV"])
    folder = _folder(store, "clubs", proposals)
    swapped.write_log(kept, folder / pw.SCOPED_CLUBS)
    return proposals


def _plan_row(team_id, old, new, tier="A_own_name_band", name=None):
    return {
        "state_code": "NV",
        "team_id_master": team_id,
        "team_name": name or f"Team {team_id}",
        "club_name": "Reno APEX Soccer Club",
        "gender": "Female",
        "gotsport_team_name": "",
        "band": new,
        "old_age_group": old,
        "new_age_group": new,
        "action": "would_update",
        "collision_with": "",
        "evidence_tier": tier,
        "fixture_verdict": "review_group_1_band_older_by_1",
        "opp_games_proposed": "",
        "opp_games_current": "",
    }


def _ages(store, rows):
    folder = stage_dir(store, RUN, "ages")
    folder.mkdir(parents=True, exist_ok=True)
    bands.write_csv(rows, folder / pw.AGE_PLAN, bands.PLAN_FIELDS)
    _folder(store, "ages", pw.age_proposals(pw._read_csv(folder / pw.AGE_PLAN)))


def _build(monkeypatch, capsys, store, db, stage="states"):
    monkeypatch.setattr(pages, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["pages.py", "--run", RUN, "--stage", stage, "--store", str(store)])
    code = pages.main()
    return code, capsys.readouterr().out


def _built(tmp_path, monkeypatch, capsys):
    store, db = _state_week(tmp_path)
    _build(monkeypatch, capsys, store, db)
    return store


def _read(store, stage, name):
    return json.loads((stage_dir(store, RUN, stage) / name).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- which proposals reach the page --------------------------------------------------------------


def _state_week(tmp_path):
    store = tmp_path / "store"
    _reviewing(store)
    _states(
        store,
        [
            _decision("fill", None, "NV"),
            _decision("unsure", "WA", "NV", "queue"),
            _decision("stale", None, "NV"),
            _decision("gone", None, "NV"),
            _decision("missing", None, "NV"),
            _decision("relabel", None, "NV"),
            _decision("moved", None, "NV"),
            _decision("declined", None, "NV"),
            _decision("other", None, "NV"),
            _decision("keep", None, "NV"),
            _decision("stays", "NV", "NV", "confirm"),
        ],
        stale=[
            {
                **pw.state_proposals({"decisions": [_decision("stale", None, "NV")]}, ["NV"])[1][0],
                "changed": {"state_code": [None, "UT"]},
            }
        ],
    )
    db = _Db(
        teams=[
            _team("fill", state=None),
            _team("fill-old", state=None, deprecated=True),
            _team("unsure", state="WA"),
            _team("stale", state="UT"),
            _team("gone", state=None, deprecated=True),
            _team("relabel", state=None),
            _team("moved", state="UT"),
            _team("declined", state=None),
            _team("other", state=None),
            _team("keep", state=None),
            _team("stays"),
        ],
        team_merge_map=[_merged("fill-old", "fill", 1), _merged("old", "keep", 2), _merged("relabel", "keep", 3)],
        team_cleanup_decisions=[
            _declined("declined", "NV", n=1),
            _declined("other", "CA", n=2),
            _declined("other", "NV", n=3, superseded="2026-10-05T00:00:00+00:00"),
            _declined("old", "NV", n=4),
            _declined("fill", "NV", n=5, stage="clubs"),
            _declined("unsure", "NV", n=6, decision="unsure"),
        ],
        games=[
            _game(1, "fill", "x", "2026-08-30"),
            _game(2, "y", "fill-old", "2026-09-12"),
            _game(3, "fill", "z", "2026-09-20", excluded=True),
        ],
    )
    return store, db


def test_the_page_shows_each_live_unchanged_undeclined_change_and_lists_the_rest_with_why(
    tmp_path, monkeypatch, capsys
):
    store, db = _state_week(tmp_path)

    code, out = _build(monkeypatch, capsys, store, db)

    manifest = _read(store, "states", MANIFEST_FILE)
    assert code == 0
    assert [(p["team_id_master"], p["old_value"], p["new_value"]) for p in manifest["cards"].values()] == [
        ("fill", None, "NV"),
        ("other", None, "NV"),
        ("unsure", "WA", "NV"),
    ]
    assert [(p["team_id_master"], p["why"]) for p in manifest["left_out"]] == [
        ("stale", "changed while the week was proposed: {'state_code': [None, 'UT']}"),
        ("gone", "no longer a live team"),
        ("missing", "no longer a live team"),
        ("relabel", "no longer a live team"),
        ("moved", "state_code is now 'UT', not None"),
        ("declined", "declined on 2026-10-01"),
        ("keep", "declined on 2026-10-01"),
    ]
    assert manifest["overflow"] == [] and manifest["cleanup_run"] == RUN and manifest["stage"] == "states"
    assert "3 cards" in out and "left off 7, past the cap 0" in out


def test_each_card_shows_the_team_as_it_stands_with_its_merged_predecessors_games(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)

    html = (stage_dir(store, RUN, "states") / pages.PAGE_FILE).read_text(encoding="utf-8")
    data = json.loads(html.split("const CARDS = ", 1)[1].split(";\n", 1)[0])
    fill = data[0]
    assert {k: fill[k] for k in ("n", "group", "whole", "interest", "change", "why")} == {
        "n": 1,
        "group": "B fill",
        "whole": True,
        "interest": False,
        "change": {"field": "state_code", "old": None, "new": "NV"},
        "why": "club-mates",
    }
    assert fill["team"] == {
        "name": "Team fill",
        "original": None,
        "club": "Las Vegas Sports Academy",
        "state": None,
        "age": "u12",
        "gender": "Male",
        "provider": "gotsport",
        "games": 2,
        "excluded": 1,
        "first": "2026-08-30",
        "last": "2026-09-12",
    }
    assert [(c["group"], c["whole"]) for c in data[1:]] == [("B fill", True), ("B correction (rules unsure)", False)]


def test_a_card_id_carries_the_page_run_and_the_change_it_decides(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)

    manifest = _read(store, "states", MANIFEST_FILE)
    run = manifest["run"]
    digest = hashlib.sha256(b"fill|state_code|NV").hexdigest()[:16]
    assert list(manifest["cards"])[0] == f"{run}_{digest}"
    assert f'const COLLECTION = "decisions-{run}";' in (stage_dir(store, RUN, "states") / pages.PAGE_FILE).read_text(
        encoding="utf-8"
    )


def test_the_build_records_the_hashes_of_the_files_the_collector_reads(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)

    folder = stage_dir(store, RUN, "states")
    marker = _read(store, "states", "page.json")
    assert marker["hashes"] == {
        "proposals.json": _sha(folder / "proposals.json"),
        "snapshot.json": _sha(folder / "snapshot.json"),
        "page.manifest.json": _sha(folder / "page.manifest.json"),
    }
    assert (marker["cards"], marker["left_out"], marker["overflow"]) == (3, 7, 0)
    assert stage_progress(store, RUN, "states").next_step.name == "collect"


def test_a_name_cannot_close_the_script_that_carries_it(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    _states(store, [_decision("t1", None, "NV")])
    db = _Db(teams=[_team("t1", state=None, name="</script><img src=x onerror=alert(1)>")])

    _build(monkeypatch, capsys, store, db)

    html = (stage_dir(store, RUN, "states") / pages.PAGE_FILE).read_text(encoding="utf-8")
    assert "</script><img" not in html and "\\u003c/script>\\u003cimg" in html


def test_teams_users_follow_are_kept_inside_the_cap_and_shown_first_in_their_group(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    _states(
        store, [_decision(t, None, "NV") for t in ("a", "b", "c", "d", "e")] + [_decision("q", "WA", "NV", "queue")]
    )
    today = date.today().isoformat()
    db = _Db(
        teams=[_team(t, state=None) for t in ("a", "b", "c", "d", "e")] + [_team("q", state="WA")],
        team_merge_map=[_merged("c-old", "c")],
        watchlist_items=[{"id": 1, "team_id_master": "c-old"}, {"id": 2, "team_id_master": "q"}],
        report_card_leads=[{"id": 1, "team_id": "d"}],
        scrape_requests=[
            {"id": 1, "team_id_master": "e", "priority": 1, "request_type": "missing_game", "requested_at": today},
            {
                "id": 2,
                "team_id_master": "b",
                "priority": 1,
                "request_type": "missing_game",
                "requested_at": "2024-01-01",
            },
        ],
    )
    monkeypatch.setattr(pages, "CARD_CAP", 5)

    _build(monkeypatch, capsys, store, db)

    manifest = _read(store, "states", MANIFEST_FILE)
    assert [p["team_id_master"] for p in manifest["cards"].values()] == ["c", "d", "e", "a", "q"]
    assert [p["team_id_master"] for p in manifest["overflow"]] == ["b"]


@pytest.mark.parametrize(
    "stage, proposal, group, whole",
    [
        ("clubs", {"tier": "swap", "needs_review": False}, "swap", True),
        ("clubs", {"tier": "provider", "needs_review": False}, "provider", True),
        ("clubs", {"tier": "word", "needs_review": False}, "word", True),
        ("clubs", {"tier": "bracket", "needs_review": False}, "bracket", True),
        ("clubs", {"tier": "swap", "needs_review": True}, "swap (needs review)", False),
        ("clubs", {"tier": "capital", "needs_review": False}, "capital", False),
        ("clubs", {"tier": "recased", "needs_review": False}, "recased", False),
        ("states", {"tier": "B", "old_value": None, "action": "apply"}, "B fill", True),
        ("states", {"tier": "B", "old_value": None, "action": "queue"}, "B fill (rules unsure)", False),
        ("states", {"tier": "B", "old_value": "WA", "action": "apply"}, "B correction", False),
        ("states", {"tier": "E", "old_value": None, "action": "apply"}, "E fill", False),
        ("ages", {"tier": "U_own_name_ulabel_opponent_confirmed"}, "U_own_name_ulabel_opponent_confirmed", True),
    ],
)
def test_only_the_tiers_a_skill_already_trusts_can_be_applied_whole(stage, proposal, group, whole):
    assert pages.group_of(stage, proposal) == group
    assert pages.whole(stage, group) is whole


# --- when a page cannot be built -------------------------------------------------------------------


def test_unreadable_decisions_stop_the_page_rather_than_show_declined_changes(tmp_path, monkeypatch, capsys):
    store, db = _state_week(tmp_path)
    db.broken["team_cleanup_decisions"] = APIError({"code": "PGRST205", "message": "not found"})

    with pytest.raises(SystemExit, match="could not read team_cleanup_decisions"):
        _build(monkeypatch, capsys, store, db)
    assert not (stage_dir(store, RUN, "states") / pages.PAGE_FILE).exists()


@pytest.mark.parametrize(
    "status, stages, stage, message",
    [
        ("proposing", {}, "states", "is proposing; pages are built and collected while it is reviewing"),
        ("reviewing", {"states": "skill_stale: check failed"}, "states", "states has no proposals this run"),
    ],
)
def test_a_page_waits_for_the_run_to_reach_review(tmp_path, monkeypatch, capsys, status, stages, stage, message):
    store, db = _state_week(tmp_path)
    write_run(store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": status, "budgets": {}, "stages": stages})

    with pytest.raises(SystemExit, match=message):
        _build(monkeypatch, capsys, store, db, stage)


def test_a_stage_still_proposing_has_no_page(tmp_path, monkeypatch, capsys):
    store, db = _state_week(tmp_path)
    (stage_dir(store, RUN, "states") / PROPOSE_MARKER).unlink()

    with pytest.raises(SystemExit, match="states is not ready for this: next, write the stage's proposals"):
        _build(monkeypatch, capsys, store, db)


def test_a_collected_stage_cannot_have_its_page_rebuilt(tmp_path, monkeypatch, capsys):
    store, db = _state_week(tmp_path)
    _build(monkeypatch, capsys, store, db)
    _collect(monkeypatch, capsys, store, "states", _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}}))

    with pytest.raises(SystemExit, match="next, the owner runs the apply"):
        _build(monkeypatch, capsys, store, db)


# --- collecting the owner's choices ----------------------------------------------------------


def _choose(store, stage, tmp_path, picks, *, nested=True):
    """Save the page's choices the way ArtifactData's out_dir does: picks keyed by team id, each
    saved under its card's id."""
    manifest = _read(store, stage, MANIFEST_FILE)
    folder = tmp_path / "out" / (f"decisions-{manifest['run']}" if nested else "")
    folder.mkdir(parents=True, exist_ok=True)
    ids = {p["team_id_master"]: card_id for card_id, p in manifest["cards"].items()}
    for team_id, data in picks.items():
        (folder / f"{ids[team_id]}.json").write_text(json.dumps({"id": ids[team_id], "data": data}), encoding="utf-8")
    return tmp_path / "out"


def _collect(monkeypatch, capsys, store, stage, out):
    monkeypatch.setattr(
        sys, "argv", ["collect.py", "--run", RUN, "--stage", stage, "--decisions", str(out), "--store", str(store)]
    )
    code = col.main()
    return code, capsys.readouterr().out


def test_state_choices_become_a_snapshot_the_state_applier_replays(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(
        store,
        "states",
        tmp_path,
        {
            "fill": {"decision": "apply", "note": ""},
            "unsure": {"decision": "apply", "note": "  club moved to Reno  "},
            "other": {"decision": "dont_apply", "note": "plays in CA"},
        },
    )

    code, printed = _collect(monkeypatch, capsys, store, "states", out)

    folder = stage_dir(store, RUN, "states")
    vetted = json.loads((folder / "vetted.json").read_text(encoding="utf-8"))
    assert code == 0
    assert {k: v for k, v in vetted.items() if k != "decisions"} == {
        "rules": "authority",
        "created_at": "2026-10-14T18:00:00",
        "live_teams": 9,
    }
    assert vetted["decisions"] == [_decision("fill", None, "NV"), _decision("unsure", "WA", "NV", "queue")]
    rows = json.loads((folder / "decisions.json").read_text(encoding="utf-8"))
    run = _read(store, "states", MANIFEST_FILE)["run"]
    built = f"{run[0:4]}-{run[4:6]}-{run[6:8]}T{run[9:11]}:{run[11:13]}:{run[13:15]}+00:00"
    assert [(r["team_id_master"], r["decision"], r["note"], r["decided_at"], r["source"]) for r in rows] == [
        ("fill", "apply", None, built, f"page:{run}"),
        ("other", "dont_apply", "plays in CA", built, f"page:{run}"),
        ("unsure", "apply", "club moved to Reno", built, f"page:{run}"),
    ]
    marker = _read(store, "states", "collected.json")
    assert marker["counts"] == {"apply": 2, "dont_apply": 1, "unsure": 0, "undecided": 0}
    assert marker["vetted"] == "vetted.json"
    assert marker["hashes"] == {
        "vetted.json": _sha(folder / "vetted.json"),
        "decisions.json": _sha(folder / "decisions.json"),
    }
    assert "dont_apply 'Team other': None -> 'NV'  note: 'plays in CA'" in printed


def test_club_choices_become_approved_snapshot_rows_the_club_applier_reads_back(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    _clubs(
        store,
        [
            _scan_row("c1", "-LVSA", "Las Vegas Sports Academy"),
            _scan_row("c2", "Henderson", "=Henderson FC", tier="word", needs_review=True),
            _scan_row("c3", "Reno", "Reno United"),
        ],
        tmp_path,
    )
    db = _Db(teams=[_team("c1", club="-LVSA"), _team("c2", club="Henderson"), _team("c3", club="reno")])
    _build(monkeypatch, capsys, store, db, "clubs")
    out = _choose(
        store,
        "clubs",
        tmp_path,
        {"c1": {"decision": "apply"}, "c2": {"decision": "apply"}, "c3": {"decision": "unsure"}},
    )

    _collect(monkeypatch, capsys, store, "clubs", out)

    rows = swapped.load_snapshot(stage_dir(store, RUN, "clubs") / "vetted.csv")
    assert [(r["team_id_master"], r["stored_club"], r["proposed_club"], swapped.is_approved(r)) for r in rows] == [
        ("c1", "-LVSA", "Las Vegas Sports Academy", True),
        ("c2", "Henderson", "=Henderson FC", True),
    ]


def test_age_choices_become_plan_rows_the_age_applier_reads_back(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    _ages(store, [_plan_row("g1", "u10", "u9", name="=GOLD G2017-18"), _plan_row("g2", "u10", "u9")])
    db = _Db(teams=[_team("g1", age="u10", name="=GOLD G2017-18"), _team("g2", age="u10")])
    _build(monkeypatch, capsys, store, db, "ages")
    out = _choose(store, "ages", tmp_path, {"g1": {"decision": "apply"}, "g2": {"decision": "dont_apply"}})

    _collect(monkeypatch, capsys, store, "ages", out)

    rows = bands.read_our_csv(stage_dir(store, RUN, "ages") / "vetted.csv")
    assert rows == [{k: str(v) for k, v in _plan_row("g1", "u10", "u9", name="=GOLD G2017-18").items()}]


def test_with_nothing_chosen_to_apply_no_applier_input_is_left_behind(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    _collect(monkeypatch, capsys, store, "states", _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}}))
    out = _choose(store, "states", tmp_path / "again", {"fill": {"decision": "unsure"}})

    code, printed = _collect(monkeypatch, capsys, store, "states", out)

    assert code == 0 and "nothing to apply" in printed
    assert not (stage_dir(store, RUN, "states") / "vetted.json").exists()
    marker = _read(store, "states", "collected.json")
    assert marker["vetted"] is None and set(marker["hashes"]) == {"decisions.json"}


def test_a_stage_that_proposed_nothing_gets_an_empty_page_and_collects_to_nothing(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    assert _clubs(store, [{**_scan_row("ut1", "SLC", "Salt Lake City FC"), "state": "UT"}], tmp_path) == []
    assert not (stage_dir(store, RUN, "clubs") / pw.SCOPED_CLUBS).exists()

    _build(monkeypatch, capsys, store, _Db(), "clubs")
    code, printed = _collect(monkeypatch, capsys, store, "clubs", tmp_path / "never-saved")

    assert _read(store, "clubs", "page.json")["hashes"]["repair_swapped_club_names.csv"] is None
    assert code == 0 and "nothing to apply" in printed
    counts = _read(store, "clubs", "collected.json")["counts"]
    assert counts == {"apply": 0, "dont_apply": 0, "unsure": 0, "undecided": 0}


def test_an_applier_input_that_appears_after_an_empty_page_is_refused(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    _clubs(store, [{**_scan_row("ut1", "SLC", "Salt Lake City FC"), "state": "UT"}], tmp_path)
    _build(monkeypatch, capsys, store, _Db(), "clubs")
    (stage_dir(store, RUN, "clubs") / pw.SCOPED_CLUBS).write_text("team_id_master", encoding="utf-8")

    with pytest.raises(SystemExit, match="changed since the page was built: repair_swapped_club_names.csv"):
        _collect(monkeypatch, capsys, store, "clubs", tmp_path / "never-saved")


def test_choices_are_read_from_the_out_dir_itself_too(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}}, nested=False)

    _collect(monkeypatch, capsys, store, "states", out)

    assert _read(store, "states", "collected.json")["counts"] == {
        "apply": 1,
        "dont_apply": 0,
        "unsure": 0,
        "undecided": 2,
    }


@pytest.mark.parametrize(
    "data, message",
    [
        ({"decision": "merge"}, "holds a decision or note the page never writes"),
        ({"decision": True}, "holds a decision or note the page never writes"),
        ({"decision": "apply", "note": 5}, "holds a decision or note the page never writes"),
        ({"decision": "apply", "note": "a\x00b"}, "holds a decision or note the page never writes"),
    ],
    ids=["unknown-decision", "boolean-decision", "number-note", "nul-note"],
)
def test_a_choice_the_page_never_writes_is_refused(tmp_path, monkeypatch, capsys, data, message):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": data})

    with pytest.raises(SystemExit, match=message):
        _collect(monkeypatch, capsys, store, "states", out)
    assert not (stage_dir(store, RUN, "states") / "collected.json").exists()


def test_a_choice_for_a_card_the_page_never_showed_is_refused(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}})
    run = _read(store, "states", MANIFEST_FILE)["run"]
    stray = out / f"decisions-{run}" / f"{run}_0000000000000000.json"
    stray.write_text(json.dumps({"decision": "apply"}), encoding="utf-8")

    with pytest.raises(SystemExit, match="1 saved choice\\(s\\) name no card on this page"):
        _collect(monkeypatch, capsys, store, "states", out)


def test_a_saved_file_claiming_another_card_s_id_is_refused(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {})
    run = _read(store, "states", MANIFEST_FILE)["run"]
    real = list(_read(store, "states", MANIFEST_FILE)["cards"])[0]
    (out / f"decisions-{run}" / "other.json").write_text(
        json.dumps({"id": real, "data": {"decision": "apply"}}), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match=f"document other claims to be {real}"):
        _collect(monkeypatch, capsys, store, "states", out)


def test_finding_no_choices_is_refused(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    (tmp_path / "out").mkdir()

    with pytest.raises(SystemExit, match="no saved choices were found"):
        _collect(monkeypatch, capsys, store, "states", tmp_path / "out")


@pytest.mark.parametrize("name", ["proposals.json", "snapshot.json", "page.manifest.json"])
def test_a_stage_file_changed_after_the_build_is_refused(tmp_path, monkeypatch, capsys, name):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}})
    path = stage_dir(store, RUN, "states") / name
    path.write_text(path.read_text(encoding="utf-8").replace('"NV"', '"CA"', 1), encoding="utf-8")

    with pytest.raises(SystemExit, match=f"changed since the page was built: {name}"):
        _collect(monkeypatch, capsys, store, "states", out)


def test_an_applied_stage_is_not_collected_again(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}})
    _collect(monkeypatch, capsys, store, "states", out)
    (stage_dir(store, RUN, "states") / "RECORD.md").write_text("applied", encoding="utf-8")

    with pytest.raises(SystemExit, match="already applied"):
        _collect(monkeypatch, capsys, store, "states", out)


def test_collecting_never_opens_the_database(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}})

    def refuse(*args, **kwargs):
        raise AssertionError("the collector opened a database client")

    monkeypatch.setattr(pw, "get_client", refuse)
    monkeypatch.setattr("supabase.create_client", refuse)

    code, _ = _collect(monkeypatch, capsys, store, "states", out)
    assert code == 0


def test_a_card_saved_with_no_decision_is_collected_as_undecided(tmp_path, monkeypatch, capsys):
    """The page saves a null decision for a note typed before choosing, and for a choice cleared."""
    store = _built(tmp_path, monkeypatch, capsys)
    picks = {
        "fill": {"decision": "apply"},
        "other": {"decision": None, "note": "ask the coach"},
        "unsure": {"decision": None},
    }

    _collect(monkeypatch, capsys, store, "states", _choose(store, "states", tmp_path, picks))

    rows = _read(store, "states", "decisions.json")
    assert [(r["team_id_master"], r["decision"]) for r in rows] == [("fill", "apply")]
    counts = _read(store, "states", "collected.json")["counts"]
    assert counts == {"apply": 1, "dont_apply": 0, "unsure": 0, "undecided": 2}


@pytest.mark.parametrize(
    "status, stages, message",
    [
        ("done", {}, "run 2026-10-14-nv is done; pages are built and collected while it is reviewing"),
        ("reviewing", {"states": "skill_stale: check failed"}, "states has no proposals this run: skill_stale"),
    ],
    ids=["run-done", "stage-skill-stale"],
)
def test_choices_are_collected_only_while_the_run_is_in_review(tmp_path, monkeypatch, capsys, status, stages, message):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}})
    write_run(store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": status, "budgets": {}, "stages": stages})

    with pytest.raises(SystemExit, match=message):
        _collect(monkeypatch, capsys, store, "states", out)
    assert not (stage_dir(store, RUN, "states") / "collected.json").exists()


def test_a_stage_past_the_cap_reads_its_teams_in_batches_and_lists_the_rest(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _reviewing(store)
    ids = [f"t{n:03}" for n in range(160)]
    _states(store, [_decision(t, None, "NV") for t in ids])

    _build(monkeypatch, capsys, store, _Db(teams=[_team(t, state=None) for t in ids]))

    manifest = _read(store, "states", MANIFEST_FILE)
    assert len(manifest["cards"]) == 150
    assert [p["team_id_master"] for p in manifest["overflow"]] == ids[150:]


def test_a_blank_state_read_back_padded_is_unchanged(tmp_path, monkeypatch, capsys):
    """state_code is CHAR(2): a blank one reads back as two spaces, while the proposal names none."""
    store = tmp_path / "store"
    _reviewing(store)
    _states(store, [_decision("t1", None, "NV")])

    _build(monkeypatch, capsys, store, _Db(teams=[_team("t1", state="  ")]))

    assert [p["team_id_master"] for p in _read(store, "states", MANIFEST_FILE)["cards"].values()] == ["t1"]


def test_a_club_that_gained_a_space_since_it_was_proposed_is_left_off(tmp_path, monkeypatch, capsys):
    """The club applier compares clubs ignoring case but not spaces, so it would skip this one."""
    store = tmp_path / "store"
    _reviewing(store)
    _clubs(store, [_scan_row("c1", "Sparks", "Sparks United")], tmp_path)

    _build(monkeypatch, capsys, store, _Db(teams=[_team("c1", club="Sparks ")]), "clubs")

    left_out = _read(store, "clubs", MANIFEST_FILE)["left_out"]
    assert [(p["team_id_master"], p["why"]) for p in left_out] == [("c1", "club_name is now 'Sparks ', not 'Sparks'")]


def test_a_club_guess_the_scan_lists_without_approving_gets_no_card(tmp_path, monkeypatch, capsys):
    """The skill writes a recased, unclear or capital row only when a person opts it in, so the page
    leaves them off. A conflict row from a trusted tier, held back for a person, keeps its card."""
    store = tmp_path / "store"
    _reviewing(store)
    _clubs(
        store,
        [
            _scan_row("swap", "LVSA", "Las Vegas Sports Academy"),
            {**_scan_row("provider", "SPARKS", "Sparks United", tier="provider"), "approved": True},
            {**_scan_row("bracket", "Elko [EYS]", "Elko [eys]", tier="bracket"), "approved": True},
            _scan_row("conflict", "Reno", "Reno United", tier="word", needs_review=True),
            _scan_row("recased", "RSL Arizona", "RSL-AZ - North", tier="recased"),
            _scan_row("unclear", "RSL Arizona", "07", tier="unclear", needs_review=True),
            _scan_row("capital", "Henderson", "=Henderson FC", tier="capital"),
        ],
        tmp_path,
    )
    teams = [
        _team("swap", club="LVSA"),
        _team("provider", club="SPARKS"),
        _team("bracket", club="Elko [EYS]"),
        _team("conflict", club="Reno"),
        _team("recased", club="RSL Arizona"),
        _team("unclear", club="RSL Arizona"),
        _team("capital", club="Henderson"),
    ]

    code, out = _build(monkeypatch, capsys, store, _Db(teams=teams), "clubs")

    manifest = _read(store, "clubs", MANIFEST_FILE)
    assert code == 0
    cards = sorted(p["team_id_master"] for p in manifest["cards"].values())
    assert cards == ["bracket", "conflict", "provider", "swap"]
    assert [(p["team_id_master"], p["why"]) for p in manifest["left_out"]] == [
        ("recased", "the scan lists recased guesses without approving them"),
        ("unclear", "the scan lists unclear guesses without approving them"),
        ("capital", "the scan lists capital guesses without approving them"),
    ]
    assert "4 cards" in out and "left off 3, past the cap 0" in out


@pytest.mark.parametrize(
    "script, args, message",
    [
        (pages, ["--run", RUN, "--stage", "states", "--store", "relative-store"], "must be an absolute path"),
        (
            col,
            ["--run", RUN, "--stage", "states", "--decisions", "x", "--store", "relative-store"],
            "must be an absolute path",
        ),
        (col, ["--run", "2026-10-14-NV", "--stage", "states", "--decisions", "x"], "is not a run id"),
    ],
    ids=["page-relative-store", "collect-relative-store", "collect-bad-run"],
)
def test_a_bad_store_or_run_ends_with_a_message_not_a_traceback(monkeypatch, script, args, message):
    monkeypatch.setattr(pages, "get_client", lambda: _Db())
    monkeypatch.setattr(sys, "argv", ["script.py", *args])

    with pytest.raises(SystemExit) as caught:
        script.main()
    assert message in str(caught.value)


def test_the_page_never_saves_a_team_id():
    template = pages.TEMPLATE.read_text(encoding="utf-8")
    writer = template[template.index("function save(") : template.index("buildPage();")]
    assert "team" not in writer


def test_the_page_writes_the_fields_the_collector_reads():
    template = pages.TEMPLATE.read_text(encoding="utf-8")
    assert 'await ref.set({decision: null, note: "", ...choice(id), ...body});' in template
    assert "save(c.id, {decision:" in template and "save(c.id, {note:" in template
    assert 'await save(x.id, {decision: "apply"});' in template
