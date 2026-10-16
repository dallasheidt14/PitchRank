"""A birth-year band is one age token, and on the u19 board a bare 2008 names no single squad.

The three extract_team_variant copies each find an age token and read the next word as
the squad label. Their age patterns match one year of a band, so each widens its token
through age_token_span: "B2012/13 Riedell" reads "riedell", where a "/13" label
would never match the single-year spelling and would make two coaches' squads in one
band ("B2016/17 Rodriguez", "B2016/17 Gonzalez") read the same. The copy guard below
finds every function that loops over an age-pattern list and fails for one that does not
widen, apart from the readers it names as not yet widened.

U19 holds the 2009/08 and 2008/07 squads, so a name stating only 2008 fits both. The base
importer, the queue matcher, the event-team matcher and the unknown-opponent auto-match
send such a pairing to review rather than linking it.
"""

import ast
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from scripts import auto_match_unknown_opponents as amu
from scripts import find_queue_matches
from src.models import game_matcher
from src.models.game_matcher import GameHistoryMatcher
from src.tournaments.event_team_matcher import EventTeamSearchQuery, search_event_team_in_db
from src.utils import team_name_utils, team_utils
from src.utils.team_name_utils import age_token_span, u19_shared_year_ambiguous

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROVIDER = "33333333-3333-4333-8333-333333333333"
NO_ROWS = APIError({"code": "PGRST116", "message": "JSON object requested, multiple (or no) rows returned"})


@pytest.fixture(autouse=True)
def _pin_season(monkeypatch):
    """The shared u19 year moves every Aug 1. team_name_utils binds CURRENT_YEAR at import,
    so pinning team_utils alone does not reach the u19 rule."""
    monkeypatch.setattr(team_name_utils, "CURRENT_YEAR", 2026)
    monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2026)


@pytest.mark.parametrize(
    "name,matched,widened",
    [
        ("NTH NASA ECNL RL B2012/13", "B2012", "B2012/13"),
        ("Club 2013/2014 Riedell", "2013", "2013/2014"),
        ("Club 2009/08 Gold", "2009", "2009/08"),
        ("Club 2015/16B Jones", "2015", "2015/16B"),
        # Three years are one run; cutting it at two would leave "/15" as the label.
        ("Club B13/14/15 Smith", "B13", "B13/14/15"),
        ("Club B2007/08/09 Lee", "B2007", "B2007/08/09"),
        # The band can sit on either side of the matched token.
        ("Club 13/14G Smith", "14G", "13/14G"),
        # A U-led range is a U-age run, which the band grammar refuses.
        ("Club U11/12G Davis", "U11", "U11/12G"),
        ("Club U14/15 Ross", "U14", "U14/15"),
        # ...with or without the U repeated, in any mix.
        ("Boys U14/U15 Riedell", "U14", "U14/U15"),
        ("Rock SC Rush 15U/16U Smith", "15U", "15U/16U"),
        ("Club U14/U15/16 Smith", "U14", "U14/U15/16"),
        ("Club U14/15/U16 Smith", "U14", "U14/15/U16"),
        # ...spelled out, or with the U only after the last age.
        ("Club Under 14G/15 Riedell", "14G", "Under 14G/15"),
        ("Augusta Arsenal Under 13B NAL", "13B", "Under 13B"),
        ("Ames SC 13/14u Girls Yellow", "14u", "13/14u"),
        # No band or range around the token: it comes back as matched.
        ("FC Dynamo 2014 Davis", "2014", "2014"),
        ("Atletico Dallas 15G Riedell", "15G", "15G"),
        ("FC Example 14U Riedell", "14U", "14U"),
        # A band elsewhere in the name is not this token's.
        ("Club 2014 Riedell 2025-26", "2014", "2014"),
    ],
)
def test_age_token_span(name, matched, widened):
    start = name.index(matched)
    got_start, got_end = age_token_span(name, start, start + len(matched))
    assert name[got_start:got_end] == widened


@pytest.mark.parametrize(
    "name,matched,widened",
    [
        # A club number joined to a year is part of the club: glued to its letters...
        ("CF10 - 2013 White", "2013", "2013"),
        ("CF10 – 2013 White", "2013", "2013"),
        ("T11 - 2014B", "2014B", "2014B"),
        # ...or bare and naming no birth year.
        ("Extreme Touch 90 - 2012 PDL", "2012", "2012"),
        ("Team LA 59-62 - 2008", "2008", "2008"),
        # Whatever follows the club number is read whole: a band, a combined cohort, a year.
        ("T11 - 16/17B", "17B", "16/17B"),
        ("T11 - B2007/09 Riedell", "B2007", "B2007/09"),
        ("Extreme Touch 90 - '15B", "15B", "'15B"),
        # Glued to a letter, but consecutive years: a band.
        ("Nevada FC17-18G Elite", "18G", "17-18G"),
        # Glued, but led by a four-digit year: a combined cohort.
        ("Pikuni C2007-11 CL", "2007", "2007-11"),
        # Glued, but joined by a slash, which joins years and never a club number.
        ("Nevada FC13/15G Riedell", "15G", "13/15G"),
        # Glued, but written as a year: a gender letter after it, or an apostrophe.
        ("Nevada FC13B-15B Riedell", "15B", "13B-15B"),
        ("Nevada FC'07-09B Riedell", "09B", "'07-09B"),
        # Not glued, and the lead is a birth year: a combined cohort.
        ("Club B2007/09 Lee", "B2007", "B2007/09"),
        ("Club 13-15 Lee", "13", "13-15"),
        ("13-15 Club Lee", "13", "13-15"),
        # A gender letter on either side makes the lead a year, even one no birth year can be.
        ("Club G02-15 Lee", "G02", "G02-15"),
        ("Club 04B-07 Lee", "04B", "04B-07"),
    ],
)
def test_a_club_number_joined_to_a_year_is_not_a_band(name, matched, widened):
    start = name.index(matched)
    got_start, got_end = age_token_span(name, start, start + len(matched))
    assert name[got_start:got_end] == widened


def test_a_name_past_the_band_scan_limit_is_left_as_matched():
    name = "Club 2013/2014 Riedell " + "x" * 200
    assert age_token_span(name, 5, 9) == (5, 9)


_READERS = [
    pytest.param(find_queue_matches.extract_team_variant, id="find_queue_matches"),
    pytest.param(game_matcher.extract_team_variant, id="game_matcher"),
    pytest.param(team_name_utils.extract_team_variant, id="team_name_utils"),
]


@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize(
    "name,expected",
    [
        ("NASA ECNL RL B2012/13", None),
        ("Club G2014/15 Premier", None),
        ("Club 2013/2014 Riedell", "riedell"),
        ("FC Dallas Youth Pre-ECNL B2016/17 Rodriguez", "rodriguez"),
        ("Club B13/14/15 Smith", "smith"),
        ("Club 2015/16B Jones", "jones"),
        ("Club U11/12G Davis", "davis"),
        ("PT U11/U12G Edmunds", "edmunds"),
        ("Club U14/U15/16 Smith", "smith"),
        ("Club B2007/08/09 Lee", "lee"),
        ("Club Under 14G/15 Riedell", "riedell"),
        # The age token opens the name, so the label is read from the token's end.
        ("2014 Riedell Premier", "riedell"),
        ("B2012/13 Riedell Premier", "riedell"),
    ],
)
def test_every_reader_reads_the_label_after_the_whole_band(reader, name, expected):
    assert reader(name) == expected


@pytest.mark.parametrize(
    "name", ["Riedell Davis 13/14G", "Riedell Davis 14G", "Riedell Davis 2014", "Riedell Davis Under 14G"]
)
def test_the_queue_reader_takes_the_same_word_before_a_band_as_before_a_single_year(name):
    """Only this copy reads the words before the age; it reads them up to the band's start."""
    assert find_queue_matches.extract_team_variant(name) == "riedell"


_CLUB_EXTRACTORS = [
    pytest.param(find_queue_matches.extract_club_from_name, id="find_queue_matches"),
    pytest.param(game_matcher.extract_club_from_team_name, id="game_matcher"),
    pytest.param(team_name_utils.extract_club_from_team_name, id="team_name_utils"),
]


@pytest.mark.parametrize("extract", _CLUB_EXTRACTORS)
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Texas Premier SC 13/14B", "Texas Premier SC"),
        ("Portage SC 14/15B Yellow", "Portage SC"),
        ("Nevada FC 17/18G Elite", "Nevada FC"),
        ("Nevada FC13/15G Riedell", "Nevada FC"),
        ("Club B2012/13 Riedell", "Club"),
        ("Phoenix Rising FC B2014 Black", "Phoenix Rising FC"),
        ("Ames SC 13/14u Girls Yellow", "Ames SC"),
        ("Augusta Arsenal Under 13B NAL", "Augusta Arsenal"),
    ],
)
def test_every_club_extractor_cuts_at_the_start_of_the_whole_band(extract, name, expected):
    assert extract(name) == expected


@pytest.mark.parametrize("extract", _CLUB_EXTRACTORS)
@pytest.mark.parametrize(
    "name,expected",
    [
        ("CF10 - 2013 White", "CF10"),
        ("T11 - 2014B", "T11"),
        ("T11 - 16/17B", "T11"),
        ("T11 - B2007/09 Riedell", "T11"),
        ("SSE90 - 2017 -Girls", "SSE90"),
        ("Wave Riders - R64-14B-SELECT", "Wave Riders - R64"),
        ("Extreme Touch 90 - 2012 PDL", "Extreme Touch 90"),
        ("Extreme Touch 90 - '15B", "Extreme Touch 90"),
        ("Team LA 59-62 - 2008", "Team LA 59-62"),
    ],
)
def test_every_club_extractor_keeps_a_club_number_joined_to_a_year(extract, name, expected):
    assert extract(name) == expected


@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("name", ["T11 - B2007/09 Riedell", "Club 04B/07B Riedell"])
def test_every_reader_reads_the_label_after_a_combined_cohort(reader, name):
    assert reader(name) == "riedell"


@pytest.mark.parametrize("name", ["Chelsea SC B2014/15 OG", "Chelsea SC B2015 OG"])
def test_the_program_tier_reads_the_branch_after_a_band_as_after_a_single_year(name):
    assert find_queue_matches.extract_program_tier(name) == "og"


# --------------------------------------------------------------------------- #
# Every age reader widens its token
# --------------------------------------------------------------------------- #

# Readers that still cut inside a band. Each needs widening; drop it from here when it is.
_NOT_YET_WIDENED = {"scripts/extract_missing_club_names.py::extract_club_name"}


def _loops_over_age_patterns(func):
    """A reader finds its age token by looping over a list of age patterns, whatever the function is called."""
    for node in ast.walk(func):
        if isinstance(node, ast.For):
            name = getattr(node.iter, "id", None) or getattr(node.iter, "attr", "")
            if "age" in name.lower() and "pattern" in name.lower():
                return True
    return False


def _age_readers(root):
    """Every age reader defined under scripts/ and src/, and whether it widens its token."""
    found = {}
    for path in list(root.glob("scripts/**/*.py")) + list(root.glob("src/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _loops_over_age_patterns(node):
                calls = {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                found[f"{path.relative_to(root).as_posix()}::{node.name}"] = "age_token_span" in calls
    return found


def test_the_reader_search_actually_fires(tmp_path):
    (tmp_path / "scripts" / "nested").mkdir(parents=True)
    (tmp_path / "scripts" / "stale.py").write_text(
        "def club_of(name):\n    for pattern in AGE_PATTERNS:\n        pass\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "nested" / "stale.py").write_text(
        "def read(name):\n    for p in self._VARIANT_AGE_PATTERNS:\n        pass\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "current.py").write_text(
        "def label(name):\n    for p in age_patterns:\n        age_token_span(name, 0, 1)\n"
        "def colors(name):\n    for p in COLOR_WORDS:\n        pass\n",
        encoding="utf-8",
    )

    assert _age_readers(tmp_path) == {
        "scripts/stale.py::club_of": False,
        "scripts/nested/stale.py::read": False,
        "scripts/current.py::label": True,
    }


def test_the_reader_search_finds_the_known_copies():
    assert {
        "scripts/extract_missing_club_names.py::extract_club_name",
        "scripts/find_queue_matches.py::extract_team_variant",
        "scripts/find_queue_matches.py::extract_club_from_name",
        "scripts/find_queue_matches.py::extract_program_tier",
        "src/models/game_matcher.py::extract_team_variant",
        "src/models/game_matcher.py::extract_club_from_team_name",
        "src/utils/team_name_utils.py::extract_team_variant",
        "src/utils/team_name_utils.py::extract_club_from_team_name",
    } <= set(_age_readers(PROJECT_ROOT))


def test_every_reader_widens_its_age_token():
    stale = sorted(
        rel for rel, widens in _age_readers(PROJECT_ROOT).items() if not widens and rel not in _NOT_YET_WIDENED
    )
    assert not stale, f"these read a band's tail as the squad label; call age_token_span: {stale}"


def test_the_readers_not_yet_widened_still_are_not():
    """Fails once one is widened, so it comes off the list instead of hiding a later relapse."""
    readers = _age_readers(PROJECT_ROOT)
    assert {rel: readers.get(rel) for rel in _NOT_YET_WIDENED} == dict.fromkeys(_NOT_YET_WIDENED, False)


# --------------------------------------------------------------------------- #
# The year both u19 squads share
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name_a,name_b,age_group,season,expected",
    [
        ("X 2008", "X B08/07", "u19", 2026, True),
        ("X 2008", "X 2009/08", "u19", 2026, True),
        ("X 2008", "X B08/07", "U19", 2026, True),
        # A band joined by an en dash or written with mixed widths states both years.
        ("X 2008", "X B08–09", "u19", 2026, True),
        ("X 2008", "X 09/2008", "u19", 2026, True),
        # A U-age range is not a band, however it is spaced.
        ("X 2008 U 18/19", "X B08/07", "u19", 2026, True),
        # A band glued to a letter, which birth_years leaves unread, still states the band.
        ("X 2008", "X M08/09", "u19", 2026, True),
        ("X 2008", "X 07/08F", "u19", 2026, True),
        ("X 2008", "X 08B/09", "u19", 2026, True),
        # A number beside the year is not a band, so the name still states only 2008.
        ("X Elite 11 - 2008", "X B08/07", "u19", 2026, True),
        ("X 18/19U 2008", "X B08/07", "u19", 2026, True),
        # A season written into the name is not a birth year.
        ("X 2008 2025-26", "X B08/07", "u19", 2026, True),
        # U18 files into the u19 board.
        ("X 2008", "X B08/07", "u18", 2026, True),
        # The shared year moves with the season.
        ("X 2009", "X 2009/08", "u19", 2027, True),
        ("X 2008", "X B08/07", "u19", 2027, False),
        # 2009 sits only in 2009/08 this season, so it names one squad.
        ("X 2009", "X 2009/08", "u19", 2026, False),
        # Same label on both sides, two bands, or no year: nothing for this rule to say.
        ("X 2008", "X 2008", "u19", 2026, False),
        ("X B08/07", "X 2009/08", "u19", 2026, False),
        ("X B08–09", "X 2009/08", "u19", 2026, False),
        ("X U19", "X B08/07", "u19", 2026, False),
        # A band without the shared year is a plain conflict, not this ambiguity.
        ("X 2008", "X 2009/10", "u19", 2026, False),
        # Every other board holds one squad per band.
        ("X 2014", "X 2013/14", "u13", 2026, False),
        ("X 2008", "X B08/07", None, 2026, False),
    ],
)
def test_u19_shared_year_ambiguous(name_a, name_b, age_group, season, expected):
    assert u19_shared_year_ambiguous(name_a, name_b, age_group, season) is expected
    assert u19_shared_year_ambiguous(name_b, name_a, age_group, season) is expected


# --------------------------------------------------------------------------- #
# A database double that filters like PostgREST
# --------------------------------------------------------------------------- #


def _like(value, pattern, ignore_case):
    if value is None:
        return False
    regex = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern)
    return re.fullmatch(regex, str(value), re.I if ignore_case else 0) is not None


def _clause(row, field, op, value):
    if op == "is" and value == "null":
        return row.get(field) is None
    if op == "eq":
        return str(row.get(field)) == value
    if op == "neq":
        return row.get(field) is not None and str(row.get(field)) != value
    raise AssertionError(f"filter the double does not model: {field}.{op}.{value}")


# The live teams columns (information_schema, 2026-10-16). PostgREST refuses a select naming
# any other, so the double does too.
_TEAMS_COLUMNS = frozenset(
    "age_group birth_year club_name created_at distinction game_row_count gender id is_deprecated"
    " last_fixture_at last_played_at last_scraped_at league provider_id provider_team_id"
    " scrape_attempts state state_assigned_at state_code state_confidence state_source"
    " team_id_master team_name team_name_original updated_at".split()
)


class _Query:
    """Applies its filters, returns only the selected columns, and records at execute();
    refuses a column the teams table lacks and a review row the table's CHECK refuses."""

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.payload, self.single_row, self.cap = "select", None, False, None
        self.tests, self._negate, self.columns, self.window = [], False, None, None

    @property
    def not_(self):
        self._negate = True
        return self

    def _add(self, test):
        negate, self._negate = self._negate, False
        self.tests.append((lambda row: not test(row)) if negate else test)
        return self

    def select(self, *columns, **_k):
        names = [name.strip() for arg in columns for name in arg.split(",")]
        self.columns = None if names in ([], ["*"]) else names
        return self

    def eq(self, field, value):
        return self._add(lambda row: row.get(field) == value)

    def is_(self, field, value):
        assert value == "null", value
        return self._add(lambda row: row.get(field) is None)

    def like(self, field, pattern):
        return self._add(lambda row: _like(row.get(field), pattern, False))

    def ilike(self, field, pattern):
        return self._add(lambda row: _like(row.get(field), pattern, True))

    def or_(self, expression):
        clauses = [clause.split(".", 2) for clause in expression.split(",")]
        return self._add(lambda row: any(_clause(row, *clause) for clause in clauses))

    def limit(self, n):
        self.cap = n
        return self

    def range(self, start, end):
        self.window = (start, end + 1)
        return self

    def single(self):
        self.single_row = True
        return self

    def insert(self, data):
        self.op, self.payload = "insert", data
        return self

    def execute(self):
        unknown = sorted(set(self.columns or ()) - _TEAMS_COLUMNS) if self.table == "teams" else []
        if unknown:
            raise APIError({"code": "42703", "message": f"column teams.{unknown[0]} does not exist"})
        if self.table == "team_match_review_queue" and self.op == "insert":
            # The column is DECIMAL(3,2), rounded to its scale before the table's CHECK
            # (confidence_range): 0.75 <= confidence_score < 0.90.
            stored = Decimal(str(self.payload["confidence_score"])).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if stored.is_nan() or not Decimal("0.75") <= stored < Decimal("0.90"):
                raise RuntimeError('violates check constraint "confidence_range"')
        self.db.executed.append((self.table, self.op, self.payload))
        if self.op != "select":
            return SimpleNamespace(data=[self.payload])
        rows = [row for row in self.db.rows.get(self.table, []) if all(test(row) for test in self.tests)]
        if self.columns is not None:
            rows = [{name: row.get(name) for name in self.columns} for row in rows]
        rows = rows[slice(*self.window)] if self.window is not None else rows
        rows = rows[: self.cap] if self.cap is not None else rows
        if self.single_row:
            if len(rows) != 1:
                raise NO_ROWS
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, teams=()):
        self.rows = {
            "providers": [{"id": PROVIDER, "code": "gotsport"}],
            "teams": list(teams),
            "team_alias_map": [],
            "team_match_review_queue": [],
        }
        self.executed = []

    def table(self, name):
        return _Query(self, name)

    def writes(self, table):
        return [payload for t, op, payload in self.executed if t == table and op == "insert"]


def test_the_double_refuses_a_column_the_teams_table_lacks():
    with pytest.raises(APIError):
        _DB().table("teams").select("team_id_master,no_such_column").execute()


def _team(name, age_group, team_id="m1"):
    return {
        "id": 1,
        "team_id_master": team_id,
        "team_name": name,
        "club_name": "Club",
        "gender": "Male",
        "age_group": age_group,
        "state_code": "GA",
        "is_deprecated": False,
    }


# --------------------------------------------------------------------------- #
# The importers' accept path
# --------------------------------------------------------------------------- #


def _match(monkeypatch, provider_name, candidate_name, age_group, confidence=0.95):
    db = _DB()
    matcher = GameHistoryMatcher(db, provider_id=PROVIDER)
    monkeypatch.setattr(
        matcher,
        "_fuzzy_match_team",
        lambda *a, **k: {"team_id": "m1", "team_name": candidate_name, "confidence": confidence},
    )
    result = matcher._match_team(PROVIDER, "p1", provider_name, age_group, "Male")
    return db, result


def test_a_bare_2008_against_a_u19_band_goes_to_review(monkeypatch):
    db, result = _match(monkeypatch, "Club ECNL 2008", "Club ECNL B08/07", "u19")

    assert result["method"] == "fuzzy_review"
    assert db.writes("team_alias_map") == []
    assert [r["confidence_score"] for r in db.writes("team_match_review_queue")] == [0.89]


def test_the_same_shape_on_another_board_still_links(monkeypatch):
    """The contrast case, so the test above cannot pass by breaking auto-linking outright."""
    db, result = _match(monkeypatch, "Club ECNL 2014", "Club ECNL 2013/14", "u13")

    assert result["method"] == "fuzzy_auto"
    assert [a["team_id_master"] for a in db.writes("team_alias_map")] == ["m1"]
    assert db.writes("team_match_review_queue") == []


def test_a_demoted_high_score_is_queued_below_the_tables_ceiling(monkeypatch):
    """A birth-year conflict keeps its 0.95 score, above the CHECK's 0.90 ceiling."""
    db, result = _match(monkeypatch, "EPIC SC 2008 Dash", "EPIC SC 2009 Dash", "u19")

    assert result["method"] == "fuzzy_review"
    assert [r["confidence_score"] for r in db.writes("team_match_review_queue")] == [0.89]


# --------------------------------------------------------------------------- #
# The review-queue matcher
# --------------------------------------------------------------------------- #


def _queue_entry(name, stored_candidates=()):
    return {
        "provider_team_name": name,
        "match_details": {"club_name": "Club", "gender": "male", "candidates": list(stored_candidates)},
    }


def test_the_queue_matcher_skips_a_bare_2008_against_a_u19_band():
    db = _DB([_team("Club ECNL B08/07", "u19")])
    assert find_queue_matches.find_best_match(_queue_entry("Club ECNL 2008"), db, None) == (
        None,
        0.0,
        "low_confidence",
    )


def test_the_queue_matcher_still_matches_on_the_u19_board():
    """The contrast case: on other boards this matcher already refuses a band against a
    single year, so the u19 board is where this rule decides."""
    db = _DB([_team("Club ECNL 2008", "u19")])
    match, score, method = find_queue_matches.find_best_match(_queue_entry("Club ECNL 2008"), db, None)
    assert (match["team_id_master"], score, method) == ("m1", 1.0, "fuzzy")


def test_the_queue_matcher_passes_over_an_ambiguous_band_to_the_next_candidate():
    """The band listed first is skipped, not the end of the search."""
    db = _DB([_team("Club ECNL B08/07", "u19", "m-band"), _team("Club ECNL 2008", "u19", "m-right")])
    match, score, method = find_queue_matches.find_best_match(_queue_entry("Club ECNL 2008"), db, None)
    assert (match["team_id_master"], score, method) == ("m-right", 1.0, "fuzzy")


def _club_omitted_entry():
    return {
        "provider_team_name": "Futuro - B13/14",
        "match_details": {"club_name": "", "gender": "male", "candidates": []},
    }


def test_the_queue_matcher_reads_past_a_club_the_stored_name_omits():
    """With nothing after the band, the queue name's last words are its club; a stored name
    under that club that leaves the club out is the same squad, not a different label."""
    db = _DB([{**_team("B13/14", "u13"), "club_name": "Futuro"}])
    match, score, method = find_queue_matches.find_best_match(_club_omitted_entry(), db, None)
    assert match["team_id_master"] == "m1"


def test_the_queue_matcher_still_refuses_another_squad_of_that_club():
    """The contrast case: reading past the club leaves the squad label to compare."""
    db = _DB([{**_team("B13/14 Blue", "u13"), "club_name": "Futuro"}])
    assert find_queue_matches.find_best_match(_club_omitted_entry(), db, None)[0] is None


def _stored(name, age_group):
    return {**_team(name, age_group), "score": 0.97, "age_match_kind": "search_age_exact"}


def test_the_stored_tiebreak_refuses_a_bare_2008_against_a_u19_band():
    entry = _queue_entry("Club ECNL 2008", [_stored("Club ECNL B08/07", "u19")])
    assert find_queue_matches.resolve_via_stored_candidates(entry) == (None, 0.0, None)


def test_the_stored_tiebreak_still_resolves_the_same_shape_on_another_board():
    entry = _queue_entry("Club ECNL 2014", [_stored("Club ECNL 2013/14", "u13")])
    match, score, method = find_queue_matches.resolve_via_stored_candidates(entry)
    assert (match["team_id_master"], score, method) == ("m1", 0.97, "stored_tiebreak:sole_strong_candidate")


# --------------------------------------------------------------------------- #
# The event-team matcher
# --------------------------------------------------------------------------- #


def _event_search(event_name, candidate, age_group, provider_team_id=None, club="Club"):
    """Drives the whole search, so the candidate goes through the fetch's own select."""
    query = EventTeamSearchQuery(
        event_team_name=event_name,
        event_age_group=age_group,
        event_gender="Male",
        event_club_name=club,
        provider_team_id=provider_team_id,
    )
    return search_event_team_in_db(_DB([candidate]), query)


def _event_status(event_name, candidate, age_group, provider_team_id=None):
    return _event_search(event_name, candidate, age_group, provider_team_id).resolved_status


def test_the_event_matcher_reviews_a_bare_2008_against_a_u19_band():
    assert _event_status("Club ECNL 2008", _team("Club ECNL B08/07", "u19"), "u19") == "review"


def test_the_event_matcher_still_accepts_the_same_shape_on_another_board():
    assert _event_status("Club ECNL 2014", _team("Club ECNL 2013/14", "u13"), "u13") == "high_confidence"


def test_the_event_matcher_leaves_a_weak_u19_pairing_unmatched():
    """Only a link the score earned is held for review; a weak pairing stays unmatched."""
    candidate = {**_team("Northgate Strikers SC B08/07", "u19"), "club_name": "Northgate Strikers SC"}
    result = _event_search("Westside Eagles 2008", candidate, "u19", club=None)
    assert (result.resolved_status, result.best_score) == ("none", 0.479)


def test_the_event_matcher_still_links_a_provider_id_match_on_the_shared_year():
    """The provider's own id names the squad, so the shared year leaves nothing to decide."""
    candidate = {**_team("Club ECNL B08/07", "u19"), "provider_team_id": "12345"}
    assert _event_status("Club ECNL 2008", candidate, "u19", provider_team_id="12345") == "direct_provider_id"


# --------------------------------------------------------------------------- #
# The unknown-opponent auto-match
# --------------------------------------------------------------------------- #


def _classify(monkeypatch, unknown_name, candidates, age_group):
    monkeypatch.setattr(amu, "fetch_candidates", lambda **_k: list(candidates))
    row = {
        "provider_code": "gotsport",
        "unknown_team_name": unknown_name,
        "unknown_club_name": "Club",
        "unknown_age": age_group,
        "unknown_gender": "Male",
    }
    return amu.match_row(row, None, None, False, 10, 0.95, 0.90, {})["action"]


def test_the_auto_match_reviews_a_bare_2008_against_a_u19_band(monkeypatch):
    assert _classify(monkeypatch, "Club ECNL 2008", [_team("Club ECNL B08/07", "u19")], "u19") == "review"


def test_the_auto_match_still_links_the_same_shape_on_another_board(monkeypatch):
    assert _classify(monkeypatch, "Club ECNL 2014", [_team("Club ECNL 2013/14", "u13")], "u13") == "auto_link"


def test_the_auto_match_leaves_a_weak_u19_pairing_unmatched(monkeypatch):
    """Only an automatic link is demoted; a score below review stays a no-match."""
    assert _classify(monkeypatch, "Westside Club ECNL 2008", [_team("Club ECNL B08/07", "u19")], "u19") == "no_match"


def test_the_auto_match_with_no_candidate_is_a_no_match(monkeypatch):
    assert _classify(monkeypatch, "Club ECNL 2008", [], "u19") == "no_match"
