"""Discovery never creates a team whose GotSport lookup failed, and creates a coed one excluded.

This drives ``main`` itself, the way the weekly workflow runs it: the decision to create
lives in main's loop, after the lookup, so a test of the metadata builder alone would hand
over exactly the record a failed lookup never returned. Run 42919277448 (2026-11-10)
created 992 teams whose lookups GotSport had blocked, each named ``unknown_<id>`` and
carrying its opponent's cohort, and 159 that GotSport files as Coed, every one of them
queued for a scrape and ranked.
"""

import csv
import sys
from types import SimpleNamespace

import pytest
from requests.structures import CaseInsensitiveDict

from scripts import discover_teams_from_opponents as discover
from scripts import export_unknown_opponents as export
from src.utils.gotsport_team_details import TeamDetailsPacer

PROVIDER_ID = "gotsport-uuid"
PRIMARY_KEYS = {"team_ranking_exclusions": "team_id_master"}


class _Query:
    """Applies its filters, returns only the selected columns, fills ``count`` only when it was
    asked for, and records each write at execute(), where requests are sent."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._filters = []
        self._columns = None
        self._count = None
        self._head = False
        self._write = None

    def select(self, columns="*", count=None, head=False):
        self._columns = None if columns.strip() == "*" else [c.strip() for c in columns.split(",")]
        self._count = count
        self._head = head
        return self

    def eq(self, column, value):
        self._filters.append(lambda r, c=column, v=value: r.get(c) == v)
        return self

    def is_(self, column, value):
        if value != "null":
            raise AssertionError(f"is_ value this double does not model: {value}")
        self._filters.append(lambda r, c=column: r.get(c) is None)
        return self

    def limit(self, _count):
        return self

    def insert(self, record):
        self._write = ("insert", record)
        return self

    def upsert(self, record, on_conflict=None):
        self._write = ("upsert", record)
        return self

    def update(self, values):
        self._write = ("update", values)
        return self

    def __getattr__(self, name):
        raise AssertionError(f"_Query.{name} is not modelled; model it or the test proves nothing")

    def execute(self):
        rows = self._db.tables[self._table]
        matched = [r for r in rows if all(f(r) for f in self._filters)]
        if self._write is None:
            data = [] if self._head else matched
            if self._columns:
                data = [{c: r.get(c) for c in self._columns} for r in data]
            return SimpleNamespace(data=data, count=len(matched) if self._count else None)
        kind, payload = self._write
        if kind == "insert" and self._table in self._db.failing_inserts:
            raise RuntimeError(f"insert into {self._table} refused")
        key = PRIMARY_KEYS.get(self._table)
        if kind == "insert" and key and any(r.get(key) == payload.get(key) for r in rows):
            raise RuntimeError(f'duplicate key value violates unique constraint "{self._table}_pkey"')
        self._db.writes.append((self._table, kind, payload))
        if kind == "update":
            for r in matched:
                r.update(payload)
            return SimpleNamespace(data=matched, count=None)
        rows.append(dict(payload))
        if kind == "insert" and self._table in self._db.lost_replies:
            self._db.lost_replies.discard(self._table)
            raise RuntimeError("RemoteProtocolError: Server disconnected without sending a response")
        return SimpleNamespace(data=[dict(payload)], count=None)


class _Rpc:
    def __init__(self, db, name, params):
        self._db = db
        self._call = (name, params)

    def execute(self):
        self._db.writes.append(("rpc", *self._call))
        return SimpleNamespace(data=None)


class _DB:
    """``failing_inserts`` refuses a table's insert outright; ``lost_replies`` commits the next one
    and then drops the connection before answering."""

    def __init__(self, games, failing_inserts=(), lost_replies=(), aliases=()):
        self.tables = {
            "providers": [{"id": PROVIDER_ID, "code": "gotsport", "name": "GotSport"}],
            "teams": [],
            "team_alias_map": [dict(a) for a in aliases],
            "team_ranking_exclusions": [],
            "games": games,
        }
        self.failing_inserts = set(failing_inserts)
        self.lost_replies = set(lost_replies)
        self.writes = []

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"unexpected table {name!r}")
        return _Query(self, name)

    def rpc(self, name, params):
        return _Rpc(self, name, params)

    def written(self, table, kind):
        return [payload for t, k, payload in self.writes if (t, k) == (table, kind)]

    def created(self):
        return {payload["provider_team_id"]: payload for payload in self.written("teams", "insert")}

    def enqueued(self):
        return [params["p_provider_team_id"] for params in self.written("rpc", "enqueue_scrape_request")]


class _Response:
    content = b"{}"

    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} for url")

    def json(self):
        return self._payload


class _GotSport:
    """team_details by id; an id it does not list answers as a CloudFront block."""

    def __init__(self, records):
        self._records = records
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params["team_id"])
        record = self._records.get(params["team_id"])
        if record is None:
            return _Response({}, 403, {"Server": "CloudFront"})
        if record == 404:
            return _Response({"message": "Can not find team"}, 404)
        return _Response(record)


def _record(name, gender, age="U12"):
    return {
        "name": name,
        "club_name": "Rangers FC",
        "team_association": "WA",
        "display_gender": gender,
        "display_age_group": age,
    }


def _no_match(pid, name_used="", age_used="u11", gender_used="Male"):
    """A match-report row; the *_used columns hold the opponent's cohort when nothing answered."""
    return {
        "provider_code": "gotsport",
        "provider_id": PROVIDER_ID,
        "unknown_provider_team_id": pid,
        "missing_side": "away",
        "games_count": "1",
        "unknown_team_name_used": name_used or f"unknown_{pid}",
        "unknown_club_name_used": "",
        "unknown_age_group_used": age_used,
        "unknown_gender_used": gender_used,
        "unknown_provider_gender": "",
        "unknown_state_used": "",
        "action": "no_match",
    }


def _export_row(pid, name, age, gender, club="Rangers FC", state="WA"):
    return {
        "provider_code": "gotsport",
        "unknown_provider_team_id": pid,
        "unknown_team_name": name,
        "unknown_club_name": club,
        "unknown_state": state,
        "unknown_age": age,
        "unknown_gender": gender,
    }


def _game(pid):
    return {
        "id": f"game-{pid}",
        "provider_id": PROVIDER_ID,
        "home_provider_id": "100",
        "away_provider_id": pid,
        "home_team_master_id": "known",
        "away_team_master_id": None,
    }


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def run_discovery(tmp_path, monkeypatch):
    def run(report_rows, gotsport, export_rows=None, execute=True, failing_inserts=(), lost_replies=(), aliases=()):
        report = tmp_path / "match_report.csv"
        _write_csv(report, report_rows)
        games = [_game(r["unknown_provider_team_id"]) for r in report_rows]
        db = _DB(games, failing_inserts, lost_replies, aliases)
        monkeypatch.setattr(discover, "load_env", lambda: None)
        monkeypatch.setattr(discover, "get_supabase", lambda: db)
        monkeypatch.setattr(discover.time, "sleep", lambda _s: None)

        class _Resolver(discover.GotSportResolver):
            def __init__(self):
                super().__init__(pacer=TeamDetailsPacer(cooldown_sec=0, sleep=lambda _s: None))
                self.session = gotsport

        monkeypatch.setattr(discover, "GotSportResolver", _Resolver)
        out = tmp_path / "discovery.csv"
        argv = ["discover", "--match-report", str(report), "--output", str(out)]
        if execute:
            argv.append("--execute")
        if export_rows:
            export_csv = tmp_path / "export_aggregate.csv"
            _write_csv(export_csv, export_rows)
            argv += ["--export-aggregate", str(export_csv)]
        monkeypatch.setattr(sys, "argv", argv)
        discover.main()
        with out.open(encoding="utf-8") as f:
            actions = {r["unknown_provider_team_id"]: r["action"] for r in csv.DictReader(f)}
        return db, actions

    return run


def test_a_team_with_its_own_record_is_created_queued_and_linked(run_discovery):
    """The control: the path can create, so the guards below are the guards and not the double."""
    db, actions = run_discovery(
        report_rows=[_no_match("500001")],
        gotsport=_GotSport({"500001": _record("Rangers 2015 Boys Red", "Male")}),
    )

    assert actions == {"500001": "created"}
    created = db.created()["500001"]
    assert (created["team_name"], created["age_group"], created["state_code"]) == ("Rangers 2015 Boys Red", "u12", "WA")
    assert db.enqueued() == ["500001"]
    assert db.written("team_ranking_exclusions", "insert") == []
    assert db.tables["games"][0]["away_team_master_id"] == created["team_id_master"]


def test_a_coed_team_is_created_excluded_and_never_queued(run_discovery):
    """Linking its games is what keeps it out of next week's export, and the exclusion keeps those
    games out of every ranking. Queued, its scrape would bring in its coed opponents."""
    db, actions = run_discovery(
        report_rows=[_no_match("500002", name_used="Rangers 2015 Red")],
        gotsport=_GotSport({"500002": _record("Rangers 2015 Red", "Coed")}),
    )

    assert actions == {"500002": "created_coed_excluded"}
    team_id = db.created()["500002"]["team_id_master"]
    assert db.written("team_ranking_exclusions", "insert") == [
        {
            "team_id_master": team_id,
            "reason": "Coed team (GotSport files it as Coed); PitchRank does not rank coed teams",
            "evidence": {"provider": "gotsport", "provider_team_id": "500002", "gotsport_gender": "Coed"},
            "excluded_by": "discover_teams_from_opponents",
        }
    ]
    assert db.enqueued() == []
    assert db.tables["games"][0]["away_team_master_id"] == team_id


def test_a_coed_team_whose_exclusion_fails_is_not_created_at_all(run_discovery):
    """An approved alias left behind would let every later import link the team's games, and they
    would count in the next ranking run; next week's run tries again instead."""
    db, actions = run_discovery(
        report_rows=[_no_match("500009", name_used="Rangers 2015 Red")],
        gotsport=_GotSport({"500009": _record("Rangers 2015 Red", "Coed")}),
        failing_inserts={"team_ranking_exclusions"},
    )

    assert actions == {"500009": "error"}
    assert db.writes == []


def test_an_exclusion_whose_reply_was_lost_counts_as_written(run_discovery):
    """The retry finds its own committed row and is refused as a duplicate."""
    db, actions = run_discovery(
        report_rows=[_no_match("500013", name_used="Rangers 2015 Red")],
        gotsport=_GotSport({"500013": _record("Rangers 2015 Red", "Coed")}),
        lost_replies={"team_ranking_exclusions"},
    )

    assert actions == {"500013": "created_coed_excluded"}
    team_id = db.created()["500013"]["team_id_master"]
    assert [row["team_id_master"] for row in db.tables["team_ranking_exclusions"]] == [team_id]
    assert db.tables["games"][0]["away_team_master_id"] == team_id


def test_a_coed_record_already_aliased_is_left_to_its_team(run_discovery):
    """Only a team this run creates is excluded; an existing alias points at a team that may be
    ranked on its own record."""
    db, actions = run_discovery(
        report_rows=[_no_match("500014", name_used="Rangers 2015 Red")],
        gotsport=_GotSport({"500014": _record("Rangers 2015 Red", "Coed")}),
        aliases=[{"provider_id": PROVIDER_ID, "provider_team_id": "500014", "team_id_master": "ranked-team"}],
    )

    assert actions == {"500014": "exists_alias"}
    assert db.writes == []


def test_a_dry_run_reports_a_coed_team_without_writing(run_discovery):
    db, actions = run_discovery(
        report_rows=[_no_match("500010", name_used="Rangers 2015 Red")],
        gotsport=_GotSport({"500010": _record("Rangers 2015 Red", "Coed")}),
        execute=False,
    )

    assert actions == {"500010": "would_create_coed_excluded"}
    assert db.writes == []


def test_a_team_whose_lookup_is_blocked_is_left_for_next_week(run_discovery):
    db, actions = run_discovery(report_rows=[_no_match("500003")], gotsport=_GotSport({}))

    assert actions == {"500003": "skipped_lookup_failed"}
    assert db.writes == []


def test_every_team_after_the_lookups_stop_is_left_for_next_week(run_discovery):
    """Once a block outlasts the wait, later lookups are refused without a request, which is the
    path every blocked team but the first takes."""
    gotsport = _GotSport({})
    db, actions = run_discovery(report_rows=[_no_match("500011"), _no_match("500012")], gotsport=gotsport)

    assert actions == {"500011": "skipped_lookup_failed", "500012": "skipped_lookup_failed"}
    assert gotsport.calls == ["500011", "500011"]
    assert db.writes == []


def test_a_team_gotsport_has_no_record_of_is_still_created_from_the_report(run_discovery):
    """A 404 is GotSport answering, unlike a block, so the team is created from the report's columns."""
    db, actions = run_discovery(
        report_rows=[_no_match("500004", name_used="Rangers 2015 Boys Red")],
        gotsport=_GotSport({"500004": 404}),
    )

    assert actions == {"500004": "created"}
    assert set(db.created()) == {"500004"}


def test_the_exports_lookups_are_reused_rather_than_repeated(run_discovery):
    """The report row carries the opponent's cohort and no club, so each field the created team
    gets from the export is visible, and a dropped one falls back to the opponent's."""
    gotsport = _GotSport({"500006": _record("Rangers 2014 Boys Blue", "Male", age="U13")})
    db, actions = run_discovery(
        report_rows=[_no_match("500005"), _no_match("500006"), _no_match("500007")],
        gotsport=gotsport,
        export_rows=[
            _export_row("500005", "Rangers 2015 Girls Red", age="U12", gender="Female"),
            _export_row("500007", "Rangers 2016 Red", age="U11", gender="Coed"),
        ],
    )

    assert gotsport.calls == ["500006"]
    assert actions == {"500005": "created", "500006": "created", "500007": "created_coed_excluded"}
    seeded = db.created()["500005"]
    assert (seeded["team_name"], seeded["club_name"], seeded["age_group"], seeded["gender"], seeded["state_code"]) == (
        "Rangers 2015 Girls Red",
        "Rangers FC",
        "u12",
        "Female",
        "WA",
    )


def test_an_export_row_it_could_not_read_is_looked_up_again(run_discovery):
    gotsport = _GotSport({"500008": _record("Rangers 2015 Boys Red", "Male")})
    db, actions = run_discovery(
        report_rows=[_no_match("500008")],
        gotsport=gotsport,
        export_rows=[_export_row("500008", "", age="", gender="", club="", state="")],
    )

    assert gotsport.calls == ["500008"]
    assert actions == {"500008": "created"}


def test_the_columns_discovery_reuses_are_ones_the_export_writes():
    """A rename on either side would seed blank fields, and the opponent's cohort fills them."""
    assert set(discover.EXPORT_COLUMNS.values()) <= set(export.AGGREGATE_FIELDNAMES)
