"""Unit tests for the ZenRows Batch API client and run control.

No network and no credits: every test drives a fake session that records each
call's method, URL, headers, JSON body and timeout. There is no HTTP-mocking
library in either requirements file, and the client's clock and sleep are
injected, so nothing here sleeps for real.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.parse
from pathlib import Path

import pytest
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.batch_drain_queue import (  # noqa: E402
    ACTIVE_RUN_STATUSES,
    DATACENTER_PROXY_PARAMS,
    MAX_TASKS_PER_SUBMISSION,
    DEFAULT_CLUB_RESERVE_MINUTES,
    DEFAULT_REQUEST_ATTEMPTS,
    DEFAULT_WAIT_CAP_MINUTES,
    MIN_CLUB_RESERVE_MINUTES,
    MIN_WAIT_CAP_MINUTES,
    PREMIUM_PROXY_PARAMS,
    NON_TERMINAL_TASK_STATUSES,
    POLL_SECONDS,
    SETTLE_CAP_SECONDS,
    STOP_CLEANUP_SECONDS,
    TERMINAL_RUN_STATUSES,
    TERMINATION_ABORTED,
    TERMINATION_COMPLETE,
    TERMINATION_TIMED_OUT,
    BATCH_RUN_ID,
    RUN_TS,
    BatchClientError,
    BatchJob,
    BodyFetchError,
    BudgetExpired,
    RunBudget,
    RunOutcome,
    SubmissionSequence,
    ZenRowsBatchClient,
    _build_tasks,
    _cleanup_deadline,
    _keyed_submissions,
    _operator_text,
    _normalized_team_id,
    _plan_submissions,
    _key_supplier,
    _print_dry_run_plan,
    _report_outcome,
    _run_progress,
    _run_status,
    _spend_credits,
    _validate_run_args,
    main,
    poll_until_terminal,
    run_batch,
    submit_tasks,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "zenrows_batch"
API_KEY = "zr-secret-key-do-not-log"
BATCH_HOST = "async.api.zenrows.com/v1"


def fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeResponse:
    """Enough of ``requests.Response`` for the client's status ladders.

    ``content`` is the source of truth and ``text`` decodes it through
    ``encoding``, mirroring ``requests``: a ``text/html`` body with no charset
    infers ISO-8859-1, so the decoded text mangles UTF-8 while the bytes stay
    intact. A double that stored ``text`` directly cannot reproduce that.
    """

    def __init__(
        self, status_code=200, payload=None, text=None, headers=None, content=None, encoding="ISO-8859-1"
    ):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.encoding = encoding
        if content is not None:
            self.content = content
        elif text is not None:
            self.content = text.encode("utf-8")
        elif payload is not None:
            self.content = json.dumps(payload).encode("utf-8")
        else:
            self.content = b""

    @property
    def text(self):
        return self.content.decode(self.encoding, errors="replace")

    def json(self):
        if self._payload is None:
            raise ValueError("response body is not JSON")
        return self._payload


def _route_key(url: str) -> str:
    """The routing key: a Batch-API path with its query, or a third-party URL with
    the query stripped.

    Keeping our own query is what makes a dropped cursor visible.
    """
    if BATCH_HOST in url:
        return url.split(BATCH_HOST, 1)[1]
    return url.split("?", 1)[0]


class FakeSession:
    """Answers routed by (method, path) and records every call it was handed.

    A route holding several responses hands them out in order and then repeats
    the last one, which is what a poll loop needs. A route entry may instead be a
    callable ``(method, url, json_body)`` so a test can vary the answer or move
    the clock as a side effect, and an ``Exception`` instance is raised.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.headers: dict[str, str] = {}
        self._routes: dict[tuple[str, str], list] = {}

    def route(self, method, path, *responses):
        self._routes.setdefault((method, path), []).extend(responses)
        return self

    def replace(self, method, path, *responses):
        """Swap a route wholesale, so tests stop assembling routing keys by hand."""
        self._routes[(method, path)] = list(responses)
        return self

    def _answer(self, method, url, json_body):
        key = (method, _route_key(url))
        queue = self._routes.get(key)
        if not queue:
            raise AssertionError(f"no fake route for {method} {_route_key(url)}")
        item = queue[0] if len(queue) == 1 else queue.pop(0)
        if callable(item):
            item = item(method, url, json_body)
        if isinstance(item, BaseException):
            raise item
        return item

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": {**self.headers, **(headers or {})},
                "json": json,
                "timeout": timeout,
            }
        )
        return self._answer(method, url, json)

    def get(self, url, timeout=None, **kwargs):
        """GET, following redirects the way ``requests`` does unless told not to.

        This is the behaviour that matters for the credential: ``requests`` strips
        only ``Authorization`` when the host changes and carries any other header
        verbatim. A double that ignored ``allow_redirects`` could not see a key
        riding a hop to a third party, which is exactly the defect it needs to show.
        """
        headers = {**self.headers, **(kwargs.get("headers") or {})}
        follow = kwargs.get("allow_redirects", True)
        for _ in range(10):
            self.calls.append(
                {"method": "GET", "url": url, "headers": headers, "json": None, "timeout": timeout}
            )
            response = self._answer("GET", url, None)
            location = response.headers.get("Location") if response.headers else None
            if not follow or response.status_code not in {301, 302, 303, 307, 308} or not location:
                return response
            url = urllib.parse.urljoin(url, location)
        raise AssertionError("fake session followed too many redirects")

    def calls_to(self, method, path):
        """Calls whose path matches, ignoring any query string."""
        return [
            call
            for call in self.calls
            if call["method"] == method and _route_key(call["url"]).split("?", 1)[0] == path
        ]


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += max(0.0, seconds)


def make_client(session=None, clock=None, **kwargs):
    session = session if session is not None else FakeSession()
    clock = clock if clock is not None else FakeClock()
    return ZenRowsBatchClient(
        API_KEY,
        session=session,
        sleep=clock.sleep,
        time_source=clock.now,
        retry_delay=kwargs.pop("retry_delay", 1.0),
        **kwargs,
    )


def keys_sent(session):
    return [call["headers"].get("Idempotency-Key") for call in session.calls if call["headers"].get("Idempotency-Key")]


def valid_argv(**overrides):
    argv = {
        "--team-id": "126693",
        "--premium-proxy": "false",
        "--wait-cap-minutes": "30",
        "--club-reserve-minutes": "5",
    }
    argv.update({k: v for k, v in overrides.items() if v is not None})
    flat: list[str] = []
    for flag, value in argv.items():
        if value == "":
            flat.append(flag)
        else:
            flat.extend([flag, value])
    return flat


def flat_output(capsys):
    return " ".join(capsys.readouterr().out.split())


class TestSubmissionShaping:
    def test_exactly_the_cap_stays_closed_and_inline(self):
        lifecycle, chunks = _plan_submissions(_build_tasks(range(MAX_TASKS_PER_SUBMISSION), premium=False))
        assert lifecycle == "closed"
        assert [len(chunk) for chunk in chunks] == [1000]
        assert _keyed_submissions(lifecycle, chunks) == [("create", 1000, True)]

    def test_one_over_the_cap_opens_the_job(self):
        lifecycle, chunks = _plan_submissions(_build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False))
        assert lifecycle == "open"
        assert [len(chunk) for chunk in chunks] == [1000, 1]
        assert _keyed_submissions(lifecycle, chunks) == [
            ("create", 0, True),
            ("add_tasks", 1000, False),
            ("add_tasks", 1, False),
        ]

    def test_closed_run_issues_one_create_and_no_add_tasks(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 1000}))
        client = make_client(session)

        job = submit_tasks(
            client,
            _build_tasks(range(MAX_TASKS_PER_SUBMISSION), premium=False),
            sequence=SubmissionSequence("run"),
            deadline=None,
        )

        assert job.lifecycle == "closed"
        assert len(session.calls_to("POST", "/jobs")) == 1
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/tasks")) == 0
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/close")) == 0

    def test_open_run_adds_each_chunk_then_closes(self):
        session = _open_lifecycle_session()
        client = make_client(session)

        job = submit_tasks(
            client,
            _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
            sequence=SubmissionSequence("run"),
            deadline=None,
        )

        adds = session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/tasks")
        assert [len(call["json"]["tasks"]) for call in adds] == [1000, 1]
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/close")) == 1
        assert job.accepted_tasks == 1001
        assert job.run_id == "run_01SYNTHETICOPEN"

    def test_add_tasks_response_without_a_count_contributes_its_chunk_size(self):
        session = _open_lifecycle_session(add_payload={"job_id": "job_01SYNTHETICOPEN"})
        client = make_client(session)

        job = submit_tasks(
            client,
            _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
            sequence=SubmissionSequence("run"),
            deadline=None,
        )

        assert job.accepted_tasks == 1001

    def test_a_job_that_accepted_nothing_fails_loudly(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 0}))
        client = make_client(session)

        with pytest.raises(BatchClientError, match="accepted no tasks"):
            submit_tasks(client, _build_tasks([1], premium=False), sequence=SubmissionSequence("run"), deadline=None)

    def test_an_open_create_without_a_run_id_fails_rather_than_polling_none(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, {"job_id": "job_x", "status": "open"}))
        client = make_client(session)

        with pytest.raises(BatchClientError, match="latest_run.run_id"):
            submit_tasks(
                client,
                _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
                sequence=SubmissionSequence("run"),
                deadline=None,
            )

    def test_dry_run_preview_matches_the_submission_it_previews(self, capsys):
        tasks = _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False)

        preview_sequence = SubmissionSequence("run")
        _print_dry_run_plan(tasks, sequence=preview_sequence)
        preview = flat_output(capsys)

        session = _open_lifecycle_session()
        submit_tasks(make_client(session), tasks, sequence=SubmissionSequence("run"), deadline=None)

        # One key for the create and none for the two add-tasks chunks.
        assert keys_sent(session) == ["run:0"]
        for key in keys_sent(session):
            assert key in preview
        assert "lifecycle: open" in preview
        assert "submissions: 3" in preview
        assert preview.count("no idempotency key") == 2

    def test_dry_run_with_no_teams_prints_an_empty_plan(self, capsys):
        assert _print_dry_run_plan([], sequence=SubmissionSequence("run")) == 0
        out = flat_output(capsys)
        assert "tasks: 0" in out
        assert "submissions: 0" in out


def _open_lifecycle_session(add_payload=None):
    session = FakeSession()
    session.route("POST", "/jobs", FakeResponse(200, fixture("create_open")))
    if add_payload is None:
        session.route(
            "POST",
            "/jobs/job_01SYNTHETICOPEN/tasks",
            lambda method, url, body: FakeResponse(200, {"job_id": "job_01SYNTHETICOPEN", "accepted_tasks": len(body["tasks"])}),
        )
    else:
        session.route("POST", "/jobs/job_01SYNTHETICOPEN/tasks", FakeResponse(200, add_payload))
    session.route("POST", "/jobs/job_01SYNTHETICOPEN/close", FakeResponse(200, fixture("close")))
    return session


class TestTaskConstruction:
    def test_external_id_stays_raw_while_the_path_is_normalized(self):
        task = _build_tasks(["126693.0"], premium=False)[0]
        assert task["external_id"] == "126693.0"
        assert "/teams/126693/matches" in task["url"]

    def test_both_date_params_are_sent(self):
        url = _build_tasks(["126693"], premium=False)[0]["url"]
        assert "since_date=2025-10-17" in url
        assert "from_date=2025-10-17" in url

    def test_the_tier_flag_picks_the_proxy_params(self):
        assert _build_tasks(["1"], premium=True)[0]["zenrows_params"] == PREMIUM_PROXY_PARAMS
        assert _build_tasks(["1"], premium=False)[0]["zenrows_params"] == DATACENTER_PROXY_PARAMS

    def test_tasks_do_not_share_the_module_constant(self):
        tasks = _build_tasks(["1", "2"], premium=True)
        tasks[0]["zenrows_params"]["premium_proxy"] = "mutated"
        assert tasks[1]["zenrows_params"] == PREMIUM_PROXY_PARAMS
        assert PREMIUM_PROXY_PARAMS["premium_proxy"] == "true"


class TestIdempotencyKeys:
    def test_one_sequence_spans_a_retry_and_the_next_job(self):
        session = FakeSession()
        session.route(
            "POST",
            "/jobs",
            FakeResponse(503, {"message": "temporarily unavailable"}, headers={"Retry-After": "0"}),
            FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 1}),
        )
        client = make_client(session)
        sequence = SubmissionSequence("run")

        submit_tasks(client, _build_tasks([1], premium=False), sequence=sequence, deadline=None)
        assert keys_sent(session) == ["run:0", "run:1"]

        session._routes[("POST", "/jobs")] = [FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 1})]
        submit_tasks(client, _build_tasks([2], premium=False), sequence=sequence, deadline=None)
        assert keys_sent(session)[-1] == "run:2"

    def test_an_explicit_503_is_retried_and_rotates_the_key(self):
        session = FakeSession()
        session.route(
            "POST",
            "/jobs",
            FakeResponse(503, {"message": "unavailable"}, headers={"Retry-After": "0"}),
            FakeResponse(200, fixture("create_closed")),
        )
        client = make_client(session)

        client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        assert keys_sent(session) == ["run:0", "run:1"]

    @pytest.mark.parametrize("status", [429, 500, 502, 504])
    def test_an_unknown_outcome_reuses_the_key(self, status):
        session = FakeSession()
        session.route(
            "POST",
            "/jobs",
            FakeResponse(status, {"message": "try again"}),
            FakeResponse(200, fixture("create_closed")),
        )
        client = make_client(session)

        client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        assert keys_sent(session) == ["run:0", "run:0"]

    def test_a_timeout_reuses_the_key(self):
        session = FakeSession()
        session.route(
            "POST",
            "/jobs",
            requests.exceptions.Timeout("read timed out"),
            FakeResponse(200, fixture("create_closed")),
        )
        client = make_client(session)

        client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        assert keys_sent(session) == ["run:0", "run:0"]


def _supplier(sequence):
    return _key_supplier(sequence)


class TestStatusMapping:
    def test_a_create_409_is_a_failure_even_when_the_body_names_a_job(self):
        """A 409 never means "your earlier submission succeeded, here it is": a real
        replay returns the original 2xx, and the error envelope defines no job id, so
        adopting one would stop a job this process does not own."""
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(409, fixture("create_closed")))
        client = make_client(session)

        with pytest.raises(BatchClientError) as excinfo:
            client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        assert "run:0" in str(excinfo.value)
        assert "dashboard" in str(excinfo.value)

    def test_a_create_409_naming_no_job_fails_and_names_the_key(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(409, fixture("create_409_idempotency_conflict")))
        client = make_client(session)

        with pytest.raises(BatchClientError) as excinfo:
            client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        assert "run:0" in str(excinfo.value)
        assert "dashboard" in str(excinfo.value)

    def test_an_add_tasks_409_is_retried_because_it_means_not_accepted(self):
        """The documented cause is ingest still in progress, so the chunk was not
        taken — which is the one add-tasks outcome that is safe to repeat."""
        session = FakeSession()
        session.route(
            "POST",
            "/jobs/job_01SYNTHETICOPEN/tasks",
            FakeResponse(409, {"message": "ingestion in progress"}),
            FakeResponse(200, {"job_id": "job_01SYNTHETICOPEN", "accepted_tasks": 3}),
        )
        client = make_client(session)

        payload = client.add_tasks("job_01SYNTHETICOPEN", [], deadline=None)

        assert payload["accepted_tasks"] == 3
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/tasks")) == 2

    def test_closing_an_already_closed_job_is_success(self):
        session = FakeSession()
        session.route("POST", "/jobs/j/close", FakeResponse(409, fixture("close_409_already_closed")))

        make_client(session).close_job("j", deadline=None)

    def test_a_rejected_close_still_fails(self):
        session = FakeSession()
        session.route("POST", "/jobs/j/close", FakeResponse(404, {"message": "no such job"}))

        with pytest.raises(BatchClientError, match="404"):
            make_client(session).close_job("j", deadline=None)

    def test_stop_reads_the_run_again_when_it_is_already_terminal(self):
        session = FakeSession()
        session.route("POST", "/jobs/j/stop", FakeResponse(409, fixture("stop_409_run_not_stoppable")))
        session.route("GET", "/jobs/j/runs/r", FakeResponse(200, fixture("run_poll_completed")))
        client = make_client(session)

        run = client.stop_run(_job(job_id="j", run_id="r"), deadline=None)

        assert run["status"] == "completed"
        assert len(session.calls_to("GET", "/jobs/j/runs/r")) == 1

    def test_any_stop_409_re_reads_the_run_rather_than_guessing_a_code(self):
        """The vendor documents one meaning for this 409 and never enumerates its
        `code` values, so the run's own status is the discriminator."""
        session = FakeSession()
        session.route("POST", "/jobs/j/stop", FakeResponse(409, {"code": "something_else"}))
        session.route("GET", "/jobs/j/runs/r", FakeResponse(200, fixture("run_poll_completed")))

        run = make_client(session).stop_run(_job(job_id="j", run_id="r"), deadline=None)

        assert run["status"] == "completed"

    @pytest.mark.parametrize("status", [401, 404])
    def test_a_rejected_get_run_raises_rather_than_being_parsed(self, status):
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r", FakeResponse(status, {"message": "nope"}))

        with pytest.raises(BatchClientError, match=str(status)):
            make_client(session).get_run("j", "r")

    @pytest.mark.parametrize("status", [401, 404])
    def test_a_rejected_results_page_raises_rather_than_yielding_nothing(self, status):
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r/results", FakeResponse(status, {"message": "nope"}))

        with pytest.raises(BatchClientError, match=str(status)):
            list(make_client(session).iter_results("j", "r"))


def _job(job_id="job_01SYNTHETICCLOSED", run_id="run_01SYNTHETICCLOSED", submitted=3, accepted=3):
    return BatchJob(
        job_id=job_id, run_id=run_id, lifecycle="closed", submitted_tasks=submitted, accepted_tasks=accepted
    )


class TestResultsAndBodies:
    def test_the_cursor_walks_both_pages_and_stops(self):
        """Page two is routed by the cursor, not by call order: a double that hands
        pages out in sequence cannot see a request that stopped sending one."""
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r/results", FakeResponse(200, fixture("results_page_1")))
        session.route(
            "GET", "/jobs/j/runs/r/results?cursor=cursor-page-2", FakeResponse(200, fixture("results_page_2"))
        )

        entries = list(make_client(session).iter_results("j", "r"))

        assert [entry["external_id"] for entry in entries] == ["126693", "126694", "126695", "126696"]
        calls = session.calls_to("GET", "/jobs/j/runs/r/results")
        assert len(calls) == 2
        assert "cursor=cursor-page-2" in calls[1]["url"]

    def test_a_repeated_cursor_terminates_instead_of_looping(self):
        session = FakeSession()
        page = FakeResponse(200, {"results": [{"a": 1}], "next_cursor": "same"})
        session.route("GET", "/jobs/j/runs/r/results", page)
        session.route("GET", "/jobs/j/runs/r/results?cursor=same", page)

        entries = list(make_client(session).iter_results("j", "r"))

        assert len(entries) == 2
        assert len(session.calls_to("GET", "/jobs/j/runs/r/results")) == 2

    def test_a_body_is_parsed_as_json_whatever_the_reported_type(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/126693"
        session = FakeSession()
        session.route("GET", url, FakeResponse(200, text=json.dumps(fixture("result_body_matches"))))

        body = make_client(session).fetch_body(url + "?X-Amz-Expires=7200")

        assert isinstance(body, list)
        assert len(body) == 2

    def test_a_body_fetch_carries_no_api_key(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/126693"
        session = FakeSession()
        session.route("GET", url, FakeResponse(200, text="[]"))

        make_client(session).fetch_body(url)

        assert "X-API-Key" not in session.calls[-1]["headers"]

    def test_a_failed_body_download_retries_once_then_raises_its_own_error(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/126693"
        session = FakeSession()
        session.route("GET", url, FakeResponse(403, text="<Error>AccessDenied</Error>"))

        with pytest.raises(BodyFetchError):
            make_client(session).fetch_body(url)

        assert len(session.calls_to("GET", url)) == 2

    def test_a_body_fetch_error_is_not_a_generic_client_error_by_accident(self):
        assert issubclass(BodyFetchError, BatchClientError)


class TestRunBudget:
    def test_the_reserve_sits_exactly_below_the_whole_run_deadline(self):
        clock = FakeClock()
        budget = RunBudget(30, 5, time_source=clock.now)
        budget.start()

        assert budget.deadline == clock.now() + 30 * 60
        assert budget.pass1_deadline == budget.deadline - 5 * 60

    def test_the_deadline_is_unreadable_before_the_first_request(self):
        with pytest.raises(RuntimeError, match="start"):
            _ = RunBudget(30, 5).deadline

    def test_the_cleanup_allowance_outlives_the_run_budget(self):
        assert _cleanup_deadline(lambda: 1000.0) == 1000.0 + STOP_CLEANUP_SECONDS


class TestDeadlines:
    def test_a_request_timeout_is_clamped_to_the_time_left(self):
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r", FakeResponse(200, fixture("run_poll_completed")))
        clock = FakeClock()
        client = make_client(session, clock, timeout=30)

        client.get_run("j", "r", deadline=clock.now() + 7)

        assert session.calls[-1]["timeout"] == 7

    def test_a_deadline_already_past_issues_no_request_at_all(self):
        session = FakeSession()
        clock = FakeClock()
        client = make_client(session, clock)

        with pytest.raises(BudgetExpired):
            client.get_run("j", "r", deadline=clock.now() - 1)

        assert session.calls == []

    def test_a_backoff_that_would_overrun_the_deadline_is_clamped(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(503, {"message": "unavailable"}))
        clock = FakeClock()
        client = make_client(session, clock, retry_delay=100.0)
        start = clock.now()

        with pytest.raises(BudgetExpired):
            client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=start + 5)

        assert clock.now() - start == 5.0
        assert len(session.calls_to("POST", "/jobs")) == 1


class TestPollingAndSettle:
    def test_a_completed_run_reports_its_spend_without_stopping_anything(self):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_running")),
            FakeResponse(200, fixture("run_poll_completed")),
        )
        clock = FakeClock()
        client = make_client(session, clock)

        outcome = poll_until_terminal(client, _job(), deadline=clock.now() + 600)

        assert outcome.termination == TERMINATION_COMPLETE
        assert outcome.spend == 3
        assert outcome.spend_is_lower_bound is False
        assert session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop") == []

    def test_a_poll_timeout_stops_and_settles_rather_than_raising(self):
        session = _settling_session(completed_by_poll=[3], never_finishes=True)
        clock = FakeClock()
        client = make_client(session, clock)
        start = clock.now()

        outcome = poll_until_terminal(client, _job(), deadline=start + 20)

        assert outcome.termination == TERMINATION_TIMED_OUT
        assert outcome.spend == 3
        assert outcome.spend_is_lower_bound is False
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop")) == 1
        assert clock.now() - start <= 20 + STOP_CLEANUP_SECONDS

    def test_an_unsettled_run_reports_a_lower_bound_inside_the_cleanup_allowance(self):
        session = _settling_session(completed_by_poll=list(range(1, 400)), total=10_000, never_finishes=True)
        clock = FakeClock()
        client = make_client(session, clock)
        start = clock.now()

        outcome = poll_until_terminal(client, _job(), deadline=start + 20)

        assert outcome.termination == TERMINATION_TIMED_OUT
        assert outcome.spend_is_lower_bound is True
        cleanup_elapsed = clock.now() - (start + 20)
        assert 0 < cleanup_elapsed <= STOP_CLEANUP_SECONDS

    def test_settle_returns_once_the_run_reports_every_task_complete(self):
        session = _settling_session(completed_by_poll=[1, 3])
        clock = FakeClock()
        client = make_client(session, clock)

        spend, lower_bound = client.settle(_job(), deadline=clock.now() + STOP_CLEANUP_SECONDS)

        assert spend == 3
        assert lower_bound is False
        assert clock.now() > 1000.0

    def test_settle_gives_up_at_its_cap_and_says_the_figure_is_short(self):
        # A counter that keeps climbing never stabilises, so the cap is what ends it.
        session = _settling_session(completed_by_poll=list(range(1, 400)), total=10_000)
        clock = FakeClock()
        client = make_client(session, clock)
        start = clock.now()

        spend, lower_bound = client.settle(_job(), deadline=start + STOP_CLEANUP_SECONDS)

        assert lower_bound is True
        assert spend == 3
        assert clock.now() - start <= SETTLE_CAP_SECONDS

    def test_settle_honours_a_tighter_cleanup_deadline_than_its_own_cap(self):
        session = _settling_session(completed_by_poll=list(range(1, 400)), total=10_000)
        clock = FakeClock()
        client = make_client(session, clock)
        start = clock.now()

        spend, lower_bound = client.settle(_job(), deadline=start + 30)

        assert (spend, lower_bound) == (3, True)
        assert clock.now() - start <= 30

    def test_a_still_running_run_does_not_settle_on_a_stalled_counter(self):
        """Two equal reads fifteen seconds apart mean the work is slow, not drained.

        Stabilisation is only meaningful once the run itself is terminal, which is
        why it is gated on the status rather than on the counter alone.
        """
        session = FakeSession()
        run = fixture("run_poll_running")
        run["stats"] = {**run["stats"], "total": 3, "completed": 1}
        session.route("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, run))
        clock = FakeClock()
        start = clock.now()

        spend, lower_bound = make_client(session, clock).settle(_job(), deadline=start + STOP_CLEANUP_SECONDS)

        assert lower_bound is True
        assert clock.now() - start >= SETTLE_CAP_SECONDS - POLL_SECONDS
        assert spend == 1

    def test_a_stopped_run_settles_once_its_counter_stops_moving(self):
        """The vendor leaves a stopped run's pending tasks unrun, so `completed`
        provably never reaches `total`. Waiting for it would report a lower bound on
        every abort; what settles is the counter going quiet."""
        session = FakeSession()
        run = fixture("run_poll_completed")
        run["status"] = "stopped"
        run["stats"] = {**run["stats"], "total": 10, "completed": 4}
        session.route("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, run))
        clock = FakeClock()
        start = clock.now()

        spend, lower_bound = make_client(session, clock).settle(_job(), deadline=start + STOP_CLEANUP_SECONDS)

        assert lower_bound is False
        assert spend == 3
        assert clock.now() - start < SETTLE_CAP_SECONDS

    def test_an_unacknowledged_chunk_keeps_the_figure_a_lower_bound(self):
        """A lost add-tasks response may still have been accepted, so `total` can
        grow — the counter looking stable proves nothing while that is outstanding."""
        session = FakeSession()
        run = fixture("run_poll_completed")
        run["status"] = "stopped"
        run["stats"] = {**run["stats"], "total": 10, "completed": 4}
        session.route("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, run))
        clock = FakeClock()
        start = clock.now()

        spend, lower_bound = make_client(session, clock).settle(
            _job(submitted=1001, accepted=1000), deadline=start + STOP_CLEANUP_SECONDS
        )

        assert lower_bound is True
        assert clock.now() - start >= SETTLE_CAP_SECONDS - POLL_SECONDS

    def test_a_job_with_no_run_id_cannot_settle_and_says_so(self):
        session = FakeSession()

        assert make_client(session).settle(_job(run_id=""), deadline=None) == (None, True)
        assert session.calls == []


def _run_with(*, completed, total=3, status="running"):
    run = fixture("run_poll_completed")
    run["status"] = status
    run["stats"] = {**run["stats"], "total": total, "completed": completed}
    return run


def _settling_session(*, completed_by_poll, total=3, never_finishes=False, stopped_status="stopped"):
    """A session whose run reports its completion counter over successive polls.

    ``completed_by_poll`` gives ``stats.completed`` for each read; the last value
    repeats, so a list ending in a repeat models work that has drained and a
    generator-like growing list models work that never does. With
    ``never_finishes`` the run stays non-terminal until it is stopped, at which
    point it reports ``stopped_status`` — which is what the vendor does, and what
    makes stabilisation meaningful.
    """
    session = FakeSession()
    state = {"stopped": False, "reads": 0}
    phases = list(completed_by_poll)

    def get_run(method, url, body):
        completed = phases[min(state["reads"], len(phases) - 1)]
        state["reads"] += 1
        if never_finishes and not state["stopped"]:
            run = fixture("run_poll_running")
        else:
            run = fixture("run_poll_completed")
            run["status"] = stopped_status if state["stopped"] else run["status"]
        run["stats"] = {**run["stats"], "total": total, "completed": completed}
        return FakeResponse(200, run)

    def stop(method, url, body):
        state["stopped"] = True
        return FakeResponse(200, fixture("run_poll_running"))

    session.route("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", get_run)
    session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", stop)
    return session


class TestExpiryOutcomes:
    def test_an_expiry_mid_submission_carries_the_partial_job_and_stops_adding(self):
        clock = FakeClock()
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_open")))

        def add(method, url, body):
            clock.t += 100
            return FakeResponse(200, {"job_id": "job_01SYNTHETICOPEN", "accepted_tasks": len(body["tasks"])})

        session.route("POST", "/jobs/job_01SYNTHETICOPEN/tasks", add)
        session.route("POST", "/jobs/job_01SYNTHETICOPEN/close", FakeResponse(200, fixture("close")))
        client = make_client(session, clock)

        with pytest.raises(BudgetExpired) as excinfo:
            submit_tasks(
                client,
                _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
                sequence=SubmissionSequence("run"),
                deadline=clock.now() + 50,
            )

        job = excinfo.value.job
        assert job is not None
        assert job.job_id == "job_01SYNTHETICOPEN"
        # The unacknowledged chunk counts as submitted but not accepted, which is
        # what stops settle trusting the total and calling the run settled early.
        # Counting intent rather than acknowledgement is deliberate: from here the
        # two are indistinguishable, and over-counting only costs a settle wait.
        assert (job.submitted_tasks, job.accepted_tasks) == (1001, 1000)
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/tasks")) == 1
        assert session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/close") == []

    def test_the_two_expiries_are_different_types(self):
        assert not issubclass(BudgetExpired, BatchClientError)
        assert not issubclass(BatchClientError, BudgetExpired)


class TestCredentialSafety:
    def test_an_exhausted_request_never_names_the_key(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(500, {"message": "boom"}))
        client = make_client(session)

        with pytest.raises(BatchClientError) as excinfo:
            client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        assert API_KEY not in str(excinfo.value)

    def test_an_error_body_echoing_the_key_comes_back_redacted(self):
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r", FakeResponse(401, text=f"bad key {API_KEY}"))
        client = make_client(session)

        with pytest.raises(BatchClientError) as excinfo:
            client.get_run("j", "r")

        assert API_KEY not in str(excinfo.value)
        assert "REDACTED" in str(excinfo.value)

    def test_a_retry_warning_is_redacted(self, caplog):
        session = FakeSession()
        session.route(
            "POST",
            "/jobs",
            requests.exceptions.ConnectionError(f"failed to connect with apikey={API_KEY}"),
            FakeResponse(200, fixture("create_closed")),
        )
        client = make_client(session)

        with caplog.at_level(logging.WARNING, logger="scripts.batch_drain_queue"):
            client.create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert warnings, "the retry should have logged a warning"
        assert any("REDACTED" in message for message in warnings)
        assert all(API_KEY not in message for message in warnings)


class TestValidation:
    def test_a_wait_cap_below_the_floor_is_rejected(self, capsys):
        assert main(valid_argv(**{"--wait-cap-minutes": "4", "--club-reserve-minutes": "2", "--dry-run": ""})) == 1
        assert "--wait-cap-minutes must be at least 5" in flat_output(capsys)

    def test_the_floor_itself_is_accepted(self):
        args = _args(wait_cap_minutes=MIN_WAIT_CAP_MINUTES + MIN_CLUB_RESERVE_MINUTES,
                     club_reserve_minutes=MIN_CLUB_RESERVE_MINUTES)
        assert _validate_run_args(args) == []

    def test_a_reserve_that_leaves_no_first_pass_is_rejected(self, capsys):
        assert main(valid_argv(**{"--wait-cap-minutes": "20", "--club-reserve-minutes": "20", "--dry-run": ""})) == 1
        assert "must be less than --wait-cap-minutes" in flat_output(capsys)

    def test_a_missing_proxy_tier_is_rejected(self, capsys):
        argv = ["--team-id", "126693", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5", "--dry-run"]
        assert main(argv) == 1
        assert "--premium-proxy is required" in flat_output(capsys)

    def test_a_real_run_needs_at_least_one_team(self, capsys, monkeypatch):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        argv = ["--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]
        assert main(argv) == 1
        assert "at least one --team-id is required" in flat_output(capsys)

    def test_a_dry_run_with_no_teams_is_allowed(self):
        args = _args(team_id=[], dry_run=True)
        assert _validate_run_args(args) == []

    def test_a_real_run_needs_the_api_key(self, monkeypatch):
        monkeypatch.delenv("ZENROWS_API_KEY", raising=False)
        errors = _validate_run_args(_args(dry_run=False))
        assert any("ZENROWS_API_KEY" in error for error in errors)

    def test_a_dry_run_does_not_need_the_api_key(self, monkeypatch):
        monkeypatch.delenv("ZENROWS_API_KEY", raising=False)
        assert _validate_run_args(_args(dry_run=True)) == []


def _args(**overrides):
    values = {
        "team_id": ["126693"],
        "wait_cap_minutes": 30,
        "club_reserve_minutes": 5,
        "premium_proxy": "false",
        "dry_run": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestProxyTierThroughTheCli:
    @pytest.mark.parametrize(
        "flag,expected",
        [("false", DATACENTER_PROXY_PARAMS), ("true", PREMIUM_PROXY_PARAMS)],
    )
    def test_the_tier_flag_reaches_the_transmitted_body(self, flag, expected, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        client = make_client(session, FakeClock())

        exit_code = main(
            ["--team-id", "126693", "--premium-proxy", flag, "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"],
            client=client,
        )
        capsys.readouterr()

        assert exit_code == 0
        submitted = session.calls_to("POST", "/jobs")[0]["json"]["tasks"]
        assert submitted[0]["zenrows_params"] == expected

    def test_no_submitted_task_ever_asks_for_auto_mode(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()

        main(
            ["--team-id", "126693", "--premium-proxy", "true", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"],
            client=make_client(session, FakeClock()),
        )
        capsys.readouterr()

        for call in session.calls:
            for task in (call["json"] or {}).get("tasks", []):
                assert task["zenrows_params"].get("mode") != "auto"

    def test_a_reported_html_type_still_reaches_json_parsing(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()

        main(
            ["--team-id", "126693", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"],
            client=make_client(session, FakeClock()),
        )
        out = flat_output(capsys)

        assert "126693: 2 match(es)" in out
        assert "126694: 2 match(es)" in out

    def test_one_failed_body_is_counted_and_the_rest_still_run(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session._routes[("GET", "https://zenrows-results.s3.amazonaws.invalid/r/126693")] = [
            FakeResponse(403, text="<Error>AccessDenied</Error>")
        ]

        exit_code = main(
            ["--team-id", "126693", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"],
            client=make_client(session, FakeClock()),
        )
        out = flat_output(capsys)

        assert exit_code == 0
        assert "body download failed" in out
        assert "126694: 2 match(es)" in out
        assert "bodies fetched: 1" in out
        assert "tasks without a body: 2" in out


def _happy_path_session():
    session = FakeSession()
    session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 1}))
    session.route(
        "GET",
        "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
        FakeResponse(200, fixture("run_poll_completed")),
    )
    session.route(
        "GET",
        "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results",
        FakeResponse(200, fixture("results_page_1")),
    )
    session.route(
        "GET",
        "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results?cursor=cursor-page-2",
        FakeResponse(200, fixture("results_page_2")),
    )
    body = json.dumps(fixture("result_body_matches"))
    session.route("GET", "https://zenrows-results.s3.amazonaws.invalid/r/126693", FakeResponse(200, text=body))
    session.route("GET", "https://zenrows-results.s3.amazonaws.invalid/r/126694", FakeResponse(200, text=body))
    return session


class TestPayloadShapes:
    """The poll endpoint answers with the run itself; a create nests it under
    latest_run. Reading the wrong one leaves a finished run unrecognised."""

    def test_a_polled_run_is_read_from_the_root(self):
        assert _run_status(fixture("run_poll_completed")) == "completed"
        assert _spend_credits(fixture("run_poll_completed")) == 3

    def test_a_created_job_carries_its_run_under_latest_run(self):
        """A create response also has a root `status`, but that is the job's
        (open/closed). Reading it as a run status is the trap these two
        readers refuse to accommodate."""
        job_payload = fixture("create_closed")
        assert job_payload["status"] == "closed"
        assert _run_status(job_payload["latest_run"]) == "pending"
        assert _spend_credits(job_payload["latest_run"]) == 0
        assert _run_status(job_payload) == "closed"

    def test_spend_is_the_credit_count_not_the_object(self):
        assert _spend_credits({"stats": {"spend": {"credits": 7, "cost": 0.008}}}) == 7

    def test_a_missing_or_unusable_spend_reads_as_unknown(self):
        assert _spend_credits({}) is None
        assert _spend_credits({"stats": {}}) is None
        assert _spend_credits({"stats": {"spend": {"cost": 0.1}}}) is None

    def test_every_vendor_status_is_classified(self):
        vendor_enum = {"running", "pending", "completed", "stopped", "failed", "deleted"}
        assert TERMINAL_RUN_STATUSES | ACTIVE_RUN_STATUSES == vendor_enum
        assert not TERMINAL_RUN_STATUSES & ACTIVE_RUN_STATUSES

    @pytest.mark.parametrize("status", sorted(TERMINAL_RUN_STATUSES))
    def test_each_terminal_status_ends_the_poll_without_stopping(self, status):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_completed") | {"status": status}),
        )
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert outcome.termination == TERMINATION_COMPLETE
        assert outcome.spend == 3
        assert session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop") == []

    def test_an_unrecognized_status_is_named_once_and_polled_on(self, caplog):
        session = _settling_session(completed_by_poll=[3], never_finishes=True)
        session._routes[("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED")] = [
            lambda m, u, b: FakeResponse(200, fixture("run_poll_running") | {"status": "cancelled"})
        ]
        clock = FakeClock()
        client = make_client(session, clock)

        with caplog.at_level(logging.WARNING, logger="scripts.batch_drain_queue"):
            outcome = poll_until_terminal(client, _job(), deadline=clock.now() + 40)

        named = [r.getMessage() for r in caplog.records if "Unrecognized run status" in r.getMessage()]
        assert len(named) == 1
        assert "cancelled" in named[0]
        assert outcome.termination == TERMINATION_TIMED_OUT


class TestCleanupAlwaysRuns:
    def test_a_rejected_poll_stops_the_run_instead_of_abandoning_it(self):
        session = _settling_session(completed_by_poll=[3], never_finishes=True)
        session._routes[("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED")] = [
            FakeResponse(500, {"message": "upstream blip"}),
            FakeResponse(500, {"message": "upstream blip"}),
            FakeResponse(500, {"message": "upstream blip"}),
            FakeResponse(200, fixture("run_poll_completed")),
        ]
        clock = FakeClock()
        client = make_client(session, clock)

        outcome = poll_until_terminal(client, _job(), deadline=clock.now() + 600)

        assert outcome.termination == TERMINATION_ABORTED
        assert outcome.error and "500" in outcome.error
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop")) == 1

    def test_a_failed_stop_still_takes_the_spend_snapshot_and_says_so(self):
        session = _settling_session(completed_by_poll=[3], never_finishes=True)
        session.replace("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(500, {"message": "nope"}))
        session.replace(
            "GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, fixture("run_poll_completed"))
        )
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() - 1)

        assert outcome.spend == 3
        assert outcome.stop_confirmed is False

    def test_a_successful_stop_is_recorded_as_confirmed(self):
        """stop_confirmed must distinguish a confirmed stop from an unconfirmed one;
        the report turns on it."""
        session = _settling_session(completed_by_poll=[3], never_finishes=True)
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() - 1)

        assert outcome.stop_confirmed is True

    def test_an_unconfirmed_stop_tells_the_operator_to_check_the_dashboard(self, capsys):
        _report_outcome(
            RunOutcome(
                job=_job(),
                spend=1,
                spend_is_lower_bound=True,
                termination=TERMINATION_ABORTED,
                stop_confirmed=False,
            )
        )
        out = flat_output(capsys)

        assert "not confirmed" in out
        assert "dashboard" in out

    def test_a_confirmed_stop_says_so_plainly(self, capsys):
        _report_outcome(
            RunOutcome(
                job=_job(),
                spend=1,
                spend_is_lower_bound=False,
                termination=TERMINATION_TIMED_OUT,
                stop_confirmed=True,
            )
        )
        out = flat_output(capsys)

        assert "the run was stopped" in out
        assert "not confirmed" not in out

    def test_a_failed_stop_does_not_overwrite_the_reason_the_run_aborted(self):
        """A failed stop is a consequence; the poll rejection that ended the run is
        the reason to report."""
        session = _settling_session(completed_by_poll=[3], never_finishes=True)
        session.replace(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(401, {"message": "the poll rejection that ended the run"}),
        )
        session.replace("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(500, {"message": "and the stop failed"}))
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert "401" in outcome.error
        assert outcome.stop_confirmed is False

    def test_settle_reports_an_unknown_lower_bound_when_the_run_cannot_be_read(self):
        session = FakeSession()
        session.route("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(500, {"m": "blip"}))
        clock = FakeClock()

        spend, lower_bound = make_client(session, clock).settle(_job(), deadline=clock.now() + STOP_CLEANUP_SECONDS)

        assert (spend, lower_bound) == (None, True)

    def test_settle_keeps_the_last_spend_it_read_when_a_later_read_fails(self):
        """The credits are spent either way, so a figure already in hand beats
        reporting nothing at all."""
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, _run_with(completed=1)),
            FakeResponse(500, {"m": "blip"}),
        )
        clock = FakeClock()

        spend, lower_bound = make_client(session, clock).settle(_job(), deadline=clock.now() + STOP_CLEANUP_SECONDS)

        assert (spend, lower_bound) == (3, True)

    def test_a_failure_after_the_create_carries_the_job_out_for_stopping(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_open")))
        session.route("POST", "/jobs/job_01SYNTHETICOPEN/tasks", FakeResponse(400, {"message": "bad task"}))
        client = make_client(session)

        with pytest.raises(BatchClientError) as excinfo:
            submit_tasks(
                client,
                _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
                sequence=SubmissionSequence("run"),
                deadline=None,
            )

        assert excinfo.value.job is not None
        assert excinfo.value.job.job_id == "job_01SYNTHETICOPEN"


class TestCredentialValidation:
    @pytest.mark.parametrize("key", ["abc123\n", "abc123\r", " abc123", "abc 123", "abc123\t"])
    def test_a_key_that_cannot_travel_in_a_header_is_refused(self, key):
        with pytest.raises(BatchClientError) as excinfo:
            ZenRowsBatchClient(key, session=FakeSession())
        assert key.strip() not in str(excinfo.value)

    def test_an_empty_key_is_refused(self):
        with pytest.raises(BatchClientError, match="empty"):
            ZenRowsBatchClient("", session=FakeSession())

    def test_a_clean_key_is_accepted(self):
        assert ZenRowsBatchClient("abc123", session=FakeSession()).api_key == "abc123"


class TestBodyDecoding:
    def test_a_utf8_body_served_as_html_is_not_mangled(self):
        """The vendor serves JSON as text/html with no charset, which requests
        decodes as ISO-8859-1. Decoding the text would corrupt every accented name
        while still parsing cleanly, so the bytes are what gets parsed."""
        url = "https://zenrows-results.s3.amazonaws.invalid/r/1"
        payload = [{"homeTeam": {"name": "Fútbol Águilas"}}]
        session = FakeSession()
        session.route("GET", url, FakeResponse(200, content=json.dumps(payload, ensure_ascii=False).encode("utf-8")))

        body = make_client(session).fetch_body(url)

        assert body[0]["homeTeam"]["name"] == "Fútbol Águilas"

    def test_a_transport_failure_retries_once_then_raises_body_fetch_error(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/1"
        session = FakeSession()
        session.route("GET", url, requests.exceptions.ConnectionError("reset"))

        with pytest.raises(BodyFetchError):
            make_client(session).fetch_body(url)

        assert len(session.calls_to("GET", url)) == 2

    def test_a_200_carrying_garbage_raises_rather_than_reading_as_no_games(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/1"
        session = FakeSession()
        session.route("GET", url, FakeResponse(200, text="<Error>truncated</Error>"))

        with pytest.raises(BodyFetchError):
            make_client(session).fetch_body(url)

        assert len(session.calls_to("GET", url)) == 1

    def test_a_body_fetch_stops_at_the_deadline(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/1"
        session = FakeSession()
        session.route("GET", url, FakeResponse(200, text="[]"))
        clock = FakeClock()

        with pytest.raises(BudgetExpired):
            make_client(session, clock).fetch_body(url, deadline=clock.now() - 1)

        assert session.calls == []


class TestRunReport:
    def _report(self, capsys, **kwargs):
        _report_outcome(RunOutcome(job=_job(), **kwargs))
        return flat_output(capsys)

    def test_a_settled_run_reports_its_credits_plainly(self, capsys):
        out = self._report(capsys, spend=42, spend_is_lower_bound=False)
        assert "credits spent: 42" in out
        assert "lower bound" not in out

    def test_an_unsettled_run_labels_the_figure_a_lower_bound(self, capsys):
        out = self._report(capsys, spend=42, spend_is_lower_bound=True)
        assert "credits spent: 42" in out
        assert "lower bound" in out

    def test_an_unknown_spend_says_so_rather_than_printing_none(self, capsys):
        out = self._report(capsys, spend=None, spend_is_lower_bound=True)
        assert "credits spent: unknown" in out

    def test_a_timed_out_run_does_not_read_like_a_complete_one(self, capsys):
        out = self._report(capsys, spend=1, spend_is_lower_bound=False, termination=TERMINATION_TIMED_OUT)
        assert "did not finish inside its budget" in out

    def test_an_aborted_run_says_it_aborted_without_claiming_a_phase(self, capsys):
        out = self._report(capsys, spend=1, spend_is_lower_bound=True, termination=TERMINATION_ABORTED)
        assert "aborted" in out.lower()
        # It is also set after a fully-submitted run, so it must not blame submission.
        assert "submission" not in out.lower()

    def test_a_failure_reason_reaches_the_operator(self, capsys):
        out = self._report(capsys, spend=None, spend_is_lower_bound=True, error="upstream 500")
        assert "upstream 500" in out


class _StopWiring(Exception):
    """Raised by the stub client so the wiring test stops before any request."""


class TestProductionWiring:
    def test_the_client_is_built_from_the_env_var_validation_checks(self, monkeypatch):
        """A drifted name would pass validation and die inside the generic handler."""
        seen = {}

        def _stub(key, **kwargs):
            seen["key"] = key
            raise _StopWiring()

        monkeypatch.setenv("ZENROWS_API_KEY", "env-key-123")
        monkeypatch.setattr("scripts.batch_drain_queue.ZenRowsBatchClient", _stub)

        with pytest.raises(_StopWiring):
            run_batch(
                _args(dry_run=False),
                premium=False,
                sequence=SubmissionSequence("run"),
                budget=RunBudget(30, 5),
            )

        assert seen["key"] == "env-key-123"

    def test_the_session_mounts_no_retry_budget(self):
        adapter = ZenRowsBatchClient("abc123")._build_session().get_adapter("https://x.invalid")
        assert adapter.max_retries.total == 0

    def test_a_cancelled_run_exits_130(self, monkeypatch):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = FakeSession()
        session.route("POST", "/jobs", KeyboardInterrupt())
        argv = ["--team-id", "1", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]

        assert main(argv, client=make_client(session)) == 130

    def test_an_unexpected_failure_exits_1_without_a_traceback(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = FakeSession()
        session.route("POST", "/jobs", RuntimeError("something odd"))
        argv = ["--team-id", "1", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]

        assert main(argv, client=make_client(session)) == 1
        assert "something odd" in flat_output(capsys)

    def test_the_dry_run_branch_previews_the_teams_it_was_given(self, capsys):
        assert main(valid_argv(**{"--dry-run": ""})) == 0
        out = flat_output(capsys)
        assert "tasks: 1" in out
        assert "/teams/126693/matches" in out


class TestRemainingStatusArms:
    def test_a_rejected_add_tasks_fails_rather_than_counting_as_accepted(self):
        session = FakeSession()
        session.route("POST", "/jobs/j/tasks", FakeResponse(400, {"message": "malformed"}))

        with pytest.raises(BatchClientError, match="400"):
            make_client(session).add_tasks("j", [], deadline=None)

    def test_a_2xx_that_is_not_json_fails_with_the_status_and_body(self):
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r", FakeResponse(200, text="<html>maintenance</html>"))

        with pytest.raises(BatchClientError, match="not JSON"):
            make_client(session).get_run("j", "r")

    def test_a_409_that_is_not_json_still_fails_cleanly(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(409, text="<html>conflict</html>"))

        with pytest.raises(BatchClientError, match="409"):
            make_client(session).create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

    def test_a_stop_409_on_a_job_with_no_run_id_does_not_pretend_to_re_read(self):
        session = FakeSession()
        session.route("POST", "/jobs/j/stop", FakeResponse(409, text="<html>conflict</html>"))

        assert make_client(session).stop_run(_job(job_id="j", run_id=""), deadline=None) == {}

    def test_the_add_tasks_contract_fixture_reports_a_per_submission_count(self):
        session = FakeSession()
        session.route("POST", "/jobs/j/tasks", FakeResponse(200, fixture("add_tasks")))

        payload = make_client(session).add_tasks("j", [], deadline=None)

        assert payload["accepted_tasks"] == MAX_TASKS_PER_SUBMISSION
        assert payload["last_batch_received"] is False

    def test_submitting_nothing_fails_with_a_message_not_an_index_error(self):
        with pytest.raises(BatchClientError, match="no tasks"):
            submit_tasks(make_client(), [], sequence=SubmissionSequence("run"), deadline=None)


class TestValidationFloors:
    @pytest.mark.parametrize("reserve", [0, -10, 1, MIN_CLUB_RESERVE_MINUTES - 1])
    def test_a_reserve_too_short_to_cover_cleanup_is_rejected(self, reserve):
        """Anything below the cleanup allowance is consumed entirely by stopping and
        settling, so a timed-out run pays for every task and collects none."""
        errors = _validate_run_args(_args(club_reserve_minutes=reserve))
        assert any("--club-reserve-minutes" in error for error in errors)

    def test_the_cleanup_allowance_fits_inside_the_minimum_reserve(self):
        assert MIN_CLUB_RESERVE_MINUTES * 60 >= STOP_CLEANUP_SECONDS

    def test_a_reserve_at_the_floor_is_accepted(self):
        assert _validate_run_args(_args(club_reserve_minutes=MIN_CLUB_RESERVE_MINUTES, wait_cap_minutes=30)) == []


class TestRedactionOrdering:
    def test_a_key_straddling_the_excerpt_cut_is_matched_before_truncation(self):
        """Truncating first leaves an unmatchable prefix of the key in the message.

        Asserting only that the *whole* key is absent passes either way, because a
        cut key is no longer the whole key. The tell is whether the redactor ever
        matched at all: scrub-then-truncate leaves REDACTED in the excerpt, and
        truncate-then-scrub leaves a live fragment and no marker.
        """
        key = "k" * 40
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r", FakeResponse(401, text="x" * 490 + key + "y" * 200))
        client = ZenRowsBatchClient(key, session=session)

        with pytest.raises(BatchClientError) as excinfo:
            client.get_run("j", "r")

        message = str(excinfo.value)
        assert "REDACTED" in message
        assert key[:20] not in message


class TestAcceptedTaskFallback:
    def test_a_closed_create_without_a_count_trusts_what_was_submitted(self):
        """Defaulting to zero here would trip the "accepted no tasks" guard and
        abort every run — after the billing job had already been created."""
        payload = {k: v for k, v in fixture("create_closed").items() if k != "accepted_tasks"}
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, payload))

        job = submit_tasks(
            make_client(session),
            _build_tasks([1, 2, 3], premium=False),
            sequence=SubmissionSequence("run"),
            deadline=None,
        )

        assert job.accepted_tasks == 3

    def test_a_create_reporting_zero_accepted_still_fails(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 0}))

        with pytest.raises(BatchClientError, match="accepted no tasks"):
            submit_tasks(
                make_client(session),
                _build_tasks([1], premium=False),
                sequence=SubmissionSequence("run"),
                deadline=None,
            )


class TestMarkupSafety:
    """Rich reads square brackets as markup, so vendor text reaches print unescaped
    at its peril: a bracketed lowercase token is deleted silently, and an unmatched
    closing tag raises from inside the handler that was reporting the failure."""

    def test_a_closing_tag_in_a_failure_reason_does_not_raise(self, capsys):
        _report_outcome(
            RunOutcome(job=_job(), spend=None, spend_is_lower_bound=True, error="upstream said [/bold] no")
        )
        assert "[/bold]" in flat_output(capsys)

    def test_a_bracketed_token_in_a_failure_reason_survives(self, capsys):
        _report_outcome(
            RunOutcome(job=_job(), spend=None, spend_is_lower_bound=True, error="rejected [invalid_key] here")
        )
        assert "[invalid_key]" in flat_output(capsys)

    def test_a_bracketed_token_in_a_per_task_error_survives(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session._routes[("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results")] = [
            FakeResponse(
                200,
                {
                    "results": [
                        {"external_id": "9", "status": "failed", "result_url": "", "error": {"code": "[bad_target]"}}
                    ],
                    "next_cursor": None,
                },
            )
        ]
        argv = ["--team-id", "1", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]

        main(argv, client=make_client(session, FakeClock()))

        assert "[bad_target]" in flat_output(capsys)


class TestReportIsGuaranteed:
    def test_a_failure_while_collecting_results_still_reports_the_spend(self, monkeypatch, capsys):
        """The credits are spent whether or not the download loop finishes, so the
        run must still say what it cost."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session._routes[("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results")] = [
            FakeResponse(500, {"message": "listing blew up"})
        ]
        argv = ["--team-id", "1", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]

        exit_code = main(argv, client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 1
        assert "credits spent: 3" in out
        assert "Run failed; stopping it" in out

    def test_an_unexpected_failure_mid_download_still_reports_the_spend(self, monkeypatch, capsys):
        """An exception the handler does not name must not swallow the cost of a run
        that already spent the credits."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session._routes[("GET", "https://zenrows-results.s3.amazonaws.invalid/r/126693")] = [
            RuntimeError("something nobody planned for")
        ]
        argv = ["--team-id", "1", "--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]

        exit_code = main(argv, client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 1
        assert "credits spent: 3" in out
        assert "something nobody planned for" in out
#
class TestWireValuesArePinned:
    """Every assertion here names the value it expects outright. A test that reads
    the constant under test on both sides cannot fail, and the wire values here
    carry a 10x billing difference."""

    def test_the_datacenter_tier_sends_no_proxy_parameters(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()

        main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        capsys.readouterr()

        assert session.calls_to("POST", "/jobs")[0]["json"]["tasks"][0]["zenrows_params"] == {}

    def test_the_residential_tier_sends_exactly_the_two_documented_keys(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()

        main(_real_run_argv("true"), client=make_client(session, FakeClock()))
        capsys.readouterr()

        assert session.calls_to("POST", "/jobs")[0]["json"]["tasks"][0]["zenrows_params"] == {
            "premium_proxy": "true",
            "proxy_country": "us",
        }

    def test_the_api_key_is_actually_sent_and_under_the_documented_header(self):
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r", FakeResponse(200, fixture("run_poll_completed")))

        make_client(session).get_run("j", "r")

        assert session.calls[-1]["headers"]["X-API-Key"] == API_KEY

    def test_the_session_carries_no_default_credential(self):
        """A key on the session would ride along to the presigned S3 link, which is
        a third party — the per-request header is what keeps it off that call."""
        assert ZenRowsBatchClient(API_KEY)._build_session().headers.get("X-API-Key") is None

    def test_the_run_statuses_are_the_vendor_enum_split_by_hand(self):
        assert TERMINAL_RUN_STATUSES == {"completed", "stopped", "failed", "deleted"}
        assert ACTIVE_RUN_STATUSES == {"running", "pending"}
        assert NON_TERMINAL_TASK_STATUSES == {"pending", "processing"}

    @pytest.mark.parametrize(
        "status,is_clean",
        [("completed", True), ("stopped", False), ("failed", False), ("deleted", False)],
    )
    def test_each_terminal_status_is_classified_as_success_or_failure(self, status, is_clean):
        """Asserting only what every arm shares — that polling ended — cannot tell a
        completed run from one someone stopped in the dashboard, which is the whole
        distinction the exit code rests on."""
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_completed") | {"status": status}),
        )
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert outcome.is_clean is is_clean
        assert (outcome.error is None) is is_clean
        if not is_clean:
            assert status in outcome.error
        assert session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop") == []

    @pytest.mark.parametrize("status", ["stopped", "failed", "deleted"])
    def test_a_terminal_run_that_stopped_short_has_not_settled(self, status):
        """Someone stops the run from the dashboard with work still dispatched: the
        spend keeps climbing, so reporting it unqualified would understate the cost."""
        run = fixture("run_poll_completed") | {"status": status}
        run["stats"] = {**run["stats"], "total": 10, "completed": 4}
        session = FakeSession()
        session.route("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, run))
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert outcome.spend_is_lower_bound is True

    def test_a_run_that_finished_every_task_reports_a_final_figure(self):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_completed")),
        )
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert outcome.spend_is_lower_bound is False

    @pytest.mark.parametrize("status", ["running", "pending"])
    def test_each_named_active_status_keeps_polling(self, status):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_running") | {"status": status}),
            FakeResponse(200, fixture("run_poll_completed")),
        )
        clock = FakeClock()

        poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert len(session.calls_to("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED")) == 2

    def test_the_create_body_names_its_lifecycle(self):
        session = _open_lifecycle_session()

        submit_tasks(
            make_client(session),
            _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
            sequence=SubmissionSequence("run"),
            deadline=None,
        )

        assert session.calls_to("POST", "/jobs")[0]["json"]["status"] == "open"

    def test_a_closed_create_names_its_lifecycle_and_carries_the_tasks(self):
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed")))

        submit_tasks(
            make_client(session), _build_tasks([1, 2], premium=False), sequence=SubmissionSequence("run"), deadline=None
        )

        body = session.calls_to("POST", "/jobs")[0]["json"]
        assert body["status"] == "closed"
        assert len(body["tasks"]) == 2

    def test_the_timing_constants_hold_the_values_the_design_depends_on(self):
        assert MAX_TASKS_PER_SUBMISSION == 1000
        assert MIN_WAIT_CAP_MINUTES == 5
        # settle's cap must leave room inside the cleanup allowance for the stop.
        assert SETTLE_CAP_SECONDS < STOP_CLEANUP_SECONDS

    def test_the_shipped_defaults_of_the_two_budget_flags_are_mutually_valid(self):
        """The two budget defaults must satisfy each other's constraints.

        Narrower than it looks: a genuinely flagless run also has no team id and no
        tier, and is *supposed* to fail on both.
        """
        assert DEFAULT_WAIT_CAP_MINUTES >= MIN_WAIT_CAP_MINUTES
        assert DEFAULT_CLUB_RESERVE_MINUTES >= MIN_CLUB_RESERVE_MINUTES
        assert DEFAULT_CLUB_RESERVE_MINUTES < DEFAULT_WAIT_CAP_MINUTES
        assert (
            _validate_run_args(
                _args(
                    wait_cap_minutes=DEFAULT_WAIT_CAP_MINUTES,
                    club_reserve_minutes=DEFAULT_CLUB_RESERVE_MINUTES,
                )
            )
            == []
        )

    def test_a_genuinely_flagless_run_is_rejected_on_the_two_required_inputs(self):
        errors = _validate_run_args(_args(team_id=[], premium_proxy=None, dry_run=False))
        assert any("--team-id" in error for error in errors)
        assert any("--premium-proxy" in error for error in errors)

    def test_the_key_namespace_cannot_repeat_across_runs(self):
        """One namespace per process is the point — two sequences in a run share it.
        What must not repeat is the namespace itself: a fixed one would replay key
        :0 against a different body on the next dispatch, drawing the one 409 whose
        only recovery is finding the job by hand."""
        assert re.fullmatch(r".+_[0-9a-f]{6}", BATCH_RUN_ID), BATCH_RUN_ID
        assert BATCH_RUN_ID.startswith(RUN_TS)
        assert SubmissionSequence().next_key() == f"{BATCH_RUN_ID}:0"


def _real_run_argv(tier):
    return ["--team-id", "126693", "--premium-proxy", tier, "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]


class TestVendorContract:
    def test_add_tasks_sends_no_idempotency_key(self):
        """The vendor declares that header on job creation and rerun only, so a key
        here would promise a dedupe the endpoint does not perform."""
        session = _open_lifecycle_session()

        submit_tasks(
            make_client(session),
            _build_tasks(range(MAX_TASKS_PER_SUBMISSION + 1), premium=False),
            sequence=SubmissionSequence("run"),
            deadline=None,
        )

        for call in session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/tasks"):
            assert "Idempotency-Key" not in call["headers"]

    @pytest.mark.parametrize(
        "outcome",
        [requests.exceptions.Timeout("read timed out"), requests.exceptions.ConnectionError("reset"), None],
    )
    def test_an_unreadable_add_tasks_outcome_is_never_replayed(self, outcome):
        """A replay would append the chunk a second time and bill every task in it
        twice, because nothing on this endpoint deduplicates."""
        session = FakeSession()
        session.route("POST", "/jobs/j/tasks", outcome or FakeResponse(500, {"m": "boom"}))

        with pytest.raises(BatchClientError):
            make_client(session).add_tasks("j", [{"url": "u"}], deadline=None)

        assert len(session.calls_to("POST", "/jobs/j/tasks")) == 1

    def test_a_failed_run_is_reported_as_a_failure_not_an_empty_sweep(self):
        session = FakeSession()
        session.route(
            "GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, fixture("run_poll_failed"))
        )
        clock = FakeClock()

        outcome = poll_until_terminal(make_client(session, clock), _job(), deadline=clock.now() + 600)

        assert outcome.error and "insufficient_credits" in outcome.error
        assert outcome.is_clean is False

    def test_a_failed_run_makes_the_command_exit_non_zero(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.replace(
            "GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", FakeResponse(200, fixture("run_poll_failed"))
        )

        exit_code = main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 1
        assert "insufficient_credits" in out

    def test_a_timed_out_run_exits_non_zero_on_the_timeout_alone(self, monkeypatch, capsys):
        """A workflow reads the exit code, not the banner, so a force-stopped
        partial sweep must not pass for a clean one.

        The run settles cleanly after the stop and every body downloads, so nothing
        sets an error — the timeout is the only thing making this non-zero.
        """
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        state = {"stopped": False}

        def get_run(method, url, body):
            template = "run_poll_completed" if state["stopped"] else "run_poll_running"
            return FakeResponse(200, fixture(template))

        def stop(method, url, body):
            state["stopped"] = True
            return FakeResponse(200, fixture("run_poll_completed"))

        session.replace("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", get_run)
        session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", stop)

        exit_code = main(
            ["--team-id", "1", "--premium-proxy", "false", "--wait-cap-minutes", "10", "--club-reserve-minutes", "5"],
            client=make_client(session, FakeClock()),
        )
        out = flat_output(capsys)

        assert exit_code == 1
        assert "did not finish inside its budget" in out
        assert "Failure:" not in out
        assert "credits spent: 3" in out

    def test_a_task_that_never_ran_is_not_counted_as_a_failure(self, monkeypatch, capsys):
        """A stopped run leaves pending tasks. Reporting them as scrape failures
        reads as 'we were blocked' when the truth is 'raise the budget'."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()

        main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert "126696: never started" in out
        assert "never started: 1" in out
        assert "tasks without a body: 1" in out

    def test_a_relative_content_url_is_resolved_and_authenticated(self):
        """result_url comes in two documented forms and they need opposite
        treatment: the presigned one must not carry the credential, this one cannot
        be fetched without it."""
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r/tasks/t/content", FakeResponse(200, text="[]"))

        make_client(session).fetch_body("/v1/jobs/j/runs/r/tasks/t/content")

        call = session.calls[-1]
        assert call["url"] == "https://async.api.zenrows.com/v1/jobs/j/runs/r/tasks/t/content"
        assert call["headers"]["X-API-Key"] == API_KEY

    def test_a_presigned_url_is_still_fetched_without_the_credential(self):
        url = "https://zenrows-results.s3.amazonaws.invalid/r/1"
        session = FakeSession()
        session.route("GET", url, FakeResponse(200, text="[]"))

        make_client(session).fetch_body(url + "?X-Amz-Expires=86400")

        assert "X-API-Key" not in session.calls[-1]["headers"]

    @pytest.mark.parametrize(
        "bad,why",
        [
            ("12 6694", "a space is not a digit"),
            ("abc-1_2", "letters pass a charset check then crash the URL builder"),
            ("126693.9", "a fractional id would silently scrape team 126693 instead"),
            ("126693\n", "a trailing newline slips past a $-anchored pattern"),
            ("", "empty is not an id"),
        ],
    )
    def test_a_team_id_the_url_builder_cannot_use_is_refused_before_submitting(self, bad, why):
        errors = _validate_run_args(_args(team_id=["126693", bad]))
        assert any("not a usable GotSport team id" in error for error in errors), why

    def test_the_two_usable_team_id_forms_are_accepted(self):
        assert _validate_run_args(_args(team_id=["126693", "126693.0"])) == []

    def test_a_fractional_id_would_have_scraped_a_different_team(self):
        """The scraper's own int(float(...)) absorbs .9 silently; this refuses it."""
        assert _normalized_team_id("126693.0") == 126693
        with pytest.raises(BatchClientError):
            _normalized_team_id("126693.9")


class TestCancellation:
    def test_an_interrupt_after_submission_stops_the_run_before_exiting(self, monkeypatch, capsys):
        """Unwinding without a stop would leave the job billing every task it had
        not yet reached."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.replace(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results",
            KeyboardInterrupt(),
        )
        session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(200, fixture("run_poll_completed")))

        exit_code = main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 130
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop")) == 1
        assert "credits spent" in out

    def test_a_create_that_names_a_job_carries_it_out_even_without_a_run_id(self):
        """The job exists and is billing; reporting "no job existed" while naming it
        in the same message is the worst of both."""
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, {"job_id": "job_REAL", "status": "closed"}))

        with pytest.raises(BatchClientError) as excinfo:
            submit_tasks(
                make_client(session), _build_tasks([1], premium=False), sequence=SubmissionSequence("run"), deadline=None
            )

        assert excinfo.value.job is not None
        assert excinfo.value.job.job_id == "job_REAL"

    def test_the_job_ids_reach_the_operator(self):
        """These are what makes a killed run recoverable inside the retention
        window, so they must actually be emitted."""
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed")))
        from rich.console import Console

        import scripts.batch_drain_queue as module

        recorded = []
        original = module.console
        module.console = Console(file=_Recorder(recorded), soft_wrap=True)
        try:
            submit_tasks(
                make_client(session), _build_tasks([1], premium=False), sequence=SubmissionSequence("run"), deadline=None
            )
        finally:
            module.console = original

        printed = " ".join("".join(recorded).split())
        assert "job_id=job_01SYNTHETICCLOSED" in printed
        assert "run_id=run_01SYNTHETICCLOSED" in printed


class _Recorder:
    def __init__(self, sink):
        self._sink = sink

    def write(self, text):
        self._sink.append(text)

    def flush(self):
        return None


class TestJsonEscapedRedaction:
    def test_a_key_that_json_escapes_differently_is_still_redacted(self):
        """An encoder between the secret and the sink defeats an exact-substring
        redactor. json.dumps is the one that actually runs, on a payload echoed
        back in a create failure."""
        # The key must sit *inside* a longer string. When it is the whole JSON value
        # its escaped form is bounded by the surrounding quotes, so redacting the
        # quoted and unquoted forms both match and the two implementations coincide.
        key = 'ab"cd' + "e" * 35
        session = FakeSession()
        session.route(
            "POST", "/jobs", FakeResponse(200, {"echoed": f"rejected {key} at the gateway", "status": "closed"})
        )
        client = ZenRowsBatchClient(key, session=session)

        with pytest.raises(BatchClientError) as excinfo:
            submit_tasks(client, _build_tasks([1], premium=False), sequence=SubmissionSequence("run"), deadline=None)

        message = str(excinfo.value)
        assert key not in message
        assert 'ab\\"cd' not in message
        assert "REDACTED" in message

    def test_an_interrupt_mid_download_stops_the_run_and_still_reports(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.replace(
            "GET", "https://zenrows-results.s3.amazonaws.invalid/r/126693", KeyboardInterrupt()
        )
        session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(200, fixture("run_poll_completed")))

        exit_code = main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 130
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop")) == 1
        assert "credits spent" in out


class TestRedirectHandling:
    """`requests` strips only `Authorization` when a redirect changes host, so a
    custom auth header would ride a hop from the Batch API to storage. Each hop is
    authorised on its own origin instead."""

    def test_the_credential_does_not_follow_a_redirect_off_the_batch_api(self):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/j/runs/r/tasks/t/content",
            FakeResponse(302, headers={"Location": "https://storage.example.invalid/blob"}),
        )
        session.route("GET", "https://storage.example.invalid/blob", FakeResponse(200, text="[]"))

        make_client(session).fetch_body("/v1/jobs/j/runs/r/tasks/t/content")

        first, second = session.calls[0], session.calls[1]
        assert first["headers"]["X-API-Key"] == API_KEY
        assert "X-API-Key" not in second["headers"]
        assert second["url"] == "https://storage.example.invalid/blob"

    def test_a_redirect_that_stays_on_the_batch_api_keeps_the_credential(self):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/j/runs/r/tasks/t/content",
            FakeResponse(307, headers={"Location": "/v1/jobs/j/runs/r/tasks/t/content2"}),
        )
        session.route("GET", "/jobs/j/runs/r/tasks/t/content2", FakeResponse(200, text="[]"))

        make_client(session).fetch_body("/v1/jobs/j/runs/r/tasks/t/content")

        assert session.calls[1]["headers"]["X-API-Key"] == API_KEY

    def test_a_redirect_loop_is_bounded(self):
        session = FakeSession()
        session.route(
            "GET",
            "/jobs/j/runs/r/tasks/t/content",
            FakeResponse(302, headers={"Location": "/v1/jobs/j/runs/r/tasks/t/content"}),
        )

        with pytest.raises(BodyFetchError, match="redirected"):
            make_client(session).fetch_body("/v1/jobs/j/runs/r/tasks/t/content")

    @pytest.mark.parametrize(
        "hostile",
        [
            "https://async.api.zenrows.com.evil.invalid/v1/jobs/j/x",
            "//evil.invalid/v1/jobs/j/x",
            "https://evil.invalid/v1/jobs/j/x",
        ],
    )
    def test_a_host_that_merely_resembles_the_batch_api_gets_no_credential(self, hostile):
        session = FakeSession()
        session.route("GET", hostile.split("?", 1)[0], FakeResponse(200, text="[]"))

        make_client(session).fetch_body(hostile)

        assert "X-API-Key" not in session.calls[-1]["headers"]

    @pytest.mark.parametrize(
        "equivalent",
        [
            "https://ASYNC.API.ZENROWS.COM/v1/jobs/j/runs/r/tasks/t/content",
            "https://async.api.zenrows.com:443/v1/jobs/j/runs/r/tasks/t/content",
        ],
    )
    def test_an_equivalent_batch_origin_still_gets_the_credential(self, equivalent):
        """Comparing origins rather than string prefixes: these are the same host by
        any reading, and a prefix test would withhold the key and 401 every body."""
        session = FakeSession()
        # Routed by the literal URL: these variants are the same origin but not the
        # same string, which is the whole point of the parametrization.
        session.route("GET", equivalent, FakeResponse(200, text="[]"))

        make_client(session).fetch_body(equivalent)

        assert session.calls[-1]["headers"]["X-API-Key"] == API_KEY

    def test_an_absolute_batch_api_url_still_gets_the_credential(self):
        """The vendor may return the content endpoint absolute rather than relative."""
        url = "https://async.api.zenrows.com/v1/jobs/j/runs/r/tasks/t/content"
        session = FakeSession()
        session.route("GET", "/jobs/j/runs/r/tasks/t/content", FakeResponse(200, text="[]"))

        make_client(session).fetch_body(url)

        assert session.calls[-1]["headers"]["X-API-Key"] == API_KEY


class TestCleanupCoversEveryPhase:
    @pytest.mark.parametrize("interrupt_at", ["submit", "poll", "download"])
    def test_an_interrupt_in_any_phase_stops_the_run(self, interrupt_at, monkeypatch, capsys):
        """A workflow cancellation arrives as SIGINT and the poll is where a run
        spends nearly all its time, so guarding only the download left the likeliest
        phase able to abandon a billing job."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(200, fixture("run_poll_completed")))

        if interrupt_at == "submit":
            # The create succeeds and the close is interrupted, so a job exists.
            session.replace("POST", "/jobs", FakeResponse(200, fixture("create_open")))
            session.route("POST", "/jobs/job_01SYNTHETICOPEN/tasks", KeyboardInterrupt())
            session.route("POST", "/jobs/job_01SYNTHETICOPEN/stop", FakeResponse(200, fixture("run_poll_completed")))
        elif interrupt_at == "poll":
            session.replace("GET", "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED", KeyboardInterrupt())
        else:
            session.replace("GET", "https://zenrows-results.s3.amazonaws.invalid/r/126693", KeyboardInterrupt())

        team_ids = ["1"] if interrupt_at != "submit" else [str(i) for i in range(MAX_TASKS_PER_SUBMISSION + 1)]
        argv = ["--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]
        for team_id in team_ids:
            argv = ["--team-id", team_id] + argv

        exit_code = main(argv, client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 130
        stops = session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/stop") + session.calls_to(
            "POST", "/jobs/job_01SYNTHETICCLOSED/stop"
        )
        assert len(stops) == 1, f"interrupt during {interrupt_at} left the run unstopped"
        assert "credits spent" in out

    def test_an_interrupt_before_a_job_exists_needs_no_stop(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = FakeSession()
        session.route("POST", "/jobs", KeyboardInterrupt())

        assert main(_real_run_argv("false"), client=make_client(session, FakeClock())) == 130
        capsys.readouterr()

    def test_a_failure_after_the_create_is_stopped_and_reported_through_main(self, monkeypatch, capsys):
        """The handler that joins "the exception carries the job" to "stop it"."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_open")))
        session.route("POST", "/jobs/job_01SYNTHETICOPEN/tasks", FakeResponse(400, {"message": "bad chunk"}))
        session.route("POST", "/jobs/job_01SYNTHETICOPEN/stop", FakeResponse(200, fixture("run_poll_completed")))
        session.route(
            "GET", "/jobs/job_01SYNTHETICOPEN/runs/run_01SYNTHETICOPEN", FakeResponse(200, fixture("run_poll_completed"))
        )

        argv = ["--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]
        for team_id in range(MAX_TASKS_PER_SUBMISSION + 1):
            argv = ["--team-id", str(team_id)] + argv

        exit_code = main(argv, client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 1
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICOPEN/stop")) == 1
        assert "job_id=job_01SYNTHETICOPEN" in out
        assert "credits spent" in out

    def test_a_job_that_accepted_nothing_is_still_stopped(self, monkeypatch, capsys):
        """A job that accepted nothing still exists and still bills, so it must be
        stopped and named — not reported as "no job existed"."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_closed") | {"accepted_tasks": 0}))
        session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(200, fixture("run_poll_completed")))
        session.route(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_completed")),
        )

        exit_code = main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 1
        assert len(session.calls_to("POST", "/jobs/job_01SYNTHETICCLOSED/stop")) == 1
        assert "before a job existed" not in out


class TestTaskStatusDispatch:
    def test_an_unrecognized_task_status_is_named_rather_than_counted_as_a_failure(
        self, monkeypatch, capsys, caplog
    ):
        """An unrecognized task status is named, not counted as a scrape failure."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.replace(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results",
            FakeResponse(200, {"results": [{"external_id": "9", "status": "quarantined"}], "next_cursor": None}),
        )

        with caplog.at_level(logging.WARNING, logger="scripts.batch_drain_queue"):
            main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert "unrecognized: 1" in out
        assert "tasks without a body: 0" in out
        assert any("Unrecognized task status" in record.getMessage() for record in caplog.records)

    def test_a_processing_task_is_not_reported_as_never_started(self, monkeypatch, capsys):
        """`pending` never began; `processing` was dispatched and may still bill.
        Collapsing them gives an operator the wrong retry and cost picture."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.replace(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED/results",
            FakeResponse(
                200,
                {
                    "results": [
                        {"external_id": "8", "status": "pending", "result_url": ""},
                        {"external_id": "9", "status": "processing", "result_url": ""},
                    ],
                    "next_cursor": None,
                },
            ),
        )

        main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert "never started: 1" in out
        assert "still running: 1" in out

    @pytest.mark.parametrize("status", [409, 429])
    def test_an_add_tasks_rejection_that_means_not_accepted_is_retried(self, status):
        session = FakeSession()
        session.route(
            "POST",
            "/jobs/j/tasks",
            FakeResponse(status, {"message": "not taken"}),
            FakeResponse(200, {"job_id": "j", "accepted_tasks": 3}),
        )

        payload = make_client(session).add_tasks("j", [], deadline=None)

        assert payload["accepted_tasks"] == 3
        assert len(session.calls_to("POST", "/jobs/j/tasks")) == 2

    def test_a_non_retried_add_tasks_failure_names_the_status_and_sends_once(self):
        """An operator reasoning about whether a chunk could have been duplicated
        needs to know it was sent once. Reporting the configured retry maximum sent
        them looking for two attempts that never happened."""
        session = FakeSession()
        session.route("POST", "/jobs/j/tasks", FakeResponse(500, {"message": "boom"}))

        with pytest.raises(BatchClientError, match="status 500"):
            make_client(session).add_tasks("j", [], deadline=None)

        assert len(session.calls_to("POST", "/jobs/j/tasks")) == 1

    def test_an_exhausted_retry_budget_reports_the_attempts_it_made(self):
        session = FakeSession()
        session.route("POST", "/jobs", requests.exceptions.ConnectionError("reset"))

        with pytest.raises(BatchClientError) as excinfo:
            make_client(session).create_job_closed([], key_supplier=_supplier(SubmissionSequence("run")), deadline=None)

        made = len(session.calls_to("POST", "/jobs"))
        assert f"{made} attempt(s)" in str(excinfo.value)
        assert made == DEFAULT_REQUEST_ATTEMPTS

    def test_a_run_payload_with_no_stats_reads_as_unknown_progress(self):
        assert _run_progress({"run_id": "r", "status": "running"}) == (None, None)
        assert _run_progress({"stats": None}) == (None, None)
        assert _run_progress({"stats": {"completed": "3", "total": 3}}) == (None, 3)

    def test_operator_text_redacts_as_well_as_escapes(self):
        """Both jobs are pinned: a vendor `failure_reason` carrying the key must be
        redacted, not merely escaped."""
        assert _operator_text(f"rejected {API_KEY}", API_KEY) == "rejected REDACTED"
        # Escaping neutralises the tag rather than deleting the bracket.
        assert _operator_text("[bold]x", None) == "\[bold]x"

    def test_a_failure_reason_carrying_the_key_is_redacted_end_to_end(self, monkeypatch, capsys):
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = _happy_path_session()
        session.replace(
            "GET",
            "/jobs/job_01SYNTHETICCLOSED/runs/run_01SYNTHETICCLOSED",
            FakeResponse(200, fixture("run_poll_failed") | {"failure_reason": f"auth rejected for {API_KEY}"}),
        )
        session.route("POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(200, fixture("run_poll_completed")))

        main(_real_run_argv("false"), client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert API_KEY not in out
        assert "REDACTED" in out


class TestJobHandlePublication:
    """The caller must hold the freshest handle at every moment a failure can land.

    Both cases below passed before the fixes: the job existed, the run was billing,
    and cleanup had nothing to stop or stale counts to settle on.
    """

    @pytest.mark.parametrize("lifecycle", ["closed", "open"])
    def test_the_handle_reaches_the_caller_before_anything_that_can_fail(self, lifecycle, monkeypatch, capsys):
        """`_log_job_ids` writes to stdout. A broken pipe or an interrupt there would
        otherwise unwind past the callback and leave the caller with no job.

        Both lifecycles publish the handle in their own branch, so both are driven.
        """
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        if lifecycle == "open":
            session = _open_lifecycle_session()
            session.route("POST", "/jobs/job_01SYNTHETICOPEN/stop", FakeResponse(200, fixture("run_poll_completed")))
            session.route(
                "GET",
                "/jobs/job_01SYNTHETICOPEN/runs/run_01SYNTHETICOPEN",
                FakeResponse(200, fixture("run_poll_completed")),
            )
            argv = ["--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]
            for team_id in range(MAX_TASKS_PER_SUBMISSION + 1):
                argv = ["--team-id", str(team_id)] + argv
            stop_path = "/jobs/job_01SYNTHETICOPEN/stop"
        else:
            session = _happy_path_session()
            session.route(
                "POST", "/jobs/job_01SYNTHETICCLOSED/stop", FakeResponse(200, fixture("run_poll_completed"))
            )
            argv = _real_run_argv("false")
            stop_path = "/jobs/job_01SYNTHETICCLOSED/stop"

        import scripts.batch_drain_queue as module

        original = module._log_job_ids

        def exploding_log(job, api_key=None):
            raise KeyboardInterrupt("interrupted while printing the ids")

        monkeypatch.setattr(module, "_log_job_ids", exploding_log)
        try:
            exit_code = main(argv, client=make_client(session, FakeClock()))
        finally:
            monkeypatch.setattr(module, "_log_job_ids", original)
        capsys.readouterr()

        assert exit_code == 130
        assert len(session.calls_to("POST", stop_path)) == 1

    def test_a_failure_mid_submission_settles_on_the_counts_it_actually_reached(self, monkeypatch, capsys):
        """An open job's counts advance chunk by chunk, so the handle the callback
        first saw is 0/0. Settling on that reads accepted >= submitted and would
        report a final spend while an unacknowledged chunk is still ingesting."""
        monkeypatch.setenv("ZENROWS_API_KEY", API_KEY)
        session = FakeSession()
        session.route("POST", "/jobs", FakeResponse(200, fixture("create_open")))
        session.route(
            "POST",
            "/jobs/job_01SYNTHETICOPEN/tasks",
            FakeResponse(200, {"job_id": "job_01SYNTHETICOPEN", "accepted_tasks": 1000}),
            FakeResponse(500, {"message": "ambiguous"}),
        )
        session.route("POST", "/jobs/job_01SYNTHETICOPEN/stop", FakeResponse(200, fixture("run_poll_completed")))
        stopped_short = fixture("run_poll_completed")
        stopped_short["status"] = "stopped"
        stopped_short["stats"] = {**stopped_short["stats"], "total": 1001, "completed": 400}
        session.route(
            "GET", "/jobs/job_01SYNTHETICOPEN/runs/run_01SYNTHETICOPEN", FakeResponse(200, stopped_short)
        )

        argv = ["--premium-proxy", "false", "--wait-cap-minutes", "30", "--club-reserve-minutes", "5"]
        for team_id in range(MAX_TASKS_PER_SUBMISSION + 1):
            argv = ["--team-id", str(team_id)] + argv

        exit_code = main(argv, client=make_client(session, FakeClock()))
        out = flat_output(capsys)

        assert exit_code == 1
        # 1001 submitted against 1000 acknowledged: the count is not trustworthy, so
        # the figure stays a lower bound however settled the run looks.
        assert "lower bound" in out
