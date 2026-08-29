"""The association map must fail closed, and must never read CAN as Canada.

GotSport's ``team_association`` is the registration body a team belongs to, not a
postal code, and two of its properties bite anyone who treats it as one.

``CAN`` is California North. Read as a country it sends every Northern
California team to Canada, and California is the largest cohort in the database.
Canada itself is ``CND``.

Four states never emit their own postal code. California, New York, Pennsylvania
and Texas split by region, so a map holding only the identity cases silently
drops four of the five largest cohorts while looking complete.

The closed-map rule matters for the opposite reason: an unrecognised code has to
mean "no signal", never "probably a state". The discovery path creates tens of
thousands of teams a year off this field, and a Brazilian or Canadian club
guessed into a US state board is worse than one with no state at all.
"""

import re
from pathlib import Path

import pytest

from src.utils.team_association_map import (
    CANADIAN_PROVINCES,
    IDENTITY,
    NON_US_BODIES,
    SPLIT,
    to_state_code,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISCOVERY_SCRIPT = PROJECT_ROOT / "scripts" / "discover_teams_from_opponents.py"

# Keys the team_details payload does not have. Reading any of them returns "" on
# every call, which is how the opponent's state came to be persisted as the
# discovered team's own.
ABSENT_PAYLOAD_KEYS = ("full_name", "state", "age", "gender")


def test_can_is_california_north_not_canada():
    assert to_state_code("CAN") == "CA"


def test_canada_is_cnd_and_maps_to_nothing():
    assert to_state_code("CND") is None


@pytest.mark.parametrize("code,expected", sorted(SPLIT.items()))
def test_split_codes_resolve_to_their_state(code, expected):
    assert to_state_code(code) == expected


@pytest.mark.parametrize("code", sorted(IDENTITY))
def test_identity_codes_resolve_to_themselves(code):
    assert to_state_code(code) == code


def test_the_four_split_states_are_never_identity():
    """They only ever emit a regional code, so listing them would be a guess."""
    assert IDENTITY.isdisjoint({"CA", "NY", "PA", "TX"})


def test_split_targets_are_absent_from_identity_and_complete():
    assert set(SPLIT.values()) == {"CA", "NY", "PA", "TX"}


@pytest.mark.parametrize("code", sorted(CANADIAN_PROVINCES | NON_US_BODIES))
def test_known_non_us_bodies_never_resolve(code):
    assert to_state_code(code) is None


@pytest.mark.parametrize("value", ["", "   ", None, "ZZ", "XX", "MT", "DC", "USA", "12"])
def test_unmapped_input_fails_closed(value):
    assert to_state_code(value) is None


def test_lookup_is_case_and_whitespace_insensitive():
    assert to_state_code(" can ") == "CA"
    assert to_state_code("oh") == "OH"


def test_identity_holds_only_real_two_letter_codes():
    assert all(re.fullmatch(r"[A-Z]{2}", code) for code in IDENTITY)


@pytest.mark.parametrize("key", ABSENT_PAYLOAD_KEYS)
def test_discovery_resolver_does_not_read_absent_payload_keys(key):
    """The resolver dict must not go back to keys team_details never returns."""
    source = DISCOVERY_SCRIPT.read_text(encoding="utf-8")
    assert f'payload.get("{key}")' not in source


def test_discovery_reads_the_real_locality_and_cohort_fields():
    source = DISCOVERY_SCRIPT.read_text(encoding="utf-8")
    for key in ("team_association", "display_age_group", "display_gender"):
        assert f'payload.get("{key}")' in source


def test_discovery_does_not_persist_the_opponents_state():
    """unknown_state_used is the played-against team's state, not this team's."""
    source = DISCOVERY_SCRIPT.read_text(encoding="utf-8")
    assert 'row.get("unknown_state_used")' not in source
