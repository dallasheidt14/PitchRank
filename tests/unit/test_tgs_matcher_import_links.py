"""The TGS game import finds a team by its TGS id alone; it never links by name or creates a team.

extract_and_import_tgs_teams.py decides every new id before the import, where it sees every
shard's teams and the age each name states, and refuses a team that already carries a TGS id.
"""

from src.models.tgs_matcher import TGSGameMatcher
from tests.unit.test_extract_and_import_tgs_teams import CLUB, NAME, OPPONENT_ID, TGS, _db, _run, _team
from tests.unit.test_extract_and_import_tgs_teams import _game as _csv_game


def _game(team_id):
    return {
        "provider": "tgs",
        "team_id": team_id,
        "team_name": NAME,
        "club_name": CLUB,
        "opponent_id": OPPONENT_ID,
        "opponent_name": "Seattle United B16/17 Red",
        "opponent_club_name": "Seattle United",
        "age_group": "u10",
        "gender": "Male",
        "home_away": "H",
        "goals_for": 2,
        "goals_against": 1,
        "game_date": "2026-09-12",
    }


def _import(db, team_id):
    return TGSGameMatcher(db, provider_id=TGS).match_game_history(_game(team_id))


def _writes(db):
    return [payload for _, op, payload in db.executed if op != "select"]


def test_a_team_is_found_by_its_tgs_id():
    db = _db()

    record = _import(db, OPPONENT_ID)

    assert record["home_team_master_id"] == "opponent"
    assert _writes(db) == []
    assert db.unmodeled == []


def test_a_name_link_the_match_step_wrote_is_found_at_import(monkeypatch, tmp_path):
    db = _db(teams=[_team("gotsport-row")])
    assert _run(monkeypatch, tmp_path, db, [_csv_game("501")]) == 0
    assert db.alias_of("501")["match_method"] == "fuzzy_auto"
    written = len(db.executed)

    record = _import(db, "501")

    assert record["home_team_master_id"] == "gotsport-row"
    assert [payload for _, op, payload in db.executed[written:] if op != "select"] == []
    assert db.unmodeled == []


def test_an_unseen_id_is_neither_linked_nor_created_even_when_a_name_matches_exactly():
    db = _db(teams=[_team("gotsport-row", NAME)])

    record = _import(db, "501")

    assert record["home_team_master_id"] is None
    assert record["away_team_master_id"] == "opponent"
    assert _writes(db) == []
    assert db.unmodeled == []


def test_a_placeholder_id_stays_unmatched_instead_of_becoming_a_team():
    for team_id in ("", "None"):
        db = _db()

        record = _import(db, team_id)

        assert record["home_team_master_id"] is None
        assert record["away_team_master_id"] == "opponent"
        assert _writes(db) == []
        assert db.unmodeled == []
