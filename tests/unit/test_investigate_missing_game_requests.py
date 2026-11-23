"""Tests for the 3-hourly missing-game request investigation.

Each duplicate rule gets a fixture that breaks only that rule, because a pair breaking two
at once still dies when either guard is deleted.

The Supabase double evaluates the filters it is given, refuses a filter or a select naming a
column its rows lack (PostgREST answers 42703), projects rows to the selected columns, refuses
a range() that no order() precedes, and serves at most `cap` rows per response. Like
postgrest-py, which sends None as the text "None", its eq() and in_() never match NULL. Its only
write is update(), which changes rows at execute() and records them there, as postgrest-py
sends nothing until then; an update with no filter is refused.

Dates the season rules read hang off the current season's start, because "this season" moves
every Aug 1; dates that only test formatting are fixed.
"""

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT)

from scripts import investigate_missing_game_requests as img  # noqa: E402

SEASON = date.fromisoformat(img.SEASON_START)
UTC = timezone.utc


def day(n: int) -> str:
    return (SEASON + timedelta(days=n)).isoformat()


GS, SINC, TGS = "p-gotsport", "p-sincsports", "p-tgs"
PROVIDERS = [{"id": GS, "code": "gotsport"}, {"id": SINC, "code": "sincsports"}, {"id": TGS, "code": "tgs"}]
PROVIDER_CODES = {p["id"]: p["code"] for p in PROVIDERS}


def team(team_id, name, *, club="Rush", age="u10", gender="Male", state="CO", provider=GS, pid=None, original=None):
    return {
        "id": f"row-{team_id}",
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": original,
        "club_name": club,
        "age_group": age,
        "gender": gender,
        "state_code": state,
        "provider_id": provider,
        "provider_team_id": pid if pid is not None else f"{team_id}-pid",
        "is_deprecated": False,
    }


# Saved long before any scrape the tests run.
BEFORE = "2026-01-05T00:00:00+00:00"


def game(game_id, home, away, when, *, excluded=False, score=(1, 0), created=BEFORE, scraped=BEFORE):
    return {
        "id": game_id,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "game_date": when,
        "home_score": score[0],
        "away_score": score[1],
        "is_excluded": excluded,
        "created_at": created,
        "scraped_at": scraped,
    }


def schedule(games, tracked):
    return img.schedules(games, lambda t: t, set(tracked))


def fixtures_for(team_id, games):
    return schedule(games, [team_id])[0][team_id]


class _Result:
    def __init__(self, data):
        self.data = data


def _comparable(value):
    if isinstance(value, str) and "T" in value:
        return datetime.fromisoformat(value)
    return value


class _Table:
    def __init__(self, name, rows, cap, writes):
        self.name = name
        self._rows = rows
        self._cap = cap
        self._writes = writes
        self._filters = []
        self._columns = None
        self._order = None
        self._page = None
        self._update = None

    def _check(self, column):
        if self._rows and column not in self._rows[0]:
            raise AssertionError(f"{self.name}: no column {column!r}")

    def _filter(self, column, test):
        self._check(column)
        self._filters.append((column, test))
        return self

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
        return self._filter(column, lambda v: value is not None and v == value)

    def in_(self, column, values):
        values = [v for v in values if v is not None]
        if len(values) > 100:
            raise AssertionError(f"{self.name}: .in_() with {len(values)} ids exceeds the URI limit")
        return self._filter(column, lambda v: v in values)

    def is_(self, column, value):
        assert value == "null"
        return self._filter(column, lambda v: v is None)

    def gte(self, column, value):
        return self._filter(column, lambda v: v is not None and _comparable(v) >= _comparable(value))

    def lt(self, column, value):
        return self._filter(column, lambda v: v is not None and _comparable(v) < _comparable(value))

    def order(self, column):
        self._check(column)
        self._order = column
        return self

    def _matching(self):
        return [r for r in self._rows if all(test(r[c]) for c, test in self._filters)]

    def range(self, start, end):
        if self._order is None:
            raise AssertionError(f"{self.name}: range() without order() pages a table unstably")
        rows = sorted(self._matching(), key=lambda r: r[self._order])
        self._page = rows[start : min(end + 1, start + self._cap)]
        return self

    def execute(self):
        if self._update is not None:
            if not self._filters:
                raise AssertionError(f"{self.name}: update() with no filter rewrites every row")
            rows = self._matching()
            for r in rows:
                r.update(self._update)
            self._writes.append((self.name, self._update, sorted(r["id"] for r in rows)))
            return _Result([dict(r) for r in rows])
        rows = self._page if self._page is not None else self._matching()[: self._cap]
        return _Result([{c: r[c] for c in self._columns} for r in rows])


class _Supabase:
    def __init__(self, tables, cap=10):
        self._tables = tables
        self._cap = cap
        self.writes = []

    def table(self, name):
        if name not in self._tables:
            raise AssertionError(f"no rows seeded for table {name!r}")
        return _Table(name, self._tables[name], self._cap, self.writes)


# Fractional seconds trimmed as PostgREST returns them, not padded to 3 or 6 digits.
RAN = ("2026-11-18T21:00:40.8078+00:00", "2026-11-18T21:09:23.4+00:00")


def queue_row(req_id, *, status="completed", ran=RAN, error=None):
    return {"id": req_id, "status": status, "processed_at": ran[0], "completed_at": ran[1], "error_message": error}


def click(click_id, team_id, when_utc, *, game_date, request_id=None, reported=None):
    return {
        "id": click_id,
        "team_id_master": team_id,
        "game_date": game_date,
        "clicked_at": when_utc,
        "scrape_request_id": request_id,
        "reported_at": reported,
    }


def clicked(game_date, request=None, request_id="req"):
    """A click as fetch_clicks hands it on, with its queue request attached."""
    return {**click("c", "a", "", game_date=game_date, request_id=request_id), "request": request}


# --- the window ------------------------------------------------------------------------------


def test_the_window_ends_on_the_latest_three_hour_utc_boundary():
    assert img.window_end(datetime(2026, 11, 16, 13, 50, tzinfo=UTC)) == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert img.window_end(datetime(2026, 11, 16, 12, 0, tzinfo=UTC)) == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert img.window_end(datetime(2026, 11, 17, 2, 59, tzinfo=UTC)) == datetime(2026, 11, 17, 0, 0, tzinfo=UTC)
    assert img.window_end(datetime(2026, 11, 17, 3, 50, tzinfo=UTC)) == datetime(2026, 11, 17, 3, 0, tzinfo=UTC)
    assert img.window_end(datetime(2026, 11, 17, 21, 50, tzinfo=UTC)) == datetime(2026, 11, 17, 21, 0, tzinfo=UTC)


def test_the_window_is_labelled_in_arizona_time():
    def label(start_hour, day=16):
        start = datetime(2026, 11, day, start_hour, tzinfo=UTC)
        return img.window_label(start, start + timedelta(hours=3))

    assert label(21) == "Mon Nov 16, 2 PM to 5 PM Arizona time"
    assert label(6) == "Sun Nov 15, 11 PM to Mon Nov 16, 2 AM Arizona time"
    assert label(15) == "Mon Nov 16, 8 AM to 11 AM Arizona time"
    assert label(18) == "Mon Nov 16, 11 AM to 2 PM Arizona time"


def test_a_hand_run_window_off_the_hour_keeps_its_minutes():
    start = datetime(2026, 11, 16, 15, 30, tzinfo=UTC)

    assert img.window_label(start, start + timedelta(hours=3)) == "Mon Nov 16, 8:30 AM to 11:30 AM Arizona time"


def test_midnight_and_noon_read_as_twelve():
    assert img.clock(datetime(2026, 11, 16, 0)) == "12 AM"
    assert img.clock(datetime(2026, 11, 16, 12)) == "12 PM"
    assert img.clock(datetime(2026, 11, 16, 13, 5)) == "1:05 PM"


def test_dates_read_as_a_weekday_month_and_day():
    assert img.nice_date("2026-11-07") == "Sat Nov 7"
    assert img.nice_date(date(2026, 9, 12)) == "Sat Sep 12"


def test_fetch_clicks_reads_the_window_past_the_cap_and_attaches_each_queue_request():
    start, end = datetime(2026, 11, 16, 12, tzinfo=UTC), datetime(2026, 11, 16, 15, tzinfo=UTC)
    clicks = [
        click("c1", "t1", "2026-11-16T12:00:00+00:00", game_date="2026-11-15", request_id="q1"),
        click("c2", "t2", "2026-11-16T14:59:59+00:00", game_date="2026-11-15", request_id="q2"),
        click("c3", "t3", "2026-11-16T11:59:59+00:00", game_date="2026-11-15", request_id="q1"),
        click("c4", "t4", "2026-11-16T15:00:00+00:00", game_date="2026-11-15", request_id="q1"),
        click("c5", "t5", "2026-11-16T13:30:00+00:00", game_date="2026-11-15"),
    ]
    sb = _Supabase({"missing_game_clicks": clicks, "scrape_requests": [queue_row("q1"), queue_row("q9")]}, cap=2)

    fetched = img.fetch_clicks(sb, start, end)

    assert [(c["id"], c["request"]) for c in fetched] == [
        ("c1", queue_row("q1")),
        ("c5", None),
        ("c2", None),
    ]


def test_fetch_unreported_clicks_reads_every_unstamped_click_before_the_end_past_the_cap():
    end = datetime(2026, 11, 16, 15, tzinfo=UTC)
    clicks = [
        click("c1", "t1", "2026-11-14T02:00:00+00:00", game_date="2026-11-13", request_id="q1"),
        click("c2", "t2", "2026-11-16T14:59:59+00:00", game_date="2026-11-15"),
        click("c3", "t3", "2026-11-15T09:00:00+00:00", game_date="2026-11-15", reported="2026-11-15T12:50:00+00:00"),
        click("c4", "t4", "2026-11-16T15:00:00+00:00", game_date="2026-11-15"),
        click("c5", "t5", "2026-11-16T03:30:00+00:00", game_date="2026-11-15", request_id="q9"),
    ]
    sb = _Supabase({"missing_game_clicks": clicks, "scrape_requests": [queue_row("q1")]}, cap=2)

    fetched = img.fetch_unreported_clicks(sb, end)

    assert [(c["id"], c["request"]) for c in fetched] == [
        ("c1", queue_row("q1")),
        ("c5", None),
        ("c2", None),
    ]


# --- candidate rows --------------------------------------------------------------------------


def test_neighbour_ages_skip_the_folded_u18_and_pass_an_unknown_label_through():
    assert img.neighbour_ages("u17") == ["u16", "u17", "u19"]
    assert img.neighbour_ages("u19") == ["u17", "u19"]
    assert img.neighbour_ages("u7") == ["u7", "u8"]
    assert img.neighbour_ages("u20") == ["u20"]


def test_fetch_pool_reads_same_gender_neighbour_ages_and_stateless_rows_past_the_cap():
    target = team("t0", "Rush U10B", age="u10")
    keep = [
        team("t1", "Rush 2016 Blue", age="u11"),
        team("t2", "Rush U10 Red", age="u9"),
        team("t3", "Rush 2017 Blue", age="u10", state=None),
        team("t4", "Rush 2017 White", age="u10"),
    ]
    drop = [
        team("t5", "Rush U10G", gender="Female"),
        team("t6", "Rush U12", age="u12"),
        team("t7", "Rush U10 AZ", state="AZ"),
        {**team("t8", "Rush U10 old"), "is_deprecated": True},
    ]
    sb = _Supabase({"teams": [target, *keep, *drop]}, cap=2)

    assert sorted(r["team_id_master"] for r in img.fetch_pool(sb, target)) == ["t1", "t2", "t3", "t4"]


def test_a_stateless_team_is_compared_only_with_stateless_rows():
    target = team("t0", "Rush U10B", state=None)
    sb = _Supabase({"teams": [target, team("t1", "Rush U10 Red", state=None), team("t2", "Rush U10 Blue")]})

    assert [r["team_id_master"] for r in img.fetch_pool(sb, target)] == ["t1"]


def test_a_fuzzy_score_from_080_admits_a_candidate():
    a = team("a", "Rush 2015 Blue", club="Rush")

    assert img.name_match(a, team("b", "Rush 2015 Blue Elite", club="Colorado Rush")) == pytest.approx(0.8235, abs=1e-4)
    assert img.name_match(a, team("b", "Rush 2015 Blue Premier", club="Colorado Rush")) is None


def test_names_stating_different_cohorts_never_match_however_alike():
    assert img.name_match(team("a", "Rush U10B"), team("b", "Rush 17/18B")) is None


def test_names_with_different_squad_words_do_not_match():
    assert img.name_match(team("a", "Rush 2015 Blue"), team("b", "Rush 2015 Red")) is None


@pytest.mark.parametrize(
    "mine, other",
    [
        ("Rush 2014 ECNL", "Rush 2014 ECNL RL"),
        ("Rush 2014 Boys Blue", "Rush 2014 Girls Blue"),
        ("Rush 2014 Blue", "Rush 2014 Blue MLS Next"),
    ],
    ids=["ECNL against ECNL RL", "boys against girls", "an MLS division"],
)
def test_a_high_fuzzy_score_across_a_league_gender_or_division_is_refused(mine, other):
    assert img.name_match(team("a", mine), team("b", other)) is None


def test_a_club_spelled_two_ways_matches_through_its_squad_words():
    a = team("a", "ESC- 2015 Purple", club="Colorado Edge")
    b = team("b", "EDGE Purple 15B", club="Colorado Edge")

    assert img.name_match(a, b) == 1.0


@pytest.mark.parametrize(
    "mine, other",
    [("ESC- 2015 Purple", "EDGE Purple 15B MLS Next"), ("ESC 2015 Purple NPL", "EDGE Purple 15B DPL")],
    ids=["an MLS division", "a different league"],
)
def test_squad_words_do_not_match_across_a_division_or_league(mine, other):
    a, b = team("a", mine, club="Colorado Edge"), team("b", other, club="Colorado Edge")

    assert img.name_match(a, b) is None


def test_two_unknown_team_rows_of_one_club_are_not_one_squad():
    """Both read the squad key {unknown, team}, which every "Unknown team" row shares."""
    a, b = team("a", "Unknown team", club="Colorado Edge"), team("b", "Unknown team", club="Colorado Edge")

    assert img.name_match(a, b) is None


def test_squad_words_match_only_under_the_same_club():
    a = team("a", "ESC- 2015 Purple", club="Colorado Edge")
    b = team("b", "EDGE Purple 15B", club="Edge United")

    assert img.name_match(a, b) is None


# --- duplicate rules -------------------------------------------------------------------------


def reason(games, *, requested=(), score=0.5):
    sched, self_play = schedule(games, ["a", "b"])
    return img.duplicate_reason("a", "b", sched, self_play, set(requested), score)


def test_rows_that_played_each_other_are_two_squads():
    assert reason([game("g1", "a", "b", day(10)), game("g2", "a", "x", day(20)), game("g3", "b", "x", day(20))]) is None


def test_the_same_game_on_both_rows_is_the_strongest_sign():
    games = [game("g1", "a", "x", day(20), score=(2, 1)), game("g2", "x", "b", day(20), score=(1, 2))]

    assert reason(games) == "1 game saved on both teams (same opponent, same day)"


def test_the_same_opponent_on_one_day_with_another_score_is_two_games():
    games = [game("g1", "a", "x", day(20), score=(3, 0)), game("g2", "b", "x", day(20), score=(0, 2))]

    assert reason(games) is None


def test_a_hidden_copy_is_not_a_game_stored_twice():
    assert reason([game("g1", "a", "x", day(20)), game("g2", "b", "x", day(20), excluded=True)]) is None


def test_different_games_on_one_day_mean_two_squads():
    assert reason([game("g1", "a", "x", day(20)), game("g2", "b", "y", day(20))], requested=[day(20)], score=1) is None


def test_a_game_stored_twice_does_not_outweigh_different_games_on_another_day():
    games = [
        game("g1", "a", "x", day(20)),
        game("g2", "b", "x", day(20)),
        game("g3", "a", "y", day(30)),
        game("g4", "b", "z", day(30)),
    ]

    assert reason(games) is None


def test_a_row_holding_an_extra_game_on_the_doubled_day_still_reads_as_one_squad():
    games = [game("g1", "a", "x", day(20)), game("g2", "b", "x", day(20)), game("g3", "a", "y", day(20))]

    assert reason(games) == "1 game saved on both teams (same opponent, same day)"


def test_a_blank_fixture_and_its_scored_copy_are_one_game():
    games = [game("g1", "a", "x", day(20), score=(None, None)), game("g2", "x", "b", day(20), score=(0, 2))]

    assert reason(games) == "1 game saved on both teams (same opponent, same day)"


def test_two_half_scored_games_against_one_opponent_are_two_games():
    games = [game("g1", "a", "x", day(20), score=(3, None)), game("g2", "b", "x", day(20), score=(0, None))]

    assert reason(games) is None


def test_playing_each_other_on_a_day_with_a_game_stored_twice_still_means_two_squads():
    games = [game("g1", "a", "x", day(20)), game("g2", "b", "x", day(20)), game("g3", "a", "b", day(20))]

    assert reason(games) is None


def test_different_extra_games_on_a_day_with_a_game_stored_twice_mean_two_squads():
    games = [
        game("g1", "a", "x", day(20)),
        game("g2", "b", "x", day(20)),
        game("g3", "a", "y", day(20)),
        game("g4", "b", "z", day(20)),
    ]

    assert reason(games) is None


@pytest.mark.parametrize("fused", ["a", "b"])
def test_a_row_that_plays_itself_is_never_a_duplicate(fused):
    games = [game("g1", "a", "x", day(10)), game("g2", "b", "y", day(20)), game("g3", fused, fused, day(5))]

    assert reason(games, requested=[day(20)]) is None


def test_a_row_holding_the_requested_game_is_named():
    games = [game("g1", "a", "x", day(10)), game("g2", "b", "y", day(20))]

    assert reason(games, requested=[day(20)]) == f"has a game on the date asked about ({img.nice_date(day(20))})"


def test_a_schedule_split_across_two_rows_needs_two_shared_opponents_this_season():
    split = [
        game("g1", "a", "x", day(10)),
        game("g2", "a", "y", day(11)),
        game("g3", "b", "x", day(30)),
        game("g4", "b", "y", day(31)),
    ]
    one = split[:3]
    last_season = [game("g5", "b", "y", day(-30)), *one]

    assert reason(split) == "2 of the same opponents this season, never on the same day"
    assert reason(one) is None
    assert reason(last_season) is None


def test_a_name_alone_counts_from_090():
    games = [game("g1", "a", "x", day(10))]

    assert reason(games, score=0.90) == "same name; their games don't say either way"
    assert reason(games, score=0.89) is None


def test_the_season_starts_on_the_last_august_first():
    today = date.today()

    assert img.SEASON_START == f"{today.year if today.month >= 8 else today.year - 1}-08-01"


# --- profile ---------------------------------------------------------------------------------


def test_a_name_stating_another_age_is_flagged():
    findings = img.name_age_findings(team("a", "Rush U12 Boys Blue", age="u13"))

    assert [f.title for f in findings] == ["Name says u12, but it's on the u13 board"]


def test_a_bare_birth_year_fitting_either_of_its_ages_is_not_flagged():
    assert img.name_age_findings(team("a", "Rush 2015 Boys", age="u11")) == []
    assert img.name_age_findings(team("a", "Rush 2015 Boys", age="u12")) == []


def test_the_registered_name_is_read_too():
    findings = img.name_age_findings(team("a", "Rush Blue", age="u13", original="Rush U12 Blue"))

    assert [f.title for f in findings] == ["Name says u12, but it's on the u13 board"]


def opponent_case(names, *, own="Rush B2016 Samba", stored="u11", when=None, hidden=()):
    opponents = {f"o{i}": {"team_id_master": f"o{i}", "team_name": n} for i, n in enumerate(names)}
    games = [game(f"g{i}", "a", o, when or day(10 + i), excluded=i in hidden) for i, o in enumerate(opponents)]
    return img.opponent_age_findings(team("a", own, age=stored), schedule(games, ["a"])[0], opponents)


def test_opponents_whose_names_agree_on_another_age_are_flagged():
    findings = opponent_case(["X U10", "Y U10", "Z 2016/17", "W U10B"])

    assert [(f.title, f.details) for f in findings] == [
        (
            "This season's opponents are mostly u10, but it's on the u11 board",
            ["4 of 4 opponents whose names give an age are u10"],
        )
    ]


def test_three_of_four_is_enough():
    assert [f.title for f in opponent_case(["X U10", "Y U10", "Z U10", "W U11"])] == [
        "This season's opponents are mostly u10, but it's on the u11 board"
    ]


def test_opponents_agreeing_with_the_stored_age_say_nothing():
    assert opponent_case(["X U11", "Y U11", "Z U11", "W U11"]) == []


def test_too_few_age_stating_opponents_say_nothing():
    assert opponent_case(["X U10", "Y U10", "Z U10", "W 2016 Red"]) == []


def test_an_opponent_naming_two_ages_is_no_witness():
    assert opponent_case(["X U10", "Y U10", "Z U10", "W U10/U11"]) == []


def test_a_split_opposition_says_nothing():
    assert opponent_case(["X U10", "Y U10", "Z U11", "W U11"]) == []


def test_last_season_s_opponents_are_not_witnesses():
    assert opponent_case(["X U10", "Y U10", "Z U10", "W U10"], when=day(-30)) == []


def test_hidden_games_are_not_witnesses():
    assert opponent_case(["X U10", "Y U10", "Z U10", "W U10"], hidden=[3]) == []


def test_u18_opponents_count_for_the_u19_board():
    assert opponent_case(["X U18", "Y U18", "Z U18", "W U18"], own="Rush 2008 Girls", stored="u19") == []


@pytest.mark.parametrize("own", ["Novi Pre MLS U10 Boys 1", "Novi U12 Boys"], ids=["agrees", "disagrees"])
def test_a_name_stating_its_own_age_is_not_measured_against_its_opponents(own):
    assert opponent_case(["X U11", "Y U11", "Z U11", "W U11"], own=own, stored="u10") == []


def test_gender_against_the_name_and_a_missing_state_are_flagged():
    titles = [f.title for f in img.gender_and_state_findings(team("a", "Rush U10 Girls", state=None))]

    assert titles == ["Name says girls, but it's saved as boys", "No state"]


# --- providers -------------------------------------------------------------------------------


def alias(team_id, provider, pid):
    return {"team_id_master": team_id, "provider_id": provider, "provider_team_id": pid}


def test_a_team_with_no_gotsport_link_cannot_be_scraped():
    findings = img.provider_findings(
        team("a", "Rush U10", provider=SINC), [alias("a", TGS, "9")], PROVIDER_CODES, False
    )

    assert findings[0].title == "No GotSport link, so the scrape can't reach this team"
    assert findings[0].details == ["Linked only to: sincsports, tgs"]


def test_a_placeholder_gotsport_id_is_no_link():
    findings = img.provider_findings(team("a", "Rush U10", provider=GS, pid="None"), [], PROVIDER_CODES, False)

    assert findings[0].title == "No GotSport link, so the scrape can't reach this team"


def test_a_gotsport_alias_on_a_row_from_another_provider_is_a_link():
    t = team("a", "Rush U10", provider=SINC)

    findings = img.provider_findings(t, [alias("a", GS, "123")], PROVIDER_CODES, still_missing=True)

    assert [f.title for f in findings] == ["Also gets games from sources this scrape doesn't read"]
    assert findings[0].details == ["SincSports tournaments: imported by hand, a month at a time"]


def test_other_providers_are_left_out_once_the_requested_game_is_on_record():
    findings = img.provider_findings(team("a", "Rush U10"), [alias("a", TGS, "9")], PROVIDER_CODES, still_missing=False)

    assert findings == []


def test_a_provider_without_a_refresh_note_is_named_by_its_code():
    findings = img.provider_findings(
        team("a", "Rush U10", provider="p-new"), [alias("a", GS, "1")], {**PROVIDER_CODES, "p-new": "newcomer"}, True
    )

    assert findings[0].details == ["newcomer: not read by the GotSport scrape; check that provider's own import"]


def test_three_gotsport_registrations_on_one_row_are_flagged():
    t = team("a", "Rush U10", pid="1")

    findings = img.provider_findings(t, [alias("a", GS, "2"), alias("a", GS, "3")], PROVIDER_CODES, False)

    assert [f.title for f in findings] == ["3 GotSport registrations on one team"]


def test_the_workflow_never_runs_a_dry_run_into_its_public_log():
    """A dry run prints the report, team names and stored error text included, and this repo's
    Actions logs are public."""
    path = os.path.join(ROOT, ".github", "workflows", "investigate-missing-game-requests.yml")
    with open(path, encoding="utf-8") as fh:
        workflow = "\n".join(line.split("#", 1)[0] for line in fh)

    assert "--dry-run" not in workflow
    assert "dry_run" not in workflow


def test_every_workflow_and_importer_the_refresh_notes_name_exists():
    named = " ".join(img.PROVIDER_REFRESH.values())
    workflows = re.findall(r"[\w-]+\.yml", named)
    importers = re.findall(r"import_\w+\.py", named)

    assert workflows and importers
    missing = [w for w in workflows if not os.path.exists(os.path.join(ROOT, ".github", "workflows", w))]
    missing += [s for s in importers if not os.path.exists(os.path.join(ROOT, "scripts", s))]
    assert missing == []


# --- the scrape ------------------------------------------------------------------------------


def result_for(request, games=(), request_id="req"):
    return img.scrape_result(clicked(day(20), request, request_id), fixtures_for("a", list(games)))


def test_each_click_states_how_its_scrape_ended():
    def failed(error):
        return result_for(queue_row("q", status="failed", error=error)).outcome

    assert result_for(queue_row("q")).outcome == "Nothing new"
    assert failed(None) == "Scrape failed: no reason given"
    assert failed("x" * 200) == f"Scrape failed: {'x' * 160}"
    assert failed("403 for url: https://api.zenrows.com/v1/?apikey=S3CRET&url=x") == (
        "Scrape failed: 403 for url: https://api.zenrows.com/v1/?apikey=<redacted>&url=x"
    )
    assert failed("Team 740723 not found on gotsport (404) - the provider_team_id may be outdated.") == (
        "Scrape failed: GotSport has no page for this team's id any more"
    )
    assert failed("No scraper available for provider 'tgs' and no GotSport alias found") == (
        "Scrape failed: not a GotSport team, and it has no GotSport link to scrape instead"
    )
    assert failed("WAF blocked: 403") == "Scrape failed: GotSport blocked the request"
    assert result_for(queue_row("q", status="pending")).outcome == "Scrape hasn't run yet"
    assert result_for(queue_row("q", status="processing")).outcome == "Scrape is still running"
    assert result_for(None, request_id=None).outcome == (
        "Not scraped for this date: the team already had a scrape waiting for another date or GotSport id"
    )
    assert result_for(None).outcome == "Scrape record no longer on file"
    assert result_for(queue_row("q", ran=(None, RAN[1]))).outcome == (
        "Scrape finished, but its start time wasn't saved, so new games can't be counted"
    )


def test_games_first_saved_while_the_scrape_ran_are_new():
    games = [
        game("before", "a", "x", day(1), created="2026-11-18T21:00:40.8+00:00"),
        game("start", "a", "x", day(2), created="2026-11-18T21:00:40.8078+00:00"),
        game("during", "x", "a", day(3), created="2026-11-18T21:05:00.12345+00:00"),
        game("slack", "a", "x", day(4), created="2026-11-18T21:10:23.4+00:00"),
        game("after", "a", "x", day(5), created="2026-11-18T21:10:23.5+00:00"),
    ]

    result = result_for(queue_row("q"), games)

    assert [f.game["id"] for f in result.added] == ["start", "during", "slack"]
    assert result.scored == []
    assert result.outcome == "Added 3 new games"


def test_a_score_filled_onto_a_game_already_on_record_counts_once():
    games = [
        game("filled", "a", "x", day(1), scraped="2026-11-18T21:04:00+00:00"),
        game("blank", "a", "x", day(2), score=(None, None), scraped="2026-11-18T21:04:00+00:00"),
        game("half", "a", "x", day(3), score=(2, None), scraped="2026-11-18T21:04:00+00:00"),
        game("earlier", "a", "x", day(4), scraped="2026-11-18T20:59:00+00:00"),
        game("never", "a", "x", day(5), scraped=None),
        game("new", "a", "x", day(6), created="2026-11-18T21:05:00+00:00", scraped="2026-11-18T21:04:00+00:00"),
        game("late", "a", "x", day(7), created="2026-11-18T21:12:00+00:00", scraped="2026-11-18T21:04:00+00:00"),
        game("unsaved", "a", "x", day(8), created=None, scraped="2026-11-18T21:04:00+00:00"),
    ]

    result = result_for(queue_row("q"), games)

    assert [f.game["id"] for f in result.added] == ["new"]
    assert [f.game["id"] for f in result.scored] == ["filled"]
    assert result.outcome == "Added 1 new game and 1 missing score"


def test_a_scrape_that_only_filled_a_score_says_so():
    games = [game("filled", "a", "x", day(1), scraped="2026-11-18T21:04:00+00:00")]

    assert result_for(queue_row("q"), games).outcome == "Added 1 missing score"


def test_a_failed_or_waiting_scrape_brings_nothing_in():
    games = [game("during", "a", "x", day(3), created="2026-11-18T21:05:00+00:00")]

    for request in (
        queue_row("q", status="failed"),
        queue_row("q", status="pending"),
        queue_row("q", status="processing"),
        None,
    ):
        result = result_for(request, games)
        assert (result.added, result.scored) == ([], [])


def test_games_read_from_the_team_s_side_newest_first():
    games = [
        game("g1", "x", "a", "2026-11-14", score=(4, 1)),
        game("g2", "a", "y", "2026-11-15", excluded=True, score=(None, None)),
        game("g3", "a", "z", "2026-11-16", score=(2, 2)),
        game("g4", "a", None, "2026-11-13", score=(3, 0)),
        game("g5", "a", "x", "2026-11-12", score=(0, 1)),
    ]
    names = {"x": {"team_id_master": "x", "team_name": "Opp X"}, "y": {"team_id_master": "y", "team_name": "Opp Y"}}

    lines = img.game_lines(fixtures_for("a", games), names)

    assert lines == [
        "Mon Nov 16 vs unknown opponent: tied 2-2",
        "Sun Nov 15 vs Opp Y: no score yet (hidden)",
        "Sat Nov 14 vs Opp X: lost 1-4",
        "Fri Nov 13 vs unknown opponent: won 3-0",
        "Thu Nov 12 vs Opp X: lost 0-1",
    ]


def test_a_hidden_game_on_the_requested_date_is_flagged_only_when_nothing_visible_is_there():
    hidden = fixtures_for("a", [game("g1", "a", "x", day(20), excluded=True)])
    both = fixtures_for("a", [game("g1", "a", "x", day(20), excluded=True), game("g2", "a", "x", day(20))])

    assert img.hidden_game_finding({day(20)}, hidden).title == "The game on that date is hidden"
    assert img.hidden_game_finding({day(20)}, both) is None


# --- composition -----------------------------------------------------------------------------


WINDOW = (datetime(2026, 11, 16, 12, tzinfo=UTC), datetime(2026, 11, 16, 15, tzinfo=UTC))


def investigate_window(sb):
    return img.investigate(sb, img.fetch_clicks(sb, *WINDOW))


# Inside RAN, the run that drained q2.
DURING = "2026-11-18T21:05:00+00:00"


def _world(**overrides):
    """One clicked team, filed under a merged-away id, with a duplicate row holding the game.

    `dup` holds the requested game; `kept` is a duplicate by every rule but the owner chose
    Keep separate; `far` is a similar name in another state; `t-live` is a live row already
    merged into the target. The second click's scrape saved g6 under the merged-away id and
    filled in g7's score.
    """
    asked = day(20)
    tables = {
        "missing_game_clicks": [
            click("c1", "t-old", "2026-11-16T13:00:00+00:00", game_date=asked, request_id="q1"),
            click("c2", "t", "2026-11-16T14:00:00+00:00", game_date=asked, request_id="q2"),
        ],
        "scrape_requests": [queue_row("q1", status="failed"), queue_row("q2")],
        "team_merge_map": [
            {"id": 1, "deprecated_team_id": "t-old", "canonical_team_id": "t"},
            {"id": 2, "deprecated_team_id": "t-live", "canonical_team_id": "t"},
        ],
        "team_cleanup_decisions": [
            {
                "id": 1,
                "team_id_master": "t",
                "other_team_id": "kept",
                "decided_at": "2026-10-01T00:00:00+00:00",
                "source": "owner",
                "superseded_at": None,
                "decision": "keep_separate",
            }
        ],
        "providers": PROVIDERS,
        "teams": [
            team("t", "Rush 2016 Blue", age="u10", provider=SINC, original="Rush B2016 Blue"),
            team("dup", "Rush B2016 Blue", age="u11"),
            team("kept", "Rush 2016 Blue", age="u10"),
            team("far", "Rush 2016 Blue", state="AZ"),
            team("t-live", "Rush 2016 Blue"),
            team("x", "Opp U10"),
            team("y", "Opp U11"),
        ],
        "games": [
            game("g1", "t-old", "x", day(19)),
            game("g2", "dup", "y", asked),
            game("g3", "kept", "y", asked),
            game("g4", "far", "y", asked),
            game("g5", "dup", "x", day(5), excluded=True),
            game("g6", "y", "t-old", day(18), score=(3, 2), created=DURING, scraped=DURING),
            game("g7", "t", "x", day(17), score=(0, 0), scraped=DURING),
        ],
        "team_alias_map": [
            {**alias("t", SINC, "S1"), "id": 1, "review_status": "approved"},
            {**alias("t-old", TGS, "T1"), "id": 2, "review_status": "approved"},
            {**alias("t", GS, "G1"), "id": 3, "review_status": "pending"},
        ],
    }
    tables.update(overrides)
    return _Supabase(tables)


def test_a_window_is_investigated_end_to_end_through_the_database():
    reports, caveats = investigate_window(_world())

    assert caveats == []
    [report] = reports
    assert [c["id"] for c in report.clicks] == ["c1", "c2"]
    assert [f.title for f in report.findings] == [
        "Possible duplicate team",
        "No GotSport link, so the scrape can't reach this team",
        "Also gets games from sources this scrape doesn't read",
    ]
    assert [(row["team_id_master"], text) for row, text in report.findings[0].teams] == [
        (
            "dup",
            f"(u11, Rush, gotsport, 1 game, last {img.nice_date(day(20))}, {day(20)[:4]}): "
            f"has a game on the date asked about ({img.nice_date(day(20))})",
        )
    ]
    assert report.findings[0].details == ["Left out 1 similar team you already marked Keep separate"]
    assert report.findings[1].details == ["Linked only to: sincsports, tgs"]
    assert report.outcomes == ["Scrape failed: no reason given", "Added 1 new game and 1 missing score"]
    assert report.new_games == [f"{img.nice_date(day(18))} vs Opp U11: lost 2-3"]
    assert report.scored_games == [f"{img.nice_date(day(17))} vs Opp U10: tied 0-0"]


def test_two_clicks_on_one_scrape_list_its_games_once():
    world = _world()
    world._tables["missing_game_clicks"].append(
        click("c3", "t", "2026-11-16T14:30:00+00:00", game_date=day(19), request_id="q2")
    )

    [report] = investigate_window(world)[0]

    assert report.outcomes == ["Scrape failed: no reason given", "Added 1 new game and 1 missing score"]
    assert (len(report.new_games), len(report.scored_games)) == (1, 1)


# A run after RAN.
LATER = ("2026-11-18T22:00:00+00:00", "2026-11-18T22:05:00+00:00")


def test_two_scrapes_that_each_added_a_game_are_both_reported():
    world = _world()
    world._tables["scrape_requests"] = [queue_row("q1"), queue_row("q2", ran=LATER)]
    world._tables["games"] = [
        game("g6", "y", "t", day(18), created="2026-11-18T21:05:00+00:00"),
        game("g8", "t", "x", day(16), created="2026-11-18T22:02:00+00:00"),
    ]

    [report] = investigate_window(world)[0]

    assert report.outcomes == ["Added 1 new game", "Added 1 new game"]
    assert len(report.new_games) == 2


def test_a_game_new_in_one_scrape_and_scored_in_the_next_is_listed_once():
    world = _world()
    world._tables["missing_game_clicks"].append(
        click("c3", "t", "2026-11-16T14:30:00+00:00", game_date=day(19), request_id="q3")
    )
    world._tables["scrape_requests"].append(queue_row("q3", ran=LATER))
    world._tables["games"] = [
        game("g6", "y", "t", day(18), score=(3, 2), created="2026-11-18T21:05:00+00:00", scraped=LATER[0]),
    ]

    [report] = investigate_window(world)[0]

    assert report.outcomes == ["Scrape failed: no reason given", "Added 1 new game", "Added 1 missing score"]
    assert report.new_games == [f"{img.nice_date(day(18))} vs Opp U11: lost 2-3"]
    assert report.scored_games == []


def test_other_sources_drop_out_once_the_requested_game_lands():
    world = _world()
    world._tables["games"].append(game("g9", "t", "x", day(20)))

    [report] = investigate_window(world)[0]

    assert "Also gets games from sources this scrape doesn't read" not in [f.title for f in report.findings]


def test_a_hidden_requested_game_is_still_missing():
    world = _world()
    world._tables["games"].append(game("g9", "t", "x", day(20), excluded=True))

    [report] = investigate_window(world)[0]

    titles = [f.title for f in report.findings]
    assert "The game on that date is hidden" in titles
    assert "Also gets games from sources this scrape doesn't read" in titles


def test_a_clicked_row_that_plays_itself_says_so_and_suggests_no_duplicate():
    world = _world()
    world._tables["games"].append(game("g9", "t", "t-old", day(3)))

    [report] = investigate_window(world)[0]

    titles = [f.title for f in report.findings]
    assert "Has a game against itself" in titles
    assert "Possible duplicate team" not in titles


def test_unreadable_keep_separate_decisions_are_reported_rather_than_fatal():
    reports, caveats = investigate_window(_world(team_cleanup_decisions=[{"id": 1}]))

    assert caveats == ["Keep-separate decisions could not be read, so pairs already kept apart may be listed."]
    duplicates = reports[0].findings[0]
    assert [row["team_id_master"] for row, _ in duplicates.teams] == ["dup", "kept"]
    assert duplicates.details == []


def test_a_request_for_a_missing_team_row_becomes_a_caveat():
    world = _world()
    world._tables["missing_game_clicks"].append(click("c3", "ghost", "2026-11-16T14:30:00+00:00", game_date=day(20)))

    reports, caveats = investigate_window(world)

    assert [r.team["team_id_master"] for r in reports] == ["t"]
    assert caveats == ["A clicked team could not be found (ghost)"]


def test_teams_with_more_to_look_at_come_first():
    world = _world()
    world._tables["teams"].append(team("calm", "Aaa Calm U10"))
    world._tables["missing_game_clicks"].append(click("c3", "calm", "2026-11-16T14:30:00+00:00", game_date=day(20)))

    reports, _ = investigate_window(world)

    assert [r.team["team_id_master"] for r in reports] == ["t", "calm"]
    assert reports[1].findings == []


def test_a_window_with_no_clicks_has_no_reports():
    assert investigate_window(_world(missing_game_clicks=[])) == ([], [])


# --- delivery --------------------------------------------------------------------------------


def two_reports():
    flagged = img.TeamReport(
        team("a", "<script>alert(1)</script>"),
        [{"game_date": "2026-11-11"}],
        ["Added <b>"],
        [f"game {n}" for n in range(12)],
        ["<filled>"],
        [img.Finding("T&C", ["<i>"], "a<b", [(team("d", "Dup & Co"), "(u10) <why>")])],
    )
    calm = img.TeamReport(team("b", "Calm"), [{"game_date": "2026-11-14"}], ["Nothing new"])
    return [flagged, calm]


def test_the_subject_counts_teams_with_new_games_or_scores_and_teams_to_look_at():
    scores_only = img.TeamReport(team("s", "Scored"), [], ["Added 1 missing score"], [], ["a score"])
    two_flagged = img.TeamReport(team("f", "Flagged"), [], ["Nothing new"], findings=[img.Finding("x", [], "y")])

    assert img.subject(two_reports(), "LABEL") == (
        "PitchRank missing games: 2 teams, 1 with new games or scores, 1 needs a look (LABEL)"
    )
    assert img.subject([*two_reports(), scores_only, two_flagged], "LABEL") == (
        "PitchRank missing games: 4 teams, 2 with new games or scores, 2 need a look (LABEL)"
    )


def test_the_email_escapes_names_and_lists_what_each_scrape_added():
    body = img.render_html(two_reports(), ["<caveat>"], "LABEL")

    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "<i>" not in body and "<li>&lt;i&gt;</li>" in body
    assert "&lt;caveat&gt;</p>" in body
    assert ">Wed Nov 11</td>" in body and ">Sat Nov 14</td>" in body
    assert ">Added &lt;b&gt;</td>" in body and ">Nothing new</td>" in body
    assert "<b>New games (12)</b>" in body
    assert "<li>game 9</li>" in body and "game 10" not in body and "<li>and 2 more</li>" in body
    assert "<b>Scores filled in (1)</b>" in body and "<li>&lt;filled&gt;</li>" in body
    assert (
        "<li><a href='https://www.pitchrank.io/teams/d' style='color:#0B5345'>Dup &amp; Co</a> (u10) &lt;why&gt;</li>"
        in body
    )
    assert "What to do: a&lt;b</p>" in body
    assert ">T&amp;C</p></td>" in body
    assert ">None</span></td>" in body
    assert body.count("<h3") == 1


def test_a_team_with_only_problems_or_only_filled_scores_gets_its_own_section():
    problems_only = img.TeamReport(
        team("p", "Problem Team"),
        [{"game_date": "2026-11-11"}],
        ["Nothing new"],
        findings=[img.Finding("Possible duplicate team", [], "Ask Claude.", [(team("d", "Dup Team"), "(u10)")])],
    )
    scores_only = img.TeamReport(
        team("s", "Scored Team"), [{"game_date": "2026-11-11"}], ["Added 1 missing score"], [], ["a score"]
    )

    body = img.render_html([problems_only, scores_only], [], "LABEL")

    assert body.count("<h3") == 2
    assert "<a href='https://www.pitchrank.io/teams/d' style='color:#0B5345'>Dup Team</a>" in body
    assert "<b>Scores filled in (1)</b>" in body and "<li>a score</li>" in body
    assert "font-weight:bold; color:#0B5345'>Added 1 missing score</td>" in body
    assert "text-align:left'>Nothing new</td>" in body


def test_the_text_report_lists_games_and_findings():
    text = img.render_text(two_reports(), ["caveat"], "LABEL")

    assert text.splitlines()[:3] == [
        "Missing-game requests, LABEL",
        "2 teams, 1 with new games or scores, 1 needs a look",
        "caveat",
    ]
    assert "<script>alert(1)</script> (u10 Boys, CO)\n" in text
    assert "Asked about: Wed Nov 11\nScrape: Added <b>\nNew games (12):\n  game 0\n" in text
    assert "  game 9\n  and 2 more\nScores filled in (1):\n  <filled>\n" in text
    assert (
        "Needs a look: T&C\n  Dup & Co (u10) <why> https://www.pitchrank.io/teams/d\n  <i>\n  What to do: a<b" in text
    )
    assert text.endswith(
        "Scrape: Nothing new\n\n"
        "This email only reports: it changes nothing. It comes every 3 hours when someone asked for a missing game."
    )


def test_a_team_label_says_when_there_is_no_state():
    assert img.team_label(team("a", "Rush", gender="Female", state=None, age="u12")) == "u12 Girls, no state"


def test_asked_about_lists_each_date_once_in_order():
    clicks = [{"game_date": "2026-11-14"}, {"game_date": "2026-11-11"}, {"game_date": "2026-11-14"}]

    assert img.asked_about(img.TeamReport(team("a", "Rush"), clicks, [])) == "Wed Nov 11, Sat Nov 14"


def test_ten_games_are_listed_without_a_more_line():
    assert img.listed([f"game {n}" for n in range(10)]) == [f"game {n}" for n in range(10)]
    assert img.listed([f"game {n}" for n in range(11)])[-1] == "and 1 more"


@pytest.fixture
def world(monkeypatch):
    sb = _world()
    monkeypatch.setattr(img, "get_client", lambda: sb)
    return sb


@pytest.fixture
def sent(world, monkeypatch):
    """Every email main() sends, as (to, subject, html)."""
    calls = []
    monkeypatch.setattr(img, "send_email", lambda to, subj, body: calls.append((to, subj, body)) or True)
    return calls


def freeze(monkeypatch, moment):
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(img, "datetime", _Clock)


def stamps(sb):
    return {c["id"]: c["reported_at"] for c in sb._tables["missing_game_clicks"]}


LABEL = "Mon Nov 16, 5 AM to 8 AM Arizona time"


def test_a_dry_run_prints_the_report_and_sends_and_stamps_nothing(world, sent, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00", "--dry-run"])

    assert img.main() == 0
    assert sent == []
    assert world.writes == []
    assert "Rush 2016 Blue" in capsys.readouterr().out


def test_a_live_run_emails_the_report_and_keeps_team_names_out_of_the_log(sent, monkeypatch, capsys, caplog):
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    with caplog.at_level("INFO"):
        assert img.main() == 0

    assert [(to, subj) for to, subj, _ in sent] == [
        (
            "pitchrankio@gmail.com",
            f"PitchRank missing games: 1 team, 1 with new games or scores, 1 needs a look ({LABEL})",
        )
    ]
    logged = capsys.readouterr().out + caplog.text
    assert "Rush" not in logged and "failed" not in logged


def test_a_live_run_stamps_each_click_it_emailed(world, sent, monkeypatch):
    freeze(monkeypatch, datetime(2026, 11, 16, 16, 5, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 0
    assert stamps(world) == {"c1": "2026-11-16T16:05:00+00:00", "c2": "2026-11-16T16:05:00+00:00"}


def test_a_scheduled_run_reports_the_window_that_closed_before_it(world, sent, monkeypatch):
    freeze(monkeypatch, datetime(2026, 11, 16, 15, 50, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x"])

    assert img.main() == 0
    assert sent[0][1].endswith(f"({LABEL})")
    assert stamps(world) == {"c1": "2026-11-16T15:50:00+00:00", "c2": "2026-11-16T15:50:00+00:00"}


def test_a_scheduled_run_also_reports_the_windows_a_skipped_run_never_reported(world, sent, monkeypatch):
    world._tables["missing_game_clicks"][1]["clicked_at"] = "2026-11-16T16:00:00+00:00"
    freeze(monkeypatch, datetime(2026, 11, 16, 21, 50, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x"])

    assert img.main() == 0
    assert sent[0][1].endswith("(Mon Nov 16, 5 AM to 2 PM Arizona time)")
    assert stamps(world) == {"c1": "2026-11-16T21:50:00+00:00", "c2": "2026-11-16T21:50:00+00:00"}


def test_a_scheduled_run_leaves_out_clicks_an_earlier_email_reported(world, sent, monkeypatch):
    world._tables["missing_game_clicks"][0]["reported_at"] = "2026-11-16T15:50:00+00:00"
    freeze(monkeypatch, datetime(2026, 11, 16, 21, 50, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x"])

    assert img.main() == 0
    [(_, _, body)] = sent
    assert "Scrape failed" not in body and "Added 1 new game and 1 missing score" in body
    assert stamps(world) == {"c1": "2026-11-16T15:50:00+00:00", "c2": "2026-11-16T21:50:00+00:00"}


def test_a_click_the_email_did_not_carry_stays_unstamped(world, monkeypatch):
    """Stamping covers the clicks the email was built from, so one saved while it was sending
    waits for the next email."""

    def send(to, subj, body):
        world._tables["missing_game_clicks"].append(click("c3", "t", "2026-11-16T14:30:00+00:00", game_date=day(20)))
        return True

    monkeypatch.setattr(img, "send_email", send)
    freeze(monkeypatch, datetime(2026, 11, 16, 15, 50, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x"])

    assert img.main() == 0
    assert stamps(world) == {"c1": "2026-11-16T15:50:00+00:00", "c2": "2026-11-16T15:50:00+00:00", "c3": None}


def test_a_click_the_queue_may_still_be_scraping_waits_for_the_next_run(world, sent, monkeypatch):
    freeze(monkeypatch, datetime(2026, 11, 16, 15, 40, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x"])

    assert img.main() == 0
    assert sent == []
    assert world.writes == []


def test_a_re_sent_window_keeps_the_time_each_click_was_first_reported(world, sent, monkeypatch):
    world._tables["missing_game_clicks"][0]["reported_at"] = "2026-11-16T15:50:00+00:00"
    freeze(monkeypatch, datetime(2026, 11, 16, 22, 0, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 0
    [(_, _, body)] = sent
    assert "Scrape failed" in body
    assert stamps(world) == {"c1": "2026-11-16T15:50:00+00:00", "c2": "2026-11-16T22:00:00+00:00"}


def test_an_end_with_an_offset_is_taken_as_given(sent, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T15:00+00:00"])

    assert img.main() == 0
    assert sent[0][1].endswith(f"({LABEL})")


def test_a_failed_send_fails_the_run_and_stamps_nothing(world, monkeypatch):
    monkeypatch.setattr(img, "send_email", lambda *a: False)
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 1
    assert world.writes == []


def test_a_quiet_window_sends_nothing(sent, monkeypatch):
    monkeypatch.setattr(img, "get_client", lambda: _world(missing_game_clicks=[]))
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 0
    assert sent == []


def test_a_click_on_a_team_that_cannot_be_found_is_still_emailed_and_stamped(world, sent, monkeypatch):
    world._tables["missing_game_clicks"][:] = [click("c9", "ghost", "2026-11-16T13:00:00+00:00", game_date=day(20))]
    freeze(monkeypatch, datetime(2026, 11, 16, 16, 0, tzinfo=UTC))
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 0
    [(_, _, body)] = sent
    assert "A clicked team could not be found (ghost)" in body
    assert stamps(world) == {"c9": "2026-11-16T16:00:00+00:00"}


def test_stamping_batches_the_clicks_under_the_uri_limit():
    rows = [click(f"c{n:03d}", "t", "2026-11-16T13:00:00+00:00", game_date=day(20)) for n in range(150)]
    sb = _Supabase({"missing_game_clicks": rows})

    assert img.mark_reported(sb, rows) == 150
    assert [len(ids) for _, _, ids in sb.writes] == [100, 50]
    assert all(r["reported_at"] for r in rows)


def test_stamping_counts_only_the_clicks_it_stamped():
    rows = [
        click("c1", "t", "2026-11-16T13:00:00+00:00", game_date=day(20), reported="2026-11-16T15:50:00+00:00"),
        click("c2", "t", "2026-11-16T14:00:00+00:00", game_date=day(20)),
    ]
    sb = _Supabase({"missing_game_clicks": rows})

    assert img.mark_reported(sb, rows) == 1
