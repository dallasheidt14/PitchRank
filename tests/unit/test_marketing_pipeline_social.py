"""Unit tests for the 5-post Instagram week helpers in scripts/marketing_pipeline.py."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone

from scripts.marketing_pipeline import (
    PILLAR_STATES,
    SOCIAL_TEMPLATES,
    STATE_COHORT_EPOCH,
    TOP10_AGES,
    build_big_games_caption,
    build_top10_caption,
    encode_big_games_payload,
    fetch_top10_cohorts,
    format_rankings_live_caption,
    generate_social_posts,
    live_run_failed,
    next_weekend_window,
    rankings_are_stale,
    weekly_top10_combos,
)

MT = timezone(timedelta(hours=-6))


def _monday_of_week(week: int) -> datetime:
    return STATE_COHORT_EPOCH + timedelta(weeks=week)


# ---------------------------------------------------------------------------
# weekly_top10_combos
# ---------------------------------------------------------------------------


def test_weekly_top10_combos_same_week_is_identical():
    monday = _monday_of_week(23)
    assert weekly_top10_combos(monday) == weekly_top10_combos(monday)
    # Any day within the same Mon-Sun week selects the same combos
    assert weekly_top10_combos(monday + timedelta(days=3)) == weekly_top10_combos(monday)


def test_weekly_top10_combos_covers_all_19_states_before_repeating():
    picks = [combo[0] for week in range(7) for combo in weekly_top10_combos(_monday_of_week(week))]
    assert set(picks[:19]) == set(PILLAR_STATES)
    assert len(set(picks[:19])) == 19


def test_weekly_top10_combos_ages_from_pool_no_u18():
    ages = {combo[1] for week in range(30) for combo in weekly_top10_combos(_monday_of_week(week))}
    assert ages <= set(TOP10_AGES)
    assert 18 not in ages


def test_weekly_top10_combos_genders_vary_within_week():
    for week in range(5):
        genders = {combo[2] for combo in weekly_top10_combos(_monday_of_week(week))}
        assert genders == {"male", "female"}


# ---------------------------------------------------------------------------
# Caption builders
# ---------------------------------------------------------------------------


def test_rankings_live_count_variant_fills_live_count():
    template = SOCIAL_TEMPLATES["rankings_live"][1]
    text = format_rankings_live_caption(template, 59123)
    assert "59,123 teams updated." in text


def test_rankings_live_count_variant_drops_line_when_count_unavailable():
    template = SOCIAL_TEMPLATES["rankings_live"][1]
    text = format_rankings_live_caption(template, 0)
    assert "teams updated" not in text
    assert "{active_team_count}" not in text
    assert "pitchrank.io/rankings" in text


def test_rankings_live_plain_variant_passes_through():
    template = SOCIAL_TEMPLATES["rankings_live"][0]
    assert format_rankings_live_caption(template, 0) == template


def test_build_top10_caption_format():
    text = build_top10_caption("NY", 14, "male")
    assert text.startswith("New York U14 Boys — Top 10 in the state.")
    assert "#NYSoccer" in text
    assert "pitchrank.io/rankings" in text


def _matchup(i: int = 0, club: str = "Club") -> dict:
    return {
        "game_date": "2026-06-13",
        "home_team_id_master": f"home-{i}",
        "home_team_name": f"Home Team {i}",
        "home_club_name": club,
        "home_state_rank": 1 + i,
        "away_team_id_master": f"away-{i}",
        "away_team_name": f"Away Team {i}",
        "away_club_name": club,
        "away_state_rank": 2 + i,
        "state_code": "PA",
        "age_group": "u14",
        "gender": "M",
    }


def test_build_big_games_caption_renders_one_line_per_matchup():
    text = build_big_games_caption([_matchup(0), _matchup(1), _matchup(2)])
    assert text.count("⚔️") == 3
    assert "Home Team 0 vs Away Team 0 (PA U14 Boys)" in text


# ---------------------------------------------------------------------------
# encode_big_games_payload
# ---------------------------------------------------------------------------


def _decode(payload: str) -> dict:
    padded = payload + "=" * ((4 - len(payload) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


def test_encode_big_games_payload_round_trips():
    matchups = [_matchup(0), _matchup(1)]
    decoded = _decode(encode_big_games_payload(matchups, date(2026, 6, 13), date(2026, 6, 14)))
    assert decoded["v"] == 1
    assert len(decoded["games"]) == 2
    game = decoded["games"][0]
    assert game["home"] == {"name": "Home Team 0", "club": "Club", "rank": 1}
    assert game["away"] == {"name": "Away Team 0", "club": "Club", "rank": 2}
    assert game["cohort"] == "PA · U14 BOYS"
    assert game["state"] == "PA"


def test_encode_big_games_payload_day_labels():
    for game_date, label in [("2026-06-12", "FRI"), ("2026-06-13", "SAT"), ("2026-06-14", "SUN")]:
        matchup = {**_matchup(), "game_date": game_date}
        decoded = _decode(encode_big_games_payload([matchup], date(2026, 6, 12), date(2026, 6, 14)))
        assert decoded["games"][0]["day"] == label


def test_encode_big_games_payload_range_string():
    decoded = _decode(encode_big_games_payload([_matchup()], date(2026, 6, 13), date(2026, 6, 14)))
    assert decoded["range"] == "Jun 13–14, 2026"


def test_encode_big_games_payload_range_string_cross_month():
    decoded = _decode(encode_big_games_payload([_matchup()], date(2026, 7, 31), date(2026, 8, 2)))
    assert decoded["range"] == "Jul 31 – Aug 2, 2026"


def test_encode_big_games_payload_stays_small_with_long_unicode_names():
    # Worst-case 70+ char names must stay far below the ~14KB edge URL ceiling
    # (typical real payloads land around 1KB)
    long_club = "Fußballverein Müller-Lüdenscheidt Süd-West Akademie 2012"
    matchups = []
    for i in range(5):
        m = _matchup(i, club=long_club)
        m["home_team_name"] = f"Extraordinarily Long Youth Soccer Association Team Name {i} Premier Gold"
        m["away_team_name"] = f"Another Remarkably Long Club Academy Select Team Name {i} Elite Black"
        matchups.append(m)
    payload = encode_big_games_payload(matchups, date(2026, 6, 13), date(2026, 6, 14))
    assert len(payload) < 4096


# ---------------------------------------------------------------------------
# Freshness gate + weekend window
# ---------------------------------------------------------------------------


def test_rankings_are_stale_none_is_stale():
    assert rankings_are_stale(None) is True


def test_rankings_are_stale_beyond_threshold():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    assert rankings_are_stale(now - timedelta(days=9), now=now) is True


def test_rankings_are_stale_healthy_midweek_age_is_fresh():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    assert rankings_are_stale(now - timedelta(days=3, hours=12), now=now) is False


def test_next_weekend_window_from_monday():
    assert next_weekend_window(datetime(2026, 6, 8, 12, 0, tzinfo=MT)) == (date(2026, 6, 12), date(2026, 6, 14))


def test_next_weekend_window_on_friday_skips_to_next_weekend():
    assert next_weekend_window(datetime(2026, 6, 12, 12, 0, tzinfo=MT)) == (date(2026, 6, 19), date(2026, 6, 21))


# ---------------------------------------------------------------------------
# live_run_failed (exit-code guard)
# ---------------------------------------------------------------------------


def test_live_run_failed_normal_week_everything_failed():
    assert live_run_failed(False, False, True, [False, False]) is True


def test_live_run_failed_normal_week_newsletter_sent():
    assert live_run_failed(True, False, True, [False]) is False


def test_live_run_failed_normal_week_drafts_succeeded():
    assert live_run_failed(False, False, True, [True, False]) is False


def test_live_run_failed_quiet_week_drafts_succeeded():
    assert live_run_failed(False, True, True, [True]) is False


def test_live_run_failed_quiet_week_all_drafts_failed():
    # Quiet week: IG drafts are the only deliverable, so a total draft failure
    # must exit non-zero rather than be masked by the skipped newsletter.
    assert live_run_failed(False, True, True, [False, False]) is True


def test_live_run_failed_quiet_week_nothing_attempted():
    # Kill switch on a quiet week: no newsletter, no drafts — nothing was due.
    assert live_run_failed(False, True, False, []) is False


# ---------------------------------------------------------------------------
# fetch_top10_cohorts
# ---------------------------------------------------------------------------


def _ranked_team(i: int, status: str = "Active", rank=None) -> dict:
    return {
        "team_id_master": f"team-{i}",
        "status": status,
        "rank_in_state_final": (i + 1) if rank is None else rank,
    }


class _FakeRpcResult:
    def __init__(self, rows):
        self.data = rows

    def execute(self):
        return self


class _StubSupabase:
    """Returns per-state get_state_rankings rows from a {state: rows} map.

    A state mapped to the RAISE sentinel makes .execute() raise, exercising the
    per-state failure-skip branch. Unmapped states return an empty list.
    """

    RAISE = object()

    def __init__(self, by_state: dict):
        self.by_state = by_state
        self.calls = []

    def rpc(self, fn_name, params):
        state = params["p_state"]
        self.calls.append(state)
        rows = self.by_state.get(state, [])
        if rows is _StubSupabase.RAISE:
            raise RuntimeError("rpc boom")
        return _FakeRpcResult(rows)


def _full_cohort() -> list[dict]:
    return [_ranked_team(i) for i in range(12)]


def test_fetch_top10_cohorts_happy_path():
    stub = _StubSupabase({"NY": _full_cohort()})
    out = fetch_top10_cohorts(stub, [("NY", 14, "male")])
    assert stub.calls == ["NY"]
    assert len(out) == 1
    assert out[0]["state"] == "NY"
    assert len(out[0]["teams"]) == 10


def test_fetch_top10_cohorts_filters_non_active_and_unranked():
    rows = (
        [_ranked_team(i) for i in range(8)]
        + [_ranked_team(99, status="Not Enough Ranked Games")]
        + [_ranked_team(98, rank=None)]
        + [_ranked_team(i) for i in range(8, 11)]
    )
    stub = _StubSupabase({"NY": rows})
    out = fetch_top10_cohorts(stub, [("NY", 14, "male")])
    assert len(out[0]["teams"]) == 10
    assert all(t["status"] == "Active" and t["rank_in_state_final"] is not None for t in out[0]["teams"])


def test_fetch_top10_cohorts_repicks_next_pillar_state_when_thin():
    start = PILLAR_STATES.index("AZ")
    next_state = PILLAR_STATES[(start + 1) % len(PILLAR_STATES)]
    stub = _StubSupabase({"AZ": [_ranked_team(i) for i in range(3)], next_state: _full_cohort()})
    out = fetch_top10_cohorts(stub, [("AZ", 14, "male")])
    assert stub.calls == ["AZ", next_state]
    assert out[0]["state"] == next_state
    assert len(out[0]["teams"]) == 10


def test_fetch_top10_cohorts_skips_state_whose_rpc_raises():
    start = PILLAR_STATES.index("AZ")
    next_state = PILLAR_STATES[(start + 1) % len(PILLAR_STATES)]
    stub = _StubSupabase({"AZ": _StubSupabase.RAISE, next_state: _full_cohort()})
    out = fetch_top10_cohorts(stub, [("AZ", 14, "male")])
    assert stub.calls == ["AZ", next_state]
    assert out[0]["state"] == next_state


def test_fetch_top10_cohorts_drops_combo_when_all_states_thin():
    stub = _StubSupabase({state: [_ranked_team(i) for i in range(3)] for state in PILLAR_STATES})
    out = fetch_top10_cohorts(stub, [("AZ", 14, "male")])
    assert out == []
    assert len(stub.calls) == len(PILLAR_STATES)


# ---------------------------------------------------------------------------
# generate_social_posts
# ---------------------------------------------------------------------------


def _cohort(state: str = "NY", age: int = 14, gender: str = "male") -> dict:
    return {
        "state": state,
        "age": age,
        "gender": gender,
        "teams": [{"team_id_master": f"{state}-{i}"} for i in range(10)],
    }


def _week_data(big_games: list | None = None, cohorts: list | None = None) -> dict:
    return {
        "date": datetime(2026, 6, 8, 8, 0, tzinfo=MT),  # a Monday
        "climbers": [],
        "fallers": [],
        "active_team_count": 59000,
        "top10_combos": [("NY", 14, "male"), ("TX", 12, "female"), ("CA", 16, "male")],
        "top10_cohorts": (
            cohorts if cohorts is not None else [_cohort("NY"), _cohort("TX", 12, "female"), _cohort("CA", 16)]
        ),
        "big_games_window": (date(2026, 6, 12), date(2026, 6, 14)),
        "big_games": big_games if big_games is not None else [_matchup(0), _matchup(1)],
    }


def test_generate_social_posts_full_week_is_five_posts_with_no_movers():
    posts = generate_social_posts(_week_data())
    assert [p["type"] for p in posts] == ["rankings_live", "top10", "top10", "top10", "big_games"]


def test_generate_social_posts_schedule_slots():
    posts = generate_social_posts(_week_data())
    by_type = {}
    for p in posts:
        by_type.setdefault(p["type"], []).append(p["scheduled_at"])
    assert by_type["rankings_live"] == [datetime(2026, 6, 8, 12, 0, tzinfo=MT)]
    assert by_type["top10"] == [
        datetime(2026, 6, 9, 9, 0, tzinfo=MT),
        datetime(2026, 6, 9, 12, 0, tzinfo=MT),
        datetime(2026, 6, 9, 17, 0, tzinfo=MT),
    ]
    assert by_type["big_games"] == [datetime(2026, 6, 11, 19, 30, tzinfo=MT)]


def test_generate_social_posts_skips_big_games_when_empty():
    posts = generate_social_posts(_week_data(big_games=[]))
    assert [p["type"] for p in posts] == ["rankings_live", "top10", "top10", "top10"]


def test_generate_social_posts_tag_targets():
    posts = generate_social_posts(_week_data())
    top10 = [p for p in posts if p["type"] == "top10"]
    assert all(len(p["_tag_target_ids"]) == 10 for p in top10)
    big = next(p for p in posts if p["type"] == "big_games")
    assert big["_tag_target_ids"] == ["home-0", "away-0", "home-1", "away-1"]
    live = next(p for p in posts if p["type"] == "rankings_live")
    assert "_tag_target_ids" not in live


def test_generate_social_posts_media_urls():
    posts = generate_social_posts(_week_data())
    live = next(p for p in posts if p["type"] == "rankings_live")
    assert live["media_url"].endswith("/api/infographic/rankings-live?platform=instagram")
    first_top10 = next(p for p in posts if p["type"] == "top10")
    assert "/api/infographic/state?state=NY&age=u14&gender=male&platform=instagram" in first_top10["media_url"]
    big = next(p for p in posts if p["type"] == "big_games")
    assert "/api/infographic/big-games?platform=instagram&m=" in big["media_url"]
