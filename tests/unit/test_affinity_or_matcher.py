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

from types import SimpleNamespace

import pytest

from src.models.affinity_or_matcher import (
    AffinityORGameMatcher,
    _extract_lane_number,
    _extract_tier_tokens,
    _is_same_club,
    _normalize_for_affinity_or,
    _tiers_conflict,
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

    @pytest.mark.parametrize(
        "spelling",
        ["United PDX ECNL RL 2013", "United PDX ECNL-RL 2013", "United PDX ECRL 2013"],
    )
    def test_every_ecnl_rl_spelling_is_a_different_tier_from_ecnl(self, spelling):
        """The pair CLAUDE.md names explicitly: ECNL is not ECNL-RL.

        game_matcher.extract_club_from_team_name strips all three spellings, so
        all three are live in this data. Testing only the space-separated one
        left the hyphen and the contraction reading as no tier at all, which
        merged an ECNL-RL squad onto its club's ECNL squad at confidence 1.0.
        """
        assert _extract_tier_tokens(spelling) != _extract_tier_tokens("United PDX ECNL 2013")

    def test_the_three_ecnl_rl_spellings_agree_with_each_other(self):
        assert (
            _extract_tier_tokens("United PDX ECNL RL 2013")
            == _extract_tier_tokens("United PDX ECNL-RL 2013")
            == _extract_tier_tokens("United PDX ECRL 2013")
        )

    def test_academy_and_premier_are_different_tiers(self):
        assert _extract_tier_tokens("WOODBURN FC 2013 Academy") != _extract_tier_tokens("WOODBURN FC 2013 Premier")


class TestTiersConflict:
    """A one-sided competitive tier is a difference; a club-shaped word is not."""

    def _tiers(self, name):
        return _extract_tier_tokens(name)

    @pytest.mark.parametrize(
        "provider, candidate",
        [
            # One side names ECNL and the other names nothing — the case that
            # slipped past the both-sided rule with the club+variant boosts
            # carrying it over auto-approve.
            ("FC Portland 2013 Red", "FC Portland ECNL 2013 Red"),
            ("FC Portland ECNL 2013 Red", "FC Portland 2013 Red"),
            # Every spelling of the regional league against plain ECNL
            ("United PDX ECNL 2013", "United PDX ECNL RL 2013"),
            ("United PDX ECNL 2013", "United PDX ECNL-RL 2013"),
            ("United PDX ECNL 2013", "United PDX ECRL 2013"),
            # Both name a club-shaped word, and they differ
            ("Woodburn FC 2013 Academy", "Woodburn FC 2013 Premier"),
        ],
    )
    def test_conflicting_tiers_are_refused(self, provider, candidate):
        assert _tiers_conflict(self._tiers(provider), self._tiers(candidate)) is True

    @pytest.mark.parametrize(
        "provider, candidate",
        [
            # Neither names a tier
            ("FC Portland 2013 Red", "FC Portland 2014 Red"),
            # Same tier both sides
            ("United PDX ECNL 2013", "United PDX ECNL 2014"),
            ("United PDX ECRL 2013", "United PDX ECNL-RL 2014"),
            # "Academy" and "Premier" are part of these clubs' names, not tiers,
            # so one side carrying the club's full name must not reject.
            ("Coast to Coast Futbol Academy 2013 Red", "Coast to Coast 2014 Red"),
            ("Oregon Premier FC 2013 Red", "Oregon Premier 2014 Red"),
        ],
    )
    def test_compatible_tiers_are_allowed(self, provider, candidate):
        assert _tiers_conflict(self._tiers(provider), self._tiers(candidate)) is False


class _FakeQuery:
    """Chainable PostgREST double that only yields rows at execute().

    A builder that returned rows on ``.eq()`` would let a caller that never
    executes look like it read the table — the failure mode CLAUDE.md describes
    for deferred builders.
    """

    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def select(self, *_a, **_k):
        return self

    def eq(self, field, value):
        if field == "club_name":
            self._log.append(value)
            self._rows = [r for r in self._rows if r.get("club_name") == value]
        return self

    def neq(self, *_a, **_k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"state_code": r["state_code"]} for r in self._rows])


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.clubs_queried = []

    def table(self, _name):
        return _FakeQuery(list(self.rows), self.clubs_queried)


def _matcher_with(rows):
    matcher = AffinityORGameMatcher.__new__(AffinityORGameMatcher)
    matcher.db = _FakeDB(rows)
    matcher._or_search_state_cache = {}
    return matcher


class TestSearchState:
    """Which state to look in is decided per club, not stamped Oregon."""

    def test_a_club_stored_in_washington_is_searched_in_washington(self):
        """OYSA reaches into SW Washington; FC Salmon Creek lives there."""
        rows = [{"club_name": "FC Salmon Creek", "state_code": "WA"}] * 31

        assert _matcher_with(rows)._state_for_club("FC Salmon Creek") == "WA"

    def test_a_lone_outlier_does_not_flip_the_club(self):
        """Pacific FC is 82 WA rows and one BC. Unanimity would abstain here."""
        rows = [{"club_name": "Pacific FC", "state_code": "WA"}] * 82
        rows.append({"club_name": "Pacific FC", "state_code": "BC"})

        assert _matcher_with(rows)._state_for_club("Pacific FC") == "WA"

    def test_an_oregon_club_is_searched_in_oregon(self):
        rows = [{"club_name": "FC Portland", "state_code": "OR"}] * 12

        assert _matcher_with(rows)._state_for_club("FC Portland") == "OR"

    def test_an_unknown_club_falls_back_to_the_leagues_state(self):
        assert _matcher_with([])._state_for_club("Brand New Club") == "OR"

    def test_no_club_name_falls_back_without_querying(self):
        matcher = _matcher_with([{"club_name": "x", "state_code": "WA"}])

        assert matcher._state_for_club(None) == "OR"
        assert matcher.db.clubs_queried == []

    def test_the_answer_is_cached_per_club(self):
        matcher = _matcher_with([{"club_name": "FC Salmon Creek", "state_code": "WA"}])

        matcher._state_for_club("FC Salmon Creek")
        matcher._state_for_club("FC Salmon Creek")

        assert matcher.db.clubs_queried == ["FC Salmon Creek"]


class TestLaneNumber:
    """Oregon separates same-colour squads of one club by a trailing number."""

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Columbia Premier SC 2013 Black 1", "1"),
            ("Columbia Premier SC 2013 Black 2", "2"),
            ("Eugene Metro FC 2013 Inter Comp 3", "3"),
            # A trailing parenthetical must not hide the lane, whatever it says
            ("Columbia Premier SC N1 2012/13 Black 1 (OR)", "1"),
            ("Columbia Premier SC N1 2012/13 Black 1 (Oregon)", "1"),
            # A birth year is not a lane
            ("FC Portland 2013", None),
            ("FC Portland 2013 Red", None),
            ("RVT N1 2013/14 Red (OR)", None),
            # Nor is the tail of a two-digit birth-year band. Every trailing
            # two-digit token in the OR corpus is one of these, so reading it
            # as a lane hard-rejects correct candidates over a year.
            ("Eugene Metro FC ECNL RL B2013/14", None),
            ("Westside Metros ECNL RL B06/07", None),
            ("Eastside Timbers 09", None),
        ],
    )
    def test_lane_is_the_trailing_number(self, name, expected):
        assert _extract_lane_number(name) == expected

    def test_the_two_columbia_squads_differ(self):
        one = _extract_lane_number(_normalize_for_affinity_or("Columbia Premier SC 13B Black 1"))
        two = _extract_lane_number(_normalize_for_affinity_or("Columbia Premier SC 13B Black 2"))

        assert (one, two) == ("1", "2")
