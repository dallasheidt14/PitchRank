"""Verify each provider matcher applies ``canonicalize_club_name`` before
its gated funnel.

The four provider matchers (SOM Sports, SincSports, PlayMetrics,
Affinity-WA) each apply the per-state Monday-hygiene override registry to
the provider's club name before the candidate-retrieval gate. Without
this, the gate misses canonical rows whose ``teams.club_name`` was
rewritten by the Monday job (``"Mustang SC"`` → ``"Mustang Soccer"``,
``"Beach FC (CA)"`` → ``"Beach Futbol Club"``, ``"XF"`` →
``"Crossfire Premier"``).

The test target is the same: ``canonicalize_club_name`` must be reached
during ``_fuzzy_match_team``. Each provider has a slightly different
gate mechanism (SQL ``ilike`` vs Python ``are_same_club``), but the
canonicalization step is provider-agnostic.
"""

from __future__ import annotations

import inspect

import pytest


@pytest.mark.parametrize(
    "module_path,class_name",
    [
        ("src.models.somsports_matcher", "SomSportsGameMatcher"),
        ("src.models.sincsports_matcher", "SincSportsGameMatcher"),
        ("src.models.playmetrics_matcher", "PlayMetricsGameMatcher"),
        ("src.models.affinity_wa_matcher", "AffinityWAGameMatcher"),
    ],
)
def test_fuzzy_match_team_invokes_canonicalize(module_path, class_name):
    """Each provider's ``_fuzzy_match_team`` must reference the shared
    ``canonicalize_club_name`` helper. Regression guard against future
    refactors that silently drop the wire-in.
    """
    module = __import__(module_path, fromlist=[class_name])
    cls = getattr(module, class_name)
    src = inspect.getsource(cls._fuzzy_match_team)
    assert "canonicalize_club_name" in src, (
        f"{class_name}._fuzzy_match_team is expected to call "
        f"canonicalize_club_name (per the cross-provider wire-in). If you "
        f"removed it intentionally, update this test."
    )


@pytest.mark.parametrize(
    "module_path,class_name",
    [
        ("src.models.somsports_matcher", "SomSportsGameMatcher"),
        ("src.models.sincsports_matcher", "SincSportsGameMatcher"),
        ("src.models.playmetrics_matcher", "PlayMetricsGameMatcher"),
        ("src.models.affinity_wa_matcher", "AffinityWAGameMatcher"),
    ],
)
def test_provider_imports_canonicalize_at_module_level(module_path, class_name):
    """The matcher module must import ``canonicalize_club_name`` at the
    module level (not lazily inside a function), to keep the wire-in
    discoverable via standard ``grep``/import-graph tools.
    """
    module = __import__(module_path, fromlist=[class_name])
    assert hasattr(module, "canonicalize_club_name"), (
        f"{module_path} should import canonicalize_club_name at module level"
    )


class TestSomSportsHygieneScoring:
    """``SomSportsGameMatcher._calculate_match_score`` delegates to the
    hygiene pipeline's ``score_team_pair`` (via the team_pair_scoring
    adapter). Tests verify the override exists and produces expected
    behavior on clean matches, variant-rejects, and unrelated pairs.
    """

    @pytest.fixture
    def matcher(self):
        from unittest.mock import MagicMock

        from src.models.somsports_matcher import SomSportsGameMatcher

        return SomSportsGameMatcher(MagicMock(), provider_id="x", alias_cache={})

    def test_override_exists(self, matcher):
        from src.models.game_matcher import GameHistoryMatcher
        from src.models.somsports_matcher import SomSportsGameMatcher

        assert SomSportsGameMatcher._calculate_match_score is not GameHistoryMatcher._calculate_match_score, (
            "SomSports must override the base scorer to use hygiene's score_team_pair"
        )

    def test_clean_match_scores_high(self, matcher):
        # Mustang SC 2011B ECNL ↔ Mustang SC 2011 ECNL (same club, same age,
        # same tier) should auto-merge under hygiene scoring (>= 0.91).
        p = {"team_name": "Mustang SC 2011B ECNL", "club_name": "Mustang Soccer"}
        c = {"team_name": "Mustang SC 2011 ECNL", "club_name": "Mustang Soccer"}
        score = matcher._calculate_match_score(p, c)
        assert score >= 0.91, f"expected auto-approve score, got {score}"

    def test_variant_mismatch_returns_zero(self, matcher):
        # Red ≠ Blue squads under the same club. Hygiene's
        # extract_team_variant returns None → adapter returns 0.0.
        p = {"team_name": "Mustang SC 2011 ECNL Red", "club_name": "Mustang Soccer"}
        c = {"team_name": "Mustang SC 2011 ECNL Blue", "club_name": "Mustang Soccer"}
        score = matcher._calculate_match_score(p, c)
        assert score == 0.0

    def test_unrelated_pair_scores_low(self, matcher):
        # Different clubs, different teams — should land well below review threshold.
        p = {"team_name": "Mustang SC 2011 ECNL", "club_name": "Mustang Soccer"}
        c = {"team_name": "Totally Different FC 2011", "club_name": "Other Club"}
        score = matcher._calculate_match_score(p, c)
        assert score < 0.75, f"expected sub-review score, got {score}"

    def test_missing_clubs_dont_crash(self, matcher):
        # Defensive: ``None`` / missing club fields shouldn't raise.
        p = {"team_name": "Some Team 2011", "club_name": None}
        c = {"team_name": "Other Team 2011"}  # no club_name key
        score = matcher._calculate_match_score(p, c)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_team_pair_none_maps_to_zero(self, matcher, monkeypatch):
        """When ``score_team_pair`` returns ``None`` (variant mismatch /
        protected division), the adapter must return ``0.0`` — not ``None``
        — so the base ``_fuzzy_match_team`` loop's ``>= threshold`` check
        works correctly. Direct monkeypatch test isolates the adapter
        contract from whatever the real hygiene scorer happens to return.
        """
        monkeypatch.setattr(
            "src.models.somsports_matcher.score_team_pair",
            lambda a, b: None,
        )
        p = {"team_name": "anything", "club_name": "any club"}
        c = {"team_name": "whatever", "club_name": "other club"}
        score = matcher._calculate_match_score(p, c)
        assert score == 0.0
        assert isinstance(score, float)

    def test_score_team_pair_numeric_passes_through(self, matcher, monkeypatch):
        """Numeric returns from ``score_team_pair`` are forwarded as-is
        (cast to ``float``)."""
        monkeypatch.setattr(
            "src.models.somsports_matcher.score_team_pair",
            lambda a, b: 0.873,
        )
        p = {"team_name": "anything", "club_name": "any club"}
        c = {"team_name": "whatever", "club_name": "other club"}
        assert matcher._calculate_match_score(p, c) == pytest.approx(0.873)
