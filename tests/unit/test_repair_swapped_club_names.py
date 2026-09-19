"""Repairing swapped club names proposes from three sources and writes only approved rows.

The script turns a reviewed CSV into service-role writes on ``teams.club_name``, so the
double below is written to be no more forgiving than PostgREST: it evaluates every
filter at ``execute()``, applies NULL semantics, honours ``ilike`` wildcards and
escapes, gives a ranged read with no ``order()`` a different order on each call,
returns fresh copies restricted to the selected columns, refuses a builder method or
table nobody modelled, and records only what reached ``execute()``. Its two
hooks let a test change a row between the replay's read and its write, which is the
window the compare-and-set exists for.
"""

import csv
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.repair_swapped_club_names as repair
from scripts.repair_swapped_club_names import (
    build_snapshot,
    classify_team_name,
    club_part,
    escape_like,
    fetch_playmetrics_clubs,
    load_snapshot,
    parse_cleanup_log,
    parse_league_urls,
    read_run_log,
    resolve_execute,
    revert,
    snapshot_csv_row,
    snapshot_row,
    write_log,
)

GS = "provider-gotsport"
PM = "provider-playmetrics"
PMT = "provider-playmetrics-tournament"
SINC = "provider-sincsports"
TGS = "provider-tgs"
M11 = "provider-modular11"
PROVIDERS = [
    {"id": GS, "code": "gotsport"},
    {"id": PM, "code": "playmetrics"},
    {"id": PMT, "code": "playmetrics_tournament"},
    {"id": SINC, "code": "sincsports"},
    {"id": TGS, "code": "tgs"},
    {"id": M11, "code": "modular11"},
]
CODES = {p["id"]: p["code"] for p in PROVIDERS}


def _uuid(n):
    return f"00000000-0000-0000-0000-{n:012d}"


def _team(n, team_name, club, provider=TGS, state="TX", provider_team_id=None, deprecated=False):
    return {
        "team_id_master": _uuid(n),
        "team_name": team_name,
        "club_name": club,
        "state_code": state,
        "provider_id": provider,
        "provider_team_id": provider_team_id or str(n),
        "is_deprecated": deprecated,
    }


def _line(label, before, after, step="UNKNOWN STEP"):
    return (
        f"Update Missing Club Names & State Codes\t{step}\t2026-09-14T16:12:54.4283827Z   "
        f'✅ {label}: "{before}" → "{after}"'
    )


# --- the double ----------------------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


def _like_regex(pattern):
    """PostgreSQL ILIKE with its default ``\\`` escape, after PostgREST has turned every
    ``*`` into ``%``, escaped or not."""
    out, escaped = [], False
    for ch in pattern.replace("*", "%"):
        if escaped:
            out.append(re.escape(ch))
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


class _FakeQuery:
    def __init__(self, db, table):
        self._db = db
        self.table = table
        self._rows = db.tables[table]
        self._columns = None
        self._selected = False
        self._filters = []
        self._payload = None
        self._order = None
        self._range = None

    def _known(self, column):
        if self._rows and not all(column in row for row in self._rows):
            raise AssertionError(f"column {column!r} does not exist on {self.table!r}")
        return column

    def select(self, columns):
        self._columns = [self._known(c.strip()) for c in columns.split(",")]
        self._selected = True
        return self

    def eq(self, column, value):
        self._filters.append(("eq", self._known(column), value))
        return self

    def neq(self, column, value):
        self._filters.append(("neq", self._known(column), value))
        return self

    def in_(self, column, values):
        values = list(values)
        if len(values) > 100:
            raise AssertionError(f"an .in_ list of {len(values)} overruns the URI limit")
        self._filters.append(("in", self._known(column), values))
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
            return re.fullmatch(_like_regex(value), cell, re.IGNORECASE | re.DOTALL) is not None
        raise AssertionError(f"unknown filter {kind!r}")

    def execute(self):
        if self._payload is not None:
            for hook in self._db.before_update:
                hook(self.table)
            matched = [row for row in self._rows if all(self._holds(row, *f) for f in self._filters)]
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
        matched = [row for row in self._rows if all(self._holds(row, *f) for f in self._filters)]
        if self._order:
            matched.sort(key=lambda r: r[self._order[0]] or "", reverse=self._order[1])
        elif self._range:
            self._db.unordered_ranges += 1
            if self._db.unordered_ranges % 2 == 0:
                matched.reverse()
        if self._range:
            matched = matched[self._range[0] : self._range[1] + 1]
        self._db.recorder.append({"kind": "select", "table": self.table, "filters": list(self._filters)})
        result = [{c: row[c] for c in self._columns} for row in matched]
        for hook in self._db.after_read:
            hook(self.table)
        return _Result(result)


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.recorder = []
        self.after_read = []
        self.before_update = []
        self.unordered_ranges = 0

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"unexpected table {name!r} — seed it or the test proves nothing")
        return _FakeQuery(self, name)


def _db(*teams):
    return _FakeSupabase({"teams": [dict(t) for t in teams], "providers": [dict(p) for p in PROVIDERS]})


def _updates(db):
    return [c for c in db.recorder if c["kind"] == "update"]


def _club(db, n):
    return next(t["club_name"] for t in db.tables["teams"] if t["team_id_master"] == _uuid(n))


def test_the_double_refuses_a_builder_method_it_does_not_model():
    with pytest.raises(AttributeError):
        _db().table("teams").select("club_name").limit(1)


def test_the_double_refuses_a_table_nobody_seeded():
    with pytest.raises(AssertionError, match="unexpected table"):
        _db().table("team_alias_map")


def test_the_double_reads_every_star_as_a_percent_sign():
    """PostgREST maps ``*`` to ``%`` whether or not it is escaped."""
    db = _db(_team(1, "a", "AxB"), _team(2, "b", "A*B"), _team(3, "c", "A%B"))

    def holders(pattern):
        query = db.table("teams").select("club_name").ilike("club_name", pattern)
        return [row["club_name"] for row in query.execute().data]

    assert holders("a*b") == ["AxB", "A*B", "A%B"]
    assert holders("a\\*b") == ["A%B"]


def test_the_double_gives_unordered_pages_no_stable_order():
    db = _db(_team(1, "a", "X"), _team(2, "b", "X"))

    def first_row():
        return db.table("teams").select("team_id_master").range(0, 0).execute().data

    assert (first_row(), first_row()) == ([{"team_id_master": _uuid(1)}], [{"team_id_master": _uuid(2)}])


# --- where a team name's club part ends ------------------------------------------------


@pytest.mark.parametrize(
    "team_name,expected",
    [
        ("Oregon Surf GU11 PreECNL", ("Oregon Surf", True)),
        ("Sporting Wichita U16 HD", ("Sporting Wichita", True)),
        ("Bold FC 2014 Pre-ECNL", ("Bold FC", True)),
        ("Real Colorado 14B Red", ("Real Colorado", True)),
        ("Club Tempo ECNL-RL G12", ("Club Tempo", True)),
        ("XF - B16/17 A", ("XF", True)),
        ("CAI de la Chorrera MLS NEXT", ("CAI de la Chorrera", True)),
        ("Boyds FC U12", ("Boyds FC", True)),
        ("Hadley Athletic U12", ("Hadley Athletic", True)),
        ("Toronto FC", ("Toronto FC", False)),
    ],
)
def test_the_club_part_ends_at_the_first_age_or_level_token(team_name, expected):
    assert club_part(team_name) == expected


@pytest.mark.parametrize("team_name", ["Club Tempo U１２ Blue", "Club Tempo Boyſ Blue", "Club Tempo MLS NEXT"])
def test_a_non_ascii_lookalike_is_not_an_age_token(team_name):
    """The text before a token is written to teams.club_name; see .claude/rules/data-safety.md.
    Unicode matching folds "ſ" into "s" and reads a no-break space as a space."""
    assert club_part(team_name) == (team_name, False)


# --- the team_name decision rules ------------------------------------------------------


def test_a_club_still_in_canonical_upper_case_is_an_approved_swap():
    assert classify_team_name("Oregon Surf GU11 PreECNL", "SURF") == ("swap", "Oregon Surf")


def test_a_re_cased_canonical_club_is_listed_not_swapped():
    assert classify_team_name("Sporting Wichita U16 HD", "Sporting KC") == ("recased", "Sporting Wichita")


def test_a_squad_of_the_stored_club_is_skipped():
    assert classify_team_name("FC Dallas Red U14", "FC DALLAS") == ("skip_prefix", "")


def test_a_team_named_with_its_stored_club_is_skipped():
    assert classify_team_name("FC DELCO Pre-ECNL G2014/15", "FC DELCO") == ("skip_prefix", "")


def test_a_team_whose_whole_name_reads_as_the_stored_club_is_skipped():
    """The light form of "Solar Soccer Club U12" is that of "SOLAR SC", with nothing after it."""
    assert classify_team_name("Solar Soccer Club U12", "SOLAR SC") == ("skip_prefix", "")


def test_the_prefix_rule_is_bounded_by_words():
    """Surfside FC is not a squad of SURF."""
    assert classify_team_name("Surfside FC U12", "SURF") == ("swap", "Surfside FC")


def test_a_squad_label_naming_the_stored_club_is_skipped():
    assert classify_team_name("Solar White U12", "Solar SC") == ("skip_core", "")


def test_the_squad_label_rule_is_bounded_by_words():
    """Surfside does not name Surf."""
    assert classify_team_name("Surfside Elite U12", "Surf") == ("recased", "Surfside Elite")


def test_an_abbreviated_squad_label_is_listed_not_written():
    """An initialism does not spell out the stored club's core ("LSC" is not "lonestar"),
    so the core check cannot see it; the row stays listed, never approved."""
    assert classify_team_name("LSC White USC TX RL B2012", "Lonestar") == ("recased", "LSC White USC TX RL")


@pytest.mark.parametrize(
    "team_name,proposal",
    [
        ("FC", "FC"),
        ("Toronto FC", "Toronto FC"),
        ("WSC Crush WSC Crush 16 Boys Black", "WSC Crush WSC Crush 16"),
        ("XF - B16/17 A", "XF"),
    ],
)
def test_an_unclear_team_name_needs_review(team_name, proposal):
    assert classify_team_name(team_name, "SURF") == ("needs_review", proposal)


# --- selecting the teams ---------------------------------------------------------------


def test_the_team_name_source_proposes_from_a_non_gotsport_team():
    rows, _ = build_snapshot(_db(_team(1, "Oregon Surf GU11 PreECNL", "SURF", provider=M11, state="OR")), {}, [])

    assert rows == [
        {
            "team_id_master": _uuid(1),
            "provider": "modular11",
            "state": "OR",
            "team_name": "Oregon Surf GU11 PreECNL",
            "stored_club": "SURF",
            "proposed_club": "Oregon Surf",
            "source": "team_name",
            "tier": "swap",
            "needs_review": False,
            "approved": True,
            "state_note": "",
        }
    ]


def test_the_team_name_source_never_reads_a_gotsport_team():
    rows, _ = build_snapshot(
        _db(
            _team(1, "Oregon Surf GU11 PreECNL", "SURF", provider=GS),
            _team(2, "Oregon Surf GU12 PreECNL", "SURF", provider=TGS),
        ),
        {},
        [],
    )
    assert [r["team_id_master"] for r in rows] == [_uuid(2)]


def test_the_team_name_source_reads_playmetrics_tournament_teams():
    rows, _ = build_snapshot(_db(_team(1, "NC Fusion U12 Blue", "Ventura County Fusion", provider=PMT)), {}, [])
    assert [(r["proposed_club"], r["tier"]) for r in rows] == [("NC Fusion", "recased")]


def test_a_re_cased_canonical_club_is_still_selected():
    """The weekly cleanup re-cases an upper-case club to a spelling its state already holds."""
    rows, _ = build_snapshot(_db(_team(1, "Sporting Wichita U16 HD", "Sporting KC", provider=M11, state="KS")), {}, [])

    assert [(r["proposed_club"], r["tier"], r["approved"]) for r in rows] == [("Sporting Wichita", "recased", False)]


@pytest.mark.parametrize("club", ["NEFC", "Nefc"])
def test_nefc_is_never_proposed_from_a_team_name(club):
    rows, _ = build_snapshot(_db(_team(1, "Boston Bolts U12", club, provider=TGS, state="MA")), {}, [])
    assert rows == []


def test_a_club_that_is_not_a_canonical_name_is_not_selected():
    rows, _ = build_snapshot(_db(_team(1, "Polonia SC U12", "Polonia SC", provider=TGS, state="IL")), {}, [])
    assert rows == []


def test_a_deprecated_team_is_not_selected():
    rows, _ = build_snapshot(_db(_team(1, "Oregon Surf GU11", "SURF", provider=TGS, deprecated=True)), {}, [])
    assert rows == []


def test_every_page_of_a_large_selection_is_read():
    teams = [_team(n, "Oregon Surf GU11", "SURF", provider=TGS) for n in range(1, 1501)]
    rows, _ = build_snapshot(_db(*teams), {}, [])
    assert len(rows) == 1500


def test_skipped_and_unclear_rows_are_counted():
    rows, stats = build_snapshot(
        _db(
            _team(1, "FC Dallas Red U14", "FC DALLAS"),
            _team(2, "Solar White U12", "Solar SC"),
            _team(3, "FC", "FC DALLAS", provider=SINC),
        ),
        {},
        [],
    )
    assert dict(stats["team_name_outcomes"]) == {"skip_prefix": 1, "skip_core": 1, "needs_review": 1}
    assert [(r["tier"], r["needs_review"], r["approved"]) for r in rows] == [("unclear", True, False)]


# --- the PlayMetrics source ------------------------------------------------------------


def test_playmetrics_own_club_replaces_the_swapped_one():
    team = _team(1, "NC Fusion U12 Blue", "VENTURA COUNTY FUSION", provider=PM, state="NC", provider_team_id="4321")
    rows, _ = build_snapshot(_db(team), {"4321": ("NC Fusion", "NC")}, [])

    assert [(r["proposed_club"], r["source"], r["tier"], r["approved"], r["state_note"]) for r in rows] == [
        ("NC Fusion", "playmetrics", "provider", True, "")
    ]


def test_a_playmetrics_club_the_cleanup_re_cased_is_still_repaired():
    team = _team(1, "CSA U12 Premier", "Charlotte FC", provider=PM, state="NC", provider_team_id="555")
    rows, _ = build_snapshot(_db(team), {"555": ("Charlotte Soccer Academy", "NC")}, [])
    assert [r["proposed_club"] for r in rows] == ["Charlotte Soccer Academy"]


def test_a_state_the_swapped_club_suggested_is_flagged():
    team = _team(1, "NC Fusion U12 Blue", "VENTURA COUNTY FUSION", provider=PM, state="CA", provider_team_id="4321")
    rows, _ = build_snapshot(_db(team), {"4321": ("NC Fusion", "NC")}, [])
    assert rows[0]["state_note"] == "stored state CA, league NC"


def test_a_playmetrics_team_no_league_lists_is_not_proposed():
    team = _team(1, "Oregon Surf GU11", "SURF", provider=PM, state="NC", provider_team_id="999")
    rows, stats = build_snapshot(_db(team), {"4321": ("NC Fusion", "NC")}, [])
    assert (rows, stats["playmetrics_unlisted"]) == ([], 1)


def test_another_providers_team_id_is_never_read_as_a_playmetrics_id():
    """Team ids are per provider, so a TGS 4321 is not the PlayMetrics 4321."""
    team = _team(1, "Oregon Surf GU11", "SURF", provider=TGS, provider_team_id="4321")
    rows, _ = build_snapshot(_db(team), {"4321": ("NC Fusion", "NC")}, [])
    assert [(r["source"], r["proposed_club"]) for r in rows] == [("team_name", "Oregon Surf")]


def test_a_playmetrics_club_that_already_matches_is_not_proposed():
    team = _team(1, "Bavarian United U12", "Bavarian United", provider=PM, state="WI", provider_team_id="7")
    rows, _ = build_snapshot(_db(team), {"7": ("Bavarian United", "WI")}, [])
    assert rows == []


def test_the_league_urls_parse_to_known_governing_bodies():
    assert parse_league_urls(repair.DEFAULT_LEAGUE_URLS) == [(1014, 2319, "3e2c725a"), (1207, 2289, "46ec05ca")]


@pytest.mark.parametrize(
    "url",
    ["https://playmetricssports.com/g/leagues/9999-1-abc/league_view.html", "https://example.com/not-a-league"],
)
def test_an_unusable_league_url_is_refused(url):
    with pytest.raises(ValueError):
        parse_league_urls([url])


def test_playmetrics_clubs_are_keyed_by_the_team_id_the_importer_stored():
    calls = []

    def league(gb_id, league_id, key):
        calls.append(("league", gb_id, league_id, key))
        return {"divisions": [{"id": 11}, {"id": None}, {"id": 12}]}

    def division(gb_id, league_id, key, division_id):
        calls.append(("division", division_id))
        return {
            11: {
                "teams": [
                    {"team": {"id": 4321, "name": "NC Fusion U12"}, "club": {"id": 7, "name": " NC Fusion "}},
                    {"team": {}, "club": {"name": "No Id FC"}},
                ]
            },
            12: {"teams": [{"team": {"id": 99}, "club": None}]},
        }[division_id]

    clubs = fetch_playmetrics_clubs([(1207, 2289, "46ec05ca")], league, division, delay=0)

    assert clubs == {"4321": ("NC Fusion", "NC"), "99": ("", "NC")}
    assert calls == [("league", 1207, 2289, "46ec05ca"), ("division", 11), ("division", 12)]


# --- the abbreviation source -----------------------------------------------------------


def test_a_lowered_abbreviation_word_is_kept():
    assert parse_cleanup_log(_line("CA", "JSC Soccer Club", "Jsc Soccer Club")) == [
        ("CA", "JSC Soccer Club", "Jsc Soccer Club", "word")
    ]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("SG1 Soccer", "Sg1 Soccer"),
        ("North Port Fusion FC/North Port YSA", "North Port Fusion Fc/north Port YSA"),
    ],
)
def test_capitals_lowered_inside_a_longer_word_are_kept(before, after):
    assert parse_cleanup_log(_line("TX", before, after)) == [("TX", before, after, "word")]


def test_a_lowered_bracketed_segment_is_kept():
    assert parse_cleanup_log(_line("AL", "Homewood Soccer Club (AL)", "Homewood Soccer Club (al)")) == [
        ("AL", "Homewood Soccer Club (AL)", "Homewood Soccer Club (al)", "bracket")
    ]


def test_a_rename_that_changed_more_than_case_is_dropped():
    """Violates (a) only: an abbreviation was lowered, the name was mixed case, but text changed."""
    assert parse_cleanup_log(_line("CA", "JSC Soccer Club", "Jsc Soccer Clubs")) == []


def test_a_rename_of_an_all_caps_name_is_dropped():
    """Violates (b) only: re-casing an all-caps name is the cleanup doing its job."""
    assert parse_cleanup_log(_line("AL", "JSC SOCCER CLUB", "Jsc Soccer Club")) == []


def test_a_rename_that_only_capitalised_lowercase_words_is_dropped():
    """Violates (c), and touches no word that held a capital: the cleanup doing its job."""
    assert parse_cleanup_log(_line("VA", "Chesapeake united sc", "Chesapeake United SC")) == []


def test_an_all_caps_bracket_the_rename_left_alone_is_not_a_lowered_bracket():
    assert parse_cleanup_log(_line("VA", "Chesapeake united sc (VA)", "Chesapeake United SC (VA)")) == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("McLean Youth Soccer", "Mclean Youth Soccer"),
        ("La Jolla Impact Soccer Club", "LA Jolla Impact Soccer Club"),
        ("Lincoln FC (Lincoln YSC/LYSC)", "Lincoln FC (lincoln Ysc/lysc)"),
    ],
)
def test_any_other_word_holding_a_capital_that_changed_case_is_kept_as_capital(before, after):
    assert parse_cleanup_log(_line("CA", before, after)) == [("CA", before, after, "capital")]


def test_a_no_state_line_reads_as_no_state():
    assert parse_cleanup_log(_line("NO_STATE", "Eastside FC (WA)", "Eastside FC (wa)")) == [
        (None, "Eastside FC (WA)", "Eastside FC (wa)", "bracket")
    ]


def test_lines_are_chosen_by_content_whatever_the_step_column_says():
    prefix = "Update Missing Club Names & State Codes\tUNKNOWN STEP\t2026-09-14T16:12:55Z "
    log = "\n".join(
        [
            _line("CA", "JSC Soccer Club", "Jsc Soccer Club", step="UNKNOWN STEP"),
            _line("TX", "PDA Blue SC", "Pda Blue SC", step="Step 3 - Standardize club names"),
            prefix + "✅ Dependencies installed",
            prefix + '  ❌ AL: "X FC" → error: boom',
            prefix + '  AL: "IMG SC" → "Img SC" (3 teams)',
        ]
    )
    assert [fix[:2] for fix in parse_cleanup_log(log)] == [("CA", "JSC Soccer Club"), ("TX", "PDA Blue SC")]


def test_an_abbreviation_rename_is_undone_for_every_live_team_in_its_state():
    log = _line("AL", "Homewood Soccer Club (AL)", "Homewood Soccer Club (al)")
    rows, stats = build_snapshot(
        _db(
            _team(1, "Homewood 2014 Blue", "Homewood Soccer Club (al)", provider=SINC, state="AL"),
            _team(2, "Homewood 2013 Red", "Homewood Soccer Club (al)", provider=GS, state="AL"),
            _team(3, "Homewood 2012", "Homewood Soccer Club (al)", provider=GS, state="GA"),
            _team(4, "Homewood 2011", "Homewood Soccer Club (al)", provider=GS, state="AL", deprecated=True),
            _team(5, "Homewood 2010", "HOMEWOOD SOCCER CLUB (AL)", provider=SINC, state="AL"),
        ),
        {},
        [log],
    )

    assert sorted((r["team_id_master"], r["proposed_club"], r["source"], r["tier"], r["approved"]) for r in rows) == [
        (_uuid(1), "Homewood Soccer Club (AL)", "abbreviation", "bracket", True),
        (_uuid(2), "Homewood Soccer Club (AL)", "abbreviation", "bracket", True),
    ]
    assert dict(stats["abbreviation_renames"]) == {"bracket": 1}


def test_a_capital_rename_is_listed_but_not_approved():
    log = _line("CA", "SoCal Reds", "Socal Reds")
    rows, stats = build_snapshot(_db(_team(1, "SoCal Reds 2014", "Socal Reds", state="CA")), {}, [log])

    assert [(r["proposed_club"], r["tier"], r["approved"]) for r in rows] == [("SoCal Reds", "capital", False)]
    assert dict(stats["abbreviation_renames"]) == {"capital": 1}


def test_a_no_state_rename_is_undone_for_null_and_empty_states_only():
    log = _line("NO_STATE", "Eastside FC (WA)", "Eastside FC (wa)")
    rows, _ = build_snapshot(
        _db(
            _team(1, "Eastside 2014", "Eastside FC (wa)", provider=SINC, state=None),
            _team(2, "Eastside 2013", "Eastside FC (wa)", provider=SINC, state=""),
            _team(3, "Eastside 2012", "Eastside FC (wa)", provider=SINC, state="WA"),
        ),
        {},
        [log],
    )
    assert sorted(r["team_id_master"] for r in rows) == [_uuid(1), _uuid(2)]


def test_a_rename_logged_by_two_runs_proposes_once():
    log = _line("CA", "JSC Soccer Club", "Jsc Soccer Club")
    rows, stats = build_snapshot(_db(_team(1, "JSC 2014", "Jsc Soccer Club", state="CA")), {}, [log, log])
    assert [(r["proposed_club"], r["approved"]) for r in rows] == [("JSC Soccer Club", True)]
    assert stats["conflicts"] == []


def test_two_sources_that_disagree_leave_the_team_for_review():
    """The team is re-cased "City Sc": team_name reads "Real Monarchs", the log "City SC"."""
    log = _line("UT", "City SC", "City Sc")
    rows, stats = build_snapshot(_db(_team(1, "Real Monarchs U12", "City Sc", provider=TGS, state="UT")), {}, [log])

    assert [(r["source"], r["proposed_club"], r["needs_review"], r["approved"]) for r in rows] == [
        ("team_name", "Real Monarchs", True, False)
    ]
    assert [(team_id, [p["proposed_club"] for p in offers]) for team_id, offers in stats["conflicts"]] == [
        (_uuid(1), ["Real Monarchs", "City SC"])
    ]


def test_a_conflict_withdraws_the_approval_of_the_first_proposal():
    """PlayMetrics proposes first and is approved by default; the log's lowered FC disagrees."""
    log = _line("NC", "Charlotte FC", "Charlotte Fc")
    team = _team(1, "CSA U12 Premier", "Charlotte Fc", provider=PM, state="NC", provider_team_id="555")
    rows, stats = build_snapshot(_db(team), {"555": ("Charlotte Soccer Academy", "NC")}, [log])

    assert [(r["source"], r["proposed_club"], r["needs_review"], r["approved"]) for r in rows] == [
        ("playmetrics", "Charlotte Soccer Academy", True, False)
    ]
    assert [(team_id, [p["proposed_club"] for p in offers]) for team_id, offers in stats["conflicts"]] == [
        (_uuid(1), ["Charlotte Soccer Academy", "Charlotte FC"])
    ]


def test_the_log_is_read_with_gh_as_utf8(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="log text")

    monkeypatch.setattr(repair.subprocess, "run", run)

    assert read_run_log("34866235667") == "log text"
    assert calls == [
        (["gh", "run", "view", "34866235667", "--log"], {"capture_output": True, "encoding": "utf-8", "check": True})
    ]


@pytest.mark.parametrize("run_id", ["--repo=evil/repo", "３４８６６", "", "123 456"])
def test_a_run_id_that_is_not_ascii_digits_is_refused(monkeypatch, run_id):
    monkeypatch.setattr(repair.subprocess, "run", lambda *a, **k: pytest.fail("gh must not be called"))
    with pytest.raises(ValueError):
        read_run_log(run_id)


def test_like_metacharacters_are_escaped():
    assert escape_like("50%_off*\\") == "50\\%\\_off\\*\\\\"


def test_a_star_in_a_canonical_name_is_never_a_wildcard(monkeypatch):
    monkeypatch.setattr(repair, "CANONICAL_CLUBS", {"SURF*": []})
    assert repair.fetch_canonical_holders(_db(_team(1, "Surfside FC U12", "SURFSIDE FC"))) == []


# --- the snapshot file -----------------------------------------------------------------


def _row(n, stored, proposed, *, approved=True, source="team_name", tier="swap", team_name="Oregon Surf GU11"):
    team = _team(n, team_name, stored)
    return snapshot_row(team, CODES, proposed, source, tier, approved=approved)


def test_a_defanged_name_round_trips_through_the_snapshot(tmp_path):
    path = tmp_path / "snapshot.csv"
    write_log([snapshot_csv_row(_row(1, "SURF", "=Oregon Surf", team_name="+Oregon Surf GU11"))], path)

    loaded = load_snapshot(path)

    assert (loaded[0]["team_name"], loaded[0]["proposed_club"]) == ("+Oregon Surf GU11", "=Oregon Surf")
    assert next(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))["proposed_club"] == "'=Oregon Surf"


def test_the_snapshot_opens_as_utf8_in_a_spreadsheet(tmp_path):
    path = tmp_path / "snapshot.csv"
    write_log([snapshot_csv_row(_row(1, "SURF", "Club Atlético Querétaro"))], path)

    assert path.read_bytes().startswith(b"\xef\xbb\xbfteam_id_master,")
    assert load_snapshot(path)[0]["proposed_club"] == "Club Atlético Querétaro"


def test_a_file_that_is_not_a_snapshot_is_refused(tmp_path):
    path = tmp_path / "other.csv"
    write_log([{"team_id_master": _uuid(1), "club_name": "X"}], path)
    with pytest.raises(ValueError, match="not a snapshot"):
        load_snapshot(path)


# --- the replay ------------------------------------------------------------------------


def _write_snapshot(tmp_path, *rows, edit=None):
    path = tmp_path / "snapshot.csv"
    csv_rows = [snapshot_csv_row(r) for r in rows]
    if edit:
        edit(csv_rows)
    write_log(csv_rows, path)
    return path


def _replay(monkeypatch, tmp_path, db, snapshot_path, execute=True):
    requested = []

    def get_supabase(require_service_role=False):
        requested.append(require_service_role)
        return db

    monkeypatch.setattr(repair, "get_supabase", get_supabase)
    monkeypatch.setattr(repair, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(repair, "timestamp", lambda: "20260918_120000")
    repair.replay_snapshot(snapshot_path, execute)
    log_path = tmp_path / "exports" / "repair_swapped_club_names_log_20260918_120000.csv"
    return list(csv.DictReader(log_path.open(encoding="utf-8-sig", newline=""))), requested, log_path


def test_an_approved_row_is_written_under_all_three_predicates(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log, requested, _ = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))

    assert _club(db, 1) == "Oregon Surf"
    assert _updates(db)[0]["filters"] == [
        ("eq", "team_id_master", _uuid(1)),
        ("eq", "is_deprecated", False),
        ("eq", "club_name", "SURF"),
    ]
    assert [(r["action"], r["before"], r["after"], r["run_mode"]) for r in log] == [
        ("updated", "SURF", "Oregon Surf", "execute")
    ]
    assert requested == [True]


def test_a_change_of_case_since_the_snapshot_is_accepted(monkeypatch, tmp_path):
    """The weekly cleanup re-cases "CHARLOTTE FC" to "Charlotte FC" where the team's state
    already holds that spelling."""
    db = _db(_team(1, "CSA U12", "Charlotte FC", provider=PM))
    snapshot = _write_snapshot(tmp_path, _row(1, "CHARLOTTE FC", "Charlotte Soccer Academy", source="playmetrics"))

    _replay(monkeypatch, tmp_path, db, snapshot)

    assert _club(db, 1) == "Charlotte Soccer Academy"
    assert ("eq", "club_name", "Charlotte FC") in _updates(db)[0]["filters"]


def test_a_text_change_since_the_snapshot_is_refused(monkeypatch, tmp_path):
    db = _db(_team(1, "CSA U12", "Charlotte FC Blue", provider=PM))
    snapshot = _write_snapshot(tmp_path, _row(1, "CHARLOTTE FC", "Charlotte Soccer Academy", source="playmetrics"))

    log, _, _ = _replay(monkeypatch, tmp_path, db, snapshot)

    assert _updates(db) == []
    assert _club(db, 1) == "Charlotte FC Blue"
    assert [r["action"] for r in log] == ["skipped_changed_since_snapshot"]


def test_a_team_merged_away_between_read_and_write_is_not_written(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    db.after_read.append(lambda table: db.tables["teams"][0].update(is_deprecated=True))

    log, _, _ = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))

    assert _club(db, 1) == "SURF"
    assert [r["action"] for r in log] == ["skipped_changed_since_read"]


def test_a_club_changed_between_read_and_write_is_not_overwritten(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    db.after_read.append(lambda table: db.tables["teams"][0].update(club_name="Oregon Surf SC"))

    log, _, _ = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))

    assert _club(db, 1) == "Oregon Surf SC"
    assert [r["action"] for r in log] == ["skipped_changed_since_read"]


def test_a_replay_larger_than_one_read_batch_writes_every_row(monkeypatch, tmp_path):
    db = _db(*[_team(n, "Oregon Surf GU11", "SURF") for n in range(1, 151)])
    snapshot = _write_snapshot(tmp_path, *[_row(n, "SURF", "Oregon Surf") for n in range(1, 151)])

    _replay(monkeypatch, tmp_path, db, snapshot)

    assert [t["club_name"] for t in db.tables["teams"]] == ["Oregon Surf"] * 150


def test_a_team_already_merged_away_is_not_read_or_written(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF", deprecated=True))
    log, _, _ = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))
    assert (_updates(db), [r["action"] for r in log]) == ([], ["skipped_missing"])


def test_a_team_whose_club_is_now_null_is_skipped(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", None))
    log, _, _ = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))
    assert (_updates(db), [r["action"] for r in log]) == ([], ["skipped_changed_since_snapshot"])


def test_a_second_replay_never_overwrites_the_first_ones_log(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    snapshot = _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf"))
    _, _, log_path = _replay(monkeypatch, tmp_path, db, snapshot)
    first = log_path.read_bytes()
    db.recorder.clear()

    with pytest.raises(ValueError, match="already exists"):
        _replay(monkeypatch, tmp_path, db, snapshot)

    assert (log_path.read_bytes(), db.recorder) == (first, [])


def test_only_approved_rows_are_written(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"), _team(2, "Sporting Wichita U16", "Sporting KC"))
    snapshot = _write_snapshot(
        tmp_path,
        _row(1, "SURF", "Oregon Surf"),
        _row(2, "Sporting KC", "Sporting Wichita", approved=False, tier="recased"),
    )

    _replay(monkeypatch, tmp_path, db, snapshot)

    assert (_club(db, 1), _club(db, 2)) == ("Oregon Surf", "Sporting KC")


def test_a_row_the_operator_approved_by_hand_is_written(monkeypatch, tmp_path):
    """A spreadsheet saves the edited cell as TRUE."""
    db = _db(_team(2, "Sporting Wichita U16", "Sporting KC"))

    def approve(rows):
        rows[0]["approved"] = "TRUE"

    snapshot = _write_snapshot(
        tmp_path, _row(2, "Sporting KC", "Sporting Wichita", approved=False, tier="recased"), edit=approve
    )
    _replay(monkeypatch, tmp_path, db, snapshot)

    assert _club(db, 2) == "Sporting Wichita"


@pytest.mark.parametrize(
    "column,value",
    [
        ("team_id_master", "not-a-uuid"),
        ("proposed_club", ""),
        ("proposed_club", "   "),
        ("proposed_club", "x" * 201),
        ("stored_club", ""),
    ],
)
def test_a_snapshot_row_not_shaped_like_ours_is_refused(monkeypatch, tmp_path, column, value):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))

    def spoil(rows):
        rows[0][column] = value

    snapshot = _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf"), edit=spoil)
    log, _, _ = _replay(monkeypatch, tmp_path, db, snapshot)

    assert (_updates(db), [r["action"] for r in log]) == ([], ["refused_shape"])


def test_a_preview_replay_writes_nothing_and_marks_its_log(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log, requested, _ = _replay(
        monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")), execute=False
    )

    assert _updates(db) == []
    assert [(r["run_mode"], r["action"]) for r in log] == [("dry-run", "updated")]
    assert requested == [False]


def test_the_log_is_on_disk_before_the_first_write(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    seen = []
    log_path = tmp_path / "exports" / "repair_swapped_club_names_log_20260918_120000.csv"
    db.before_update.append(lambda table: seen.append(log_path.exists()))

    _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))

    assert seen == [True]


def test_a_run_that_dies_mid_write_leaves_its_log(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))

    def boom(table):
        raise RuntimeError("connection reset")

    db.before_update.append(boom)
    with pytest.raises(RuntimeError):
        _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))

    log_path = tmp_path / "exports" / "repair_swapped_club_names_log_20260918_120000.csv"
    rows = list(csv.DictReader(log_path.open(encoding="utf-8-sig", newline="")))
    assert [(r["team_id_master"], r["before"], r["after"]) for r in rows] == [(_uuid(1), "SURF", "Oregon Surf")]


def test_a_run_that_dies_mid_loop_leaves_only_the_write_in_flight_revertible(monkeypatch, tmp_path):
    """The first write lands but its response is lost; the loop never reaches the other two,
    which another process then sets to the value the run would have written."""
    db = _db(*[_team(n, "Oregon Surf GU11", "SURF") for n in (1, 2, 3)])
    attempts = []

    def commit_then_lose_the_response(table):
        attempts.append(table)
        if len(attempts) == 1:
            db.tables["teams"][0]["club_name"] = "Oregon Surf"
            raise RuntimeError("connection reset")

    db.before_update.append(commit_then_lose_the_response)
    snapshot = _write_snapshot(tmp_path, *[_row(n, "SURF", "Oregon Surf") for n in (1, 2, 3)])
    with pytest.raises(RuntimeError):
        _replay(monkeypatch, tmp_path, db, snapshot)

    log_path = tmp_path / "exports" / "repair_swapped_club_names_log_20260918_120000.csv"
    rows = list(csv.DictReader(log_path.open(encoding="utf-8-sig", newline="")))
    assert [(r["team_id_master"], r["action"]) for r in rows] == [
        (_uuid(1), "updated"),
        (_uuid(2), "not_attempted"),
        (_uuid(3), "not_attempted"),
    ]

    for team in db.tables["teams"][1:]:
        team["club_name"] = "Oregon Surf"
    db.recorder.clear()
    counts = revert(db, log_path, execute=True)

    assert counts == {"reverted": 1, "refused_changed": 0, "refused_shape": 0}
    assert [u["filters"][0] for u in _updates(db)] == [("eq", "team_id_master", _uuid(1))]
    assert (_club(db, 1), _club(db, 2), _club(db, 3)) == ("SURF", "Oregon Surf", "Oregon Surf")


# --- the undo --------------------------------------------------------------------------


def _executed_log(monkeypatch, tmp_path, db):
    _, _, log_path = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))
    db.recorder.clear()
    return log_path


def test_revert_restores_the_club_under_all_three_predicates(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log_path = _executed_log(monkeypatch, tmp_path, db)

    counts = revert(db, log_path, execute=True)

    assert counts == {"reverted": 1, "refused_changed": 0, "refused_shape": 0}
    assert _club(db, 1) == "SURF"
    assert _updates(db)[0]["filters"] == [
        ("eq", "team_id_master", _uuid(1)),
        ("eq", "is_deprecated", False),
        ("eq", "club_name", "Oregon Surf"),
    ]


def test_revert_refuses_a_row_that_changed_since_the_run(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log_path = _executed_log(monkeypatch, tmp_path, db)
    db.tables["teams"][0]["club_name"] = "Oregon Surf SC"

    counts = revert(db, log_path, execute=True)

    assert counts == {"reverted": 0, "refused_changed": 1, "refused_shape": 0}
    assert _club(db, 1) == "Oregon Surf SC"


def test_revert_refuses_a_team_merged_away_since_the_run(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log_path = _executed_log(monkeypatch, tmp_path, db)
    db.tables["teams"][0]["is_deprecated"] = True

    assert revert(db, log_path, execute=True)["refused_changed"] == 1
    assert _club(db, 1) == "Oregon Surf"


def test_revert_restores_a_formula_leading_club(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "+SURF"))
    log, _, log_path = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "+SURF", "=Oregon Surf")))
    assert [(r["before"], r["after"]) for r in log] == [("'+SURF", "'=Oregon Surf")]
    db.recorder.clear()

    assert revert(db, log_path, execute=True) == {"reverted": 1, "refused_changed": 0, "refused_shape": 0}
    assert _club(db, 1) == "+SURF"


def test_revert_leaves_alone_a_row_the_run_did_not_write(monkeypatch, tmp_path):
    """Another process set the team to "Oregon Surf" between the replay's read and its
    write, so the compare-and-set skipped it; undoing it would erase that change."""
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    db.after_read.append(lambda table: db.tables["teams"][0].update(club_name="Oregon Surf"))
    log, _, log_path = _replay(monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")))
    assert [(r["action"], r["before"], r["after"]) for r in log] == [
        ("skipped_changed_since_read", "SURF", "Oregon Surf")
    ]
    db.recorder.clear()

    assert revert(db, log_path, execute=True) == {"reverted": 0, "refused_changed": 0, "refused_shape": 0}
    assert (_updates(db), _club(db, 1)) == ([], "Oregon Surf")


def test_revert_refuses_a_preview_log(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    _, _, log_path = _replay(
        monkeypatch, tmp_path, db, _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")), execute=False
    )
    with pytest.raises(ValueError, match="dry-run"):
        revert(db, log_path, execute=True)


def test_revert_refuses_a_snapshot(tmp_path):
    with pytest.raises(ValueError, match="not a log"):
        revert(_db(), _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf")), execute=True)


def test_revert_writes_nothing_without_execute(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log_path = _executed_log(monkeypatch, tmp_path, db)

    assert revert(db, log_path, execute=False)["reverted"] == 1
    assert (_updates(db), _club(db, 1)) == ([], "Oregon Surf")


def test_revert_refuses_a_log_row_not_shaped_like_ours(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log_path = _executed_log(monkeypatch, tmp_path, db)
    rows = list(csv.DictReader(log_path.open(encoding="utf-8-sig", newline="")))
    rows[0]["before"] = ""
    write_log(rows, log_path)

    assert revert(db, log_path, execute=True)["refused_shape"] == 1
    assert _updates(db) == []


# --- run control -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "execute_flag,dry_run_flag,expected", [(False, False, False), (True, False, True), (True, True, False)]
)
def test_asking_for_both_modes_yields_the_preview(execute_flag, dry_run_flag, expected):
    assert resolve_execute(execute_flag, dry_run_flag) is expected


def test_executing_needs_the_service_role_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "anon")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        repair.get_supabase(require_service_role=True)


def _run_main(monkeypatch, tmp_path, argv, db, logs=None, clubs=None):
    requested, leagues_seen, runs_seen = [], [], []

    def get_supabase(require_service_role=False):
        requested.append(require_service_role)
        return db

    def fetch_clubs(leagues):
        leagues_seen.extend(leagues)
        return clubs or {}

    def read_log(run_id):
        runs_seen.append(run_id)
        return (logs or {}).get(run_id, "")

    monkeypatch.setattr(repair, "load_env", lambda: None)
    monkeypatch.setattr(repair, "get_supabase", get_supabase)
    monkeypatch.setattr(repair, "fetch_playmetrics_clubs", fetch_clubs)
    monkeypatch.setattr(repair, "read_run_log", read_log)
    monkeypatch.setattr(repair, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(repair, "timestamp", lambda: "20260918_120000")
    monkeypatch.setattr(sys, "argv", ["repair_swapped_club_names.py", *argv])
    code = repair.main()
    return code, SimpleNamespace(requested=requested, leagues=leagues_seen, runs=runs_seen)


SNAPSHOT_NAME = "repair_swapped_club_names_20260918_120000.csv"


def test_the_dry_run_writes_a_snapshot_and_nothing_else(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11 PreECNL", "SURF", provider=M11, state="OR"))

    code, seen = _run_main(monkeypatch, tmp_path, [], db)

    assert code == 0
    assert _updates(db) == []
    assert seen.requested == [False]
    assert seen.leagues == [(1014, 2319, "3e2c725a"), (1207, 2289, "46ec05ca")]
    assert seen.runs == ["34866235667"]
    rows = list(csv.DictReader((tmp_path / "exports" / SNAPSHOT_NAME).open(encoding="utf-8-sig", newline="")))
    assert rows == [
        {
            "team_id_master": _uuid(1),
            "provider": "modular11",
            "state": "OR",
            "team_name": "Oregon Surf GU11 PreECNL",
            "stored_club": "SURF",
            "proposed_club": "Oregon Surf",
            "source": "team_name",
            "tier": "swap",
            "needs_review": "false",
            "approved": "true",
            "state_note": "",
        }
    ]


def test_every_abbreviation_run_named_is_read(monkeypatch, tmp_path):
    _, seen = _run_main(
        monkeypatch, tmp_path, ["--abbreviation-run", "34866235667", "--abbreviation-run", "35000000000"], _db()
    )
    assert seen.runs == ["34866235667", "35000000000"]


def test_the_dry_run_refuses_to_overwrite_a_snapshot(monkeypatch, tmp_path):
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports" / SNAPSHOT_NAME).write_text("reviewed", encoding="utf-8")

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, tmp_path, [], _db(_team(1, "Oregon Surf GU11", "SURF")))

    assert (tmp_path / "exports" / SNAPSHOT_NAME).read_text(encoding="utf-8") == "reviewed"


def test_execute_replays_the_snapshot_with_the_service_role(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    snapshot = _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf"))

    _, seen = _run_main(monkeypatch, tmp_path, ["--execute", str(snapshot)], db)

    assert seen.requested == [True]
    assert _club(db, 1) == "Oregon Surf"
    assert (seen.leagues, seen.runs) == ([], [])


def test_dry_run_wins_over_execute(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    snapshot = _write_snapshot(tmp_path, _row(1, "SURF", "Oregon Surf"))

    _, seen = _run_main(monkeypatch, tmp_path, ["--execute", str(snapshot), "--dry-run"], db)

    assert (_updates(db), seen.requested) == ([], [False])


@pytest.mark.parametrize("argv", [["--execute"], ["--revert", "log.csv", "--execute", "snapshot.csv"]])
def test_a_malformed_execute_is_refused(monkeypatch, tmp_path, argv):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, tmp_path, argv, db)
    assert db.recorder == []


def test_revert_from_the_command_line_needs_execute_to_write(monkeypatch, tmp_path):
    db = _db(_team(1, "Oregon Surf GU11", "SURF"))
    log_path = _executed_log(monkeypatch, tmp_path, db)

    _run_main(monkeypatch, tmp_path, ["--revert", str(log_path)], db)
    assert _club(db, 1) == "Oregon Surf"

    _, seen = _run_main(monkeypatch, tmp_path, ["--revert", str(log_path), "--execute"], db)
    assert (_club(db, 1), seen.requested) == ("SURF", [True])


def test_the_script_runs_the_way_the_operator_runs_it():
    """`python scripts/repair_swapped_club_names.py` puts scripts/ on sys.path rather than the
    repo root, so the bootstrap that reaches src/ and scripts/ is load-bearing there and
    inert under pytest."""
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "scripts/repair_swapped_club_names.py", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
