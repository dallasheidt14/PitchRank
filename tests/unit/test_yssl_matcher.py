"""Unit tests for the YSSL matcher.

The database double is the Athletes2Events matcher test's: it records at
``execute()``, applies the ``or_`` state filter, refuses review rows the table's
CHECK refuses, and raises ``APIError(PGRST116)`` on a zero-row ``.single()`` as
postgrest does, which is the normal path for the pre-create existence check.
"""

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from src.models.yssl_matcher import YSSLGameMatcher

PROVIDER = "33333333-3333-4333-8333-333333333333"
NO_ROWS = APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.or_clauses = []
        self.order_by = None
        self.op = "select"
        self.payload = None
        self.single_row = False
        self.window = None
        self.columns = None

    def select(self, columns="*", *_a, **_k):
        self.columns = [c.strip() for c in columns.split(",")] if columns != "*" else None
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def or_(self, expression):
        for clause in expression.split(","):
            field, op, value = clause.split(".", 2)
            self.or_clauses.append((field, None if (op, value) == ("is", "null") else value))
        return self

    def order(self, field):
        self.order_by = field
        return self

    def in_(self, field, values):
        self.filters.append((field, tuple(values)))
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def single(self):
        self.single_row = True
        return self

    def insert(self, data):
        self.op, self.payload = "insert", data
        return self

    def update(self, data):
        self.op, self.payload = "update", data
        return self

    def _matches(self, row):
        for field, value in self.filters:
            if isinstance(value, tuple):
                if row.get(field) not in value:
                    return False
            elif row.get(field) != value:
                return False
        return not self.or_clauses or any(row.get(field) == value for field, value in self.or_clauses)

    def execute(self):
        if self.db.fail_candidate_query and self.table == "teams" and self.or_clauses:
            raise RuntimeError("canceling statement due to statement timeout")
        if self.table == "team_match_review_queue" and self.op == "insert":
            # The table's CHECK (confidence_range): 0.75 <= confidence_score < 0.90.
            if not 0.75 <= self.payload["confidence_score"] < 0.90:
                raise RuntimeError('violates check constraint "confidence_range"')
        self.db.executed.append(
            (self.table, self.op, dict(self.filters), self.payload, tuple(self.or_clauses), self.order_by, self.columns)
        )
        if self.op != "select":
            return SimpleNamespace(data=[self.payload])
        rows = [r for r in self.db.rows.get(self.table, []) if self._matches(r)]
        if self.order_by:
            rows.sort(key=lambda r: str(r.get(self.order_by)))
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        if self.columns is not None:
            rows = [{c: r.get(c) for c in self.columns} for r in rows]
        if self.single_row:
            if not rows:
                raise NO_ROWS
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, teams=()):
        self.rows = {
            "providers": [{"id": PROVIDER, "code": "yssl"}],
            "teams": [{"is_deprecated": False, **t} for t in teams],
            "team_alias_map": [],
            "team_match_review_queue": [],
        }
        self.executed = []
        self.fail_candidate_query = False

    def table(self, name):
        return _Query(self, name)

    def writes(self, table):
        return [payload for t, op, _, payload, _, _, _ in self.executed if t == table and op != "select"]

    def reads(self, table):
        return [
            (filters, or_clauses, order)
            for t, op, filters, _, or_clauses, order, _ in self.executed
            if t == table and op == "select"
        ]

    def selected(self, table):
        """Columns the first read of ``table`` asked for."""
        for t, op, _, _, _, _, columns in self.executed:
            if t == table and op == "select":
                return columns
        return None


def _candidate(team_id, team_name, club_name, age_group="u12", state_code="IL"):
    return {
        "team_id_master": team_id,
        "team_name": team_name,
        "club_name": club_name,
        "age_group": age_group,
        "gender": "Male",
        "state_code": state_code,
    }


def _register(db, name="AAC EAGLES CHICAGO 14/15 GOLD", dry_run=False):
    matcher = YSSLGameMatcher(db, provider_id=PROVIDER, registration_mode=True, dry_run=dry_run)
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id="AACM121",
        team_name=name,
        age_group="u12",
        gender="Male",
        club_name="AAC Eagles",
        state_code="IL",
        written_club="AAC EAGLES CHICAGO",
    )


def test_links_the_existing_squad_despite_band_spelling():
    db = _DB(
        [
            _candidate("t1", "AAC EAGLES CHICAGO 2014-15 GOLD", "AAC Eagles"),
            _candidate("t2", "AAC EAGLES CHICAGO 2015 RED", "AAC Eagles"),
        ]
    )
    result = _register(db)
    assert (result["matched"], result["team_id"], result["created"]) == (True, "t1", False)
    assert db.writes("teams") == []


def test_a_different_squad_color_is_created_with_its_full_name():
    db = _DB([_candidate("t2", "AAC EAGLES CHICAGO 2015 RED", "AAC Eagles")])
    result = _register(db)
    assert result["created"] is True
    [team] = db.writes("teams")
    assert (team["team_name"], team["club_name"], team["state_code"], team["state"]) == (
        "AAC EAGLES CHICAGO 14/15 GOLD",
        "AAC Eagles",
        "IL",
        "Illinois",
    )
    assert (team["provider_id"], team["provider_team_id"], team["age_group"], team["gender"]) == (
        PROVIDER,
        "AACM121",
        "u12",
        "Male",
    )
    [alias] = db.writes("team_alias_map")
    assert (alias["provider_team_id"], alias["match_method"], alias["review_status"]) == (
        "AACM121",
        "direct_id",
        "approved",
    )


def test_another_clubs_team_is_never_a_candidate():
    db = _DB([_candidate("t9", "PEGASUS FC 14/15 GOLD", "Pegasus FC")])
    assert _register(db)["created"] is True


def test_a_team_already_carrying_the_code_is_relinked_not_duplicated():
    carrying = {"provider_id": PROVIDER, "provider_team_id": "AACM121"}
    db = _DB([{**_candidate("t5", "OLD NAME", "Other Club", age_group="u11"), **carrying}])
    result = _register(db)
    assert (result["team_id"], result["created"], result["relinked"]) == ("t5", False, True)
    assert db.writes("teams") == []


def test_dry_run_writes_nothing():
    db = _DB([])
    result = _register(db, dry_run=True)
    assert result["created"] is True
    assert [entry for entry in db.executed if entry[1] != "select"] == []


def _register_as(db, name, club, written, age_group="u10"):
    matcher = YSSLGameMatcher(db, provider_id=PROVIDER, registration_mode=True)
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id="2026-XXXM101",
        team_name=name,
        age_group=age_group,
        gender="Male",
        club_name=club,
        state_code="IL",
        written_club=written,
    )


RUSH_SC = "Chicago Rush Soccer Club"


def test_a_branch_word_missing_from_the_candidate_blocks_the_link():
    db = _DB([_candidate("t1", "SC 2016 Oswego Blue", RUSH_SC, age_group="u11")])
    result = _register_as(db, "RUSH - WILMETTE WINGS 15/16B BLUE", RUSH_SC, "CHICAGO RUSH", age_group="u11")
    assert result["created"] is True


def test_a_squad_word_missing_from_the_candidate_blocks_the_link():
    club = "Eclipse Select Soccer Club"
    db = _DB([_candidate("t1", "Eclipse 2017 Solar Naperville Boys", club, age_group="u10")])
    result = _register_as(db, "ECLIPSE 16/17 LUNAR NAPERVILLE", club, "ECLIPSE SELECT SOCCER CLUB")
    assert result["created"] is True


def test_every_distinguishing_word_present_still_links():
    db = _DB([_candidate("t1", "U10 (16/17) Chicago Rush North Boys Premier", RUSH_SC, age_group="u10")])
    result = _register_as(db, "RUSH NORTH 16/17 PREMIER", RUSH_SC, "CHICAGO RUSH")
    assert (result["team_id"], result["created"]) == ("t1", False)


def test_an_abbreviated_word_in_the_candidate_still_links():
    db = _DB([_candidate("t1", "Chicago Rush SC - 2016 Chicago Rush West Prem", RUSH_SC, age_group="u11")])
    result = _register_as(db, "RUSH WEST 15/16 PREMIER", RUSH_SC, "CHICAGO RUSH", age_group="u11")
    assert (result["team_id"], result["created"]) == ("t1", False)


def test_a_club_word_that_reads_as_a_level_does_not_block_the_link():
    club = "Hawthorn Woods Elite SC"
    db = _DB([_candidate("t1", "Hawthorn Woods Elite SC Boys 2016-17 Black", club, age_group="u10")])
    result = _register_as(db, "HAWTHORN WOODS ELITE 16/17 BLACK", club, "HAWTHORN WOODS ELITE")
    assert (result["team_id"], result["created"]) == ("t1", False)


def test_a_stored_word_shorter_than_four_letters_is_not_an_abbreviation():
    db = _DB([_candidate("t1", "Chicago Rush 2016 B Premier", RUSH_SC, age_group="u10")])
    result = _register_as(db, "RUSH 16/17 BLAZE", RUSH_SC, "RUSH")
    assert result["created"] is True


def test_a_single_letter_is_not_a_squad_word():
    db = _DB([_candidate("t1", "AAC Eagles 2014 Gold", "AAC Eagles", age_group="u12")])
    result = _register_as(db, "AAC EAGLES CHICAGO 14/15 B GOLD", "AAC Eagles", "AAC EAGLES CHICAGO", age_group="u12")
    assert (result["team_id"], result["created"]) == ("t1", False)


def test_yssl_abbreviations_are_expanded_before_matching():
    club = "NWI Lions United"
    db = _DB([_candidate("t1", "NWI Lions United U12 Yellow II 2014/15B", club, age_group="u12", state_code="IN")])
    matcher = YSSLGameMatcher(db, provider_id=PROVIDER, registration_mode=True)
    result = matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id="2026-NWIM121",
        team_name="NWI LIONS UTD 14/15 YELLOW II",
        age_group="u12",
        gender="Male",
        club_name=club,
        state_code="IN",
        written_club="NWI LIONS",
    )
    assert (result["team_id"], result["created"]) == ("t1", False)


def test_the_clubs_initials_count_as_club_words():
    db = _DB([_candidate("t1", "Plainfield United SC 2014/15B Select Black", "United Elite", age_group="u12")])
    result = _register_as(
        db, "UESC-PLAINFIELD UTD 14/15 SEL BLACK", "United Elite", "UNITED ELITE SOCCER CLUB", age_group="u12"
    )
    assert (result["team_id"], result["created"]) == ("t1", False)


def test_a_created_team_keeps_the_yssl_spelling():
    db = _DB([])
    _register_as(db, "UESC-PLAINFIELD UTD 14/15 SEL BLACK", "United Elite", "UNITED ELITE SOCCER CLUB", age_group="u12")
    [team] = db.writes("teams")
    assert team["team_name"] == "UESC-PLAINFIELD UTD 14/15 SEL BLACK"


@pytest.mark.parametrize(
    ("yssl_name", "stored_name", "links"),
    [
        ("PRSC 16/17 WHITE 1", "PRSC U10 B White", True),
        ("PRSC 16/17 WHITE 2", "PRSC U10 B White", False),
        ("PRSC 16/17 WHITE 2", "PRSC U10 B White 2", True),
        ("PRSC 16/17 WHITE II", "PRSC U10 B White 2", True),
        ("PRSC 16/17 WHITE 2", "PRSC U10 B White 1", False),
        ("PRSC 16/17 - 2ND TEAM WHITE", "PRSC U10 B White Team 2", True),
        ("PRSC 16/17 - 3RD TEAM WHITE", "PRSC U10 B White", False),
        ("PRSC 16/17 WHITE", "PRSC U10 B White", True),
        ("PRSC 16/17 WHITE 1", "PRSC U10 B 2nd Team White", False),
        ("PRSC 16/17 WHITE", "PRSC U10 B White 2", False),
        ("PRSC 16/17 WHITE", "PRSC U10 B White 1", True),
        ("PRSC U10 WHITE 2", "PRSC U10 B White", False),
        ("PRSC 2016-2017 WHITE II", "PRSC U10 B White", False),
    ],
    ids=[
        "1-to-none",
        "2-to-none",
        "2-to-2",
        "roman-to-digit",
        "2-to-1",
        "ordinal",
        "3rd-to-none",
        "none-to-none",
        "1-to-2nd",
        "none-to-2",
        "none-to-1",
        "no-band-2-to-none",
        "hyphen-band-2-to-none",
    ],
)
def test_a_squad_numbered_two_or_more_needs_the_same_number(yssl_name, stored_name, links):
    club = "Park Ridge SC"
    db = _DB([_candidate("t1", stored_name, club, age_group="u10")])
    result = _register_as(db, yssl_name, club, "PRSC")
    assert (result["team_id"] == "t1") is links
