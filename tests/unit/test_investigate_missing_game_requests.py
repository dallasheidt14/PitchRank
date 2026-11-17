"""Tests for the 3-hourly missing-game request investigation.

Each duplicate rule gets a fixture that breaks only that rule, because a pair breaking two
at once still dies when either guard is deleted.

The Supabase double evaluates the filters it is given, refuses a filter or a select naming a
column its rows lack (PostgREST answers 42703), projects rows to the selected columns, refuses
a range() that no order() precedes, and serves at most `cap` rows per response. Like
postgrest-py, which sends None as the text "None", its eq() and in_() never match NULL. It has
no write methods, so any write the script attempted would raise.

Fixture dates hang off the current season's start, because "this season" moves every Aug 1.
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


def game(game_id, home, away, when, *, excluded=False, score=(1, 0), provider=GS):
    return {
        "id": game_id,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "game_date": when,
        "home_score": score[0],
        "away_score": score[1],
        "is_excluded": excluded,
        "provider_id": provider,
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
    def __init__(self, name, rows, cap):
        self.name = name
        self._rows = rows
        self._cap = cap
        self._filters = []
        self._columns = None
        self._order = None
        self._page = None

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
        rows = self._page if self._page is not None else self._matching()[: self._cap]
        return _Result([{c: r[c] for c in self._columns} for r in rows])


class _Supabase:
    def __init__(self, tables, cap=10):
        self._tables = tables
        self._cap = cap

    def table(self, name):
        if name not in self._tables:
            raise AssertionError(f"no rows seeded for table {name!r}")
        return _Table(name, self._tables[name], self._cap)


def queue_row(req_id, *, status="completed", found=3, error=None):
    return {"id": req_id, "status": status, "games_found": found, "error_message": error}


def click(click_id, team_id, when_utc, *, game_date, request_id=None):
    return {
        "id": click_id,
        "team_id_master": team_id,
        "game_date": game_date,
        "clicked_at": when_utc,
        "scrape_request_id": request_id,
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
    start, end = datetime(2026, 11, 16, 6, tzinfo=UTC), datetime(2026, 11, 16, 9, tzinfo=UTC)

    assert img.window_label(start, end) == "2026-11-15 23:00 to 2026-11-16 02:00 Arizona time"


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

    assert reason(games) == "1 game(s) stored on both rows (same opponent, same day)"


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

    assert reason(games) == "1 game(s) stored on both rows (same opponent, same day)"


def test_a_blank_fixture_and_its_scored_copy_are_one_game():
    games = [game("g1", "a", "x", day(20), score=(None, None)), game("g2", "x", "b", day(20), score=(0, 2))]

    assert reason(games) == "1 game(s) stored on both rows (same opponent, same day)"


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

    assert reason(games, requested=[day(20)]) == f"holds a game on the requested date ({day(20)})"


def test_a_schedule_split_across_two_rows_needs_two_shared_opponents_this_season():
    split = [
        game("g1", "a", "x", day(10)),
        game("g2", "a", "y", day(11)),
        game("g3", "b", "x", day(30)),
        game("g4", "b", "y", day(31)),
    ]
    one = split[:3]
    last_season = [game("g5", "b", "y", day(-30)), *one]

    assert reason(split) == "schedule split across both rows: 2 shared opponents this season, never the same day"
    assert reason(one) is None
    assert reason(last_season) is None


def test_a_name_alone_counts_from_090():
    games = [game("g1", "a", "x", day(10))]

    assert reason(games, score=0.90) == "same squad by name; no game evidence either way"
    assert reason(games, score=0.89) is None


def test_the_season_starts_on_the_last_august_first():
    today = date.today()

    assert img.SEASON_START == f"{today.year if today.month >= 8 else today.year - 1}-08-01"


# --- profile ---------------------------------------------------------------------------------


def test_a_name_stating_another_age_is_flagged():
    findings = img.name_age_findings(team("a", "Rush U12 Boys Blue", age="u13"))

    assert [f.title for f in findings] == ["Name says u12, stored u13"]


def test_a_bare_birth_year_fitting_either_of_its_ages_is_not_flagged():
    assert img.name_age_findings(team("a", "Rush 2015 Boys", age="u11")) == []
    assert img.name_age_findings(team("a", "Rush 2015 Boys", age="u12")) == []


def test_the_registered_name_is_read_too():
    findings = img.name_age_findings(team("a", "Rush Blue", age="u13", original="Rush U12 Blue"))

    assert [f.title for f in findings] == ["Name says u12, stored u13"]


def opponent_case(names, *, own="Rush B2016 Samba", stored="u11", when=None, hidden=()):
    opponents = {f"o{i}": {"team_id_master": f"o{i}", "team_name": n} for i, n in enumerate(names)}
    games = [game(f"g{i}", "a", o, when or day(10 + i), excluded=i in hidden) for i, o in enumerate(opponents)]
    return img.opponent_age_findings(team("a", own, age=stored), schedule(games, ["a"])[0], opponents)


def test_opponents_whose_names_agree_on_another_age_are_flagged():
    findings = opponent_case(["X U10", "Y U10", "Z 2016/17", "W U10B"])

    assert [(f.title, f.details) for f in findings] == [
        ("This season's opponents point to u10, stored u11", ["4 of 4 opponents whose names state an age are u10"])
    ]


def test_three_of_four_is_enough():
    assert [f.title for f in opponent_case(["X U10", "Y U10", "Z U10", "W U11"])] == [
        "This season's opponents point to u10, stored u11"
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

    assert titles == ["Name says Female, stored Male", "No state"]


# --- providers -------------------------------------------------------------------------------


def alias(team_id, provider, pid):
    return {"team_id_master": team_id, "provider_id": provider, "provider_team_id": pid}


def test_a_team_with_no_gotsport_link_cannot_be_scraped():
    findings = img.provider_findings(
        team("a", "Rush U10", provider=SINC), [alias("a", TGS, "9")], PROVIDER_CODES, False
    )

    assert findings[0].title == "No GotSport link, so the scrape cannot reach this team"
    assert findings[0].details == ["Linked only to: sincsports, tgs"]


def test_a_placeholder_gotsport_id_is_no_link():
    findings = img.provider_findings(team("a", "Rush U10", provider=GS, pid="None"), [], PROVIDER_CODES, False)

    assert findings[0].title == "No GotSport link, so the scrape cannot reach this team"


def test_a_gotsport_alias_on_a_row_from_another_provider_is_a_link():
    t = team("a", "Rush U10", provider=SINC)

    findings = img.provider_findings(t, [alias("a", GS, "123")], PROVIDER_CODES, still_missing=True)

    assert [(f.title, f.problem) for f in findings] == [
        ("Also linked to providers the GotSport scrape never reads", True)
    ]
    assert findings[0].details == ["sincsports: SincSports tournaments: imported by hand, a month at a time"]


def test_other_providers_are_context_once_the_requested_game_is_on_record():
    findings = img.provider_findings(team("a", "Rush U10"), [alias("a", TGS, "9")], PROVIDER_CODES, still_missing=False)

    assert [(f.title, f.problem) for f in findings] == [
        ("Also linked to providers the GotSport scrape never reads", False)
    ]


def test_three_gotsport_registrations_on_one_row_are_flagged():
    t = team("a", "Rush U10", pid="1")

    findings = img.provider_findings(t, [alias("a", GS, "2"), alias("a", GS, "3")], PROVIDER_CODES, False)

    assert [f.title for f in findings] == ["3 GotSport registrations on one row"]


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


def lines_for(clicks, games, opponents=None):
    names = {k: {"team_id_master": k, "team_name": v} for k, v in (opponents or {}).items()}
    return img.scrape_lines(clicks, fixtures_for("a", games), names, PROVIDER_CODES)


def test_each_click_states_how_its_scrape_ended():
    clicks = [
        clicked(day(40), queue_row("q", found=None)),
        clicked(day(50), queue_row("q", status="failed", error="x" * 200)),
        clicked(
            day(55),
            queue_row("q", status="failed", error="403 for url: https://api.zenrows.com/v1/?apikey=S3CRET&url=x"),
        ),
        clicked(day(60), queue_row("q", status="pending")),
        clicked(day(70), None, request_id=None),
        clicked(day(80), None),
    ]

    assert lines_for(clicks, []) == [
        f"Requested {day(40)}: scraped, 0 games found",
        f"  no game on record for {day(40)}",
        f"Requested {day(50)}: failed: {'x' * 160}",
        f"  no game on record for {day(50)}",
        f"Requested {day(55)}: failed: 403 for url: https://api.zenrows.com/v1/?apikey=<redacted>&url=x",
        f"  no game on record for {day(55)}",
        f"Requested {day(60)}: not scraped yet (pending)",
        f"  no game on record for {day(60)}",
        f"Requested {day(70)}: not scraped for this date: "
        "the team's queued request is for another date or registration",
        f"  no game on record for {day(70)}",
        f"Requested {day(80)}: queue request no longer on record",
        f"  no game on record for {day(80)}",
    ]


def test_games_a_day_either_side_are_listed_from_the_team_s_side():
    games = [
        game("g1", "x", "a", day(19), score=(4, 1)),
        game("g2", "a", "y", day(21), excluded=True, score=(None, None)),
        game("g3", "a", "z", day(22)),
        game("g4", "a", "z", day(18)),
    ]

    lines = lines_for([clicked(day(20), queue_row("q"))], games, {"x": "Opp X", "y": "Opp Y"})

    assert lines == [
        f"Requested {day(20)}: scraped, 3 games found",
        f"  {day(19)} vs Opp X, 1-4, gotsport",
        f"  {day(21)} vs Opp Y, no score, gotsport [hidden]",
        f"  no game on record for {day(20)}",
    ]


def test_a_hidden_game_on_the_requested_date_is_flagged_only_when_nothing_visible_is_there():
    hidden = fixtures_for("a", [game("g1", "a", "x", day(20), excluded=True)])
    both = fixtures_for("a", [game("g1", "a", "x", day(20), excluded=True), game("g2", "a", "x", day(20))])

    assert img.hidden_game_finding({day(20)}, hidden).title == "The requested game is on record but hidden"
    assert img.hidden_game_finding({day(20)}, both) is None


# --- composition -----------------------------------------------------------------------------


WINDOW = (datetime(2026, 11, 16, 12, tzinfo=UTC), datetime(2026, 11, 16, 15, tzinfo=UTC))


def _world(**overrides):
    """One clicked team, filed under a merged-away id, with a duplicate row holding the game.

    `dup` holds the requested game; `kept` is a duplicate by every rule but the owner chose
    Keep separate; `far` is a similar name in another state; `t-live` is a live row already
    merged into the target.
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
    reports, caveats = img.investigate(_world(), *WINDOW)

    assert caveats == []
    [report] = reports
    assert [c["id"] for c in report.clicks] == ["c1", "c2"]
    assert [(f.title, f.problem) for f in report.findings] == [
        ("Possible duplicate rows", True),
        ("No GotSport link, so the scrape cannot reach this team", True),
        ("Also linked to providers the GotSport scrape never reads", True),
    ]
    assert report.findings[0].details == [
        f"Rush B2016 Blue (u11, Rush, gotsport, 1 games, last {day(20)}) https://www.pitchrank.io/teams/dup: "
        f"holds a game on the requested date ({day(20)})",
        "1 similar row(s) left out: already decided Keep separate",
    ]
    assert report.findings[1].details == ["Linked only to: sincsports, tgs"]
    assert report.scrape == [
        f"Requested {day(20)}: failed: no message",
        f"  {day(19)} vs Opp U10, 1-0, gotsport",
        f"  no game on record for {day(20)}",
        f"Requested {day(20)}: scraped, 3 games found",
        f"  {day(19)} vs Opp U10, 1-0, gotsport",
        f"  no game on record for {day(20)}",
    ]


def test_other_providers_turn_to_context_once_the_requested_game_lands():
    world = _world()
    world._tables["games"].append(game("g9", "t", "x", day(20)))

    [report] = img.investigate(world, *WINDOW)[0]

    other = [f for f in report.findings if f.title.startswith("Also linked")]
    assert [f.problem for f in other] == [False]


def test_a_hidden_requested_game_is_still_missing():
    world = _world()
    world._tables["games"].append(game("g9", "t", "x", day(20), excluded=True))

    [report] = img.investigate(world, *WINDOW)[0]

    titles = {f.title: f.problem for f in report.findings}
    assert titles["The requested game is on record but hidden"] is True
    assert titles["Also linked to providers the GotSport scrape never reads"] is True


def test_a_clicked_row_that_plays_itself_says_so_and_suggests_no_duplicate():
    world = _world()
    world._tables["games"].append(game("g9", "t", "t-old", day(3)))

    [report] = img.investigate(world, *WINDOW)[0]

    titles = [f.title for f in report.findings]
    assert "This row has a game against itself" in titles
    assert "Possible duplicate rows" not in titles


def test_unreadable_keep_separate_decisions_are_reported_rather_than_fatal():
    reports, caveats = img.investigate(_world(team_cleanup_decisions=[{"id": 1}]), *WINDOW)

    assert caveats == ["Keep-separate decisions could not be read, so pairs already kept apart may be listed."]
    details = reports[0].findings[0].details
    assert len(details) == 2
    assert details[1].startswith("Rush 2016 Blue (u10")


def test_a_request_for_a_missing_team_row_becomes_a_caveat():
    world = _world()
    world._tables["missing_game_clicks"].append(click("c3", "ghost", "2026-11-16T14:30:00+00:00", game_date=day(20)))

    reports, caveats = img.investigate(world, *WINDOW)

    assert [r.team["team_id_master"] for r in reports] == ["t"]
    assert caveats == ["A clicked team's row was not found (ghost)"]


def test_teams_with_more_to_look_at_come_first():
    world = _world()
    world._tables["teams"].append(team("calm", "Aaa Calm U10"))
    world._tables["missing_game_clicks"].append(click("c3", "calm", "2026-11-16T14:30:00+00:00", game_date=day(20)))

    reports, _ = img.investigate(world, *WINDOW)

    assert [r.team["team_id_master"] for r in reports] == ["t", "calm"]
    assert reports[1].problems == []


def test_a_window_with_no_clicks_has_no_reports():
    assert img.investigate(_world(missing_game_clicks=[]), *WINDOW) == ([], [])


# --- delivery --------------------------------------------------------------------------------


def two_reports():
    flagged = img.TeamReport(
        team("a", "<script>alert(1)</script>"),
        [{"game_date": day(1)}],
        ["Requested <b>", "  a game"],
        [img.Finding("T&C", ["<i>"], "a<b"), img.Finding("Context", ["c"], "n", problem=False)],
    )
    calm = img.TeamReport(team("b", "Calm"), [{"game_date": day(2)}], ["Requested x"], [])
    return [flagged, calm]


def test_the_subject_counts_only_teams_with_problems():
    assert img.subject(two_reports(), "LABEL") == "PitchRank: 2 missing-game request team(s), 1 need a look (LABEL)"


def test_the_email_escapes_names_and_carries_caveats_and_context():
    body = img.render_html(two_reports(), ["<caveat>"], "LABEL")

    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "<i>" not in body and "Requested &lt;b&gt;" in body
    assert "<p><b>&lt;caveat&gt;</b></p>" in body
    assert "<li style='margin-left:20px'>a game</li>" in body
    assert "<p><b>Context</b> (for context)</p>" in body
    assert "<td style='padding:6px 12px'>T&amp;C</td>" in body
    assert "<td style='padding:6px 12px'>nothing found</td>" in body


def test_the_text_report_carries_caveats_findings_and_quiet_teams():
    text = img.render_text(two_reports(), ["caveat"], "LABEL")

    assert text.splitlines()[:2] == [
        "Missing-game requests, LABEL: 2 team(s). Report only; nothing was changed.",
        "caveat",
    ]
    assert "* Context (for context)" in text
    assert "    Next step: a<b" in text
    assert text.endswith("Requested x\nNothing else found.")


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(img, "get_client", lambda: _world())
    monkeypatch.setattr(img, "send_email", lambda to, subj, body: calls.append((to, subj)) or True)
    return calls


LABEL = "2026-11-16 05:00 to 2026-11-16 08:00 Arizona time"


def test_a_dry_run_prints_the_report_and_sends_nothing(sent, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00", "--dry-run"])

    assert img.main() == 0
    assert sent == []
    assert "Rush 2016 Blue" in capsys.readouterr().out


def test_a_live_run_emails_the_report_and_keeps_team_names_out_of_the_log(sent, monkeypatch, capsys, caplog):
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    with caplog.at_level("INFO"):
        assert img.main() == 0

    assert sent == [("pitchrankio@gmail.com", f"PitchRank: 1 missing-game request team(s), 1 need a look ({LABEL})")]
    logged = capsys.readouterr().out + caplog.text
    assert "Rush" not in logged and "failed" not in logged


def test_a_scheduled_run_reports_the_window_that_closed_before_it(sent, monkeypatch):
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 16, 15, 50, tzinfo=UTC)

    monkeypatch.setattr(img, "datetime", _Clock)
    monkeypatch.setattr(sys, "argv", ["x"])

    assert img.main() == 0
    assert sent[0][1].endswith(f"({LABEL})")


def test_an_end_with_an_offset_is_taken_as_given(sent, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T15:00+00:00"])

    assert img.main() == 0
    assert sent[0][1].endswith(f"({LABEL})")


def test_a_failed_send_fails_the_run(monkeypatch):
    monkeypatch.setattr(img, "get_client", lambda: _world())
    monkeypatch.setattr(img, "send_email", lambda *a: False)
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 1


def test_a_quiet_window_sends_nothing(sent, monkeypatch):
    monkeypatch.setattr(img, "get_client", lambda: _world(missing_game_clicks=[]))
    monkeypatch.setattr(sys, "argv", ["x", "--end", "2026-11-16T08:00"])

    assert img.main() == 0
    assert sent == []
