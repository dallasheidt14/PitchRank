"""Queue recovery must survive lost responses, consumer completion, and restarts."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_refresh import RefreshQueue, read_refresh, refresh_run
from src.tournaments.seeding_run_store import SeedingRun, load_run, save_run


class Queue:
    provider = "gotsport"

    def __init__(self):
        self.requests = {}
        self.sources = {"a": "101", "b": "202", "c": "303"}
        self.inserts = []
        self.lose_response = False

    def canonical(self, identity):
        return {"old-a": "a"}.get(identity, identity)

    def source(self, identity):
        if self.sources.get(identity) == "error":
            raise ConnectionError("lookup failed")
        return self.sources.get(identity)

    def get(self, request_id):
        return deepcopy(self.requests.get(request_id))

    def active(self, identity):
        return [deepcopy(x) for x in self.requests.values()
                if self.canonical(x["team_id_master"]) == identity and x["status"] in {"pending", "processing"}]

    def insert(self, receipt):
        self.inserts.append(deepcopy(receipt))
        if receipt["request_id"] in self.requests:
            raise ValueError("duplicate id")
        self.requests[receipt["request_id"]] = {**receipt, "id": receipt["request_id"], "status": "pending"}
        if self.lose_response:
            raise ConnectionError("response lost after insert")
        return deepcopy(self.requests[receipt["request_id"]])

    def prioritize(self, request):
        if request["status"] == "pending" and request.get("priority", 1) > 1:
            self.requests[request["id"]]["priority"] = 1


@pytest.fixture
def saved(tmp_path):
    parsed = parse_roster("Male U13\nClub\tTeam\tState\nClub A\tTeam A\tMD\nClub B\tTeam B\tMD")
    run = SeedingRun("sample", parsed.rows, tuple(
        ResolvedTeam(source_index=i, status="exact_name", team_id_master=identity)
        for i, identity in enumerate(("a", "b"))
    ))
    path = save_run(run, base_dir=tmp_path)
    return load_run("sample", base_dir=tmp_path), path.parent


def test_dry_run_writes_neither_queue_journal_nor_lock(saved):
    run, folder = saved
    before = {p: p.read_bytes() for p in folder.parent.rglob("*") if p.is_file()}
    queue = Queue()
    result = refresh_run(run, folder, queue, dry_run=True)
    assert {x["status"] for x in result["teams"].values()} == {"would_queue"}
    assert not queue.inserts
    assert before == {p: p.read_bytes() for p in folder.parent.rglob("*") if p.is_file()}


def test_restart_after_completion_never_requeues_or_changes_saved_pack(saved):
    run, folder = saved
    original = (folder / "seeding_run.json").read_bytes()
    queue = Queue()
    refresh_run(run, folder, queue)
    for request in queue.requests.values():
        request.update(status="completed", completed_at="2026-10-20T00:00:00Z")
    restarted = load_run("sample", base_dir=folder.parent)
    result = refresh_run(restarted, folder, queue, status_only=True)
    assert len(queue.inserts) == 2
    assert {x["status"] for x in result["teams"].values()} == {"completed"}
    assert (folder / "seeding_run.json").read_bytes() == original


def test_lost_insert_response_is_recovered_even_after_consumer_completed(saved):
    run, folder = saved
    queue = Queue()
    queue.lose_response = True
    first = refresh_run(run, folder, queue)
    assert {x["status"] for x in first["teams"].values()} == {"uncertain"}
    for request in queue.requests.values():
        request["status"] = "completed"
    second = refresh_run(run, folder, queue, retry_failed=True)
    assert len(queue.inserts) == 2
    assert {x["status"] for x in second["teams"].values()} == {"completed"}


def test_intent_is_durable_before_any_database_write(saved):
    run, folder = saved
    queue = Queue()
    original = queue.insert

    def checked(receipt):
        persisted = read_refresh(folder, run.name)["teams"][receipt["team_id_master"]]
        assert persisted["status"] == "submitting"
        assert persisted["request_id"] == receipt["request_id"]
        return original(receipt)

    queue.insert = checked
    refresh_run(run, folder, queue)
    assert len(queue.inserts) == 2


def test_manual_override_uses_correct_source_and_canonical_dedup(saved):
    run, folder = saved
    queue = Queue()
    run = replace(run, overrides={0: {"team_id_master": "c"}})
    refresh_run(run, folder, queue)
    assert {(x["team_id_master"], x["provider_team_id"]) for x in queue.inserts} == {("c", "303"), ("b", "202")}
    duplicate = replace(run, overrides={0: {"team_id_master": "old-a"}, 1: {"team_id_master": "a"}})
    refresh_run(duplicate, folder, queue)
    assert [x["team_id_master"] for x in queue.inserts] == ["c", "b", "a"]


def test_unmatched_and_rejected_identity_never_enqueued(saved):
    run, folder = saved
    queue = Queue()
    result = refresh_run(replace(run, overrides={0: {"not_found": True}, 1: {"not_found": True}}), folder, queue)
    assert result["teams"] == {}
    assert not queue.inserts


@pytest.mark.parametrize("status", ["pending", "processing"])
@pytest.mark.parametrize("same_source", [True, False])
def test_active_request_is_reused_only_if_compatible_and_never_overwritten(saved, status, same_source):
    run, folder = saved
    queue = Queue()
    request = {"id": "existing", "team_id_master": "a", "provider_id": "gotsport",
               "provider_team_id": "101" if same_source else "another", "status": status,
               "game_date": datetime.now(timezone.utc).date().isoformat()}
    queue.requests["existing"] = deepcopy(request)
    result = refresh_run(run, folder, queue)
    assert result["teams"]["a"]["status"] == (status if same_source else "conflict")
    assert queue.requests["existing"] == request
    assert [x["team_id_master"] for x in queue.inserts] == ["b"]


def test_compatible_background_request_gets_operator_priority_without_source_changes(saved):
    run, folder = saved
    queue = Queue()
    existing = dict(id="background", team_id_master="a", provider_id="gotsport", provider_team_id="101",
                    game_date=datetime.now(timezone.utc).date().isoformat(), status="pending", priority=3)
    queue.requests["background"] = deepcopy(existing)
    refresh_run(run, folder, queue, dry_run=True)
    assert queue.requests["background"] == existing
    refresh_run(run, folder, queue)
    assert queue.requests["background"] == {**existing, "priority": 1}
    assert [x["team_id_master"] for x in queue.inserts] == ["b"]


def test_lookup_failure_does_not_sink_other_matches_and_retry_only_adds_missing(saved):
    run, folder = saved
    queue = Queue()
    queue.sources["a"] = "error"
    result = refresh_run(run, folder, queue)
    assert result["teams"]["a"]["status"] == "failed"
    assert result["teams"]["b"]["status"] == "pending"
    queue.sources["a"] = "101"
    refresh_run(run, folder, queue, retry_failed=True)
    assert [x["team_id_master"] for x in queue.inserts] == ["b", "a"]


def test_status_check_of_legacy_save_does_not_enqueue(saved):
    run, folder = saved
    queue = Queue()
    refresh_run(run, folder, queue, status_only=True)
    assert not queue.inserts


def test_missing_source_is_explicit(saved):
    run, folder = saved
    queue = Queue()
    queue.sources.pop("a")
    result = refresh_run(run, folder, queue)
    assert result["teams"]["a"]["status"] == "unavailable_source"
    assert [x["team_id_master"] for x in queue.inserts] == ["b"]


def test_saved_roster_corrections_control_refresh_eligibility(saved):
    run, folder = saved
    run = replace(run, rows=(replace(run.rows[0], intake_issue="Confirm this line"), run.rows[1]),
                  cohort_decisions={0: {"intake_issue": "", "team_name_raw": "Corrected Team A"},
                                    1: {"exclude": True}})
    queue = Queue()
    refresh_run(run, folder, queue)
    assert [(x["team_id_master"], x["team_name"]) for x in queue.inserts] == [("a", "Corrected Team A")]


@pytest.mark.parametrize("status", ["pending", "processing", "completed"])
def test_merge_after_first_refresh_retains_original_receipt_without_requeue(saved, status):
    run, folder = saved
    queue = Queue()
    refresh_run(run, folder, queue)
    for request in queue.requests.values():
        request["status"] = status
    refresh_run(run, folder, queue, status_only=True)
    queue.canonical = lambda identity: "c" if identity == "a" else identity
    merged = replace(run, overrides={0: {"team_id_master": "c"}})
    result = refresh_run(merged, folder, queue, retry_failed=True)
    assert len(queue.inserts) == 2
    assert result["teams"]["a"]["current"]
    assert result["teams"]["a"]["status"] == status
    assert "c" not in result["teams"]


def test_related_active_request_is_adopted_after_merge(saved):
    run, folder = saved
    queue = Queue()
    queue.requests["old-request"] = dict(id="old-request", team_id_master="old-a", provider_id="gotsport",
                                         provider_team_id="101", game_date=datetime.now(timezone.utc).date().isoformat(),
                                         status="processing")
    result = refresh_run(run, folder, queue)
    assert result["teams"]["a"]["request_id"] == "old-request"
    assert [x["team_id_master"] for x in queue.inserts] == ["b"]


def test_equivalent_event_urls_share_receipts_but_another_event_is_refused(saved):
    run, folder = saved
    queue = Queue()
    run = replace(run, source_url="https://system.gotsport.com/org_event/events/52975")
    refresh_run(run, folder, queue)
    refresh_run(replace(run, source_url=run.source_url + "/schedules"), folder, queue)
    assert len(queue.inserts) == 2
    with pytest.raises(ValueError, match="another tournament"):
        refresh_run(replace(run, source_url=run.source_url.replace("52975", "12345")), folder, queue)


def test_name_only_legacy_event_reopens_and_checks_status(saved):
    run, folder = saved
    run = replace(run, name="GotSport Event 52975")
    save_run(run, base_dir=folder.parent)
    folder = folder.parent / "gotsport-event-52975"
    run = load_run(folder.name, base_dir=folder.parent)
    queue = Queue()
    refresh_run(run, folder, queue)
    result = refresh_run(load_run(folder.name, base_dir=folder.parent), folder, queue, status_only=True)
    assert result["event_id"] == "52975"
    refresh_run(run, folder, queue)
    assert len(queue.inserts) == 2


def test_retry_after_consumer_failure_creates_one_new_request(saved):
    run, folder = saved
    queue = Queue()
    first = refresh_run(run, folder, queue)
    old_id = first["teams"]["a"]["request_id"]
    queue.requests[old_id]["status"] = "failed"
    refresh_run(run, folder, queue, status_only=True)
    refresh_run(run, folder, queue)
    assert len(queue.inserts) == 2
    result = refresh_run(run, folder, queue, retry_failed=True)
    assert len(queue.inserts) == 3
    assert result["teams"]["a"]["request_id"] != old_id


def test_save_failure_cannot_send_an_unrecoverable_request(saved, monkeypatch):
    import src.tournaments.seeding_refresh as module
    run, folder = saved
    queue = Queue()
    monkeypatch.setattr(module, "write_json", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        refresh_run(run, folder, queue)
    assert not queue.inserts


def test_interrupted_submission_reuses_the_saved_request_id(saved):
    run, folder = saved
    queue = Queue()
    original = queue.insert
    def interrupted(receipt):
        raise KeyboardInterrupt()
    queue.insert = interrupted
    with pytest.raises(KeyboardInterrupt):
        refresh_run(run, folder, queue)
    request_id = read_refresh(folder, run.name)["teams"]["a"]["request_id"]
    queue.insert = original
    result = refresh_run(run, folder, queue)
    assert result["teams"]["a"]["request_id"] == request_id
    assert len(queue.inserts) == 2


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, ConnectionError])
def test_merge_after_interruption_before_insert_uses_survivor_and_same_request(saved, interruption):
    run, folder = saved
    queue = Queue()
    original = queue.insert

    def interrupted(receipt):
        raise interruption()

    queue.insert = interrupted
    try:
        refresh_run(run, folder, queue)
    except KeyboardInterrupt:
        pass
    request_id = read_refresh(folder, run.name)["teams"]["a"]["request_id"]
    queue.canonical = lambda identity: "c" if identity == "a" else identity
    queue.sources["c"] = "101"
    queue.insert = original
    result = refresh_run(run, folder, queue)
    receipt = result["teams"]["a"]
    assert receipt["request_id"] == request_id
    assert receipt["team_id_master"] == "c"
    assert queue.requests[request_id]["team_id_master"] == "c"
    assert len(queue.inserts) == 2


class FilteredClient:
    """Apply query predicates to rows so races test the adapter's actual filters."""
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "scrape_requests"
        client = self

        class Query:
            def __init__(self):
                self.filters, self.window, self.changes = [], slice(None), None

            def select(self, _):
                return self

            def in_(self, key, values):
                self.filters.append(lambda row: row[key] in values)
                return self

            def eq(self, key, value):
                self.filters.append(lambda row: row[key] == value)
                return self

            def gt(self, key, value):
                self.filters.append(lambda row: row[key] > value)
                return self

            def order(self, _):
                return self

            def range(self, first, last):
                self.window = slice(first, last + 1)
                return self

            def update(self, changes):
                self.changes = changes
                return self

            def execute(self):
                from types import SimpleNamespace
                rows = [row for row in client.rows if all(test(row) for test in self.filters)][self.window]
                if self.changes:
                    for row in rows:
                        row.update(self.changes)
                return SimpleNamespace(data=deepcopy(rows))

        return Query()


def test_database_active_query_finds_deprecated_id_after_first_page():
    from types import SimpleNamespace
    queue = object.__new__(RefreshQueue)
    queue.resolver = SimpleNamespace(get_deprecated_teams=lambda: {"old-a"})
    queue.canonical = lambda identity: "a" if identity == "old-a" else identity
    queue.client = FilteredClient([
        dict(id=str(i), team_id_master="old-a", status="processing") for i in range(101)
    ] + [dict(id="unrelated", team_id_master="b", status="processing")])
    assert {row["id"] for row in queue.active("a")} == {str(i) for i in range(101)}


@pytest.mark.parametrize("changed", [{}, {"status": "processing"}, {"provider_team_id": "other"},
                                      {"game_date": "2026-10-18"}, {"team_id_master": "b"}])
def test_database_priority_update_requires_unchanged_pending_request(changed):
    existing = dict(id="request", team_id_master="a", provider_id="gotsport", provider_team_id="101",
                    game_date="2026-10-19", status="pending", priority=3)
    current = {**existing, **changed}
    queue = object.__new__(RefreshQueue)
    queue.client = FilteredClient([current])
    queue.prioritize(existing)
    assert current == {**existing, **changed, "priority": 3 if changed else 1}


def test_database_insert_is_executed_and_dry_run_does_not_write():
    calls = []

    class Db:
        def rpc(self, name, row):
            assert name == "enqueue_scrape_request_once"
            self.row = row
            assert not calls
            return self

        def execute(self):
            from types import SimpleNamespace
            calls.append(self.row)
            return SimpleNamespace(data=[{"id": "request", "status": "pending"}])

    queue = object.__new__(RefreshQueue)
    queue.client = Db()
    receipt = dict(request_id="request", team_id_master="a", team_name="Team A", provider_id="gotsport",
                   provider_team_id="101", game_date="2026-10-19")
    queue.insert(receipt, dry_run=True)
    assert not calls
    assert queue.insert(receipt) == {"id": "request", "status": "pending"}
    assert calls == [{"p_intent_id": "request", "p_team_id_master": "a", "p_team_name": "Team A", "p_provider_id": "gotsport",
                      "p_provider_team_id": "101", "p_game_date": "2026-10-19", "p_request_type": "missing_games",
                      "p_priority": 1}]


@pytest.mark.parametrize("compatible", [True, False])
def test_request_arriving_after_lookup_is_adopted_or_reported_without_replacement(saved, compatible):
    run, folder = saved
    queue = Queue()
    original = queue.insert

    def race(receipt):
        if receipt["team_id_master"] != "a":
            return original(receipt)
        return dict(id="racing-request", team_id_master="a", provider_id="gotsport",
                    provider_team_id="101" if compatible else "other", game_date=receipt["game_date"],
                    status="processing")

    queue.insert = race
    result = refresh_run(run, folder, queue)
    assert result["teams"]["a"]["status"] == ("processing" if compatible else "conflict")
    if compatible:
        assert result["teams"]["a"]["request_id"] == "racing-request"
    assert [x["team_id_master"] for x in queue.inserts] == ["b"]


def test_database_lookup_recovers_lost_adoption_after_worker_completed():
    from types import SimpleNamespace
    calls = []

    class Db:
        def table(self, name):
            self.name = name
            return self

        def select(self, fields):
            return self

        def eq(self, key, value):
            calls.append((self.name, key, value))
            return self

        def limit(self, count):
            return self

        def execute(self):
            if self.name == "scrape_request_intents":
                return SimpleNamespace(data=[{"request_id": "adopted"}])
            return SimpleNamespace(data=[{"id": "adopted", "status": "completed"}])

    queue = object.__new__(RefreshQueue)
    queue.client = Db()
    assert queue.get("original-intent") == {"id": "adopted", "status": "completed"}
    assert calls == [("scrape_request_intents", "intent_id", "original-intent"),
                     ("scrape_requests", "id", "adopted")]


@pytest.mark.parametrize("status", ["processing", "completed", "failed"])
def test_explicit_retry_releases_incompatible_intent_only_after_request_is_terminal(saved, status):
    run, folder = saved
    queue = Queue()
    original = queue.insert
    conflict = dict(id="other-request", team_id_master="a", provider_id="gotsport",
                    provider_team_id="other", game_date=datetime.now(timezone.utc).date().isoformat(),
                    status="processing")
    intents = {}

    def adopted(receipt):
        if receipt["team_id_master"] != "a":
            return original(receipt)
        intents[receipt["request_id"]] = conflict
        return deepcopy(conflict)

    queue.insert = adopted
    first = refresh_run(run, folder, queue)
    assert first["teams"]["a"]["status"] == "conflict"
    old_intent = first["teams"]["a"]["request_id"]
    conflict["status"] = status
    original_get = queue.get
    queue.get = lambda key: deepcopy(intents[key]) if key in intents else original_get(key)
    queue.requests[conflict["id"]] = conflict
    queue.insert = original
    second = refresh_run(run, folder, queue, retry_failed=True)
    receipt = second["teams"]["a"]
    assert receipt["status"] == ("conflict" if status == "processing" else "pending")
    assert (receipt["request_id"] == old_intent) == (status == "processing")


def test_refresh_adds_newly_eligible_match_without_repeating_completed_work(saved):
    run, folder = saved
    queue = Queue()
    excluded = replace(run, overrides={1: {"not_found": True}})
    refresh_run(excluded, folder, queue)
    for request in queue.requests.values():
        request.update(status="completed")
    refresh_run(excluded, folder, queue, status_only=True)
    refresh_run(run, folder, queue, status_only=True)
    assert [item["team_id_master"] for item in queue.inserts] == ["a"]
    result = refresh_run(run, folder, queue, retry_failed=True)
    assert [item["team_id_master"] for item in queue.inserts] == ["a", "b"]
    assert result["teams"]["a"]["status"] == "completed"
    assert result["teams"]["b"]["status"] == "pending"
