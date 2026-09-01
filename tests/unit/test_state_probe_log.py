"""What a GotSport probe records, including the probes that change nothing.

The tier's whole cost is the HTTP call, and it is paid whether or not the answer is kept.
Only a probe that *moves* a state leaves a trace anywhere else -- the audit table is
trigger-written and the tier_a stamp lands only on a write -- so without this ledger an
agreement, a 404 and a team nobody ever asked about are indistinguishable afterwards.
These cases pin the outcomes that produce no state change, because those are the ones
that vanish silently when the writer regresses.
"""

import inspect
import os
import re
import sys
import threading
from collections import Counter

import pytest
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.assign_team_states as assign  # noqa: E402
from scripts.assign_team_states import (  # noqa: E402
    ACTOR,
    NO_ALIAS_OUTCOME,
    PROBE_LOG_TABLE,
    build_snapshot,
    probe_associations,
    probe_log_row,
    write_probe_log,
)
from tests.unit.test_assign_team_states import team  # noqa: E402
from tests.unit.test_team_state_provenance_migration import (  # noqa: E402
    _split_top_level,
    _table,
)


class Response:
    """Enough of ``requests.Response`` for ``probe`` to branch on."""

    def __init__(self, status_code=200, payload=None, content=b"{}"):
        self.status_code = status_code
        self.content = content
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeClient:
    """A Supabase stand-in that records a write only once it is executed."""

    def __init__(self, fail_on_execute=None):
        self.writes = []  # (table, rows, thread name), one per executed insert
        self.insert_kwargs = []
        self.fail_on_execute = fail_on_execute

    def table(self, name):
        return _FakeTable(self, name)


class _FakeTable:
    def __init__(self, client, name):
        self._client = client
        self._name = name

    def insert(self, rows, **kwargs):
        return _FakeInsert(self._client, self._name, rows, kwargs)


class _FakeInsert:
    def __init__(self, client, name, rows, kwargs):
        self._client = client
        self._name = name
        self._rows = list(rows)
        self.kwargs = kwargs

    def execute(self):
        if self._client.fail_on_execute:
            raise self._client.fail_on_execute
        self._client.writes.append((self._name, self._rows, threading.current_thread().name))
        self._client.insert_kwargs.append(self.kwargs)
        return self


def rows_inserted(sb) -> list:
    """Every row that actually reached the database, flattened across executed calls."""
    return [row for _, rows, _ in sb.writes for row in rows]


def run_probe(monkeypatch, responses, stored_states, workers=1, sb=None):
    """Drive the real ``probe_associations`` over `responses`, keyed by provider id."""
    sb = sb or FakeClient()

    def fake_get(session, api_key, url, **kwargs):
        outcome = responses[url.rsplit("team_id=", 1)[1]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("src.scrapers.gotsport._zenrows_get", fake_get)
    aliases = {f"team-{pid}": pid for pid in responses}
    states, outcomes = probe_associations(aliases, workers, sb, stored_states)
    return sb, states, outcomes


CONSTRAINT_KEYWORDS = frozenset(
    {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "EXCLUDE", "LIKE"}
)


def probe_log_columns() -> dict:
    """The probe log's column name -> its declaration, read from the migration itself.

    Table-level constraints are members of the same parenthesised group as the columns,
    so they are skipped by keyword: without that, a `CONSTRAINT ... CHECK (... NOT NULL)`
    would present itself as a required column literally named CONSTRAINT.
    """
    columns = {}
    for member in _split_top_level(_table(PROBE_LOG_TABLE)):
        words = member.split()
        if not words or words[0].upper() in CONSTRAINT_KEYWORDS:
            continue
        columns[words[0]] = member
    return columns


def _is_required(name: str, declaration: str) -> bool:
    """Whether the writer must supply this column for an insert to succeed.

    Clause-matched, not substring-matched: a column named `default_source` contains the
    word DEFAULT and has none, and dropping it from the required set is silent — the
    guard stays green and the insert fails in production.
    """
    rest = declaration[len(name) :].upper()
    return (
        re.search(r"\bNOT\s+NULL\b", rest) is not None
        and re.search(r"\bDEFAULT\b", rest) is None
        and re.search(r"\bPRIMARY\s+KEY\b", rest) is None
    )


# --------------------------------------------------------------------------- #
# The row against the schema that has to accept it
# --------------------------------------------------------------------------- #


def test_every_key_the_writer_sends_is_a_column_the_table_has():
    """Payload keys against the CREATE TABLE column names. CI applies no migrations, so a
    key the table lacks is not a test failure -- it is PGRST204 on the first insert of the
    next Tier A run, which is fatal by design and takes the whole sweep down with it.
    """
    columns = probe_log_columns()
    keys = set(probe_log_row("t", "9", "mapped", "OH", "OH"))

    assert keys <= set(columns), f"the table has no column: {sorted(keys - set(columns))}"


def test_the_writer_supplies_every_column_that_has_no_default():
    """A NOT NULL column the payload omits fails the insert just as fatally, and the
    reverse drift is the one a renamed column produces."""
    columns = probe_log_columns()
    keys = set(probe_log_row("t", "9", "mapped", "OH", "OH"))
    required = {name for name, decl in columns.items() if _is_required(name, decl)}

    assert required <= keys, f"the writer never sends: {sorted(required - keys)}"


# --------------------------------------------------------------------------- #
# The row
# --------------------------------------------------------------------------- #


def test_an_agreeing_probe_is_recorded_as_agreeing():
    """The case the table exists for. It writes no state, so it fires no ledger trigger
    and leaves no other trace anywhere.

    ``provider`` is asserted here because its table DEFAULT excludes it from every other
    guard. postgrest sends each payload key explicitly, so a None is inserted rather than
    defaulted and the sweep's first insert dies on 23502.
    """
    row = probe_log_row("t", "9", "mapped", "OH", "OH")

    assert row["agreed"] is True
    assert row["reported_state_code"] == "OH"
    assert row["stored_state_code"] == "OH"
    assert row["provider"] == "gotsport"
    assert row["probed_by"] == ACTOR


def test_a_contradicting_probe_is_recorded_as_disagreeing():
    assert probe_log_row("t", "9", "mapped", "WA", "OH")["agreed"] is False


@pytest.mark.parametrize("reported,stored", [(None, "OH"), ("OH", None), (None, None)])
def test_agreed_is_null_unless_both_sides_answered(reported, stored):
    """NULL is not False. "Nobody answered" and "the provider contradicted us" are
    different facts, and a reader that cannot tell them apart re-probes the wrong half."""
    assert probe_log_row("t", "9", "mapped", reported, stored)["agreed"] is None


# --------------------------------------------------------------------------- #
# What reaches the database
# --------------------------------------------------------------------------- #


def test_a_mapped_probe_that_agrees_writes_a_row(monkeypatch):
    sb, states, _ = run_probe(
        monkeypatch,
        {"9": Response(payload={"team_association": "OH"})},
        {"team-9": "OH"},
    )

    assert states == {"team-9": "OH"}
    # provider_team_id is the two-armed field: the None arm is pinned by the no-alias
    # test, and without this the populated arm could go NULL for every probed row,
    # erasing the pointer back to the id the call was paid for.
    assert [
        (r["team_id_master"], r["outcome"], r["agreed"], r["provider_team_id"])
        for r in rows_inserted(sb)
    ] == [("team-9", "mapped", True, "9")]


@pytest.mark.parametrize(
    "response,outcome",
    [
        (Response(status_code=404), "no such team (404)"),
        (Response(payload=None), "unparseable payload"),
        (Response(status_code=403), "http 403"),
        (Response(payload={"team_association": ""}), "no association in payload"),
        (Response(payload={"team_association": "ZZZ"}), "unmapped code ZZZ"),
    ],
)
def test_a_probe_that_found_no_state_still_writes_a_row(monkeypatch, response, outcome):
    """Every one of these produces no state change, so the audit ledger never sees it."""
    sb, states, _ = run_probe(monkeypatch, {"9": response}, {"team-9": "OH"})

    assert states == {}
    row = rows_inserted(sb)[0]
    assert row["outcome"] == outcome
    assert row["reported_state_code"] is None
    assert row["agreed"] is None


def test_a_failed_call_records_its_exception_not_the_histograms_category(monkeypatch):
    """The counter collapses 'request failed (X)' to 'request failed' before counting.
    The ledger must not: a timeout and a refused connection are the same category and a
    later reader still needs to tell them apart."""
    sb, _, outcomes = run_probe(
        monkeypatch,
        {"9": requests.ConnectionError("refused")},
        {"team-9": "OH"},
    )

    assert rows_inserted(sb)[0]["outcome"] == "request failed (ConnectionError)"
    assert outcomes == Counter({"request failed": 1})


def test_the_stored_state_is_recorded_even_when_the_probe_says_nothing(monkeypatch):
    """Without it the row cannot answer "did this disagree", only "we called"."""
    sb, _, _ = run_probe(monkeypatch, {"9": Response(status_code=404)}, {"team-9": "NV"})

    assert rows_inserted(sb)[0]["stored_state_code"] == "NV"


def test_rows_are_written_to_the_probe_log_and_nowhere_else(monkeypatch):
    """team_state_audit is the table revert_team_states walks. A probe row landing there
    would carry no action and no old_state_code."""
    sb, _, _ = run_probe(monkeypatch, {"9": Response(status_code=404)}, {"team-9": "NV"})

    assert {table for table, _, _ in sb.writes} == {PROBE_LOG_TABLE}


def test_the_insert_asks_for_no_representation_back(monkeypatch):
    """Postgrest returns every inserted row by default, and a full run discards thousands
    of them unread."""
    sb, _, _ = run_probe(monkeypatch, {"9": Response(status_code=404)}, {"team-9": "NV"})

    assert sb.insert_kwargs == [{"returning": "minimal"}]


# --------------------------------------------------------------------------- #
# Where and when the write happens
# --------------------------------------------------------------------------- #


def test_every_insert_runs_on_the_main_thread(monkeypatch):
    """supabase-py publishes no thread-safety guarantee, and every other pool in this
    repo resolves in the workers and writes sequentially."""
    sb, _, _ = run_probe(
        monkeypatch,
        {str(i): Response(payload={"team_association": "OH"}) for i in range(6)},
        {f"team-{i}": "OH" for i in range(6)},
        workers=3,
    )

    assert {thread for _, _, thread in sb.writes} == {threading.main_thread().name}


def test_the_buffer_is_flushed_before_returning(monkeypatch):
    """The caller aborts the run when too many calls failed, and it does so after this
    returns. A buffer left unflushed would throw away observations already paid for."""
    sb, _, _ = run_probe(
        monkeypatch,
        {str(i): Response(status_code=403) for i in range(5)},
        {f"team-{i}": "OH" for i in range(5)},
    )

    assert len(rows_inserted(sb)) == 5


def test_a_long_run_flushes_in_batches_without_resending(monkeypatch):
    """Past the batch size the buffer drains mid-run, and a drain that failed to clear
    the buffer would re-send every earlier row on each subsequent flush -- filling the
    ledger with duplicates, so "when was this team last probed" reads off a table that is
    wrong in exactly the way it exists to fix."""
    monkeypatch.setattr(assign, "FLUSH_EVERY", 3)
    ids = [str(i) for i in range(7)]
    sb, _, _ = run_probe(
        monkeypatch,
        {i: Response(payload={"team_association": "OH"}) for i in ids},
        {f"team-{i}": "OH" for i in ids},
    )

    assert [len(rows) for _, rows, _ in sb.writes] == [3, 3, 1]
    written = [r["team_id_master"] for r in rows_inserted(sb)]
    assert sorted(written) == sorted(f"team-{i}" for i in ids)
    assert len(written) == len(set(written)), "a row was sent more than once"


def test_a_failed_insert_is_fatal(monkeypatch):
    """A half-written ledger is worse than none: a missing row reads as "never probed"
    and is paid for again, a present one reads as settled."""
    sb = FakeClient(fail_on_execute=RuntimeError("insert failed"))

    with pytest.raises(RuntimeError):
        run_probe(
            monkeypatch,
            {"9": Response(payload={"team_association": "OH"})},
            {"team-9": "OH"},
            sb=sb,
        )


def test_write_probe_log_batches_at_the_insert_limit():
    """The rows travel in the request body, so the 100-id URI cap that bounds .in_()
    lists does not apply here."""
    sb = FakeClient()
    write_probe_log(sb, [probe_log_row(f"t{i}", "9", "mapped", "OH", "OH") for i in range(2500)])

    assert [len(rows) for _, rows, _ in sb.writes] == [1000, 1000, 500]


def test_the_ledger_arguments_cannot_be_omitted():
    """Defaulting either is how the ledger goes inert in production while every unit test
    passes: the probes are paid for and nothing records them.

    Both are checked independently. Omitting both raises as long as *any* parameter is
    still required, so that alone would not notice ``stored_states`` acquiring a default
    -- and every row would then carry a NULL stored state and a NULL ``agreed``, which is
    the blind spot this table exists to close.
    """
    signature = inspect.signature(probe_associations)
    for name in ("sb", "stored_states"):
        assert signature.parameters[name].default is inspect.Parameter.empty, (
            f"{name} has a default; a caller can omit it and silently disable the ledger"
        )

    with pytest.raises(TypeError):
        probe_associations({}, 1)


# --------------------------------------------------------------------------- #
# The caller
# --------------------------------------------------------------------------- #


def snapshot_with(monkeypatch, teams, aliases, only_team=None):
    """Drive the real ``build_snapshot`` far enough to reach the alias lookup.

    Captures what it hands the probe, because the arguments are the whole seam: a stub
    that discarded them would let the call site pass nothing and stay green.
    """
    written = []
    handed = {}

    def fake_probe(ids, workers, sb, stored):
        handed["ids"], handed["stored"] = ids, stored
        return {}, Counter()

    def fake_aliases(sb, ids):
        handed["looked_up"] = list(ids)
        return aliases

    monkeypatch.setattr(assign, "fetch_live_teams", lambda sb: teams)
    monkeypatch.setattr(assign, "fetch_revert_blocks", lambda sb: set())
    monkeypatch.setattr(assign, "fetch_gotsport_aliases", fake_aliases)
    monkeypatch.setattr(assign, "ranked_and_active", lambda sb, ids: [])
    monkeypatch.setattr(assign, "write_probe_log", lambda sb, rows: written.extend(rows))
    monkeypatch.setattr(assign, "probe_associations", fake_probe)
    build_snapshot(FakeClient(), use_tier_a=True, workers=1, only_team=only_team)
    return written, handed


def test_a_candidate_with_no_alias_is_recorded_as_such(monkeypatch):
    """It never reaches the probe, so nothing else would record that we selected it."""
    teams = [
        team(team_id_master="has-alias", team_name="A"),
        team(team_id_master="no-alias", team_name="B"),
    ]
    written, handed = snapshot_with(monkeypatch, teams, {"has-alias": "9"})

    assert [(r["team_id_master"], r["outcome"], r["provider_team_id"]) for r in written] == [
        ("no-alias", NO_ALIAS_OUTCOME, None)
    ]
    # Without this the call site could pass an empty map -- no calls, no rows, and no
    # abort, since an empty outcome counter is not "unusable" -- or look the aliases up
    # for the wrong ids, filling the ledger with false no-alias rows.
    assert handed["ids"] == {"has-alias": "9"}
    assert sorted(handed["looked_up"]) == ["has-alias", "no-alias"]


def test_the_no_alias_row_carries_the_state_the_team_actually_holds(monkeypatch):
    """A row reporting NULL for a team that has a state would read as "we asked and it
    had none", which is a different fact from "we could not ask".

    The team is a candidate here because its own name disputes its stored state, which is
    what a correction candidate looks like -- a stateless team would make the assertion
    vacuous, since NULL is then the right answer.
    """
    teams = [team(team_id_master="no-alias", team_name="Texas United", state_code="NV")]
    written, _ = snapshot_with(monkeypatch, teams, {})

    assert [r["team_id_master"] for r in written] == ["no-alias"]
    assert written[0]["stored_state_code"] == "NV"


def test_the_probe_is_handed_the_stored_state_of_every_team(monkeypatch):
    """`agreed` is the one fact no other table can hold, and this map is its only input.
    Building it off the wrong column is silent here and fatal in production: teams.state
    holds full names, and 'Ohio' into CHAR(2) raises 22001 on the first insert."""
    teams = [
        team(team_id_master="a", state_code="OH", state="Ohio"),
        team(team_id_master="b", state_code="  NV  ", state="Nevada"),
        team(team_id_master="c", state_code="", state="Texas"),
    ]
    _, handed = snapshot_with(monkeypatch, teams, {"a": "1", "b": "2", "c": "3"})

    assert handed["stored"] == {"a": "OH", "b": "NV", "c": None}


def test_a_named_team_is_probed_and_ledgered_like_any_other(monkeypatch):
    """It is the one path guaranteed to probe."""
    teams = [
        team(team_id_master="named", state_code="OH"),
        team(team_id_master="other", state_code="OH"),
    ]
    written, handed = snapshot_with(monkeypatch, teams, {}, only_team="named")

    assert [r["team_id_master"] for r in written] == ["named"]
    assert written[0]["outcome"] == NO_ALIAS_OUTCOME
    assert handed["stored"]["named"] == "OH"
    assert handed["looked_up"] == ["named"]


def test_a_named_team_that_has_an_alias_reaches_the_probe(monkeypatch):
    """The other half of --team. With no alias in the fixture this path only ever exercises
    the no-alias branch, so nothing would notice it failing to hand the id to the probe."""
    teams = [
        team(team_id_master="named", state_code="OH"),
        team(team_id_master="other", state_code="OH"),
    ]
    written, handed = snapshot_with(monkeypatch, teams, {"named": "77"}, only_team="named")

    assert handed["ids"] == {"named": "77"}
    assert written == []


def test_a_decision_normalises_the_state_it_records_as_the_pre_image():
    """The pre-image is the optimistic predicate every state write carries, and it has to
    mean the same thing as the ledger's stored_state_code -- one helper now produces both.

    A blank state_code read raw would classify as a correction rather than a fill, so
    --fills-only would withhold it and the predicate would stop matching a NULL row.
    """
    blank = team(team_id_master="blank", team_name="Texas United", state_code="   ")

    decision = assign.decide(blank, {}, {}, {}, set())

    assert decision is not None
    assert decision["pre_image"] is None


def test_the_dry_run_help_does_not_promise_it_writes_nothing(monkeypatch, capsys):
    """The claim a user actually reads. It is false the moment a probe is recorded, and a
    stale safety guarantee is worse than none -- so it cannot survive this change."""
    monkeypatch.setattr(sys, "argv", ["assign_team_states.py", "--help"])

    with pytest.raises(SystemExit):
        assign.main()

    text = re.sub(r"\s+", " ", capsys.readouterr().out).lower()
    assert "write nothing" not in text
    assert "paid-probe observations are recorded" in text
