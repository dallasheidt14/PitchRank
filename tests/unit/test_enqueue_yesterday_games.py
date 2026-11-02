"""Tests for the daily yesterday-game enqueue.

The Supabase double evaluates its filters, and is strict in ways this job needs:

  - every table has a fixed column list, so selecting or filtering on a column
    the real table lacks raises at build time, even against an empty table,
  - is_() matches only a real NULL in a known column,
  - in_() refuses more than 100 values, the URI-length limit the callers batch for,
  - a limit() or range() page refuses to run without order(), since paging by id
    depends on the rows coming back sorted,
  - an RPC's params go through json.dumps before the call is recorded, so a value
    httpx cannot serialize (a date object) fails here as it does in production.

Dates are seeded as ISO strings because PostgREST returns them that way.

Guard tests seed the guarded side with the lower team id. The cover breaks ties on
the lower id, so with the guard removed that side would win, and the test fails.
"""

import json
import os
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import enqueue_helpers  # noqa: E402
from scripts import enqueue_yesterday_games as eyg  # noqa: E402

GOTSPORT_ID = "prov-gotsport"
OTHER_PROVIDER_ID = "prov-tgs"

TODAY = date(2026, 11, 2)
YESTERDAY = date(2026, 11, 1)
YESTERDAY_ISO = "2026-11-01"

TABLE_COLUMNS = {
    "providers": ("id", "code"),
    "games": (
        "id",
        "game_date",
        "provider_id",
        "home_team_master_id",
        "away_team_master_id",
        "home_provider_id",
        "away_provider_id",
        "home_score",
        "away_score",
        "is_excluded",
    ),
    "teams": (
        "team_id_master",
        "team_name",
        "provider_id",
        "provider_team_id",
        "is_deprecated",
        "last_scraped_at",
        "scrape_attempts",
        "last_played_at",
    ),
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
    def __init__(self, name, rows, after_execute=None):
        self.name = name
        self._rows = rows
        self._known = TABLE_COLUMNS[name]
        self._after_execute = after_execute
        self._filters = []
        self._columns = None
        self._order = None
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

    def eq(self, column, value):
        self._check(column)
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._check(column)
        values = list(values)
        if len(values) > 100:
            raise AssertionError(f"{self.name}: in_() with {len(values)} values breaks the URI length limit")
        self._filters.append(("in", column, values))
        return self

    def gt(self, column, value):
        self._check(column)
        self._filters.append(("gt", column, value))
        return self

    def limit(self, count):
        self._limit = count
        return self

    def is_(self, column, value):
        self._check(column)
        if value != "null":
            raise AssertionError(f"{self.name}: is_() supports only 'null', got {value!r}")
        self._filters.append(("is_null", column, None))
        return self

    def order(self, column, *, desc=False):
        self._check(column)
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
                if kind == "eq" and row[column] != value:
                    keep = False
                elif kind == "in" and row[column] not in value:
                    keep = False
                elif kind == "is_null" and row[column] is not None:
                    keep = False
                elif kind == "gt" and not row[column] > value:
                    keep = False
            if keep:
                rows.append(row)
        return rows

    def _project(self, rows):
        if self._columns is None:
            return [dict(r) for r in rows]
        return [{c: r[c] for c in self._columns} for r in rows]

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if (self._range is not None or self._limit is not None) and self._order is None:
            raise AssertionError(f"{self.name}: a page without order() reads the table unstably")
        rows = self._matching()
        if self._order is not None:
            rows = sorted(rows, key=lambda r: r[self._order[0]], reverse=self._order[1])
        if self._range is not None:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        rows = self._project(rows)
        if self._after_execute is not None:
            self._after_execute(self.name, rows)
        if self._single:
            if not rows:
                raise RuntimeError("PGRST116: JSON object requested, multiple (or no) rows returned")
            return _Result(rows[0])
        return _Result(rows)


class _RpcBuilder:
    """Records the call at execute(), after serializing it the way httpx does."""

    def __init__(self, parent, name, params):
        self._parent = parent
        self._name = name
        self._params = params

    def execute(self):
        json.dumps(self._params)
        if self._params.get("p_team_id_master") in self._parent.rpc_failures:
            raise RuntimeError("simulated PostgREST failure")
        self._parent.rpc_calls.append((self._name, self._params))
        return _Result(None)


class FakeSupabase:
    def __init__(self, tables, rpc_failures=frozenset(), after_execute=None):
        for name, rows in tables.items():
            for row in rows:
                assert set(row) == set(TABLE_COLUMNS[name]), f"{name} fixture row has the wrong columns"
        self._tables = tables
        self.rpc_calls = []
        self.rpc_failures = rpc_failures
        self._after_execute = after_execute

    def table(self, name):
        if name not in self._tables:
            raise AssertionError(f"query against unseeded table {name!r}")
        return _Table(name, self._tables[name], self._after_execute)

    def rpc(self, name, params):
        return _RpcBuilder(self, name, params)


_GS = object()


def game(
    home,
    away,
    *,
    game_date=YESTERDAY_ISO,
    provider_id=GOTSPORT_ID,
    home_pid=_GS,
    away_pid=_GS,
    home_score=None,
    away_score=None,
    game_id=None,
):
    return {
        "id": game_id or f"g-{home}-{away}-{game_date}-{provider_id}-{home_score}-{away_score}",
        "game_date": game_date,
        "provider_id": provider_id,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_provider_id": f"gs-{home}" if home_pid is _GS else home_pid,
        "away_provider_id": f"gs-{away}" if away_pid is _GS else away_pid,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": False,
    }


def team(
    team_id,
    *,
    deprecated=False,
    last_scraped_at=None,
    provider_team_id=None,
    scrape_attempts=0,
    last_played_at=None,
):
    return {
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "provider_id": GOTSPORT_ID,
        "provider_team_id": provider_team_id or f"gs-{team_id}",
        "is_deprecated": deprecated,
        "last_scraped_at": last_scraped_at,
        "scrape_attempts": scrape_attempts,
        "last_played_at": last_played_at,
    }


def request(
    team_id,
    *,
    status="pending",
    provider_id=GOTSPORT_ID,
    provider_team_id=None,
    game_date=YESTERDAY_ISO,
    requested_at="2026-11-01T12:00:00+00:00",
    row_id=None,
):
    return {
        "id": row_id or f"r-{team_id}-{status}-{game_date}",
        "team_id_master": team_id,
        "status": status,
        "priority": 3,
        "request_type": "discovery",
        "provider_id": provider_id,
        "provider_team_id": provider_team_id or f"gs-{team_id}",
        "game_date": game_date,
        "requested_at": requested_at,
    }


def merge(old, canonical):
    return {"deprecated_team_id": old, "canonical_team_id": canonical}


def build_supabase(games, teams, merges=(), scrape_requests=(), rpc_failures=frozenset(), after_execute=None):
    return FakeSupabase(
        {
            "providers": [{"id": GOTSPORT_ID, "code": "gotsport"}],
            "games": list(games),
            "teams": list(teams),
            "team_merge_map": list(merges),
            "scrape_requests": list(scrape_requests),
        },
        rpc_failures=rpc_failures,
        after_execute=after_execute,
    )


def select(supabase):
    return eyg.find_teams_to_enqueue(supabase, GOTSPORT_ID, YESTERDAY, TODAY)


def picked_ids(picks):
    return [p["team_id_master"] for p in picks]


def guarded_game(team_overrides=None, scrape_requests=()):
    """One game between a guarded side (the tie-break winner) and its opponent."""
    return build_supabase(
        games=[game("a-g", "z-o")],
        teams=[team("a-g", **(team_overrides or {})), team("z-o")],
        scrape_requests=scrape_requests,
    )


def test_constants_pin_the_tier_and_tag():
    assert eyg.PRIORITY_YESTERDAY_GAME == 2
    assert eyg.REQUEST_TYPE == "yesterday_game"


# --------------------------------------------------------------------------- #
# pick_cover
# --------------------------------------------------------------------------- #

A, B, C, X, Y, Z = (("a", "1"), ("b", "1"), ("c", "1"), ("x", "1"), ("y", "1"), ("z", "1"))
A1, A2 = ("a", "1"), ("a", "2")


def test_one_game_picks_one_team():
    assert eyg.pick_cover([{A, B}]) == ([A], 0, 0)


def test_a_hub_team_covers_its_games_alone():
    hub = ("z-hub", "1")
    assert eyg.pick_cover([{hub, A}, {hub, B}, {hub, C}]) == ([hub], 0, 0)


def test_a_chain_is_covered_by_its_middle():
    assert eyg.pick_cover([{A, B}, {B, C}]) == ([B], 0, 0)


def test_a_blocked_sibling_registration_leaves_its_game_to_the_opponent():
    assert eyg.pick_cover([{A1, Z}, {A1, X}, {A2, Y}]) == ([A1, Y], 0, 0)


def test_a_game_with_a_single_candidate_is_settled_before_the_greedy_pass():
    """Greedy-first would pick A1 for its two games, block A2, and strand the third."""
    assert eyg.pick_cover([{A1, B}, {A1, C}, {A2}]) == ([A2, B, C], 0, 0)


def test_a_forced_pick_covers_its_other_games_too():
    assert eyg.pick_cover([{X}, {X, Y}]) == ([X], 0, 0)


def test_a_game_whose_sides_resolve_to_one_unit_needs_one_pick():
    assert eyg.pick_cover([{A}]) == ([A], 0, 0)


def test_a_game_with_no_eligible_side_is_counted():
    assert eyg.pick_cover([set(), {A, B}]) == ([A], 1, 0)


def test_a_game_whose_only_side_is_a_blocked_sibling_is_counted():
    assert eyg.pick_cover([{A1}, {A2}]) == ([A1], 0, 1)


def test_a_tie_goes_to_the_lower_team_id():
    assert eyg.pick_cover([{("b", "1"), ("a", "1")}]) == ([("a", "1")], 0, 0)


def test_a_stale_count_is_rechecked_before_a_unit_is_taken():
    """After D is taken, B still sits in the heap at its old count of 2 but now covers
    one game, so C (still 2) must win instead of B being taken on a stale count."""
    D, E, F, G = ("d", "1"), ("e", "1"), ("f", "1"), ("g", "1")
    assert eyg.pick_cover([{B, C}, {C, E}, {B, D}, {D, F}, {D, G}]) == ([C, D], 0, 0)


# --------------------------------------------------------------------------- #
# find_teams_to_enqueue: what is read
# --------------------------------------------------------------------------- #


def test_only_yesterdays_unscored_gotsport_games_are_read():
    supabase = build_supabase(
        games=[
            game("m-keep", "z-keep"),
            game("a-scored", "z-scored", home_score=2),
            game("a-other-day", "z-other-day", game_date="2026-10-31"),
            game("a-other-provider", "z-other-provider", provider_id=OTHER_PROVIDER_ID),
        ],
        teams=[
            team(t)
            for t in (
                "m-keep",
                "z-keep",
                "a-scored",
                "z-scored",
                "a-other-day",
                "z-other-day",
                "a-other-provider",
                "z-other-provider",
            )
        ],
    )

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["m-keep"]
    assert stats["games"] == 1


def test_only_the_home_score_decides_whether_a_game_is_unscored():
    supabase = build_supabase(
        games=[
            game("a-home-null", "z-1", home_score=None, away_score=1),
            game("a-away-null", "z-2", home_score=1, away_score=None),
        ],
        teams=[team(t) for t in ("a-home-null", "z-1", "a-away-null", "z-2")],
    )

    picks, _ = select(supabase)

    assert picked_ids(picks) == ["a-home-null"]


def test_a_score_landing_mid_read_does_not_hide_a_later_game(monkeypatch):
    """Scores fill while the read runs. Each one shrinks the unscored set, so an
    offset would skip past an unread game; paging by id does not. Both page sizes
    are shrunk so the test reads in pages whichever pager the script uses."""
    monkeypatch.setattr(eyg, "PAGE_SIZE", 2)
    monkeypatch.setattr(enqueue_helpers, "PAGE_SIZE", 2)
    # Stored out of id order, so a page that is not sorted by id comes back wrong.
    games = [game(f"a-{i}", None, game_id=f"g-{i}") for i in (0, 3, 1, 2, 4)]
    first_game = next(g for g in games if g["id"] == "g-0")

    def score_the_first_game_after_page_one(table, rows):
        if table == "games" and rows and rows[0]["id"] == "g-0":
            first_game["home_score"] = 1

    supabase = build_supabase(
        games=games,
        teams=[team(f"a-{i}") for i in range(5)],
        after_execute=score_the_first_game_after_page_one,
    )

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["a-0", "a-1", "a-2", "a-3", "a-4"]
    assert stats["games"] == 5


def test_every_batch_of_teams_and_queue_rows_is_read():
    """101 teams cross the 100-id batch, and the last one's conflicting row sits in
    the second batch."""
    ids = [f"t-{i:03d}" for i in range(101)]
    supabase = build_supabase(
        games=[game(t, None) for t in ids],
        teams=[team(t) for t in ids],
        scrape_requests=[request("t-100", status="processing")],
    )

    picks, stats = select(supabase)

    assert picked_ids(picks) == ids[:100]
    assert stats["active_request_conflict"] == 1


def test_merged_ids_are_found_in_every_batch_of_survivors():
    """t-000 sits in the first 100-survivor batch and t-100 in the second; each has a
    conflicting row filed under a merged-away id that no game names."""
    ids = [f"t-{i:03d}" for i in range(101)]
    supabase = build_supabase(
        games=[game(t, None) for t in ids],
        teams=[team(t) for t in ids],
        merges=[merge("u-old", "t-000"), merge("v-old", "t-100")],
        scrape_requests=[request("u-old", status="processing"), request("v-old", status="processing")],
    )

    picks, stats = select(supabase)

    assert picked_ids(picks) == ids[1:100]
    assert stats["active_request_conflict"] == 2


def test_a_merged_side_is_queued_as_its_survivor_with_the_games_registration():
    supabase = build_supabase(
        games=[game("a-old", "z-o", home_pid="gs-registration-on-the-game")],
        teams=[team("b-canon", provider_team_id="gs-registration-on-the-team"), team("z-o")],
        merges=[merge("a-old", "b-canon")],
    )

    picks, _ = select(supabase)

    assert picks == [
        {
            "team_id_master": "b-canon",
            "team_name": "Team b-canon",
            "provider_team_id": "gs-registration-on-the-game",
            "enqueue": True,
        }
    ]


# --------------------------------------------------------------------------- #
# find_teams_to_enqueue: an unscrapeable side leaves the game to its opponent
# --------------------------------------------------------------------------- #


def test_a_side_with_no_master_id_leaves_the_game_to_the_opponent():
    supabase = build_supabase(games=[game(None, "z-o")], teams=[team("z-o")])

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["z-o"]
    assert stats["no_master"] == 1


@pytest.mark.parametrize("placeholder", [None, "None", "", " null "])
def test_a_side_with_a_placeholder_provider_id_leaves_the_game_to_the_opponent(placeholder):
    supabase = build_supabase(games=[game("a-g", "z-o", home_pid=placeholder)], teams=[team("a-g"), team("z-o")])

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["z-o"]
    assert stats["blank_provider_id"] == 1


def test_a_side_with_no_team_row_leaves_the_game_to_the_opponent():
    supabase = build_supabase(games=[game("a-g", "z-o")], teams=[team("z-o")])

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["z-o"]
    assert stats["missing_team"] == 1


def test_a_deprecated_side_leaves_the_game_to_the_opponent():
    picks, stats = select(guarded_game({"deprecated": True}))

    assert picked_ids(picks) == ["z-o"]
    assert stats["deprecated"] == 1


def test_a_null_deprecation_flag_counts_as_deprecated_as_the_sql_selectors_read_it():
    picks, stats = select(guarded_game({"deprecated": None}))

    assert picked_ids(picks) == ["z-o"]
    assert stats["deprecated"] == 1
    assert stats["old_rule_teams"] == 1


def test_a_side_scraped_today_leaves_the_game_to_the_opponent():
    picks, stats = select(guarded_game({"last_scraped_at": "2026-11-02T03:00:00+00:00"}))

    assert picked_ids(picks) == ["z-o"]
    assert stats["scraped_today"] == 1


def test_scraped_late_yesterday_is_eligible_and_early_today_is_not():
    supabase = build_supabase(
        games=[game("a-late", "z-o1"), game("a-early", "z-o2")],
        teams=[
            team("a-late", last_scraped_at="2026-11-01T23:30:00+00:00"),
            team("a-early", last_scraped_at="2026-11-02T00:30:00+00:00"),
            team("z-o1"),
            team("z-o2"),
        ],
    )

    picks, _ = select(supabase)

    assert picked_ids(picks) == ["a-late", "z-o2"]


def test_a_dormant_looking_team_is_still_queued():
    """This job is how a team that starts playing again gets scraped, so it must
    carry no activity filter (the SQL selectors' revival rule)."""
    dormant = team(
        "a-dormant",
        scrape_attempts=50,
        last_played_at="2025-01-01",
        last_scraped_at="2026-10-01T00:00:00+00:00",
    )
    supabase = build_supabase(games=[game("a-dormant", "z-o")], teams=[dormant, team("z-o")])

    picks, _ = select(supabase)

    assert picked_ids(picks) == ["a-dormant"]


def test_a_game_with_neither_side_scrapeable_is_counted_and_queues_nothing():
    supabase = build_supabase(games=[game("a-g", "z-o")], teams=[])

    picks, stats = select(supabase)

    assert picks == []
    assert stats["uncovered_no_side"] == 1


# --------------------------------------------------------------------------- #
# find_teams_to_enqueue: an active queue row the RPC would refuse
# --------------------------------------------------------------------------- #


def test_a_processing_row_leaves_the_game_to_the_opponent():
    picks, stats = select(guarded_game(scrape_requests=[request("a-g", status="processing")]))

    assert picked_ids(picks) == ["z-o"]
    assert stats["active_request_conflict"] == 1


def test_a_pending_row_for_another_registration_leaves_the_game_to_the_opponent():
    picks, _ = select(guarded_game(scrape_requests=[request("a-g", provider_team_id="gs-other-registration")]))

    assert picked_ids(picks) == ["z-o"]


def test_a_pending_row_under_another_provider_leaves_the_game_to_the_opponent():
    """A producer that queues under the team row's own provider leaves such a row.
    Without the provider check it would read as already queued and nobody would be."""
    row = request("a-g", provider_id=OTHER_PROVIDER_ID, game_date="2026-11-02")

    picks, _ = select(guarded_game(scrape_requests=[row]))

    assert picked_ids(picks) == ["z-o"]


def test_a_pending_row_outside_the_ninety_day_window_leaves_the_game_to_the_opponent():
    picks, _ = select(guarded_game(scrape_requests=[request("a-g", game_date="2026-07-01")]))

    assert picked_ids(picks) == ["z-o"]


def test_a_finished_row_is_not_an_active_request():
    finished = request("a-g", status="completed", provider_team_id="gs-other-registration")

    picks, stats = select(guarded_game(scrape_requests=[finished]))

    assert [(p["team_id_master"], p["enqueue"]) for p in picks] == [("a-g", True)]
    assert stats["active_request_conflict"] == 0


def test_a_conflicting_row_under_the_raw_pre_merge_id_is_seen():
    supabase = build_supabase(
        games=[game("a-old", "z-o")],
        teams=[team("b-canon"), team("z-o")],
        merges=[merge("a-old", "b-canon")],
        scrape_requests=[request("a-old", provider_team_id="gs-other-registration")],
    )

    picks, _ = select(supabase)

    assert picked_ids(picks) == ["z-o"]


def test_a_conflicting_row_under_a_merged_id_no_game_names_is_seen():
    """enqueue_scrape_request matches a row under any id merged into the survivor,
    not only ids that appear on yesterday's games."""
    supabase = build_supabase(
        games=[game("a-canon", "z-o")],
        teams=[team("a-canon"), team("z-o")],
        merges=[merge("b-old-dup", "a-canon")],
        scrape_requests=[request("b-old-dup", provider_team_id="gs-other-registration")],
    )

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["z-o"]
    assert stats["active_request_conflict"] == 1


@pytest.mark.parametrize("row_owner", ["b-canon", "c-old"], ids=["survivor", "sibling-merged-id"])
def test_a_game_naming_a_merged_id_sees_rows_under_the_survivor_and_its_siblings(row_owner):
    """Games keep the pre-merge id, so the side arrives as a-old. A conflicting row may
    sit under the survivor itself or under another id merged into it."""
    supabase = build_supabase(
        games=[game("a-old", "z-o")],
        teams=[team("b-canon"), team("z-o")],
        merges=[merge("a-old", "b-canon"), merge("c-old", "b-canon")],
        scrape_requests=[request(row_owner, status="processing")],
    )

    picks, stats = select(supabase)

    assert picked_ids(picks) == ["z-o"]
    assert stats["active_request_conflict"] == 1


@pytest.mark.parametrize(
    "incompatible",
    [
        {"provider_team_id": "gs-other-registration"},
        {"provider_team_id": "gs-a-g", "provider_id": OTHER_PROVIDER_ID},
        {"provider_team_id": "gs-a-g", "game_date": "2026-07-01"},
        {"provider_team_id": "gs-a-g", "game_date": "2026-11-02"},
    ],
    ids=["registration", "provider", "window", "later-date"],
)
def test_a_compatible_pending_row_is_chosen_over_an_older_incompatible_one(incompatible):
    """The RPC orders compatible rows first, so an older stranded processing row that
    is incompatible in any one way does not stop a newer compatible row being reused."""
    supabase = build_supabase(
        games=[game("a-g", "z-o")],
        teams=[team("a-g"), team("z-o")],
        merges=[merge("b-old", "a-g")],
        scrape_requests=[
            request("b-old", status="processing", requested_at="2026-10-01T00:00:00+00:00", **incompatible),
            request("a-g", requested_at="2026-11-01T12:00:00+00:00"),
        ],
    )

    picks, _ = select(supabase)

    assert [(p["team_id_master"], p["enqueue"]) for p in picks] == [("a-g", True)]


def test_rows_tied_on_compatibility_and_time_fall_to_the_lower_id():
    """The RPC's last sort key is the row id. Here the lower id is a processing row,
    which the job treats as a conflict, so the opponent covers the game."""
    supabase = build_supabase(
        games=[game("a-g", "z-o")],
        teams=[team("a-g"), team("z-o")],
        merges=[merge("b-old", "a-g")],
        scrape_requests=[
            request("a-g", row_id="r-2-pending"),
            request("b-old", status="processing", provider_team_id="gs-a-g", row_id="r-1-processing"),
        ],
    )

    picks, _ = select(supabase)

    assert picked_ids(picks) == ["z-o"]


@pytest.mark.parametrize(
    ("row_date", "expected"),
    [("2026-08-03", [("a-g", True)]), ("2026-08-02", [("z-o", True)])],
)
def test_the_ninety_day_window_is_inclusive(row_date, expected):
    picks, _ = select(guarded_game(scrape_requests=[request("a-g", game_date=row_date)]))

    assert [(p["team_id_master"], p["enqueue"]) for p in picks] == expected


def test_a_compatible_pending_row_dated_yesterday_is_reused():
    picks, stats = select(guarded_game(scrape_requests=[request("a-g", game_date=YESTERDAY_ISO)]))

    assert [(p["team_id_master"], p["enqueue"]) for p in picks] == [("a-g", True)]
    assert stats["already_queued"] == 0


def test_a_compatible_pending_row_dated_today_already_covers_yesterday():
    picks, stats = select(guarded_game(scrape_requests=[request("a-g", game_date="2026-11-02")]))

    assert [(p["team_id_master"], p["enqueue"]) for p in picks] == [("a-g", False)]
    assert stats["already_queued"] == 1


# --------------------------------------------------------------------------- #
# find_teams_to_enqueue: the counts
# --------------------------------------------------------------------------- #


def test_the_old_rule_count_reproduces_the_retired_selector():
    """find_yesterday_null_score_teams returns every side with a non-null provider id,
    a live merge-resolved team row and no scrape today, placeholder ids included."""
    supabase = build_supabase(
        games=[
            game("a-1", "z-1"),
            game("a-1", "z-2"),
            game("a-2", "z-3", home_pid="None"),
            game("a-3", "z-4", home_pid=None),
            game("a-4", "z-5"),
            game("a-5", "z-6"),
            game("a-old", "z-7"),
            game("b-canon", "z-8"),
        ],
        teams=[
            team("a-1"),
            team("a-2"),
            team("a-3"),
            team("a-4", deprecated=True),
            team("a-5", last_scraped_at="2026-11-02T01:00:00+00:00"),
            team("b-canon"),
            *[team(f"z-{i}") for i in range(1, 9)],
        ],
        merges=[merge("a-old", "b-canon")],
    )

    _, stats = select(supabase)

    # a-1 once, a-2's placeholder passes IS NOT NULL, b-canon once for its raw id and
    # itself, and the eight opponents; not a-3 (NULL id), a-4 or a-5.
    assert stats["old_rule_teams"] == 11


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


class _FrozenDatetime(datetime):
    """01:13 UTC on 2026-11-02, which is still the evening of 11-01 in Arizona."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return datetime(2026, 11, 1, 18, 13)
        return datetime(2026, 11, 2, 1, 13, tzinfo=timezone.utc).astimezone(tz)


def _run_main(monkeypatch, supabase, argv):
    monkeypatch.setattr(eyg, "create_client", lambda url, key: supabase)
    monkeypatch.setattr(eyg, "datetime", _FrozenDatetime)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(sys, "argv", ["enqueue_yesterday_games.py", *argv])
    eyg.main()


def _two_games(rpc_failures=frozenset()):
    """a-1 needs queueing; a-2 already holds a pending row dated today."""
    return build_supabase(
        games=[game("a-1", "z-1"), game("a-2", "z-2")],
        teams=[team("a-1"), team("z-1"), team("a-2"), team("z-2")],
        scrape_requests=[request("a-2", game_date="2026-11-02")],
        rpc_failures=rpc_failures,
    )


def test_dry_run_enqueues_nothing_and_reports_both_counts(monkeypatch, caplog):
    supabase = _two_games()

    with caplog.at_level("INFO", logger=eyg.logger.name):
        _run_main(monkeypatch, supabase, ["--dry-run"])
        log = caplog.text

    assert supabase.rpc_calls == []
    assert (
        "2 unscored games on 2026-11-01; old rule would queue 4 teams; queueing 2 (1 already queued); "
        "0 games had no scrapeable side, 0 blocked by a sibling registration"
    ) in log
    assert (
        "Sides skipped: no_master 0, blank_provider_id 0, missing_team 0, deprecated 0, "
        "scraped_today 0, active_request_conflict 0"
    ) in log
    assert "WOULD ENQUEUE: a-1 (Team a-1)\n" in log
    assert "WOULD ENQUEUE: a-2 (Team a-2) [already queued]" in log


def test_live_run_enqueues_each_new_pick_once_for_yesterday(monkeypatch):
    supabase = _two_games()

    _run_main(monkeypatch, supabase, [])

    assert supabase.rpc_calls == [
        (
            "enqueue_scrape_request",
            {
                "p_team_id_master": "a-1",
                "p_team_name": "Team a-1",
                "p_provider_id": GOTSPORT_ID,
                "p_provider_team_id": "gs-a-1",
                "p_game_date": "2026-11-01",
                "p_request_type": "yesterday_game",
                "p_priority": 2,
            },
        )
    ]


def test_one_failed_enqueue_does_not_stop_the_rest(monkeypatch, caplog):
    supabase = build_supabase(
        games=[game("a-1", "z-1"), game("a-2", "z-2")],
        teams=[team("a-1"), team("z-1"), team("a-2"), team("z-2")],
        rpc_failures=frozenset({"a-1"}),
    )

    with caplog.at_level("INFO", logger=eyg.logger.name):
        _run_main(monkeypatch, supabase, [])
        assert "Enqueued 1 teams at priority 2, 1 failed" in caplog.text

    assert [params["p_team_id_master"] for _, params in supabase.rpc_calls] == ["a-2"]


def test_missing_gotsport_provider_fails_loudly():
    supabase = FakeSupabase({"providers": [], "games": [], "teams": [], "team_merge_map": [], "scrape_requests": []})

    with pytest.raises(RuntimeError):
        eyg.get_gotsport_provider_id(supabase)
