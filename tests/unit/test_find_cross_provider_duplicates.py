"""Tests for the Doorway C cross-provider duplicate detector.

Each screen gets a fixture violating exactly that screen, because a row that breaks two at
once still dies when either guard is deleted.

The Supabase double evaluates its filters rather than recording them, refuses a range()
that no order() precedes, and serves at most `cap` rows per page. The cap models a
deployment's max-rows, and a pager that reads a capped page as the last one truncates its
scan there.
"""

import csv
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import find_cross_provider_duplicates as fcpd  # noqa: E402

GS, TGS, SINC = "prov-gotsport", "prov-tgs", "prov-sincsports"
PROVIDERS = {GS: "gotsport", TGS: "tgs", SINC: "sincsports"}
SECONDARY = {"tgs", "sincsports"}


def team(
    team_id,
    *,
    name,
    club,
    provider,
    provider_team_id=None,
    age_group="u14",
    gender="Male",
    state_code="TX",
    original=None,
):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": original,
        "club_name": club,
        "age_group": age_group,
        "gender": gender,
        "state_code": state_code,
        "provider_id": provider,
        "provider_team_id": provider_team_id or f"{team_id}-pid",
        "is_deprecated": False,
    }


def game(game_id, home, away, date, *, is_excluded=False):
    return {
        "id": game_id,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "game_date": date,
        "is_excluded": is_excluded,
    }


def alias(team_id, provider, provider_team_id):
    return {"team_id_master": team_id, "provider_id": provider, "provider_team_id": provider_team_id}


def pairs_for(teams, *, competing_similarity=0.60, min_name_len=8):
    return fcpd.build_pairs(
        teams,
        PROVIDERS,
        secondary_codes=SECONDARY,
        competing_similarity=competing_similarity,
        min_name_len=min_name_len,
    )


def evidence_for(games=(), aliases=(), merge_map=None, tracked=()):
    canonical = fcpd.resolver(merge_map or {})
    return fcpd.build_evidence(list(games), list(aliases), canonical, set(tracked)), canonical


def screen_one(pair, ev, canonical, jaccard_max=0.20):
    return fcpd.screen(pair, ev, canonical, jaccard_max=jaccard_max)[0]


class _Result:
    def __init__(self, data):
        self.data = data


IN_BATCH_LIMIT = 100


class _Table:
    def __init__(self, name, rows, cap):
        self.name = name
        self._rows = rows
        self._cap = cap
        self._eq = []
        self._in = []
        self._columns = None
        self._order = None
        self._page = None

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def in_(self, column, values):
        values = list(values)
        if len(values) > IN_BATCH_LIMIT:
            raise AssertionError(
                f"{self.name}: .in_() with {len(values)} ids exceeds the {IN_BATCH_LIMIT}-id URI limit"
            )
        self._in.append((column, values))
        return self

    def order(self, column):
        self._order = column
        return self

    def _matching(self):
        rows = []
        for row in self._rows:
            if any(row[c] != v for c, v in self._eq):
                continue
            if any(row[c] not in v for c, v in self._in):
                continue
            rows.append(row)
        return rows

    def range(self, start, end):
        if self._order is None:
            raise AssertionError(f"{self.name}: range() without order() pages a table unstably")
        rows = sorted(self._matching(), key=lambda r: r[self._order])
        self._page = rows[start : min(end + 1, start + self._cap)]
        return self

    def execute(self):
        # An un-ranged read is capped too. PostgREST caps every response at max-rows, so a
        # double that serves all of them here lets an unpaginated fetch look complete.
        rows = self._page if self._page is not None else self._matching()[: self._cap]
        return _Result([{c: r[c] for c in self._columns} for r in rows])


class _Supabase:
    """`cap` is the server's max-rows, not the caller's page size."""

    def __init__(self, tables, cap=3):
        self._tables = tables
        self._cap = cap

    def table(self, name):
        if name not in self._tables:
            raise AssertionError(f"no rows seeded for table {name!r}")
        return _Table(name, self._tables[name], self._cap)


def test_page_continues_past_a_server_capped_page():
    """A cap below the requested size is not the end of the table.

    Requesting 10,000 and being served 3 is what a local `supabase start` does. A pager that
    advances by its own page size skips the rest; one that stops on a short page loses it too.
    """
    rows = [team(f"t{i:03d}", name=f"Squad {i}", club="Club", provider=GS) for i in range(10)]
    sb = _Supabase({"teams": rows}, cap=3)

    fetched = fcpd.page(lambda: sb.table("teams").select("team_id_master"), "team_id_master")

    assert [r["team_id_master"] for r in fetched] == [f"t{i:03d}" for i in range(10)]


def test_page_refuses_to_range_without_ordering():
    """Pins the double itself, not the script: an unordered pager must be unrepresentable."""
    sb = _Supabase({"teams": [team("t1", name="Squad", club="Club", provider=GS)]})

    with pytest.raises(AssertionError, match="unstably"):
        sb.table("teams").select("team_id_master").range(0, 9)


def test_the_double_refuses_an_in_batch_above_the_uri_limit():
    """Pins the double. A fetch that stopped batching would otherwise look fine here."""
    sb = _Supabase({"teams": []})

    with pytest.raises(AssertionError, match="URI limit"):
        sb.table("teams").select("team_id_master").in_("team_id_master", [f"t{i}" for i in range(101)])


def test_the_double_caps_a_read_that_never_asked_for_a_range():
    """Pins the double. PostgREST caps every response, ranged or not, so a fetch that drops its
    pager must come back short here rather than complete."""
    rows = [team(f"t{i:03d}", name=f"Squad {i}", club="Club", provider=GS) for i in range(10)]

    served = _Supabase({"teams": rows}, cap=3).table("teams").select("team_id_master").execute().data

    assert len(served) == 3


def test_fetch_teams_reads_only_live_rows_in_the_named_scope():
    rows = [
        team("live", name="Squad One", club="Club", provider=GS),
        {**team("dead", name="Squad Two", club="Club", provider=GS), "is_deprecated": True},
        team("other-state", name="Squad Three", club="Club", provider=GS, state_code="WA"),
        team("other-age", name="Squad Four", club="Club", provider=GS, age_group="u15"),
    ]

    fetched = fcpd.fetch_teams(_Supabase({"teams": rows}), state="tx", age_group="U14")

    assert [r["team_id_master"] for r in fetched] == ["live"]


def test_fetch_aliases_pages_past_the_cap_and_reads_only_approved_rows():
    """An alias is evidence for `1_provably_safe`, the one tier that skips every review flag.

    Truncation and a rejected alias fail the same way -- silently, and towards proposing.
    """
    rows = [
        {**alias("gs", TGS, f"pid-{i}"), "id": f"a{i:03d}", "review_status": "approved"}
        for i in range(7)
    ] + [
        {**alias("gs", TGS, "pid-rejected"), "id": "a900", "review_status": "rejected"},
        {**alias("gs", TGS, "pid-pending"), "id": "a901", "review_status": "pending"},
    ]

    fetched = fcpd.fetch_aliases(_Supabase({"team_alias_map": rows}, cap=3), ["gs"])

    assert len(fetched) == 7
    assert {r["provider_team_id"] for r in fetched} == {f"pid-{i}" for i in range(7)}


def test_fetch_games_batches_ids_and_counts_a_game_touching_both_sides_once():
    rows = [
        {**game(f"g{i:03d}", f"t{i:03d}", "opp", "2026-09-05"), "id": f"g{i:03d}"} for i in range(150)
    ] + [game("shared", "t000", "t001", "2026-09-12")]

    fetched = fcpd.fetch_games(_Supabase({"games": rows}), [f"t{i:03d}" for i in range(150)])

    assert len(fetched) == 151
    assert len({g["id"] for g in fetched}) == 151


def test_a_club_punctuated_differently_by_two_providers_still_pairs():
    """The mutation this kills: comparing club_name raw instead of normalised.

    `Total Futbol Academy(OH)` and `Total Futbol Academy (OH)` are the same club, and a raw
    comparison refuses them -- which is exactly the refusal Doorway A already makes and that
    this doorway exists to get past.
    """
    teams = [
        team("gs", name="TFA 2012 Black", club="Total Futbol Academy(OH)", provider=GS),
        team("ot", name="TFA 2012 Black", club="Total Futbol Academy (OH)", provider=TGS),
    ]

    pairs = pairs_for(teams)

    assert len(pairs) == 1
    assert (pairs[0]["gs"]["team_id_master"], pairs[0]["ot"]["team_id_master"]) == ("gs", "ot")


@pytest.mark.parametrize("missing", ["club_name", "age_group", "gender"])
def test_a_row_missing_club_age_or_gender_never_pairs(missing):
    """One conjunct per case: a blank club is not an identity, and None is not a cohort.

    `normalize(None)` is `""` on both sides, so without the club conjunct two unrelated teams
    sharing a generic name like `2012 Boys Red` would pair.
    """
    teams = [
        {**team("gs", name="2012 Boys Red", club="Westy SC", provider=GS), missing: None},
        {**team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS), missing: None},
    ]

    assert pairs_for(teams) == []


def test_two_rows_with_no_state_still_pair():
    """NULL state buckets together deliberately -- the alternative is never proposing them."""
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS, state_code=None),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS, state_code=None),
    ]

    assert len(pairs_for(teams)) == 1


def test_two_different_clubs_sharing_a_team_name_do_not_pair():
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Rush Soccer Club", provider=TGS),
    ]

    assert pairs_for(teams) == []


def test_only_rows_of_different_providers_pair():
    teams = [
        team("gs-a", name="Dallas Texans Red", club="Dallas Texans", provider=GS),
        team("gs-b", name="Dallas Texans Red", club="Dallas Texans", provider=GS),
    ]

    assert pairs_for(teams) == []


def test_a_short_normalised_name_is_not_identity():
    teams = [
        team("gs", name="B12 Red", club="Westy SC", provider=GS),
        team("ot", name="B12 Red", club="Westy SC", provider=TGS),
    ]

    assert pairs_for(teams) == []


def test_a_third_row_under_the_club_s_other_spelling_is_a_competing_partner():
    """The pair's club is byte-equal; the competitor's is only similar.

    Grouping on the club -- which is what byte-equal club matching amounts to -- puts this
    third row in a different bucket, and the pair then reads as an unambiguous two.
    """
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
        team("third", name="2012 Boys Red", club="Westy Soccer Club", provider=SINC),
    ]

    pairs = {(p["gs"]["team_id_master"], p["ot"]["team_id_master"]): p for p in pairs_for(teams)}

    assert [c["team_id_master"] for c in pairs[("gs", "ot")]["competing"]] == ["third"]


def test_an_unrelated_club_in_the_cohort_does_not_compete():
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
        team("third", name="2012 Boys Red", club="Rush Soccer Club", provider=SINC),
    ]

    pairs = {(p["gs"]["team_id_master"], p["ot"]["team_id_master"]): p for p in pairs_for(teams)}

    assert pairs[("gs", "ot")]["competing"] == []


def test_opponent_overlap_is_measured_through_the_merge_map():
    """The mutation this kills: recording opponents by raw master id.

    Both rows played the same opponent, but one game names the opponent row that has since
    been merged away. Unresolved, the two opponent sets are disjoint and Jaccard reads 0.0 --
    the permissive direction, which passes the pair the screen exists to reject.
    """
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
    ]
    games = [
        game("g1", "gs", "opp-old", "2026-09-05"),
        game("g2", "ot", "opp-live", "2026-09-12"),
    ]
    ev, canonical = evidence_for(games, merge_map={"opp-old": "opp-live"}, tracked={"gs", "ot"})

    assert screen_one(pairs_for(teams)[0], ev, canonical) == "opponent overlap above 0.2"


def test_registered_names_stating_opposite_genders_are_refused():
    """Both rows store the same wrong gender; only the registered names disagree.

    This is the Oklahoma Cosmos shape. The stored column is what let the pair into the
    candidate pool, and a word-only reading of the names ("Boys"/"Girls") sees nothing in
    `12B` against `12G`.
    """
    teams = [
        team("gs", name="Oklahoma Cosmos 2012 Premier", club="Oklahoma Cosmos", provider=GS,
             original="Oklahoma Cosmos 12B Premier"),
        team("ot", name="Oklahoma Cosmos 2012 Premier", club="Oklahoma Cosmos", provider=TGS,
             original="Oklahoma Cosmos 12G Premier"),
    ]
    ev, canonical = evidence_for(tracked={"gs", "ot"})

    assert screen_one(pairs_for(teams)[0], ev, canonical) == (
        "the registered names state opposite genders (Male vs Female)"
    )


def test_registered_names_agreeing_on_gender_pass():
    teams = [
        team("gs", name="Oklahoma Cosmos 2012 Premier", club="Oklahoma Cosmos", provider=GS,
             original="Oklahoma Cosmos 12B Premier"),
        team("ot", name="Oklahoma Cosmos 2012 Premier", club="Oklahoma Cosmos", provider=TGS,
             original="Oklahoma Cosmos 12B Premier"),
    ]
    ev, canonical = evidence_for(tracked={"gs", "ot"})

    assert screen_one(pairs_for(teams)[0], ev, canonical) is None


def _plain_pair():
    return [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
    ]


def test_a_head_to_head_game_is_refused():
    games = [game("g1", "gs", "ot", "2026-09-05")]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert screen_one(pairs_for(_plain_pair())[0], ev, canonical) == "the two records played each other"


@pytest.mark.parametrize("known_side", ["gs", "ot"])
def test_a_head_to_head_seen_from_one_side_only_is_refused(known_side):
    """One conjunct each. Both sides normally record the fixture, so an `or` degraded to an
    `and` survives every two-sided fixture -- only a pair where one side never saw the game
    tells them apart."""
    ev, canonical = evidence_for(tracked={"gs", "ot"})
    other = "ot" if known_side == "gs" else "gs"
    ev.opponents[known_side].add(other)

    assert screen_one(pairs_for(_plain_pair())[0], ev, canonical) == "the two records played each other"


def test_one_side_stating_no_gender_does_not_refuse_the_pair():
    """The `said_ot` conjunct: a silent name contradicts nothing."""
    teams = [
        team("gs", name="Westy SC 2012 Red", club="Westy SC", provider=GS, original="Westy SC 12B Red"),
        team("ot", name="Westy SC 2012 Red", club="Westy SC", provider=TGS, original="Westy SC 2012 Red"),
    ]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert fcpd.stated_gender("Westy SC 2012 Red") is None
    assert screen_one(pairs_for(teams)[0], ev, canonical) is None


def test_a_name_contradicting_itself_states_no_gender():
    """`any_gender` lets the affix win so it can guess an opponent; here a guess refuses a merge."""
    assert fcpd.stated_gender("Westy SC 12B Girls") is None
    assert fcpd.stated_gender("GU12 Boys Blue") is None
    assert fcpd.stated_gender("Oklahoma Cosmos 12G Premier") == "Female"
    assert fcpd.stated_gender("Westy SC 2012 Girls") == "Female"


def test_the_jaccard_denominator_is_the_opponent_union_not_the_dates():
    """Each side replays its own opponents, so there are twice as many dates as opponents.

    One shared opponent out of three is 0.333 and refuses; counted against the eight dates it
    would read 0.125 and pass. A fixture with no shared opponent cannot tell the two apart,
    because the numerator is zero either way.
    """
    games = [
        game("g1", "gs", "opp-a", "2026-09-01"),
        game("g2", "gs", "opp-b", "2026-09-02"),
        game("g3", "gs", "opp-a", "2026-09-03"),
        game("g4", "gs", "opp-b", "2026-09-04"),
        game("g5", "ot", "opp-a", "2026-09-05"),
        game("g6", "ot", "opp-c", "2026-09-06"),
        game("g7", "ot", "opp-a", "2026-09-07"),
        game("g8", "ot", "opp-c", "2026-09-08"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    reason, jaccard = fcpd.screen(pairs_for(_plain_pair())[0], ev, canonical, jaccard_max=0.20)

    assert jaccard == pytest.approx(1 / 3)
    assert reason == "opponent overlap above 0.2"


def test_a_refused_pair_carries_the_overlap_it_actually_had():
    """A shared date refuses first, but Step 4's question is what the opponents were."""
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-a", "2026-09-05"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    reason, jaccard = fcpd.screen(pairs_for(_plain_pair())[0], ev, canonical, jaccard_max=0.20)

    assert reason == "both played a game on the same day"
    assert jaccard == 1.0


def test_a_shared_game_date_is_refused():
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-05"),
        game("g3", "ot", "opp-c", "2026-09-12"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert screen_one(pairs_for(_plain_pair())[0], ev, canonical) == "both played a game on the same day"


def test_a_self_play_row_is_refused_even_when_the_game_is_excluded():
    """Self-play says the row is already two squads, which exclusion does not undo."""
    games = [
        game("g1", "gs", "gs", "2026-09-05", is_excluded=True),
        game("g2", "ot", "opp-a", "2026-09-12"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert screen_one(pairs_for(_plain_pair())[0], ev, canonical) == (
        "a row carries a self-play game and is already two squads"
    )


def test_disjoint_schedules_pass_every_screen():
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-12"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert screen_one(pairs_for(_plain_pair())[0], ev, canonical) is None


def test_an_excluded_game_is_not_counted_as_a_shared_date():
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-05", is_excluded=True),
        game("g3", "ot", "opp-c", "2026-09-12"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert screen_one(pairs_for(_plain_pair())[0], ev, canonical) is None


def test_a_candidate_that_is_itself_merged_away_keeps_its_games():
    """`tracked` is compared against resolved ids, so it has to hold resolved ids.

    A live row can still carry a `team_merge_map` entry. Matching raw candidate ids against a
    resolved one drops every game it has, and the pair is then filed as a direction flip --
    deprecating the row that holds the schedule.
    """
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, merge_map={"gs": "gs-new"}, tracked={"gs", "ot"})

    assert ev.games[canonical("gs")] == 1
    assert fcpd.tier_for(pairs_for(_plain_pair())[0], ev, canonical) == "2_both_have_games"


def test_games_inherited_through_a_merge_stop_a_survivor_reading_as_empty():
    """The GotSport row holds no game under its own id, only under one merged into it.

    Read raw, it looks like the empty side and the pair is filed as a direction flip -- which
    would deprecate the row holding the live schedule.
    """
    pair = pairs_for(_plain_pair())[0]
    games = [
        game("g1", "gs-old", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-12"),
    ]
    ev, canonical = evidence_for(games, merge_map={"gs-old": "gs"}, tracked={"gs", "ot"})

    assert ev.games["gs"] == 1
    assert fcpd.tier_for(pair, ev, canonical) == "2_both_have_games"


def test_merged_into_gathers_the_rows_a_candidate_inherited_from():
    merge_map = {"a": "b", "b": "survivor", "unrelated": "elsewhere"}

    assert fcpd.merged_into({"survivor"}, merge_map, fcpd.resolver(merge_map)) == {"survivor", "a", "b"}


def test_a_cyclic_merge_map_terminates():
    """A merge undone and reapplied can close the loop; without the guard the scan hangs."""
    canonical = fcpd.resolver({"a": "b", "b": "a"})

    assert canonical("a") in {"a", "b"}


def test_a_row_that_absorbed_a_team_it_had_played_is_refused_as_self_play():
    """The commonest fused row: raw ids still differ, so only the resolved pair sees it."""
    pair = pairs_for(_plain_pair())[0]
    games = [game("g1", "gs", "gs-old", "2026-09-05"), game("g2", "ot", "opp-a", "2026-09-12")]
    ev, canonical = evidence_for(games, merge_map={"gs-old": "gs"}, tracked={"gs", "ot"})

    assert ev.self_play == {"gs"}
    assert ev.games["gs"] == 0
    assert "gs" not in ev.opponents["gs"]
    assert screen_one(pair, ev, canonical) == "a row carries a self-play game and is already two squads"


def test_an_empty_other_side_is_its_own_tier():
    pair = pairs_for(_plain_pair())[0]
    ev, canonical = evidence_for([game("g1", "gs", "opp-a", "2026-09-05")], tracked={"gs", "ot"})

    assert fcpd.tier_for(pair, ev, canonical) == "3_other_side_empty"


def test_two_empty_rows_are_their_own_tier():
    pair = pairs_for(_plain_pair())[0]
    ev, canonical = evidence_for(tracked={"gs", "ot"})

    assert fcpd.tier_for(pair, ev, canonical) == "5_both_empty"


def test_a_review_flag_does_not_take_the_direction_away_from_an_empty_gotsport_row():
    """The flags moved the tier off `4_flip_direction`; the survivor must not move with it.

    Deciding direction from the tier string sends the row holding the whole season to the
    applier as the row to deprecate.
    """
    teams = _plain_pair() + [team("third", name="2012 Boys Red", club="Westy Soccer Club", provider=SINC)]
    pair = next(p for p in pairs_for(teams) if p["ot"]["team_id_master"] == "ot")
    ev, canonical = evidence_for([game("g1", "ot", "opp-a", "2026-09-05")], tracked={"gs", "ot"})
    tier = fcpd.tier_for(pair, ev, canonical)

    record = fcpd.to_record(pair, ev, canonical, tier, 0.0)

    assert tier == "6_review_competing_partner"
    assert (record["merge_id"], record["keep_id"]) == ("gs", "ot")
    assert record["survivor_holds_fewer_games"] is False


def test_a_flipped_record_reports_the_survivor_as_holding_more_games():
    """The second half of the flip: the counts must follow the rows they were chosen for."""
    pair = pairs_for(_plain_pair())[0]
    games = [game(f"g{i}", "ot", f"opp-{i}", f"2026-09-{5 + i:02d}") for i in range(3)]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    record = fcpd.to_record(pair, ev, canonical, fcpd.tier_for(pair, ev, canonical), 0.0)

    assert (record["merge_id"], record["keep_id"]) == ("gs", "ot")
    assert (record["gs_games"], record["ot_games"]) == (0, 3)
    assert record["survivor_holds_fewer_games"] is False


def test_a_secondary_row_holding_games_is_a_flip_even_when_its_alias_points_at_gotsport():
    """The `ot_games == 0` half of the provably-safe test.

    Without it the tier claims the merge moves no attribution while the secondary row holds
    the whole schedule -- and it is the tier that skips every later review.
    """
    teams = _plain_pair()
    pair = pairs_for(teams)[0]
    aliases = [alias("gs", TGS, teams[1]["provider_team_id"])]
    ev, canonical = evidence_for([game("g1", "ot", "opp-a", "2026-09-05")], aliases, tracked={"gs", "ot"})

    assert fcpd.alias_points_at_primary(pair, ev, canonical) is True
    assert fcpd.tier_for(pair, ev, canonical) == "4_flip_direction"


def test_a_blank_registration_is_not_evidence_that_an_alias_points_anywhere():
    """`''`, `'None'` and `'null'` are live provider_team_id values; two matching identify nothing."""
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS, provider_team_id="None"),
    ]
    pair = pairs_for(teams)[0]
    ev, canonical = evidence_for(aliases=[alias("gs", TGS, "None")], tracked={"gs", "ot"})

    assert fcpd.alias_points_at_primary(pair, ev, canonical) is False
    assert fcpd.tier_for(pair, ev, canonical) == "5_both_empty"


def test_excluded_games_are_reported_without_deciding_the_direction():
    """A merge moves an excluded row too, so the reviewer sees it; but it is no live schedule."""
    pair = pairs_for(_plain_pair())[0]
    games = [game(f"x{i}", "gs", f"opp-{i}", f"2026-09-{i + 1:02d}", is_excluded=True) for i in range(4)]
    games.append(game("g1", "ot", "opp-live", "2026-09-20"))
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    record = fcpd.to_record(pair, ev, canonical, fcpd.tier_for(pair, ev, canonical), 0.0)

    assert (record["gs_games"], record["gs_excluded_games"]) == (0, 4)
    assert record["direction"] == "flipped"
    assert (record["merge_id"], record["keep_id"]) == ("gs", "ot")


def test_the_direction_column_names_the_surviving_provider_on_a_flagged_tier():
    """Tiers 6 and 7 keep the reversal but lose the `4_flip_direction` label that announced it."""
    teams = _plain_pair() + [team("third", name="2012 Boys Red", club="Westy Soccer Club", provider=SINC)]
    pair = next(p for p in pairs_for(teams) if p["ot"]["team_id_master"] == "ot")
    ev, canonical = evidence_for([game("g1", "ot", "opp-a", "2026-09-05")], tracked={"gs", "ot"})
    tier = fcpd.tier_for(pair, ev, canonical)

    record = fcpd.to_record(pair, ev, canonical, tier, 0.0)

    assert tier == "6_review_competing_partner"
    assert record["direction"] == "flipped"


def test_an_empty_other_side_whose_alias_already_points_at_gotsport_is_provably_safe():
    teams = _plain_pair()
    pair = pairs_for(teams)[0]
    aliases = [alias("gs", TGS, teams[1]["provider_team_id"])]
    ev, canonical = evidence_for([game("g1", "gs", "opp-a", "2026-09-05")], aliases, tracked={"gs", "ot"})

    assert fcpd.tier_for(pair, ev, canonical) == "1_provably_safe"


def test_a_provably_safe_pair_keeps_its_tier_despite_a_competing_partner():
    """Its alias already points at the survivor, so the merge moves no attribution."""
    teams = _plain_pair() + [team("third", name="2012 Boys Red", club="Westy Soccer Club", provider=SINC)]
    pair = next(p for p in pairs_for(teams) if p["ot"]["team_id_master"] == "ot")
    aliases = [alias("gs", TGS, teams[1]["provider_team_id"])]
    ev, canonical = evidence_for([game("g1", "gs", "opp-a", "2026-09-05")], aliases, tracked={"gs", "ot"})

    assert pair["competing"]
    assert fcpd.tier_for(pair, ev, canonical) == "1_provably_safe"


def test_a_competing_partner_demotes_a_pair_that_would_otherwise_merge():
    teams = _plain_pair() + [team("third", name="2012 Boys Red", club="Westy Soccer Club", provider=SINC)]
    pair = next(p for p in pairs_for(teams) if p["ot"]["team_id_master"] == "ot")
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    assert fcpd.tier_for(pair, ev, canonical) == "6_review_competing_partner"


def test_a_row_carrying_three_registrations_from_one_provider_is_flagged():
    pair = pairs_for(_plain_pair())[0]
    aliases = [alias("gs", GS, f"reg-{i}") for i in range(fcpd.FUSED_REGISTRATION_THRESHOLD)]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, aliases, tracked={"gs", "ot"})

    assert fcpd.tier_for(pair, ev, canonical) == "7_review_fused_registration"


def test_two_registrations_from_one_provider_are_not_flagged():
    pair = pairs_for(_plain_pair())[0]
    below = fcpd.FUSED_REGISTRATION_THRESHOLD - 1
    aliases = [alias("gs", GS, f"reg-{i}") for i in range(below)]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, aliases, tracked={"gs", "ot"})

    assert below == 2
    assert fcpd.tier_for(pair, ev, canonical) == "2_both_have_games"


def test_an_empty_gotsport_row_flips_the_direction():
    pair = pairs_for(_plain_pair())[0]
    ev, canonical = evidence_for([game("g1", "ot", "opp-a", "2026-09-05")], tracked={"gs", "ot"})
    tier = fcpd.tier_for(pair, ev, canonical)

    record = fcpd.to_record(pair, ev, canonical, tier, 0.0)

    assert tier == "4_flip_direction"
    assert (record["merge_id"], record["keep_id"]) == ("gs", "ot")


def test_the_gotsport_row_survives_every_other_tier():
    pair = pairs_for(_plain_pair())[0]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    record = fcpd.to_record(pair, ev, canonical, fcpd.tier_for(pair, ev, canonical), 0.0)

    assert (record["merge_id"], record["keep_id"]) == ("ot", "gs")
    assert record["survivor_holds_fewer_games"] is False


def test_a_refused_pair_is_recorded_with_the_reason_that_refused_it():
    """Step 4 of the skill reviews every refusal, which a funnel count alone cannot support."""
    pair = pairs_for(_plain_pair())[0]
    ev, canonical = evidence_for([game("g1", "gs", "ot", "2026-09-05")], tracked={"gs", "ot"})
    reason, jaccard = fcpd.screen(pair, ev, canonical, jaccard_max=0.20)

    record = fcpd.to_record(pair, ev, canonical, fcpd.REJECTED_TIER, jaccard, reason)

    assert record["tier"] == fcpd.REJECTED_TIER
    assert record["rejected_reason"] == "the two records played each other"


def test_a_proposed_pair_carries_no_rejection_reason():
    pair = pairs_for(_plain_pair())[0]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    record = fcpd.to_record(pair, ev, canonical, fcpd.tier_for(pair, ev, canonical), 0.0)

    assert record["rejected_reason"] == ""
    assert record["tier"] != fcpd.REJECTED_TIER


def test_opponent_overlap_exactly_at_the_cap_is_allowed():
    """The skill states the rule as "Jaccard <= 0.20", so 0.20 itself must pass."""
    games = [game("shared", "gs", "opp-0", "2026-09-05")] + [
        game(f"g{i}", "gs", f"opp-{i}", f"2026-09-{6 + i:02d}") for i in range(1, 3)
    ] + [game("o0", "ot", "opp-0", "2026-09-20")] + [
        game(f"o{i}", "ot", f"opp-x{i}", f"2026-09-2{i}") for i in range(1, 3)
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    reason, jaccard = fcpd.screen(pairs_for(_plain_pair())[0], ev, canonical, jaccard_max=0.20)

    assert jaccard == pytest.approx(0.20)
    assert reason is None


def test_a_name_of_exactly_the_minimum_length_is_long_enough():
    teams = [
        team("gs", name="2012 Reds", club="Westy SC", provider=GS),
        team("ot", name="2012 Reds", club="Westy SC", provider=TGS),
    ]

    assert len(fcpd.normalize("2012 Reds")) == 8
    assert len(pairs_for(teams, min_name_len=8)) == 1


def test_record_fields_match_the_declared_csv_columns():
    """Pins the declared column order against what `to_record` actually emits."""
    pair = pairs_for(_plain_pair())[0]
    ev, canonical = evidence_for(tracked={"gs", "ot"})

    record = fcpd.to_record(pair, ev, canonical, fcpd.tier_for(pair, ev, canonical), 0.0)

    assert tuple(record) == fcpd.RECORD_FIELDS
    assert fcpd.PROVIDER_TEXT_FIELDS <= set(fcpd.RECORD_FIELDS)


def test_a_survivor_holding_fewer_games_is_flagged_for_the_reviewer():
    pair = pairs_for(_plain_pair())[0]
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-12"),
        game("g3", "ot", "opp-c", "2026-09-19"),
    ]
    ev, canonical = evidence_for(games, tracked={"gs", "ot"})

    record = fcpd.to_record(pair, ev, canonical, fcpd.tier_for(pair, ev, canonical), 0.0)

    assert record["keep_id"] == "gs"
    assert record["survivor_holds_fewer_games"] is True


def _scan_double(teams, games=(), aliases=(), merges=()):
    return _Supabase(
        {
            "providers": [
                {"id": GS, "code": "gotsport"},
                {"id": TGS, "code": "tgs"},
                {"id": SINC, "code": "sincsports"},
            ],
            "teams": list(teams),
            "games": [{**g, "id": g["id"]} for g in games],
            "team_alias_map": [
                {**a, "id": f"al{i}", "review_status": "approved"} for i, a in enumerate(aliases)
            ],
            "team_merge_map": list(merges),
        },
        cap=1000,
    )


def _args(**overrides):
    defaults = dict(
        provider=None, state=None, age_group=None,
        jaccard_max=0.20, competing_similarity=0.60, min_name_len=8,
    )
    return SimpleNamespace(**{**defaults, **overrides})


def test_scan_proposes_a_disjoint_pair_and_refuses_a_head_to_head_one():
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
        team("gs2", name="2013 Boys Blue", club="Rush Soccer Club", provider=GS, age_group="u13"),
        team("ot2", name="2013 Boys Blue", club="Rush Soccer Club", provider=TGS, age_group="u13"),
    ]
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-12"),
        game("g3", "gs2", "ot2", "2026-09-19"),
    ]

    records, rejected = fcpd.scan(_scan_double(teams, games), _args())

    by_tier = {r["tier"]: r for r in records}
    assert by_tier["2_both_have_games"]["merge_id"] == "ot"
    assert by_tier[fcpd.REJECTED_TIER]["merge_id"] == "ot2"
    assert rejected == {"the two records played each other": 1}


def test_scan_keeps_a_competing_partner_visible_when_one_provider_is_selected():
    """Narrowing which pairs are proposed must not narrow the screen that protects them."""
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
        team("third", name="2012 Boys Red", club="Westy Soccer Club", provider=SINC),
    ]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]

    records, _ = fcpd.scan(_scan_double(teams, games), _args(provider="tgs"))

    assert [r["ot_name"] for r in records] == ["2012 Boys Red"]
    assert records[0]["tier"] == "6_review_competing_partner"
    assert records[0]["competing_partner_ids"] == "third"


def test_scan_counts_games_a_candidate_inherited_from_a_merged_row():
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
    ]
    games = [game("g1", "gs-old", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    merges = [{"id": "m1", "deprecated_team_id": "gs-old", "canonical_team_id": "gs"}]

    records, _ = fcpd.scan(_scan_double(teams, games, merges=merges), _args())

    assert (records[0]["tier"], records[0]["gs_games"]) == ("2_both_have_games", 1)


def test_scan_fetches_the_games_of_a_candidate_that_is_itself_merged_away():
    """Driving `build_evidence` directly cannot catch this -- the bug is in what gets fetched.

    The GotSport row is live but carries a `team_merge_map` entry, so its evidence is keyed on
    the survivor. Leaving that survivor out of the fetch reads the row as having no schedule,
    flips the direction, and hands the applier the row holding the season as the one to
    deprecate -- which it then redirects onto the survivor.
    """
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
    ]
    games = [game(f"g{i}", "gs-new", f"opp-{i}", f"2026-09-{i + 1:02d}") for i in range(5)]
    games.append(game("g9", "ot", "opp-late", "2026-09-20"))
    merges = [{"id": "m1", "deprecated_team_id": "gs", "canonical_team_id": "gs-new"}]

    records, _ = fcpd.scan(_scan_double(teams, games, merges=merges), _args())

    assert (records[0]["gs_games"], records[0]["ot_games"]) == (5, 1)
    assert records[0]["direction"] == "gotsport_survives"
    assert (records[0]["merge_id"], records[0]["keep_id"]) == ("ot", "gs")


def test_main_keeps_refused_pairs_out_of_the_file_that_feeds_the_applier(tmp_path, monkeypatch):
    """The one line between a refusal and the merge tool."""
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
        team("gs2", name="2013 Boys Blue", club="Rush Soccer Club", provider=GS, age_group="u13"),
        team("ot2", name="2013 Boys Blue", club="Rush Soccer Club", provider=TGS, age_group="u13"),
    ]
    games = [
        game("g1", "gs", "opp-a", "2026-09-05"),
        game("g2", "ot", "opp-b", "2026-09-12"),
        game("g3", "gs2", "ot2", "2026-09-19"),
    ]
    monkeypatch.setattr(fcpd, "get_client", lambda: _scan_double(teams, games))
    monkeypatch.setattr(sys, "argv", ["prog", "--out-dir", str(tmp_path)])

    assert fcpd.main() == 0

    proposed = json.loads((tmp_path / "cross_provider_duplicates.json").read_text(encoding="utf-8"))
    csv_rows = list(csv.DictReader((tmp_path / "cross_provider_duplicates.csv").open(encoding="utf-8")))
    assert [r["merge_id"] for r in proposed] == ["ot"]
    assert {r["tier"] for r in csv_rows} == {"2_both_have_games", fcpd.REJECTED_TIER}


def test_main_rewrites_the_csv_when_a_narrower_run_finds_nothing(tmp_path, monkeypatch):
    """Otherwise the CSV describes an earlier, wider scan while the JSON describes this one."""
    teams = [
        team("gs", name="2012 Boys Red", club="Westy SC", provider=GS),
        team("ot", name="2012 Boys Red", club="Westy SC", provider=TGS),
    ]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    monkeypatch.setattr(sys, "argv", ["prog", "--out-dir", str(tmp_path)])

    monkeypatch.setattr(fcpd, "get_client", lambda: _scan_double(teams, games))
    fcpd.main()
    monkeypatch.setattr(fcpd, "get_client", lambda: _scan_double([], []))
    fcpd.main()

    csv_rows = list(csv.DictReader((tmp_path / "cross_provider_duplicates.csv").open(encoding="utf-8")))
    assert csv_rows == []
    assert json.loads((tmp_path / "cross_provider_duplicates.json").read_text(encoding="utf-8")) == []


def test_main_defangs_a_club_name_a_spreadsheet_would_run(tmp_path, monkeypatch):
    """The CSV is the review sheet; the JSON the applier reads keeps the registered text."""
    teams = [
        team("gs", name="2012 Boys Red", club="=HYPERLINK(1)", provider=GS),
        team("ot", name="2012 Boys Red", club="=HYPERLINK(1)", provider=TGS),
    ]
    games = [game("g1", "gs", "opp-a", "2026-09-05"), game("g2", "ot", "opp-b", "2026-09-12")]
    monkeypatch.setattr(fcpd, "get_client", lambda: _scan_double(teams, games))
    monkeypatch.setattr(sys, "argv", ["prog", "--out-dir", str(tmp_path)])

    fcpd.main()

    csv_rows = list(csv.DictReader((tmp_path / "cross_provider_duplicates.csv").open(encoding="utf-8")))
    proposed = json.loads((tmp_path / "cross_provider_duplicates.json").read_text(encoding="utf-8"))
    assert csv_rows[0]["club"] == "'=HYPERLINK(1)"
    assert proposed[0]["keep_name"] == "2012 Boys Red"


@pytest.mark.parametrize("flag", ["--jaccard-max", "--competing-similarity"])
def test_main_refuses_a_threshold_that_switches_its_screen_off(flag, tmp_path, monkeypatch):
    """NaN compares false against everything, so it disables a screen rather than widening it."""
    monkeypatch.setattr(fcpd, "get_client", lambda: _scan_double([], []))
    monkeypatch.setattr(sys, "argv", ["prog", "--out-dir", str(tmp_path), flag, "nan"])

    with pytest.raises(SystemExit) as exc:
        fcpd.main()

    assert exc.value.code == 2
