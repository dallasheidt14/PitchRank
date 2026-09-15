"""The importer's periodic client refresh must keep the URL and key the caller's client was built with."""

import asyncio

import pytest

from src.etl import enhanced_pipeline
from src.etl.enhanced_pipeline import EnhancedETLPipeline

CALLER_URL = "https://caller-project.supabase.co"
CONFIG_URL = "https://config-project.supabase.co"


class _Url:
    """Stands in for the yarl URL supabase 2.26+ stores on the client."""

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text


class _Client:
    def __init__(self, url, key):
        self.supabase_url = url
        self.supabase_key = key


class _Matcher:
    def __init__(self, db):
        self.db = db

    def match_game_history(self, *_a, **_k):
        raise RuntimeError("stub matcher")


@pytest.fixture
def built(monkeypatch):
    calls = []

    def fake_create_client(url, key):
        # supabase's create_client runs re.match on the URL, which raises TypeError for anything but str.
        if not isinstance(url, str):
            raise TypeError(f"create_client needs a str url, got {type(url)}")
        calls.append((url, key))
        return _Client(url, key)

    monkeypatch.setattr(enhanced_pipeline, "create_client", fake_create_client)
    # Pin config's URL and key to values distinct from the caller's, so any rebuild that reads
    # config instead of the current client fails the assertions below.
    monkeypatch.setattr(enhanced_pipeline, "SUPABASE_URL", CONFIG_URL, raising=False)
    monkeypatch.setattr(enhanced_pipeline, "SUPABASE_KEY", "anon-key", raising=False)
    return calls


def _pipeline(client):
    pipeline = EnhancedETLPipeline(client, "sincsports", dry_run=True)
    pipeline.matcher = _Matcher(client)
    return pipeline


def test_refresh_rebuilds_with_the_callers_url_and_key(built):
    client = _Client(CALLER_URL, "service-role-key")
    pipeline = _pipeline(client)

    pipeline._refresh_client()

    assert built == [("https://caller-project.supabase.co", "service-role-key")]
    assert pipeline.supabase is not client
    assert pipeline.matcher.db is pipeline.supabase


def test_refresh_accepts_a_url_object(built):
    pipeline = _pipeline(_Client(_Url("https://caller-project.supabase.co/"), "service-role-key"))

    pipeline._refresh_client()

    assert built == [("https://caller-project.supabase.co/", "service-role-key")]


def test_import_loop_refreshes_once_per_interval_with_the_callers_key(built, monkeypatch):
    pipeline = _pipeline(_Client(CALLER_URL, "service-role-key"))
    games = [{"game_uid": f"sincsports:2026-09-0{i}:a:b"} for i in (1, 2, 3)]
    stats = {"duplicates_skipped": 0, "skipped_empty_scores": 0, "date_mismatches": 0}

    async def validate(g):
        return g, [], stats

    async def no_duplicates(_g):
        return set(), {}

    monkeypatch.setitem(enhanced_pipeline.MATCHING_CONFIG, "connection_refresh_interval", 2)
    monkeypatch.setattr(pipeline, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(pipeline, "_validate_games", validate)
    monkeypatch.setattr(pipeline, "_check_duplicates", no_duplicates)

    asyncio.run(pipeline.import_games(games))

    # Three games at an interval of two: one refresh, at the second game.
    assert built == [("https://caller-project.supabase.co", "service-role-key")]
