"""Verify ``EnhancedETLPipeline._ensure_initialized()`` selects the right
matcher subclass based on ``provider_code``.

Bare ``python -c`` construction is not viable here — the alias-cache preload
hits Supabase before the matcher branch is reached, so the test needs a
mock client that returns empty data at every chained ``.table().select()
.execute()`` call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.etl.enhanced_pipeline import EnhancedETLPipeline


def _build_empty_supabase_mock(provider_id: str = "provider-uuid-x") -> MagicMock:
    """Return a Supabase client mock whose every ``.execute()`` yields empty.

    Provider lookup: ``providers`` table single row with the given UUID.
    All other reads: ``.execute().data = []`` so the alias preload skips.
    """
    supabase = MagicMock()

    provider_result = MagicMock()
    provider_result.data = {"id": provider_id}

    empty_result = MagicMock()
    empty_result.data = []

    def _table(name):
        chain = MagicMock()
        if name == "providers":
            chain.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
        # Generic chained reads → empty.
        chain.select.return_value.execute.return_value = empty_result
        chain.select.return_value.eq.return_value.execute.return_value = empty_result
        chain.select.return_value.in_.return_value.execute.return_value = empty_result
        chain.select.return_value.limit.return_value.execute.return_value = empty_result
        chain.rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=empty_result)))
        return chain

    supabase.table.side_effect = _table
    supabase.rpc = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=empty_result)))
    return supabase


@pytest.mark.parametrize(
    "provider_code,expected_cls",
    [
        ("somsports", "SomSportsGameMatcher"),
        ("sincsports", "SincSportsGameMatcher"),
    ],
)
def test_provider_routes_to_expected_matcher(provider_code, expected_cls):
    supabase = _build_empty_supabase_mock()
    pipeline = EnhancedETLPipeline(supabase, provider_code, dry_run=True)
    pipeline._ensure_initialized()
    assert type(pipeline.matcher).__name__ == expected_cls


def test_somsports_routes_to_somsports_matcher():
    """Plan Step 5 verification: the new elif branch wires up the matcher
    AND inherits the shared MATCHING_CONFIG thresholds (aligned with the
    weekly hygiene pipeline's auto-merge cutoffs)."""
    from config.settings import MATCHING_CONFIG

    supabase = _build_empty_supabase_mock()
    pipeline = EnhancedETLPipeline(supabase, "somsports", dry_run=True)
    pipeline._ensure_initialized()
    assert type(pipeline.matcher).__name__ == "SomSportsGameMatcher"
    assert pipeline.matcher.fuzzy_threshold == MATCHING_CONFIG["fuzzy_threshold"]
    assert pipeline.matcher.auto_approve_threshold == MATCHING_CONFIG["auto_approve_threshold"]
    assert pipeline.matcher.dry_run is True


def test_somsports_matcher_is_normalization_only():
    """No auto-create override: SomSportsGameMatcher must NOT shadow the base's
    _match_team. The base's review-queue path is what feeds the weekly hygiene
    pipeline; an override would short-circuit it."""
    from src.models.game_matcher import GameHistoryMatcher
    from src.models.somsports_matcher import SomSportsGameMatcher

    assert SomSportsGameMatcher._match_team is GameHistoryMatcher._match_team, (
        "SomSportsGameMatcher must not override _match_team — the base path "
        "feeds team_match_review_queue, which the weekly hygiene job resolves."
    )
    assert not hasattr(SomSportsGameMatcher, "_create_new_somsports_team"), (
        "Auto-create path was intentionally removed; the hygiene pipeline owns "
        "team creation/merge via find_queue_matches.py."
    )
