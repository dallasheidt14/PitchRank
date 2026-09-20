"""The weekly club cleanup must never lower an abbreviation, and its SincSports/PlayMetrics
pass must write only what its dry run listed.

The re-case title-cases only a word it can read as an ordinary word; the cases below pin
that word by word.

`_FakeQuery` is written against PostgREST rather than against the calls this script
happens to make: it evaluates every filter at `execute()`, treats NULL the way SQL does,
returns fresh copies restricted to the selected columns, refuses a column the table does
not have, and raises `AttributeError` for any builder method it does not model, so a
query the double cannot evaluate fails instead of quietly matching everything. A ranged
read with no `order()` comes back in a different order on alternate pages, as an
unordered Postgres scan may, so paging one skips some rows and repeats others.
"""

import copy
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import scripts.full_club_analysis as fca
from scripts.full_club_analysis import (
    Vocabulary,
    analyze_state,
    apply_provider_rules,
    csv_safe,
    execute_fixes,
    fetch_all_teams,
    fetch_no_state_teams,
    generate_sql,
    has_age_or_gender_text,
    is_partial_recase,
    learn_vocabulary,
    overlay_fixes,
    proper_case,
    write_provider_changes,
)
from scripts.repair_swapped_club_names import lowered_abbreviation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "update-missing-club-and-state.yml"

SINC = "provider-sincsports"
PM = "provider-playmetrics"
GS = "provider-gotsport"
PROVIDERS = [
    {"id": SINC, "code": "sincsports"},
    {"id": PM, "code": "playmetrics"},
    {"id": GS, "code": "gotsport"},
]
PROVIDER_CODES = {SINC: "sincsports", PM: "playmetrics", GS: "gotsport"}

VOCAB = Vocabulary(
    spellings={"club": "Club", "soccer": "Soccer", "mclean": "McLean", "la": "La", "surf": "Surf"},
    mixed_names={"paso": 9},
)


def _team(team_id, club, state="AL", provider=SINC, deprecated=False):
    return {
        "team_id_master": team_id,
        "team_name": f"{club} U14 Blue",
        "club_name": club,
        "gender": "Male",
        "state_code": state,
        "provider_id": provider,
        "is_deprecated": deprecated,
    }


class _Result:
    def __init__(self, data):
        self.data = data


def _like_pattern(pattern):
    return "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern)


class _FakeQuery:
    def __init__(self, table, rows, db):
        self.table = table
        self._rows = rows
        self._db = db
        self._columns = None
        self._selected = False
        self._filters = []
        self._payload = None
        self._range = None
        self._order = None

    def _known(self, column):
        if self._rows and not all(column in row for row in self._rows):
            raise AssertionError(f"column {column!r} does not exist on {self.table!r}")
        return column

    def select(self, columns):
        names = [c.strip() for c in columns.split(",")]
        self._columns = None if names == ["*"] else [self._known(c) for c in names]
        self._selected = True
        return self

    def eq(self, column, value):
        self._filters.append(("eq", self._known(column), value))
        return self

    def neq(self, column, value):
        self._filters.append(("neq", self._known(column), value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", self._known(column), list(values)))
        return self

    def is_(self, column, value):
        if value != "null":
            raise AssertionError(f"is_ value the double does not model: {value!r}")
        self._filters.append(("is", self._known(column), None))
        return self

    def ilike(self, column, pattern):
        self._filters.append(("ilike", self._known(column), pattern))
        return self

    def or_(self, expression):
        disjuncts = []
        for part in expression.split(","):
            column, op, value = part.split(".", 2)
            if op == "is" and value == "null":
                disjuncts.append(("is", self._known(column), None))
            elif op == "eq":
                disjuncts.append(("eq", self._known(column), value))
            else:
                raise AssertionError(f"or_ form the double does not model: {part!r}")
        self._filters.append(("or", None, disjuncts))
        return self

    def order(self, column, desc=False):
        self._order = (self._known(column), desc)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def update(self, payload):
        for column in payload:
            self._known(column)
        self._payload = dict(payload)
        return self

    @staticmethod
    def _holds(row, kind, column, value):
        if kind == "or":
            return any(_FakeQuery._holds(row, *disjunct) for disjunct in value)
        cell = row[column]
        if kind == "is":
            return cell is None
        if cell is None:
            return False
        if kind == "eq":
            return cell == value
        if kind == "neq":
            return cell != value
        if kind == "in":
            return cell in value
        if kind == "ilike":
            return re.fullmatch(_like_pattern(value), cell, re.IGNORECASE | re.DOTALL) is not None
        raise AssertionError(f"unknown filter {kind!r}")

    def execute(self):
        if self._payload is not None and self._db.before_update:
            self._db.before_update(self._rows, self._filters)
        matched = [row for row in self._rows if all(self._holds(row, *f) for f in self._filters)]
        if self._payload is not None:
            for row in matched:
                row.update(self._payload)
            self._db.recorder.append(
                {
                    "kind": "update",
                    "table": self.table,
                    "payload": dict(self._payload),
                    "filters": list(self._filters),
                    "matched": len(matched),
                }
            )
            return _Result([dict(row) for row in matched])
        if not self._selected:
            raise AssertionError("a read with no select() is not a query this script sends")
        if self._order:
            column, desc = self._order
            matched.sort(key=lambda row: (row[column] is None, row[column]), reverse=desc)
        if self._range:
            start, end = self._range
            if self._order is None and (start // (end - start + 1)) % 2 == 0:
                matched.reverse()
            matched = matched[start : end + 1]
        self._db.recorder.append({"kind": "select", "table": self.table, "filters": list(self._filters)})
        if self._columns is None:
            return _Result([dict(row) for row in matched])
        return _Result([{c: row[c] for c in self._columns} for row in matched])


class _FakeSupabase:
    """`before_update(rows, filters)`, when set, runs as each update executes: it may raise,
    as a failed request does, or change a row, as another writer would."""

    def __init__(self, tables, before_update=None):
        self.tables = tables
        self.recorder = []
        self.before_update = before_update

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"unexpected table {name!r} — seed it or the test proves nothing")
        return _FakeQuery(name, self.tables[name], self)


def _db(*teams, before_update=None):
    return _FakeSupabase({"teams": [dict(t) for t in teams], "providers": [dict(p) for p in PROVIDERS]}, before_update)


def _updates(db):
    return [c for c in db.recorder if c["kind"] == "update"]


def _club(db, team_id):
    return next(t["club_name"] for t in db.tables["teams"] if t["team_id_master"] == team_id)


# --- the double itself ------------------------------------------------------------


def test_the_double_refuses_a_builder_method_it_does_not_model():
    with pytest.raises(AttributeError):
        _db().table("teams").select("club_name").limit(1)


def _page_through(db, ordered):
    ids, offset = [], 0
    while True:
        q = db.table("teams").select("team_id_master")
        q = q.order("team_id_master") if ordered else q
        page = q.range(offset, offset + 999).execute().data
        ids.extend(row["team_id_master"] for row in page)
        if len(page) < 1000:
            return ids
        offset += 1000


def test_the_double_pages_an_unordered_read_unreliably_and_an_ordered_one_completely():
    db = _db(*(_team(f"t{i:04d}", "Homewood SC") for i in reversed(range(1001))))
    everyone = [f"t{i:04d}" for i in range(1001)]

    assert _page_through(db, ordered=True) == everyone
    unordered = _page_through(db, ordered=False)
    assert len(unordered) == 1001
    assert set(unordered) == set(everyone) - {"t1000"}


def test_the_double_refuses_an_unseeded_table():
    with pytest.raises(AssertionError):
        _db().table("games")


def test_the_double_treats_null_the_way_postgrest_does():
    db = _db(_team("t1", None), _team("t2", "Homewood SC"))
    rows = db.table("teams").select("team_id_master").neq("club_name", "Other").execute().data
    assert rows == [{"team_id_master": "t2"}]
    rows = db.table("teams").select("team_id_master").ilike("club_name", "homewood%").execute().data
    assert rows == [{"team_id_master": "t2"}]


# --- the re-case ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DAVIS LEGACY SOCCER CLUB", "Davis Legacy Soccer Club"),
        ("O'FALLON FC", "O'Fallon FC"),
        ("MCLEAN YOUTH SOCCER", "McLean Youth Soccer"),
        ("CULLMAN UNITED SC (CUSC)", "Cullman United SC (CUSC)"),
        ("AFCHSV/UNITED SC", "AFCHSV/United SC"),
        ("METRO ATLANTA YMCA SOCCER", "Metro Atlanta YMCA Soccer"),
        ("YMCA'S SOCCER CLUB", "YMCA'S Soccer Club"),
        ("JSC SOCCER CLUB", "JSC Soccer Club"),
        ("PLATINUM IE FUTBOL CLUB", "Platinum IE Futbol Club"),
        ("NASA TOPHAT", "NASA Tophat"),
        ("NEFC", "NEFC"),
        ("FASC", "FASC"),
        ("JUSA", "JUSA"),
        ("AZFC", "AZFC"),
        ("AVSA", "AVSA"),
        ("WCUSC", "WCUSC"),
        ("MACON UNITED", "Macon United"),
        ("JSC Soccer Club", "JSC Soccer Club"),
        ("Flyte SC IE", "Flyte SC IE"),
        ("MACON'S UNITED", "Macon's United"),
        ("O’FALLON FC", "O’Fallon FC"),
        ("YMCA’S SOCCER CLUB", "YMCA’S Soccer Club"),
        ("MACON’S UNITED", "Macon’s United"),
        ("D'ARC UNITED", "D'ARC United"),
        ("D’ARC UNITED", "D’ARC United"),
        ("LA SURF", "LA Surf"),
        ("MACON UNITED (MACON)", "Macon United (MACON)"),
        ("MARSHALL  UNITED FUTBOL CLUB", "Marshall  United Futbol Club"),
        ("FC WISCONSIN", "FC Wisconsin"),
        ("LAKEFC UNITED", "LAKEFC United"),
        ("ALMANAC FC", "Almanac FC"),
        ("ANDBRO SC", "ANDBRO SC"),
    ],
)
def test_the_re_case_never_lowers_an_abbreviation(name, expected):
    assert proper_case(name, VOCAB) == expected


@pytest.mark.parametrize("acronym", sorted(fca._CLUB_ACRONYMS))
def test_a_lowered_abbreviation_is_restored_from_a_capitalised_variant(acronym):
    """The path the cleanup actually takes for a mixed-case club name.

    ``caps_winner`` merges case variants whenever any variant carries a lowercase
    letter, and reaches ``proper_case`` only when every variant is all-caps. So a
    mixed-case club is decided by ``merge_case_variants``, and that is where a lowered
    abbreviation would survive: the majority spelling below writes it lowered, and only
    the minority keeps its capitals.

    The check is the repair script's own definition of damage, so the two move together
    rather than each holding its own idea of what went wrong.
    """
    lowered = f"{acronym.capitalize()} Soccer Club"
    kept = f"{acronym} Soccer Club"

    winner = fca.caps_winner([lowered, kept], {lowered: 9, kept: 1}, "AL", VOCAB)

    assert acronym in winner, winner
    assert lowered_abbreviation(kept, winner) is None, winner


@pytest.mark.parametrize("acronym", sorted(fca._CLUB_ACRONYMS))
def test_an_all_caps_group_keeps_its_abbreviation(acronym):
    """No mixed-case variant, so the winner comes from ``proper_case`` instead."""
    name = f"{acronym} SOCCER CLUB"

    winner = fca.caps_winner([name], {name: 2}, "AL", VOCAB)

    assert acronym in winner, winner


def test_the_damage_classifier_still_recognises_the_renames_it_was_written_for():
    """Without this the guard above passes for a classifier that recognises nothing."""
    assert lowered_abbreviation("JSC Soccer Club", "Jsc Soccer Club") == "word"
    assert lowered_abbreviation("Homewood Soccer Club (AL)", "Homewood Soccer Club (al)") == "bracket"


def test_an_all_caps_override_output_is_not_re_cased(monkeypatch):
    monkeypatch.setattr(fca, "_OVERRIDE_OUTPUTS", frozenset({"MACON UNITED"}))
    assert proper_case("MACON UNITED", VOCAB) == "MACON UNITED"


def test_every_override_output_is_written_the_way_a_club_is():
    """caps_winner hands a whole case group the override's spelling, so an output typed in
    lowercase or in capitals re-cases every team holding the club."""
    for state, _, _, output in fca.CLUB_CANONICAL_OVERRIDES:
        assert output != output.lower(), (state, output)
        if fca.looks_all_caps(output):
            words = re.findall(r"[A-Za-z]+", output)
            assert all(fca.looks_like_acronym(w) for w in words), (state, output)


def test_a_name_needs_four_letters_to_count_as_all_caps():
    vocabulary = Vocabulary(spellings={"fox": "Fox", "foxy": "Foxy"}, mixed_names={})
    assert proper_case("FOX", vocabulary) == "FOX"
    assert proper_case("FOXY", vocabulary) == "Foxy"


def test_a_word_left_in_capitals_that_other_names_write_in_lowercase_is_a_partial_re_case():
    assert proper_case("EL PASO PREMIER LEAGUE", VOCAB) == "EL PASO Premier League"
    assert is_partial_recase("EL PASO Premier League", VOCAB) is True


def test_two_names_writing_a_word_in_lowercase_are_not_enough_to_call_it_partial():
    vocabulary = Vocabulary(spellings={}, mixed_names={"paso": 2})
    assert is_partial_recase("EL PASO Premier League", vocabulary) is False


def test_a_three_letter_word_written_in_lowercase_by_exactly_three_names_is_partial():
    vocabulary = Vocabulary(spellings={}, mixed_names={"pal": 3})
    assert is_partial_recase("Metro PAL Soccer", vocabulary) is True


def test_a_word_the_vocabulary_spells_in_capitals_is_not_partial():
    vocabulary = Vocabulary(spellings={"ymca": "YMCA"}, mixed_names={"ymca": 15})
    assert is_partial_recase("Metro Atlanta YMCA Soccer", vocabulary) is False


def test_a_word_holding_a_non_ascii_letter_is_never_partial():
    vocabulary = Vocabulary(spellings={}, mixed_names={"león": 5})
    assert is_partial_recase("Club LEÓN Premier", vocabulary) is False


def test_an_apostrophe_is_not_a_letter_of_a_word_left_in_capitals():
    vocabulary = Vocabulary(spellings={}, mixed_names={"o’n": 3})
    assert is_partial_recase("Metro O’N Soccer", vocabulary) is False


def test_a_curly_possessive_keeps_its_apostrophe():
    vocabulary = Vocabulary(
        spellings={**VOCAB.spellings, "st": "St", "mary": "Mary", "black": "Black", "lion": "Lion"},
        mixed_names={},
    )
    assert proper_case("ST MARY’S SOCCER CLUB", vocabulary) == "St Mary’s Soccer Club"
    assert proper_case("BLACK LION’S USA FC", vocabulary) == "Black Lion’s USA FC"


def test_a_name_holding_a_non_ascii_letter_is_left_whole():
    assert proper_case("MÉXICO UNITED", VOCAB) == "MÉXICO UNITED"


def test_a_word_holding_a_non_ascii_letter_is_left_as_written_past_the_whole_name_check(monkeypatch):
    monkeypatch.setattr(fca, "looks_all_caps", lambda name: True)
    assert proper_case("MÉXICO UNITED", VOCAB) == "MÉXICO United"


# --- the learner --------------------------------------------------------------------


def _names(template, count):
    return [template.format(i) for i in range(count)]


def test_the_learner_spells_a_word_the_way_the_database_does():
    vocabulary = learn_vocabulary(
        _names("Metro Ymca {}", 15)
        + _names("Downtown YMCA {}", 10)
        + _names("Alpha Club {}", 30)
        + _names("Beta CLUB {}", 5)
        + _names("Bold Rovers {}", 19)
    )

    assert vocabulary.spellings["ymca"] == "YMCA"
    assert vocabulary.spellings["club"] == "Club"
    assert "bold" not in vocabulary.spellings
    assert proper_case("METRO ATLANTA YMCA SOCCER", vocabulary) == "Metro Atlanta YMCA Soccer"
    assert proper_case("JSC SOCCER CLUB", vocabulary) == "JSC Soccer Club"
    assert proper_case("BOLD UNITED", vocabulary) == "BOLD United"
    assert is_partial_recase("BOLD United", vocabulary) is True


def test_a_short_word_is_learned_from_twenty_names():
    vocabulary = learn_vocabulary(_names("Bold Rovers {}", 20))
    assert proper_case("BOLD UNITED", vocabulary) == "Bold United"


def test_a_long_word_is_learned_from_three_names_and_not_two():
    assert proper_case("MCLEAN FC", learn_vocabulary(_names("McLean United {}", 2))) == "Mclean FC"
    assert proper_case("MCLEAN FC", learn_vocabulary(_names("McLean United {}", 3))) == "McLean FC"


def test_a_third_of_occurrences_in_capitals_spells_the_word_in_capitals():
    assert learn_vocabulary(_names("Metro Ymca {}", 20) + _names("Downtown YMCA {}", 10)).spellings["ymca"] == "YMCA"
    assert learn_vocabulary(_names("Alpha Club {}", 22) + _names("Beta CLUB {}", 8)).spellings["club"] == "Club"


def test_all_caps_names_teach_the_learner_nothing():
    vocabulary = learn_vocabulary(_names("Alpha Club {}", 22) + ["GAMMA CLUB"] * 50 + _names("GAMMA CLUB {}", 50))
    assert vocabulary.spellings["club"] == "Club"
    assert "gamma" not in vocabulary.spellings


def test_a_word_holding_a_non_ascii_letter_is_never_learned():
    assert learn_vocabulary(_names("Club León {}", 20)) == Vocabulary(
        spellings={"club": "Club"}, mixed_names={"club": 20}
    )


@pytest.mark.parametrize("apostrophe", ["'", "’"])
def test_an_apostrophe_does_not_count_toward_a_words_letters(apostrophe):
    assert learn_vocabulary(_names(f"Jeanne D{apostrophe}Arc {{}}", 3)).spellings == {"jeanne": "Jeanne"}


# --- the CAPS winner ----------------------------------------------------------------


def _caps_fixes(state, *clubs, vocabulary=VOCAB):
    teams = [_team(f"t{i}", club, state) for i, club in enumerate(clubs)]
    fixes, _, listed = analyze_state(teams, state, vocabulary)
    return {(f["from"], f["to"]) for f in fixes if f["type"] == "CAPS"}, listed


def test_the_caps_winner_keeps_the_mixed_case_spelling_of_an_all_caps_variant():
    fixes, _ = _caps_fixes("AL", "JSC Soccer Club", "JSC SOCCER CLUB")
    assert fixes == {("JSC SOCCER CLUB", "JSC Soccer Club")}


def test_an_override_output_wins_the_group_exactly():
    fixes, _ = _caps_fixes("CA", "FC Scorpions (CA)", "Fc Scorpions (Ca)", "Fc Scorpions (Ca)")
    assert fixes == {("Fc Scorpions (Ca)", "FC Scorpions (CA)")}

    fixes, _ = _caps_fixes("CA", "Legends FC (ca)", "Legends FC (ca)", "Legends FC (ca)", "Legends Fc (ca)")
    assert fixes == {("Legends FC (ca)", "Legends FC (CA)"), ("Legends Fc (ca)", "Legends FC (CA)")}


def test_a_short_word_takes_the_capitals_any_mixed_case_variant_gives_it():
    fixes, _ = _caps_fixes("KS", "Colorado Edge", "Colorado Edge", "Colorado Edge", "Colorado EDGE")
    assert fixes == {("Colorado Edge", "Colorado EDGE")}


def test_a_short_word_the_database_writes_in_lowercase_keeps_the_majority_case():
    vocabulary = Vocabulary(spellings={"rush": "Rush"}, mixed_names={})
    teams = [_team(f"t{i}", club, "WI") for i, club in enumerate(["Rush WI Southeast"] * 3 + ["RUSH WI Southeast"])]
    fixes, _, _ = analyze_state(teams, "WI", vocabulary)
    assert {(f["from"], f["to"]) for f in fixes if f["type"] == "CAPS"} == {("RUSH WI Southeast", "Rush WI Southeast")}


def test_colorado_edge_in_colorado_is_the_override_output():
    fixes, _ = _caps_fixes("CO", "Colorado Edge", "Colorado Edge", "Colorado Edge", "Colorado EDGE")
    assert fixes == {("Colorado EDGE", "Colorado Edge")}


def test_a_five_letter_word_keeps_the_majority_case():
    fixes, _ = _caps_fixes("TX", *["Tyler Storm SC"] * 3, "Tyler STORM SC")
    assert fixes == {("Tyler STORM SC", "Tyler Storm SC")}


def test_a_long_word_keeps_the_majority_case():
    fixes, _ = _caps_fixes("CA", "ALBION SC Orange County", *["Albion SC Orange County"] * 3)
    assert fixes == {("ALBION SC Orange County", "Albion SC Orange County")}


def test_a_bracketed_word_takes_the_capitals_whatever_its_length():
    fixes, _ = _caps_fixes("AL", *["Cullman United SC (Cullman)"] * 3, "Cullman United SC (CULLMAN)")
    assert fixes == {("Cullman United SC (Cullman)", "Cullman United SC (CULLMAN)")}


def test_a_bracketed_word_takes_the_capitals_an_all_caps_variant_gives_it():
    fixes, _ = _caps_fixes("KY", *["Kings Hammer Academy (ky)"] * 3, "KINGS HAMMER ACADEMY (KY)")
    assert fixes == {
        ("Kings Hammer Academy (ky)", "Kings Hammer Academy (KY)"),
        ("KINGS HAMMER ACADEMY (KY)", "Kings Hammer Academy (KY)"),
    }


def test_ccv_stars_keeps_its_abbreviation_against_a_lowered_majority():
    teams = [_team(f"t{i}", club, "AZ") for i, club in enumerate(["Ccv Stars"] * 3 + ["CCV STARS"])]
    fixes, _, _ = analyze_state(teams, "AZ", VOCAB)
    assert sorted((f["from"], f["to"], f["type"]) for f in fixes) == [
        ("CCV STARS", "CCV Stars", "CANONICAL"),
        ("Ccv Stars", "CCV Stars", "CANONICAL"),
    ]


def test_an_override_output_spelled_the_way_the_club_is_wins_its_group():
    fixes, _ = _caps_fixes("WI", *["FC Wisconsin"] * 3, "FC WISCONSIN")
    assert fixes == {("FC WISCONSIN", "FC Wisconsin")}


@pytest.mark.parametrize(
    ("clubs", "expected"),
    [
        (["Atlético Madrid"] * 2 + ["ATLÉTICO Madrid"], {("ATLÉTICO Madrid", "Atlético Madrid")}),
        (["Club León"] * 2 + ["Club LEÓN"], {("Club LEÓN", "Club León")}),
        (["Club (México)"] * 2 + ["CLUB (MÉXICO)"], {("CLUB (MÉXICO)", "Club (México)")}),
    ],
)
def test_a_word_holding_a_non_ascii_letter_keeps_the_most_common_spelling(clubs, expected):
    fixes, _ = _caps_fixes("TX", *clubs)
    assert fixes == expected


def test_a_club_code_takes_the_capitals_whatever_the_vocabulary_says():
    fixes, _ = _caps_fixes("TX", *["Test Sc"] * 3, "Test SC", vocabulary=Vocabulary({"sc": "Sc"}, {}))
    assert fixes == {("Test Sc", "Test SC")}


def test_a_club_code_takes_the_capitals_an_all_caps_variant_gives_it():
    fixes, _ = _caps_fixes("TX", *["Alpha Fc"] * 3, "ALPHA FC")
    assert fixes == {("Alpha Fc", "Alpha FC"), ("ALPHA FC", "Alpha FC")}


def test_a_state_code_the_vocabulary_writes_as_a_word_is_not_raised():
    fixes, _ = _caps_fixes("TX", *["La Roca FC"] * 3, "LA ROCA FC", vocabulary=Vocabulary({"la": "La"}, {}))
    assert fixes == {("LA ROCA FC", "La Roca FC")}


def test_a_short_word_the_vocabulary_spells_in_capitals_takes_them():
    fixes, _ = _caps_fixes("TX", *["Metro Ymca"] * 3, "Metro YMCA", vocabulary=Vocabulary({"ymca": "YMCA"}, {}))
    assert fixes == {("Metro Ymca", "Metro YMCA")}


@pytest.mark.parametrize(
    ("clubs", "expected"),
    [
        (["Jeanne D'Arc"] * 3 + ["Jeanne D'ARC"], {("Jeanne D'Arc", "Jeanne D'ARC")}),
        (["Jeanne D’Arc"] * 3 + ["Jeanne D’ARC"], {("Jeanne D’Arc", "Jeanne D’ARC")}),
    ],
)
def test_an_apostrophe_does_not_make_a_short_word_long(clubs, expected):
    fixes, _ = _caps_fixes("TX", *clubs)
    assert fixes == expected


# --- the provider pass ----------------------------------------------------------------


def _provider_pass(*teams):
    changes, listed = apply_provider_rules(list(teams), PROVIDER_CODES, VOCAB)
    return (
        {c["team_id_master"]: (c["after"], c["rule"]) for c in changes},
        sorted((team["team_id_master"], reason) for team, reason in listed),
    )


def test_a_tag_naming_the_teams_own_state_is_stripped():
    assert _provider_pass(_team("t1", "Homewood Soccer Club (al)", "AL")) == (
        {"t1": ("Homewood Soccer Club", "tag")},
        [],
    )


def test_a_tag_naming_another_state_stays_and_is_listed():
    assert _provider_pass(_team("t1", "DORADUS BARCA FC (MD)", "VA")) == (
        {"t1": ("Doradus Barca FC (MD)", "caps")},
        [("t1", "tag_mismatch")],
    )


def test_a_tag_that_is_not_a_state_stays_and_is_listed():
    assert _provider_pass(_team("t1", "CULLMAN UNITED SC (CUSC)", "AL")) == (
        {"t1": ("Cullman United SC (CUSC)", "caps")},
        [("t1", "tag_other")],
    )


def test_a_two_letter_tag_that_is_not_a_us_state_stays_even_when_the_state_column_holds_it():
    assert _provider_pass(_team("t1", "Platinum FC (IE)", "CA"), _team("t2", "Toronto Blizzard (ON)", "ON")) == (
        {},
        [("t1", "tag_other"), ("t2", "tag_other")],
    )


def test_a_tag_the_override_list_depends_on_stays_and_is_listed():
    assert _provider_pass(_team("t1", "Atletico FC (ut)", "UT")) == ({}, [("t1", "tag_override")])


def test_a_kept_override_tag_still_lets_the_re_case_run():
    assert _provider_pass(_team("t1", "ATLETICO FC (UT)", "UT")) == (
        {"t1": ("Atletico FC (UT)", "caps")},
        [("t1", "tag_override")],
    )


def test_a_tag_and_capitals_are_both_fixed():
    assert _provider_pass(_team("t1", "HOMEWOOD SC (AL)", "AL")) == ({"t1": ("Homewood SC", "tag+caps")}, [])


def test_a_team_with_no_state_keeps_its_tag():
    assert _provider_pass(_team("t1", "HOMEWOOD SC (AL)", None)) == (
        {"t1": ("Homewood SC (AL)", "caps")},
        [("t1", "tag_mismatch")],
    )


def test_an_override_output_is_untouched_whatever_its_case():
    assert _provider_pass(_team("t1", "Legends FC (ca)", "CA")) == ({}, [])


def test_age_or_gender_text_lists_the_team_and_changes_nothing():
    assert _provider_pass(_team("t1", "AFC ECNL-RL U17 Boys", "AL")) == ({}, [("t1", "age_gender")])


def test_age_text_is_read_before_the_tag():
    assert _provider_pass(_team("t1", "Homewood SC U14 (al)", "AL")) == ({}, [("t1", "age_gender")])


def test_a_word_that_starts_like_boy_is_not_gender_text():
    assert _provider_pass(_team("t1", "Boyds FC", "AL")) == ({}, [])


def test_only_ascii_digits_make_an_age():
    assert has_age_or_gender_text("U17") is True
    assert has_age_or_gender_text("U１７") is False
    assert _provider_pass(_team("t1", "U１７ Stars", "AL")) == ({}, [])


def test_a_partial_re_case_is_listed_and_not_written():
    assert _provider_pass(_team("t1", "EL PASO PREMIER LEAGUE", "TX")) == ({}, [("t1", "partial_recase")])


def test_a_stripped_tag_is_still_written_when_the_re_case_is_partial():
    assert _provider_pass(_team("t1", "EL PASO PREMIER LEAGUE (TX)", "TX")) == (
        {"t1": ("EL PASO PREMIER LEAGUE", "tag")},
        [("t1", "partial_recase")],
    )


def test_only_sincsports_and_playmetrics_teams_are_in_scope():
    assert _provider_pass(
        _team("sinc", "MACON UNITED", provider=SINC),
        _team("pm", "MACON UNITED", provider=PM),
        _team("gs", "MACON UNITED", provider=GS),
        _team("none", "MACON UNITED", provider=None),
    ) == ({"sinc": ("Macon United", "caps"), "pm": ("Macon United", "caps")}, [])


def test_a_state_tag_is_kept_only_where_that_states_override_needs_it():
    assert _provider_pass(_team("t1", "Legends FC (tx)", "TX")) == ({"t1": ("Legends FC", "tag")}, [])


def test_a_name_left_all_caps_by_a_stripped_tag_is_re_cased():
    assert _provider_pass(_team("t1", "HOMEWOOD SC (al)", "AL")) == ({"t1": ("Homewood SC", "tag+caps")}, [])


def test_a_re_case_that_changes_nothing_is_not_counted_as_one():
    assert _provider_pass(_team("t1", "NEFC (MA)", "MA")) == ({"t1": ("NEFC", "tag")}, [])


@pytest.mark.parametrize("club", ["HOMEWOOD 2014", "HOMEWOOD BOYS"])
def test_a_birth_year_or_a_gender_word_alone_lists_the_team_and_changes_nothing(club):
    assert _provider_pass(_team("t1", club, "AL")) == ({}, [("t1", "age_gender")])


def test_a_name_with_an_accented_capital_is_left_as_written():
    assert proper_case("GALÁCTICOS FC (MX)", VOCAB) == "GALÁCTICOS FC (MX)"
    assert _provider_pass(_team("t1", "GALÁCTICOS FC (MX)", "TX")) == ({}, [("t1", "tag_other")])


def test_the_same_name_in_ascii_capitals_is_re_cased():
    assert proper_case("GALACTICOS FC (MX)", VOCAB) == "Galacticos FC (MX)"
    assert _provider_pass(_team("t1", "GALACTICOS FC (MX)", "TX")) == (
        {"t1": ("Galacticos FC (MX)", "caps")},
        [("t1", "tag_other")],
    )


# --- the writes -------------------------------------------------------------------------


def _change(team_id="t1", before="HOMEWOOD SC", after="Homewood SC"):
    return {
        "team_id_master": team_id,
        "team_name": "x",
        "provider": "sincsports",
        "state": "AL",
        "before": before,
        "after": after,
        "rule": "caps",
    }


def test_a_provider_change_is_written_to_that_live_team_while_it_still_holds_the_club_read():
    db = _db(_team("t1", "HOMEWOOD SC"), _team("t2", "HOMEWOOD SC"))

    assert write_provider_changes(db, [_change()]) == (1, 0, 0)

    assert _updates(db) == [
        {
            "kind": "update",
            "table": "teams",
            "payload": {"club_name": "Homewood SC"},
            "filters": [
                ("eq", "team_id_master", "t1"),
                ("eq", "is_deprecated", False),
                ("eq", "club_name", "HOMEWOOD SC"),
            ],
            "matched": 1,
        }
    ]
    assert (_club(db, "t1"), _club(db, "t2")) == ("Homewood SC", "HOMEWOOD SC")


def test_a_team_deprecated_since_the_read_is_not_written():
    db = _db(_team("t1", "HOMEWOOD SC", deprecated=True))
    assert write_provider_changes(db, [_change()]) == (0, 1, 0)
    assert _club(db, "t1") == "HOMEWOOD SC"


def test_a_club_changed_since_the_read_is_not_written():
    db = _db(_team("t1", "Homewood Soccer"))
    assert write_provider_changes(db, [_change()]) == (0, 1, 0)
    assert _club(db, "t1") == "Homewood Soccer"


def test_execute_fixes_renames_live_rows_and_leaves_deprecated_ones():
    db = _db(
        _team("live", "HOMEWOOD SC", "AL"),
        _team("dead", "HOMEWOOD SC", "AL", deprecated=True),
        _team("live-null", "Lou Fusz", None),
        _team("live-empty", "Lou Fusz", ""),
        _team("dead-null", "Lou Fusz", None, deprecated=True),
    )
    fixes = [
        {"from": "HOMEWOOD SC", "to": "Homewood SC", "count": 1, "type": "CAPS", "state": "AL"},
        {"from": "Lou Fusz", "to": "Lou Fusz Athletic", "count": 2, "type": "CANONICAL_NO_STATE", "state": None},
    ]

    execute_fixes(db, fixes, dry_run=False)

    assert [_club(db, t) for t in ("live", "dead", "live-null", "live-empty", "dead-null")] == [
        "Homewood SC",
        "HOMEWOOD SC",
        "Lou Fusz Athletic",
        "Lou Fusz Athletic",
        "Lou Fusz",
    ]


def test_the_sql_audit_trail_touches_only_live_rows():
    sql = generate_sql(
        [
            {"from": "HOMEWOOD SC", "to": "Homewood SC", "count": 1, "type": "CAPS", "state": "AL"},
            {"from": "Lou Fusz", "to": "Lou Fusz Athletic", "count": 2, "type": "CANONICAL_NO_STATE", "state": None},
        ]
    )
    updates = [line for line in sql.splitlines() if line.startswith("UPDATE")]
    assert updates == [
        "UPDATE teams SET club_name = 'Homewood SC' WHERE club_name = 'HOMEWOOD SC' AND state_code = 'AL' "
        "AND is_deprecated = false;",
        "UPDATE teams SET club_name = 'Lou Fusz Athletic' WHERE club_name = 'Lou Fusz' "
        "AND (state_code IS NULL OR state_code = '') AND is_deprecated = false;",
    ]


def test_a_line_break_in_a_club_cannot_end_the_sql_comment():
    sql = generate_sql(
        [{"from": "Evil\nDROP TABLE teams; --", "to": "Evil\r\n\tFC", "count": 1, "type": "CAPS", "state": "AL"}]
    )
    lines = sql.split("\n")
    comment = next(i for i, line in enumerate(lines) if line.startswith("-- [CAPS]"))

    assert lines[comment] == '-- [CAPS] "Evil DROP TABLE teams; --" → "Evil FC" (1 teams)'
    assert sql.split("\n", comment + 1)[-1].startswith(
        "UPDATE teams SET club_name = 'Evil\r\n\tFC' WHERE club_name = 'Evil\nDROP TABLE teams; --' "
        "AND state_code = 'AL' AND is_deprecated = false;\n"
    )


def test_a_quote_in_the_state_is_escaped_in_the_sql():
    sql = generate_sql([{"from": "HOMEWOOD SC", "to": "Homewood SC", "count": 1, "type": "CAPS", "state": "A'L"}])
    assert [line for line in sql.splitlines() if line.startswith("UPDATE")] == [
        "UPDATE teams SET club_name = 'Homewood SC' WHERE club_name = 'HOMEWOOD SC' AND state_code = 'A''L' "
        "AND is_deprecated = false;"
    ]


def test_a_state_fix_leaves_the_same_club_in_another_state_or_with_no_state():
    teams = [
        _team("al", "HOMEWOOD SC", "AL"),
        _team("ga", "HOMEWOOD SC", "GA"),
        _team("null", "HOMEWOOD SC", None),
        _team("empty", "HOMEWOOD SC", ""),
    ]
    fixes = [{"from": "HOMEWOOD SC", "to": "Homewood SC", "count": 1, "type": "CAPS", "state": "AL"}]

    assert [t["club_name"] for t in overlay_fixes(teams, fixes)] == [
        "Homewood SC",
        "HOMEWOOD SC",
        "HOMEWOOD SC",
        "HOMEWOOD SC",
    ]


def test_a_states_teams_are_paged_in_team_order():
    db = _db(
        _team("other-state", "Homewood SC", "GA"),
        *(_team(f"t{i:04d}", "Homewood SC", "AL") for i in reversed(range(1001))),
        _team("dead", "Homewood SC", "AL", deprecated=True),
    )
    assert [t["team_id_master"] for t in fetch_all_teams(db, "AL")] == [f"t{i:04d}" for i in range(1001)]


def test_teams_with_no_state_are_paged_in_team_order():
    db = _db(
        _team("empty-a", "Homewood SC", ""),
        _team("empty-b", "Homewood SC", ""),
        _team("stated", "Homewood SC", "AL"),
        *(_team(f"t{i:04d}", "Homewood SC", None) for i in reversed(range(1001))),
        _team("dead", "Homewood SC", None, deprecated=True),
    )
    assert [t["team_id_master"] for t in fetch_no_state_teams(db)] == [f"t{i:04d}" for i in range(1001)] + [
        "empty-a",
        "empty-b",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@SUM(1)", "'@SUM(1)"),
        ("\t=1", "'\t=1"),
        ("\r=1", "'\r=1"),
        ("\n=1", "'\n=1"),
        ("Homewood SC", "Homewood SC"),
        ("A-1 FC", "A-1 FC"),
        ("", ""),
        (None, None),
    ],
)
def test_text_a_spreadsheet_would_run_as_a_formula_is_quoted(value, expected):
    assert csv_safe(value) == expected


def test_the_overlay_applies_fixes_in_order_to_copies():
    teams = [_team("t1", "HOMEWOOD SC", "AL"), _team("t2", "Lou Fusz", None), _team("t3", "Lou Fusz", "")]
    fixes = [
        {"from": "HOMEWOOD SC", "to": "Homewood Sc", "count": 1, "type": "CAPS", "state": "AL"},
        {"from": "Homewood Sc", "to": "Homewood SC", "count": 1, "type": "NAMING", "state": "AL"},
        {"from": "Lou Fusz", "to": "Lou Fusz Athletic", "count": 2, "type": "CANONICAL_NO_STATE", "state": None},
    ]

    overlaid = overlay_fixes(teams, fixes)

    assert [t["club_name"] for t in overlaid] == ["Homewood SC", "Lou Fusz Athletic", "Lou Fusz Athletic"]
    assert [t["club_name"] for t in teams] == ["HOMEWOOD SC", "Lou Fusz", "Lou Fusz"]


# --- main() end to end ----------------------------------------------------------------------


SEEDED_TEAMS = (
    _team("gs-1", "Homewood SC", "AL", provider=GS),
    _team("gs-2", "Homewood SC", "AL", provider=GS),
    _team("sinc-homewood", "HOMEWOOD SC", "AL"),
    _team("sinc-macon", "MACON UNITED", "AL"),
    _team("gs-macon", "MACON UNITED", "AL", provider=GS),
    _team("gs-naming-1", "MACON UNITED SOCCER CLUB", "AL", provider=GS),
    _team("gs-naming-2", "MACON UNITED SOCCER CLUB", "AL", provider=GS),
    _team("sinc-naming", "MACON UNITED SC", "AL"),
    _team("sinc-null", "MACON UNITED", None),
    _team("sinc-empty", "CULLMAN UNITED", ""),
    _team("sinc-dead", "HOMEWOOD SC", "AL", deprecated=True),
)


def _seeded_db(before_update=None):
    return _db(*SEEDED_TEAMS, before_update=before_update)


def _review_db():
    """The seeded teams plus a tag change, a tag-and-caps change and two teams listed for review."""
    return _db(
        *SEEDED_TEAMS,
        _team("gs-caps-2", "HOMEWOOD SC", "AL", provider=GS),
        _team("sinc-tag", "Homewood Soccer Club (al)", "AL"),
        _team("pm-tag-caps", "CULLMAN UNITED (AL)", "AL", provider=PM),
        _team("pm-age", "Macon FC U14 Boys", "AL", provider=PM),
        _team("sinc-mismatch", "Doradus FC (MD)", "VA"),
    )


SERVICE_ROLE_ENV = {"SUPABASE_SERVICE_ROLE_KEY": "service-key", "SUPABASE_KEY": "anon-key"}


def _run_main(monkeypatch, tmp_path, db, *flags, keys=SERVICE_ROLE_ENV):
    """Run main() with only `keys` among the Supabase key variables; returns each (url, key) it connected with."""
    monkeypatch.setattr(fca, "SQL_OUTPUT_PATH", str(tmp_path / "fixes.sql"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["full_club_analysis.py", *flags])
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    connections = []

    def create_client(url, key):
        connections.append((url, key))
        return db

    monkeypatch.setattr(fca, "create_client", create_client)
    fca.main()
    return connections


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


EXPECTED_CHANGES = [
    {
        "team_id_master": "sinc-empty",
        "team_name": "CULLMAN UNITED U14 Blue",
        "provider": "sincsports",
        "state": "",
        "before": "CULLMAN UNITED",
        "after": "Cullman United",
        "rule": "caps",
    },
    {
        "team_id_master": "sinc-null",
        "team_name": "MACON UNITED U14 Blue",
        "provider": "sincsports",
        "state": "",
        "before": "MACON UNITED",
        "after": "Macon United",
        "rule": "caps",
    },
    {
        "team_id_master": "sinc-macon",
        "team_name": "MACON UNITED U14 Blue",
        "provider": "sincsports",
        "state": "AL",
        "before": "MACON UNITED",
        "after": "Macon United",
        "rule": "caps",
    },
    {
        "team_id_master": "sinc-naming",
        "team_name": "MACON UNITED SC U14 Blue",
        "provider": "sincsports",
        "state": "AL",
        "before": "MACON UNITED SOCCER CLUB",
        "after": "Macon United Soccer CLUB",
        "rule": "caps",
    },
]


@pytest.mark.parametrize("flags", [["--dry-run"], [], ["--execute", "--dry-run"]])
def test_a_run_without_execute_writes_nothing_and_lists_the_provider_changes(monkeypatch, tmp_path, flags):
    db = _seeded_db()
    before = copy.deepcopy(db.tables)

    _run_main(monkeypatch, tmp_path, db, *flags)

    assert _updates(db) == []
    assert db.tables == before
    assert _read_csv(tmp_path / "logs" / "club_name_provider_changes.csv") == EXPECTED_CHANGES
    assert _read_csv(tmp_path / "logs" / "club_name_review.csv") == []
    assert "AND is_deprecated = false;" in (tmp_path / "fixes.sql").read_text(encoding="utf-8")


def test_execute_writes_exactly_what_the_dry_run_listed(monkeypatch, tmp_path):
    dry_dir, live_dir = tmp_path / "dry", tmp_path / "live"
    dry_dir.mkdir()
    live_dir.mkdir()
    _run_main(monkeypatch, dry_dir, _seeded_db(), "--dry-run")
    listed = {(r["team_id_master"], r["after"]) for r in _read_csv(dry_dir / "logs" / "club_name_provider_changes.csv")}

    db = _seeded_db()
    _run_main(monkeypatch, live_dir, db, "--execute")

    provider_writes = [u for u in _updates(db) if u["filters"][0][1] == "team_id_master"]
    assert {(u["filters"][0][2], u["payload"]["club_name"]) for u in provider_writes} == listed
    assert all(u["matched"] == 1 for u in provider_writes)
    assert next(u for u in provider_writes if u["filters"][0][2] == "sinc-macon")["filters"] == [
        ("eq", "team_id_master", "sinc-macon"),
        ("eq", "is_deprecated", False),
        ("eq", "club_name", "MACON UNITED"),
    ]
    assert {t["team_id_master"]: t["club_name"] for t in db.tables["teams"]} == {
        "gs-1": "Homewood SC",
        "gs-2": "Homewood SC",
        "sinc-homewood": "Homewood SC",
        "sinc-macon": "Macon United",
        "gs-macon": "MACON UNITED",
        "gs-naming-1": "MACON UNITED SOCCER CLUB",
        "gs-naming-2": "MACON UNITED SOCCER CLUB",
        "sinc-naming": "Macon United Soccer CLUB",
        "sinc-null": "Macon United",
        "sinc-empty": "Cullman United",
        "sinc-dead": "HOMEWOOD SC",
    }


def test_the_provider_pass_reads_the_club_the_existing_fixes_leave(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, _seeded_db(), "--dry-run")
    before = {r["team_id_master"]: r["before"] for r in _read_csv(tmp_path / "logs" / "club_name_provider_changes.csv")}
    assert "sinc-homewood" not in before
    assert before["sinc-naming"] == "MACON UNITED SOCCER CLUB"


def test_execute_and_dry_run_together_preview_the_fixes(monkeypatch, tmp_path, capsys):
    _run_main(monkeypatch, tmp_path, _seeded_db(), "--execute", "--dry-run")
    assert "[DRY RUN] Would apply 2 club name fixes" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY"])
def test_execute_writes_with_the_service_role_key(monkeypatch, tmp_path, name):
    db = _seeded_db()
    keys = {name: "service-key", "SUPABASE_KEY": "anon-key"}

    connections = _run_main(monkeypatch, tmp_path, db, "--execute", keys=keys)

    assert connections == [("https://example.invalid", "service-key")]
    assert _club(db, "sinc-macon") == "Macon United"


def test_execute_with_only_the_anon_key_is_refused_before_anything_is_read(monkeypatch, tmp_path, capsys):
    """anon holds the UPDATE grant but no UPDATE policy, so every write would match zero rows and report success."""
    db = _seeded_db()
    before = copy.deepcopy(db.tables)

    with pytest.raises(SystemExit) as exited:
        _run_main(monkeypatch, tmp_path, db, "--execute", keys={"SUPABASE_KEY": "anon-key"})

    assert exited.value.code == 1
    assert (db.recorder, db.tables) == ([], before)
    assert not (tmp_path / "fixes.sql").exists()
    assert capsys.readouterr().out.splitlines()[-1] == (
        "ERROR: --execute needs SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY; the anon key writes nothing"
    )


@pytest.mark.parametrize("flags", [["--dry-run"], [], ["--execute", "--dry-run"]])
def test_a_run_that_writes_nothing_needs_only_the_anon_key(monkeypatch, tmp_path, flags):
    db = _seeded_db()

    connections = _run_main(monkeypatch, tmp_path, db, *flags, keys={"SUPABASE_KEY": "anon-key"})

    assert connections == [("https://example.invalid", "anon-key")]
    assert _updates(db) == []
    assert _read_csv(tmp_path / "logs" / "club_name_provider_changes.csv") == EXPECTED_CHANGES


def _raise_where(column, value):
    def before_update(rows, filters):
        if ("eq", column, value) in filters:
            raise RuntimeError("simulated PostgREST failure")

    return before_update


@pytest.mark.parametrize(
    ("column", "value", "error"),
    [
        ("team_id_master", "sinc-macon", "ERROR: 0 club name fixes and 1 provider rule writes failed"),
        ("state_code", "AL", "ERROR: 2 club name fixes and 0 provider rule writes failed"),
    ],
)
def test_a_failed_write_fails_the_run(monkeypatch, tmp_path, capsys, column, value, error):
    with pytest.raises(SystemExit) as exited:
        _run_main(monkeypatch, tmp_path, _seeded_db(_raise_where(column, value)), "--execute")

    assert exited.value.code == 1
    assert capsys.readouterr().out.splitlines()[-1] == error


def test_a_team_changed_by_another_writer_does_not_fail_the_run(monkeypatch, tmp_path, capsys):
    def another_writer(rows, filters):
        if ("eq", "team_id_master", "sinc-macon") in filters:
            next(row for row in rows if row["team_id_master"] == "sinc-macon")["club_name"] = "Macon Utd"

    db = _seeded_db(another_writer)
    _run_main(monkeypatch, tmp_path, db, "--execute")

    out = capsys.readouterr().out
    assert "Provider rule writes: 3 written, 1 no longer matched, 0 failed" in out
    assert "ERROR:" not in out
    assert _club(db, "sinc-macon") == "Macon Utd"


def test_the_review_csvs_quote_formula_text_and_the_write_does_not(monkeypatch, tmp_path):
    db = _db(
        {**_team("sinc-formula", "-MACON UNITED", "AL"), "team_name": "=HYPERLINK(1)"},
        {**_team("pm-formula", "@HOMEWOOD U14", "AL", provider=PM), "team_name": "+cmd"},
    )
    _run_main(monkeypatch, tmp_path, db, "--execute")

    assert _read_csv(tmp_path / "logs" / "club_name_provider_changes.csv") == [
        {
            "team_id_master": "sinc-formula",
            "team_name": "'=HYPERLINK(1)",
            "provider": "sincsports",
            "state": "AL",
            "before": "'-MACON UNITED",
            "after": "'-Macon United",
            "rule": "caps",
        }
    ]
    assert _read_csv(tmp_path / "logs" / "club_name_review.csv") == [
        {
            "team_id_master": "pm-formula",
            "team_name": "'+cmd",
            "provider": "playmetrics",
            "state": "AL",
            "club": "'@HOMEWOOD U14",
            "reason": "age_gender",
        }
    ]
    assert _club(db, "sinc-formula") == "-Macon United"


def test_the_review_csvs_open_as_utf8_in_a_spreadsheet(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, _review_db(), "--dry-run")

    for name in ("club_name_provider_changes.csv", "club_name_review.csv"):
        assert (tmp_path / "logs" / name).read_bytes().startswith(b"\xef\xbb\xbfteam_id_master,"), name


def test_a_state_held_only_by_the_first_team_read_is_still_processed(monkeypatch, tmp_path):
    db = _db(
        _team("wy-macon", "MACON UNITED", "WY"),
        *(_team(f"al-{i:04d}", "Homewood SC", "AL", provider=GS) for i in range(1000)),
    )
    _run_main(monkeypatch, tmp_path, db, "--dry-run")

    assert _read_csv(tmp_path / "logs" / "club_name_provider_changes.csv") == [
        {
            "team_id_master": "wy-macon",
            "team_name": "MACON UNITED U14 Blue",
            "provider": "sincsports",
            "state": "WY",
            "before": "MACON UNITED",
            "after": "Macon United",
            "rule": "caps",
        }
    ]


def test_the_review_list_names_each_listed_teams_club_and_provider(monkeypatch, tmp_path, capsys):
    _run_main(monkeypatch, tmp_path, _review_db(), "--dry-run")

    assert _read_csv(tmp_path / "logs" / "club_name_review.csv") == [
        {
            "team_id_master": "pm-age",
            "team_name": "Macon FC U14 Boys U14 Blue",
            "provider": "playmetrics",
            "state": "AL",
            "club": "Macon FC U14 Boys",
            "reason": "age_gender",
        },
        {
            "team_id_master": "sinc-mismatch",
            "team_name": "Doradus FC (MD) U14 Blue",
            "provider": "sincsports",
            "state": "VA",
            "club": "Doradus FC (MD)",
            "reason": "tag_mismatch",
        },
    ]
    provider_lines = [line for line in capsys.readouterr().out.splitlines() if "PROVIDER RULES:" in line]
    assert provider_lines == ["PROVIDER RULES: 6 changes (2 tag + 5 caps); 2 listed for review"]


def _step3_block():
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["update-missing-club-and-state"]["steps"]
    return next(step["run"] for step in steps if step.get("id") == "step3")


def _grep_o(pattern, text, first_line_only):
    """What `grep -oP` prints for `text`, one value per match; only the text after a PCRE `\\K` is kept."""
    head, sep, tail = pattern.partition(r"\K")
    regex = re.compile(f"(?:{head})(?P<kept>{tail})" if sep else f"(?P<kept>{pattern})")
    found = []
    for line in text.split("\n"):
        kept = [m.group("kept") for m in regex.finditer(line)]
        found.extend(value for value in kept if value)
        if kept and first_line_only:
            break
    return found


def _step3_outputs(stdout):
    """The `$GITHUB_OUTPUT` values Step 3 derives from `stdout`, read through its own greps.

    Each assignment's `grep -oP` stages run in order, every stage over the previous stage's
    output, as `grep -o` does, and `-m1` stops at the first matching line. A grep flag this
    reader does not model fails the test, and a stage must yield exactly one value.
    """
    block = _step3_block()
    values = {}
    for name, body in re.findall(r"^\s*([A-Z_][A-Z0-9_]*)=\$\((.+)\)\s*$", block, re.M):
        stages = re.findall(r"grep((?: -\w+)+) '([^']*)'", body)
        if not stages:
            continue
        text = stdout
        for flags, pattern in stages:
            flags = flags.split()
            assert "-oP" in flags and set(flags) <= {"-oP", "-m1"}, (name, flags)
            found = _grep_o(pattern, text, first_line_only="-m1" in flags)
            assert len(found) == 1, (name, pattern, found)
            text = found[0]
        values[name] = text
    outputs = re.findall(r'^\s*echo "(\w+)=\$\{?([A-Z_][A-Z0-9_]*)', block, re.M)
    return {key: values.get(variable) for key, variable in outputs}


def test_the_workflow_reads_each_count_from_the_run_once(monkeypatch, tmp_path, capsys):
    _run_main(monkeypatch, tmp_path, _review_db(), "--dry-run")

    assert _step3_outputs(capsys.readouterr().out) == {
        "naming_fixes": "2",
        "teams_standardized": "3",
        "provider_changes": "6",
        "review_listed": "2",
    }


def test_the_workflow_reads_the_provider_counts_from_the_first_provider_line(monkeypatch, tmp_path, capsys):
    _run_main(monkeypatch, tmp_path, _review_db(), "--dry-run")
    stdout = capsys.readouterr().out + "PROVIDER RULES: 9 changes (1 tag + 8 caps); 7 listed for review\n"

    outputs = _step3_outputs(stdout)

    assert (outputs["provider_changes"], outputs["review_listed"]) == ("6", "2")


def test_step3_reports_its_counts_before_failing_with_the_script():
    lines = [line.strip() for line in _step3_block().splitlines()]
    commands = [line for line in lines if line and not line.startswith("#")]
    runs = [command for command in commands if command.startswith("python scripts/full_club_analysis.py")]

    assert len(runs) == 1
    assert runs[0].endswith(" || STEP3_RC=$?")
    assert commands[-1] == 'exit "${STEP3_RC:-0}"'


def test_the_script_runs_the_way_the_workflow_runs_it():
    """`python scripts/full_club_analysis.py` puts scripts/ on sys.path rather than the repo
    root, so the bootstrap that reaches src/ is load-bearing there and inert under pytest."""
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "scripts/full_club_analysis.py", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_the_sql_audit_trail_still_defaults_to_the_tracked_file():
    expected = PROJECT_ROOT / "scripts" / "club_name_fixes_male_all_states.sql"
    assert Path(fca.SQL_OUTPUT_PATH).resolve() == expected.resolve()
