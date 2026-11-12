"""An automatic name match never links a team record to a row of the other gender.

Names that differ only by a B or G (``LFA 17/18B …`` and ``LFA 17/18G …``) normalize to the same
string, and the matcher filters its candidates by the game's gender, which is the division's: a
girls team in a boys division is matched against boys rows. A row stored under the wrong gender
still names its own, so the accept point reads the matched row again.
"""

from types import SimpleNamespace

import pytest

from src.models.game_matcher import GameHistoryMatcher

PROVIDER = "provider-uuid"
CLUB = "Lou Fusz Athletic"
GIRLS = "LFA 17/18G Red Star Swift (2036)"
BOYS = "LFA 17/18B Red Star Swift (2036)"


class _Query:
    """Applies its filters, returns only the selected columns, raises on a .single() that does
    not find exactly one row, and records every call -- payload included -- at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._payload = None
        self._columns = None
        self._filters = []
        self._single = False

    def select(self, columns="*", *_a, **_k):
        self._columns = None if columns.strip() == "*" else [c.strip() for c in columns.split(",")]
        return self

    def insert(self, payload, *_a, **_k):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload, *_a, **_k):
        self._op, self._payload = "update", payload
        return self

    def eq(self, field, value):
        self._filters.append(("eq", field, value))
        return self

    def like(self, field, pattern):
        self._filters.append(("like", field, pattern))
        return self

    def ilike(self, field, pattern):
        self._filters.append(("ilike", field, pattern))
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        self._single = True
        return self

    def __getattr__(self, name):
        self._db.unmodeled.append(name)
        raise AttributeError(name)

    def _keeps(self, row, kind, field, value):
        cell = row.get(field)
        if kind == "eq":
            return cell == value
        needle = value.strip("%")
        if kind == "like":
            return needle in str(cell or "")
        return needle.lower() == str(cell or "").lower()

    def execute(self):
        self._db.executed.append({"table": self._table, "op": self._op, "payload": self._payload})
        if self._db.raise_on == (self._table, self._op):
            raise RuntimeError("connection reset")
        if self._op != "select":
            return SimpleNamespace(data=[])
        rows = [r for r in self._db.rows.get(self._table, []) if all(self._keeps(r, *f) for f in self._filters)]
        if self._columns:
            rows = [{c: r.get(c) for c in self._columns} for r in rows]
        if self._single:
            if len(rows) != 1:
                raise RuntimeError("PGRST116: JSON object requested, multiple (or no) rows returned")
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, teams):
        self.rows = {
            "teams": teams,
            "team_alias_map": [],
            "team_match_review_queue": [],
            "providers": [{"id": PROVIDER, "code": "gotsport"}],
        }
        self.executed = []
        self.unmodeled = []
        self.raise_on = None

    def table(self, name):
        return _Query(self, name)

    def writes(self, table):
        return [q for q in self.executed if q["table"] == table and q["op"] != "select"]


def _row(team_id, name, gender, original=None):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": original,
        "club_name": CLUB,
        "age_group": "u9",
        "gender": gender,
        "state_code": "MO",
    }


def _match(db, name=GIRLS, gender="Female"):
    matcher = GameHistoryMatcher(db, provider_id=PROVIDER)
    return matcher._match_team(PROVIDER, "750465", name, "u9", gender, club_name=CLUB)


def test_a_girls_record_is_not_linked_to_a_boys_row_stored_as_girls():
    """The row's current name states nothing; its registered name and the record disagree."""
    db = _DB([_row("boys-row", "LFA 17/18 Red Star Swift (2036)", "Female", original=BOYS)])

    result = _match(db)

    assert result["method"] == "fuzzy_review"
    assert db.writes("team_alias_map") == []
    queued = db.writes("team_match_review_queue")
    assert [q["payload"]["suggested_master_team_id"] for q in queued] == ["boys-row"]
    assert db.unmodeled == []


def test_a_girls_record_in_a_boys_division_is_not_linked_to_a_boys_row_named_for_neither():
    """Only the row's stored gender says boys, and the division's gender agrees with it."""
    db = _DB([_row("boys-row", "LFA 17/18 Red Star Swift (2036)", "Male")])

    result = _match(db, gender="Male")

    assert result["method"] == "fuzzy_review"
    assert db.writes("team_alias_map") == []
    queued = db.writes("team_match_review_queue")
    assert [q["payload"]["suggested_master_team_id"] for q in queued] == ["boys-row"]
    assert db.unmodeled == []


def test_a_b_g_twin_does_not_win_the_candidate_search():
    """The boys twin is filtered in by the division's gender and scores like the right row."""
    db = _DB([_row("boys-twin", BOYS, "Female")])

    result = _match(db)

    assert result["matched"] is False
    assert db.writes("team_alias_map") == []
    assert [q["payload"]["suggested_master_team_id"] for q in db.writes("team_match_review_queue")] == [None]
    assert db.unmodeled == []


def test_a_b_g_twin_listed_first_does_not_shadow_the_right_row():
    db = _DB([_row("boys-twin", BOYS, "Female"), _row("girls-row", GIRLS, "Female")])

    result = _match(db)

    assert (result["matched"], result["team_id"]) == (True, "girls-row")
    assert [q["payload"]["team_id_master"] for q in db.writes("team_alias_map")] == ["girls-row"]
    assert db.unmodeled == []


def test_a_record_of_the_same_gender_still_links():
    db = _DB([_row("girls-row", GIRLS, "Female")])

    result = _match(db)

    assert (result["matched"], result["method"], result["team_id"]) == (True, "fuzzy_auto", "girls-row")
    assert [q["payload"]["team_id_master"] for q in db.writes("team_alias_map")] == ["girls-row"]
    assert db.unmodeled == []


def test_a_name_stating_no_gender_links_as_before():
    db = _DB([_row("row", "LFA 17/18 Red Star Swift (2036)", "Female")])

    result = _match(db, name="LFA 17/18 Red Star Swift (2036)")

    assert result["method"] == "fuzzy_auto"
    assert db.unmodeled == []


def test_tgs_does_not_reuse_its_own_row_once_the_guard_holds_it():
    """TGS's match step creates a team for an id it cannot link, first reusing the row the id
    already names. When that row is the one the guard just held, reusing it would link the record
    anyway."""
    from src.models.tgs_matcher import ReuseRefused, TGSGameMatcher

    own_row = {**_row("own-row", BOYS, "Female"), "provider_id": PROVIDER, "provider_team_id": "750465"}
    db = _DB([own_row])

    with pytest.raises(ReuseRefused):
        TGSGameMatcher(db, provider_id=PROVIDER).create_team(PROVIDER, "750465", GIRLS, CLUB, "u9", "Female")

    assert db.writes("team_alias_map") == []
    assert db.writes("teams") == []
    assert db.unmodeled == []


class _FlakyQuery(_Query):
    """The first single-row teams lookup drops its connection, and every teams insert collides."""

    def execute(self):
        db = self._db
        if self._table == "teams" and self._single and db.single_failures:
            db.single_failures -= 1
            db.executed.append({"table": self._table, "op": self._op, "payload": self._payload})
            raise RuntimeError("connection reset")
        if self._table == "teams" and self._op == "insert":
            db.executed.append({"table": self._table, "op": self._op, "payload": self._payload})
            raise RuntimeError('duplicate key value violates unique constraint "teams_provider_key" (23505)')
        return super().execute()


class _FlakyDB(_DB):
    def __init__(self, teams):
        super().__init__(teams)
        self.single_failures = 1

    def table(self, name):
        return _FlakyQuery(self, name)


def test_tgs_does_not_reuse_the_held_row_after_a_duplicate_key_insert():
    """A failed first lookup is taken for "no row yet", so the insert collides and the duplicate-key
    branch finds the row the guard held."""
    from src.models.tgs_matcher import ReuseRefused, TGSGameMatcher

    own_row = {**_row("own-row", BOYS, "Female"), "provider_id": PROVIDER, "provider_team_id": "750465"}
    db = _FlakyDB([own_row])
    matcher = TGSGameMatcher(db, provider_id=PROVIDER)
    matcher._club_state_cache[CLUB] = (None, None)

    with pytest.raises(ReuseRefused):
        matcher.create_team(PROVIDER, "750465", GIRLS, CLUB, "u9", "Female")

    assert [q["op"] for q in db.executed if q["table"] == "teams" and q["op"] == "insert"] == ["insert"]
    assert db.writes("team_alias_map") == []
    assert db.unmodeled == []


@pytest.mark.parametrize("teams,raise_on", [([], None), ([_row("girls-row", GIRLS, "Female")], ("teams", "select"))])
def test_a_matched_row_that_cannot_be_read_counts_as_a_conflict(teams, raise_on):
    db = _DB(teams)
    db.raise_on = raise_on
    assert GameHistoryMatcher(db, provider_id=PROVIDER)._genders_conflict(GIRLS, "girls-row") is True
