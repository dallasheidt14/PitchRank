"""The birth-year guard is actually reachable, for every provider.

This repo has already shipped a guard that never fired: a placeholder check that
read `provider_team_id`, a column the fetch query does not select. A guard that
looks right and is inert is worse than no guard, because it is counted as
protection. So this file tests reachability and wiring, not semantics --
tests/unit/test_birth_years_guard.py covers what the guard decides.

Five provider matchers OVERRIDE `_fuzzy_match_team`, which is why the guard sits
at `_match_team`'s accept path: every subclass reaches it through
`super()._match_team(...)`. The guard reads `fuzzy_match["team_name"]`, so a
subclass that stops returning that key would fail the guard OPEN and silently.
"""

import importlib
import inspect

import pytest


def test_team_name_utils_import_is_available():
    """game_matcher's import of the guard must not be taking its fallback.

    game_matcher.py wraps the team_name_utils import in try/except ImportError and
    binds a fallback that returns False -- failing open. That fallback exists so a
    missing module cannot raise inside the 15-minute import path, but it must never
    be what actually runs here.
    """
    gm = importlib.import_module("src.models.game_matcher")
    assert gm.HAVE_TEAM_NAME_UTILS is True, "game_matcher fell back to the INERT birth-year guard"

    from src.utils.team_name_utils import birth_years_conflict

    assert gm.birth_years_conflict is birth_years_conflict


def test_guard_is_wired_into_the_accept_path():
    """The accept path must consult the guard before it auto-aliases."""
    from src.models.game_matcher import GameHistoryMatcher

    source = inspect.getsource(GameHistoryMatcher._match_team)
    assert "birth_years_conflict" in source, "accept path does not call the guard"
    assert "and not year_conflict" in source, "auto-approve is not conditioned on the guard"
    assert "or year_conflict" in source, "a conflicting match is not demoted to review"


def test_guard_is_wired_into_the_candidate_loop():
    """A wrong-year candidate must be skipped, not allowed to win the search."""
    from src.models.game_matcher import GameHistoryMatcher

    source = inspect.getsource(GameHistoryMatcher._fuzzy_match_team)
    assert "birth_years_conflict" in source, "candidate loop does not call the guard"


_SUBCLASS_PATHS = [
    ("src.models.affinity_wa_matcher", "AffinityWAGameMatcher"),
    ("src.models.playmetrics_matcher", "PlayMetricsGameMatcher"),
    ("src.models.tgs_matcher", "TGSGameMatcher"),
    ("src.models.sincsports_matcher", "SincSportsGameMatcher"),
    ("src.models.modular11_matcher", "Modular11GameMatcher"),
]


@pytest.mark.parametrize("module_path,class_name", _SUBCLASS_PATHS)
def test_subclass_fuzzy_match_returns_team_name(module_path, class_name):
    """Every overriding matcher must still return the key the guard reads.

    The guard uses `fuzzy_match.get("team_name")`. A subclass that drops that key
    makes birth_years_conflict compare against None, which returns False -- the
    guard passes and the bad alias is written, with nothing in the logs.
    """
    module = pytest.importorskip(module_path)
    cls = getattr(module, class_name, None)
    if cls is None or "_fuzzy_match_team" not in cls.__dict__:
        pytest.skip(f"{class_name} does not override _fuzzy_match_team")

    source = inspect.getsource(cls.__dict__["_fuzzy_match_team"])
    assert '"team_name"' in source or "'team_name'" in source, (
        f"{class_name}._fuzzy_match_team does not appear to return 'team_name'; "
        "the birth-year guard would silently fail open for this provider"
    )


@pytest.mark.parametrize("module_path,class_name", _SUBCLASS_PATHS)
def test_subclass_reaches_the_guarded_accept_path(module_path, class_name):
    """Subclass _match_team overrides must delegate to the guarded base."""
    module = pytest.importorskip(module_path)
    cls = getattr(module, class_name, None)
    if cls is None or "_match_team" not in cls.__dict__:
        pytest.skip(f"{class_name} does not override _match_team")

    source = inspect.getsource(cls.__dict__["_match_team"])
    if "super()." in source and "_match_team" in source:
        return

    # Modular11 fully replaces _match_team and creates its own fuzzy_auto alias, so
    # it never reaches the base guard. A matcher in that position must carry its
    # own -- either in the override or in the fuzzy helper it accepts from. This
    # branch is what caught modular11 in the first place; keep it failing loudly
    # rather than skipping, so the next such override is caught too.
    module_source = inspect.getsource(module)
    assert "birth_years_conflict" in module_source, (
        f"{class_name}._match_team does not call super()._match_team AND its module "
        "never calls birth_years_conflict; it writes aliases with no birth-year guard"
    )


def test_the_eight_known_affinity_defects_are_refused():
    """The aliases that actually misfiled games must now be refused.

    These 8 affinity_wa aliases carry all 75 known misfiled games. Each pairs a
    provider name against a master a year or more apart -- the shape no age-token
    comparison can catch, because U19 holds two birth years at once.
    """
    from src.utils.team_name_utils import birth_years_conflict

    defects = [
        ("XF B13 RCL 1", "XF 2014 RCL 1"),
        ("Eastside FC B09 Red", "Eastside FC 2008 Red"),
        ("Seattle United B09 Copa A", "Seattle United 2008 Copa A"),
        ("Whatcom FC Rangers G09 Gold", "Whatcom FC Rangers 2008 Gold"),
        ("Eastside FC G09 White", "Eastside FC 2008 White"),
        ("XF B17 RCL 1", "XF 2016 RCL 1"),
        ("XF G11 ECNL RL", "XF 2012 ECNL RL"),
        ("Seattle United G09 Copa A", "Seattle United 2008 Copa A"),
    ]
    unrefused = [(a, b) for a, b in defects if not birth_years_conflict(a, b)]
    assert not unrefused, f"guard fails to refuse known-defective pairs: {unrefused}"
