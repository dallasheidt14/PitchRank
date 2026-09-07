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

import ast
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

TEAM_DETAILS_URL = "team_ranking_data/team_details"

# Derived, never listed. Every copy of this resolver has been fixed one incident at
# a time, and a hand-written tuple is why: it cannot fail for a script it omits.
RESOLVER_SCRIPTS = tuple(
    sorted(p for p in (PROJECT_ROOT / "scripts").glob("*.py") if TEAM_DETAILS_URL in p.read_text(encoding="utf-8"))
)

# Two copies still read the absent keys. They are in update-missing-club-and-state.yml
# rather than the hygiene chain, and IMP-142 tracks them; naming them here keeps the
# guard derived and makes the deferral impossible to lose. Delete an entry as it is
# fixed -- the test below fails if one is fixed and left listed.
KNOWN_BROKEN = frozenset({"backfill_missing_club_names.py", "backfill_missing_state_codes.py"})

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


def test_every_us_state_is_reachable():
    """Derived from the fifty states, not from the map, so it fails for the one the
    map omits rather than agreeing with whatever the map happens to contain.

    Montana was the last hold-out and is the reason this exists: it read as no
    signal, so a probe that answered ``MT`` was paid for and discarded, and the
    team kept the wrong state while the ledger recorded a durable non-answer that
    suppressed asking again. The gap cost real calls before anyone saw it.

    DC is deliberately outside this list. No payload has named it, and the map's
    rule is that a code is added on evidence rather than by inference.
    """
    states = set(
        "AK AL AR AZ CA CO CT DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO "
        "MS MT NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI "
        "WV WY".split()
    )
    assert len(states) == 50, "the reference list itself is wrong"
    reachable = set(IDENTITY) | set(SPLIT.values())

    assert states - reachable == set()


@pytest.mark.parametrize("code", sorted(CANADIAN_PROVINCES | NON_US_BODIES))
def test_known_non_us_bodies_never_resolve(code):
    assert to_state_code(code) is None


@pytest.mark.parametrize("value", ["", "   ", None, "ZZ", "XX", "DC", "USA", "12"])
def test_unmapped_input_fails_closed(value):
    """``USA`` is the interesting one: a real code, from a real body, naming no
    state. It must stay unmapped however many payloads carry it, which is what
    separates "we have not seen this yet" from "this cannot answer the question"."""
    assert to_state_code(value) is None


def test_lookup_is_case_and_whitespace_insensitive():
    assert to_state_code(" can ") == "CA"
    assert to_state_code("oh") == "OH"


def test_identity_holds_only_real_two_letter_codes():
    assert all(re.fullmatch(r"[A-Z]{2}", code) for code in IDENTITY)


def _payload_reading_source(script):
    """Source of the functions that read the response body, and nothing else.

    Scoped rather than whole-file so a comment or docstring naming a key cannot
    satisfy the check. Not every copy spells the reader `resolve` -- assign_team_states
    goes through the hardened `_zenrows_get` probe -- so it is found by what it does.
    """
    tree = ast.parse(script.read_text(encoding="utf-8"))
    bodies = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "payload.get(" in ast.unparse(node)
    ]
    assert bodies, f"{script.name} reaches team_details but no function reads payload.get()"
    return "\n".join(bodies)


def test_every_script_reaching_team_details_is_accounted_for():
    """A new copy of the resolver has to be fixed or listed, never just added."""
    assert RESOLVER_SCRIPTS, "the glob matched nothing; the URL constant has moved"
    assert KNOWN_BROKEN <= {p.name for p in RESOLVER_SCRIPTS}


@pytest.mark.parametrize("script", RESOLVER_SCRIPTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("key", ABSENT_PAYLOAD_KEYS)
def test_resolvers_do_not_read_absent_payload_keys(script, key):
    """Scoped to resolve() because the behavioral tests miss one shape: an
    additive fallback such as `payload.get("name") or payload.get("full_name")`
    never fires against a payload whose real key is populated."""
    if script.name in KNOWN_BROKEN:
        pytest.skip(f"{script.name} still reads absent keys; tracked as IMP-142")
    assert f'payload.get({key!r})' not in _payload_reading_source(script)


@pytest.mark.parametrize("name", sorted(KNOWN_BROKEN))
def test_deferred_scripts_are_still_broken(name):
    """Keeps the deferral honest in both directions: fix one and this fails until
    it is taken off the list, so the guard above starts covering it."""
    script = PROJECT_ROOT / "scripts" / name
    source = _payload_reading_source(script)
    assert any(f'payload.get({key!r})' in source for key in ABSENT_PAYLOAD_KEYS), (
        f"{name} no longer reads absent keys -- remove it from KNOWN_BROKEN (IMP-142)"
    )


def test_discovery_does_not_persist_the_opponents_state():
    """unknown_state_used is the played-against team's state, not this team's."""
    source = DISCOVERY_SCRIPT.read_text(encoding="utf-8")
    assert 'row.get("unknown_state_used")' not in source
