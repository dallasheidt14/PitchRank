"""Unit tests for the Athletes2Events matcher.

The database double records at ``execute()``, applies the ``or_`` state filter and
the ``order`` it is given, and refuses review rows the table's CHECK refuses.

It differs from the Soccer Events Group double on one point, deliberately: a
zero-row ``.single()`` **raises** ``APIError(PGRST116)`` here, as postgrest does.
That is the normal path for the pre-create existence check on a team this run has
never seen, so a double that returns ``None`` instead is more permissive than
production on exactly the line that would crash every team creation.
"""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from scripts import import_athletes2events_event as a2e_import
from src.models import athletes2events_matcher as a2em
from src.models.athletes2events_matcher import Athletes2EventsGameMatcher
from src.models.tournament_name_gates import canonical_team_name, squad_numbers
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher

PROVIDER = "22222222-2222-4222-8222-222222222222"
SOMSPORTS = "somsports.athletes2events.com"
CROSSFIRE = "crossfire.athletes2events.com"
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
            "providers": [{"id": PROVIDER, "code": "athletes2events"}],
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


def _matcher(db, registration_mode=True, dry_run=False):
    return Athletes2EventsGameMatcher(db, provider_id=PROVIDER, registration_mode=registration_mode, dry_run=dry_run)


def _register(matcher, name="XF B13 RCL1", state_code="WA", a2e_id="10186", age_group="u13", gender="Male"):
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=a2e_id,
        team_name=name,
        age_group=age_group,
        gender=gender,
        state_code=state_code,
    )


def _register_with_club(matcher, name, club, age_group, state_code, gender="Male", written=None, a2e_id="13000"):
    """Register a team as the roster pass does, with the club it is filed under and the club as written."""
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=a2e_id,
        team_name=name,
        age_group=age_group,
        gender=gender,
        club_name=club,
        state_code=state_code,
        written_club=written or club,
    )


def _register_split(matcher, name, age_group, state_code, gender="Male", host=SOMSPORTS, a2e_id="13000"):
    """Register a team with its club split the way the roster pass splits it."""
    club, written = a2e_import.split_club(name, host, stop=a2e_import._A2E_CLUB_STOP)
    return _register_with_club(
        matcher, name, club, age_group, state_code, gender=gender, written=written, a2e_id=a2e_id
    )


def _without_rules(matcher):
    matcher.athletes2events_rules = False
    return matcher


def _athletes2events_family():
    """The Athletes2Events matcher and every class built on it, found by importing each matcher module."""
    for path in sorted(Path(a2em.__file__).parent.glob("*.py")):
        if not path.stem.startswith("_"):
            importlib.import_module(f"src.models.{path.stem}")
    found, todo = {}, [Athletes2EventsGameMatcher]
    while todo:
        cls = todo.pop()
        if cls.__module__.startswith("src.models."):
            found[cls.__name__] = cls
        todo.extend(cls.__subclasses__())
    return found


def _candidate(team_id, team_name, club_name, age_group="u13", state_code="WA", gender="Male"):
    return {
        "team_id_master": team_id,
        "team_name": team_name,
        "club_name": club_name,
        "age_group": age_group,
        "gender": gender,
        "state_code": state_code,
    }


class TestPresplit:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("XF RCL 1", "XF RCL1"),
            ("XF RCL-1", "XF RCL1"),
            ("XF RCL1", "XF RCL1"),
            ("XF RCL 12", "XF RCL12"),
            ("Crossfire ECNL2", "Crossfire ECNL 2"),
            ("Crossfire ECNL-2", "Crossfire ECNL 2"),
            ("Crossfire ENCL B13", "Crossfire ECNL B13"),
            ("XF B-U10B", "XF U10 B"),
            ("XF GU10A", "XF U10 A"),
            ("XF BU9C", "XF U9 C"),
            ("XF B15C", "XF B15 C"),
            ("XF G14B", "XF G14 B"),
            ("XF B2017C", "XF B2017 C"),
        ],
    )
    def test_the_platforms_glued_marks_are_split(self, raw, expected):
        assert a2em._presplit(raw) == expected

    @pytest.mark.parametrize("raw", ["XF RCL 1", "XF B-U10B", "Crossfire ECNL2", "XF B15C"])
    def test_presplitting_twice_changes_nothing(self, raw):
        """The gates canonicalise a name more than once; a second pass must be a no-op."""
        once = a2em._presplit(raw)

        assert a2em._presplit(once) == once


class TestSquadMarks:
    @staticmethod
    def _conflict(provider, candidate, club=None):
        """Strips one club from both names, standing in for the loop's strip of an agreeing club.

        ``club`` is given where the shared club extractor would otherwise swallow a
        squad label into the club, which is not what the matcher does: there the club
        comes from the team page's own split.
        """
        club = club if club is not None else a2em.club_from_team_name(provider, a2em._presplit)
        return a2em.squads_conflict(
            a2em._squad_marks(a2em.without_club(a2em.canonical_team_name(provider, a2em._presplit), club)),
            a2em._squad_marks(a2em.without_club(a2em.canonical_team_name(candidate, a2em._presplit), club)),
        )

    def test_a_standalone_letter_is_a_squad_code(self):
        assert a2em._squad_marks("U10 B")["squad_codes"] == frozenset({"squad-b"})

    def test_an_rcl_label_is_a_squad_code(self):
        assert a2em._squad_marks("RCL1 B13")["squad_codes"] == frozenset({"rcl1"})

    def test_a_letter_glued_to_the_birth_year_is_a_squad_code(self):
        assert a2em._squad_marks("B15C Red")["squad_codes"] == frozenset({"squad-c"})

    @pytest.mark.parametrize(
        "provider, candidate",
        [
            ("XF B-U10B", "XF U10 A"),
            ("XF RCL 1 B13", "XF RCL2 B13"),
            ("XF ECNL2 B13", "XF ECNL 1 B13"),
        ],
    )
    def test_different_squad_codes_conflict(self, provider, candidate):
        assert self._conflict(provider, candidate, club="XF") is True

    @pytest.mark.parametrize(
        "provider, candidate",
        [
            ("XF RCL 1 B13", "XF RCL-1 B13"),
            ("XF RCL 1 B13", "XF RCL1 B13"),
            ("XF ECNL2 B13", "XF ECNL 2 B13"),
            ("XF ENCL 2 B13", "XF ECNL 2 B13"),
            ("XF B-U10B", "XF GU10B"),
        ],
    )
    def test_spellings_of_one_squad_agree(self, provider, candidate):
        assert self._conflict(provider, candidate, club="XF") is False

    def test_a_one_sided_squad_code_is_no_evidence(self):
        """A squad code carried by one name only is not evidence either way."""
        assert self._conflict("XF B13 Red", "XF B13 RCL1 Red", club="XF") is False

    def test_a_tier_the_shared_set_omits_still_separates_two_squads(self):
        """EA and Aspire are not in the shared tier set, so they arrive via the provider's own."""
        assert self._conflict("WW Surf BU13 Academy EA Blue", "WW Surf BU13 Academy Blue") is True
        assert self._conflict("Seattle Celtic G14 GA Aspire", "Seattle Celtic G14 GA") is True

    @pytest.mark.parametrize(
        "short, spelled, direction",
        [
            ("SW", "Southwest", "southwest"),
            ("NW", "Northwest", "northwest"),
            ("NE", "Northeast", "northeast"),
            ("SE", "Southeast", "southeast"),
        ],
    )
    def test_a_spelled_compound_direction_reads_as_its_abbreviation_when_asked(self, short, spelled, direction):
        abbreviated = a2em._squad_marks(f"ECNL RL {short} Girls U14", spelled_compounds=True)["directions"]
        written_out = a2em._squad_marks(f"ECNL RL {spelled} G13", spelled_compounds=True)["directions"]

        assert abbreviated == written_out == frozenset({direction})

    def test_by_default_a_spelled_compound_direction_reads_as_none(self):
        """Tourney Central's club cut reads marks this way: a spelled direction stays in its drivers' club guesses."""
        assert a2em._squad_marks("ECNL RL SW Girls U14")["directions"] == frozenset({"southwest"})
        assert a2em._squad_marks("ECNL RL Southwest G13")["directions"] == frozenset()


class TestRegistrationOutcomes:
    def test_no_candidate_creates_the_team_under_its_provider_id_with_the_pages_state(self):
        db = _DB()

        result = _register(_matcher(db))

        assert (result["matched"], result["created"], result["method"]) == (True, True, "direct_id")
        [team] = db.writes("teams")
        fields = ("state_code", "state", "provider_team_id", "age_group", "gender")
        assert {k: team[k] for k in fields} == {
            "state_code": "WA",
            "state": "Washington",
            "provider_team_id": "10186",
            "age_group": "u13",
            "gender": "Male",
        }
        [alias] = db.writes("team_alias_map")
        assert (alias["provider_team_id"], alias["match_method"], alias["team_id_master"]) == (
            "10186",
            "direct_id",
            team["team_id_master"],
        )

    def test_team_creation_survives_the_zero_row_single_that_postgrest_raises(self):
        """The pre-create existence check raises PGRST116 for every unseen team."""
        db = _DB()

        result = _register(_matcher(db))

        assert result["created"] is True
        assert len(db.writes("teams")) == 1

    def test_a_team_row_already_carrying_the_provider_id_is_relinked_not_created(self, monkeypatch):
        own_row = {**_candidate("m-own", "B13 RCL1", "XF"), "provider_id": PROVIDER, "provider_team_id": "10186"}
        db = _DB([own_row])
        matcher = _matcher(db)
        monkeypatch.setattr(matcher, "_fuzzy_match_team", lambda *a, **k: None)

        result = _register(matcher)

        assert (result["team_id"], result["created"], result["relinked"]) == ("m-own", False, True)
        assert db.writes("teams") == []

    def test_outside_registration_mode_nothing_is_created(self):
        db = _DB()

        result = _register(_matcher(db, registration_mode=False))

        assert (result["matched"], result["created"]) == (False, False)
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []

    def test_without_a_state_no_candidate_is_queried(self):
        db = _DB([_candidate("m1", "XF B13 RCL1", "Crossfire Premier")])

        result = _register(_matcher(db), state_code=None)

        assert result["matched"] is False
        assert db.reads("teams") == []

    def test_a_failed_candidate_query_raises_and_creates_nothing(self):
        db = _DB()
        db.fail_candidate_query = True

        with pytest.raises(RuntimeError):
            _register(_matcher(db))

        assert (db.writes("teams"), db.writes("team_alias_map")) == ([], [])

    def test_a_dry_run_writes_neither_the_team_nor_the_alias(self):
        db = _DB()

        result = _register(_matcher(db, dry_run=True))

        assert result["created"] is True
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []
        assert db.writes("team_match_review_queue") == []

    def test_a_review_band_match_queues_below_the_auto_approve_threshold(self, monkeypatch):
        db = _DB()
        matcher = _matcher(db)
        monkeypatch.setattr(
            matcher,
            "_fuzzy_match_team",
            lambda *a, **k: {"team_id": "m1", "team_name": "XF B13 RCL1 Red", "confidence": 0.8},
        )

        result = _register(matcher)

        assert (result["matched"], result["created"], result["review"]) == (False, False, True)
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []
        assert [r["confidence_score"] for r in db.writes("team_match_review_queue")] == [0.8]

    def test_a_birth_year_conflict_queues_at_the_clamped_confidence(self, monkeypatch):
        db = _DB()
        matcher = _matcher(db)
        monkeypatch.setattr(
            matcher,
            "_fuzzy_match_team",
            lambda *a, **k: {"team_id": "m1", "team_name": "XF 2014 RCL1", "confidence": 0.95},
        )

        result = _register(matcher, name="XF 2013 RCL1")

        assert result["review"] is True
        assert db.writes("team_alias_map") == []
        assert [r["confidence_score"] for r in db.writes("team_match_review_queue")] == [0.89]


class TestFuzzyMatching:
    def test_the_fuzzy_result_carries_the_team_name_the_birth_year_guard_reads(self):
        db = _DB([_candidate("m1", "XF B13 RCL1", "Crossfire Premier")])

        match = _matcher(db)._fuzzy_match_team("XF B13 RCL1", "u13", "Male", "Crossfire Premier", state_code="WA")

        assert match["team_name"] == "XF B13 RCL1"

    def test_candidates_are_scoped_to_the_state_or_to_no_state(self):
        db = _DB([_candidate("m1", "XF B13 RCL1", "Crossfire Premier")])

        _matcher(db)._fuzzy_match_team("XF B13 RCL1", "u13", "Male", "Crossfire Premier", state_code="WA")

        [(filters, or_clauses, order)] = db.reads("teams")
        assert filters == {"age_group": "u13", "gender": "Male", "is_deprecated": False}
        assert set(or_clauses) == {("state_code", "WA"), ("state_code", None)}
        assert order == "team_id_master"

    def test_an_equal_ranked_tie_goes_to_review_rather_than_to_the_first_candidate(self):
        db = _DB(
            [
                _candidate("m1", "XF B13 Delgado", "Crossfire Premier"),
                _candidate("m2", "XF B13 Delgado", "Crossfire Premier"),
            ]
        )

        match = _matcher(db)._fuzzy_match_team("XF B13 Delgado", "u13", "Male", "Crossfire Premier", state_code="WA")

        assert match["confidence"] <= 0.89

    def test_the_score_itself_is_never_clamped(self):
        """Clamping here would put every link below auto-approve and make fuzzy_auto unreachable."""
        matcher = _matcher(_DB())
        provider = {"team_name": "XF B13 RCL1", "club_name": "Crossfire Premier", "age_group": "u13"}

        score = matcher._calculate_match_score(provider, {**provider})

        assert score > float(a2em.REVIEW_QUEUE_CLAMP)


class TestCandidateLoop:
    def test_a_team_created_this_run_is_never_a_candidate(self):
        """The dry-run preview that decided to create it could not see it."""
        db = _DB()
        matcher = _matcher(db)
        first = _register(matcher, name="XF B13 Red", a2e_id="1")
        db.rows["teams"].append(
            _candidate(first["team_id"], "XF B13 Red", "Crossfire Premier") | {"is_deprecated": False}
        )

        second = _register(matcher, name="XF B13 Red", a2e_id="2")

        assert second["team_id"] != first["team_id"]
        assert second["created"] is True

    def test_a_match_on_the_second_page_of_candidates_is_found(self):
        """PostgREST caps a response, so the real row can sit past the first page."""
        filler = [_candidate(f"f{i}", f"Filler SC B13 {i}", f"Filler SC {i}") for i in range(1000)]
        db = _DB([*filler, _candidate("wanted", "XF B13 RCL1", "Crossfire Premier")])

        match = _matcher(db)._fuzzy_match_team("XF B13 RCL1", "u13", "Male", "Crossfire Premier", state_code="WA")

        assert match is not None and match["team_id"] == "wanted"

    def test_the_candidate_query_asks_only_for_the_columns_the_loop_reads(self):
        db = _DB([_candidate("m1", "XF B13 RCL1", "Crossfire Premier")])

        _matcher(db)._fuzzy_match_team("XF B13 RCL1", "u13", "Male", "Crossfire Premier", state_code="WA")

        assert db.selected("teams") == [
            "team_id_master",
            "team_name",
            "club_name",
            "age_group",
            "gender",
            "state_code",
        ]


class TestWrittenClub:
    """The host writes "Crossfire Select"; PitchRank stores "Crossfire Select Soccer Club"."""

    CANON = "Crossfire Select Soccer Club"
    WRITTEN = "Crossfire Select"

    def _register_select(self, db, name="Crossfire Select B2013 Blue"):
        return db, _matcher(db)._match_team(
            provider_id=PROVIDER,
            provider_team_id="6195",
            team_name=name,
            age_group="u13",
            gender="Male",
            club_name=self.CANON,
            state_code="WA",
            written_club=self.WRITTEN,
        )

    def test_a_stored_row_whose_name_omits_the_club_word_still_links(self):
        """Left in, "Select" reads as a tier the stored row does not name, and the match is refused."""
        db, result = self._register_select(_DB([_candidate("m1", "Crossfire B13 Blue", self.CANON)]))

        assert (result["matched"], result.get("created")) == (True, False)
        assert result["team_id"] == "m1"

    def test_a_stored_row_whose_name_carries_the_club_word_still_links(self):
        """The other half of the same guard: stripping only one side inverts the defect onto these."""
        db, result = self._register_select(_DB([_candidate("m2", "Crossfire Select B13 Blue", self.CANON)]))

        assert (result["matched"], result.get("created")) == (True, False)
        assert result["team_id"] == "m2"

    def test_a_real_tier_difference_is_still_refused(self):
        db, result = self._register_select(_DB([_candidate("m3", "Crossfire Select B13 ECNL", self.CANON)]))

        assert result["created"] is True

    def test_the_created_team_is_filed_under_the_stored_club_name(self):
        db, result = self._register_select(_DB())

        [team] = db.writes("teams")
        assert team["club_name"] == self.CANON

    def test_the_written_club_does_not_outlive_the_call(self):
        matcher = _matcher(_DB())
        matcher._match_team(
            provider_id=PROVIDER,
            provider_team_id="6195",
            team_name="Crossfire Select B2013 Blue",
            age_group="u13",
            gender="Male",
            club_name=self.CANON,
            state_code="WA",
            written_club=self.WRITTEN,
        )

        assert matcher._written_club is None


class TestAthletes2EventsRules:
    def test_only_athletes2events_runs_its_own_club_rules(self):
        """Derived, not listed, so a new subclass fails here until someone decides whether it runs the rules."""
        assert {name: cls.athletes2events_rules for name, cls in _athletes2events_family().items()} == {
            "Athletes2EventsGameMatcher": True,
            "TourneyCentralGameMatcher": False,
            "DemosphereGameMatcher": False,
            "HeartlandGameMatcher": False,
            "HtgSportsGameMatcher": False,
            "YSSLGameMatcher": False,
        }


class TestHostClubTable:
    def test_a_hyphenated_branch_club_is_not_the_club_its_code_begins(self):
        """LASC-SCV is its own club; read as LASC it would link a generic Los Angeles SC row."""
        db = _DB([_candidate("lasc", "Los Angeles SC", "Los Angeles Soccer Club", "u15", "CA")])

        result = _register_split(_matcher(db), "LASC-SCV BU15 N1", "u15", "CA")

        assert result["created"] is True
        assert result["team_id"] != "lasc"


class TestWrittenClubPass:
    """Surf Cup writes "HB Slammers"; PitchRank files the club as "CDA Slammers"."""

    ROW = _candidate("hb", "HB Slammers U10 Blue", "Huntington Beach Slammers", age_group="u10", state_code="CA")

    def _register_hb(self, matcher):
        return _register_with_club(
            matcher, "HB Slammers U10 Blue", "CDA Slammers", "u10", "CA", written="HB Slammers", a2e_id="12111"
        )

    def test_a_row_only_the_written_club_vouches_for_links_on_the_second_pass(self):
        result = self._register_hb(_matcher(_DB([self.ROW])))

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "hb")

    def test_the_stored_club_alone_does_not_find_it(self):
        result = self._register_hb(_without_rules(_matcher(_DB([self.ROW]))))

        assert result["created"] is True

    def test_tourney_central_still_links_it_through_its_own_written_club_pass(self):
        matcher = TourneyCentralGameMatcher(_DB([self.ROW]), provider_id=PROVIDER, registration_mode=True)

        result = self._register_hb(matcher)

        assert (result["matched"], result["team_id"]) == (True, "hb")

    def test_the_written_club_pass_reads_club_names_without_spacing(self):
        """Only the club read from the stored name agrees with the written club, and only once spacing is ignored."""
        db = _DB([_candidate("fc", "SlammersFC ECNL U13", "Independent", "u13", "CA")])

        result = _register_with_club(
            _matcher(db), "Slammers FC ECNL U13", "CDA Slammers", "u13", "CA", written="Slammers FC"
        )

        assert (result["matched"], result["team_id"]) == (True, "fc")


class TestCutBackClub:
    """A club read from the words before the age can run on into a squad or branch word."""

    NEXT_LEVEL = _candidate("nl", "Southeast U12 Boys Red", "Next Level Soccer (AZ)", age_group="u12", state_code="AZ")
    # Stored under a club the cut club passes, so the missing "SB" is all that keeps it out.
    SACRAMENTO = _candidate("sac", "Legends U11B-A", "Legends FC (CA)", age_group="u11", state_code="CA")
    LEGENDS_SB = _candidate("sb", "SB BU11", "Legends FC (CA)", age_group="u11", state_code="CA")
    CARLSBAD = [
        _candidate("dennis", "Carlsbad GU11 Gold - Dennis", "City SC", "u11", "CA", gender="Female"),
        _candidate("cordeiro", "City SC - Carlsbad 2016 Gold - Cordeiro", "City SC", "u11", "CA", gender="Female"),
        _candidate("cardenas", "Carlsbad G18 Gold - Cardenas", "City SC", "u11", "CA", gender="Female"),
    ]

    def _register_next_level(self, matcher):
        return _register_with_club(
            matcher, "Next Level Soccer Southeast U12 Boys Red", "Next Level Soccer Southeast", "u12", "AZ"
        )

    def _register_legends(self, db):
        return _register_with_club(_matcher(db), "Legends FC SB U11 Garcia", "Legends FC SB", "u11", "CA")

    def test_a_club_running_into_a_direction_links_its_squad_once_cut_back(self):
        result = self._register_next_level(_matcher(_DB([self.NEXT_LEVEL])))

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "nl")

    def test_a_cut_back_club_never_links_a_row_without_the_cut_word(self):
        """Cut back to "Legends FC", the club gate admits this row, whose name has no "SB"."""
        result = self._register_legends(_DB([self.SACRAMENTO]))

        assert result["created"] is True
        assert result["team_id"] != "sac"

    def test_a_cut_back_club_links_the_row_carrying_the_cut_word(self):
        result = self._register_legends(_DB([self.SACRAMENTO, self.LEGENDS_SB]))

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "sb")

    def test_the_club_is_cut_back_to_two_words_and_no_further(self):
        """Cut to "Desert", the club would match this row, whose name carries both cut words."""
        db = _DB([_candidate("storm", "Storm Rangers U12 Red", "Desert", age_group="u12", state_code="AZ")])

        result = _register_with_club(_matcher(db), "Desert Storm Rangers U12 Red", "Desert Storm Rangers", "u12", "AZ")

        assert result["created"] is True
        assert result["team_id"] != "storm"

    def test_the_cut_back_pass_reads_club_names_without_spacing(self):
        db = _DB([_candidate("ts", "So Cal Tsunami Elite U14", "So Cal Tsunami", "u14", "CA", gender="Female")])

        result = _register_with_club(
            _matcher(db), "SoCal Tsunami Elite U14", "SoCal Tsunami Elite", "u14", "CA", gender="Female"
        )

        assert (result["matched"], result["team_id"]) == (True, "ts")

    def test_a_shortened_club_is_vouched_for_only_by_the_stored_club(self):
        """Were a row's own name allowed to vouch, the stale Cordeiro row alone would pass at "City SC Carlsbad";
        at "City SC" the club field passes all three, and the tie goes to review."""
        db = _DB(self.CARLSBAD)

        result = _register_split(_matcher(db), "City SC Carlsbad Gold GU11-Dennis", "u11", "CA", gender="Female")

        assert (result["matched"], result.get("review"), result["confidence"]) == (False, True, 0.89)
        assert db.writes("team_alias_map") == []

    def test_a_club_parted_by_a_dash_is_cut_back_word_by_word(self):
        """Cut back to "Legends FC", the cut words are "San" and "Diego" (a dash is no word); this row has both."""
        db = _DB([_candidate("sd", "San Diego GU15 Elite I", "Legends FC (CA)", "u15", "CA", gender="Female")])

        result = _register_split(_matcher(db), "Legends FC - San Diego GU15 Elite I", "u15", "CA", gender="Female")

        assert (result["matched"], result["team_id"]) == (True, "sd")

    def test_a_dash_does_not_count_toward_the_two_word_floor(self):
        """Read as a word, the dash would cut "Desert - Storm Rangers" to "Desert -", one word in all but name."""
        db = _DB([_candidate("storm", "Storm Rangers U12 Red", "Desert", age_group="u12", state_code="AZ")])

        result = _register_split(_matcher(db), "Desert - Storm Rangers U12 Red", "u12", "AZ")

        assert result["created"] is True
        assert result["team_id"] != "storm"

    def test_a_club_parted_by_a_dash_still_needs_every_cut_word(self):
        db = _DB([_candidate("other", "GU15 Elite I", "Legends FC (CA)", "u15", "CA", gender="Female")])

        result = _register_split(_matcher(db), "Legends FC - San Diego GU15 Elite I", "u15", "CA", gender="Female")

        assert result["created"] is True
        assert result["team_id"] != "other"

    def test_carrying_one_of_the_cut_words_is_not_enough(self):
        """San Marcos carries "San" but not "Diego": another branch of the club."""
        db = _DB([_candidate("marcos", "San Marcos GU15 Elite I", "Legends FC (CA)", "u15", "CA", gender="Female")])

        result = _register_split(_matcher(db), "Legends FC - San Diego GU15 Elite I", "u15", "CA", gender="Female")

        assert result["created"] is True
        assert result["team_id"] != "marcos"

    def test_every_pass_gates_the_same_candidate_rows_read_once(self):
        """The first pass and the cut-back share one read: the rows depend only on age, gender and state."""
        db = _DB([self.NEXT_LEVEL])

        self._register_next_level(_matcher(db))

        candidate_reads = [filters for filters, or_clauses, _ in db.reads("teams") if "age_group" in filters]
        assert candidate_reads == [{"age_group": "u12", "gender": "Male", "is_deprecated": False}]

    def test_tourney_central_does_not_cut_a_club_back(self):
        matcher = TourneyCentralGameMatcher(_DB([self.NEXT_LEVEL]), provider_id=PROVIDER, registration_mode=True)

        result = self._register_next_level(matcher)

        assert result["created"] is True


class TestSquadNumbers:
    """A plain squad is not its club's squad 2 (owner, 2026-11-19, as YSSL's "White1 and white2" ruling)."""

    SANTA_CRUZ = [
        _candidate("blue", "2015 Blue", "Santa Cruz United Football Club", "u12", "CA"),
        _candidate("blue2", "14/15 Boys Blue 2", "Santa Cruz United Football Club", "u12", "CA"),
    ]

    def test_an_unnumbered_squad_links_the_unnumbered_row_not_squad_2(self):
        result = _register_split(_matcher(_DB(self.SANTA_CRUZ)), "Sant Cruz United 14-15 Boys Blue", "u12", "CA")

        assert (result["matched"], result["team_id"]) == (True, "blue")

    def test_squad_2_never_links_a_row_naming_no_number(self):
        db = _DB([_candidate("ecnl", "XF B13 ECNL", "Crossfire Premier", "u14", "WA")])

        result = _register_split(_matcher(db), "XF U14 B12-13 ECNL 2 - Cruz", "u14", "WA", host=CROSSFIRE)

        assert result["created"] is True
        assert result["team_id"] != "ecnl"

    def test_squad_1_is_the_unnumbered_squad(self):
        db = _DB([_candidate("red", "XF B13 Red", "Crossfire Premier", "u13", "WA")])

        result = _register_split(_matcher(db), "XF B13 Red 1", "u13", "WA", host=CROSSFIRE)

        assert (result["matched"], result["team_id"]) == (True, "red")

    def test_a_club_digit_is_not_a_squad_number(self):
        """Read with its club, the name is squad 7, which no row of the club carries, so the team would be created."""
        db = _DB(
            [
                _candidate("copa", "U14 Copa South", "7 Elite Academy", "u14", "CA"),
                _candidate("copa2", "7 Elite Academy U14 Copa South 2", "7 Elite Academy", "u14", "CA"),
            ]
        )

        result = _register_split(_matcher(db), "7 Elite Academy u14B Copa South", "u14", "CA")

        assert (result["matched"], result["team_id"]) == (True, "copa")

    @pytest.mark.parametrize(
        "name, numbers",
        [
            ("SoCal Reds EA2", frozenset()),
            ("Legends G2010/11 NL1", frozenset()),
            ("XF U10 RCL 2", frozenset()),
            ("XF N1 B13", frozenset()),
            ("Crossfire ECNL2 B13", frozenset({2})),
        ],
    )
    def test_glued_labels_are_squad_codes_not_numbers_except_ecnl(self, name, numbers):
        assert squad_numbers(canonical_team_name(name, a2em._presplit)) == numbers

    @pytest.mark.parametrize("name", ["XF B13 Red İ", "XF B13 Red ı", "XF B13 Red ıı"])
    def test_a_non_ascii_look_alike_of_a_roman_numeral_is_no_number(self, name):
        """Under IGNORECASE alone "İ" and "ı" match "i", and their lowercase forms are not in the numeral table."""
        assert squad_numbers(name) == frozenset()

    def test_a_stored_name_with_a_dotless_i_does_not_stop_the_team_matching(self):
        db = _DB([_candidate("red", "XF B13 Red ıı", "Crossfire Premier", "u13", "WA")])

        result = _register_split(_matcher(db), "XF B13 Red", "u13", "WA", host=CROSSFIRE)

        assert (result["matched"], result["team_id"]) == (True, "red")

    def test_two_squads_of_one_club_in_a_row_each_link_their_own_row(self):
        matcher = _matcher(_DB(self.SANTA_CRUZ))

        second = _register_split(matcher, "Sant Cruz United 14-15 Boys Blue 2", "u12", "CA", a2e_id="1")
        first = _register_split(matcher, "Sant Cruz United 14-15 Boys Blue", "u12", "CA", a2e_id="2")

        assert (second["team_id"], first["team_id"]) == ("blue2", "blue")

    def test_tourney_central_keeps_the_shared_both_sides_rule(self):
        matcher = TourneyCentralGameMatcher(_DB(self.SANTA_CRUZ), provider_id=PROVIDER, registration_mode=True)

        result = _register_split(matcher, "Sant Cruz United 14-15 Boys Blue", "u12", "CA")

        assert (result["matched"], result["team_id"]) == (True, "blue2")


class TestClubSpacing:
    @pytest.mark.parametrize(
        "provider, stored",
        [("LeonFC", "Leon FC"), ("TopBallers", "Top Ballers"), ("SoCal Tsunami", "So Cal Tsunami")],
    )
    def test_spacing_is_ignored(self, provider, stored):
        assert a2em._same_club_ignoring_spacing(provider, stored) is True

    @pytest.mark.parametrize("provider, stored", [("Leon FC", "Leon United"), ("", ""), ("-", None)])
    def test_other_letters_or_no_letters_are_not_one_club(self, provider, stored):
        assert a2em._same_club_ignoring_spacing(provider, stored) is False

    ROW = _candidate("ts", "So Cal Tsunami", "Independent - Cal South", "u14", "CA", gender="Female")

    def _register_tsunami(self, matcher):
        return _register_with_club(
            matcher, "SoCal Tsunami U14 - Anthony", "SoCal Tsunami", "u14", "CA", gender="Female"
        )

    def test_a_club_written_without_its_space_links_its_stored_row(self):
        result = self._register_tsunami(_matcher(_DB([self.ROW])))

        assert (result["matched"], result["team_id"]) == (True, "ts")

    def test_without_the_rules_the_club_gate_refuses_it(self):
        result = self._register_tsunami(_without_rules(_matcher(_DB([self.ROW]))))

        assert result["created"] is True


class TestSpelledDirections:
    ROW = _candidate(
        "sd", "San Diego Surf ECNL RL Southwest G13", "San Diego Surf Soccer Club", "u14", "CA", gender="Female"
    )

    def _register_sd(self, matcher):
        return _register_with_club(
            matcher, "SD Surf ECNL RL SW Girls U14 (Gonzalez)", "SD Surf", "u14", "CA", gender="Female"
        )

    def test_an_abbreviated_direction_links_the_squad_that_spells_it(self):
        result = self._register_sd(_matcher(_DB([self.ROW])))

        assert (result["matched"], result["team_id"]) == (True, "sd")

    def test_a_spelled_direction_links_the_squad_that_abbreviates_it(self):
        db = _DB(
            [_candidate("sw", "SD Surf ECNL RL SW G13", "San Diego Surf Soccer Club", "u14", "CA", gender="Female")]
        )

        result = _register_split(_matcher(db), "San Diego Surf ECNL RL Southwest G13", "u14", "CA", gender="Female")

        assert (result["matched"], result["team_id"]) == (True, "sw")

    def test_without_the_rules_the_squad_gate_refuses_it(self):
        result = self._register_sd(_without_rules(_matcher(_DB([self.ROW]))))

        assert result["created"] is True


class TestReviewSuppression:
    def test_a_team_the_roster_pass_creates_gets_no_review_row(self):
        """Otherwise every created team floods the queue with a no_match row."""
        db = _DB()

        result = _register(_matcher(db))

        assert result["created"] is True
        assert db.writes("team_match_review_queue") == []

    def test_outside_registration_mode_the_row_is_still_queued(self):
        db = _DB()

        _register(_matcher(db, registration_mode=False))

        assert [r["match_details"]["match_method"] for r in db.writes("team_match_review_queue")] == ["no_match"]
