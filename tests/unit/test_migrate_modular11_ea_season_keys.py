"""Re-keying the EA rows already in production: raw uid -> uid:season, once, logged, reversible."""

import json

import pytest
from postgrest.exceptions import APIError

from scripts import migrate_modular11_ea_season_keys as migrate

PROVIDER = "prov-ea"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Builds lazily and records only at execute(); an update touches only rows matching every filter."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.filters, self.payload, self.window = "select", [], None, None

    def select(self, *_cols):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        rows = [r for r in self.db.rows[self.table] if all(r.get(c) == v for c, v in self.filters)]
        if self.op == "update":
            for row in rows:
                clash = [
                    r
                    for r in self.db.rows[self.table]
                    if r is not row
                    and r["provider_id"] == row["provider_id"]
                    and r["provider_team_id"] == self.payload["provider_team_id"]
                ]
                if clash:
                    raise APIError({"code": "23505", "message": "duplicate key value violates unique constraint"})
            self.db.updates.append((self.table, list(self.filters), dict(self.payload)))
            for row in rows:
                row.update(self.payload)
            return _Result([dict(r) for r in rows])
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        return _Result([dict(r) for r in rows])


class _Db:
    def __init__(self, aliases=(), teams=()):
        self.rows = {"team_alias_map": [dict(a) for a in aliases], "teams": [dict(t) for t in teams]}
        self.updates = []

    def table(self, name):
        return _Query(self, name)


def _db():
    return _Db(
        aliases=[
            {"id": 1, "provider_id": PROVIDER, "provider_team_id": "3432", "team_id_master": "CFA"},
            {"id": 2, "provider_id": "prov-gotsport", "provider_team_id": "3432", "team_id_master": "GS"},
        ],
        teams=[
            {"team_id_master": "NEW", "provider_id": PROVIDER, "provider_team_id": "7155"},
            {"team_id_master": "GS", "provider_id": "prov-gotsport", "provider_team_id": "7155"},
        ],
    )


def _ids(db, table):
    return [(r["provider_id"], r["provider_team_id"]) for r in db.rows[table]]


def test_execute_rekeys_only_this_providers_rows(tmp_path):
    db = _db()
    counts = migrate.migrate(db, PROVIDER, 2026, tmp_path / "log.jsonl", execute=True)
    assert counts == {"aliases": 1, "teams": 1, "already_keyed": 0, "collisions": 0}
    assert _ids(db, "team_alias_map") == [(PROVIDER, "3432:2026"), ("prov-gotsport", "3432")]
    assert _ids(db, "teams") == [(PROVIDER, "7155:2026"), ("prov-gotsport", "7155")]
    log = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log == [
        {"table": "team_alias_map", "id": 1, "old": "3432", "new": "3432:2026"},
        {"table": "teams", "team_id_master": "NEW", "old": "7155", "new": "7155:2026"},
    ]


def test_second_run_changes_nothing(tmp_path):
    db = _db()
    migrate.migrate(db, PROVIDER, 2026, tmp_path / "first.jsonl", execute=True)
    db.updates.clear()
    counts = migrate.migrate(db, PROVIDER, 2026, tmp_path / "second.jsonl", execute=True)
    assert counts == {"aliases": 0, "teams": 0, "already_keyed": 2, "collisions": 0}
    assert db.updates == []
    assert _ids(db, "team_alias_map")[0] == (PROVIDER, "3432:2026")


def test_update_is_guarded_on_the_value_read(tmp_path):
    db = _db()
    migrate.migrate(db, PROVIDER, 2026, tmp_path / "log.jsonl", execute=True)
    assert [f for _, f, _ in db.updates] == [
        [("id", 1), ("provider_team_id", "3432")],
        [("team_id_master", "NEW"), ("provider_team_id", "7155")],
    ]


def test_dry_run_counts_but_writes_nothing(tmp_path):
    db = _db()
    counts = migrate.migrate(db, PROVIDER, 2026, tmp_path / "log.jsonl", execute=False)
    assert counts == {"aliases": 1, "teams": 1, "already_keyed": 0, "collisions": 0}
    assert db.updates == [] and not (tmp_path / "log.jsonl").exists()


def test_undo_restores_raw_ids(tmp_path):
    db = _db()
    log = tmp_path / "log.jsonl"
    migrate.migrate(db, PROVIDER, 2026, log, execute=True)
    assert migrate.undo(db, log) == {"restored": 2, "skipped": 0}
    assert _ids(db, "team_alias_map") == [(PROVIDER, "3432"), ("prov-gotsport", "3432")]
    assert _ids(db, "teams") == [(PROVIDER, "7155"), ("prov-gotsport", "7155")]


def test_undo_skips_a_row_moved_since(tmp_path):
    db = _db()
    log = tmp_path / "log.jsonl"
    migrate.migrate(db, PROVIDER, 2026, log, execute=True)
    db.rows["teams"][0]["provider_team_id"] = "7155:2027"
    assert migrate.undo(db, log) == {"restored": 1, "skipped": 1}
    assert db.rows["teams"][0]["provider_team_id"] == "7155:2027"


def _collided():
    db = _db()
    db.rows["team_alias_map"].append({"id": 3, "provider_id": PROVIDER, "provider_team_id": "3432:2026", "team_id_master": "DUP"})
    return db


def test_a_keyed_row_already_present_is_a_collision_not_a_crash(tmp_path):
    db = _collided()
    counts = migrate.migrate(db, PROVIDER, 2026, tmp_path / "log.jsonl", execute=True)
    assert counts == {"aliases": 0, "teams": 1, "already_keyed": 1, "collisions": 1}
    assert db.rows["team_alias_map"][0]["provider_team_id"] == "3432"


def test_dry_run_reports_the_collision(tmp_path):
    counts = migrate.migrate(_collided(), PROVIDER, 2026, tmp_path / "log.jsonl", execute=False)
    assert counts["collisions"] == 1


def test_refuse_unmigrated_names_the_command():
    with pytest.raises(SystemExit, match="migrate_modular11_ea_season_keys.py"):
        migrate.refuse_unmigrated(_db(), PROVIDER)
    keyed = _Db(aliases=[{"id": 1, "provider_id": PROVIDER, "provider_team_id": "3432:2026", "team_id_master": "C"}])
    migrate.refuse_unmigrated(keyed, PROVIDER)
