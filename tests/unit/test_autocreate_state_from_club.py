"""A provider with no state field asks the club, and takes NULL for an answer.

TGS carries no per-team state and its matcher wrote none, so it created 763 stateless
teams in a single day and 3,697 of the database's 3,845 blanks were TGS. The club is the
only thing such a provider can be asked.

What it must NOT do is guess. A wrong state written at creation is the value every later
heuristic then agrees with: a club whose teams are uniformly mislabelled is invisible to
the assignment tool, because the tool reads the club. That shape cost four separate
hand-fixes -- Boise Timbers, Hawaii Rush, Legends FC Arizona, and 162 TCSL teams -- none
of which any tier could reach.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.game_matcher import GameHistoryMatcher
from src.models.playmetrics_matcher import PlayMetricsGameMatcher
from src.models.tgs_matcher import TGSGameMatcher


def _matcher(stated=None, dissenting=False):
    """A TGS matcher whose club holds `stated` and, when `dissenting`, a team elsewhere.

    The resolver asks two questions rather than fetching the club: one stated team, then
    "is there one that disagrees". `dissenting` answers the second. Both hang off the
    `.neq("state_code", "")` hop, because a stateless team is stored two ways.
    """
    db = MagicMock()
    select = db.table.return_value.select.return_value
    select.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = None
    stated_query = _stated_query(db)
    stated_query.limit.return_value.execute.return_value.data = [stated] if stated else []
    dissent = [{"state_code": "XX"}] if dissenting else []
    stated_query.neq.return_value.limit.return_value.execute.return_value.data = dissent
    return TGSGameMatcher(db, provider_id="tgs"), db


def _stated_query(db):
    """The club query with both spellings of "no state" already filtered out."""
    return db.table.return_value.select.return_value.eq.return_value.not_.is_.return_value.neq.return_value


def _inserted(db):
    for call in db.table.return_value.insert.call_args_list:
        if call.args and isinstance(call.args[0], dict) and "team_id_master" in call.args[0]:
            return call.args[0]
    return {}


def test_a_club_that_agrees_gives_the_new_team_its_state():
    matcher, db = _matcher(stated={"state_code": "OR", "state": "Oregon"})

    matcher._create_new_tgs_team(
        team_name="Oregon Surf GU13 ECNL",
        club_name="Oregon Surf",
        age_group="u14",
        gender="Female",
        provider_id="tgs",
        provider_team_id="99001",
    )

    row = _inserted(db)
    assert row.get("state_code") == "OR"
    # Never the full-name column: four writers set that, and assign_team_states reads a
    # filled one as "a provider reported this", which would stop it correcting a value
    # that was only ever inferred from the club.
    assert "state" not in row


def test_a_club_spanning_states_leaves_the_state_null():
    """The blank is the point. A guess here is what the assignment tool then reads as
    corroboration, and a club that agrees with itself is the one shape it cannot fix."""
    matcher, db = _matcher(stated={"state_code": "MA", "state": "Massachusetts"}, dissenting=True)

    matcher._create_new_tgs_team(
        team_name="FC Stars 2014 Blue",
        club_name="FC Stars",
        age_group="u13",
        gender="Female",
        provider_id="tgs",
        provider_team_id="99002",
    )

    row = _inserted(db)
    assert "state_code" not in row
    assert "state" not in row


def test_an_unknown_club_leaves_the_state_null():
    matcher, db = _matcher()

    matcher._create_new_tgs_team(
        team_name="Brand New Club 2015",
        club_name="Brand New Club",
        age_group="u12",
        gender="Male",
        provider_id="tgs",
        provider_team_id="99003",
    )

    assert "state_code" not in _inserted(db)


def test_a_placeholder_club_never_queries():
    """TGS writes "No Club Selection" rather than leaving the field blank, so it arrives
    looking like a club. It is the largest club_name in the database -- 1,596 teams
    across 23 states -- and the unanimity question can only ever answer no, at two
    queries per created team."""
    matcher, db = _matcher(stated={"state_code": "OR", "state": "Oregon"})

    assert matcher._resolve_state_from_club("No Club Selection") == (None, None)
    assert matcher._resolve_state_from_club("NO CLUB SELECTION") == (None, None)
    assert not db.table.return_value.select.called


def test_a_team_with_no_club_never_queries():
    matcher, _ = _matcher()

    assert matcher._resolve_state_from_club(None) == (None, None)
    assert matcher._resolve_state_from_club("") == (None, None)


def test_the_club_is_asked_once_per_batch():
    """Autocreate runs per team; a club with forty new teams must not run forty lookups."""
    matcher, db = _matcher(stated={"state_code": "OR", "state": "Oregon"})

    matcher._resolve_state_from_club("Oregon Surf")
    matcher._resolve_state_from_club("Oregon Surf")

    assert matcher._club_state_cache["Oregon Surf"] == ("OR", "Oregon")


def test_one_implementation_of_the_rule():
    """It lives on the base class. Two copies of a state-deciding rule is how a provider
    ends up disagreeing with itself about what a club's state is."""
    canonical = GameHistoryMatcher._resolve_state_from_club
    assert PlayMetricsGameMatcher._resolve_state_from_club is canonical
    assert TGSGameMatcher._resolve_state_from_club is canonical


def test_unanimity_is_asked_for_rather_than_paged():
    """The club with the most stated teams here has 532. Any fixed page would call a
    multi-state club unanimous whenever its minority fell outside the rows returned, and
    unordered pagination gives no say in which those are."""
    matcher, db = _matcher(stated={"state_code": "OR", "state": "Oregon"})

    matcher._resolve_state_from_club("Oregon Surf")

    stated_query = _stated_query(db)
    assert stated_query.neq.called, "the club is fetched and deduped instead of asked for a dissenter"
    assert stated_query.neq.call_args.args == ("state_code", "OR")


def test_a_club_mate_with_no_state_neither_seeds_nor_dissents():
    """No state is stored two ways. `teams` holds 3,080 NULL and 0 empty today, but the
    CSV importer still writes "" and match_state_from_club.py pages for both, so one
    legacy row would otherwise seed the club with an empty code -- or count as the
    dissenter that silences a club every real row agrees on."""
    matcher, db = _matcher(stated={"state_code": "OR", "state": "Oregon"})

    matcher._resolve_state_from_club("Oregon Surf")

    excluded = db.table.return_value.select.return_value.eq.return_value.not_.is_.return_value
    assert excluded.neq.call_args.args == ("state_code", "")
