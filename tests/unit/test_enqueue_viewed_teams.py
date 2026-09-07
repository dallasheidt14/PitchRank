"""Tests for the viewed-teams enqueue.

The Supabase double here evaluates its filters. A double that records calls and
returns canned rows is strictly more permissive than PostgREST, so an unfiltered
read, a filter on the wrong column and a projection missing a column the caller
goes on to read would all pass green against it. This one:

  - applies eq / in_ / gte rather than recording them,
  - projects rows down to the selected columns, so reading a column the query did
    not ask for raises here exactly as it would in production,
  - requires order() before range(), so paging a growing table without a sort key
    fails,
  - gives order() postgrest-py's keyword-only ``desc``,
  - records an RPC only when ``execute()`` runs, so a call that is built and never
    sent cannot pass for a write,
  - raises on a table nobody seeded.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import enqueue_viewed_teams as evt  # noqa: E402

GOTSPORT_ID = "prov-gotsport"
OTHER_PROVIDER_ID = "prov-tgs"

PREMIUM_USER = "user-premium"
ADMIN_USER = "user-admin"


def hours_ago(n):
    return (datetime.now(timezone.utc) - timedelta(hours=n)).isoformat()


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, name, rows):
        self.name = name
        self._rows = rows
        self._filters = []
        self._columns = None
        self._order = None
        self._single = False

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", column, value))
        return self

    def order(self, column, *, desc=False):
        # Keyword-only, matching postgrest-py: order("id", True) is a TypeError
        # there, so a double that accepted it would hide the mistake.
        self._order = (column, desc)
        return self

    def single(self):
        self._single = True
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

    def range(self, start, end):
        if self._order is None:
            raise AssertionError(f"{self.name}: range() without order() pages a table unstably")
        rows = sorted(self._matching(), key=lambda r: r[self._order[0]], reverse=self._order[1])
        self._page = self._project(rows[start : end + 1])
        return self

    def execute(self):
        if hasattr(self, "_page"):
            return _Result(self._page)
        rows = self._project(self._matching())
        if self._single:
            return _Result(rows[0] if rows else None)
        return _Result(rows)


class _RpcBuilder:
    """Records the call at execute(), never at construction.

    postgrest-py returns a builder that does nothing until executed, so a double
    that recorded at rpc() would let a caller which never sends the request pass
    for one that wrote a row.
    """

    def __init__(self, parent, name, params):
        self._parent = parent
        self._name = name
        self._params = params

    def execute(self):
        if self._params.get("p_team_id_master") in self._parent.rpc_failures:
            raise RuntimeError("simulated PostgREST failure")
        self._parent.rpc_calls.append((self._name, self._params))
        return _Result(None)


class FakeSupabase:
    def __init__(self, tables, rpc_failures=frozenset()):
        self._tables = tables
        self.rpc_calls = []
        self.rpc_failures = rpc_failures

    def table(self, name):
        if name not in self._tables:
            raise AssertionError(f"query against unseeded table {name!r}")
        return _Table(name, self._tables[name])

    def rpc(self, name, params):
        return _RpcBuilder(self, name, params)


def build_supabase(
    views,
    teams,
    merges=(),
    scrape_requests=(),
    profiles=None,
    providers=None,
    aliases=(),
    rpc_failures=frozenset(),
):
    return FakeSupabase(
        {
            "providers": list(
                providers if providers is not None else [{"id": GOTSPORT_ID, "code": "gotsport"}]
            ),
            "user_profiles": list(
                profiles if profiles is not None else [{"id": ADMIN_USER, "plan": "admin"}]
            ),
            evt.VIEW_TABLE: list(views),
            "teams": list(teams),
            "team_merge_map": list(merges),
            "scrape_requests": list(scrape_requests),
            "team_alias_map": list(aliases),
        },
        rpc_failures=rpc_failures,
    )


def view(team_id, user_id=PREMIUM_USER, age_hours=1, row_id=None):
    return {
        "id": row_id if row_id is not None else abs(hash((team_id, user_id, age_hours))) % 100000,
        "team_id_master": team_id,
        "user_id": user_id,
        "viewed_at": hours_ago(age_hours),
    }


def team(team_id, provider_id=GOTSPORT_ID, last_scraped_at=None, name=None):
    return {
        "team_id_master": team_id,
        "team_name": name or f"Team {team_id}",
        "provider_id": provider_id,
        "provider_team_id": f"gs-{team_id}",
        "last_scraped_at": last_scraped_at,
    }


def alias(team_id, provider_id=GOTSPORT_ID, review_status="approved"):
    return {
        "team_id_master": team_id,
        "provider_id": provider_id,
        "review_status": review_status,
    }


def pending(team_id, priority=1, status="pending"):
    return {"team_id_master": team_id, "status": status, "priority": priority}


def select(supabase, **kwargs):
    kwargs.setdefault("window_hours", evt.DEFAULT_WINDOW_HOURS)
    kwargs.setdefault("cooldown_hours", evt.DEFAULT_COOLDOWN_HOURS)
    kwargs.setdefault("limit", evt.DEFAULT_LIMIT)
    return evt.select_targets(supabase, GOTSPORT_ID, **kwargs)


def test_constants_pin_the_tier_and_tag():
    assert evt.PRIORITY_VIEWED_TEAM == 2
    assert evt.REQUEST_TYPE == "viewed_team"


def test_window_absorbs_the_scheduler_drift_this_repo_has_recorded():
    """A window equal to the cadence loses every view in the gap when a run is late.
    enqueue-active-teams.yml records a run sliding from 10:00 to 20:10, so the
    overlap has to clear ten hours, not merely be greater than the cadence."""
    assert evt.DEFAULT_WINDOW_HOURS >= 34


def test_view_outside_the_window_is_not_enqueued():
    supabase = build_supabase(
        views=[view("t-recent", age_hours=2), view("t-old", age_hours=48)],
        teams=[team("t-recent"), team("t-old")],
    )

    targets = select(supabase, window_hours=36)

    assert [t["team_id_master"] for t in targets] == ["t-recent"]


def test_a_view_inside_the_overlap_still_counts():
    supabase = build_supabase(views=[view("t-1", age_hours=27)], teams=[team("t-1")])

    assert [t["team_id_master"] for t in select(supabase)] == ["t-1"]


def test_admin_view_does_not_enqueue_but_a_subscriber_view_of_the_same_team_does():
    admin_only = build_supabase(
        views=[view("t-1", user_id=ADMIN_USER)],
        teams=[team("t-1")],
    )
    assert select(admin_only) == []

    also_viewed_by_subscriber = build_supabase(
        views=[view("t-1", user_id=ADMIN_USER), view("t-1", user_id=PREMIUM_USER)],
        teams=[team("t-1")],
    )
    assert [t["team_id_master"] for t in select(also_viewed_by_subscriber)] == ["t-1"]


def test_deprecated_team_resolves_to_canonical_and_enqueues_once():
    supabase = build_supabase(
        views=[view("t-old", row_id=1), view("t-canonical", row_id=2)],
        teams=[team("t-canonical")],
        merges=[{"deprecated_team_id": "t-old", "canonical_team_id": "t-canonical"}],
    )

    targets = select(supabase)

    assert [t["team_id_master"] for t in targets] == ["t-canonical"]


def test_team_scraped_inside_the_cooldown_is_skipped():
    supabase = build_supabase(
        views=[view("t-fresh", row_id=1), view("t-stale", row_id=2)],
        teams=[
            team("t-fresh", last_scraped_at=hours_ago(2)),
            team("t-stale", last_scraped_at=hours_ago(40)),
        ],
    )

    targets = select(supabase, cooldown_hours=20)

    assert [t["team_id_master"] for t in targets] == ["t-stale"]


def test_never_scraped_team_is_not_treated_as_recently_scraped():
    supabase = build_supabase(views=[view("t-1")], teams=[team("t-1", last_scraped_at=None)])

    assert [t["team_id_master"] for t in select(supabase)] == ["t-1"]


def test_non_gotsport_team_with_no_alias_is_skipped():
    supabase = build_supabase(
        views=[view("t-gs", row_id=1), view("t-tgs", row_id=2)],
        teams=[team("t-gs"), team("t-tgs", provider_id=OTHER_PROVIDER_ID)],
    )

    targets = select(supabase)

    assert [t["team_id_master"] for t in targets] == ["t-gs"]


def test_non_gotsport_team_with_an_approved_alias_is_enqueued():
    """process_missing_games re-routes such a team through the alias, so dropping it
    would discard a team the drainer can serve."""
    supabase = build_supabase(
        views=[view("t-tgs")],
        teams=[team("t-tgs", provider_id=OTHER_PROVIDER_ID)],
        aliases=[alias("t-tgs")],
    )

    assert [t["team_id_master"] for t in select(supabase)] == ["t-tgs"]


def test_an_unapproved_alias_does_not_make_a_team_eligible():
    """get_gotsport_alias filters on review_status='approved', so a pending alias is
    one the drainer will not follow."""
    supabase = build_supabase(
        views=[view("t-tgs")],
        teams=[team("t-tgs", provider_id=OTHER_PROVIDER_ID)],
        aliases=[alias("t-tgs", review_status="pending")],
    )

    assert select(supabase) == []


def test_a_team_with_no_provider_is_skipped_even_with_an_approved_alias():
    """teams.provider_id is nullable, and process_missing_games validates the queue row
    before reaching its alias fallback, so such a row can only become a failed item."""
    supabase = build_supabase(
        views=[view("t-nullprov")],
        teams=[team("t-nullprov", provider_id=None)],
        aliases=[alias("t-nullprov")],
    )

    assert select(supabase) == []


def test_an_alias_on_another_provider_does_not_count():
    supabase = build_supabase(
        views=[view("t-tgs")],
        teams=[team("t-tgs", provider_id=OTHER_PROVIDER_ID)],
        aliases=[alias("t-tgs", provider_id=OTHER_PROVIDER_ID)],
    )

    assert select(supabase) == []


def test_team_holding_a_pending_priority_one_row_is_left_alone():
    supabase = build_supabase(
        views=[view("t-1")],
        teams=[team("t-1")],
        scrape_requests=[pending("t-1", priority=1)],
    )

    assert select(supabase) == []


def test_a_pending_lower_priority_row_is_not_protected():
    supabase = build_supabase(
        views=[view("t-1")],
        teams=[team("t-1")],
        scrape_requests=[pending("t-1", priority=2)],
    )

    assert [t["team_id_master"] for t in select(supabase)] == ["t-1"]


def test_limit_caps_the_batch():
    views = [view(f"t-{i}", row_id=i) for i in range(5)]
    supabase = build_supabase(views=views, teams=[team(f"t-{i}") for i in range(5)])

    assert len(select(supabase, limit=3)) == 3


def test_empty_window_returns_no_targets_without_touching_teams():
    supabase = build_supabase(views=[], teams=[])

    assert select(supabase) == []


def test_missing_gotsport_provider_fails_loudly():
    """Degrading to None would compare every provider_id against it, enqueue
    nothing, and exit 0 — a dead daily job reporting success."""
    supabase = build_supabase(views=[], teams=[], providers=[])

    with pytest.raises(RuntimeError, match="gotsport"):
        evt.get_gotsport_provider_id(supabase)


def _run_main(monkeypatch, supabase, argv):
    monkeypatch.setattr(evt, "create_client", lambda url, key: supabase)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(sys, "argv", ["enqueue_viewed_teams.py", *argv])
    evt.main()


def test_dry_run_enqueues_nothing(monkeypatch):
    supabase = build_supabase(views=[view("t-1")], teams=[team("t-1")])

    _run_main(monkeypatch, supabase, ["--dry-run"])

    assert supabase.rpc_calls == []


def test_live_run_enqueues_at_priority_two(monkeypatch):
    supabase = build_supabase(views=[view("t-1")], teams=[team("t-1", name="Rush WI 2012")])

    _run_main(monkeypatch, supabase, [])

    assert len(supabase.rpc_calls) == 1
    name, params = supabase.rpc_calls[0]
    assert name == "enqueue_scrape_request"
    assert params["p_team_id_master"] == "t-1"
    assert params["p_priority"] == 2
    assert params["p_request_type"] == "viewed_team"
    assert params["p_provider_id"] == GOTSPORT_ID
    assert params["p_provider_team_id"] == "gs-t-1"
    assert params["p_team_name"] == "Rush WI 2012"
    # NOT NULL in scrape_requests, and the centre of the processor's +/-90 day window.
    assert params["p_game_date"] == date.today().isoformat()


def test_one_failed_enqueue_does_not_stop_the_rest(monkeypatch):
    views = [view(f"t-{i}", row_id=i) for i in range(3)]
    supabase = build_supabase(
        views=views,
        teams=[team(f"t-{i}") for i in range(3)],
        rpc_failures={"t-1"},
    )

    _run_main(monkeypatch, supabase, [])

    assert [p["p_team_id_master"] for _, p in supabase.rpc_calls] == ["t-0", "t-2"]


def test_double_rejects_an_unseeded_table():
    supabase = FakeSupabase({})

    with pytest.raises(AssertionError, match="unseeded table"):
        supabase.table("teams")


def test_double_rejects_paging_without_a_sort_key():
    supabase = build_supabase(views=[view("t-1")], teams=[team("t-1")])

    with pytest.raises(AssertionError, match="without order"):
        supabase.table(evt.VIEW_TABLE).select("team_id_master,user_id").range(0, 999)


def test_double_records_an_rpc_only_once_executed():
    """Guards the guard: an enqueue that builds a request and never sends it must
    not read as a write."""
    supabase = build_supabase(views=[], teams=[])

    supabase.rpc("enqueue_scrape_request", {"p_team_id_master": "t-1"})
    assert supabase.rpc_calls == []

    supabase.rpc("enqueue_scrape_request", {"p_team_id_master": "t-1"}).execute()
    assert len(supabase.rpc_calls) == 1
