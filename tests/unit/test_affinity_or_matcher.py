"""Unit tests for the affinity_or matcher's candidate gates.

Each gate here exists because a dry run against the live Oregon league caught
the shared matching utilities merging two distinct squads at confidence 1.0:

- ``are_same_club`` returns on canonical id alone, and the canonical map folds
  every Oregon "Timbers" affiliate into ``portland_timbers``.
- ``similarity_score`` is ``token_set_ratio``, which reads containment, so
  "FC Portland" scores a perfect 1.0 against "Portland City United SC".
- ``extract_team_variant`` only knows colours, returning None for both
  "Academy" and "Premier" — and the variant gate reads None == None as
  agreement.
- Nothing at all separated "Black 1" from "Black 2".

The wiring of these gates into candidate selection is covered by the dry-run
verification against the database, not by a mocked PostgREST chain.
"""

import pytest

from src.models.affinity_or_matcher import (
    _extract_lane_number,
    _extract_tier_tokens,
    _is_same_club,
    _normalize_for_affinity_or,
)

THRESHOLD = 0.9


class TestIsSameClub:
    """Canonical agreement alone is not enough; the names must also agree."""

    @pytest.mark.parametrize(
        "provider_club, candidate_club",
        [
            ("FC Portland", "FC Portland Academy"),
            ("Oregon Surf", "Oregon Surf SC"),
            ("Columbia Premier SC", "Columbia Premier Soccer Club"),
            ("Apex FC", "Apex FC"),
        ],
    )
    def test_same_club_still_matches(self, provider_club, candidate_club):
        assert _is_same_club(provider_club, candidate_club, THRESHOLD) is True

    @pytest.mark.parametrize(
        "provider_club, candidate_club",
        [
            # All four collapse to canonical 'portland_timbers'
            ("FC Portland", "Rogue Valley Timbers"),
            ("Portland Timbers", "Rogue Valley Timbers"),
            ("Eastside Timbers", "Rogue Valley Timbers"),
            ("Eastside Timbers", "Eugene Timbers Futbol Club (ETFC)"),
            ("FC Portland", "Portland Timbers"),
            # token_set_ratio scores this pair 1.0 by containment
            ("FC Portland", "Portland City United SC"),
            # Both collapse to canonical 'surf'
            ("Cascade Surf", "Oregon Surf"),
        ],
    )
    def test_distinct_clubs_are_refused(self, provider_club, candidate_club):
        assert _is_same_club(provider_club, candidate_club, THRESHOLD) is False


class TestTierTokens:
    """A tier is never mergeable with a different tier."""

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("United PDX ECNL 2013", {"ecnl"}),
            ("Some Club ECNL RL 2013", {"ecnl", "rl"}),
            ("WOODBURN FC 2013 Academy", {"academy"}),
            ("WOODBURN FC 2013 Premier", {"premier"}),
            ("FC Portland 2013 Red", set()),
            ("Westside Metros 2013 Copa White", set()),
        ],
    )
    def test_tiers_are_read_from_the_name(self, name, expected):
        assert _extract_tier_tokens(name) == frozenset(expected)

    def test_ecnl_and_ecnl_rl_are_different_tiers(self):
        """The pair CLAUDE.md names explicitly: ECNL is not ECNL-RL."""
        assert _extract_tier_tokens("United PDX ECNL 2013") != _extract_tier_tokens("United PDX ECNL RL 2013")

    def test_academy_and_premier_are_different_tiers(self):
        assert _extract_tier_tokens("WOODBURN FC 2013 Academy") != _extract_tier_tokens("WOODBURN FC 2013 Premier")


class TestLaneNumber:
    """Oregon separates same-colour squads of one club by a trailing number."""

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Columbia Premier SC 2013 Black 1", "1"),
            ("Columbia Premier SC 2013 Black 2", "2"),
            ("Eugene Metro FC 2013 Inter Comp 3", "3"),
            # A trailing state suffix must not hide the lane
            ("Columbia Premier SC N1 2012/13 Black 1 (OR)", "1"),
            # A birth year is not a lane
            ("FC Portland 2013", None),
            ("FC Portland 2013 Red", None),
            ("RVT N1 2013/14 Red (OR)", None),
        ],
    )
    def test_lane_is_the_trailing_number(self, name, expected):
        assert _extract_lane_number(name) == expected

    def test_the_two_columbia_squads_differ(self):
        one = _extract_lane_number(_normalize_for_affinity_or("Columbia Premier SC 13B Black 1"))
        two = _extract_lane_number(_normalize_for_affinity_or("Columbia Premier SC 13B Black 2"))

        assert (one, two) == ("1", "2")
