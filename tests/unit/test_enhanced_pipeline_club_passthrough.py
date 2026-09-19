"""The importer must hand the matcher every club name exactly as the provider sent it."""

import asyncio

from src.etl.enhanced_pipeline import EnhancedETLPipeline

CLUB_FIELDS = ("club_name", "team_club_name", "home_club_name", "away_club_name", "opponent_club_name")


class _Client:
    pass


class _RecordingMatcher:
    def __init__(self):
        self.received = []

    def match_game_history(self, game_data):
        self.received.append(dict(game_data))
        return {"match_status": "failed"}


def test_import_passes_every_club_field_to_the_matcher_unchanged(monkeypatch):
    pipeline = EnhancedETLPipeline(_Client(), "playmetrics", dry_run=True)
    matcher = _RecordingMatcher()
    pipeline.matcher = matcher
    # Every value resolves to a canonical club, so any rewrite before matching changes it.
    game = {
        "game_uid": "playmetrics:2026-09-12:a:b",
        "club_name": "Phoenix Rising Soccer Club",
        "team_club_name": "Solar SC",
        "home_club_name": "FC Dallas",
        "away_club_name": "Charlotte FC",
        "opponent_club_name": "LA Galaxy",
    }
    stats = {"duplicates_skipped": 0, "skipped_empty_scores": 0, "date_mismatches": 0}

    async def validate(g):
        return g, [], stats

    async def no_duplicates(_g):
        return set(), {}

    monkeypatch.setattr(pipeline, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(pipeline, "_validate_games", validate)
    monkeypatch.setattr(pipeline, "_check_duplicates", no_duplicates)

    asyncio.run(pipeline.import_games([game]))

    assert len(matcher.received) == 1
    assert {field: matcher.received[0][field] for field in CLUB_FIELDS} == {
        "club_name": "Phoenix Rising Soccer Club",
        "team_club_name": "Solar SC",
        "home_club_name": "FC Dallas",
        "away_club_name": "Charlotte FC",
        "opponent_club_name": "LA Galaxy",
    }
