"""Unit tests for the Tourney Central matcher.

It is the Athletes2Events matcher with two overrides, so the database double is that
matcher's: it records at ``execute()``, applies the state filter, raises
``APIError(PGRST116)`` on a zero-row ``.single()`` as postgrest does, and refuses
review rows the table's CHECK refuses. ``_KeepingDB`` also keeps what it inserts, so a
later lookup in the same run sees an earlier team, as the database would.
"""

import pytest

from scripts import import_tourneycentral_event as tc
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher, club_before_squad_marks
from tests.unit.test_athletes2events_matcher import _DB, PROVIDER, _candidate


class _KeepingDB(_DB):
    def table(self, name):
        query = super().table(name)
        execute = query.execute

        def execute_and_keep():
            result = execute()
            if query.op == "insert":
                self.rows.setdefault(name, []).append({"is_deprecated": False, **query.payload})
            return result

        query.execute = execute_and_keep
        return query


def _matcher(db, dry_run=False):
    return TourneyCentralGameMatcher(db, provider_id=PROVIDER, registration_mode=True, dry_run=dry_run)


def _register(
    matcher,
    name="Club Ohio Dayton U11B Green",
    club="Club Ohio Dayton",
    tc_id="317605",
    written=None,
    age_group="u11",
    gender="Male",
):
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=tc_id,
        team_name=name,
        age_group=age_group,
        gender=gender,
        club_name=club,
        state_code="OH",
        written_club=written or club,
    )


def _register_as_listed(db, name, club_field, age_group, gender="Male"):
    """Register a team as the driver does, with its club and written club read from its team-list row."""
    club, written = tc.club_for(club_field, name, "wfc.tourneycentral.com")
    return _register(_matcher(db), name=name, club=club, written=written, age_group=age_group, gender=gender)


class TestCreatedTeams:
    def test_a_created_team_keeps_its_full_name(self):
        """The Athletes2Events matcher would store "U11B Green", cutting the club off the front."""
        db = _DB()

        result = _register(_matcher(db))

        assert (result["matched"], result["created"]) == (True, True)
        [team] = db.writes("teams")
        assert (team["team_name"], team["club_name"]) == ("Club Ohio Dayton U11B Green", "Club Ohio Dayton")
        assert (team["state_code"], team["state"]) == ("OH", "Ohio")
        assert (team["provider_id"], team["provider_team_id"]) == (PROVIDER, "317605")
        assert (team["age_group"], team["gender"], team["distinction"]) == ("u11", "Male", "green")
        [alias] = db.writes("team_alias_map")
        assert (alias["provider_team_id"], alias["team_id_master"]) == ("317605", team["team_id_master"])

    def test_a_girls_team_is_created_as_female(self):
        db = _DB()

        _register(
            _matcher(db),
            name="Oakwood United Girls U10 Navy",
            club="Oakwood United",
            tc_id="315000",
            age_group="u10",
            gender="Female",
        )

        [team] = db.writes("teams")
        assert (team["gender"], team["age_group"], team["distinction"]) == ("Female", "u10", "navy")

    def test_two_teams_of_one_run_become_two_rows(self):
        """Each existence check looks up its own Tourney Central id, not any team of the provider."""
        db = _KeepingDB()
        matcher = _matcher(db)

        first = _register(matcher, name="Club Ohio Dayton U11B Green", tc_id="1")
        second = _register(matcher, name="Xcel Sport U11 Gold", club="Xcel Sport", tc_id="2")

        assert first["team_id"] != second["team_id"]
        assert (first["created"], second["created"]) == (True, True)
        assert [t["provider_team_id"] for t in db.writes("teams")] == ["1", "2"]

    def test_a_dry_run_writes_nothing_and_still_returns_a_stable_id(self):
        first_db, second_db = _DB(), _DB()

        first = _register(_matcher(first_db, dry_run=True))
        second = _register(_matcher(second_db, dry_run=True))

        assert first["created"] is True
        assert first["team_id"] == second["team_id"]
        assert (first_db.writes("teams"), first_db.writes("team_alias_map")) == ([], [])

    def test_a_team_row_already_carrying_the_id_is_relinked_not_created(self, monkeypatch):
        own_row = {
            **_candidate("m-own", "Club Ohio Dayton U11B Green", "Club Ohio Dayton", age_group="u11", state_code="OH"),
            "provider_id": PROVIDER,
            "provider_team_id": "317605",
        }
        db = _DB([own_row])
        matcher = _matcher(db)
        monkeypatch.setattr(matcher, "_fuzzy_match_team", lambda *a, **k: None)

        result = _register(matcher)

        assert (result["team_id"], result["created"], result["relinked"]) == ("m-own", False, True)
        assert db.writes("teams") == []


class TestInheritedMatching:
    def test_a_same_club_same_squad_team_in_the_state_links_rather_than_creating(self):
        db = _DB([_candidate("m1", "Warrior SC B15/16 White", "Warrior Soccer Club", age_group="u11", state_code="OH")])

        result = _register(_matcher(db), name="Warrior SC B15/16 White", club="Warrior Soccer Club", tc_id="317819")

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "m1")
        assert db.writes("teams") == []

    def test_a_row_of_another_birth_year_on_the_same_board_goes_to_review_not_to_a_link(self):
        """u19 holds 2008 and 2009; the birth-year guard reads the stored name this matcher returns."""
        db = _DB([_candidate("m08", "Elite FC 2008 Black", "Elite FC", age_group="u19", state_code="OH")])

        result = _register(_matcher(db), name="Elite FC B09 Black", club="Elite FC", age_group="u19")

        assert result["matched"] is False
        assert db.writes("team_alias_map") == []


class TestClubBeforeSquadMarks:
    @pytest.mark.parametrize(
        "written, club",
        [
            ("Lakota FC Pre", "Lakota FC"),
            ("Worthington United Navy 1", "Worthington United"),
            ("Ohio Premier North", "Ohio"),
            ("Warrior SC", "Warrior SC"),
            ("VASC", "VASC"),
            ("Blue Fire SC", None),
            (None, None),
        ],
    )
    def test_the_written_club_is_cut_back_before_any_squad_mark(self, written, club):
        assert club_before_squad_marks(written) == club


class TestWrittenClubGate:
    def test_a_stored_row_named_by_the_written_club_links_when_the_club_field_matches_nothing(self):
        """The team list says "Valentis"; PitchRank holds "VASC B12/13" under a third club name."""
        db = _DB([_candidate("vasc", "VASC B12/13", "Shelby County Youth Soccer", age_group="u14", state_code="OH")])

        result = _register(_matcher(db), name="VASC B12/13", club="Valentis", written="VASC", age_group="u14")

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "vasc")

    def test_the_club_field_is_tried_before_the_written_club(self):
        db = _DB(
            [
                _candidate("by-field", "Valentis B12/13", "Valentis", age_group="u14", state_code="OH"),
                _candidate("by-name", "VASC B12/13", "Shelby County Youth Soccer", age_group="u14", state_code="OH"),
            ]
        )

        result = _register(_matcher(db), name="VASC B12/13", club="Valentis", written="VASC", age_group="u14")

        assert result["team_id"] == "by-field"

    @pytest.mark.parametrize(
        "name, club_field, stored, gender, age_group",
        [
            ("Worthington United Navy 1 U14", "Worthington United SC", "Worthington United U14 Girls", "Female", "u14"),
            ("Lakota FC Pre-ECNL U13 Boys", "Lakota Futbol Club", "Lakota FC ECNL U13 Boys", "Male", "u13"),
            ("Ohio Premier North B2014", "Ohio Premier SC", "Ohio Premier B2014", "Male", "u13"),
        ],
    )
    def test_a_guessed_club_running_into_the_squad_marks_never_links_another_squad(
        self, name, club_field, stored, gender, age_group
    ):
        """The club field does not open the name, so the club is guessed from the words before the age."""
        db = _DB([_candidate("other", stored, club_field, age_group=age_group, state_code="OH", gender=gender)])

        result = _register_as_listed(db, name, club_field, age_group, gender)

        assert result["team_id"] != "other"
        assert [a["team_id_master"] for a in db.writes("team_alias_map")] != ["other"]

    def test_the_same_squad_still_links_when_the_club_is_guessed(self):
        db = _DB(
            [_candidate("same", "Lakota FC Pre-ECNL U13 Boys", "Lakota Futbol Club", age_group="u13", state_code="OH")]
        )

        result = _register_as_listed(db, "Lakota FC Pre-ECNL U13 Boys", "Lakota Futbol Club", "u13")

        assert (result["matched"], result["team_id"]) == (True, "same")

    @pytest.mark.parametrize(
        "name, club_field, stored, stored_club, gender, age_group",
        [
            (
                "U11 Elite FC Pre-ECNL - Black",
                "Elite FC (Oh)",
                "Elite FC Pre-ECNL B2015/16 Black",
                "Elite FC",
                "Male",
                "u11",
            ),
            (
                "Dayton Futbol Academy DFA 2012/2013G Premier",
                "Dayton Futbol Academy",
                "DFA 2012/2013G Premier",
                "Dayton Futbol Academy",
                "Female",
                "u14",
            ),
        ],
    )
    def test_a_club_field_opening_the_name_is_stripped_whole_and_links_its_stored_squad(
        self, name, club_field, stored, stored_club, gender, age_group
    ):
        """ "Elite" and "Academy" are squad words, but here they are the club's own name."""
        db = _DB([_candidate("stored", stored, stored_club, age_group=age_group, state_code="OH", gender=gender)])

        result = _register_as_listed(db, name, club_field, age_group, gender)

        assert (result["matched"], result["team_id"]) == (True, "stored")

    def test_a_squad_mark_left_in_the_name_keeps_a_markless_row_out(self):
        """With only the club stripped, "Navy 1" is a mark the stored row lacks, so no link."""
        db = _DB(
            [
                _candidate(
                    "wsp",
                    "WSP Eagle Warriors 2013 Girls",
                    "Worthington United",
                    age_group="u14",
                    state_code="OH",
                    gender="Female",
                )
            ]
        )

        result = _register(
            _matcher(db),
            name="Worthington United Navy 1 U14",
            club="Worthington United",
            age_group="u14",
            gender="Female",
        )

        assert result["created"] is True
        assert result["team_id"] != "wsp"
