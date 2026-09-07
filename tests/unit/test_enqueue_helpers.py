"""Tests for the helpers shared by the table-reading enqueue scripts.

These moved out of enqueue_user_interest_teams, where they had no coverage at
all. The double evaluates in_ / eq filters rather than recording them, so a query
scoped to the wrong column or left unscoped fails here as it would in production.
"""

import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.enqueue_helpers import (  # noqa: E402
    BATCH_SIZE,
    PAGE_SIZE,
    TEAM_ROW_COLUMNS,
    _chunks,
    _paged,
    load_team_rows,
    resolve_merges,
    teams_with_pending_user_request,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, name, rows, log):
        self.name = name
        self._rows = rows
        self._log = log
        self._filters = []
        self._columns = None
        self._order = None

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        batch = list(values)
        self._log.setdefault("batches", []).append(len(batch))
        self._filters.append(("in", column, batch))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", column, value))
        return self

    def order(self, column, *, desc=False):
        # Keyword-only, matching postgrest-py: order("id", True) is a TypeError
        # there, so a double that accepted it would hide the mistake.
        self._order = (column, desc)
        self._log.setdefault("orders", []).append(column)
        return self

    def range(self, start, end):
        if self._order is None:
            raise AssertionError(f"{self.name}: range() without order() pages a table unstably")
        self._log.setdefault("ranges", []).append((start, end))
        rows = sorted(self._matching(), key=lambda r: r[self._order[0]], reverse=self._order[1])
        self._page = rows[start : end + 1]
        return self

    def _matching(self):
        rows = []
        for row in self._rows:
            keep = True
            for kind, column, value in self._filters:
                if column not in row:
                    raise AssertionError(f"{self.name}: filtered on unknown column {column!r}")
                if kind == "eq" and row[column] != value:
                    keep = False
                elif kind == "in" and row[column] not in value:
                    keep = False
                elif kind == "gte" and not (row[column] >= value):
                    keep = False
            if keep:
                rows.append(row)
        return rows

    def _project(self, rows):
        if self._columns is None:
            return [dict(r) for r in rows]
        return [{c: r[c] for c in self._columns} for r in rows]

    def execute(self):
        rows = self._page if hasattr(self, "_page") else self._matching()
        return _Result(self._project(rows))


class FakeSupabase:
    def __init__(self, tables):
        self._tables = tables
        self.log = {}

    def table(self, name):
        if name not in self._tables:
            raise AssertionError(f"query against unseeded table {name!r}")
        return _Table(name, self._tables[name], self.log)


def test_chunks_never_exceeds_the_uri_batch_cap():
    sizes = [len(c) for c in _chunks(list(range(250)))]

    assert sizes == [BATCH_SIZE, BATCH_SIZE, 50]
    assert max(sizes) <= 100


def test_paged_reads_past_the_thousand_row_cap():
    rows = [{"id": i, "team_id_master": f"t-{i}"} for i in range(PAGE_SIZE + 500)]
    supabase = FakeSupabase({"team_page_views": rows})

    fetched = _paged(lambda: supabase.table("team_page_views").select("id,team_id_master"))

    assert len(fetched) == PAGE_SIZE + 500
    assert supabase.log["ranges"] == [(0, 999), (1000, 1999)]


def test_paged_always_orders_before_ranging():
    """Unordered paging drops and repeats rows across the boundary, so there is no
    opt-out: the double refuses a range() that no order() preceded."""
    rows = [{"id": i} for i in reversed(range(10))]
    supabase = FakeSupabase({"team_page_views": rows})

    fetched = _paged(lambda: supabase.table("team_page_views").select("id"))

    assert [r["id"] for r in fetched] == list(range(10))
    assert supabase.log["orders"] == ["id"]


def test_resolve_merges_maps_deprecated_ids_and_leaves_survivors_alone():
    supabase = FakeSupabase(
        {"team_merge_map": [{"deprecated_team_id": "t-old", "canonical_team_id": "t-new"}]}
    )

    resolved = resolve_merges(supabase, {"t-old", "t-untouched"})

    assert resolved == {"t-old": "t-new", "t-untouched": "t-untouched"}


def test_resolve_merges_batches_ids_under_the_uri_cap():
    supabase = FakeSupabase({"team_merge_map": []})

    resolve_merges(supabase, {f"t-{i}" for i in range(250)})

    assert supabase.log["batches"] == [BATCH_SIZE, BATCH_SIZE, 50]


def test_load_team_rows_selects_the_fields_the_enqueue_and_cooldown_need():
    supabase = FakeSupabase(
        {
            "teams": [
                {
                    "team_id_master": "t-1",
                    "team_name": "Team One",
                    "provider_id": "prov",
                    "provider_team_id": "gs-1",
                    "last_scraped_at": "2026-09-01T00:00:00+00:00",
                }
            ]
        }
    )

    rows = load_team_rows(supabase, {"t-1"})

    assert set(rows["t-1"]) == set(TEAM_ROW_COLUMNS.split(","))
    assert rows["t-1"]["last_scraped_at"] == "2026-09-01T00:00:00+00:00"
    assert rows["t-1"]["provider_team_id"] == "gs-1"


def _pending(team_id, priority, request_type="active_team", status="pending"):
    return {
        "team_id_master": team_id,
        "status": status,
        "priority": priority,
        "request_type": request_type,
    }


def test_pending_user_request_protects_every_priority_one_row():
    """Priority is the proxy, because request_type cannot be.

    enqueue_scrape_request's UPDATE branch leaves request_type as the automatic
    producer wrote it, so a user click that promotes an existing pending row is
    indistinguishable by type from the row it promoted.
    """
    supabase = FakeSupabase(
        {
            "scrape_requests": [
                _pending("t-click", 1, request_type="missing_game"),
                _pending("t-promoted", 1, request_type="active_team"),
                _pending("t-hygiene", 1, request_type="retention_hygiene"),
                _pending("t-auto", 2, request_type="active_team"),
            ]
        }
    )

    protected = teams_with_pending_user_request(
        supabase, {"t-click", "t-promoted", "t-hygiene", "t-auto"}
    )

    assert protected == {"t-click", "t-promoted", "t-hygiene"}


def test_pending_user_request_ignores_a_settled_row():
    supabase = FakeSupabase(
        {
            "scrape_requests": [
                _pending("t-done", 1, request_type="missing_game", status="completed"),
                _pending("t-live", 1, request_type="missing_game"),
            ]
        }
    )

    protected = teams_with_pending_user_request(supabase, {"t-done", "t-live"})

    assert protected == {"t-live"}


def test_double_rejects_an_unseeded_table():
    supabase = FakeSupabase({})

    with pytest.raises(AssertionError, match="unseeded table"):
        supabase.table("teams")
