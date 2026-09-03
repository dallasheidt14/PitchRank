"""Reconciling against GotSport writes three columns and reports five.

The asymmetry is the whole point of the script and the only thing that keeps it safe
to run over a whole cohort. `team_name` is the provider's to overwrite; `club_name`
and `state_code` are filled only where ours is absent, because corrections there
belong to `assigning-team-states` and its ranked evidence; and `age_group` and
`gender` are never written at all, because `display_age_group` has returned U14 and
U12 for two teams of the same birth year (IMP-145).

Two earlier revisions of this suite were green against code that would have wrecked
the table, so the doubles below are written against a specific failure: **a fake that
is more forgiving than PostgREST proves nothing.** The first revision dropped the
column name from `eq`, so filtering on the wrong column passed. The second recorded
the call before `execute()` and never evaluated its filters, so a write carrying a
permanently-false predicate passed. `_FakeQuery` therefore evaluates every filter
against seeded rows on both the select and the update branch, honours `order` before
`range`, returns the rows an UPDATE actually matched, and `_FakeSupabase` raises on a
table nobody seeded rather than handing back an empty one.
"""

import csv
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from reconcile_teams_with_gotsport import (  # noqa: E402
    REPORTED_FIELDS,
    WRITABLE_FIELDS,
    apply_decision,
    classify_lookup,
    csv_safe,
    csv_unsafe,
    decide,
    describe_runtime,
    drop_colliding_renames,
    fetch_state_blocks,
    fetch_target_teams,
    is_retired_registration,
    log_row,
    next_failure_streak,
    parse_filters,
    plan_writes,
    printable,
    resolve_execute,
    revert,
    run_writes,
    validate_bounds,
    write_log,
)
from src.utils.gotsport_alias import fetch_gotsport_aliases, is_rankings_space_id  # noqa: E402

PID = "742007"
TEAM_ID = "11111111-1111-1111-1111-111111111111"


def _team(**overrides):
    team = {
        "team_id_master": TEAM_ID,
        "team_name": "Crossfire Premier B12 Red",
        "club_name": "Crossfire Premier",
        "state_code": "WA",
        "age_group": "u14",
        "gender": "Male",
        "state_source": None,
        "state_confidence": None,
        "is_deprecated": False,
    }
    team.update(overrides)
    return team


def _resolved(**overrides):
    resolved = {
        "name": "Crossfire Premier B12 Red",
        "club_name": "Crossfire Premier",
        "state_code": "WA",
        "age_group": "u14",
        "gender": "Male",
    }
    resolved.update(overrides)
    return resolved


def _decide(team, resolved, pid=PID, state_blocks=frozenset()):
    return decide(team, pid, resolved, "resolved", state_blocks)


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Evaluates its filters, so a wrongly-scoped query matches nothing here too."""

    def __init__(self, table, rows, recorder):
        self.table = table
        self._rows = rows
        self._recorder = recorder
        self._filters = []
        self._payload = None
        self._order = None
        self._range = None

    def select(self, *_):
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def is_(self, column, value):
        self._filters.append(("is", column, value))
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def update(self, payload):
        self._payload = dict(payload)
        return self

    def _matched(self):
        rows = list(self._rows)
        for kind, column, value in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(column) == value]
            elif kind == "in":
                rows = [r for r in rows if r.get(column) in value]
            elif kind == "is":
                rows = [r for r in rows if r.get(column) is None]
        if self._order:
            rows.sort(key=lambda r: r.get(self._order[0]) or "", reverse=self._order[1])
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        return rows

    def execute(self):
        rows = self._matched()
        if self._payload is not None:
            self._recorder.append(
                {"kind": "update", "table": self.table, "payload": self._payload, "filters": list(self._filters)}
            )
            for row in rows:
                row.update(self._payload)
        return _Result(rows)


class _FakeRpc:
    """Records on execute() only, so a call that is never sent cannot look like one."""

    def __init__(self, name, params, recorder, returns):
        self._name = name
        self._params = params
        self._recorder = recorder
        self._returns = returns

    def execute(self):
        self._recorder.append({"kind": "rpc", "name": self._name, "params": self._params})
        return _Result(self._returns)


class _FakeSupabase:
    def __init__(self, tables=None, rpc_returns=True):
        self.tables = {"rankings_full": [], "team_state_audit": [], **(tables or {})}
        self.recorder = []
        self.rpc_returns = rpc_returns

    def table(self, name):
        if name not in self.tables:
            raise AssertionError(f"unexpected table {name!r} — seed it or the test proves nothing")
        return _FakeQuery(name, self.tables[name], self.recorder)

    def rpc(self, name, params):
        return _FakeRpc(name, params, self.recorder, self.rpc_returns)


def _supabase(team=None, rpc_returns=True, **tables):
    rows = [dict(team)] if team is not None else []
    return _FakeSupabase({"teams": rows, **tables}, rpc_returns=rpc_returns)


def _updates(supabase):
    return [c for c in supabase.recorder if c["kind"] == "update"]


def _rpcs(supabase):
    return [c for c in supabase.recorder if c["kind"] == "rpc"]


# --- the decision layer ---------------------------------------------------------


def test_a_changed_name_is_overwritten():
    decision = _decide(_team(), _resolved(name="Crossfire Premier B12 Blue"))
    assert decision.action == "updated"
    assert decision.updates == {"team_name": "Crossfire Premier B12 Blue"}


def test_an_unchanged_name_is_not_rewritten():
    assert _decide(_team(), _resolved()).action == "skipped_already_matching"


def test_a_padded_stored_name_is_a_real_difference():
    """The decision compares the raw value because the write predicate filters on it;
    stripping here would report a match the pre-image would never have found."""
    decision = _decide(_team(team_name="  Crossfire Premier B12 Red  "), _resolved())
    assert decision.updates == {"team_name": "Crossfire Premier B12 Red"}


def test_a_name_is_withheld_when_gotsport_files_the_team_under_another_cohort():
    """Measured on a live AZ u13 slice: every row GotSport called U12 played u13
    opposition — 243 games across seven teams — and the names those records carried
    named other coaches, or another birth year outright."""
    decision = _decide(_team(), _resolved(name="U12B Arriola", age_group="u12"))
    assert decision.updates == {}
    assert decision.blocked == ("team_name",)


def test_a_name_is_taken_when_the_cohorts_agree():
    """The thirteen cohort-matching rows in that same slice all offered a sane name."""
    decision = _decide(_team(), _resolved(name="14B Antunez", age_group="u14"))
    assert decision.updates == {"team_name": "14B Antunez"}


def test_a_provider_with_no_cohort_does_not_veto_the_name():
    """display_age_group is "Open" for adult teams and absent on some records; an
    absent cohort is not a disagreement."""
    decision = _decide(_team(), _resolved(name="Crossfire Premier B12 Blue", age_group=""))
    assert decision.updates == {"team_name": "Crossfire Premier B12 Blue"}


def test_the_cohort_veto_never_blocks_a_club_or_state_fill():
    """Age gates the name only. A club fill is evidence-independent of the cohort, and
    withholding it would lose the fills this tool exists for."""
    decision = _decide(_team(club_name="", state_code=""), _resolved(name="U12B Arriola", age_group="u12"))
    assert set(decision.updates) == {"club_name", "state_code"}
    assert decision.blocked == ("team_name",)


def test_a_real_name_is_never_replaced_by_a_placeholder():
    assert _decide(_team(), _resolved(name=f"unknown_{PID}")).updates == {}


@pytest.mark.parametrize(
    "name",
    ["zz old - B13 Black", "ZZ Old B13", "B13 Black - OLD", "do not use 2013", "2013 duplicate", "DELETE 2013"],
)
def test_a_retired_registration_is_never_taken_as_a_name(name):
    """Clubs park dead squads under these markers; a live WA slice offered
    'zz old - B13 Black' for a team we call '2013 Black'."""
    assert is_retired_registration(name)
    assert _decide(_team(), _resolved(name=name)).updates == {}


@pytest.mark.parametrize("name", ["Crossfire Premier B12 Blue", "Bold FC 13G", "Zenith United"])
def test_a_real_name_is_not_mistaken_for_a_retired_one(name):
    assert not is_retired_registration(name)


@pytest.mark.parametrize("name", ["", "   ", "X", None])
def test_a_real_name_is_never_replaced_by_an_unusable_one(name):
    assert _decide(_team(), _resolved(name=name)).updates == {}


def test_a_missing_club_is_filled():
    assert _decide(_team(club_name=""), _resolved()).updates == {"club_name": "Crossfire Premier"}


def test_a_placeholder_club_counts_as_missing():
    assert _decide(_team(club_name="No Club Selection"), _resolved()).updates == {"club_name": "Crossfire Premier"}


def test_a_placeholder_club_is_never_written():
    assert _decide(_team(club_name=""), _resolved(club_name="No Club Selection")).updates == {}


def test_a_club_we_already_have_is_reported_not_overwritten():
    decision = _decide(_team(club_name="Crossfire Select"), _resolved())
    assert decision.action == "conflicts_only"
    assert decision.conflicts == ("club_name",)


def test_a_missing_state_is_filled():
    assert _decide(_team(state_code=""), _resolved()).updates == {"state_code": "WA"}


def test_a_state_we_already_have_is_reported_not_overwritten():
    assert _decide(_team(state_code="OR"), _resolved()).action == "conflicts_only"


def test_a_state_an_operator_reverted_is_never_re_filled():
    """assign_team_states honours that rejection forever; re-filling it from the same
    evidence would undo the operator's decision with a `fill` stamp."""
    decision = _decide(_team(state_code=""), _resolved(), state_blocks={(TEAM_ID, "WA")})
    assert decision.updates == {}
    assert decision.blocked == ("state_code",)
    assert decision.action == "conflicts_only"


@pytest.mark.parametrize("name,provider_value", [("age_group", "u13"), ("gender", "Female")])
def test_a_reported_field_is_never_written(name, provider_value):
    decision = _decide(_team(), _resolved(**{name: provider_value}))
    assert name not in decision.updates
    assert decision.provider[name] == provider_value


def test_a_reported_field_stays_out_of_an_update_that_happens_anyway():
    """Gender never vetoes and never writes, so a rename proceeds beside a gender
    disagreement and must not carry it into the payload."""
    decision = _decide(_team(), _resolved(name="Crossfire Premier B12 Blue", age_group="u14", gender="Female"))
    assert set(decision.updates) == {"team_name"}
    assert not set(decision.updates) & set(REPORTED_FIELDS)
    assert decision.provider["gender"] == "Female"


def test_a_reported_field_does_not_raise_a_conflict():
    """display_age_group is the registered event cohort, so a month after the Aug 1
    rollover it would bury every club and state disagreement the count is for."""
    assert _decide(_team(), _resolved(age_group="u13", gender="Female")).conflicts == ()


def test_a_conflict_is_recorded_even_when_another_field_is_filled():
    decision = _decide(_team(club_name="", state_code="OR"), _resolved())
    assert decision.action == "updated"
    assert decision.conflicts == ("state_code",)


def test_a_team_with_no_gotsport_alias_is_left_alone():
    assert decide(_team(), None, None, "no_alias").action == "skipped_no_alias"


@pytest.mark.parametrize("outcome,action", [("gone", "skipped_gone"), ("failed", "skipped_lookup_failed")])
def test_an_unresolved_lookup_never_writes(outcome, action):
    decision = decide(_team(), PID, None, outcome)
    assert (decision.action, decision.updates) == (action, {})


# --- telling a dead registration from a block -----------------------------------


class _CachingResolver:
    def __init__(self, cache):
        self.cache = cache


def test_a_404_is_an_answer_not_a_failure():
    assert classify_lookup(_CachingResolver({PID: {}}), PID, {}) == "gone"


def test_a_transient_failure_is_a_failure():
    assert classify_lookup(_CachingResolver({}), PID, {}) == "failed"


def test_a_body_naming_no_team_is_a_failure_not_a_match():
    """An HTTP 200 interstitial parses truthy with every identity field empty. Read as
    a match it would reset the abort counter, defeating --abort-after entirely."""
    empty = {"name": "", "club_name": "", "state_code": None, "age_group": None, "gender": None}
    assert classify_lookup(_CachingResolver({PID: empty}), PID, empty) == "failed"


def test_a_real_answer_resolves():
    assert classify_lookup(_CachingResolver({PID: _resolved()}), PID, _resolved()) == "resolved"


# --- the write layer ------------------------------------------------------------


def test_the_forward_write_is_filtered_to_one_team():
    """An unfiltered UPDATE would rewrite team_name across every row in the table."""
    team = _team()
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved(name="Crossfire Premier B12 Blue")))

    assert len(_updates(supabase)) == 1
    assert ("eq", "team_id_master", TEAM_ID) in _updates(supabase)[0]["filters"]


def test_the_forward_write_carries_only_writable_columns():
    team = _team(club_name="")
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved(name="Crossfire Premier B12 Blue", age_group="u13")))

    payload = _updates(supabase)[0]["payload"]
    assert set(payload) <= set(WRITABLE_FIELDS)
    assert not set(payload) & set(REPORTED_FIELDS)


def test_the_forward_write_carries_the_pre_image_so_a_moved_row_is_refused():
    team = _team()
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved(name="Crossfire Premier B12 Blue")))
    assert ("eq", "team_name", "Crossfire Premier B12 Red") in _updates(supabase)[0]["filters"]


def test_a_null_pre_image_is_filtered_as_is_null():
    team = _team(club_name=None)
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved()))
    assert ("is", "club_name", "null") in _updates(supabase)[0]["filters"]


def test_a_placeholder_pre_image_is_filtered_on_its_raw_value():
    """stored_value() reads a placeholder club as absent; filtering on IS NULL there
    would match nothing and report a live row as changed."""
    team = _team(club_name="No Club Selection")
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved()))
    assert ("eq", "club_name", "No Club Selection") in _updates(supabase)[0]["filters"]


def test_a_row_that_moved_since_the_read_is_reported_not_counted():
    decision = _decide(_team(), _resolved(name="Crossfire Premier B12 Blue"))
    supabase = _supabase(_team(team_name="Renamed By Someone Else"))
    assert apply_decision(supabase, decision) == "skipped_changed_since_read"
    assert decision.applied == ()


def test_state_is_written_through_the_ledgered_path_not_the_table():
    team = _team(state_code="")
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved()))

    assert [c["name"] for c in _rpcs(supabase)] == ["apply_team_state"]
    params = _rpcs(supabase)[0]["params"]
    assert (params["p_state_code"], params["p_action"], params["p_source"]) == ("WA", "fill", "tier_a")
    assert not [c for c in _updates(supabase) if c["table"] == "teams"]


def test_the_state_pre_image_is_the_raw_value_not_a_coerced_null():
    """An empty CHAR(2) is not NULL, so sending NULL as the expected value makes the
    RPC's IS NOT DISTINCT FROM predicate refuse a row that never moved."""
    team = _team(state_code="")
    supabase = _supabase(team)
    apply_decision(supabase, _decide(team, _resolved()))
    assert _rpcs(supabase)[0]["params"]["p_expected_state_code"] == ""


def test_a_filled_state_is_mirrored_onto_the_board():
    """apply_team_state writes teams only, and the boards read rankings_full, which
    nothing but Monday's ranking run refreshes."""
    team = _team(state_code="")
    supabase = _supabase(team, rankings_full=[{"team_id": TEAM_ID, "state_code": None}])
    apply_decision(supabase, _decide(team, _resolved()))

    mirror = [c for c in _updates(supabase) if c["table"] == "rankings_full"]
    assert mirror and mirror[0]["payload"] == {"state_code": "WA"}
    assert ("eq", "team_id", TEAM_ID) in mirror[0]["filters"]


def test_a_refused_state_is_not_mirrored():
    team = _team(state_code="")
    supabase = _supabase(team, rpc_returns=False, rankings_full=[{"team_id": TEAM_ID, "state_code": None}])
    apply_decision(supabase, _decide(team, _resolved()))
    assert not [c for c in _updates(supabase) if c["table"] == "rankings_full"]


def test_a_half_applied_row_records_what_landed_and_stays_revertible():
    """The table PATCH and the RPC commit separately. Folding them into one boolean
    logged a committed write as skipped, and revert only replays `updated` rows."""
    team = _team(club_name="", state_code="")
    decision = _decide(team, _resolved(name="Crossfire Premier B12 Blue"))
    assert set(decision.updates) == {"team_name", "club_name", "state_code"}

    supabase = _supabase(team, rpc_returns=False)
    action = apply_decision(supabase, decision)

    assert action == "updated"
    assert decision.applied == ("club_name", "team_name")
    assert decision.written() == ("club_name", "team_name")


def test_a_landed_state_survives_a_refused_table_write():
    """The other half of the same split: returning early on the table result would
    lose a ledgered state fill that did commit, and the log would not carry it."""
    team = _team(state_code="")
    decision = _decide(team, _resolved(name="Crossfire Premier B12 Blue"))
    assert set(decision.updates) == {"team_name", "state_code"}

    supabase = _supabase(_team(team_name="Renamed By Someone Else", state_code=""))
    action = apply_decision(supabase, decision)

    assert action == "updated"
    assert decision.applied == ("state_code",)


# --- name collisions within a slice ---------------------------------------------


def _rename(team_name, club, new_name, team_id):
    team = _team(team_id_master=team_id, team_name=team_name, club_name=club)
    return _decide(team, _resolved(name=new_name))


def test_a_name_two_teams_would_share_is_given_to_neither():
    """Replays a live AZ u13 run: four teams from four different clubs were all
    renamed to `U13G DPL`, each from a name that had said which club it was."""
    decisions = [
        _rename("AZ Arsenal 2014 Teal VN", "Arizona Arsenal Soccer Club", "U13G DPL", "t1"),
        _rename("Arizona Soccer Club 2014 Pre-DPL", "Arizona Soccer Club", "U13G DPL", "t2"),
        _rename("Excel Soccer Academy 2014 G", "Excel Soccer Academy", "U13G DPL", "t3"),
        _rename("PRFC West Valley 2014 Pre-Elite", "Phoenix Rising FC", "U13G DPL", "t4"),
    ]
    assert all(d.updates == {"team_name": "U13G DPL"} for d in decisions)

    assert drop_colliding_renames(decisions) == 4

    assert all(d.updates == {} for d in decisions)
    assert all("team_name" in d.blocked for d in decisions)
    assert all(d.action == "conflicts_only" for d in decisions)


def test_a_rename_onto_a_name_another_team_already_holds_is_withheld():
    decisions = [
        _rename("Arizona SC 2014 Pre-GA ASPIRE", "Arizona Soccer Club", "ECNL RL G2013/14", "t1"),
        _decide(_team(team_id_master="t2", team_name="ECNL RL G2013/14"), _resolved(name="ECNL RL G2013/14")),
    ]
    assert drop_colliding_renames(decisions) == 1
    assert decisions[0].updates == {}
    assert decisions[1].updates == {}


def test_a_distinct_rename_is_untouched():
    decisions = [
        _rename("2014 Hinds", "RSL Arizona South", "14B Hinds", "t1"),
        _rename("2014 Geoff", "RSL Arizona South", "14B Geoff", "t2"),
    ]
    assert drop_colliding_renames(decisions) == 0
    assert [d.updates["team_name"] for d in decisions] == ["14B Hinds", "14B Geoff"]


def test_two_teams_that_already_shared_a_name_are_left_alone():
    """Not this run's doing, and renaming one of them away is a decision nothing here
    has evidence for."""
    decisions = [
        _decide(_team(team_id_master="t1", team_name="2014 Blue"), _resolved(name="2014 Blue")),
        _decide(_team(team_id_master="t2", team_name="2014 Blue"), _resolved(name="2014 Blue")),
    ]
    assert drop_colliding_renames(decisions) == 0
    assert all(not d.blocked for d in decisions)


def test_a_collision_never_withholds_a_club_or_state_fill():
    decisions = [
        _decide(_team(team_id_master="t1", club_name="", state_code=""), _resolved(name="U13G DPL")),
        _rename("Other Team", "Other Club", "U13G DPL", "t2"),
    ]
    drop_colliding_renames(decisions)
    assert set(decisions[0].updates) == {"club_name", "state_code"}
    assert decisions[0].action == "updated"


def test_the_write_list_cannot_be_obtained_without_the_collision_pass():
    """The guard runs where `planned` is computed, so skipping it is not a silent
    omission — a caller would have to rebuild the filter to bypass it."""
    decisions = [
        _rename("AZ Arsenal 2014 Teal VN", "Arizona Arsenal Soccer Club", "U13G DPL", "t1"),
        _rename("Excel Soccer Academy 2014 G", "Excel Soccer Academy", "U13G DPL", "t2"),
        _rename("2014 Hinds", "RSL Arizona South", "14B Hinds", "t3"),
    ]
    planned, collisions = plan_writes(decisions)

    assert collisions == 2
    assert [d.team["team_id_master"] for d in planned] == ["t3"]


# --- the dry-run gate -----------------------------------------------------------


@pytest.mark.parametrize(
    "execute_flag,dry_run_flag,expected", [(False, False, False), (True, False, True), (True, True, False)]
)
def test_asking_for_both_modes_yields_the_preview(execute_flag, dry_run_flag, expected):
    assert resolve_execute(execute_flag, dry_run_flag) is expected


def test_a_preview_issues_no_write_at_all():
    """The one line between a preview and a service-role batch over a whole cohort."""
    team = _team()
    supabase = _supabase(team)
    decision = _decide(team, _resolved(name="Crossfire Premier B12 Blue"))

    run_writes(supabase, [decision], execute=False)

    assert supabase.recorder == []
    assert decision.applied is None


def test_executing_issues_the_write():
    team = _team()
    supabase = _supabase(team)
    run_writes(supabase, [_decide(team, _resolved(name="Crossfire Premier B12 Blue"))], execute=True)
    assert len(_updates(supabase)) == 1


# --- selecting the slice --------------------------------------------------------


def _teams_table(n):
    return [
        {
            "team_id_master": f"{i:040d}",
            "team_name": f"Team {n - i:04d}",
            "club_name": "",
            "state_code": "WA",
            "age_group": "u14",
            "gender": "Male",
            "state_source": None,
            "state_confidence": None,
            "is_deprecated": False,
        }
        for i in range(n)
    ]


def test_the_slice_is_the_first_n_of_the_whole_cohort_not_of_the_first_page():
    """Breaking out of pagination before sorting pins every run to the lowest UUIDs,
    so no re-run can reach the rest of the cohort."""
    supabase = _FakeSupabase({"teams": _teams_table(1500)})
    teams, matched = fetch_target_teams(supabase, ["u14"], [], 5)

    assert matched == 1500
    assert [t["team_name"] for t in teams] == ["Team 0001", "Team 0002", "Team 0003", "Team 0004", "Team 0005"]


def test_an_offset_advances_past_a_batch_already_done():
    supabase = _FakeSupabase({"teams": _teams_table(1500)})
    teams, _ = fetch_target_teams(supabase, ["u14"], [], 3, offset=5)
    assert [t["team_name"] for t in teams] == ["Team 0006", "Team 0007", "Team 0008"]


def test_no_cap_returns_every_matching_team():
    supabase = _FakeSupabase({"teams": _teams_table(1500)})
    teams, matched = fetch_target_teams(supabase, ["u14"], [], None)
    assert (len(teams), matched) == (1500, 1500)


def test_deprecated_teams_are_never_in_scope():
    rows = _teams_table(3)
    rows[0]["is_deprecated"] = True
    supabase = _FakeSupabase({"teams": rows})
    teams, _ = fetch_target_teams(supabase, ["u14"], [], None)
    assert len(teams) == 2


def test_a_cohort_filter_excludes_other_cohorts():
    rows = _teams_table(3)
    rows[0]["age_group"] = "u15"
    supabase = _FakeSupabase({"teams": rows})
    teams, matched = fetch_target_teams(supabase, ["u14"], [], None)
    assert matched == 2


def test_revert_blocks_are_read_for_the_slice():
    audit = [
        {"team_id_master": TEAM_ID, "old_state_code": "WA", "action": "revert"},
        {"team_id_master": TEAM_ID, "old_state_code": "OR", "action": "fill"},
    ]
    supabase = _FakeSupabase({"teams": [], "team_state_audit": audit})
    assert fetch_state_blocks(supabase, [TEAM_ID]) == {(TEAM_ID, "WA")}


# --- the alias lookup -----------------------------------------------------------


def _alias_tables(rows):
    return {"teams": [], "providers": [{"id": "gs", "code": "gotsport"}], "team_alias_map": rows}


def _alias(team_id, pid, status="approved"):
    return {"team_id_master": team_id, "provider_team_id": pid, "review_status": status, "provider_id": "gs"}


@pytest.mark.parametrize("order", [["742007", "813000", "900000"], ["900000", "742007", "813000"]])
def test_the_newest_registration_wins_whatever_order_rows_arrive_in(order):
    """PostgREST supplies no ordering here, so a fixture that happens to end on the
    newest id would pass against unconditional assignment."""
    supabase = _FakeSupabase(_alias_tables([_alias("a", pid) for pid in order]))
    assert fetch_gotsport_aliases(supabase, ["a"]) == {"a": "900000"}


def test_an_unapproved_alias_never_speaks_for_a_team():
    supabase = _FakeSupabase(_alias_tables([_alias("a", "742007"), _alias("a", "900000", "pending")]))
    assert fetch_gotsport_aliases(supabase, ["a"]) == {"a": "742007"}


def test_every_chunk_of_a_large_batch_is_looked_up():
    """--limit defaults to 500, so production always enters the chunking loop. A
    mistyped slice resolves nothing past the first hundred and reports it as
    skipped_no_alias, with no error anywhere."""
    team_ids = [f"team-{i:04d}" for i in range(250)]
    supabase = _FakeSupabase(_alias_tables([_alias(t, str(700000 + i)) for i, t in enumerate(team_ids)]))

    aliases = fetch_gotsport_aliases(supabase, team_ids)

    assert len(aliases) == 250
    assert aliases["team-0249"] == str(700000 + 249)


def test_no_gotsport_provider_resolves_nothing():
    supabase = _FakeSupabase({"teams": [], "providers": [], "team_alias_map": []})
    assert fetch_gotsport_aliases(supabase, ["a"]) == {}


@pytest.mark.parametrize("pid", ["3000001", "Playoffs AWinner", "", "٧٤٢٠٠٧", "²", "12345678"])
def test_an_unusable_provider_id_is_never_probed(pid):
    """Unicode digits pass str.isdigit() and reach the query string verbatim; "²"
    passes it and then raises in int(). See .claude/rules/data-safety.md."""
    assert is_rankings_space_id(pid) is False


def test_a_rankings_space_id_is_probed():
    assert is_rankings_space_id("742007") is True


# --- the log and the undo -------------------------------------------------------


def _write_run(tmp_path, decision, run_mode="execute"):
    path = tmp_path / "log.csv"
    write_log([log_row(decision, run_mode)], path)
    return path


def test_the_undo_reads_the_schema_the_run_actually_writes(tmp_path):
    """Both sides hand-writing the header pins the test author's idea of the format,
    not the one production emits: renaming the columns kept such a suite green."""
    team = _team(club_name="")
    decision = _decide(team, _resolved())
    supabase = _supabase(_team(club_name="Crossfire Premier"))

    counts = revert(supabase, _write_run(tmp_path, decision), execute=True)

    assert counts["reverted"] == 1
    assert _updates(supabase)[0]["payload"] == {"club_name": None}


def test_the_undo_restores_an_empty_name_as_empty_not_null(tmp_path):
    """teams.team_name is NOT NULL, so restoring None aborts the revert mid-batch."""
    team = _team(team_name="")
    decision = _decide(team, _resolved())
    supabase = _supabase(_team(team_name="Crossfire Premier B12 Red"))

    revert(supabase, _write_run(tmp_path, decision), execute=True)

    assert _updates(supabase)[0]["payload"] == {"team_name": ""}


def test_the_undo_restores_the_provenance_the_fill_overwrote(tmp_path):
    """Sending this script's own source on a revert leaves a team with no state still
    claiming GotSport put one there; the SQL revert restores the prior pair."""
    team = _team(state_code="", state_source="tier_c", state_confidence=0.85)
    decision = _decide(team, _resolved())
    supabase = _supabase(_team(state_code="WA"), rankings_full=[{"team_id": TEAM_ID, "state_code": "WA"}])

    revert(supabase, _write_run(tmp_path, decision), execute=True)

    params = _rpcs(supabase)[0]["params"]
    assert params["p_action"] == "revert"
    assert params["p_expected_state_code"] == "WA"
    assert params["p_state_code"] is None
    assert (params["p_source"], params["p_confidence"]) == ("tier_c", 0.85)


def test_the_undo_mirrors_the_restored_state_onto_the_board(tmp_path):
    team = _team(state_code="")
    decision = _decide(team, _resolved())
    supabase = _supabase(_team(state_code="WA"), rankings_full=[{"team_id": TEAM_ID, "state_code": "WA"}])

    revert(supabase, _write_run(tmp_path, decision), execute=True)

    mirror = [c for c in _updates(supabase) if c["table"] == "rankings_full"]
    assert mirror and mirror[0]["payload"] == {"state_code": None}


def test_the_undo_refuses_a_column_the_run_could_never_have_written(tmp_path):
    """The payload keys are column names on a service-role write, and the log carries
    stored_age_group — the one column IMP-145 says nothing may write."""
    path = _write_run(tmp_path, _decide(_team(club_name=""), _resolved()))
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0]["written_fields"] = "age_group"
    write_log(rows, path)

    supabase = _supabase(_team())
    assert revert(supabase, path, execute=True)["refused_shape"] == 1
    assert supabase.recorder == []


@pytest.mark.parametrize(
    "column,value",
    [("team_id_master", "not-a-uuid"), ("stored_state_code", "WASHINGTON"), ("stored_team_name", "x" * 201)],
)
def test_the_undo_refuses_a_row_that_is_not_shaped_like_ours(tmp_path, column, value):
    """The row it targets and the values it writes come from the same untrusted file."""
    path = _write_run(tmp_path, _decide(_team(club_name=""), _resolved()))
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0][column] = value
    write_log(rows, path)

    supabase = _supabase(_team())
    assert revert(supabase, path, execute=True)["refused_shape"] == 1
    assert supabase.recorder == []


def test_the_undo_refuses_a_preview_log(tmp_path):
    """A dry run records its planned rows so the operator can read them; replaying
    them would overwrite live values with a snapshot that never left the database."""
    with pytest.raises(ValueError, match="dry-run"):
        revert(_supabase(_team()), _write_run(tmp_path, _decide(_team(club_name=""), _resolved()), "dry-run"), True)


def test_the_undo_refuses_a_row_that_changed_since_the_run(tmp_path):
    decision = _decide(_team(club_name=""), _resolved())
    supabase = _supabase(_team(club_name="Someone Else Set This"))

    counts = revert(supabase, _write_run(tmp_path, decision), execute=True)

    assert (counts["reverted"], counts["refused_changed"]) == (0, 1)


def test_the_undo_writes_nothing_without_execute(tmp_path):
    supabase = _supabase(_team())
    revert(supabase, _write_run(tmp_path, _decide(_team(), _resolved(name="X Blue"))), execute=False)
    assert supabase.recorder == []


def test_the_log_survives_being_rewritten(tmp_path):
    """It is the only way back from a service-role batch, and it is rewritten once the
    writes finish; truncating in place would lose the first copy on a failed second."""
    path = tmp_path / "log.csv"
    decision = _decide(_team(club_name=""), _resolved())
    write_log([log_row(decision, "execute")], path)
    decision.applied = ("club_name",)
    write_log([log_row(decision, "execute")], path)

    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    assert len(rows) == 1 and rows[0]["written_fields"] == "club_name"
    assert not list(tmp_path.glob("*.tmp"))


# --- CSV safety and terminal safety ---------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "=cmd|'/c calc'!A1",
        "+1",
        "-1",
        "@SUM(A1)",
        "\t=x",
        "'96 Elite",
        "'=SUM(1)",
        "'-FC",
        "'@evil",
        "''=x",
        "Crossfire",
        "",
    ],
)
def test_a_defanged_value_round_trips(value):
    """The log is both the operator's report and the undo's input, so the encoding has
    to be injective — `=x` and `'=x` must not both encode to `'=x`."""
    assert csv_unsafe(csv_safe(value)) == value


def test_a_formula_is_inert_in_the_written_log():
    assert csv_safe('=HYPERLINK("http://evil")').startswith("'=")


def test_a_defanged_name_is_not_written_back_to_the_database(tmp_path):
    team = _team(team_name="=OLD()")
    decision = _decide(team, _resolved(name="Crossfire Premier B12 Blue"))
    supabase = _supabase(_team(team_name="Crossfire Premier B12 Blue"))

    revert(supabase, _write_run(tmp_path, decision), execute=True)

    assert _updates(supabase)[0]["payload"] == {"team_name": "=OLD()"}


@pytest.mark.parametrize("value", ["a\rb", "a\x1b[2Jb", "a\nb", "a\x00b"])
def test_a_control_character_never_reaches_the_preview(value):
    """The dry run is the only human gate, and a bare \\r repaints the whole line."""
    assert all(c.isprintable() for c in printable(value))


# --- run control ----------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [("U14", ["u14"]), ("u14,U15", ["u14", "u15"]), ("14", ["u14"])])
def test_the_age_filter_accepts_the_labels_people_type(raw, expected):
    assert parse_filters(raw, "")[0] == expected


@pytest.mark.parametrize("raw", ["u14,u4x", "u14,,u4x", "u4x,"])
def test_an_unrecognized_age_filter_is_refused(raw):
    """Silently dropping it would scan every cohort at 3s a team. The empty segment is
    the case that pairing raw input against a filtered list gets wrong."""
    with pytest.raises(ValueError, match="u4x"):
        parse_filters(raw, "")


def test_the_state_filter_is_upper_cased():
    assert parse_filters("", "wa, or")[1] == ["WA", "OR"]


@pytest.mark.parametrize("calls,delay,expected", [(8, 3.0, "24 sec"), (485, 3.0, "24 min"), (0, 3.0, "0 sec")])
def test_a_short_run_is_estimated_in_seconds(calls, delay, expected):
    assert describe_runtime(calls, delay) == expected


@pytest.mark.parametrize("limit,offset", [(-1, 0), (0, -1), (-5, -5)])
def test_a_negative_window_is_refused(limit, offset):
    """`rows[:-1]` silently drops the last team while reporting a deliberate cap."""
    with pytest.raises(ValueError, match="negative"):
        validate_bounds(limit, offset)


@pytest.mark.parametrize("limit,offset", [(0, 0), (500, 0), (25, 500)])
def test_a_valid_window_is_accepted(limit, offset):
    assert validate_bounds(limit, offset) is None


def test_a_failed_lookup_advances_the_streak():
    assert next_failure_streak(3, "failed") == 4


@pytest.mark.parametrize("outcome", ["resolved", "gone"])
def test_an_answered_lookup_clears_the_streak(outcome):
    """A 404 is the origin answering, so it proves the endpoint is up. Leaving it
    merely unchanged aborts a responsive run on (failed, gone) nine times over."""
    assert next_failure_streak(9, outcome) == 0


def test_a_team_with_no_alias_neither_counts_nor_clears():
    """No call was made, so it is evidence of nothing either way."""
    assert next_failure_streak(4, "no_alias") == 4


def test_a_run_interleaving_dead_registrations_never_aborts():
    streak = 0
    for outcome in ["failed", "gone"] * 9 + ["failed"]:
        streak = next_failure_streak(streak, outcome)
        assert streak < 10


def test_a_sustained_block_aborts():
    streak = 0
    for _ in range(10):
        streak = next_failure_streak(streak, "failed")
    assert streak == 10
