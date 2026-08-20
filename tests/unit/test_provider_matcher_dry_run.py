"""Every provider matcher must honour the pipeline's dry_run flag.

A TGS dry run once created 118 teams and 117 review-queue rows while printing
"no changes were made". Two faults produced that, and both recur per provider:
the pipeline may forget to pass dry_run (leaving the base class's own gates
inert), and a subclass may leave its autocreate insert ungated.

TGS is covered separately in test_tgs_matcher_dry_run.py.
"""

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.etl import enhanced_pipeline
from src.models.affinity_wa_matcher import AffinityWAGameMatcher
from src.models.modular11_matcher import Modular11GameMatcher
from src.models.playmetrics_matcher import PlayMetricsGameMatcher
from src.models.sincsports_matcher import SincSportsGameMatcher
from src.models.tgs_matcher import TGSGameMatcher

AUTOCREATING_MATCHERS = [
    ("tgs", TGSGameMatcher),
    ("sincsports", SincSportsGameMatcher),
    ("affinity_wa", AffinityWAGameMatcher),
    ("playmetrics", PlayMetricsGameMatcher),
    ("modular11", Modular11GameMatcher),
]


def _db_with_no_existing_team():
    db = MagicMock()
    lookup = db.table.return_value.select.return_value.eq.return_value.eq.return_value
    lookup.single.return_value.execute.return_value.data = None
    return db


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_every_matcher_accepts_and_stores_dry_run(provider, cls):
    matcher = cls(_db_with_no_existing_team(), provider_id=provider, dry_run=True)

    assert matcher.dry_run is True


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_dry_run_defaults_off(provider, cls):
    matcher = cls(_db_with_no_existing_team(), provider_id=provider)

    assert matcher.dry_run is False


@pytest.mark.parametrize("provider", [p for p, _ in AUTOCREATING_MATCHERS])
def test_pipeline_passes_dry_run_to_every_autocreating_matcher(provider):
    """The gap that silently made each base-class gate inert."""
    source = inspect.getsource(enhanced_pipeline.EnhancedETLPipeline._ensure_initialized)
    block = source.split(f'== "{provider}"')[1].split("elif")[0]

    assert "dry_run=self.dry_run" in block, f"{provider} matcher is constructed without dry_run"


@pytest.mark.parametrize(
    ("provider", "cls", "create"),
    [
        ("sincsports", SincSportsGameMatcher, "_create_new_sincsports_team"),
        ("affinity_wa", AffinityWAGameMatcher, "_create_new_affinity_wa_team"),
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


def _match_thrice(cls, provider, db):
    matcher = cls(db, provider_id=provider, dry_run=True)
    return [
        (matcher._match_team(provider, "999001", "Some Unseen Team", "u14", "Female", "Some Club") or {}).get("team_id")
        for _ in range(3)
    ]


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_one_unseen_team_keeps_one_id_across_a_dry_run(provider, cls):
    """Without this the same team fragments into a fresh uuid per game.

    The alias cache is only populated when already non-empty, and a cached hit
    is re-validated against a `teams` row a dry run never wrote, so the alias is
    rejected and the team is created again. The simulated game_uids then stop
    matching what a real import would produce.
    """
    ids = _match_thrice(cls, provider, _EmptyDB())

    assert len(set(ids)) == 1, f"{provider} produced {len(set(ids))} ids for one team"


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_dry_run_ids_are_reproducible_across_runs(provider, cls):
    first = _match_thrice(cls, provider, _EmptyDB())[0]
    second = _match_thrice(cls, provider, _EmptyDB())[0]

    assert first == second


@pytest.mark.parametrize(("provider", "cls"), AUTOCREATING_MATCHERS)
def test_matching_writes_nothing_at_all_in_dry_run(provider, cls):
    db = _EmptyDB()

    _match_thrice(cls, provider, db)

    assert db.inserts == []


def test_real_imports_still_get_a_random_id():
    """The deterministic id is a dry-run device, not the production identity."""
    matcher = TGSGameMatcher(_EmptyDB(), provider_id="tgs", dry_run=False)
    args = ("tgs", "999001", "Some Unseen Team", "u14", "Female")

    assert matcher._new_team_id_master(*args) != matcher._new_team_id_master(*args)
