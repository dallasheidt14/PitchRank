"""Tests for the daily opponent-frontier enqueue.

The Supabase double evaluates its filters, and is strict where this job needs it:

  - every table has a fixed column list, so selecting or filtering on a column
    the real table lacks raises at build time,
  - gt() and gte() follow SQL: a NULL cell never matches, and timestamp columns
    compare as instants rather than as strings,
  - in_() refuses more than 100 values, the URI-length limit the callers batch for,
  - a limit() or range() page refuses to run without order(), and order() keys
    accumulate as postgrest-py's do,
  - execute() answers at most max_rows rows, so a read that does not page comes
    back short, and fixture rows are stored in reverse, so an unordered read is wrong,
  - each executed table query is recorded with its filters and order,
  - the RPC accepts only enqueue_scrape_request with exactly its seven parameters,
    passes them through json.dumps, and records the call at execute().

Dates and timestamps are seeded as the ISO strings PostgREST returns.
"""

import itertools
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timezone

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(REPO_ROOT)

from postgrest.exceptions import APIError  # noqa: E402

from scripts import enqueue_helpers  # noqa: E402
from scripts import enqueue_opponent_frontier as eof  # noqa: E402

GOTSPORT_ID = "prov-gotsport"
TGS_ID = "prov-tgs"

NOW = datetime(2026, 11, 24, 8, 43, tzinfo=timezone.utc)
CREATED = "2026-11-23T14:01:52.094868+00:00"
GAME_DAY = "2026-11-22"

TABLE_COLUMNS = {
    "providers": ("id", "code"),
    "games": (
        "id",
        "game_date",
        "created_at",
        "provider_id",
        "home_team_master_id",
        "away_team_master_id",
        "home_provider_id",
        "away_provider_id",
        "home_score",
        "away_score",
        "is_excluded",
        "source_url",
    ),
    "teams": (
        "team_id_master",
        "team_name",
        "provider_id",
        "provider_team_id",
        "age_group",
        "birth_year",
        "is_deprecated",
    ),
    "team_merge_map": ("deprecated_team_id", "canonical_team_id"),
    "team_alias_map": ("id", "team_id_master", "provider_id", "provider_team_id", "review_status"),
    "team_scrape_log": ("id", "team_id", "provider_id", "scraped_at", "status"),
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
        "completed_at",
    ),
    "team_ranking_exclusions": ("team_id_master",),
}
TIMESTAMP_COLUMNS = frozenset({"created_at", "scraped_at", "completed_at", "requested_at"})
RPC_PARAMS = frozenset(
    {
        "p_team_id_master",
        "p_team_name",
        "p_provider_id",
        "p_provider_team_id",
        "p_game_date",
        "p_request_type",
        "p_priority",
    }
)


def _comparable(column, value):
    return datetime.fromisoformat(value) if column in TIMESTAMP_COLUMNS else value


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, parent, name):
        self._parent = parent
        self.name = name
        self._known = TABLE_COLUMNS[name]
        self._filters = []
        self._columns = None
        self._order = []
        self._limit = None
        self._range = None
        self._single = False

    def _check(self, column):
        if column not in self._known:
            raise AssertionError(f"{self.name}: unknown column {column!r}")

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        for c in self._columns:
            self._check(c)
        return self

    def _filter(self, kind, column, value):
        self._check(column)
        self._filters.append((kind, column, value))
        return self

    def eq(self, column, value):
        return self._filter("eq", column, value)

    def gt(self, column, value):
        if any(kind == "gt" and c == column for kind, c, _ in self._filters):
            raise AssertionError(f"{self.name}: a second gt({column!r}) on one builder: it was reused across pages")
        return self._filter("gt", column, value)

    def gte(self, column, value):
        return self._filter("gte", column, value)

    def in_(self, column, values):
        values = list(values)
        if len(values) > 100:
            raise AssertionError(f"{self.name}: in_() with {len(values)} values breaks the URI length limit")
        return self._filter("in", column, values)

    def is_(self, column, value):
        if value != "null":
            raise AssertionError(f"{self.name}: is_() supports only 'null', got {value!r}")
        return self._filter("is_null", column, None)

    def order(self, column, *, desc=False):
        self._check(column)
        self._order.append((column, desc))
        return self

    # postgrest-py appends a repeated limit() or range() to the builder's params, so a
    # builder reused across pages sends another limit (and offset) every page.
    def limit(self, count):
        if self._limit is not None:
            raise AssertionError(f"{self.name}: a second limit() on one builder: it was reused across pages")
        self._limit = count
        return self

    def range(self, start, end):
        if self._range is not None:
            raise AssertionError(f"{self.name}: a second range() on one builder: it was reused across pages")
        self._range = (start, end)
        return self

    def single(self):
        self._single = True
        return self

    def _keep(self, row):
        for kind, column, value in self._filters:
            cell = row[column]
            if kind == "eq" and cell != value:
                return False
            if kind == "in" and cell not in value:
                return False
            if kind == "is_null" and cell is not None:
                return False
            if kind in ("gt", "gte"):
                if cell is None:
                    return False
                left, right = _comparable(column, cell), _comparable(column, value)
                if (kind == "gt" and not left > right) or (kind == "gte" and not left >= right):
                    return False
        return True

    def execute(self):
        if (self._range is not None or self._limit is not None) and not self._order:
            raise AssertionError(f"{self.name}: a page without order() reads the table unstably")
        rows = [r for r in self._parent.tables[self.name] if self._keep(r)]
        for column, desc in reversed(self._order):
            rows.sort(key=lambda r, c=column: _comparable(c, r[c]), reverse=desc)
        if self._range is not None:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        rows = rows[: self._parent.max_rows]
        self._parent.queries.append({"table": self.name, "filters": list(self._filters), "order": list(self._order)})
        rows = [{c: r[c] for c in self._columns} for r in rows] if self._columns else [dict(r) for r in rows]
        if self._parent.after_execute is not None:
            self._parent.after_execute(self._parent, self.name, rows)
        if self._single:
            if not rows:
                raise RuntimeError("PGRST116: JSON object requested, multiple (or no) rows returned")
            return _Result(rows[0])
        return _Result(rows)


class _RpcBuilder:
    def __init__(self, parent, name, params):
        self._parent = parent
        self._name = name
        self._params = params

    def execute(self):
        if self._name != "enqueue_scrape_request":
            raise AssertionError(f"unexpected RPC {self._name!r}")
        if set(self._params) != RPC_PARAMS:
            raise AssertionError(f"enqueue_scrape_request called with {sorted(self._params)}")
        json.dumps(self._params)
        self._parent.rpc_calls.append((self._name, self._params))
        error = self._parent.rpc_errors.get(self._params["p_team_id_master"])
        if isinstance(error, dict):
            raise APIError(error)
        if error is not None:
            raise error
        return _Result(f"00000000-0000-4000-8000-{len(self._parent.rpc_calls):012d}")


class FakeSupabase:
    def __init__(self, tables, *, rpc_errors=None, max_rows=1000, after_execute=None):
        for name, rows in tables.items():
            for row in rows:
                assert set(row) == set(TABLE_COLUMNS[name]), f"{name} fixture row has the wrong columns"
        self.tables = {name: list(reversed(rows)) for name, rows in tables.items()}
        self.rpc_errors = rpc_errors or {}
        self.max_rows = max_rows
        self.after_execute = after_execute
        self.rpc_calls = []
        self.queries = []

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"query against unseeded table {name!r}")
        return _Table(self, name)

    def rpc(self, name, params):
        return _RpcBuilder(self, name, params)


_ids = itertools.count()
_DEFAULT = object()


def team(
    team_id, gotsport_id=None, *, provider_id=GOTSPORT_ID, name=None, age_group="u13", birth_year=2014, deprecated=False
):
    return {
        "team_id_master": team_id,
        "team_name": name or f"Team {team_id}",
        "provider_id": provider_id,
        "provider_team_id": gotsport_id if gotsport_id is not None else f"own-{team_id}",
        "age_group": age_group,
        "birth_year": birth_year,
        "is_deprecated": deprecated,
    }


def game(
    source,
    source_gs,
    opponent,
    opponent_gs,
    *,
    source_side="home",
    created_at=CREATED,
    game_date=GAME_DAY,
    home_score=2,
    away_score=1,
    is_excluded=False,
    provider_id=GOTSPORT_ID,
    source_url=_DEFAULT,
    game_id=None,
):
    other = "away" if source_side == "home" else "home"
    return {
        "id": game_id or f"g-{next(_ids):05d}",
        "game_date": game_date,
        "created_at": created_at,
        "provider_id": provider_id,
        f"{source_side}_team_master_id": source,
        f"{other}_team_master_id": opponent,
        f"{source_side}_provider_id": source_gs,
        f"{other}_provider_id": opponent_gs,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": is_excluded,
        "source_url": (
            f"https://rankings.gotsport.com/teams/{source_gs}/game-history" if source_url is _DEFAULT else source_url
        ),
    }


def sighting(opponent, opponent_gs, **kwargs):
    """A game saved from a source team's page naming opponent."""
    return game(f"src-{opponent}", f"9{next(_ids):06d}", opponent, opponent_gs, **kwargs)


def log(team_id, status, scraped_at, *, provider_id=GOTSPORT_ID, log_id=None):
    return {
        "id": log_id or f"l-{next(_ids):05d}",
        "team_id": team_id,
        "provider_id": provider_id,
        "scraped_at": scraped_at,
        "status": status,
    }


def request(
    team_id,
    *,
    status="failed",
    completed_at=None,
    requested_at="2026-11-20T00:00:00+00:00",
    provider_id=GOTSPORT_ID,
    priority=2,
    request_id=None,
):
    return {
        "id": request_id or f"r-{next(_ids):05d}",
        "team_id_master": team_id,
        "status": status,
        "priority": priority,
        "request_type": "active_team",
        "provider_id": provider_id,
        "provider_team_id": "1",
        "game_date": "2026-11-20",
        "requested_at": requested_at,
        "completed_at": completed_at,
    }


def alias(team_id, gotsport_id, *, review_status="approved", provider_id=GOTSPORT_ID):
    return {
        "id": f"a-{next(_ids):05d}",
        "team_id_master": team_id,
        "provider_id": provider_id,
        "provider_team_id": gotsport_id,
        "review_status": review_status,
    }


def merge(old, canonical):
    return {"deprecated_team_id": old, "canonical_team_id": canonical}


def build(*, games=(), teams=(), merges=(), aliases=(), logs=(), requests=(), exclusions=(), **kwargs):
    return FakeSupabase(
        {
            "providers": [{"id": GOTSPORT_ID, "code": "gotsport"}, {"id": TGS_ID, "code": "tgs"}],
            "games": list(games),
            "teams": list(teams),
            "team_merge_map": list(merges),
            "team_alias_map": list(aliases),
            "team_scrape_log": list(logs),
            "scrape_requests": list(requests),
            "team_ranking_exclusions": [{"team_id_master": t} for t in exclusions],
        },
        **kwargs,
    )


CONTROL = "c-control"


def control(**kwargs):
    """An opponent that is always queued, so a test of one skip has a target beside it."""
    return [sighting(CONTROL, "1000", **kwargs)], [team(CONTROL, "1000")]


def select(supabase, *, now=NOW, window_days=7, rescrape_after_days=14, limit=1000):
    return eof.select_targets(
        supabase,
        GOTSPORT_ID,
        now,
        window_days=window_days,
        rescrape_after_days=rescrape_after_days,
        limit=limit,
    )


def target_ids(selection):
    return [t["team_id_master"] for t in selection.targets]


def _frozen(instant):
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.replace(tzinfo=None) if tz is None else instant.astimezone(tz)

    return _FrozenDatetime


def run_main(monkeypatch, supabase, argv=(), *, now=NOW, env=None):
    """Run main() against the double; returns its exit status."""
    monkeypatch.setattr(eof, "create_client", lambda url, key: supabase)
    monkeypatch.setattr(eof, "datetime", _frozen(now))
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    for name, value in (env or {}).items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", ["enqueue_opponent_frontier.py", *argv])
    try:
        eof.main()
    except SystemExit as e:
        return e.code
    return 0


def called_ids(supabase):
    return [params["p_team_id_master"] for _, params in supabase.rpc_calls]


# --------------------------------------------------------------------------- #
# Which side of a game is the opponent
# --------------------------------------------------------------------------- #


def test_the_side_the_source_page_does_not_name_is_the_opponent():
    supabase = build(
        games=[
            game("s-home", "2001", "o-away", "2002", source_side="home"),
            game("s-away", "2003", "o-home", "2004", source_side="away"),
        ],
        teams=[team("s-home", "2001"), team("o-away", "2002"), team("s-away", "2003"), team("o-home", "2004")],
    )

    selection = select(supabase)

    assert sorted(target_ids(selection)) == ["o-away", "o-home"]


def test_a_source_naming_neither_side_is_skipped():
    games, teams = control()
    supabase = build(
        games=[
            *games,
            game(
                "s-1", "2001", "o-other-id", "2002", source_url="https://rankings.gotsport.com/teams/5555/game-history"
            ),
            game(
                "s-2",
                "2003",
                "o-schedule",
                "2004",
                source_url="https://system.gotsport.com/org_event/events/1/schedules?group=2",
            ),
            game("s-3", "2005", "o-no-url", "2006", source_url=None),
            game(
                "s-4",
                "2007",
                "o-embedded",
                "2008",
                source_url="https://system.gotsport.com/org_event/events/1/schedules"
                "?from=https://rankings.gotsport.com/teams/2007/game-history",
            ),
        ],
        teams=[
            *teams,
            team("o-other-id", "2002"),
            team("o-schedule", "2004"),
            team("o-no-url", "2006"),
            team("o-embedded", "2008"),
        ],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.stats["source_matches_neither"] == 4


def test_a_source_naming_both_sides_is_skipped_even_between_two_teams():
    games, teams = control()
    supabase = build(
        games=[*games, game("b-home", "2001", "b-away", "2001")],
        teams=[*teams, team("b-home", "2001"), team("b-away", "2001")],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.stats["source_matches_both"] == 1
    assert selection.stats["self_game"] == 0


def test_a_game_between_two_registrations_of_one_team_is_not_a_sighting():
    games, teams = control()
    supabase = build(
        games=[*games, game("m-old", "2001", "m-team", "2002")],
        teams=[*teams, team("m-team", "2002")],
        merges=[merge("m-old", "m-team")],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.stats["self_game"] == 1


def test_a_game_whose_source_team_is_unlinked_still_names_its_opponent():
    games, teams = control()
    supabase = build(games=[*games, game(None, "2001", "o-seen", "2002")], teams=[*teams, team("o-seen", "2002")])

    selection = select(supabase)

    assert sorted(target_ids(selection)) == [CONTROL, "o-seen"]
    assert selection.stats["source_master_null"] == 1


# --------------------------------------------------------------------------- #
# What the games read asks PostgREST for, and what it filters itself
# --------------------------------------------------------------------------- #


def test_the_games_read_filters_only_on_provider_and_window_in_created_at_order():
    games, teams = control()
    supabase = build(
        games=[
            *games,
            sighting("o-before-window", "2001", created_at="2026-11-17T08:42:59+00:00"),
            sighting("o-other-provider", "2002", provider_id=TGS_ID),
        ],
        teams=[*teams, team("o-before-window", "2001"), team("o-other-provider", "2002")],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    games_reads = [q for q in supabase.queries if q["table"] == "games"]
    assert games_reads == [
        {
            "table": "games",
            "filters": [("eq", "provider_id", GOTSPORT_ID), ("gte", "created_at", "2026-11-17T08:43:00+00:00")],
            "order": [("created_at", False), ("id", False)],
        }
    ]


def test_each_game_filter_skips_only_its_own_row():
    games, teams = control(created_at="2026-11-23T14:01:52.09486+00:00")
    supabase = build(
        games=[
            *games,
            sighting("o-home-null", "2001", home_score=None),
            sighting("o-away-null", "2002", away_score=None),
            sighting("o-excluded", "2003", is_excluded=True),
            sighting("o-before-season", "2004", game_date="2026-07-31"),
            sighting("o-after-today", "2005", game_date="2026-11-25"),
        ],
        teams=[
            *teams,
            team("o-home-null", "2001"),
            team("o-away-null", "2002"),
            team("o-excluded", "2003"),
            team("o-before-season", "2004"),
            team("o-after-today", "2005"),
        ],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.raw_rows == 6
    for reason in ("home_score_null", "away_score_null", "excluded_game", "before_season", "after_today"):
        assert selection.stats[reason] == 1, reason


def test_a_game_with_no_opponent_team_or_id_is_skipped():
    games, teams = control()
    supabase = build(
        games=[*games, game("s-1", "2001", None, "2002"), game("s-2", "2003", "o-blank", "None")],
        teams=[*teams, team("o-blank", "None")],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.stats["opponent_master_null"] == 1
    assert selection.stats["opponent_id_blank"] == 1


# --------------------------------------------------------------------------- #
# "Never scraped this season" and the failure wait
# --------------------------------------------------------------------------- #


def test_only_an_own_gotsport_success_or_partial_since_aug_1_counts_as_scraped():
    games, teams = control()
    names = ["n-success", "n-partial", "n-before-season", "n-other-provider", "n-old-error"]
    supabase = build(
        games=[*games, *[sighting(n, f"20{i:02d}") for i, n in enumerate(names)]],
        teams=[*teams, *[team(n, f"20{i:02d}") for i, n in enumerate(names)]],
        logs=[
            log("n-success", "success", "2026-11-01T10:00:00+00:00"),
            log("n-partial", "partial", "2026-11-01T10:00:00+00:00"),
            log("n-before-season", "success", "2026-07-15T10:00:00+00:00"),
            log("n-other-provider", "success", "2026-11-01T10:00:00+00:00", provider_id=TGS_ID),
            log("n-old-error", "error", "2026-10-01T10:00:00+00:00"),
        ],
    )

    selection = select(supabase)

    assert sorted(target_ids(selection)) == [CONTROL, "n-before-season", "n-old-error", "n-other-provider"]
    assert selection.stats["scraped_this_season"] == 2


def test_a_july_scrape_read_for_the_failure_wait_does_not_count_as_this_season():
    now = datetime(2026, 8, 3, 8, 43, tzinfo=timezone.utc)
    supabase = build(
        games=[sighting("n-july", "2001", created_at="2026-08-02T10:00:00+00:00", game_date="2026-08-02")],
        teams=[team("n-july", "2001")],
        logs=[log("n-july", "success", "2026-07-30T10:00:00+00:00")],
    )

    selection = select(supabase, now=now)

    assert target_ids(selection) == ["n-july"]
    assert selection.list_name == "primary"


def test_a_failure_in_the_last_seven_days_holds_a_team_back():
    games, teams = control()
    names = [
        "w-error",
        "w-old-error",
        "w-failed-gotsport",
        "w-failed-tgs",
        "w-failed-old",
        "w-failed-requested-early",
        "w-completed",
        "w-pending",
    ]
    supabase = build(
        games=[*games, *[sighting(n, f"20{i:02d}") for i, n in enumerate(names)]],
        teams=[*teams, *[team(n, f"20{i:02d}") for i, n in enumerate(names)]],
        logs=[
            log("w-error", "error", "2026-11-20T10:00:00+00:00"),
            log("w-old-error", "error", "2026-11-16T10:00:00+00:00"),
        ],
        requests=[
            request("w-failed-gotsport", completed_at="2026-11-22T10:00:00+00:00"),
            request("w-failed-tgs", completed_at="2026-11-22T10:00:00+00:00", provider_id=TGS_ID),
            request("w-failed-old", completed_at="2026-11-16T10:00:00+00:00"),
            request(
                "w-failed-requested-early",
                requested_at="2026-11-16T10:00:00+00:00",
                completed_at="2026-11-23T10:00:00+00:00",
            ),
            request("w-completed", status="completed", completed_at="2026-11-22T10:00:00+00:00"),
            request("w-pending", status="pending", completed_at=None),
        ],
    )

    selection = select(supabase)

    assert sorted(target_ids(selection)) == [CONTROL, "w-completed", "w-failed-old", "w-old-error", "w-pending"]
    assert selection.stats["recent_error"] == 4


def test_a_july_error_still_holds_a_team_on_aug_1():
    now = datetime(2026, 8, 1, 8, 43, tzinfo=timezone.utc)
    seen = {"created_at": "2026-08-01T05:00:00+00:00", "game_date": "2026-08-01"}
    supabase = build(
        games=[sighting("w-jul-31", "2001", **seen), sighting("w-jul-24", "2002", **seen)],
        teams=[team("w-jul-31", "2001"), team("w-jul-24", "2002")],
        logs=[
            log("w-jul-31", "error", "2026-07-31T12:00:00+00:00"),
            log("w-jul-24", "error", "2026-07-24T12:00:00+00:00"),
        ],
    )

    selection = select(supabase, now=now)

    assert target_ids(selection) == ["w-jul-24"]
    assert selection.stats["recent_error"] == 1


# --------------------------------------------------------------------------- #
# Merges
# --------------------------------------------------------------------------- #


def test_every_read_covers_ids_merged_into_the_candidate():
    games, teams = control()
    supabase = build(
        games=[
            *games,
            sighting("m-old", "2001"),
            sighting("m-scraped", "2002"),
            sighting("m-failed", "2003"),
            sighting("m-aliased", "2004"),
        ],
        teams=[
            *teams,
            team("m-new", "2001"),
            team("m-scraped", "2002"),
            team("m-failed", "2003"),
            team("m-aliased", "tgs-9", provider_id=TGS_ID),
        ],
        merges=[
            merge("m-old", "m-new"),
            merge("m-scraped-old", "m-scraped"),
            merge("m-failed-old", "m-failed"),
            merge("m-aliased-old", "m-aliased"),
        ],
        logs=[log("m-scraped-old", "success", "2026-11-01T10:00:00+00:00")],
        requests=[request("m-failed-old", completed_at="2026-11-22T10:00:00+00:00")],
        aliases=[alias("m-aliased-old", "2004")],
    )

    selection = select(supabase)

    chosen = {t["team_id_master"]: t["provider_team_id"] for t in selection.targets}
    assert chosen == {CONTROL: "1000", "m-new": "2001", "m-aliased": "2004"}
    assert selection.stats["scraped_this_season"] == 1
    assert selection.stats["recent_error"] == 1


# --------------------------------------------------------------------------- #
# Team filters
# --------------------------------------------------------------------------- #


def test_each_team_filter_skips_only_its_own_team():
    games, teams = control()
    supabase = build(
        games=[
            *games,
            sighting("f-no-row", "2001"),
            sighting("f-deprecated", "2002"),
            sighting("f-u9", "2003"),
            sighting("f-birth-year", "2004"),
            sighting("f-excluded", "2005"),
            sighting("f-deprecated-null", "2006"),
        ],
        teams=[
            *teams,
            team("f-deprecated", "2002", deprecated=True),
            team("f-deprecated-null", "2006", deprecated=None),
            team("f-u9", "2003", age_group="u9"),
            team("f-birth-year", "2004", birth_year=2018),
            team("f-excluded", "2005"),
        ],
        merges=[merge("f-excluded-old", "f-excluded")],
        exclusions=["f-excluded-old"],
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.stats["deprecated"] == 2
    for reason in ("no_team_row", "not_on_board", "excluded_birth_year", "ranking_excluded"):
        assert selection.stats[reason] == 1, reason


def test_a_placeholder_name_is_judged_against_the_id_being_queued():
    games, teams = control()
    supabase = build(
        games=[*games, sighting("ph-skip", "123"), sighting("ph-keep", "124")],
        teams=[
            *teams,
            team("ph-skip", "556", name="unknown_123"),
            team("ph-keep", "555", name="unknown_555"),
        ],
        aliases=[alias("ph-skip", "123"), alias("ph-keep", "124")],
    )

    selection = select(supabase)

    assert sorted(target_ids(selection)) == [CONTROL, "ph-keep"]
    assert selection.stats["placeholder_name"] == 1


def test_board_age_groups_match_the_ranking_config():
    from config.settings import AGE_GROUPS

    assert eof.BOARD_AGE_GROUPS == set(AGE_GROUPS)


def test_the_source_pattern_matches_the_team_page_url_the_scraper_writes():
    from src.scrapers.gotsport import GotSportScraper

    match = eof.SOURCE_ID_RE.match(f"{GotSportScraper.RANKINGS_BASE}/teams/123456/game-history")

    assert match is not None and match.group(1) == "123456"


WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "enqueue-opponent-frontier.yml")

# Imports the script with only the standard library, the repo's own packages and what the
# workflow's pip line installs (with everything those require) available. config stays
# refused: config.settings pulls in numpy. ModuleNotFoundError, because some libraries
# catch only that for an optional import.
_IMPORT_UNDER_THE_WORKFLOW_INSTALL = """
import importlib.abc, importlib.metadata as metadata, logging, re, sys
from packaging.requirements import Requirement

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

def installed_by(roots):
    seen, todo = set(), [(root, ()) for root in roots]
    while todo:
        name, extras = todo.pop()
        if (norm(name), extras) in seen:
            continue
        seen.add((norm(name), extras))
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for spec in requires:
            req = Requirement(spec)
            if req.marker is None or any(req.marker.evaluate({"extra": e}) for e in extras or ("",)):
                todo.append((req.name, tuple(sorted(req.extras))))
    return {name for name, _ in seen}

installed = installed_by(sys.argv[1:])
allowed = set(sys.stdlib_module_names) | {"scripts", "src"}
for module, owners in metadata.packages_distributions().items():
    if any(norm(owner) in installed for owner in owners):
        allowed.add(module)
allowed.discard("config")

class _NotInstalled(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] not in allowed:
            raise ModuleNotFoundError("not installed by the workflow: " + name, name=name)
        return None

sys.meta_path.insert(0, _NotInstalled())
import scripts.enqueue_opponent_frontier
print(logging.getLogger("httpx").level)
"""


def _workflow_install_packages():
    """The packages the workflow's `pip install ... -c requirements.lock` line names."""
    with open(WORKFLOW, encoding="utf-8") as f:
        for line in f:
            words = line.split()
            if words[:2] == ["pip", "install"] and "-c" in words:
                return words[2 : words.index("-c")]
    return []


@pytest.fixture(scope="module")
def workflow_install_import(tmp_path_factory):
    packages = _workflow_install_packages()
    assert packages, f"no 'pip install ... -c requirements.lock' line in {WORKFLOW}"
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_UNDER_THE_WORKFLOW_INSTALL, *packages],
        cwd=tmp_path_factory.mktemp("workflow-install"),
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_script_imports_with_only_what_the_workflow_installs(workflow_install_import):
    assert workflow_install_import.returncode == 0, workflow_install_import.stderr


def test_importing_the_script_keeps_httpx_request_lines_out_of_the_log(workflow_install_import):
    assert workflow_install_import.returncode == 0, workflow_install_import.stderr
    assert workflow_install_import.stdout.strip() == str(logging.WARNING)


# --------------------------------------------------------------------------- #
# Which GotSport id is queued
# --------------------------------------------------------------------------- #


def test_only_a_linked_numeric_gotsport_id_is_queued():
    malformed = {"i-letters": "12a4", "i-13-digits": "1234567890123", "i-full-width": "１２３", "i-newline": "123\n"}
    supabase = build(
        games=[
            sighting("i-own", "1101"),
            sighting("i-alias", "1103"),
            sighting("i-pending-alias", "1105"),
            sighting("i-unrelated", "1107"),
            sighting("i-tgs-alias", "1108"),
            sighting("i-12-digits", "123456789012"),
            *[sighting(t, gid) for t, gid in malformed.items()],
        ],
        teams=[
            team("i-own", "1101"),
            team("i-alias", "1102"),
            team("i-pending-alias", "1104"),
            team("i-unrelated", "1106"),
            team("i-tgs-alias", "1108", provider_id=TGS_ID),
            team("i-12-digits", "1109"),
            *[team(t, "1110") for t in malformed],
        ],
        aliases=[
            alias("i-alias", "1103"),
            alias("i-pending-alias", "1105", review_status="pending"),
            alias("i-tgs-alias", "1108", provider_id=TGS_ID),
            alias("i-12-digits", "123456789012"),
            *[alias(t, gid) for t, gid in malformed.items()],
        ],
    )

    selection = select(supabase)

    chosen = {t["team_id_master"]: t["provider_team_id"] for t in selection.targets}
    assert chosen == {"i-own": "1101", "i-alias": "1103", "i-12-digits": "123456789012"}
    assert selection.stats["id_not_linked"] == 3
    assert selection.stats["id_malformed"] == 4


def test_the_most_seen_registration_is_queued_and_the_earliest_sighting_orders_the_team():
    """p-a's own id is seen first (11-18) and last (11-21); its alias three times from 11-20.
    p-b, seen once on 11-19, wins if first_seen came from the chosen id or a last sighting."""
    supabase = build(
        games=[
            sighting("p-a", "1201", created_at="2026-11-18T10:00:00+00:00"),
            sighting("p-a", "1201", created_at="2026-11-21T10:00:00+00:00"),
            sighting("p-a", "1202", created_at="2026-11-20T10:00:00+00:00"),
            sighting("p-a", "1202", created_at="2026-11-22T10:00:00+00:00"),
            sighting("p-a", "1202", created_at="2026-11-22T11:00:00+00:00"),
            sighting("p-b", "1203", created_at="2026-11-19T10:00:00+00:00"),
        ],
        teams=[team("p-a", "1201"), team("p-b", "1203")],
        aliases=[alias("p-a", "1202")],
    )

    selection = select(supabase, limit=1)

    assert [(t["team_id_master"], t["provider_team_id"]) for t in selection.targets] == [("p-a", "1202")]
    assert selection.targets[0]["order_key"] == datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
    assert selection.stats["over_limit"] == 1


def test_equally_seen_registrations_go_to_the_smaller_string():
    supabase = build(
        games=[sighting("p-tie", "2002"), sighting("p-tie", "10010")],
        teams=[team("p-tie", "2002")],
        aliases=[alias("p-tie", "10010")],
    )

    selection = select(supabase)

    assert [t["provider_team_id"] for t in selection.targets] == ["10010"]


def test_targets_are_queued_oldest_sighting_first_up_to_the_limit():
    """Team ids sort the other way from sighting times, so an order by id fails here."""
    supabase = build(
        games=[
            sighting("o-a", "2001", created_at="2026-11-22T10:00:00+00:00"),
            sighting("o-c", "2003", created_at="2026-11-18T10:00:00+00:00"),
            sighting("o-b", "2002", created_at="2026-11-20T10:00:00+00:00"),
        ],
        teams=[team("o-a", "2001"), team("o-b", "2002"), team("o-c", "2003")],
    )

    selection = select(supabase, limit=2)

    assert target_ids(selection) == ["o-c", "o-b"]
    assert selection.stats["over_limit"] == 1


# --------------------------------------------------------------------------- #
# The fallback for a day with no never-scraped team
# --------------------------------------------------------------------------- #


def test_with_no_never_scraped_team_a_team_scraped_14_days_ago_is_requeued():
    supabase = build(
        games=[sighting("fb-15-days", "2001"), sighting("fb-13-days", "2002")],
        teams=[team("fb-15-days", "2001"), team("fb-13-days", "2002")],
        logs=[
            log("fb-15-days", "success", "2026-11-09T08:00:00+00:00"),
            log("fb-13-days", "success", "2026-11-11T09:00:00+00:00"),
        ],
    )

    selection = select(supabase)

    assert selection.list_name == "rescrape"
    assert [(t["team_id_master"], t["request_type"]) for t in selection.targets] == [
        ("fb-15-days", "opponent_frontier_rescrape")
    ]
    assert selection.stats["rescrape_too_recent"] == 1


def test_the_fallback_queues_the_longest_unscraped_team_first():
    supabase = build(
        games=[sighting("fb-16", "2001"), sighting("fb-20", "2002")],
        teams=[team("fb-16", "2001"), team("fb-20", "2002")],
        logs=[
            log("fb-16", "partial", "2026-11-08T10:00:00+00:00"),
            log("fb-20", "success", "2026-11-04T10:00:00+00:00"),
        ],
    )

    selection = select(supabase)

    assert target_ids(selection) == ["fb-20", "fb-16"]


def test_the_fallback_does_not_run_while_a_never_scraped_team_exists():
    supabase = build(
        games=[sighting("fb-new", "2001"), sighting("fb-15-days", "2002")],
        teams=[team("fb-new", "2001"), team("fb-15-days", "2002")],
        logs=[log("fb-15-days", "success", "2026-11-09T08:00:00+00:00")],
    )

    selection = select(supabase)

    assert selection.list_name == "primary"
    assert [(t["team_id_master"], t["request_type"]) for t in selection.targets] == [("fb-new", "opponent_frontier")]
    assert selection.stats["scraped_this_season"] == 1


def test_the_fallback_needs_a_sighting_saved_after_the_teams_last_scrape():
    supabase = build(
        games=[sighting("fb-old-sighting", "2001", created_at="2026-11-04T10:00:00+00:00", game_date="2026-11-03")],
        teams=[team("fb-old-sighting", "2001")],
        logs=[log("fb-old-sighting", "success", "2026-11-09T08:00:00+00:00")],
    )

    selection = select(supabase, window_days=30)

    assert selection.targets == []
    assert selection.stats["rescrape_no_new_sighting"] == 1


def test_the_fallback_queues_the_registration_seen_most_since_the_last_scrape():
    before = [f"2026-11-0{d}T10:00:00+00:00" for d in range(1, 6)] * 2
    supabase = build(
        games=[
            *[sighting("fb-ab", "1501", created_at=at, game_date="2026-11-01") for at in before[:9]],
            sighting("fb-ab", "1501", created_at="2026-11-20T10:00:00+00:00"),
            sighting("fb-ab", "1502", created_at="2026-11-21T10:00:00+00:00"),
            sighting("fb-ab", "1502", created_at="2026-11-22T10:00:00+00:00"),
        ],
        teams=[team("fb-ab", "1501")],
        aliases=[alias("fb-ab", "1502")],
        logs=[log("fb-ab", "success", "2026-11-09T08:00:00+00:00")],
    )

    selection = select(supabase, window_days=30)

    assert [t["provider_team_id"] for t in selection.targets] == ["1502"]


def test_a_day_whose_only_never_scraped_team_has_a_placeholder_name_runs_the_fallback():
    supabase = build(
        games=[sighting("fb-placeholder", "1601"), sighting("fb-15-days", "2001")],
        teams=[team("fb-placeholder", "1601", name="unknown_1601"), team("fb-15-days", "2001")],
        logs=[log("fb-15-days", "success", "2026-11-09T08:00:00+00:00")],
    )

    selection = select(supabase)

    assert selection.list_name == "rescrape"
    assert target_ids(selection) == ["fb-15-days"]
    assert selection.stats["placeholder_name"] == 1


@pytest.mark.parametrize(
    ("recent_owner", "old_owner"),
    [("fb-two", "fb-two"), ("fb-two-old", "fb-two"), ("fb-two", "fb-two-old")],
    ids=["same-id", "recent-under-predecessor", "old-under-predecessor"],
)
@pytest.mark.parametrize(("recent_id", "old_id"), [("l-1", "l-2"), ("l-2", "l-1")], ids=["recent-first", "old-first"])
def test_the_fallback_waits_on_the_teams_newest_scrape(recent_owner, old_owner, recent_id, old_id):
    """Read in either order, so a reader that kept the first row read, the last, or the
    oldest would see only the 20-day-old scrape in one of the cases and queue the team."""
    supabase = build(
        games=[sighting("fb-two", "2001"), sighting("fb-15-days", "2002")],
        teams=[team("fb-two", "2001"), team("fb-15-days", "2002")],
        merges=[merge("fb-two-old", "fb-two")],
        logs=[
            log(recent_owner, "partial", "2026-11-19T10:00:00+00:00", log_id=recent_id),
            log(old_owner, "success", "2026-11-04T10:00:00+00:00", log_id=old_id),
            log("fb-15-days", "success", "2026-11-09T08:00:00+00:00", log_id="l-3"),
        ],
    )

    selection = select(supabase)

    assert selection.list_name == "rescrape"
    assert target_ids(selection) == ["fb-15-days"]
    assert selection.stats["rescrape_too_recent"] == 1


def test_the_fallback_skips_a_placeholder_name_for_the_id_it_would_queue():
    """The name matches the alias the fallback would queue, not the team's own id."""
    supabase = build(
        games=[sighting("fb-placeholder", "2002")],
        teams=[team("fb-placeholder", "2001", name="unknown_2002")],
        aliases=[alias("fb-placeholder", "2002")],
        logs=[log("fb-placeholder", "success", "2026-11-09T08:00:00+00:00")],
    )

    selection = select(supabase)

    assert selection.list_name == "rescrape"
    assert selection.targets == []
    assert selection.stats["placeholder_name"] == 1


# --------------------------------------------------------------------------- #
# Paging
# --------------------------------------------------------------------------- #


@pytest.fixture
def two_row_pages(monkeypatch):
    monkeypatch.setattr(eof, "PAGE_SIZE", 2)
    monkeypatch.setattr(enqueue_helpers, "PAGE_SIZE", 2)


def test_the_games_read_reads_past_its_first_page(two_row_pages):
    """Four games against a three-row cap. Only g-a names o-3, and it falls outside the
    first three rows both in created_at order and in the order the double stores them."""
    supabase = build(
        games=[
            sighting("o-3", "2003", created_at="2026-11-20T10:00:00+00:00", game_id="g-a"),
            sighting("o-1", "2001", created_at="2026-11-18T10:00:00+00:00", game_id="g-d"),
            sighting("o-1", "2001", created_at="2026-11-18T11:00:00+00:00", game_id="g-c"),
            sighting("o-2", "2002", created_at="2026-11-19T10:00:00+00:00", game_id="g-b"),
        ],
        teams=[team("o-1", "2001"), team("o-2", "2002"), team("o-3", "2003")],
        max_rows=3,
    )

    selection = select(supabase)

    assert target_ids(selection) == ["o-1", "o-2", "o-3"]


def test_a_row_repeated_by_an_import_committing_mid_read_is_counted_once(two_row_pages):
    def insert_an_earlier_game_after_the_first_page(fake, table, rows):
        if table == "games" and rows and rows[0]["id"] == "g-1":
            fake.tables["games"].append(sighting("o-late", "2000", created_at="2026-11-18T09:00:00+00:00"))

    supabase = build(
        games=[
            sighting("o-1", "2001", created_at="2026-11-18T10:00:00+00:00", game_id="g-1"),
            sighting("o-2", "2002", created_at="2026-11-19T10:00:00+00:00", game_id="g-2"),
            sighting("o-3", "2003", created_at="2026-11-20T10:00:00+00:00", game_id="g-3"),
        ],
        teams=[team("o-1", "2001"), team("o-2", "2002"), team("o-3", "2003"), team("o-late", "2000")],
        max_rows=3,
        after_execute=insert_an_earlier_game_after_the_first_page,
    )

    selection = select(supabase)

    assert selection.raw_rows == 3
    assert selection.kept_rows == 3
    assert target_ids(selection) == ["o-1", "o-2", "o-3"]


def test_the_scrape_log_read_reads_past_its_first_page(two_row_pages):
    games, teams = control()
    supabase = build(
        games=[*games, sighting("x-scraped", "2001")],
        teams=[*teams, team("x-scraped", "2001")],
        # Five rows against a three-row cap; l-4 decides, outside the first three rows in
        # id order and in stored order alike.
        logs=[
            log("x-scraped", "success", "2026-11-01T10:00:00+00:00", log_id="l-4"),
            log("x-scraped", "error", "2026-10-01T10:00:00+00:00", log_id="l-1"),
            log("x-scraped", "error", "2026-10-02T10:00:00+00:00", log_id="l-2"),
            log("x-scraped", "error", "2026-10-03T10:00:00+00:00", log_id="l-3"),
            log("x-scraped", "error", "2026-10-04T10:00:00+00:00", log_id="l-5"),
        ],
        max_rows=3,
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]


def test_the_failed_request_read_reads_past_its_first_page(two_row_pages):
    games, teams = control()
    supabase = build(
        games=[*games, sighting("x-first", "2001"), sighting("x-second", "2002")],
        teams=[*teams, team("x-first", "2001"), team("x-second", "2002")],
        requests=[
            request("x-second", completed_at="2026-11-22T10:00:00+00:00", request_id="r-4"),
            request("x-first", completed_at="2026-11-21T10:00:00+00:00", request_id="r-1"),
            request("x-first", completed_at="2026-11-22T10:00:00+00:00", request_id="r-2"),
            request("x-first", completed_at="2026-11-23T10:00:00+00:00", request_id="r-3"),
            request("x-first", completed_at="2026-11-23T11:00:00+00:00", request_id="r-5"),
        ],
        max_rows=3,
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]


def test_the_ranking_exclusion_read_reads_past_its_first_page(two_row_pages):
    games, teams = control()
    supabase = build(
        games=[*games, sighting("z-excluded", "2001")],
        teams=[*teams, team("z-excluded", "2001")],
        exclusions=["z-excluded", "a-other-1", "a-other-2", "a-other-3", "a-other-4"],
        max_rows=3,
    )

    selection = select(supabase)

    assert target_ids(selection) == [CONTROL]
    assert selection.stats["ranking_excluded"] == 1


def test_each_100_id_batch_pages_from_its_own_start(two_row_pages):
    """The second batch's deciding rows carry lower ids than the first batch ended on,
    so a cursor carried over from the first batch would skip them."""
    names = [f"t-{i:03d}" for i in range(102)]
    supabase = build(
        games=[sighting(n, f"{3000 + i}") for i, n in enumerate(names)],
        teams=[team(n, f"{3000 + i}") for i, n in enumerate(names)],
        logs=[
            log("t-000", "error", "2026-10-01T10:00:00+00:00", log_id="l-8"),
            log("t-001", "error", "2026-10-01T10:00:00+00:00", log_id="l-9"),
            log("t-100", "success", "2026-11-01T10:00:00+00:00", log_id="l-1"),
        ],
        requests=[
            request("t-002", completed_at="2026-11-22T10:00:00+00:00", request_id="r-8"),
            request("t-003", completed_at="2026-11-22T10:00:00+00:00", request_id="r-9"),
            request("t-101", completed_at="2026-11-22T10:00:00+00:00", request_id="r-1"),
        ],
    )

    selection = select(supabase)

    queued = set(target_ids(selection))
    assert len(queued) == 98
    assert {"t-000", "t-001"} <= queued
    assert not {"t-002", "t-003", "t-100", "t-101"} & queued


# --------------------------------------------------------------------------- #
# main: read guards
# --------------------------------------------------------------------------- #


def many(count, **game_kwargs):
    names = [f"t-{i:03d}" for i in range(count)]
    return (
        [sighting(n, f"{4000 + i}", **game_kwargs) for i, n in enumerate(names)],
        [team(n, f"{4000 + i}") for i, n in enumerate(names)],
    )


@pytest.mark.parametrize("argv", [[], ["--dry-run"]], ids=["live", "dry-run"])
def test_no_games_read_fails_the_run(monkeypatch, caplog, argv):
    supabase = build()

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase, argv)

    assert status == 1
    assert supabase.rpc_calls == []
    assert "Stopped before selecting: no GotSport games read from the window" in caplog.text
    assert "ran the primary list" not in caplog.text


def test_a_window_holding_only_july_games_on_aug_1_queues_nothing_and_passes(monkeypatch):
    supabase = build(
        games=[sighting("o-july", "2001", created_at="2026-07-30T10:00:00+00:00", game_date="2026-07-29")],
        teams=[team("o-july", "2001")],
    )

    assert run_main(monkeypatch, supabase, now=datetime(2026, 8, 1, 8, 43, tzinfo=timezone.utc)) == 0
    assert supabase.rpc_calls == []
    assert [q["table"] for q in supabase.queries if q["table"] in ("teams", "team_ranking_exclusions")] == []


def test_99_candidates_with_no_scrape_log_rows_pass(monkeypatch):
    games, teams = many(99)
    supabase = build(games=games, teams=teams)

    assert run_main(monkeypatch, supabase) == 0
    assert len(supabase.rpc_calls) == 99


@pytest.mark.parametrize("argv", [[], ["--dry-run"]], ids=["live", "dry-run"])
def test_100_candidates_with_no_scrape_log_rows_fail_the_run(monkeypatch, caplog, argv):
    """An unscored game and a sighting with no team row make rows read (102), rows kept and
    teams sighted (101) and candidates (100) differ, so the message must name the right two.
    One candidate's id is unlinked: the guard counts candidates before any id check."""
    games, teams = many(100)
    teams[0]["provider_team_id"] = "unlinked-to-its-sighting"
    games += [sighting("o-unscored", "5001", home_score=None), sighting("o-no-row", "5002")]
    supabase = build(games=games, teams=teams)

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase, argv)

    assert status == 1
    assert supabase.rpc_calls == []
    assert "Stopped before selecting: 102 game rows and 100 candidates read, but no team_scrape_log rows" in caplog.text
    assert "ran the primary list" not in caplog.text


def test_100_candidates_whose_only_log_row_is_an_error_pass(monkeypatch):
    games, teams = many(100)
    supabase = build(games=games, teams=teams, logs=[log("t-000", "error", "2026-11-20T10:00:00+00:00")])

    assert run_main(monkeypatch, supabase) == 0
    assert len(supabase.rpc_calls) == 99


def test_early_august_with_only_july_log_rows_queues_the_never_scraped(monkeypatch):
    games, teams = many(100, created_at="2026-08-01T10:00:00+00:00", game_date="2026-08-01")
    supabase = build(games=games, teams=teams, logs=[log("t-000", "success", "2026-07-30T10:00:00+00:00")])

    status = run_main(monkeypatch, supabase, ["--limit", "5"], now=datetime(2026, 8, 2, 8, 43, tzinfo=timezone.utc))

    assert status == 0
    assert called_ids(supabase) == ["t-000", "t-001", "t-002", "t-003", "t-004"]


# --------------------------------------------------------------------------- #
# main: what is written, and the exit status
# --------------------------------------------------------------------------- #


def test_a_live_run_queues_each_target_with_these_exact_parameters(monkeypatch):
    supabase = build(games=[sighting("r-1", "1401")], teams=[team("r-1", "1401")])

    assert run_main(monkeypatch, supabase) == 0
    assert supabase.rpc_calls == [
        (
            "enqueue_scrape_request",
            {
                "p_team_id_master": "r-1",
                "p_team_name": "Team r-1",
                "p_provider_id": "prov-gotsport",
                "p_provider_team_id": "1401",
                "p_game_date": "2026-11-24",
                "p_request_type": "opponent_frontier",
                "p_priority": 2,
            },
        )
    ]


def test_a_team_already_waiting_in_the_queue_is_still_sent(monkeypatch):
    supabase = build(
        games=[sighting("q-waiting", "1401")],
        teams=[team("q-waiting", "1401")],
        requests=[request("q-waiting", status="pending", priority=4)],
    )

    assert run_main(monkeypatch, supabase) == 0
    assert called_ids(supabase) == ["q-waiting"]


def _two_targets(rpc_errors):
    return build(
        games=[
            sighting("a-first", "1401", created_at="2026-11-20T10:00:00+00:00"),
            sighting("b-second", "1402", created_at="2026-11-21T10:00:00+00:00"),
        ],
        teams=[team("a-first", "1401"), team("b-second", "1402")],
        rpc_errors=rpc_errors,
    )


def test_a_conflicting_waiting_request_is_counted_and_passes(monkeypatch, caplog):
    supabase = _two_targets({"a-first": {"code": "23505", "message": "request unchanged"}})

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase)

    assert status == 0
    assert "Writer: enqueued 1, already_queued 1, stuck_processing 0, failed 0." in caplog.text


def test_a_stuck_processing_row_fails_the_run_and_names_the_retire_script(monkeypatch, caplog):
    supabase = _two_targets({"a-first": {"code": "55000", "message": "Retire the stranded processing request"}})

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase)

    assert status == 1
    assert "Writer: enqueued 1, already_queued 0, stuck_processing 1, failed 0." in caplog.text
    assert "scripts/retire_stranded_scrape_requests.py" in caplog.text


def test_an_unreadable_rpc_response_is_reported_as_an_unknown_outcome(monkeypatch, caplog):
    """postgrest-py raises an int-coded APIError for a body it cannot read, such as a
    gateway's 502 page, and the call may have committed before it."""
    supabase = _two_targets({"a-first": {"code": 502, "message": "JSON could not be generated"}})

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase)

    assert status == 1
    assert "Enqueue outcome unknown: APIError 502" in caplog.text
    assert "Enqueue refused" not in caplog.text
    assert "Writer: enqueued 1, already_queued 0, stuck_processing 0, failed 1." in caplog.text


def test_a_refused_rpc_call_is_reported_as_refused(monkeypatch, caplog):
    supabase = _two_targets({"a-first": {"code": "22023", "message": "Incomplete scrape request"}})

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase)

    assert status == 1
    assert "Enqueue refused: APIError 22023" in caplog.text


def test_an_unexpected_error_fails_the_run_after_trying_every_target(monkeypatch, caplog):
    """A dropped connection or timeout can follow a committed call, so it is an unknown outcome."""
    supabase = _two_targets({"a-first": RuntimeError("connection reset")})

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase)

    assert status == 1
    assert called_ids(supabase) == ["a-first", "b-second"]
    assert "Enqueue outcome unknown: RuntimeError" in caplog.text
    assert "Writer: enqueued 1, already_queued 0, stuck_processing 0, failed 1." in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        {"code": "23503", "message": "Team 7654321", "details": "Harbor City Comets 7654321", "hint": None},
        {"code": 502, "message": "Harbor City Comets", "details": "b'<html>7654321</html>'", "hint": None},
        RuntimeError("Harbor City Comets 7654321"),
    ],
    ids=["refused", "unreadable", "transport"],
)
def test_a_failed_live_call_in_actions_prints_no_gotsport_id_or_team_name(monkeypatch, caplog, capsys, error):
    supabase = build(
        games=[sighting("o-public", "7654321")],
        teams=[team("o-public", "7654321", name="Harbor City Comets")],
        rpc_errors={"o-public": error},
    )

    with caplog.at_level("INFO"):
        status = run_main(monkeypatch, supabase, env={"GITHUB_ACTIONS": "true"})
    out, err = capsys.readouterr()

    assert status == 1
    for text in (caplog.text, out, err):
        assert "7654321" not in text
        assert "Harbor City Comets" not in text


def test_the_writer_carries_its_own_dry_run_guard():
    supabase = build()
    target = {
        "team_id_master": "r-1",
        "team_name": "Team r-1",
        "provider_team_id": "1401",
        "request_type": "opponent_frontier",
        "order_key": NOW,
    }

    assert eof.enqueue_team(supabase, target, GOTSPORT_ID, "2026-11-24", dry_run=True) == "would_enqueue"
    assert supabase.rpc_calls == []
    assert eof.enqueue_team(supabase, target, GOTSPORT_ID, "2026-11-24", dry_run=False) == "enqueued"
    assert len(supabase.rpc_calls) == 1


@pytest.mark.parametrize(
    ("logs", "list_name"),
    [
        ([], "primary"),
        (
            [log("o-1", "success", "2026-11-01T10:00:00+00:00"), log("o-2", "success", "2026-11-02T10:00:00+00:00")],
            "rescrape",
        ),
    ],
    ids=["primary", "rescrape"],
)
def test_a_dry_run_sends_every_target_through_the_guarded_writer_and_writes_nothing(
    monkeypatch, tmp_path, caplog, logs, list_name
):
    supabase = build(
        games=[
            sighting("o-1", "2001", created_at="2026-11-20T10:00:00+00:00"),
            sighting("o-2", "2002", created_at="2026-11-21T10:00:00+00:00"),
        ],
        teams=[team("o-1", "2001"), team("o-2", "2002")],
        logs=logs,
    )
    seen = []
    real_enqueue_team = eof.enqueue_team

    def spy(supabase, target, provider_id, today_iso, dry_run):
        seen.append((target["team_id_master"], dry_run))
        return real_enqueue_team(supabase, target, provider_id, today_iso, dry_run)

    monkeypatch.setattr(eof, "enqueue_team", spy)
    monkeypatch.chdir(tmp_path)

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase, ["--dry-run"])

    assert status == 0
    assert seen == [("o-1", True), ("o-2", True)]
    assert supabase.rpc_calls == []
    assert os.listdir(tmp_path) == []
    assert f"Opponent frontier ran the {list_name} list: 2 targets." in caplog.text
    assert (
        "Candidates: 2 = 2 targets + recent_error 0, id_not_linked 0, id_malformed 0, placeholder_name 0, "
        "scraped_this_season 0, rescrape_too_recent 0, rescrape_no_new_sighting 0, over_limit 0. "
        "Writer: would_enqueue 2."
    ) in caplog.text


def _public_output_fixture():
    return build(
        games=[sighting("o-public", "7654321")],
        teams=[team("o-public", "7654321", name="Harbor City Comets")],
    )


def test_a_dry_run_in_actions_prints_no_gotsport_id_or_team_name(monkeypatch, caplog, capsys):
    with caplog.at_level("INFO"):
        status = run_main(monkeypatch, _public_output_fixture(), ["--dry-run"], env={"GITHUB_ACTIONS": "true"})
    out, err = capsys.readouterr()

    assert status == 0
    for text in (caplog.text, out, err):
        assert "7654321" not in text
        assert "Harbor City Comets" not in text


def test_a_local_dry_run_previews_the_gotsport_id_and_team_name(monkeypatch, caplog):
    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, _public_output_fixture(), ["--dry-run"])

    assert status == 0
    assert "WOULD ENQUEUE: 7654321 (Harbor City Comets) as opponent_frontier" in caplog.text


@pytest.mark.parametrize("argv", [[], ["--dry-run"]], ids=["live", "dry-run"])
def test_the_anon_key_is_refused_before_a_client_is_built(monkeypatch, argv):
    clients = []
    games, teams = control()
    supabase = build(games=games, teams=teams)

    def create_client(url, key):
        clients.append(key)
        return supabase

    monkeypatch.setattr(eof, "create_client", create_client)
    monkeypatch.setattr(eof, "datetime", _frozen(NOW))
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "anon-key")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["enqueue_opponent_frontier.py", *argv])

    with pytest.raises(SystemExit) as exit_info:
        eof.main()

    assert exit_info.value.code == 1
    assert clients == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--limit", "0"],
        ["--limit", "5001"],
        ["--window-days", "0"],
        ["--window-days", "31"],
        ["--rescrape-after-days", "0"],
        ["--rescrape-after-days", "91"],
    ],
)
def test_an_out_of_range_argument_is_refused(monkeypatch, argv):
    supabase = build()

    assert run_main(monkeypatch, supabase, argv) == 2
    assert supabase.queries == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--limit", "1"],
        ["--limit", "5000"],
        ["--window-days", "1"],
        ["--window-days", "30"],
        ["--rescrape-after-days", "1"],
        ["--rescrape-after-days", "90"],
    ],
)
def test_an_argument_at_either_bound_is_accepted(monkeypatch, argv):
    games, teams = control()
    supabase = build(games=games, teams=teams)

    assert run_main(monkeypatch, supabase, ["--dry-run", *argv]) == 0


def test_the_rescrape_wait_flag_reaches_the_selection(monkeypatch):
    supabase = build(
        games=[sighting("fb-15-days", "2001")],
        teams=[team("fb-15-days", "2001")],
        logs=[log("fb-15-days", "success", "2026-11-09T08:00:00+00:00")],
    )

    assert run_main(monkeypatch, supabase, ["--rescrape-after-days", "20"]) == 0
    assert supabase.rpc_calls == []


def test_the_window_flag_reaches_the_games_read(monkeypatch):
    supabase = build(
        games=[sighting("o-14-days", "2001", created_at="2026-11-10T10:00:00+00:00", game_date="2026-11-09")],
        teams=[team("o-14-days", "2001")],
    )

    assert run_main(monkeypatch, supabase, ["--window-days", "20"]) == 0
    assert called_ids(supabase) == ["o-14-days"]


def test_the_summary_counts_reconcile_stage_by_stage(monkeypatch, caplog):
    supabase = build(
        games=[
            sighting("c-1", "2001", created_at="2026-11-20T10:00:00+00:00"),
            game(None, "2002", "c-2", "2003", created_at="2026-11-21T10:00:00+00:00"),
            sighting("c-3", "2004", created_at="2026-11-22T10:00:00+00:00"),
            sighting("c-unscored", "2005", home_score=None),
            game("m-old", "5000", "m-team", "5001"),
        ],
        teams=[team("c-1", "2001"), team("c-2", "2003"), team("c-3", "2004")],
        merges=[merge("m-old", "m-team")],
    )

    with caplog.at_level("INFO", logger=eof.logger.name):
        status = run_main(monkeypatch, supabase, ["--limit", "2"])

    assert status == 0
    assert (
        "Opponent frontier ran the primary list: 2 targets. "
        "Game rows: 5 read = 3 kept (1 with no source team) + home_score_null 1, away_score_null 0, "
        "excluded_game 0, before_season 0, after_today 0, source_matches_neither 0, source_matches_both 0, "
        "opponent_master_null 0, opponent_id_blank 0, self_game 1. "
        "Teams: 3 sighted = 3 candidates + no_team_row 0, deprecated 0, not_on_board 0, excluded_birth_year 0, "
        "ranking_excluded 0. "
        "Candidates: 3 = 2 targets + recent_error 0, id_not_linked 0, id_malformed 0, placeholder_name 0, "
        "scraped_this_season 0, rescrape_too_recent 0, rescrape_no_new_sighting 0, over_limit 1. "
        "Writer: enqueued 2, already_queued 0, stuck_processing 0, failed 0."
    ) in caplog.text
    assert called_ids(supabase) == ["c-1", "c-2"]


# --------------------------------------------------------------------------- #
# Season bounds
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("today", [date(2026, 11, 24), date(2027, 7, 15), date(2026, 8, 1)])
def test_the_season_starts_on_aug_1_of_its_own_year(today):
    assert eof.season_start_date(today) == date(2026, 8, 1)
    assert eof.season_start_instant(today) == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_constants_pin_the_tier_and_tags():
    assert eof.PRIORITY_OPPONENT_FRONTIER == 2
    assert eof.REQUEST_TYPE == "opponent_frontier"
    assert eof.RESCRAPE_REQUEST_TYPE == "opponent_frontier_rescrape"
    assert eof.DEFAULT_LIMIT == 1000
