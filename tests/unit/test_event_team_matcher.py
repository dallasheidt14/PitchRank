from types import SimpleNamespace

import httpx
import pytest

from src.tournaments.event_team_matcher import (
    EventTeamSearchQuery,
    build_candidate_age_groups,
    classify_match_result,
    fetch_db_candidates,
    rank_db_candidates,
)


def test_build_candidate_age_groups_prefers_name_age_and_event_age():
    query = EventTeamSearchQuery(
        event_team_name="Dynamos SC 2016 SC",
        event_age_group="u11",
        event_gender="Male",
        event_club_name="Dynamos SC",
    )

    assert build_candidate_age_groups(query) == ["u10", "u11"]


def test_rank_db_candidates_skips_same_club_wrong_variant():
    query = EventTeamSearchQuery(
        event_team_name="Eastside B14 white",
        event_age_group="u12",
        event_gender="Male",
        event_club_name="Eastside FC",
        search_age_group="u12",
    )
    candidates = [
        {
            "team_id_master": "white-team",
            "team_name": "Eastside FC 2014 White",
            "club_name": "Eastside FC",
            "state_code": "WA",
            "age_group": "u12",
            "gender": "Male",
            "provider_team_id": "490629",
            "is_deprecated": False,
        },
        {
            "team_id_master": "blue-team",
            "team_name": "Eastside FC 2014 Blue",
            "club_name": "Eastside FC",
            "state_code": "WA",
            "age_group": "u12",
            "gender": "Male",
            "provider_team_id": "490630",
            "is_deprecated": False,
        },
    ]

    matches = rank_db_candidates(query, candidates, limit=5)

    assert [match.team_id_master for match in matches] == ["white-team"]
    assert matches[0].score_reason in {"normalized_name_exact", "weekly_score"}


def test_rank_db_candidates_prefers_actual_play_up_team_age():
    query = EventTeamSearchQuery(
        event_team_name="Dynamos SC 2016 SC",
        event_age_group="u11",
        event_gender="Male",
        event_club_name="Dynamos SC",
    )
    candidates = [
        {
            "team_id_master": "play-up-u10",
            "team_name": "Dynamos SC 2016 SC",
            "club_name": "Dynamos SC",
            "state_code": "AZ",
            "age_group": "u10",
            "gender": "Male",
            "provider_team_id": "126693",
            "is_deprecated": False,
        },
        {
            "team_id_master": "older-u11",
            "team_name": "Dynamos SC 2015 SC",
            "club_name": "Dynamos SC",
            "state_code": "AZ",
            "age_group": "u11",
            "gender": "Male",
            "provider_team_id": "999999",
            "is_deprecated": False,
        },
    ]

    matches = rank_db_candidates(query, candidates, limit=5)

    assert matches[0].team_id_master == "play-up-u10"
    assert matches[0].age_match_kind == "search_age_exact"


def test_classify_match_result_uses_margin_for_high_confidence():
    query = EventTeamSearchQuery(
        event_team_name="FC Dallas 2012",
        event_age_group="u14",
        event_gender="Male",
        event_club_name="FC Dallas",
        search_age_group="u14",
    )
    candidates = [
        {
            "team_id_master": "best",
            "team_name": "FC Dallas 2012",
            "club_name": "FC Dallas",
            "state_code": "TX",
            "age_group": "u14",
            "gender": "Male",
            "provider_team_id": "123",
            "is_deprecated": False,
        },
        {
            "team_id_master": "second",
            "team_name": "Dallas Texans 2012",
            "club_name": "Dallas Texans",
            "state_code": "TX",
            "age_group": "u14",
            "gender": "Male",
            "provider_team_id": "124",
            "is_deprecated": False,
        },
    ]

    matches = rank_db_candidates(query, candidates, limit=5)
    status, best_score, second_score, score_gap = classify_match_result(matches)

    assert status in {"strict_exact", "high_confidence"}
    assert best_score is not None
    assert second_score is not None
    assert score_gap is not None and score_gap >= 0


class _FakeQueryBuilder:
    def __init__(self, pages, transient_failures=0, fatal_after=None):
        self._pages = pages
        self._transient_remaining = transient_failures
        self._fatal_after = fatal_after
        self._calls = 0
        self._offset = 0

    def select(self, *_args, **_kwargs):
        return self

    def ilike(self, *_args, **_kwargs):
        return self

    def or_(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def range(self, start, _end):
        self._offset = start
        return self

    def execute(self):
        self._calls += 1
        if self._transient_remaining > 0:
            self._transient_remaining -= 1
            raise httpx.ConnectError("UNEXPECTED_EOF_WHILE_READING")
        if self._fatal_after is not None and self._calls > self._fatal_after:
            raise RuntimeError("should not be called past fatal_after")
        page_index = self._offset // 1000
        data = self._pages[page_index] if page_index < len(self._pages) else []
        return SimpleNamespace(data=data)


class _FakeClient:
    def __init__(self, builder):
        self._builder = builder

    def table(self, _name):
        return self._builder


def _query():
    return EventTeamSearchQuery(
        event_team_name="Test Team",
        event_age_group="u12",
        event_gender="Male",
        event_club_name="Test Club",
    )


def test_fetch_db_candidates_retries_transient_connect_error(monkeypatch):
    monkeypatch.setattr("src.tournaments.event_team_matcher.time.sleep", lambda _s: None)
    builder = _FakeQueryBuilder(pages=[[{"team_id_master": "ok"}], []], transient_failures=2)
    client = _FakeClient(builder)

    rows = fetch_db_candidates(client, _query())

    assert rows == [{"team_id_master": "ok"}]
    # 2 transient failures + 1 success; loop exits because batch < page_size.
    assert builder._calls == 3


def test_fetch_db_candidates_raises_after_max_attempts(monkeypatch):
    monkeypatch.setattr("src.tournaments.event_team_matcher.time.sleep", lambda _s: None)
    builder = _FakeQueryBuilder(pages=[[]], transient_failures=99)
    client = _FakeClient(builder)

    with pytest.raises(httpx.ConnectError):
        fetch_db_candidates(client, _query())

    assert builder._calls == 3


def test_fetch_db_candidates_does_not_retry_unrelated_errors(monkeypatch):
    monkeypatch.setattr("src.tournaments.event_team_matcher.time.sleep", lambda _s: None)

    class _Boom:
        def select(self, *_a, **_k):
            return self

        def ilike(self, *_a, **_k):
            return self

        def or_(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def range(self, *_a, **_k):
            return self

        def execute(self):
            raise ValueError("not transient")

    client = _FakeClient(_Boom())

    with pytest.raises(ValueError):
        fetch_db_candidates(client, _query())
