"""Unit tests for the Athletes2Events matcher.

The database double records at ``execute()``, applies the ``or_`` state filter and
the ``order`` it is given, and refuses review rows the table's CHECK refuses.

It differs from the Soccer Events Group double on one point, deliberately: a
zero-row ``.single()`` **raises** ``APIError(PGRST116)`` here, as postgrest does.
That is the normal path for the pre-create existence check on a team this run has
never seen, so a double that returns ``None`` instead is more permissive than
production on exactly the line that would crash every team creation.
"""

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from src.models import athletes2events_matcher as a2em
from src.models.athletes2events_matcher import Athletes2EventsGameMatcher

PROVIDER = "22222222-2222-4222-8222-222222222222"
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
