"""Unit tests for new pure helpers in scripts/marketing_pipeline.py (Postiz migration)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import marketing_pipeline as mp
from scripts.marketing_pipeline import (
    _resolve_tag_targets,
    _to_postiz_payload,
    enrich_post_with_handles,
    generate_trend_posts,
)

MT = timezone(timedelta(hours=-6))


# ---------------------------------------------------------------------------
# _to_postiz_payload
# ---------------------------------------------------------------------------


def _x_thread_post():
    return {
        "text": "tweet 1\n---\ntweet 2",
        "media_url": None,
        "scheduled_at": datetime(2026, 6, 1, 12, 0, tzinfo=MT),
        "type": "x_thread",
        "thread_parts": ["tweet 1", "tweet 2"],
    }


def _ig_post(media_url: str | None = "https://example.com/img.png"):
    return {
        "text": "ig caption",
        "media_url": media_url,
        "scheduled_at": datetime(2026, 6, 1, 12, 0, tzinfo=MT),
        "type": "rankings_live",
    }


def test_to_postiz_payload_x_thread_multi_entry():
    payload = _to_postiz_payload(_x_thread_post(), "x_int_1", "x")
    assert payload["type"] == "draft"
    assert payload["posts"][0]["integration"]["id"] == "x_int_1"
    assert payload["posts"][0]["settings"] == {"__type": "x", "who_can_reply_post": "everyone"}
    assert payload["posts"][0]["value"] == [
        {"content": "tweet 1", "image": []},
        {"content": "tweet 2", "image": []},
    ]


def test_to_postiz_payload_x_single_no_thread_parts():
    post = {
        "text": "single tweet",
        "media_url": None,
        "scheduled_at": datetime(2026, 6, 1, 12, 0, tzinfo=MT),
        "type": "trend",
    }
    payload = _to_postiz_payload(post, "x_int_1", "x")
    assert payload["posts"][0]["value"] == [{"content": "single tweet", "image": []}]


def test_to_postiz_payload_instagram_fb_linked_with_uploaded_media():
    post = _ig_post()
    post["_uploaded_media"] = {"id": "u_abc", "path": "https://uploads.postiz.com/x.png"}
    payload = _to_postiz_payload(post, "ig_int_1", "instagram")
    settings = payload["posts"][0]["settings"]
    assert settings["__type"] == "instagram"
    assert settings["post_type"] == "post"
    assert settings["is_trial_reel"] is False
    assert settings["collaborators"] == []
    assert payload["posts"][0]["value"] == [
        {"content": "ig caption", "image": [{"id": "u_abc", "path": "https://uploads.postiz.com/x.png"}]}
    ]


def test_to_postiz_payload_instagram_standalone_uses_identifier_as_type():
    post = _ig_post()
    post["_uploaded_media"] = {"id": "u_abc", "path": "https://uploads.postiz.com/x.png"}
    payload = _to_postiz_payload(post, "ig_int_1", "instagram-standalone")
    assert payload["posts"][0]["settings"]["__type"] == "instagram-standalone"


def test_to_postiz_payload_instagram_raw_media_url_is_ignored_without_upload():
    # Regression guard: Postiz rejects raw URLs in the image array. Without
    # _uploaded_media set by the caller, image must be empty even when media_url is present.
    payload = _to_postiz_payload(_ig_post(media_url="https://example.com/img.png"), "ig_int_1", "instagram")
    assert payload["posts"][0]["value"][0]["image"] == []


def test_to_postiz_payload_instagram_without_media_emits_empty_image():
    payload = _to_postiz_payload(_ig_post(media_url=None), "ig_int_1", "instagram")
    assert payload["posts"][0]["value"][0]["image"] == []


def test_to_postiz_payload_unknown_platform_raises():
    with pytest.raises(ValueError, match="Unsupported Postiz platform"):
        _to_postiz_payload(_ig_post(), "id", "linkedin")


def test_to_postiz_payload_envelope_shape():
    payload = _to_postiz_payload(_x_thread_post(), "id", "x")
    assert set(payload.keys()) == {"type", "date", "shortLink", "tags", "posts"}
    assert payload["shortLink"] is False
    assert payload["tags"] == []
    assert payload["date"] == "2026-06-01T12:00:00-06:00"


# ---------------------------------------------------------------------------
# _resolve_tag_targets
# ---------------------------------------------------------------------------


def _data(climbers=None, spotlight_teams=None):
    return {
        "climbers": climbers if climbers is not None else [],
        "spotlight_teams": spotlight_teams if spotlight_teams is not None else [],
    }


def test_resolve_tag_targets_rankings_live_picks_first_three_climbers():
    data = _data(
        climbers=[
            {"team_id": "a"},
            {"team_id": "b"},
            {"team_id": "c"},
            {"team_id": "d"},
        ]
    )
    assert _resolve_tag_targets("rankings_live", data) == ["a", "b", "c"]


def test_resolve_tag_targets_rankings_live_skips_missing_team_ids():
    data = _data(climbers=[{"team_id": "a"}, {"team_name": "no id"}, {"team_id": "c"}])
    assert _resolve_tag_targets("rankings_live", data) == ["a", "c"]


def test_resolve_tag_targets_mover_spotlight_prefers_second_climber():
    data = _data(climbers=[{"team_id": "first"}, {"team_id": "second"}, {"team_id": "third"}])
    assert _resolve_tag_targets("mover_spotlight", data) == ["second"]


def test_resolve_tag_targets_mover_spotlight_falls_back_to_first_when_only_one():
    data = _data(climbers=[{"team_id": "first"}])
    assert _resolve_tag_targets("mover_spotlight", data) == ["first"]


def test_resolve_tag_targets_mover_spotlight_empty_climbers():
    data = _data(climbers=[])
    assert _resolve_tag_targets("mover_spotlight", data) == []


def test_resolve_tag_targets_state_spotlight_picks_first_three():
    data = _data(spotlight_teams=[{"team_id": "x"}, {"team_id": "y"}, {"team_id": "z"}, {"team_id": "w"}])
    assert _resolve_tag_targets("state_spotlight", data) == ["x", "y", "z"]


def test_resolve_tag_targets_state_spotlight_none_returns_empty():
    data = {"climbers": [], "spotlight_teams": None}
    assert _resolve_tag_targets("state_spotlight", data) == []


@pytest.mark.parametrize("post_type", ["data_flex", "x_thread", "trend", "unknown_future_type"])
def test_resolve_tag_targets_other_types_return_empty(post_type):
    data = _data(climbers=[{"team_id": "a"}], spotlight_teams=[{"team_id": "b"}])
    assert _resolve_tag_targets(post_type, data) == []


# ---------------------------------------------------------------------------
# enrich_post_with_handles
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Mocks supabase.from_().select().in_().in_().execute()."""

    def __init__(self, rows, raise_on_execute: Exception | None = None):
        self._rows = rows
        self._raise = raise_on_execute

    def select(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def execute(self):
        if self._raise:
            raise self._raise
        return type("R", (), {"data": self._rows})()


class _FakeSupabase:
    def __init__(self, rows=None, raise_on_execute: Exception | None = None):
        self._query = _FakeQuery(rows or [], raise_on_execute)

    def from_(self, table):
        return self._query


def _post(text="caption", post_type="rankings_live"):
    return {
        "text": text,
        "media_url": "https://example.com/img.png",
        "scheduled_at": datetime(2026, 6, 1, 12, 0, tzinfo=MT),
        "type": post_type,
    }


def test_enrich_with_empty_targets_writes_zero_stats():
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(), [])
    assert post["_tag_stats"] == {"tagged_count": 0, "target_count": 0, "missing_team_ids": []}
    assert post["text"] == "caption"  # unchanged


def test_enrich_prefers_team_handle_over_club_for_same_team():
    rows = [
        {"team_id": "t1", "handle": "club_a", "profile_level": "club"},
        {"team_id": "t1", "handle": "team_a", "profile_level": "team"},
    ]
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(rows), ["t1"])
    assert "@team_a" in post["text"]
    assert "@club_a" not in post["text"]
    assert post["_tag_stats"]["tagged_count"] == 1


def test_enrich_falls_back_to_club_when_no_team_handle():
    rows = [{"team_id": "t1", "handle": "club_a", "profile_level": "club"}]
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(rows), ["t1"])
    assert "@club_a" in post["text"]
    assert post["_tag_stats"]["missing_team_ids"] == []


def test_enrich_dedupes_shared_club_handle_across_siblings():
    rows = [
        {"team_id": "t1", "handle": "shared_club", "profile_level": "club"},
        {"team_id": "t2", "handle": "shared_club", "profile_level": "club"},
    ]
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(rows), ["t1", "t2"])
    # @shared_club appears only once
    assert post["text"].count("@shared_club") == 1
    # Both teams are considered "covered" — missing_team_ids is empty
    assert post["_tag_stats"]["missing_team_ids"] == []
    # tagged_count reflects unique handles emitted, not unique teams covered
    assert post["_tag_stats"]["tagged_count"] == 1


def test_enrich_dedupe_is_case_insensitive():
    rows = [
        {"team_id": "t1", "handle": "Club_A", "profile_level": "team"},
        {"team_id": "t2", "handle": "club_a", "profile_level": "team"},
    ]
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(rows), ["t1", "t2"])
    assert post["_tag_stats"]["tagged_count"] == 1


def test_enrich_caps_at_ten_mentions():
    rows = [{"team_id": f"t{i}", "handle": f"team_{i}", "profile_level": "team"} for i in range(12)]
    post = _post()
    targets = [f"t{i}" for i in range(12)]
    enrich_post_with_handles(post, _FakeSupabase(rows), targets)
    assert post["_tag_stats"]["tagged_count"] == 10


def test_enrich_truncates_when_caption_would_exceed_2200_chars():
    rows = [{"team_id": f"t{i}", "handle": "x" * 200, "profile_level": "team"} for i in range(10)]
    post = _post(text="y" * 2100)  # leaves ~100 chars before 2200 limit
    enrich_post_with_handles(post, _FakeSupabase(rows), [f"t{i}" for i in range(10)])
    assert len(post["text"]) <= 2200
    assert post["_tag_stats"]["tagged_count"] < 10


def test_enrich_missing_team_ids_lists_targets_with_no_handle_at_all():
    rows = [{"team_id": "t1", "handle": "team_a", "profile_level": "team"}]
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(rows), ["t1", "t2", "t3"])
    assert set(post["_tag_stats"]["missing_team_ids"]) == {"t2", "t3"}
    assert post["_tag_stats"]["target_count"] == 3


def test_enrich_supabase_exception_writes_error_in_stats_and_leaves_text_unchanged():
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(raise_on_execute=RuntimeError("connection refused")), ["t1", "t2"])
    assert post["text"] == "caption"
    stats = post["_tag_stats"]
    assert stats["tagged_count"] == 0
    assert stats["target_count"] == 2
    assert stats["missing_team_ids"] == ["t1", "t2"]
    assert "connection refused" in stats["error"]


def test_enrich_no_handles_found_writes_all_missing():
    post = _post()
    enrich_post_with_handles(post, _FakeSupabase(rows=[]), ["t1", "t2"])
    assert post["_tag_stats"]["tagged_count"] == 0
    assert post["_tag_stats"]["missing_team_ids"] == ["t1", "t2"]
    assert "Tagging:" not in post["text"]


# ---------------------------------------------------------------------------
# generate_trend_posts
# ---------------------------------------------------------------------------


@pytest.fixture
def trend_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at a tmp_path with an empty brand/trend-research/ dir."""
    (tmp_path / "brand" / "trend-research").mkdir(parents=True)
    monkeypatch.setattr(mp, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _trend_data(date: datetime | None = None) -> dict:
    return {"date": date or datetime(2026, 6, 1, 12, 0, tzinfo=MT)}


def _write_trend(root, week: str, payload):
    path = root / "brand" / "trend-research" / f"{week}.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_generate_trend_posts_missing_file_returns_empty(trend_root):
    assert generate_trend_posts("2026-W23", _trend_data()) == []


def test_generate_trend_posts_malformed_json_returns_empty(trend_root):
    _write_trend(trend_root, "2026-W23", "not json {")
    assert generate_trend_posts("2026-W23", _trend_data()) == []


def test_generate_trend_posts_week_mismatch_returns_empty(trend_root):
    _write_trend(trend_root, "2026-W23", {"week": "2099-W01", "posts": [{"suggested_tweet": "x"}]})
    assert generate_trend_posts("2026-W23", _trend_data()) == []


def test_generate_trend_posts_no_valid_entries_returns_empty(trend_root):
    _write_trend(
        trend_root,
        "2026-W23",
        {"week": "2026-W23", "posts": [{"topic": "no tweet"}, {"suggested_tweet": "   "}]},
    )
    assert generate_trend_posts("2026-W23", _trend_data()) == []


def test_generate_trend_posts_single_valid_entry(trend_root):
    _write_trend(
        trend_root,
        "2026-W23",
        {"week": "2026-W23", "posts": [{"suggested_tweet": "tweet content"}]},
    )
    posts = generate_trend_posts("2026-W23", _trend_data())
    assert len(posts) == 1
    assert posts[0]["text"] == "tweet content"
    assert posts[0]["type"] == "trend"
    assert posts[0]["media_url"] is None


def test_generate_trend_posts_skips_entries_without_suggested_tweet(trend_root):
    _write_trend(
        trend_root,
        "2026-W23",
        {
            "week": "2026-W23",
            "posts": [
                {"topic": "no tweet"},
                {"suggested_tweet": "valid 1"},
                {"suggested_tweet": ""},
                {"suggested_tweet": "valid 2"},
            ],
        },
    )
    posts = generate_trend_posts("2026-W23", _trend_data())
    assert [p["text"] for p in posts] == ["valid 1", "valid 2"]


def test_generate_trend_posts_caps_at_three(trend_root):
    _write_trend(
        trend_root,
        "2026-W23",
        {"week": "2026-W23", "posts": [{"suggested_tweet": f"tweet {i}"} for i in range(5)]},
    )
    posts = generate_trend_posts("2026-W23", _trend_data())
    assert len(posts) == 3
    assert [p["text"] for p in posts] == ["tweet 0", "tweet 1", "tweet 2"]


def test_generate_trend_posts_schedules_wed_fri_sat_mt(trend_root):
    # Run from a Monday so the monday-advancement loop is a no-op.
    monday_jun1 = datetime(2026, 6, 1, 9, 0, tzinfo=MT)
    _write_trend(
        trend_root,
        "2026-W23",
        {"week": "2026-W23", "posts": [{"suggested_tweet": f"t{i}"} for i in range(3)]},
    )
    posts = generate_trend_posts("2026-W23", _trend_data(monday_jun1))
    # Wed 12:30 PM MT, Fri 9:00 AM MT, Sat 11:00 AM MT
    assert posts[0]["scheduled_at"] == datetime(2026, 6, 3, 12, 30, tzinfo=MT)
    assert posts[1]["scheduled_at"] == datetime(2026, 6, 5, 9, 0, tzinfo=MT)
    assert posts[2]["scheduled_at"] == datetime(2026, 6, 6, 11, 0, tzinfo=MT)
