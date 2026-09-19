"""Unit tests for the affinity_or matcher's candidate gates.

Each gate here exists because a dry run against the live Oregon league caught
the shared matching utilities merging two distinct squads at confidence 1.0:

- Distinct Oregon clubs share words such as "Timbers" and "Surf", and
  "portland" sits inside "Portland City United SC"; a same-club check that
  returned on a shared canonical id, or read containment, would merge them.
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
from src.models.squad_name_gates import token_sort_ratio
from src.utils.club_normalizer import normalize_club_name

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
            # Four distinct Oregon clubs sharing the word "Timbers", and FC Portland
            ("FC Portland", "Rogue Valley Timbers"),
            ("Portland Timbers", "Rogue Valley Timbers"),
            ("Eastside Timbers", "Rogue Valley Timbers"),
            ("Eastside Timbers", "Eugene Timbers Futbol Club (ETFC)"),
            ("FC Portland", "Portland Timbers"),
            # "portland" sits inside "portland city united"
            ("FC Portland", "Portland City United SC"),
            # Two different Surf clubs
            ("Cascade Surf", "Oregon Surf"),
        ],
    )
    def test_distinct_clubs_are_refused(self, provider_club, candidate_club):
        assert _is_same_club(provider_club, candidate_club, THRESHOLD) is False

    @pytest.mark.parametrize(
        "provider_club, candidate_club",
        [
            ("Tyler FC", "Tyler SA"),
            ("FC Arkansas", "Arkansas Soccer Club"),
        ],
    )
    def test_names_equal_once_suffixes_are_stripped_are_refused(self, provider_club, candidate_club):
        """Stripped of suffixes the names are identical; ``are_same_club`` keeps the club code and
        treats a place-only name as shared, so it refuses both."""
        assert token_sort_ratio(normalize_club_name(provider_club), normalize_club_name(candidate_club)) == 1.0
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

    def ilike(self, field, value):
        """Case-insensitive equality when the pattern carries no wildcard.

        Mirrors what PostgREST does, because that is the whole reason the
        lookup uses ilike: the DB stores "Cysa Timber Barons" where the team
        name infers "CYSA Timber Barons".
        """
        if field == "club_name":
            self._log.append(value)
            pattern = value.lower()
            self._rows = [r for r in self._rows if (r.get("club_name") or "").lower() == pattern]
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
        return SimpleNamespace(
            data=[{"club_name": r.get("club_name"), "state_code": r["state_code"]} for r in self._rows]
        )


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
    matcher._or_stored_club_name = {}
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

    def test_a_club_stored_in_a_different_case_is_still_found(self):
        """The DB spells it "Cysa Timber Barons"; the team name infers "CYSA"."""
        rows = [{"club_name": "Cysa Timber Barons", "state_code": "WA"}] * 27

        assert _matcher_with(rows)._state_for_club("CYSA Timber Barons") == "WA"

    def test_an_oregon_club_is_searched_in_oregon(self):
        rows = [{"club_name": "FC Portland", "state_code": "OR"}] * 12

        assert _matcher_with(rows)._state_for_club("FC Portland") == "OR"

    def test_a_placeholder_club_is_never_asked(self):
        """"No Club Selection" is not a club; its plurality would be noise.

        One placeholder name covers 1,596 teams across 23 states, so a state
        derived from it would be stamped on every team that carries it.
        """
        rows = [{"club_name": "No Club Selection", "state_code": "WA"}] * 40
        matcher = _matcher_with(rows)

        assert matcher._club_state_plurality("No Club Selection") is None
        assert matcher._state_for_club("No Club Selection") == "OR"
        assert matcher.db.clubs_queried == []

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


class TestClubInference:
    """The feed never names a club, so both paths must infer the same one."""

    def test_a_missing_club_is_inferred_from_the_team_name(self):
        matcher = _matcher_with([])

        assert matcher._club_for("FC Salmon Creek 13B White", None) == "FC Salmon Creek"

    def test_a_supplied_club_wins(self):
        matcher = _matcher_with([])

        assert matcher._club_for("FC Salmon Creek 13B White", "Given Club") == "Given Club"

    def test_no_team_name_infers_nothing(self):
        assert _matcher_with([])._club_for(None, None) is None

    def test_matching_and_creation_infer_the_same_club(self):
        """They used to disagree: matching inferred it, creation got None.

        That stored the whole squad name as the club and skipped the state
        resolver entirely, putting a Washington team on the Oregon board.
        """
        matcher = _matcher_with([])
        name = "FC Salmon Creek 13B White"

        assert matcher._club_for(name, None) == matcher._club_for(name, "")


class TestStateForNewTeam:
    """What gets written is stricter than what gets searched."""

    def _matcher(self, rows, unanimous=None, expect_club=None):
        matcher = _matcher_with(rows)
        seen = []

        def fake_resolver(club):
            seen.append(club)
            return (unanimous, "Washington" if unanimous else None)

        matcher._resolve_state_from_club = fake_resolver
        matcher.clubs_asked_for_unanimity = seen
        return matcher

    def test_a_unanimous_club_stores_its_state(self):
        matcher = self._matcher([{"club_name": "Cysa Timber Barons", "state_code": "WA"}], unanimous="WA")

        assert matcher._state_for_new_team("Cysa Timber Barons") == ("WA", "Washington")

    def test_a_club_whose_rows_disagree_stores_nothing(self):
        """NULL beats a guess: the state tooling can fill a NULL, not a wrong value."""
        rows = [
            {"club_name": "FC Salmon Creek", "state_code": "WA"},
            {"club_name": "FC Salmon Creek", "state_code": "OR"},
        ]
        matcher = self._matcher(rows, unanimous=None)

        assert matcher._state_for_new_team("FC Salmon Creek") == (None, None)

    def test_unanimity_is_asked_under_the_clubs_stored_spelling(self):
        """The inherited resolver compares case-sensitively.

        Handing it the inferred "CYSA Timber Barons" against 27 stored "Cysa
        Timber Barons" rows made it find nothing, and the disagreement branch
        then stored NULL for a club whose every row says WA.
        """
        rows = [{"club_name": "Cysa Timber Barons", "state_code": "WA"}] * 27
        matcher = self._matcher(rows, unanimous="WA")

        matcher._state_for_new_team("CYSA Timber Barons")

        assert matcher.clubs_asked_for_unanimity == ["Cysa Timber Barons"]

    def test_an_unknown_club_takes_the_leagues_state(self):
        matcher = self._matcher([], unanimous=None)

        assert matcher._state_for_new_team("Brand New Club") == ("OR", "Oregon")


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
