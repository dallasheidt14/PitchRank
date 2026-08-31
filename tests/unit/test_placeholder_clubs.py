"""A club name that means "no club" must not be read as a club.

TGS writes "No Club Selection" rather than leaving the field empty, which makes it the
largest single ``club_name`` in this database -- 1,596 teams, more than any real club --
and puts 23 different states under one name. Every rule that reads a club then reads a
fiction, and the only thing stopping ``assign_team_states`` Tier B from stamping all of
them is that no single state is currently meaningful enough to win.

The list itself predates this module in five hand-copied ``NO_CLUB_VALUES`` sets, which
had already drifted apart. The last test here is what stops a sixth.
"""

import ast
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.assign_team_states as assign  # noqa: E402
from src.utils.placeholder_clubs import PLACEHOLDER_CLUB_NAMES, is_placeholder_club  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_the_provider_writes_it_in_several_cases():
    for spelling in ("No Club Selection", "NO CLUB SELECTION", "  no club selection  "):
        assert is_placeholder_club(spelling), spelling


def test_a_real_club_is_not_a_placeholder():
    for name in ("Eastside FC", "OSU", "Surf", "Ottawa South United"):
        assert not is_placeholder_club(name), name


def test_a_missing_club_is_a_placeholder():
    assert is_placeholder_club(None)
    assert is_placeholder_club("")


def test_the_provider_name_athlete_one_is_not_a_club():
    """AthleteOne's own name landing in club_name. Only 2 of its 23 teams carry a state,
    both FL -- exactly enough for Tier B's two-team floor to propose Florida for the
    other 21, which are not one club."""
    assert is_placeholder_club("Athlete One")


def test_a_placeholder_keys_to_no_club_at_all():
    assert assign.club_key("No Club Selection") == ""
    assert assign.club_key("Eastside FC") == "eastside fc"


def test_a_unanimous_placeholder_club_still_decides_nothing():
    """The guard that matters. Tier B abstains today only because the placeholder's 246
    stated teams span 23 states and none is meaningful enough to win -- a property of
    today's data, not a rule. Were they ever to agree, the tier would stamp 1,596
    unrelated teams; keying to "" is what makes the abstention structural."""
    unanimous = {"no club selection": Counter({"OH": 40})}
    team = {"team_id_master": "t", "team_name": "", "club_name": "No Club Selection",
            "state_code": None, "state": None}

    assert assign.club_derived_state(team, unanimous) is None
    assert assign.decide(team, unanimous, {}, {}, set()) is None


def test_the_same_club_shape_decides_when_it_is_a_real_club():
    """The contrast case, so the test above cannot pass by breaking Tier B outright."""
    real = {"eastside fc": Counter({"OH": 40})}
    team = {"team_id_master": "t", "team_name": "", "club_name": "Eastside FC",
            "state_code": None, "state": None}

    assert assign.club_derived_state(team, real) == "OH"


def test_a_placeholder_contributes_no_place_names():
    """`name_tokens` reads club_name too, so "selection" is currently being weighed as a
    possible place by 1,596 teams. NOT_A_PLACE holds "club" but not "selection"."""
    team = {"team_name": "", "club_name": "No Club Selection"}

    assert "selection" not in set(assign.name_tokens(team))


# --------------------------------------------------------------------------- #
# No sixth copy
# --------------------------------------------------------------------------- #

# Derived, not hand-written: every file naming the literal is found by glob, and a file
# that stops carrying its own copy must be removed from here or this turns red. These
# five predate the shared module and each reads it for its own purpose; converging them
# is a separate change with its own blast radius.
KNOWN_COPIES = {
    "scripts/match_state_from_club.py",
    "scripts/extract_missing_club_names.py",
    "scripts/backfill_missing_club_names.py",
    "scripts/backfill_unknown_team_names.py",
    "scripts/extract_and_import_tgs_teams.py",
}

SHARED_MODULE = "src/utils/placeholder_clubs.py"

# Derived, not enumerated. Naming today's two resolvers would leave a third one green,
# which is the drift this whole file exists to stop -- and the same rule CLAUDE.md states
# as "derive a guarded file list; never hand-write one".
RESOLVER_NAME = re.compile(r"(state.*from.*club|club.*(state|key))", re.I)


def _files_naming_the_literal():
    """Files holding the value as *data* — an element of a set, list or tuple literal.

    Deliberately not a text search: the string also appears in three module docstrings
    explaining the problem, and a guard that fires on prose would be silenced by whoever
    hit it next.
    """
    found = set()
    for path in list(PROJECT_ROOT.glob("scripts/*.py")) + list(PROJECT_ROOT.glob("src/**/*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel == SHARED_MODULE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                continue
            if any(
                isinstance(el, ast.Constant)
                and isinstance(el.value, str)
                and el.value.strip().lower() == "no club selection"
                for el in node.elts
            ):
                found.add(rel)
                break
    return found


def test_the_glob_finds_the_copies_it_is_meant_to():
    """A doc regex that silently matches nothing passes forever while proving nothing."""
    assert _files_naming_the_literal(), "the search for hand-copied lists found no file at all"


def test_no_new_hand_copied_list():
    new = _files_naming_the_literal() - KNOWN_COPIES
    assert not new, (
        f"these carry their own placeholder-club list; import "
        f"src.utils.placeholder_clubs instead: {sorted(new)}"
    )


def test_known_copies_that_were_converged_are_dropped_from_the_list():
    stale = KNOWN_COPIES - _files_naming_the_literal()
    assert not stale, f"no longer carries its own list, drop it from KNOWN_COPIES: {sorted(stale)}"


def _club_state_resolvers():
    """Files defining a function that turns a club into a state, or keys clubs for one."""
    found = {}
    for path in list(PROJECT_ROOT.glob("scripts/*.py")) + list(PROJECT_ROOT.glob("src/**/*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel == SHARED_MODULE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        names = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and RESOLVER_NAME.search(n.name)
        ]
        if names:
            found[rel] = names
    return found


def test_the_resolver_search_finds_the_ones_it_is_meant_to():
    """A detector that silently matches nothing passes forever while proving nothing."""
    found = _club_state_resolvers()
    assert "scripts/assign_team_states.py" in found, found
    assert "src/models/game_matcher.py" in found, found


def test_every_club_to_state_resolver_reads_the_shared_set():
    """Either it imports the one list, or it is a copy that predates it and is named above.

    Anything else is a new resolver deciding for itself what "no club" means, which is
    how five copies drifted apart in the first place.
    """
    offenders = {}
    for rel, names in _club_state_resolvers().items():
        if rel in KNOWN_COPIES:
            continue
        tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
        imported = {
            n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
        }
        if "src.utils.placeholder_clubs" not in imported:
            offenders[rel] = names
    assert not offenders, (
        f"these decide a state from a club without reading the shared placeholder set; "
        f"import src.utils.placeholder_clubs: {offenders}"
    )


def test_the_shared_set_covers_every_value_the_copies_carry():
    """The module is the union of what the five already refuse, so adopting it can only
    widen a caller's notion of "no club", never narrow it."""
    for rel in sorted(KNOWN_COPIES):
        tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if "NO_CLUB_VALUES" not in targets:
                continue
            values = {
                lit.value
                for lit in ast.walk(node.value)
                if isinstance(lit, ast.Constant) and isinstance(lit.value, str)
            }
            assert values <= PLACEHOLDER_CLUB_NAMES, (
                f"{rel} refuses values the shared set does not: "
                f"{sorted(values - PLACEHOLDER_CLUB_NAMES)}"
            )
