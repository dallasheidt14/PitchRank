"""The name-based pass over the state review queue.

Drives ``classify`` directly with a hand-built locality index: what is under test is which
rows the name settles and which it leaves for a person. Each fixture breaks exactly one
condition, so deleting any single guard fails its own test. The write path runs against a
double that refuses what production refuses (an RPC called with the wrong arguments, a
review no longer pending) by raising the client's own error type, answers false for a team
whose state moved, and records each call only when it executes, in one shared order.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.review_state_queue_by_name as review  # noqa: E402
from scripts.review_state_queue_by_name import PLACE_SUFFIXES, STATE_NAMED_TOWNS, classify  # noqa: E402
from src.utils.us_states import STATE_NAME_TO_CODE  # noqa: E402

LOCALITY = {"diego": "CA", "boise": "ID", "colorado": "CO", "montreal": "QC"}


def team(name, club, state, source=None, team_id="t1"):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "club_name": club,
        "state_code": state,
        "state_source": source,
    }


def row(current, proposed, review_id=7, team_id="t1"):
    return {"id": review_id, "team_id_master": team_id, "current_state_code": current, "proposed_state_code": proposed}


def decide(name, club, current, proposed, provider=None, source=None, locality=None, **ledger):
    subject = team(name, club, current, source)
    return classify(row(current, proposed), subject, LOCALITY if locality is None else locality, provider, **ledger)


def test_a_state_spelled_in_the_team_name_overrides_both_sides():
    assert decide("Colorado Elevation FC - G06/07 Summit", "Colorado Elevation FC", "UT", "UT") == ("set", "CO")


def test_a_spelled_state_agreeing_with_the_proposal_approves_it():
    assert decide("Idaho Timbers 2012", "Timbers", "WY", "ID") == ("approve", "ID")


def test_a_town_word_agreeing_with_the_proposal_does_not_approve_it():
    assert decide("Boise Timbers 2012", "Timbers", "WY", "ID") == ("left: only a town word supports a move", None)


def test_the_name_agreeing_with_the_stored_state_rejects_the_proposal():
    assert decide("ALBION SC San Diego 2015 Academy 1", "Albion SC Colorado", "CA", "CO") == ("reject", "CA")


def test_a_town_word_alone_never_overrides_both_sides():
    assert decide("Diego Maradona S.A.", "Diego Maradona Soccer Academy", "FL", "TX") == (
        "left: only a town word supports a move",
        None,
    )


def test_the_club_name_answers_only_when_the_team_name_is_silent_and_never_overrides():
    assert decide("G2012 Blue", "Idaho Rush", "UT", "ID") == ("approve", "ID")
    assert decide("G2012 Blue", "Idaho Rush", "UT", "NM") == ("left: the club name alone cannot override", None)


def test_a_club_state_the_locality_index_also_learned_still_counts_as_spelled():
    assert decide("G2012 Blue", "Colorado Rush", "UT", "CO") == ("approve", "CO")


def test_a_town_word_backed_by_the_club_spelling_the_same_state_can_move_the_team():
    assert decide("Boise Timbers 2012", "Idaho Rush", "WY", "ID") == ("approve", "ID")


def test_a_team_with_no_state_yet_can_be_filled():
    assert decide("Idaho Timbers 2012", "Timbers", None, "ID") == ("approve", "ID")


@pytest.mark.parametrize("suffix", PLACE_SUFFIXES)
def test_a_state_word_naming_a_county_town_or_region_is_left(suffix):
    assert decide(f"Washington {suffix.title()} SC - U14", "", "OK", "WA") == ("left: state word names a place", None)


def test_the_place_check_reads_across_punctuation_and_the_club_name():
    assert decide("Washington-County SC", "", "OK", "WA") == ("left: state word names a place", None)
    assert decide("G2012 Blue", "Washington County SC", "OK", "WA") == ("left: state word names a place", None)


def test_another_states_place_name_does_not_block_the_state_that_was_read():
    assert decide("Idaho Timbers 2012", "Washington County Rec", "WY", "ID") == ("approve", "ID")


@pytest.mark.parametrize(("word", "town_state"), sorted(STATE_NAMED_TOWNS))
def test_a_town_named_for_a_state_is_left_only_in_the_towns_state(word, town_state):
    state = STATE_NAME_TO_CODE[word.title()]
    other = "NE" if town_state != "NE" else "KS"
    name = f"{word.title()} Knights 2012"
    assert decide(name, "", town_state, state) == ("left: state word names a place", None)
    assert decide(name, "", other, state) == ("approve", state)


def test_an_affiliate_marker_naming_another_state_is_left():
    assert decide("Utah Royals 2015", "Utah Royals FC - AZ", "AZ", "UT") == (
        "left: an affiliate marker names another state",
        None,
    )
    assert decide("Boise Timbers FC-WY 2012", "Idaho Rush", "WY", "ID") == (
        "left: an affiliate marker names another state",
        None,
    )


def test_a_gotsport_answer_naming_another_state_leaves_the_row():
    assert decide("Colorado Edge 2013b", "Edge", "IL", "CO", provider="IL") == (
        "left: GotSport disagrees with the name",
        None,
    )
    assert decide("Colorado Edge 2013b", "Edge", "IL", "CO", provider="CO") == ("approve", "CO")


@pytest.mark.parametrize("source", ["operator", "tier_a"])
def test_a_name_never_moves_a_state_the_record_or_an_operator_set(source):
    assert decide("Idaho Timbers 2012", "Timbers", "WY", "ID", source=source) == (
        "left: stored state outranks a name",
        None,
    )


def test_a_name_never_moves_a_state_an_operator_approved():
    assert decide("Idaho Timbers 2012", "Timbers", "WY", "ID", source="tier_e", approved_states={("t1", "WY")}) == (
        "left: an operator approved the stored state",
        None,
    )


def test_a_name_never_restores_a_state_an_operator_reverted():
    assert decide("Idaho Timbers 2012", "Timbers", "WY", "ID", revert_blocks={("t1", "ID")}) == (
        "left: an operator reverted this state",
        None,
    )


def test_a_name_pointing_two_ways_is_left():
    assert decide("Idaho Diego FC", "", "UT", "ID") == ("left: name points two ways", None)


@pytest.mark.parametrize("name", ["Idaho Utah Cup 2012", "Utah Royals FC-AZ 2015", "Kansas City Blue 2012"])
def test_a_team_name_holding_a_state_it_cannot_place_never_lets_the_club_answer(name):
    assert decide(name, "Idaho Rush", "WY", "ID") == ("left: team name names a state it cannot place", None)


def test_a_spelled_state_is_not_let_through_when_the_town_words_disagree_among_themselves():
    locality = {**LOCALITY, "idaho": "ID"}
    assert decide("Idaho Diego FC", "", "UT", "ID", locality=locality) == ("left: name points two ways", None)


def test_a_non_us_reading_is_left():
    assert decide("Montreal Impact 2012", "", "NY", "QC") == ("left: name gives no state", None)


def test_a_team_moved_since_queued_is_left():
    moved = team("Colorado Elevation FC", "", "NM")
    assert classify(row("UT", "UT"), moved, LOCALITY, None) == ("left: team moved since queued", None)


def test_a_deprecated_team_is_left():
    assert classify(row("UT", "CO"), None, LOCALITY, None) == ("left: team deprecated", None)


def _refuse(message):
    return APIError({"message": message, "code": "P0001", "hint": None, "details": None})


APPLY_PARAMS = {
    "p_team_id",
    "p_expected_state_code",
    "p_state_code",
    "p_source",
    "p_confidence",
    "p_actor",
    "p_action",
    "p_reason",
}
LEDGER_ACTIONS = {"fill", "correct", "approve", "revert", "external", "confirm"}


class _Result:
    def __init__(self, data):
        self.data = data


class _Call:
    def __init__(self, db, name, params):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        return self.db.run(self.name, self.params)


class _Query:
    """A PostgREST request over one table: honours ``eq`` and ``update``; reads return only
    the selected columns, windowed by ``range``, and out of order unless ``order`` was called."""

    def __init__(self, db, rows):
        self.db, self.rows = db, rows
        self.columns, self.filters, self.window, self.values, self.ordered = None, [], None, None, False

    def select(self, columns):
        self.columns = columns.split(",")
        return self

    def update(self, values):
        self.values = values
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column):
        self.rows, self.ordered = sorted(self.rows, key=lambda r: r[column]), True
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        rows = [r for r in (self.rows if self.ordered else self.rows[::-1]) if self._matches(r)]
        if self.values is not None:
            self.db.calls.append("update team_state_review_queue")
            for r in rows:
                r.update(self.values)
            return _Result(rows)
        if self.window:
            rows = rows[self.window[0] : self.window[1] + 1]
        return _Result([{c: r[c] for c in self.columns} for r in rows])

    def _matches(self, r):
        return all(r.get(c) == v for c, v in self.filters)


class _Db:
    """The review queue and the teams it names, with the refusals the real RPCs make."""

    def __init__(self, queue=(), states=None, failing=()):
        self.queue = {r["id"]: {**r, "status": r.get("status", "pending")} for r in queue}
        self.states = dict(states or {})
        self.failing = set(failing)
        self.calls = []
        self.sent = []

    def table(self, name):
        assert name == "team_state_review_queue"
        return _Query(self, list(self.queue.values()))

    def rpc(self, name, params):
        return _Call(self, name, params)

    def run(self, name, params):
        self.calls.append(name)
        self.sent.append(params)
        if name == "apply_team_state":
            if set(params) != APPLY_PARAMS:
                raise _refuse(f"no apply_team_state({sorted(params)})")
            if not params["p_actor"] or params["p_action"] not in LEDGER_ACTIONS:
                raise _refuse("apply_team_state requires an actor and a ledger action")
            if self.states.get(params["p_team_id"]) != params["p_expected_state_code"]:
                return _Result(False)
            self.states[params["p_team_id"]] = params["p_state_code"]
            return _Result(True)
        if name != "reject_team_state" or set(params) != {"p_review_id", "p_reviewer"} or not params["p_reviewer"]:
            raise _refuse(f"no {name}({sorted(params)})")
        if params["p_review_id"] in self.failing:
            raise _refuse("canceling statement due to statement timeout")
        review_row = self.queue.get(params["p_review_id"])
        if review_row is None or review_row["status"] != "pending":
            raise _refuse(f"State review {params['p_review_id']} not found or already reviewed")
        review_row["status"] = "rejected"
        return _Result(True)


@pytest.fixture
def mirrored(monkeypatch):
    rows = []
    monkeypatch.setattr(review, "mirror_rankings", lambda sb, applied: rows.extend(applied) or len(applied))
    return rows


def test_approve_writes_as_tier_c_and_marks_the_row_approved_without_a_person_s_approval(mirrored):
    db = _Db([row("UT", "CO")], {"t1": "UT"})
    assert review.settle(db, row("UT", "CO"), "approve", "CO") == "approve"
    assert db.calls == ["apply_team_state", "update team_state_review_queue"]
    assert db.sent[0]["p_source"] == "tier_c" and db.sent[0]["p_actor"] == "review_state_queue_by_name"
    assert db.states["t1"] == "CO" and db.queue[7]["status"] == "approved"
    assert db.queue[7]["reviewed_by"] == "review_state_queue_by_name"
    assert [(m["team_id"], m["proposed"]) for m in mirrored] == [("t1", "CO")]


def test_set_writes_as_tier_c_under_its_own_actor_then_rejects_the_row(mirrored):
    db = _Db([row("UT", "UT")], {"t1": "UT"})
    assert review.settle(db, row("UT", "UT"), "set", "CO") == "set"
    assert db.calls == ["apply_team_state", "reject_team_state"]
    assert db.sent[0] == {
        "p_team_id": "t1",
        "p_expected_state_code": "UT",
        "p_state_code": "CO",
        "p_source": "tier_c",
        "p_confidence": 0.85,
        "p_actor": "review_state_queue_by_name",
        "p_action": "correct",
        "p_reason": "team name says CO; review 7",
    }
    assert db.sent[1] == {"p_review_id": 7, "p_reviewer": "review_state_queue_by_name"}
    assert db.states["t1"] == "CO" and db.queue[7]["status"] == "rejected"
    assert [(m["team_id"], m["proposed"]) for m in mirrored] == [("t1", "CO")]


def test_a_write_to_a_team_with_no_state_is_ledgered_as_a_fill(mirrored):
    db = _Db([row(None, "ID")], {"t1": None})
    assert review.settle(db, row(None, "ID"), "approve", "ID") == "approve"
    assert db.sent[0]["p_expected_state_code"] is None and db.sent[0]["p_action"] == "fill"


@pytest.mark.parametrize("action", ["approve", "set"])
def test_a_write_on_a_team_that_moved_lands_nothing_and_leaves_the_row_pending(mirrored, action):
    db = _Db([row("UT", "CO")], {"t1": "NM"})
    assert review.settle(db, row("UT", "CO"), action, "CO") == f"{action} skipped: team moved"
    assert db.calls == ["apply_team_state"]
    assert db.states["t1"] == "NM" and db.queue[7]["status"] == "pending" and mirrored == []


def test_approving_never_reopens_a_row_a_person_settled_meanwhile(mirrored):
    db = _Db([{**row("UT", "CO"), "status": "rejected"}], {"t1": "UT"})
    review.settle(db, row("UT", "CO"), "approve", "CO")
    assert db.queue[7]["status"] == "rejected"


def test_fetch_pending_reviews_reads_only_pending_rows_in_order_across_pages(monkeypatch):
    monkeypatch.setattr(review, "PAGE_SIZE", 2)
    queue = [row("UT", "CO", review_id=i) for i in range(1, 6)] + [
        {**row("UT", "CO", review_id=6), "status": "rejected"}
    ]
    assert [r["id"] for r in review.fetch_pending_reviews(_Db(queue))] == [1, 2, 3, 4, 5]


def test_provider_states_keeps_only_recent_mapped_answers_that_name_a_real_state(monkeypatch):
    cutoffs = []

    def probes(sb, cutoff):
        cutoffs.append(cutoff)
        return {
            "il": ("mapped", "IL"),
            "al": ("mapped", "AL"),
            "unmapped": ("unmapped code ON", "TX"),
            "blank": ("mapped", None),
        }

    monkeypatch.setattr(review, "fetch_recent_probes", probes)
    assert review.provider_states(None) == {"il": "IL"}
    window = datetime.now(timezone.utc) - cutoffs[0]
    assert timedelta(days=89) < window < timedelta(days=91)


def _run_main(monkeypatch, db, teams, argv, approved=frozenset(), reverted=frozenset()):
    monkeypatch.setattr(sys, "argv", ["review_state_queue_by_name.py", *argv])
    monkeypatch.setattr(review, "SUPABASE_URL", "https://example.test")
    monkeypatch.setattr(review, "SUPABASE_KEY", "test-key")
    monkeypatch.setattr(review, "create_client", lambda *a: db)
    monkeypatch.setattr(review, "fetch_live_teams", lambda sb: teams)
    monkeypatch.setattr(review, "build_locality_index", lambda teams: LOCALITY)
    monkeypatch.setattr(review, "provider_states", lambda sb: {})
    monkeypatch.setattr(review, "fetch_approved_states", lambda sb: set(approved))
    monkeypatch.setattr(review, "fetch_revert_blocks", lambda sb: set(reverted))
    review.main()


def test_a_dry_run_writes_nothing(monkeypatch, mirrored):
    db = _Db([row("UT", "UT")], {"t1": "UT"})
    _run_main(monkeypatch, db, [team("Colorado Elevation FC", "", "UT")], [])
    assert db.calls == [] and db.states["t1"] == "UT"


def test_dry_run_and_execute_together_are_refused(monkeypatch, mirrored):
    db = _Db([row("UT", "UT")], {"t1": "UT"})
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db, [team("Colorado Elevation FC", "", "UT")], ["--dry-run", "--execute"])
    assert db.calls == []


def test_execute_settles_each_decided_row_and_never_touches_a_left_one(monkeypatch, mirrored):
    teams = [
        team("Colorado Elevation FC", "", "UT", team_id="set"),
        team("Idaho Timbers", "", "WY", team_id="approve"),
        team("ALBION SC San Diego", "Albion SC Colorado", "CA", team_id="reject"),
        team("Boise Timbers", "", "WY", team_id="left"),
        team("Idaho Rapids", "", "WY", team_id="twice"),
        team("Idaho Surf", "", "WY", source="tier_e", team_id="approved"),
        team("Idaho Rush", "", "WY", team_id="reverted"),
    ]
    queue = [
        row("UT", "UT", review_id=1, team_id="set"),
        row("WY", "ID", review_id=2, team_id="approve"),
        row("CA", "CO", review_id=3, team_id="reject"),
        row("WY", "ID", review_id=4, team_id="left"),
        row("WY", "ID", review_id=5, team_id="twice"),
        row("WY", "ID", review_id=6, team_id="twice"),
        row("WY", "ID", review_id=8, team_id="approved"),
        row("WY", "ID", review_id=9, team_id="reverted"),
    ]
    db = _Db(queue, {t["team_id_master"]: t["state_code"] for t in teams}, failing={1})

    _run_main(monkeypatch, db, teams, ["--execute"], approved={("approved", "WY")}, reverted={("reverted", "ID")})

    # Review 1's rejection fails after its state landed; the rows after it are still settled.
    assert {i: r["status"] for i, r in db.queue.items()} == {
        1: "pending",
        2: "approved",
        3: "rejected",
        4: "pending",
        5: "approved",
        6: "pending",
        8: "pending",
        9: "pending",
    }
    assert db.states == {
        "set": "CO",
        "approve": "ID",
        "reject": "CA",
        "left": "WY",
        "twice": "ID",
        "approved": "WY",
        "reverted": "WY",
    }
