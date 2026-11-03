"""Tests for the weekly user-interest enqueue's handling of a refused request.

The Supabase double evaluates its filters, records at execute(), and is strict
where production or the repo's query rules are: unknown columns raise, in_()
refuses more than 100 values, a page refuses to run without order(), an update
needs a filter, and RPC params go through json.dumps before the call runs.
"""

import json
import logging
import os
import sys

from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import enqueue_user_interest_teams as uit  # noqa: E402

GOTSPORT_ID = "prov-gotsport"

TABLE_COLUMNS = {
    "watchlist_items": ("id", "team_id_master"),
    "report_card_leads": ("id", "team_id"),
    "teams": ("team_id_master", "team_name", "provider_id", "provider_team_id", "last_scraped_at"),
    "team_merge_map": ("deprecated_team_id", "canonical_team_id"),
    "scrape_requests": (
        "id",
        "team_id_master",
        "status",
        "priority",
        "request_type",
        "provider_id",
        "provider_team_id",
        "game_date",
        "requested_at",
    ),
}


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, name, rows, update_errors):
        self.name = name
        self._rows = rows
        self._update_errors = update_errors
        self._known = TABLE_COLUMNS[name]
        self._filters = []
        self._columns = None
        self._order = None
        self._range = None
        self._update = None

    def _check(self, column):
        if column not in self._known:
            raise AssertionError(f"{self.name}: unknown column {column!r}")

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        for c in self._columns:
            self._check(c)
        return self

    def update(self, values):
        for c in values:
            self._check(c)
        self._update = values
        return self

    def eq(self, column, value):
        self._check(column)
        self._filters.append(lambda row: row[column] == value)
        return self

    def gte(self, column, value):
        self._check(column)
        self._filters.append(lambda row: row[column] >= value)
        return self

    def in_(self, column, values):
        self._check(column)
        values = list(values)
        if len(values) > 100:
            raise AssertionError(f"{self.name}: in_() with {len(values)} values breaks the URI length limit")
        self._filters.append(lambda row: row[column] in values)
        return self

    def order(self, column, *, desc=False):
        self._check(column)
        self._order = (column, desc)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if self._range is not None and self._order is None:
            raise AssertionError(f"{self.name}: a page without order() reads the table unstably")
        rows = [row for row in self._rows if all(f(row) for f in self._filters)]
        if self._update is not None:
            if not self._filters:
                raise AssertionError(f"{self.name}: an unfiltered update rewrites the whole table")
            if self.name in self._update_errors:
                raise APIError(self._update_errors[self.name])
            for row in rows:
                row.update(self._update)
            return _Result([dict(r) for r in rows])
        if self._order is not None:
            rows = sorted(rows, key=lambda r: r[self._order[0]], reverse=self._order[1])
        if self._range is not None:
            rows = rows[self._range[0] : self._range[1] + 1]
        return _Result([{c: r[c] for c in self._columns} for r in rows])


class _RpcBuilder:
    def __init__(self, parent, name, params):
        self._parent = parent
        self._name = name
        self._params = params

    def execute(self):
        json.dumps(self._params)
        self._parent.rpc_calls.append((self._name, self._params))
        error = self._parent.rpc_errors.get(self._params["p_team_id_master"])
        if error is not None:
            raise APIError(error)
        return _Result("request-id")


class FakeSupabase:
    def __init__(self, tables, rpc_errors, update_errors):
        for name, rows in tables.items():
            for row in rows:
                assert set(row) == set(TABLE_COLUMNS[name]), f"{name} fixture row has the wrong columns"
        self.tables = tables
        self.rpc_errors = rpc_errors
        self.update_errors = update_errors
        self.rpc_calls = []

    def table(self, name):
        return _Table(name, self.tables[name], self.update_errors)

    def rpc(self, name, params):
        return _RpcBuilder(self, name, params)


REFUSED = {"code": "23505", "message": "An active scrape uses a different source or date; request unchanged"}


def team(team_id):
    return {
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "provider_id": GOTSPORT_ID,
        "provider_team_id": f"gs-{team_id}",
        "last_scraped_at": None,
    }


def waiting(row_id, team_id, *, status="pending"):
    """An automatic request filed under the team's other registration, which the RPC refuses to rewrite."""
    return {
        "id": row_id,
        "team_id_master": team_id,
        "status": status,
        "priority": 3,
        "request_type": "active_team",
        "provider_id": GOTSPORT_ID,
        "provider_team_id": "gs-other-registration",
        "game_date": "2026-11-01",
        "requested_at": "2026-11-01T12:00:00+00:00",
    }


def run_job(
    monkeypatch, *, watchlisted, teams, scrape_requests, merges=(), rpc_errors=None, update_errors=None, flags=()
):
    supabase = FakeSupabase(
        {
            "watchlist_items": [{"id": f"w-{t}", "team_id_master": t} for t in watchlisted],
            "report_card_leads": [],
            "teams": [team(t) for t in teams],
            "team_merge_map": [{"deprecated_team_id": d, "canonical_team_id": c} for d, c in merges],
            "scrape_requests": list(scrape_requests),
        },
        rpc_errors or {},
        update_errors or {},
    )
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(sys, "argv", ["enqueue_user_interest_teams.py", *flags])
    monkeypatch.setattr(uit, "create_client", lambda url, key: supabase)
    uit.main()
    return supabase


def priorities(supabase):
    return {r["id"]: r["priority"] for r in supabase.tables["scrape_requests"]}


def test_a_refused_team_has_its_waiting_request_moved_to_the_front(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    supabase = run_job(
        monkeypatch,
        watchlisted=["team-a", "team-b"],
        teams=["team-a", "team-b"],
        merges=[("old-b", "team-b"), ("old-z", "team-z")],
        scrape_requests=[
            waiting("before-merge", "old-b"),
            waiting("running", "team-b", status="processing"),
            waiting("unrelated-merge", "old-z"),
        ],
        rpc_errors={"team-b": REFUSED},
    )

    assert [params["p_team_id_master"] for _, params in supabase.rpc_calls] == ["team-a", "team-b"]
    assert priorities(supabase) == {"before-merge": 1, "running": 3, "unrelated-merge": 3}
    assert (
        "Enqueued 1 teams at priority 1, moved 1 teams' waiting requests to the front, "
        "0 teams already being scraped, 0 failed"
    ) in caplog.text


def test_a_refused_team_with_nothing_waiting_is_not_counted_as_moved(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    supabase = run_job(
        monkeypatch,
        watchlisted=["team-b"],
        teams=["team-b"],
        scrape_requests=[waiting("running", "team-b", status="processing")],
        rpc_errors={"team-b": REFUSED},
    )

    assert priorities(supabase) == {"running": 3}
    assert (
        "Enqueued 0 teams at priority 1, moved 0 teams' waiting requests to the front, "
        "1 teams already being scraped, 0 failed"
    ) in caplog.text


def test_a_failed_move_is_counted_as_a_failure(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    supabase = run_job(
        monkeypatch,
        watchlisted=["team-b"],
        teams=["team-b"],
        scrape_requests=[waiting("waiting", "team-b")],
        rpc_errors={"team-b": REFUSED},
        update_errors={"scrape_requests": {"code": "57014", "message": "canceling statement due to statement timeout"}},
    )

    assert priorities(supabase) == {"waiting": 3}
    assert (
        "Enqueued 0 teams at priority 1, moved 0 teams' waiting requests to the front, "
        "0 teams already being scraped, 1 failed"
    ) in caplog.text


def test_any_other_enqueue_error_is_a_failure_and_moves_nothing(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    supabase = run_job(
        monkeypatch,
        watchlisted=["team-c"],
        teams=["team-c"],
        scrape_requests=[waiting("waiting", "team-c")],
        rpc_errors={"team-c": {"code": "57014", "message": "canceling statement due to statement timeout"}},
    )

    assert priorities(supabase) == {"waiting": 3}
    assert (
        "Enqueued 0 teams at priority 1, moved 0 teams' waiting requests to the front, "
        "0 teams already being scraped, 1 failed"
    ) in caplog.text


def test_a_dry_run_moves_nothing(monkeypatch):
    supabase = run_job(
        monkeypatch,
        watchlisted=["team-b"],
        teams=["team-b"],
        scrape_requests=[waiting("waiting", "team-b")],
        rpc_errors={"team-b": REFUSED},
        flags=["--dry-run"],
    )

    assert supabase.rpc_calls == []
    assert priorities(supabase) == {"waiting": 3}
