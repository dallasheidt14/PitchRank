"""Unit tests for the Soccer Events Group matcher.

The database double records at ``execute()``, applies the ``or_`` state filter
and the ``order`` it is given, and refuses review rows the table's CHECK refuses.
"""

from types import SimpleNamespace

import pytest

from src.models import soccereventsgroup_matcher as segm
from src.models.soccereventsgroup_matcher import SoccerEventsGroupGameMatcher

PROVIDER = "11111111-1111-4111-8111-111111111111"


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

    def select(self, *_a, **_k):
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

    def like(self, *_a, **_k):
        return self

    def in_(self, field, values):
        self.filters.append((field, tuple(values)))
        return self

    def limit(self, *_a, **_k):
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
            (self.table, self.op, dict(self.filters), self.payload, tuple(self.or_clauses), self.order_by)
        )
        if self.op != "select":
            return SimpleNamespace(data=[self.payload])
        rows = [r for r in self.db.rows.get(self.table, []) if self._matches(r)]
        if self.order_by:
            rows.sort(key=lambda r: str(r.get(self.order_by)))
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        if self.single_row:
            return SimpleNamespace(data=rows[0] if rows else None)
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, teams=()):
        self.rows = {
            "providers": [{"id": PROVIDER, "code": "soccereventsgroup"}],
            "teams": [{"is_deprecated": False, **t} for t in teams],
            "team_alias_map": [],
            "team_match_review_queue": [],
        }
        self.executed = []
        self.fail_candidate_query = False

    def table(self, name):
        return _Query(self, name)

    def writes(self, table):
        return [payload for t, op, _, payload, _, _ in self.executed if t == table and op != "select"]

    def reads(self, table):
        return [
            (filters, or_clauses, order)
            for t, op, filters, _, or_clauses, order in self.executed
            if t == table and op == "select"
        ]


def _matcher(db, registration_mode=True, dry_run=False):
    return SoccerEventsGroupGameMatcher(db, provider_id=PROVIDER, registration_mode=registration_mode, dry_run=dry_run)


def _register(matcher, name="AFC Union U15G N1", state_code="WI", seg_id="590399", age_group="u15", gender="Female"):
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=seg_id,
        team_name=name,
        age_group=age_group,
        gender=gender,
        state_code=state_code,
    )


def _candidate(team_id, team_name, club_name, age_group="u15", state_code="WI", gender="Female"):
    return {
        "team_id_master": team_id,
        "team_name": team_name,
        "club_name": club_name,
        "age_group": age_group,
        "gender": gender,
        "state_code": state_code,
    }


class TestRegistrationOutcomes:
    def test_a_review_band_match_queues_and_creates_nothing(self, monkeypatch):
        db = _DB()
        matcher = _matcher(db)
        monkeypatch.setattr(
            matcher,
            "_fuzzy_match_team",
            lambda *a, **k: {"team_id": "m1", "team_name": "AFC Union Blue", "confidence": 0.8},
        )

        result = _register(matcher)

        assert (result["matched"], result["created"], result["review"]) == (False, False, True)
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []
        queued = db.writes("team_match_review_queue")
        assert [(r["provider_team_id"], r["suggested_master_team_id"]) for r in queued] == [("590399", "m1")]

    def test_a_birth_year_conflict_queues_at_the_clamped_confidence(self, monkeypatch):
        db = _DB()
        matcher = _matcher(db)
        monkeypatch.setattr(
            matcher,
            "_fuzzy_match_team",
            lambda *a, **k: {"team_id": "m1", "team_name": "AFC Union 2013 N1", "confidence": 0.95},
        )

        result = _register(matcher, name="AFC Union 2012 N1")

        assert result["review"] is True
        assert db.writes("team_alias_map") == []
        assert db.writes("teams") == []
        assert [r["confidence_score"] for r in db.writes("team_match_review_queue")] == [0.89]

    def test_no_candidate_creates_the_team_under_its_seg_id_with_segs_state(self):
        db = _DB()

        result = _register(_matcher(db))

        assert (result["matched"], result["created"], result["method"]) == (True, True, "direct_id")
        [team] = db.writes("teams")
        fields = ("state_code", "state", "provider_team_id", "age_group", "gender", "club_name")
        assert {k: team[k] for k in fields} == {
            "state_code": "WI",
            "state": "Wisconsin",
            "provider_team_id": "590399",
            "age_group": "u15",
            "gender": "Female",
            "club_name": "AFC Union",
        }
        [alias] = db.writes("team_alias_map")
        assert (alias["provider_team_id"], alias["match_method"], alias["team_id_master"]) == (
            "590399",
            "direct_id",
            team["team_id_master"],
        )
        assert db.writes("team_match_review_queue") == []

    def test_a_boys_team_is_created_on_the_boys_board(self):
        db = _DB()

        _register(_matcher(db), name="CFYSC 11U Boys Premier", state_code="IL", age_group="u11", gender="Male")

        assert [t["gender"] for t in db.writes("teams")] == ["Male"]

    def test_outside_registration_mode_nothing_is_created(self):
        db = _DB()

        result = _register(_matcher(db, registration_mode=False))

        assert (result["matched"], result["created"]) == (False, False)
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []

    def test_without_a_state_no_candidate_is_queried(self):
        db = _DB([_candidate("m1", "AFC Union U15N1", "AFC Union")])

        result = _register(_matcher(db), state_code=None)

        assert result["matched"] is False
        assert db.reads("teams") == []
        assert db.writes("teams") == []

    def test_a_failed_candidate_query_raises_and_creates_nothing(self):
        db = _DB()
        db.fail_candidate_query = True

        with pytest.raises(RuntimeError):
            _register(_matcher(db))

        assert (db.writes("teams"), db.writes("team_alias_map")) == ([], [])

    def test_a_team_row_already_carrying_the_seg_id_is_relinked_not_created(self, monkeypatch):
        own_row = {**_candidate("m-own", "U15 N1", "AFC Union"), "provider_id": PROVIDER, "provider_team_id": "590399"}
        db = _DB([own_row])
        matcher = _matcher(db)
        monkeypatch.setattr(matcher, "_fuzzy_match_team", lambda *a, **k: None)

        result = _register(matcher)

        assert (result["team_id"], result["created"], result["relinked"]) == ("m-own", False, True)
        assert db.writes("teams") == []
        assert [(a["provider_team_id"], a["team_id_master"]) for a in db.writes("team_alias_map")] == [
            ("590399", "m-own")
        ]

    def test_a_dry_run_create_writes_nothing_and_keeps_one_id(self):
        db = _DB()
        matcher = _matcher(db, dry_run=True)

        first = _register(matcher)["team_id"]
        second = _register(matcher)["team_id"]

        assert first == second
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []
        assert db.writes("team_match_review_queue") == []


class TestQueueForReview:
    def test_the_best_candidate_is_suggested_and_nothing_is_linked(self):
        db = _DB([_candidate("m1", "Pegasus FC Girls N1 U14 Red", "Pegasus FC", age_group="u14", state_code="IL")])

        result = _matcher(db).queue_for_review(
            provider_id=PROVIDER,
            provider_team_id="7",
            team_name="Pegasus FC GU13 Red",
            age_group="u14",
            gender="Female",
            state_code="IL",
            reason="name says U13, division is U14",
        )

        [row] = db.writes("team_match_review_queue")
        assert (row["suggested_master_team_id"], row["confidence_score"]) == ("m1", 0.89)
        assert row["match_details"]["reason"] == "name says U13, division is U14"
        assert (result["review"], db.writes("team_alias_map"), db.writes("teams")) == (True, [], [])

    def test_with_no_candidate_the_row_has_no_suggestion(self):
        db = _DB()

        _matcher(db).queue_for_review(
            provider_id=PROVIDER,
            provider_team_id="7",
            team_name="Pegasus FC GU13 Red",
            age_group="u14",
            gender="Female",
            state_code="IL",
            reason="name says U13, division is U14",
        )

        queued = db.writes("team_match_review_queue")
        assert [(r["suggested_master_team_id"], r["confidence_score"]) for r in queued] == [(None, 0.75)]


class TestFuzzyLinking:
    def test_the_operators_afc_union_pair_links(self):
        """The glued "U15N1" must still link to the stored squad."""
        db = _DB(
            [
                _candidate("5b6b37ce-031b-4e77-83eb-9a5b4e667c2f", "AFC Union U15N1", "AFC Union"),
                _candidate("m-other", "AFC Union G 2016 Premier", "AFC Union"),
            ]
        )

        result = _register(_matcher(db))

        assert (result["matched"], result["method"], result["team_id"]) == (
            True,
            "fuzzy_auto",
            "5b6b37ce-031b-4e77-83eb-9a5b4e667c2f",
        )
        assert [a["match_method"] for a in db.writes("team_alias_map")] == ["fuzzy_auto"]
        assert db.writes("teams") == []

    def test_two_equally_good_candidates_go_to_review(self):
        db = _DB(
            [
                _candidate("m-2009", "Rush WI 2009 Girls Rush", "Rush WI", age_group="u19"),
                _candidate("m-2007", "Rush WI 2007 Rush", "Rush WI", age_group="u19"),
            ]
        )

        result = _register(_matcher(db), name="Rush WI U18 Girls Rush", age_group="u19")

        assert (result["matched"], result.get("review"), db.writes("team_alias_map")) == (False, True, [])

    def test_a_stored_long_club_name_is_vouched_for_by_the_rows_team_name(self):
        row = _candidate("m1", "CFYSC 10U Boys Premier", "Chicago Fire Youth SC (CFYSC)", "u11", "IL", "Male")

        result = _register(
            _matcher(_DB([row])), name="CFYSC 10U Boys Premier", state_code="IL", age_group="u11", gender="Male"
        )

        assert (result["method"], result["team_id"]) == ("fuzzy_auto", "m1")

    def test_two_clubs_sharing_a_canonical_id_are_not_one_club(self):
        """The canonical map folds every "Timbers" affiliate into one id; unchecked, this pair scores into review."""
        db = _DB([_candidate("m-rvt", "Rogue Valley Timbers U15 N1", "Rogue Valley Timbers")])

        result = _register(_matcher(db), name="Eastside Timbers U15 N1")

        assert (result["method"], result["created"]) == ("direct_id", True)
        assert db.writes("team_match_review_queue") == []

    def test_a_same_named_team_in_another_state_is_not_a_candidate(self):
        db = _DB([_candidate("m-il", "AFC Union U15N1", "AFC Union", state_code="IL")])

        result = _register(_matcher(db))

        assert (result["method"], result["created"]) == ("direct_id", True)

    def test_a_team_with_no_state_is_a_candidate(self):
        db = _DB([_candidate("m-none", "AFC Union U15N1", "AFC Union", state_code=None)])

        result = _register(_matcher(db))

        assert (result["method"], result["team_id"]) == ("fuzzy_auto", "m-none")

    def test_candidates_are_scoped_and_paged_in_a_stable_order(self):
        db = _DB()

        _register(_matcher(db))

        filters, or_clauses, order = db.reads("teams")[0]
        assert filters == {"age_group": "u15", "gender": "Female", "is_deprecated": False}
        assert or_clauses == (("state_code", "WI"), ("state_code", None))
        assert order == "team_id_master"

    def test_a_match_on_the_second_page_of_candidates_is_found(self):
        filler = [_candidate(f"a-{i:04d}", f"Filler FC U15 {i}", "Filler FC") for i in range(1000)]
        real = _candidate("z-real", "AFC Union U15N1", "AFC Union")
        db = _DB([real, *filler])

        result = _register(_matcher(db))

        assert (result["method"], result["team_id"]) == ("fuzzy_auto", "z-real")

    def test_a_team_created_this_run_is_never_a_candidate(self):
        db = _DB()
        matcher = _matcher(db)
        created = _register(matcher, name="Galaxy SC U15 Aspire", seg_id="1")["team_id"]
        db.rows["teams"].append({**_candidate(created, "Galaxy SC U15 Aspire", "Galaxy SC"), "is_deprecated": False})

        second = _register(matcher, name="Galaxy SC U15 Aspire", seg_id="2")

        assert second["created"] is True
        assert second["team_id"] != created

    def test_a_team_this_matcher_created_is_found_again_at_the_next_event(self):
        """Stored as club "Lou Fusz Athletic Blue Star", name "Premier 2016/2017G": "Blue" is the club's word."""
        name = "Lou Fusz Athletic Blue Star Premier 2016/2017G"
        db = _DB()
        _register(_matcher(db), name=name, state_code="MO", age_group="u10", seg_id="580345")
        [stored] = db.writes("teams")
        db.rows["teams"].append({**stored, "is_deprecated": False})

        again = _register(_matcher(db), name=name, state_code="MO", age_group="u10", seg_id="690001")

        assert (again["method"], again["team_id"]) == ("fuzzy_auto", stored["team_id_master"])

    def test_a_colour_in_both_club_names_is_not_read_as_a_squad_mark(self):
        db = _DB([_candidate("m-bluefire", "Blue Fire U15 Red", "Blue Fire")])

        result = _register(_matcher(db), name="Blue Fire U15G Red")

        assert (result["method"], result["team_id"]) == ("fuzzy_auto", "m-bluefire")

    @pytest.mark.parametrize(
        "provider, candidate, stored_club",
        [
            ("Pegasus FC GU15 Red", "Pegasus FC GU15 Black", "Pegasus FC"),
            ("Chicago Empire U15 Gold Girls", "Chicago Empire FC South U15 Gold Girls", "Chicago Empire FC"),
            ("Chicago Empire U15G Gold 1", "Chicago Empire FC U15 Gold 2", "Chicago Empire FC"),
            ("AFC Union U15G N1", "AFC Union U15 N2", "AFC Union"),
            ("FC Pride U15G Pre-ECNL", "FC Pride U15 ECNL", "FC Pride"),
        ],
    )
    def test_a_sibling_squad_is_not_linked(self, provider, candidate, stored_club):
        db = _DB([_candidate("m-sibling", candidate, stored_club)])

        result = _register(_matcher(db), name=provider)

        assert (result["method"], result["created"]) == ("direct_id", True)
        assert [a["team_id_master"] for a in db.writes("team_alias_map")] != ["m-sibling"]


class TestSquadMarks:
    @staticmethod
    def _conflict(provider, candidate):
        """Strips the provider's club from both names, standing in for the loop's strip of an agreeing club."""
        club = segm.club_from_team_name(provider)
        return segm.squads_conflict(
            segm.squad_marks(segm.without_club(segm.canonical_team_name(provider), club)),
            segm.squad_marks(segm.without_club(segm.canonical_team_name(candidate), club)),
        )

    def test_colours_differ(self):
        assert self._conflict("Pegasus FC GU14 Red", "Pegasus FC Girls 2012/2013 Black") is True

    def test_directions_differ(self):
        assert self._conflict("Chicago Empire U11 Gold Boys", "Chicago Empire FC South 2016 Gold Boys") is True

    def test_squad_numbers_differ_even_with_a_gender_word_after(self):
        assert self._conflict("Chicago Empire u9 Gold 1 Girls", "Chicago Empire FC U10 Gold 2") is True

    def test_a_one_sided_squad_number_is_no_evidence(self):
        assert self._conflict("FC Pride U11 Pre-ECNL 15/16", "FC Pride 2016 Boys Pre-ECNL 2") is False

    @pytest.mark.parametrize(
        "provider, candidate",
        [("AFC Union U15G N1", "AFC Union U15 N2"), ("AFC Union U15G N1", "AFC Union U15 S1")],
    )
    def test_squad_codes_differ(self, provider, candidate):
        assert self._conflict(provider, candidate) is True

    def test_a_one_sided_squad_code_is_no_evidence(self):
        assert self._conflict("Pegasus FC GU14 Red", "Pegasus FC Girls N1 U14 Red") is False

    def test_a_colour_in_the_club_name_is_not_a_squad_mark(self):
        provider = segm.squad_marks(
            segm.without_club("Lou Fusz Athletic Blue Star Premier 2016/2017G", "Lou Fusz Athletic Blue Star")
        )
        candidate = segm.squad_marks("Premier 2016/2017G")

        assert segm.squads_conflict(provider, candidate) is False

    @pytest.mark.parametrize(
        "provider, candidate",
        [
            ("Chicago FC United U14 GA Aspire", "Chicago FC United U14 GA"),
            ("FC Pride U11 Pre-ECNL", "FC Pride U11 ECNL"),
            ("Chicago Inter U14G ECNL-RL", "Chicago Inter ECNL G2012/13"),
            ("Croatian Eagles 13UB EA", "Croatian Eagles 13uB Club Premier 2"),
            ("Tonka Fusion Elite U14 MLS NEXT AD", "Tonka Fusion Elite U14 MLS NEXT HD"),
            ("Tonka Fusion Elite U14 MLS NEXT AD", "Tonka Fusion Elite U14 MLS NEXT"),
            ("Tonka Fusion Elite U14 MLS NEXT HD", "Tonka Fusion Elite U14 MLS NEXT"),
            ("Sockers FC U14 HD", "Sockers FC U14"),
        ],
    )
    def test_different_tiers_conflict(self, provider, candidate):
        assert self._conflict(provider, candidate) is True

    @pytest.mark.parametrize(
        "provider, candidate",
        [
            ("AFC Union U15G N1", "AFC Union U15N1"),
            ("Chicago Inter U14G ECNL-RL", "Chicago Inter ECNL RL G2012/13"),
            ("Portage SC ECNL/RL G2011/12", "Portage SC ECNL RL G2011/12"),
            ("FC United PreECNL U11G", "FC United (Iowa) Pre-ECNL G2015/16"),
            ("Tonka Fusion Elite U14 MLS NEXT AD", "Tonka Fusion Elite U14 AD"),
            ("Tonka Fusion Elite U14 MLS NEXT HD", "Tonka Fusion Elite U14 HD"),
            ("Galaxy U14 Girls Academy", "2013 GA"),
            ("Elite S.C. U11 Boys Red 2015/16", "Elite SC U11 Boys Red"),
        ],
    )
    def test_spellings_of_one_squad_agree(self, provider, candidate):
        assert self._conflict(provider, candidate) is False


class TestNames:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("AFC Union U15G N1", "AFC Union U15 N1"),
            ("AFC Union U15N1", "AFC Union U15 N1"),
            ("Olympiacos Chicago BU07 DF Elite", "Olympiacos Chicago U7 DF Elite"),
            ("Croatian Eagles 14uG Aspire", "Croatian Eagles U14 Aspire"),
            ("CFYSC 10U Boys Premier", "CFYSC U10 Boys Premier"),
            ("Indy Premier Inspire U11 \xa0", "Indy Premier Inspire U11"),
            ("Elite S.C. U13 Boys", "Elite SC U13 Boys"),
            ("CHICAGO MAGIC U10 PRE/ECNL", "CHICAGO MAGIC U10 Pre-ECNL"),
            ("Blue Fire U9", "Blue Fire U9"),
        ],
    )
    def test_canonical_name(self, raw, expected):
        assert segm.canonical_team_name(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("U12G FC LAKE COUNTY 14/15 SELECT", "FC LAKE COUNTY"),
            ("U13 Parkland Boys ECNL", "Parkland"),
            ("CFYSC 8U Boys Select", "CFYSC"),
            ("AFC Union U15G N1", "AFC Union"),
            ("FC Pride U9 Pre-ECNL 17/18", "FC Pride"),
            ("Lou Fusz Athletic 15/16b Blue Star Premier (2034)", "Lou Fusz Athletic"),
            ("Galaxy 15/16G Pre-GA", "Galaxy"),
            ("Portage SC ECNL/RL G2011/12", "Portage SC"),
        ],
    )
    def test_club_from_team_name(self, raw, expected):
        assert segm.club_from_team_name(raw) == expected

    def test_without_club_removes_the_club_wherever_it_sits(self):
        assert segm.without_club("U12 FC LAKE COUNTY 14/15 SELECT", "FC Lake County") == "U12 14/15 SELECT"


class TestReviewSuppression:
    def _entry(self, matcher, method):
        matcher._create_review_queue_entry(
            provider_id=PROVIDER,
            provider_team_id="9",
            provider_team_name="X",
            suggested_master_team_id=None,
            confidence_score=0.75,
            match_details={"match_method": method},
        )

    @pytest.mark.parametrize("method", ["no_match", "fuzzy_low_confidence"])
    def test_a_team_about_to_be_created_gets_no_review_row(self, method):
        db = _DB()
        self._entry(_matcher(db), method)

        assert db.writes("team_match_review_queue") == []

    def test_a_review_band_row_is_still_written(self):
        db = _DB()
        self._entry(_matcher(db), "fuzzy")

        assert len(db.writes("team_match_review_queue")) == 1

    def test_outside_registration_mode_nothing_is_suppressed(self):
        db = _DB()
        self._entry(_matcher(db, registration_mode=False), "no_match")

        assert len(db.writes("team_match_review_queue")) == 1
