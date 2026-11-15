"""Unit tests for the Heartland Soccer matcher.

It is the Tourney Central matcher searching Kansas, Missouri and stateless teams in the roster
pass, so it reuses the Athletes2Events database double.
"""

import pytest

from src.models.heartland_matcher import REGION_SEARCH, HeartlandGameMatcher
from tests.unit.test_athletes2events_matcher import _DB, PROVIDER, _candidate

NAME = "FC Vardar U12 B Red"
CLUB = "FC Vardar"


def _matcher(db, registration_mode=True, dry_run=False):
    return HeartlandGameMatcher(db, provider_id=PROVIDER, registration_mode=registration_mode, dry_run=dry_run)


def _register(matcher, state_code=None, name=NAME, club=CLUB, team_id="2026fall-7210"):
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=team_id,
        team_name=name,
        age_group="u12",
        gender="Male",
        club_name=club,
        state_code=state_code,
        written_club=club,
    )


def _twin(team_id, state_code):
    return _candidate(team_id, NAME, CLUB, age_group="u12", state_code=state_code)


def _candidate_reads(db):
    return [or_clauses for _, or_clauses, _ in db.reads("teams") if or_clauses]


class TestStatelessTeams:
    def test_a_stateless_team_links_to_its_stored_kansas_twin(self):
        db = _DB([_twin("ks-1", "KS")])

        result = _register(_matcher(db))

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "ks-1")
        assert db.writes("teams") == []
        [alias] = db.writes("team_alias_map")
        assert (alias["provider_team_id"], alias["team_id_master"]) == ("2026fall-7210", "ks-1")

    def test_a_stateless_team_links_to_its_stored_missouri_twin(self):
        db = _DB([_twin("mo-1", "MO")])

        assert _register(_matcher(db))["team_id"] == "mo-1"

    def test_a_stateless_team_with_no_twin_writes_nothing_and_is_not_created(self):
        db = _DB([_candidate("other", "Union KC 14/15B Pre ECNL Navy", "Union KC", age_group="u12", state_code="KS")])

        result = _register(_matcher(db))

        assert (result["matched"], result["created"]) == (False, False)
        assert not result.get("review")
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []
        assert db.writes("team_match_review_queue") == []

    def test_equal_twins_in_kansas_and_missouri_go_to_review_once(self):
        db = _DB([_twin("ks-1", "KS"), _twin("mo-1", "MO")])

        result = _register(_matcher(db))

        assert (result.get("review"), result["created"]) == (True, False)
        assert db.writes("team_alias_map") == []
        [review] = db.writes("team_match_review_queue")
        assert (review["provider_team_id"], review["confidence_score"]) == ("2026fall-7210", 0.89)

    def test_a_twin_with_no_state_ties_with_a_kansas_one(self):
        db = _DB([_twin("ks-1", "KS"), _twin("none-1", None)])

        assert _register(_matcher(db)).get("review") is True

    def test_a_dry_run_writes_no_review_row(self):
        db = _DB([_twin("ks-1", "KS"), _twin("mo-1", "MO")])

        assert _register(_matcher(db, dry_run=True)).get("review") is True
        assert db.writes("team_match_review_queue") == []


class TestStatedTeams:
    def test_a_kansas_team_picks_its_kansas_twin_over_a_missouri_one(self):
        db = _DB([_twin("mo-1", "MO"), _twin("ks-1", "KS")])

        result = _register(_matcher(db), state_code="KS")

        assert (result["matched"], result["team_id"]) == (True, "ks-1")

    def test_a_kansas_team_finds_its_only_stored_twin_in_missouri(self):
        db = _DB([_twin("mo-1", "MO")])

        assert _register(_matcher(db), state_code="KS")["team_id"] == "mo-1"

    def test_a_stated_team_with_no_twin_is_created_in_its_state(self):
        db = _DB()

        result = _register(_matcher(db), state_code="KS")

        assert (result["matched"], result["created"]) == (True, True)
        [team] = db.writes("teams")
        assert (team["team_name"], team["state_code"]) == (NAME, "KS")


class TestCandidateRead:
    def test_the_roster_pass_reads_kansas_missouri_and_stateless_teams(self):
        db = _DB()

        _register(_matcher(db))

        assert _candidate_reads(db) == [(("state_code", "KS"), ("state_code", "MO"), ("state_code", None))]

    def test_the_roster_pass_reads_live_teams_of_the_age_and_gender_in_a_stable_order(self):
        db = _DB()

        _register(_matcher(db))

        ((filters, _, order),) = db.reads("teams")[-1:]
        assert filters == {"age_group": "u12", "gender": "Male", "is_deprecated": False}
        assert order == "team_id_master"
        assert {"team_id_master", "team_name", "club_name", "state_code"} <= set(db.selected("teams"))

    def test_a_twin_past_the_first_page_of_candidates_is_found(self):
        filler = [
            _candidate(f"a-{i:04d}", f"Other Club U12 {i}", "Other Club", age_group="u12", state_code="KS")
            for i in range(1000)
        ]
        db = _DB([*filler, _twin("z-twin", "MO")])

        result = _register(_matcher(db))

        assert (result["matched"], result["team_id"]) == (True, "z-twin")
        assert db.writes("teams") == []

    def test_a_failed_candidate_read_raises_rather_than_reading_as_no_match(self):
        db = _DB([_twin("ks-1", "KS")])
        db.fail_candidate_query = True

        with pytest.raises(RuntimeError):
            _register(_matcher(db))

    def test_outside_the_roster_pass_a_stateless_team_reads_no_candidates(self):
        db = _DB([_twin("ks-1", "KS")])

        result = _register(_matcher(db, registration_mode=False))

        assert result["matched"] is False
        assert _candidate_reads(db) == []

    def test_outside_the_roster_pass_a_stated_team_searches_only_its_state(self):
        db = _DB()

        _register(_matcher(db, registration_mode=False), state_code="KS")

        assert _candidate_reads(db) == [(("state_code", "KS"), ("state_code", None))]

    def test_the_search_marker_is_no_state_code(self):
        assert REGION_SEARCH not in ("KS", "MO") and len(REGION_SEARCH) != 2
