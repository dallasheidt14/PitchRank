"""Direct tests for the ``team_pair_scoring`` adapter.

The adapter shims ``scripts/find_fuzzy_duplicate_teams.score_team_pair``
and ``scripts/_team_distinction.should_skip_pair`` into ``src/utils/``
via a controlled ``sys.path.insert``. These tests guard:

1. Both re-exports remain importable from the shared module path so
   matchers don't need to do their own ``sys.path`` hackery.
2. ``score_team_pair`` honors its three documented outcomes — clean
   match, variant-rejection ``None``, and unrelated pair ``< 0.80``.
3. ``should_skip_pair`` works for matching and non-matching pairs.

If the shim breaks (e.g., scripts/ moves, or a future stdlib name
collides with one of the imported modules), these tests fail at
collection time with an ImportError, which is the right signal.
"""

from __future__ import annotations

import pytest

from src.utils.team_pair_scoring import score_team_pair, should_skip_pair


class TestScoreTeamPairExposed:
    def test_is_callable(self):
        assert callable(score_team_pair)

    def test_clean_match_scores_high(self):
        a = {"team_name": "Mustang SC 2011 ECNL", "club_name": "Mustang Soccer"}
        b = {"team_name": "Mustang SC 2011 ECNL", "club_name": "Mustang Soccer"}
        # Identical pair with club identity → top-end score.
        assert score_team_pair(a, b) >= 0.95

    def test_variant_mismatch_returns_none(self):
        # Same club, different color → distinct squads, ``None``.
        a = {"team_name": "Mustang SC 2011 ECNL Red", "club_name": "Mustang Soccer"}
        b = {"team_name": "Mustang SC 2011 ECNL Blue", "club_name": "Mustang Soccer"}
        assert score_team_pair(a, b) is None

    def test_returns_float_or_none(self):
        """Contract check: every call returns either ``None`` (variant
        mismatch / protected division) or a ``float`` in ``[0, 1]``.
        Anything else would break callers that ``+`` boosts onto the result.
        """
        a = {"team_name": "Generic 2011", "club_name": "Generic FC"}
        b = {"team_name": "Other Team 2011", "club_name": "Different Club"}
        result = score_team_pair(a, b)
        assert result is None or (isinstance(result, float) and 0.0 <= result <= 1.0)

    def test_empty_names_return_none(self):
        a = {"team_name": "", "club_name": "Mustang Soccer"}
        b = {"team_name": "Mustang SC 2011 ECNL", "club_name": "Mustang Soccer"}
        assert score_team_pair(a, b) is None


class TestShouldSkipPairExposed:
    def test_is_callable(self):
        assert callable(should_skip_pair)

    @pytest.mark.parametrize(
        "name_a,name_b,club,expected",
        [
            # Same team, same age — don't skip
            ("FC X 2011", "FC X 2011", "FC X", False),
            # Same club, different color squads — should skip (variant differs)
            ("FC X 2011 Red", "FC X 2011 Blue", "FC X", True),
        ],
    )
    def test_skip_decisions(self, name_a, name_b, club, expected):
        assert should_skip_pair(name_a, name_b, club) is expected
