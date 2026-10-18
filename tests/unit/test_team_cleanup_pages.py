"""Tests for the weekly cleanup's single-team review pages and the collector that reads them back."""

import hashlib
import json
import os
import shlex
import sys
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from postgrest.exceptions import APIError
from postgrest.types import ReturnMethod

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import fix_band_cohorts as bands  # noqa: E402
from scripts import repair_swapped_club_names as swapped  # noqa: E402
from scripts.team_cleanup import collect as col  # noqa: E402
from scripts.team_cleanup import pages  # noqa: E402
from scripts.team_cleanup import propose_week as pw  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    APPLY_LOCK_FILE,
    MANIFEST_FILE,
    PREFLIGHT_MARKER,
    PROPOSALS_FILE,
    PROPOSE_MARKER,
    STALE_FILE,
    run_dir,
    stage_dir,
    stage_progress,
    write_run,
)
from src.tournaments.storage._file_lock import _acquire_file_lock  # noqa: E402
from src.tournaments.storage._io import write_json  # noqa: E402
from tests.unit import test_team_cleanup_cards_migration as cards_migration  # noqa: E402

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
        "state",
        "state_source",
        "provider_id",
        "is_deprecated",
    },
    "team_merge_map": {"id", "deprecated_team_id", "canonical_team_id"},
    "team_state_probe_log": {"id", "team_id_master", "outcome", "reported_state_code", "probed_at"},
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
    "team_cleanup_changes": {"id", "stage", "team_id_master", "field", "new_value", "reverted_at"},
    "providers": {"id", "code"},
    "games": {"id", "home_team_master_id", "away_team_master_id", "game_date", "is_excluded"},
    "watchlist_items": {"id", "team_id_master"},
    "report_card_leads": {"id", "team_id"},
    "scrape_requests": {"id", "team_id_master", "priority", "request_type", "requested_at"},
    "team_cleanup_runs": {"run_id"},
    "team_cleanup_cards": {
        "card_id",
        "run_id",
        "stage",
        "lane",
        "page_run",
        "position",
        "card",
        "decision",
        "note",
        "decided_at",
        "decided_by_user_id",
        "created_at",
    },
}
# What the cards table's migration refuses: its NOT NULL columns, listed by hand, and the values its IN-list
# CHECKs allow, read from the migration itself.
CARD_REQUIRED = ("card_id", "run_id", "stage", "lane", "page_run", "position", "card", "created_at")
CARD_STAGES, CARD_LANES, CARD_DECISIONS = (cards_migration._in_list(c) for c in ("stage", "lane", "decision"))


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records each read at execute(), where the real builder sends it. It answers at most ROW_CAP
    rows, refuses an unknown column and a ranged page with no order. A page build writes only by
    publishing, an insert (_CardsInsert), so there is no update or delete to call."""

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


def _refusal(code, message):
    return APIError({"code": code, "message": message})


# The cards insert, as `broken` and `executes` name it apart from a read of the same table.
INSERT = ("team_cleanup_cards", "insert")


def _pg_time(moment):
    """A timestamptz as PostgREST renders it: the fraction's trailing zeros dropped, and a zero fraction
    with them."""
    text = moment.isoformat()
    stamp, offset = text[:-6], text[-6:]
    return (stamp.rstrip("0").rstrip(".") if "." in stamp else stamp) + offset


class _CardsInsert:
    """An insert into team_cleanup_cards, checked at execute() as its migration would: one statement, so a
    single bad row refuses the lot. Defaults fill only the columns a row leaves out, created_at with the
    statement's time as now() does: one per insert, a quarter second later for each. A CHECK passes on NULL,
    as Postgres's does, and the auto lane's `decision IS NOT DISTINCT FROM 'apply'` does not; with no auth
    user, any decided_by_user_id fails its foreign key. A table named in ``lost`` stores the rows and then
    loses the answer, as a dropped connection does."""

    DEFAULTS = {"note": None, "decision": None, "decided_at": None, "decided_by_user_id": None}

    def __init__(self, db, rows, returning):
        self._db, self._sent, self._returning = db, rows if isinstance(rows, list) else [rows], returning

    def execute(self):
        self._db.executes.append(INSERT)
        if INSERT in self._db.broken:
            raise self._db.broken[INSERT]
        self._db.now += timedelta(milliseconds=250)
        defaults = {**self.DEFAULTS, "created_at": _pg_time(self._db.now)}
        # As the client serialises them: a value JSON cannot carry fails before any row is stored.
        rows = [{**defaults, **json.loads(json.dumps(sent, allow_nan=False))} for sent in self._sent]
        table = self._db.tables["team_cleanup_cards"]
        runs, ids = {r["run_id"] for r in self._db.tables["team_cleanup_runs"]}, {r["card_id"] for r in table}
        for sent, row in zip(self._sent, rows):
            assert set(sent) <= COLUMNS["team_cleanup_cards"], f"PostgREST refuses unknown columns in {sorted(sent)}"
            if any(row[column] is None for column in CARD_REQUIRED):
                raise _refusal("23502", f"null value in a NOT NULL column of {row}")
            checks = (
                row["stage"] in CARD_STAGES,
                row["lane"] in CARD_LANES,
                row["position"] >= 1,
                row["decision"] in (*CARD_DECISIONS, None),
                len(row["note"] or "") <= 2000,
                row["card_id"][: len(row["page_run"]) + 1] == row["page_run"] + "_",
                row["lane"] == "owner" or row["decision"] == "apply",
            )
            if not all(checks):
                raise _refusal("23514", f"new row for team_cleanup_cards violates a check constraint: {row['card_id']}")
            if row["run_id"] not in runs:
                raise _refusal("23503", "insert violates foreign key constraint team_cleanup_cards_run_id_fkey")
            if row["decided_by_user_id"] is not None:
                raise _refusal("23503", "insert violates foreign key constraint on decided_by_user_id")
            if row["card_id"] in ids:
                raise _refusal("23505", "duplicate key value violates unique constraint team_cleanup_cards_pkey")
            ids.add(row["card_id"])
        table.extend(rows)
        if "team_cleanup_cards" in self._db.lost:
            raise self._db.lost["team_cleanup_cards"]
        return _Result([] if self._returning == ReturnMethod.minimal else rows)


class _Db:
    def __init__(self, **tables):
        self.tables = {name: [dict(r) for r in tables.get(name, ())] for name in COLUMNS}
        self.tables["providers"] = self.tables["providers"] or [{"id": 1, "code": "gotsport"}]
        self.tables["team_cleanup_runs"] = self.tables["team_cleanup_runs"] or [{"run_id": RUN}]
        self.broken, self.lost, self.executes = {}, {}, []
        self.now = datetime(2026, 10, 15, 3, 0, 10, tzinfo=timezone.utc)

    def table(self, name):
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, name, [c.strip() for c in columns.split(",")])

            def insert(self, rows, returning=ReturnMethod.representation):
                assert name == "team_cleanup_cards", f"a page build writes only team_cleanup_cards, not {name}"
                return _CardsInsert(db, rows, returning)

        return _T()

    def cards(self, **match):
        return [r for r in self.tables["team_cleanup_cards"] if all(r[k] == v for k, v in match.items())]


def _team(tid, *, state="NV", club="Las Vegas Sports Academy", age="u12", deprecated=False, name=None):
    return {
        "team_id_master": tid,
        "team_name": name or f"Team {tid}",
        "team_name_original": None,
        "club_name": club,
        "age_group": age,
        "gender": "Male",
        "state_code": state,
        "state": None,
        "state_source": None,
        "provider_id": 1,
        "is_deprecated": deprecated,
    }


def _probe(tid, state, *, outcome="mapped", days_ago=1, n=1):
    probed = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "id": n,
        "team_id_master": tid,
        "outcome": outcome,
        "reported_state_code": state,
        "probed_at": probed.isoformat(),
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
    _folder(store, "ages", pw.age_proposals(pw._read_csv(folder / pw.AGE_PLAN), []))


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


def _cards(store, stage):
    """The card records the built page carries in its script."""
    html = (stage_dir(store, RUN, stage) / pages.PAGE_FILE).read_text(encoding="utf-8")
    return json.loads(html.split("const CARDS = ", 1)[1].split(";\n", 1)[0])


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

    data = _cards(store, "states")
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


def test_cards_in_one_group_from_one_club_with_the_same_change_share_a_key(tmp_path, monkeypatch, capsys):
    """A placeholder or blank club shares nothing, and a card the rules only queued sits in another
    group, so it is never decided together with a confident card."""
    store = tmp_path / "store"
    _reviewing(store)
    targets = {"a": (None, "NV"), "b": (None, "NV"), "c": ("WA", "NV"), "d": (None, "NV"), "e": (None, "NV")}
    decisions = [_decision(t, old, new) for t, (old, new) in targets.items()]
    _states(store, decisions + [_decision("q", None, "NV", "queue")])
    teams = [
        _team("a", state=None, club="Reno United"),
        _team("b", state=None, club=" reno united "),
        _team("c", state="WA", club="Reno United"),
        _team("d", state=None, club="No Club Selection"),
        _team("e", state=None, club=None),
        _team("q", state=None, club="Reno United"),
    ]

    _build(monkeypatch, capsys, store, _Db(teams=teams))

    assert {c["team"]["name"]: c["alike"] for c in _cards(store, "states")} == {
        "Team a": '["reno united", "B fill", "state_code", null, "NV"]',
        "Team b": '["reno united", "B fill", "state_code", null, "NV"]',
        "Team c": '["reno united", "B correction", "state_code", "WA", "NV"]',
        "Team d": None,
        "Team e": None,
        "Team q": '["reno united", "B fill (rules unsure)", "state_code", null, "NV"]',
    }


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
    monkeypatch.setattr(pages, "load_caps", lambda: pages.Caps(cards=5, auto=0))

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


def test_collecting_saved_choices_never_opens_the_database(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)
    out = _choose(store, "states", tmp_path, {"fill": {"decision": "apply"}})

    def refuse(*args, **kwargs):
        raise AssertionError("the collector opened a database client")

    monkeypatch.setattr(pw, "get_client", refuse)
    monkeypatch.setattr(col, "get_client", refuse)
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

    db = _Db(teams=teams)
    # A clubs page has no use for GotSport's state answers, so it must not fail when they cannot be read.
    db.broken["team_state_probe_log"] = APIError({"code": "PGRST205", "message": "not found"})

    code, out = _build(monkeypatch, capsys, store, db, "clubs")

    manifest = _read(store, "clubs", MANIFEST_FILE)
    assert code == 0
    assert "team_state_probe_log" not in db.executes
    cards = sorted(p["team_id_master"] for p in manifest["cards"].values())
    assert cards == ["bracket", "conflict", "provider", "swap"]
    assert [(p["team_id_master"], p["why"]) for p in manifest["left_out"]] == [
        ("recased", "the scan lists recased guesses without approving them"),
        ("unclear", "the scan lists unclear guesses without approving them"),
        ("capital", "the scan lists capital guesses without approving them"),
    ]
    assert "4 cards" in out and "left off 3, past the cap 0" in out


def test_a_state_change_a_recent_gotsport_answer_contradicts_gets_no_card(tmp_path, monkeypatch, capsys):
    """Only a recent, mapped answer counts, as in the states skill's name pass: the unset default
    AL, a transient failure and an answer past the re-probe window say nothing about the team."""
    store = tmp_path / "store"
    _reviewing(store)
    ids = ("kept", "agree", "transient", "stale", "lock")
    decisions = [_decision(t, "NV", "NV" if t == "lock" else "UT") for t in ids]
    _states(store, decisions + [_decision("default", "AL", "NV"), _decision("fill", None, "NV")])
    probes = [
        _probe("kept", "NV", n=1),
        _probe("agree", "UT", n=2),
        _probe("default", "AL", n=3),
        _probe("transient", "NV", outcome="http 403", n=4),
        _probe("stale", "NV", days_ago=120, n=5),
        _probe("lock", "NV", n=6),
    ]
    teams = [_team(t) for t in ids] + [_team("default", state="AL"), _team("fill", state=None)]

    code, out = _build(monkeypatch, capsys, store, _Db(teams=teams, team_state_probe_log=probes))

    manifest = _read(store, "states", MANIFEST_FILE)
    assert code == 0
    cards = sorted(p["team_id_master"] for p in manifest["cards"].values())
    assert cards == ["agree", "default", "fill", "lock", "stale", "transient"]
    assert [(p["team_id_master"], p["why"]) for p in manifest["left_out"]] == [("kept", "GotSport's record says NV")]
    assert "6 cards" in out and "left off 1, past the cap 0" in out


def test_a_state_change_the_name_already_answers_gets_no_card(tmp_path, monkeypatch, capsys):
    """The name pass answers a change its name contradicts. A change the name backs keeps its card,
    and so does one whose name points at a third state, or one GotSport backs against the name."""
    store = tmp_path / "store"
    _reviewing(store)
    targets = {"nevada": "CA", "utah": "UT", "third": "UT", "gotsport": "UT", "plain": "UT"}
    _states(store, [_decision(t, "NV", new) for t, new in targets.items()])
    teams = [
        _team("nevada", name="Northern Nevada 2012 Boys"),
        _team("utah", name="Utah Royals FC 2012"),
        _team("third", name="California Storm 2012"),
        _team("gotsport", name="Northern Nevada 2012 Girls"),
        _team("plain"),
    ]

    code, out = _build(monkeypatch, capsys, store, _Db(teams=teams, team_state_probe_log=[_probe("gotsport", "UT")]))

    manifest = _read(store, "states", MANIFEST_FILE)
    assert code == 0
    assert sorted(p["team_id_master"] for p in manifest["cards"].values()) == ["gotsport", "plain", "third", "utah"]
    assert [(p["team_id_master"], p["why"]) for p in manifest["left_out"]] == [
        ("nevada", "its name or club name places it in NV"),
    ]


def test_the_build_reports_which_cards_the_evidence_already_settles_and_still_shows_them(
    tmp_path, monkeypatch, capsys
):
    """A fill is sure unless GotSport disputes it, the hold check holds it (an operator answered the
    team), or an undo reversed it, even on a team since merged into the one proposed."""
    store = tmp_path / "store"
    _reviewing(store)
    names = ("fill", "disputed", "answered", "undone")
    _states(store, [_decision(t, None, "NV") for t in names] + [_decision("moved", "UT", "NV")])
    teams = [_team(t, state=None) for t in names] + [_team("moved", state="UT")]
    teams[2]["state_source"] = "operator"
    undo = {
        "id": 1,
        "stage": "states",
        "team_id_master": "undone-old",
        "field": "state_code",
        "new_value": "NV",
        "reverted_at": "2026-10-12T00:00:00+00:00",
    }
    db = _Db(
        teams=teams,
        team_state_probe_log=[_probe("disputed", "UT")],
        team_merge_map=[_merged("undone-old", "undone")],
        team_cleanup_changes=[undo],
    )

    code, out = _build(monkeypatch, capsys, store, db)

    manifest = _read(store, "states", MANIFEST_FILE)
    assert code == 0
    assert sorted(p["team_id_master"] for p in manifest["cards"].values()) == sorted([*names, "moved"])
    assert {manifest["cards"][c]["team_id_master"]: why for c, why in manifest["sure"].items()} == {
        "fill": "a blank state filled from its club, which nothing disputes"
    }
    assert _read(store, "states", pages.PAGE_MARKER)["sure"] == 1
    assert "the evidence already settles 1: 0 go to the automatic lane, the rest stay cards" in out


def test_an_ages_page_settles_a_far_u_label_move_only_where_the_review_saw_a_second_witness(
    tmp_path, monkeypatch, capsys
):
    """The propose step joins the review's readings to the plan, and the build reads them."""
    store = tmp_path / "store"
    _reviewing(store)
    folder = stage_dir(store, RUN, "ages")
    folder.mkdir(parents=True, exist_ok=True)
    tier = "U_own_name_ulabel_opponent_confirmed"
    bands.write_csv(
        [_plan_row("confirmed", "u17", "u9", tier), _plan_row("lone", "u17", "u9", tier)],
        folder / pw.AGE_PLAN,
        bands.PLAN_FIELDS,
    )
    (folder / pw.AGE_REVIEW_FILE).write_text(
        "team_id,gotsport_age,div_says,band_opps_say,year_witness\nconfirmed,,,u9,A 3:0\nlone,,,,A 3:0\n",
        encoding="utf-8",
    )
    _folder(store, "ages", pw.scoped_proposals("ages", folder, ["NV"]))

    db = _Db(teams=[_team("confirmed", age="u17"), _team("lone", age="u17")])

    code, _ = _build(monkeypatch, capsys, store, db, "ages")

    manifest = _read(store, "ages", MANIFEST_FILE)
    assert code == 0
    assert [manifest["cards"][c]["team_id_master"] for c in manifest["sure"]] == ["confirmed"]


def test_a_states_page_with_no_change_to_answer_reads_no_evidence(tmp_path, monkeypatch, capsys):
    """A page of lock cards has no change to answer, so it skips the evidence reads, the first of which
    is GotSport's answers; the name pass's read of every team in the country comes after it."""
    store = tmp_path / "store"
    _reviewing(store)
    _states(store, [_decision("lock", "NV", "NV")])
    db = _Db(teams=[_team("lock")])
    db.broken["team_state_probe_log"] = APIError({"code": "PGRST205", "message": "not found"})

    code, _ = _build(monkeypatch, capsys, store, db)

    assert code == 0
    assert "team_state_probe_log" not in db.executes
    assert [p["team_id_master"] for p in _read(store, "states", MANIFEST_FILE)["cards"].values()] == ["lock"]


# --- the automatic lane ----------------------------------------------------------------------------


def _sure_week(tmp_path, monkeypatch, auto):
    """Three fills nothing disputes and a correction, which is never sure, with ``auto`` the lane's cap."""
    store = tmp_path / "store"
    _reviewing(store)
    _states(store, [_decision(t, None, "NV") for t in ("a", "b", "c")] + [_decision("fix", "UT", "NV")])
    db = _Db(teams=[_team(t, state=None) for t in ("a", "b", "c")] + [_team("fix", state="UT")])
    monkeypatch.setattr(pages, "load_caps", lambda: pages.Caps(cards=150, auto=auto))
    return store, db


def _collect_auto(monkeypatch, capsys, store, stage):
    monkeypatch.setattr(
        sys, "argv", ["collect.py", "--run", RUN, "--stage", stage, "--lane", "auto", "--store", str(store)]
    )
    code = col.main()
    return code, capsys.readouterr().out


def test_settled_changes_go_to_the_automatic_lane_up_to_its_cap_and_the_rest_stay_cards(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=2)

    code, out = _build(monkeypatch, capsys, store, db)

    manifest = _read(store, "states", MANIFEST_FILE)
    assert code == 0
    assert [p["team_id_master"] for p in manifest["auto"].values()] == ["a", "b"]
    assert [p["team_id_master"] for p in manifest["cards"].values()] == ["c", "fix"]
    assert [c["id"] for c in _cards(store, "states")] == list(manifest["cards"])
    settled = {**manifest["cards"], **manifest["auto"]}
    assert sorted(settled[c]["team_id_master"] for c in manifest["sure"]) == ["a", "b", "c"]
    assert all(c.startswith(f"{manifest['run']}_") for c in manifest["auto"])
    assert _read(store, "states", pages.PAGE_MARKER)["auto"] == 2
    assert stage_progress(store, RUN, "states").auto_step.next_action == "collect the automatic lane"
    assert "the evidence already settles 3: 2 go to the automatic lane, the rest stay cards" in out
    assert f"collect.py --run {RUN} --stage states --lane auto, then apply_stage.py" in out


def test_the_configured_caps_keep_every_settled_change_a_card_until_the_lane_is_given_a_cap():
    assert pages.load_caps() == pages.Caps(cards=150, auto=0)


@pytest.mark.parametrize(
    "caps",
    [{"cards": 150}, {"cards": -1, "auto": 0}, {"cards": 150, "auto": True}, {"cards": "150", "auto": 0}, [150, 0]],
    ids=["missing", "negative", "a-bool", "a-string", "a-list"],
)
def test_caps_that_are_missing_or_not_whole_numbers_from_0_are_refused(tmp_path, caps):
    config = tmp_path / "team_cleanup.json"
    config.write_text(json.dumps({"page_caps": caps}), encoding="utf-8")

    with pytest.raises(ValueError, match="page_caps"):
        pages.load_caps(config)


def test_the_automatic_lane_collects_into_its_own_folder_as_the_owner_s_choices_do(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=2)
    _build(monkeypatch, capsys, store, db)
    built = _read(store, "states", MANIFEST_FILE)["run"]

    code, _ = _collect_auto(monkeypatch, capsys, store, "states")

    lane = stage_dir(store, RUN, "states") / "auto"
    vetted = json.loads((lane / "vetted.json").read_text(encoding="utf-8"))
    rows = json.loads((lane / col.DECISIONS_FILE).read_text(encoding="utf-8"))
    marker = json.loads((lane / "collected.json").read_text(encoding="utf-8"))
    assert code == 0
    assert vetted["rules"] == "authority" and [d["team_id"] for d in vetted["decisions"]] == ["a", "b"]
    assert [(r["team_id_master"], r["decision"], r["note"], r["source"]) for r in rows] == [
        ("a", "apply", None, f"auto:{built}"),
        ("b", "apply", None, f"auto:{built}"),
    ]
    assert marker["counts"] == {"apply": 2, "dont_apply": 0, "unsure": 0, "undecided": 0}
    assert marker["hashes"] == {
        "vetted.json": _sha(lane / "vetted.json"),
        "decisions.json": _sha(lane / "decisions.json"),
    }
    progress = stage_progress(store, RUN, "states")
    assert (progress.next_step.name, progress.auto_step.name) == ("collect", "apply")


def test_a_page_whose_automatic_lane_is_collected_is_not_rebuilt(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _build(monkeypatch, capsys, store, db)
    _collect_auto(monkeypatch, capsys, store, "states")

    with pytest.raises(SystemExit, match="the states automatic lane is collected from the page as built"):
        _build(monkeypatch, capsys, store, db)


def test_a_page_that_sent_nothing_to_the_automatic_lane_leaves_it_nothing_to_collect(tmp_path, monkeypatch, capsys):
    store = _built(tmp_path, monkeypatch, capsys)

    with pytest.raises(SystemExit, match="states has no automatic lane: no page has sent it a change"):
        _collect_auto(monkeypatch, capsys, store, "states")
    assert stage_progress(store, RUN, "states").auto_step is None


def test_a_page_json_that_cannot_be_read_keeps_the_stage_open(tmp_path, monkeypatch, capsys):
    """It may have sent changes to the automatic lane, which closing the run would leave unapplied."""
    store = _built(tmp_path, monkeypatch, capsys)
    (stage_dir(store, RUN, "states") / pages.PAGE_MARKER).write_text("{", encoding="utf-8")

    progress = stage_progress(store, RUN, "states")

    assert not progress.finished
    assert progress.auto_step.next_action.startswith("build the page again: its page.json cannot be read")


def test_a_collected_automatic_lane_stays_open_whatever_page_json_says(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _build(monkeypatch, capsys, store, db)
    _collect_auto(monkeypatch, capsys, store, "states")
    marker = _read(store, "states", pages.PAGE_MARKER)
    write_json(stage_dir(store, RUN, "states") / pages.PAGE_MARKER, {**marker, "auto": 0}, indent=1)

    assert stage_progress(store, RUN, "states").auto_step.name == "apply"


def test_the_lane_cap_picks_first_and_the_card_cap_takes_the_rest_with_followed_teams_first(
    tmp_path, monkeypatch, capsys
):
    store = tmp_path / "store"
    _reviewing(store)
    _states(store, [_decision(t, None, "NV") for t in ("a", "b", "c", "d")])
    db = _Db(
        teams=[_team(t, state=None) for t in ("a", "b", "c", "d")], watchlist_items=[{"id": 1, "team_id_master": "d"}]
    )
    monkeypatch.setattr(pages, "load_caps", lambda: pages.Caps(cards=1, auto=2))

    _build(monkeypatch, capsys, store, db)

    manifest = _read(store, "states", MANIFEST_FILE)
    assert [p["team_id_master"] for p in manifest["auto"].values()] == ["d", "a"]
    assert [p["team_id_master"] for p in manifest["cards"].values()] == ["b"]
    assert [p["team_id_master"] for p in manifest["overflow"]] == ["c"]


def test_a_lane_collected_while_the_page_is_rebuilt_keeps_the_page_it_was_collected_from(tmp_path, monkeypatch, capsys):
    """The collector holds the run's file lock; the build checks again under it before replacing anything."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=2)
    _build(monkeypatch, capsys, store, db)
    first = _read(store, "states", pages.PAGE_MARKER)["run"]
    reads = pages.fetch_teams

    def collect_meanwhile(sb, ids):
        col.collect(store, RUN, "states", None, "auto")
        return reads(sb, ids)

    monkeypatch.setattr(pages, "fetch_teams", collect_meanwhile)

    with pytest.raises(SystemExit, match="the states automatic lane is collected from the page as built"):
        _build(monkeypatch, capsys, store, db)
    assert _read(store, "states", pages.PAGE_MARKER)["run"] == first
    assert _read(store, "states", MANIFEST_FILE)["run"] == first


def test_a_build_while_an_apply_holds_the_run_exits_75(tmp_path, monkeypatch, capsys):
    store, db = _state_week(tmp_path)

    with _acquire_file_lock(run_dir(store, RUN) / APPLY_LOCK_FILE, timeout=0.0):
        with pytest.raises(SystemExit) as caught:
            _build(monkeypatch, capsys, store, db)

    assert caught.value.code == 75
    assert capsys.readouterr().err.startswith(f"Cannot build the states page for {RUN}: run {RUN} is in use")
    assert not (stage_dir(store, RUN, "states") / pages.PAGE_MARKER).exists()


def test_the_automatic_lane_waits_for_the_steps_it_shares_with_the_owner_s(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _build(monkeypatch, capsys, store, db)
    review = stage_dir(store, RUN, "states") / "review"
    review.mkdir()
    write_json(review / "batch1.json", [], indent=1)

    with pytest.raises(SystemExit, match="states is not ready for this: next, review the queued proposals"):
        _collect_auto(monkeypatch, capsys, store, "states")


LANE_RULE = "the owner's lane takes --decisions or --from-db, and the automatic lane neither"
BOTH = "argument --from-db: not allowed with argument --decisions"


@pytest.mark.parametrize(
    "argv, said",
    [
        (["--lane", "auto", "--decisions", "out"], LANE_RULE),
        (["--lane", "auto", "--from-db"], LANE_RULE),
        (["--lane", "auto", "--decisions", "out", "--from-db"], BOTH),
        (["--lane", "owner"], LANE_RULE),
        (["--lane", "owner", "--decisions", "out", "--from-db"], BOTH),
    ],
    ids=["auto-with-choices", "auto-from-db", "auto-with-both", "owner-without-choices", "owner-with-both"],
)
def test_only_the_owner_s_lane_reads_saved_choices_and_from_one_place(tmp_path, monkeypatch, capsys, argv, said):
    monkeypatch.setattr(sys, "argv", ["collect.py", "--run", RUN, "--stage", "states", *argv])

    with pytest.raises(SystemExit) as caught:
        col.main()
    assert caught.value.code == 2 and said in capsys.readouterr().err


# --- publishing the cards, and collecting the website's choices --------------------------------------


def _publish(monkeypatch, capsys, store, db, *flags, stage="states"):
    monkeypatch.setattr(pages, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["pages.py", "--run", RUN, "--stage", stage, "--store", str(store), *flags])
    code = pages.main()
    return code, capsys.readouterr().out


def _collect_db(monkeypatch, capsys, store, db, stage="states"):
    monkeypatch.setattr(col, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["collect.py", "--run", RUN, "--stage", stage, "--from-db", "--store", str(store)])
    code = col.main()
    return code, capsys.readouterr().out


def _decide(db, team_id, decision, note=None, at="2026-10-15T03:00:00+00:00"):
    """A choice as the website's route saves it, on the newest build: the decision, a note and the server's
    time."""
    row = [r for r in db.cards(lane="owner") if r["card"]["team"]["name"] == f"Team {team_id}"][-1]
    row.update(decision=decision, note=note, decided_at=at)
    return row["card_id"]


def test_a_published_build_writes_both_lanes_cards_in_one_insert(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=2)

    code, out = _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    manifest, built = _read(store, "states", MANIFEST_FILE), _read(store, "states", pages.PAGE_MARKER)
    owner, auto = db.cards(lane="owner"), db.cards(lane="auto")
    assert code == 0 and built["published"] is True
    assert db.executes.count(("team_cleanup_cards", "insert")) == 1
    assert [r["card_id"] for r in owner] == list(manifest["cards"])
    assert [r["card_id"] for r in auto] == list(manifest["auto"])
    assert {(r["run_id"], r["stage"], r["page_run"]) for r in owner + auto} == {(RUN, "states", manifest["run"])}
    assert [(r["position"], r["decision"], r["decided_at"]) for r in owner] == [(1, None, None), (2, None, None)]
    assert [(r["position"], r["decision"], r["decided_at"]) for r in auto] == [
        (1, "apply", built["built_at"]),
        (2, "apply", built["built_at"]),
    ]
    assert owner[0]["card"] == _cards(store, "states")[0]
    assert [r["card"]["sure"] for r in owner + auto] == [
        "a blank state filled from its club, which nothing disputes",
        None,
        "a blank state filled from its club, which nothing disputes",
        "a blank state filled from its club, which nothing disputes",
    ]
    assert "published its 4 cards, both lanes, to team_cleanup_cards" in out


def _page_files(store):
    folder = stage_dir(store, RUN, "states")
    return {name: (folder / name).read_bytes() for name in (pages.PAGE_FILE, MANIFEST_FILE, pages.PAGE_MARKER)}


@pytest.mark.parametrize("flags", [["--publish"], ["--publish", "--execute", "--dry-run"]], ids=["publish", "dry-run"])
def test_a_publish_s_dry_run_writes_no_card_and_no_file(tmp_path, monkeypatch, capsys, flags):
    store, db = _sure_week(tmp_path, monkeypatch, auto=2)

    code, out = _publish(monkeypatch, capsys, store, db, *flags)

    folder = stage_dir(store, RUN, "states")
    assert code == 0 and db.tables["team_cleanup_cards"] == []
    assert ("team_cleanup_cards", "insert") not in db.executes
    assert [p.name for p in folder.iterdir() if p.name.startswith("page")] == []
    assert "DRY RUN -- would build page run " in out and "publish its 4 cards to" in out


def test_a_build_that_does_not_publish_says_so(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)

    _publish(monkeypatch, capsys, store, db)

    assert _read(store, "states", pages.PAGE_MARKER)["published"] is False and db.tables["team_cleanup_cards"] == []


def test_a_page_with_published_cards_is_built_again_only_by_publishing(tmp_path, monkeypatch, capsys):
    """The website shows the newest build published, so a build that does not publish would leave it showing an
    older page than the one on disk."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    before = _page_files(store)

    with pytest.raises(SystemExit, match="the page is published, so a new build of it is published too"):
        _publish(monkeypatch, capsys, store, db)
    assert _page_files(store) == before


def _builds_no_card(monkeypatch):
    """Every proposal left off, as when the evidence now answers all of them."""
    sort_out = pages.sort_out

    def nothing_shown(*args):
        shown, left_out = sort_out(*args)
        return [], left_out + shown

    monkeypatch.setattr(pages, "sort_out", nothing_shown)


def test_a_published_page_is_not_replaced_by_a_build_with_no_card(tmp_path, monkeypatch, capsys):
    """A build with no card publishes no row, so the website would go on showing the published page."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    first, before = _read(store, "states", pages.PAGE_MARKER)["run"], _page_files(store)
    _builds_no_card(monkeypatch)

    with pytest.raises(SystemExit) as caught:
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    assert str(caught.value) == (
        f"Cannot build the states page for {RUN}: the new build has no cards, so publishing it would leave the "
        f"website showing the published page {first}; the page stays as it is"
    )
    assert _page_files(store) == before and db.executes.count(INSERT) == 1


def test_a_page_with_no_card_publishes_no_row_and_collects_to_nothing(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _builds_no_card(monkeypatch)

    code, _ = _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    assert code == 0 and _read(store, "states", pages.PAGE_MARKER)["published"] is True
    assert INSERT not in db.executes and db.tables["team_cleanup_cards"] == []
    code, out = _collect_db(monkeypatch, capsys, store, db)
    assert code == 0 and "nothing to apply" in out


def test_execute_without_publish_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pages.py", "--run", RUN, "--stage", "states", "--execute"])

    with pytest.raises(SystemExit) as caught:
        pages.main()
    assert caught.value.code == 2 and "--execute writes only the cards --publish names" in capsys.readouterr().err


def test_a_refused_publish_leaves_no_page_behind(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=2)
    db.broken[INSERT] = _refusal("42501", "permission denied for table team_cleanup_cards")

    with pytest.raises(SystemExit) as caught:
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    assert str(caught.value) == (
        f"Cannot build the states page for {RUN}: permission denied for table team_cleanup_cards; only the "
        "service-role key may do this"
    )
    assert [p.name for p in stage_dir(store, RUN, "states").iterdir() if p.name.startswith("page")] == []


def test_a_refused_publish_leaves_the_published_page_as_it_was(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    before = _page_files(store)
    db.broken[INSERT] = _refusal("23514", "new row violates a check constraint")

    with pytest.raises(SystemExit, match="new row violates a check constraint"):
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    assert _page_files(store) == before


def test_a_lost_answer_hands_back_the_same_publish_and_leaves_the_page_on_disk_as_it_was(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    db.lost["team_cleanup_cards"] = httpx.ReadTimeout("timed out")

    with pytest.raises(SystemExit) as caught:
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    assert str(caught.value).startswith(f"Cannot build the states page for {RUN}: the database's answer was lost")
    assert str(caught.value).endswith(shlex.join(["--store", str(store), "--publish", "--execute"]))
    assert [p.name for p in stage_dir(store, RUN, "states").iterdir() if p.name.startswith("page")] == []
    assert len(db.tables["team_cleanup_cards"]) == 4


def test_a_published_page_the_owner_has_begun_deciding_is_not_built_again(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    first = _read(store, "states", pages.PAGE_MARKER)["run"]
    _decide(db, "c", "dont_apply")

    with pytest.raises(SystemExit, match=f"the owner has decided cards of the published page {first}"):
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    assert _read(store, "states", pages.PAGE_MARKER)["run"] == first
    assert {r["page_run"] for r in db.tables["team_cleanup_cards"]} == {first}


def test_a_decision_saved_while_the_build_reads_its_evidence_stops_the_new_build(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    first = _read(store, "states", pages.PAGE_MARKER)["run"]
    reads = pages.fetch_teams

    def decided_meanwhile(sb, ids):
        _decide(db, "c", "apply")
        return reads(sb, ids)

    monkeypatch.setattr(pages, "fetch_teams", decided_meanwhile)

    with pytest.raises(SystemExit, match=f"the owner has decided cards of the published page {first}"):
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    assert {r["page_run"] for r in db.tables["team_cleanup_cards"]} == {first}


def test_a_decision_on_a_build_the_page_on_disk_no_longer_names_still_stops_a_new_build(tmp_path, monkeypatch, capsys):
    """A build whose insert landed but whose answer was lost leaves its cards newest on the website."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    db.lost["team_cleanup_cards"] = httpx.ReadTimeout("timed out")
    with pytest.raises(SystemExit):
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    db.lost.clear()
    orphan = db.tables["team_cleanup_cards"][0]["page_run"]
    _decide(db, "c", "apply")

    with pytest.raises(SystemExit, match=f"the owner has decided cards of the published page {orphan}"):
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")


def test_a_published_page_whose_only_decided_cards_are_the_automatic_lane_s_is_built_again(
    tmp_path, monkeypatch, capsys
):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    first = _read(store, "states", pages.PAGE_MARKER)["run"]

    code, _ = _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    assert code == 0 and _read(store, "states", pages.PAGE_MARKER)["run"] != first


def test_choices_saved_on_the_website_are_collected_with_the_time_the_database_saved_them(
    tmp_path, monkeypatch, capsys
):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    run = _read(store, "states", MANIFEST_FILE)["run"]
    _decide(db, "b", "apply", "fine", at="2026-10-15T03:00:00+00:00")
    _decide(db, "fix", "dont_apply", at="2026-10-15T04:00:00+00:00")

    code, _ = _collect_db(monkeypatch, capsys, store, db)

    folder = stage_dir(store, RUN, "states")
    rows = json.loads((folder / col.DECISIONS_FILE).read_text(encoding="utf-8"))
    assert code == 0
    assert [(r["team_id_master"], r["decision"], r["note"], r["decided_at"], r["source"]) for r in rows] == [
        ("b", "apply", "fine", "2026-10-15T03:00:00+00:00", f"page:{run}"),
        ("fix", "dont_apply", None, "2026-10-15T04:00:00+00:00", f"page:{run}"),
    ]
    vetted = json.loads((folder / "vetted.json").read_text(encoding="utf-8"))
    assert [d["team_id"] for d in vetted["decisions"]] == ["b"]
    marker = json.loads((folder / "collected.json").read_text(encoding="utf-8"))
    assert marker["run"] == run and marker["counts"] == {"apply": 1, "dont_apply": 1, "unsure": 0, "undecided": 1}


def test_a_published_page_left_undecided_collects_to_nothing(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    code, out = _collect_db(monkeypatch, capsys, store, db)

    folder = stage_dir(store, RUN, "states")
    assert code == 0 and "nothing to apply" in out and not (folder / "vetted.json").exists()
    assert json.loads((folder / "collected.json").read_text(encoding="utf-8"))["counts"]["undecided"] == 3


def test_a_page_published_again_is_collected_from_its_newest_build_alone(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    run = _read(store, "states", MANIFEST_FILE)["run"]
    _decide(db, "b", "apply")
    newest = next(r for r in db.cards(lane="owner") if r["decision"])
    assert len({r["page_run"] for r in db.tables["team_cleanup_cards"]}) == 2 and newest["page_run"] == run

    code, _ = _collect_db(monkeypatch, capsys, store, db)

    rows = json.loads((stage_dir(store, RUN, "states") / col.DECISIONS_FILE).read_text(encoding="utf-8"))
    assert code == 0 and [(r["team_id_master"], r["source"]) for r in rows] == [("b", f"page:{run}")]


def _page_runs(monkeypatch, *runs):
    """The page runs the next builds take, in order, as new_page_run stamps them when a build starts."""
    names = iter(runs)
    monkeypatch.setattr(pages, "new_page_run", lambda: next(names))


@pytest.mark.parametrize(
    "flags, first, second",
    [
        (["--publish", "--execute"], "20261015T030010Z-a1b2c3", "20261015T030011Z-a1b2c3"),
        (["--publish", "--execute"], "20261015T030010Z-ffffff", "20261015T030010Z-000000"),
        ([], "20261015T030010Z-a1b2c3", "20261015T030011Z-a1b2c3"),
    ],
    ids=["a-second-later", "same-second", "over-an-unpublished-page"],
)
def test_a_newer_published_build_with_no_page_on_disk_is_refused(tmp_path, monkeypatch, capsys, flags, first, second):
    """The website shows the newest build, so the owner may be deciding cards the page on disk lacks. Two
    page runs stamped in one second sort by their random suffix, so only the table says which is newer."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _page_runs(monkeypatch, first, second)
    _publish(monkeypatch, capsys, store, db, *flags)
    db.lost["team_cleanup_cards"] = httpx.ReadTimeout("timed out")
    with pytest.raises(SystemExit):
        _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    with pytest.raises(SystemExit) as caught:
        _collect_db(monkeypatch, capsys, store, db)

    assert str(caught.value).endswith(
        f"page run {second} of this page is published, but the page on disk is the earlier {first}: the later build's "
        "files were lost. Build and publish the page again if none of its cards is decided; decided ones stay in "
        "team_cleanup_cards and need recovering by hand"
    )


def test_a_build_stamped_earlier_but_published_last_is_the_page_collected(tmp_path, monkeypatch, capsys):
    """Two builds overlapping: the one that started first waited for the lock and published second, so its
    page is on disk and is the newest."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _page_runs(monkeypatch, "20261015T030020Z-a1b2c3", "20261015T030010Z-a1b2c3")
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    _decide(db, "b", "apply")

    code, _ = _collect_db(monkeypatch, capsys, store, db)

    rows = json.loads((stage_dir(store, RUN, "states") / col.DECISIONS_FILE).read_text(encoding="utf-8"))
    assert code == 0 and [(r["team_id_master"], r["source"]) for r in rows] == [("b", "page:20261015T030010Z-a1b2c3")]


def test_a_choice_saved_on_the_page_a_rebuild_replaced_stops_the_collect(tmp_path, monkeypatch, capsys):
    """The owner saved it on the page then shown after the rebuild checked for decided cards, so the build
    published without it."""
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    checks, saved = pages.check_undecided, []

    def decided_after_the_check(*args, **kwargs):
        checks(*args, **kwargs)
        saved.append(_decide(db, "c", "apply"))

    monkeypatch.setattr(pages, "check_undecided", decided_after_the_check)
    code, _ = _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    run = _read(store, "states", MANIFEST_FILE)["run"]
    assert code == 0 and not saved[0].startswith(run)

    with pytest.raises(SystemExit) as caught:
        _collect_db(monkeypatch, capsys, store, db)

    assert str(caught.value).endswith(
        f"1 choice(s) were saved on an earlier build of this page, which page run {run} replaced without them: "
        f"{saved[0]}. Make them again on the page shown now, then clear their decision and decided_at in "
        "team_cleanup_cards, and collect again"
    )


def test_a_card_read_the_database_refuses_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    db.broken["team_cleanup_cards"] = _refusal("42501", "permission denied for table team_cleanup_cards")

    with pytest.raises(SystemExit) as caught:
        _collect_db(monkeypatch, capsys, store, db)

    assert str(caught.value) == (
        f"Cannot collect the states choices for {RUN}: permission denied for table team_cleanup_cards; only the "
        "service-role key may do this"
    )


def test_the_automatic_lane_s_cards_carry_their_evidence(tmp_path, monkeypatch, capsys):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    db.tables["games"] = [_game(1, "a", "x", "2026-09-05"), _game(2, "y", "a", "2026-09-12")]

    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")

    team = db.cards(lane="auto")[0]["card"]["team"]
    assert (team["name"], team["games"], team["first"], team["last"]) == ("Team a", 2, "2026-09-05", "2026-09-12")


def _unpublished(db, card):
    db.tables["team_cleanup_cards"].remove(card)


def _stray(db, card):
    db.tables["team_cleanup_cards"].append({**card, "card_id": card["page_run"] + "_ffffffffffffffff"})


def _relaned(db, card):
    card["lane"] = "auto" if card["lane"] == "owner" else "owner"


def _untimed(db, card):
    card["decision"] = "apply"


def _undecided_with_a_time(db, card):
    card["decided_at"] = "2026-10-15T03:00:00+00:00"


@pytest.mark.parametrize(
    "spoil, message",
    [
        (_unpublished, "1 card(s) of page run {run} are not in team_cleanup_cards"),
        (_stray, "team_cleanup_cards holds card(s) page run {run} never made"),
        (_relaned, "is in the auto lane; page run {run} built it in owner"),
        (_untimed, "holds a decision without the time it was saved, or a time without one"),
        (_undecided_with_a_time, "holds a decision without the time it was saved, or a time without one"),
    ],
    ids=["missing", "stray", "other-lane", "decision-without-time", "time-without-decision"],
)
def test_published_cards_that_disagree_with_the_build_are_refused(tmp_path, monkeypatch, capsys, spoil, message):
    store, db = _sure_week(tmp_path, monkeypatch, auto=1)
    _publish(monkeypatch, capsys, store, db, "--publish", "--execute")
    run = _read(store, "states", MANIFEST_FILE)["run"]
    spoil(db, db.cards(lane="owner")[0])

    with pytest.raises(SystemExit) as caught:
        _collect_db(monkeypatch, capsys, store, db)

    assert message.format(run=run) in str(caught.value)
    assert not (stage_dir(store, RUN, "states") / "collected.json").exists()


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
    assert "await save(x.id, {decision});" in template
    assert 'decideOpen(groups.get(c.group).cards, "apply")' in template
