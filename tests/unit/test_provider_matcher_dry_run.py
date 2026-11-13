"""Every provider matcher must honour the pipeline's dry_run flag.

A TGS dry run once created 118 teams and 117 review-queue rows while printing
"no changes were made". Two faults produced that, and both recur per provider:
the pipeline may forget to pass dry_run (leaving the base class's own gates
inert), and a subclass may leave its autocreate insert ungated.

TGS's own team-insert gate is tested in test_tgs_matcher_dry_run.py.
"""

import inspect
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.etl import enhanced_pipeline
from src.models.affinity_ga_matcher import AffinityGAGameMatcher
from src.models.affinity_hi_matcher import AffinityHIGameMatcher
from src.models.affinity_or_matcher import AffinityORGameMatcher
from src.models.affinity_ut_matcher import AffinityUTGameMatcher
from src.models.affinity_wa_matcher import AffinityWAGameMatcher
from src.models.athletes2events_matcher import Athletes2EventsGameMatcher
from src.models.demosphere_matcher import DemosphereGameMatcher
from src.models.htgsports_matcher import HtgSportsGameMatcher
from src.models.modular11_ea_matcher import Modular11EaGameMatcher
from src.models.modular11_matcher import Modular11GameMatcher
from src.models.playmetrics_matcher import PlayMetricsGameMatcher
from src.models.sincsports_matcher import SincSportsGameMatcher
from src.models.soccereventsgroup_matcher import SoccerEventsGroupGameMatcher
from src.models.tgs_matcher import TGSGameMatcher
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher
from src.models.yssl_matcher import YSSLGameMatcher

ROOT = Path(__file__).resolve().parents[2]

AUTOCREATING_MATCHERS = [
    ("tgs", TGSGameMatcher),
    ("sincsports", SincSportsGameMatcher),
    ("affinity_wa", AffinityWAGameMatcher),
    ("affinity_or", AffinityORGameMatcher),
    ("affinity_ut", AffinityUTGameMatcher),
    ("affinity_hi", AffinityHIGameMatcher),
    ("affinity_ga", AffinityGAGameMatcher),
    ("playmetrics", PlayMetricsGameMatcher),
    ("playmetrics_tournament", PlayMetricsGameMatcher),
    ("modular11", Modular11GameMatcher),
    ("modular11_ea", Modular11EaGameMatcher),
    ("soccereventsgroup", SoccerEventsGroupGameMatcher),
    ("athletes2events", Athletes2EventsGameMatcher),
    ("yssl", YSSLGameMatcher),
    ("tourneycentral", TourneyCentralGameMatcher),
    ("demosphere", DemosphereGameMatcher),
    ("htgsports", HtgSportsGameMatcher),
]

# The pipeline branches not listed above, each pinned in its provider's own test file.
PINNED_ELSEWHERE = {"mlsnext_kitman": "tests/unit/test_mlsnext_kitman_matcher.py"}
# Constructor arguments the pipeline passes that change what a matcher matches or creates,
# so each case builds the matcher the import builds: the tournament import's is unscoped.
PIPELINE_KWARGS = {"playmetrics_tournament": {"default_state_code": None}}


def _pipeline_source():
    return inspect.getsource(enhanced_pipeline.EnhancedETLPipeline._ensure_initialized)


def _branch(provider):
    """The provider's branch of the matcher chain, ending at the next branch or the fallback."""
    return re.split(r"\belif\b|\belse:", _pipeline_source().split(f'== "{provider}"')[1])[0]


def _db_with_no_existing_team():
    db = MagicMock()
    lookup = db.table.return_value.select.return_value.eq.return_value.eq.return_value
    lookup.single.return_value.execute.return_value.data = None
    return db


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_every_matcher_accepts_and_stores_dry_run(provider, cls):
    matcher = cls(_db_with_no_existing_team(), provider_id=provider, dry_run=True, **PIPELINE_KWARGS.get(provider, {}))

    assert matcher.dry_run is True


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_dry_run_defaults_off(provider, cls):
    matcher = cls(_db_with_no_existing_team(), provider_id=provider, **PIPELINE_KWARGS.get(provider, {}))

    assert matcher.dry_run is False


@pytest.mark.parametrize("provider", [p for p, _ in AUTOCREATING_MATCHERS])
def test_pipeline_passes_dry_run_to_every_autocreating_matcher(provider):
    """The gap that silently made each base-class gate inert."""
    assert "dry_run=self.dry_run" in _branch(provider), f"{provider} matcher is constructed without dry_run"


def test_every_pipeline_branch_is_listed_here_or_pinned_elsewhere():
    """A provider code missing from AUTOCREATING_MATCHERS has its dry_run wiring checked nowhere."""
    branches = set(re.findall(r'provider_code\.lower\(\) == "(\w+)"', _pipeline_source()))

    assert branches == {p for p, _ in AUTOCREATING_MATCHERS} | set(PINNED_ELSEWHERE)
    for provider, test_file in PINNED_ELSEWHERE.items():
        pin = (ROOT / test_file).read_text(encoding="utf-8")
        assert f'"{provider}"' in pin and "dry_run=self.dry_run" in pin, f"{test_file} no longer pins {provider}"


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_pipeline_builds_each_providers_own_matcher(provider, cls):
    """A copied branch that kept its sibling's class would file one league's teams under another's state."""
    assert f"self.matcher = {cls.__name__}(" in _branch(provider)


@pytest.mark.parametrize(
    ("provider", "cls", "create"),
    [
        ("sincsports", SincSportsGameMatcher, "_create_new_sincsports_team"),
        ("affinity_wa", AffinityWAGameMatcher, "_create_new_affinity_wa_team"),
        ("affinity_or", AffinityORGameMatcher, "_create_new_affinity_or_team"),
        ("affinity_ut", AffinityUTGameMatcher, "_create_new_affinity_or_team"),
        ("affinity_hi", AffinityHIGameMatcher, "_create_new_affinity_or_team"),
        ("affinity_ga", AffinityGAGameMatcher, "_create_new_affinity_or_team"),
        ("soccereventsgroup", SoccerEventsGroupGameMatcher, "_create_new_soccereventsgroup_team"),
        ("athletes2events", Athletes2EventsGameMatcher, "_create_new_athletes2events_team"),
        ("yssl", YSSLGameMatcher, "_create_new_athletes2events_team"),
        ("tourneycentral", TourneyCentralGameMatcher, "_create_new_athletes2events_team"),
        ("demosphere", DemosphereGameMatcher, "_create_new_athletes2events_team"),
        ("htgsports", HtgSportsGameMatcher, "_create_new_athletes2events_team"),
    ],
)
def test_autocreate_writes_nothing_in_dry_run(provider, cls, create):
    db = _db_with_no_existing_team()
    matcher = cls(db, provider_id=provider, dry_run=True)
    fn = getattr(matcher, create)

    fn(
        team_name="Oregon Surf GU13 ECNL",
        club_name="Oregon Surf",
        age_group="u14",
        gender="Female",
        provider_id=provider,
        provider_team_id="129826",
    )

    db.table.return_value.insert.assert_not_called()


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Resolves every read to "nothing found" and records every insert."""

    def __init__(self, table, sink):
        self.table, self.sink, self._single = table, sink, False

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def single(self):
        self._single = True
        return self

    def insert(self, data):
        self.sink.append((self.table, data))
        return self

    def execute(self):
        return _Result(None if self._single else [])


class _EmptyDB:
    def __init__(self):
        self.inserts = []

    def table(self, name):
        return _Query(name, self.inserts)


# The roster-pass providers create a team only from that pass,
# and only for a team carrying a state. Without both, _match_team returns before any
# creation and every identity assertion below holds vacuously on None.
REGISTRATION_MATCHERS = frozenset(
    {"soccereventsgroup", "athletes2events", "yssl", "tourneycentral", "demosphere", "htgsports"}
)
# These matchers' _match_team never creates a team (EA teams come only from
# link_modular11_ea_teams.py), so every id below would be None for them.
NEVER_CREATE_ON_MATCH = frozenset({"tgs", "modular11_ea"})
CREATING_ON_MATCH = [(p, cls) for p, cls in AUTOCREATING_MATCHERS if p not in NEVER_CREATE_ON_MATCH]


def _match_thrice(cls, provider, db):
    registering = provider in REGISTRATION_MATCHERS
    kwargs = {**PIPELINE_KWARGS.get(provider, {}), **({"registration_mode": True} if registering else {})}
    matcher = cls(db, provider_id=provider, dry_run=True, **kwargs)
    extra = {"state_code": "WA"} if registering else {}
    return [
        (
            matcher._match_team(provider, "999001", "Some Unseen Team", "u14", "Female", "Some Club", **extra) or {}
        ).get("team_id")
        for _ in range(3)
    ]


@pytest.mark.parametrize(("provider", "cls"), CREATING_ON_MATCH)
def test_one_unseen_team_keeps_one_id_across_a_dry_run(provider, cls):
    """Without this the same team fragments into a fresh uuid per game.

    The alias cache is only populated when already non-empty, and a cached hit
    is re-validated against a `teams` row a dry run never wrote, so the alias is
    rejected and the team is created again. The simulated game_uids then stop
    matching what a real import would produce.
    """
    ids = _match_thrice(cls, provider, _EmptyDB())

    assert ids[0] is not None, f"{provider} created no team, so it belongs in NEVER_CREATE_ON_MATCH"
    assert len(set(ids)) == 1, f"{provider} produced {len(set(ids))} ids for one team"


@pytest.mark.parametrize(("provider", "cls"), CREATING_ON_MATCH)
def test_dry_run_ids_are_reproducible_across_runs(provider, cls):
    first = _match_thrice(cls, provider, _EmptyDB())[0]
    second = _match_thrice(cls, provider, _EmptyDB())[0]

    assert first == second


@pytest.mark.parametrize(("provider", "cls"), CREATING_ON_MATCH)
def test_matching_writes_nothing_at_all_in_dry_run(provider, cls):
    db = _EmptyDB()

    _match_thrice(cls, provider, db)

    assert db.inserts == []


def test_real_imports_still_get_a_random_id():
    """The deterministic id is a dry-run device, not the production identity."""
    matcher = TGSGameMatcher(_EmptyDB(), provider_id="tgs", dry_run=False)
    args = ("tgs", "999001", "Some Unseen Team", "u14", "Female")

    assert matcher._new_team_id_master(*args) != matcher._new_team_id_master(*args)
