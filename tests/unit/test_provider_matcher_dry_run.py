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
