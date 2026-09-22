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

import pytest

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


@pytest.mark.parametrize(
    "spelling",
    ["U.S. Futsal", "U.S. Futsal Club", "Tournament Team", "Tournament Team - PA", "AYSO", "AYSO Alliance", "Real"],
)
def test_a_competition_or_programme_label_is_not_a_club(spelling):
    """Added 2026-09-22. Each pools teams from many different clubs, the shape this
    module exists for: "U.S. Futsal" alone spans Sole Sisters, Galacticos and NLA
    Select, and "Tournament Team" holds 42 different Pennsylvania clubs."""
    assert is_placeholder_club(spelling), spelling


@pytest.mark.parametrize(
    "name",
    [
        # Every named AYSO body is a real club or region, and there are eighty-odd of
        # them. Only the bare word and the bare "Alliance" pool unrelated teams.
        "AYSO United",
        "AYSO United Bay Area",
        "AYSO S1 Alliance",
        "AYSO Region 214",
        "AYSO Alliance Knoxville",
        "AYSO Alliance Indio",
        "AYSO Extra",
        # "Real" is a club-name prefix across five states; only the bare word qualifies.
        "Real Colorado",
        "Real FC",
        "Real Salt Lake",
        "Real Futbol Academy",
        # A tournament team belonging to a named club is that club's team.
        "Tournament Team - Forza",
    ],
)
def test_a_named_body_sharing_a_placeholder_prefix_is_still_a_club(name):
    """The whole-string match is what keeps the four additions above narrow. A prefix
    or substring test would swallow every one of these."""
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
# that stops carrying its own copy must be removed from here or this turns red.
#
# It is empty now. The five that predated the shared module were converged on
# 2026-09-22, after four values were added to the shared set and the copies kept the
# old one -- which is worse than drift, because a writer that still accepts "AYSO"
# writes it into a NULL club, every shared-set reader then treats that non-empty value
# as absent, and the backfills only ever re-select NULL rows, so the team is stuck.
KNOWN_COPIES: set[str] = set()

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


def test_the_search_for_a_hand_copied_list_actually_fires(tmp_path, monkeypatch):
    """A detector that silently matches nothing passes forever while proving nothing.

    It used to be proven by the copies themselves, which is no longer possible now that
    none remain -- and a guard that needs the defect present to prove itself is the
    wrong shape anyway. Proven against a planted file instead.
    """
    planted = tmp_path / "scripts" / "planted_copy.py"
    planted.parent.mkdir(parents=True)
    planted.write_text('NO_CLUB_VALUES = {"no club selection", "none"}\n', encoding="utf-8")
    (tmp_path / "scripts" / "innocent.py").write_text(
        '"""A docstring naming no club selection is prose, not data."""\nX = 1\n', encoding="utf-8"
    )

    monkeypatch.setattr(sys.modules[__name__], "PROJECT_ROOT", tmp_path)
    found = _files_naming_the_literal()

    assert found == {"scripts/planted_copy.py"}, found


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
