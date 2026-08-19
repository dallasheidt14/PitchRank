"""A TGS dry run must not write.

Importing event 4125 with --dry-run reported "Teams created: 0" and "no changes
were made" while creating 118 teams and 117 review-queue rows. Two faults
combined: the pipeline never passed dry_run to TGSGameMatcher, so the base
class's gates on _create_alias and the review queue saw dry_run=False, and the
matcher's own team insert had no gate at all.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.tgs_matcher import TGSGameMatcher


def _matcher(dry_run):
    """A matcher whose "does this team already exist" lookup finds nothing.

    Left as a bare MagicMock that lookup returns a truthy row, and the method
    early-returns the existing id without ever reaching the insert.
    """
    db = MagicMock()
    lookup = db.table.return_value.select.return_value.eq.return_value.eq.return_value
    lookup.single.return_value.execute.return_value.data = None
    matcher = TGSGameMatcher(db, provider_id="tgs", dry_run=dry_run)
    return matcher, db


def _written_tables(db):
    return [call.args[0] for call in db.table.call_args_list if call.args]


def test_dry_run_reaches_the_matcher_at_all():
    matcher, _ = _matcher(dry_run=True)

    assert matcher.dry_run is True


def test_dry_run_defaults_off_so_real_imports_are_unaffected():
    matcher, _ = _matcher(dry_run=False)

    assert matcher.dry_run is False


def test_creating_a_team_writes_nothing_in_dry_run():
    matcher, db = _matcher(dry_run=True)

    team_id = matcher._create_new_tgs_team(
        team_name="Oregon Surf GU13 ECNL",
        club_name="Oregon Surf",
        age_group="u14",
        gender="Female",
        provider_id="tgs",
        provider_team_id="129826",
    )

    assert team_id, "a dry run still needs an id so downstream matching can proceed"
    assert not any(call.args and call.args[0] == "teams" and "insert" in str(call) for call in db.table.mock_calls), (
        f"dry run wrote to teams: {_written_tables(db)}"
    )
    db.table.return_value.insert.assert_not_called()


def test_creating_a_team_does_write_when_not_a_dry_run():
    matcher, db = _matcher(dry_run=False)

    matcher._create_new_tgs_team(
        team_name="Oregon Surf GU13 ECNL",
        club_name="Oregon Surf",
        age_group="u14",
        gender="Female",
        provider_id="tgs",
        provider_team_id="129826",
    )

    db.table.return_value.insert.assert_called()


def test_pipeline_hands_its_dry_run_flag_to_the_tgs_matcher():
    """The gap that made the base class's own gates inert."""
    import inspect

    from src.etl import enhanced_pipeline

    source = inspect.getsource(enhanced_pipeline.EnhancedETLPipeline._ensure_initialized)
    tgs_block = source.split('== "tgs"')[1].split("elif")[0]

    assert "dry_run=self.dry_run" in tgs_block, "TGSGameMatcher must receive the pipeline's dry_run flag"
