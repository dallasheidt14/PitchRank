#!/usr/bin/env python3
"""
Bulk-scrape GotSport through the ZenRows Batch API.

The synchronous proxy fetches one URL per request, so a large sweep is bounded by
round-trip latency and cannot finish inside one workflow. The Batch API takes the
whole URL list at once and fans out on ZenRows' own infrastructure.

Covers the fetching layer: submit a list of teams, wait for the run inside a
wall-clock budget, download the result bodies and report what the run cost. Queue
selection, club resolution, parsing and import live elsewhere.

The proxy tier is a required choice, not a default. The datacenter tier bills a
tenth of what the residential tier does but is unproven at volume, and an
unlabelled run would silently pick one, so --premium-proxy has no default.

Usage:
    # Preview the submission plan; issues no request and needs no API key.
    python scripts/batch_drain_queue.py --team-id 126693 --premium-proxy false --dry-run

    # Spends credits. Needs ZENROWS_API_KEY.
    python scripts/batch_drain_queue.py --team-id 126693 --team-id 126694 \
        --premium-proxy false --wait-cap-minutes 30 --club-reserve-minutes 5
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

import requests
import truststore
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from rich.console import Console
from rich.markup import escape

truststore.inject_into_ssl()

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.scrapers._http import backoff_for_event  # noqa: E402
from src.scrapers._zenrows import _redact  # noqa: E402

# Soft wrapping keeps job ids, run ids, idempotency keys and URLs on one line. A
# workflow log is 80 columns wide, and those values are what an operator copies
# out of it to recover a run.
console = Console(soft_wrap=True)

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BATCH_API_BASE = "https://async.api.zenrows.com/v1"
GOTSPORT_API_BASE = "https://system.gotsport.com/api/v1"

# The vendor OpenAPI sets maxItems 1000 on both SubmitJobRequest.tasks and
# AddTasksRequest.tasks. Its prose documentation claims 10,000; the schema governs.
MAX_TASKS_PER_SUBMISSION = 1000

RETRIABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# A result body should need at most one hop, from the Batch API's content
# endpoint to storage. The bound is what stops a redirect loop.
MAX_RESULT_REDIRECTS = 5

DEFAULT_PORTS = {"https": 443, "http": 80}

# The vendor's RunStatus enum in full. Splitting it here rather than testing only
# for the terminal set lets an unrecognized status be reported instead of polled
# to the deadline in silence.
TERMINAL_RUN_STATUSES = frozenset({"completed", "stopped", "failed", "deleted"})
ACTIVE_RUN_STATUSES = frozenset({"running", "pending"})

# A task row exists from creation, so a listing includes work that never ran. These
# are the two states that mean exactly that.
NON_TERMINAL_TASK_STATUSES = frozenset({"pending", "processing"})
TERMINAL_TASK_STATUSES = frozenset({"successful", "failed"})

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_DELAY_SECONDS = 2.0
DEFAULT_REQUEST_ATTEMPTS = 3
POLL_SECONDS = 15

# settle's own cap sits inside the terminal-cleanup allowance, so the stop call
# and its 409 re-fetch keep whatever the two constants differ by.
SETTLE_CAP_SECONDS = 180
STOP_CLEANUP_SECONDS = 240

# The vendor documents one retriable cause for an add-tasks 409: ingestion of a
# large first submission still in progress.
ADD_TASKS_CONFLICT_ATTEMPTS = 3

ADD_TASKS_RETRIABLE_STATUSES = frozenset({409, 429})

DEFAULT_WAIT_CAP_MINUTES = 120
MIN_WAIT_CAP_MINUTES = 5
DEFAULT_CLUB_RESERVE_MINUTES = 20

# The terminal stop-and-settle is carved out of the front of the club reserve, so a
# reserve shorter than that allowance leaves nothing to download results with: a
# timed-out run would pay for every task and collect none of them.
MIN_CLUB_RESERVE_MINUTES = 5

# The scraper's first-scrape baseline. This path has no last_scraped_at to derive
# a cutoff from.
DEFAULT_SINCE_DATE = date(2025, 10, 17)

BODY_EXCERPT_CHARS = 500

# A GotSport team id: digits, optionally ".0". Numeric is a strict subset of the
# vendor's external_id alphabet. Two silent failures this closes: `126693.9`
# normalizes through float() to 126693 and scrapes the wrong team, and a trailing
# newline that a `$` anchor admits fails the whole 1,000-task chunk at the vendor.
# Matched with fullmatch, never search.
TEAM_ID_PATTERN = re.compile(r"[0-9]{1,64}(\.0+)?")

# The vendor schema lists both keys under ScraperParams and rejects an unknown one
# with 400 invalid_argument, so a typo fails the submission rather than silently
# billing the other tier.
PREMIUM_PROXY_PARAMS = {"premium_proxy": "true", "proxy_country": "us"}
DATACENTER_PROXY_PARAMS: dict[str, str] = {}

RUN_TS = datetime.now(timezone.utc).isoformat()
BATCH_RUN_ID = f"{RUN_TS}_{uuid.uuid4().hex[:6]}"


class BatchRunError(Exception):
    """Base for every failure that can leave a job running on ZenRows.

    Carrying the job is the invariant: a run that has been created keeps executing
    and billing while this process unwinds, so any path that can fail after a
    create must hand the handle back for the caller to stop.
    """

    def __init__(self, message: str, job: Optional["BatchJob"] = None):
        super().__init__(message)
        self.job = job


class BatchClientError(BatchRunError):
    """An unrecoverable Batch API outcome. Its message is always key-redacted."""


class BodyFetchError(BatchClientError):
    """One task's result body could not be downloaded. Counted per task, not fatal."""


class BudgetExpired(BatchRunError):
    """A wall-clock deadline passed.

    A sibling of BatchClientError rather than a subclass: the poll loop reports an
    expiry as a timeout and a protocol failure as an abort, so every handler that
    treats them differently needs them to stay distinguishable.
    """


@dataclasses.dataclass(frozen=True)
class BatchJob:
    job_id: str
    run_id: str
    lifecycle: str
    submitted_tasks: int
    accepted_tasks: int


TERMINATION_COMPLETE = "complete"
TERMINATION_TIMED_OUT = "timed_out"
TERMINATION_ABORTED = "aborted"


@dataclasses.dataclass(frozen=True)
class RunOutcome:
    """How a run ended, and what it cost.

    ``termination`` is one state rather than a pair of booleans because the exit
    code is derived from it: two independent flags let a caller read one and miss
    the other.
    """

    job: BatchJob
    spend: int | None
    spend_is_lower_bound: bool
    termination: str = TERMINATION_COMPLETE
    error: Optional[str] = None
    stop_confirmed: bool = True

    @property
    def is_clean(self) -> bool:
        return self.termination == TERMINATION_COMPLETE and self.error is None


class SubmissionSequence:
    """Allocates the idempotency keys for every physical submission a process makes.

    The counter spans both jobs a run creates. A per-call counter restarting at 0
    would replay the first key against a different body, and the only recovery from
    that conflict is finding the job by hand in the ZenRows dashboard.

    ``key_namespace`` is this process's own prefix and is unrelated to a ZenRows
    ``run_id``; feeding the vendor's id in here would make keys per-job rather than
    per-process, which is the replay this class exists to prevent.
    """

    def __init__(self, key_namespace: str = BATCH_RUN_ID):
        self._key_namespace = key_namespace
        self._n = 0
        self._current: Optional[str] = None

    def next_key(self) -> str:
        key = f"{self._key_namespace}:{self._n}"
        self._n += 1
        self._current = key
        return key

    def retry_same(self) -> str:
        if self._current is None:
            return self.next_key()
        return self._current

    def retry_fresh(self) -> str:
        return self.next_key()


def _key_supplier(sequence: SubmissionSequence) -> Callable[[Optional[str]], str]:
    """Map a retry reason to the key that attempt should carry.

    Only an explicit 503 gets a fresh key. On a timeout, a connection error or a
    429/500/502/504 the server may already hold the submission, and a fresh key
    would orphan a second billing job.
    """

    def key_supplier(reason: Optional[str]) -> str:
        if reason is None:
            return sequence.next_key()
        if reason == "explicit_503":
            return sequence.retry_fresh()
        return sequence.retry_same()

    return key_supplier


class RunBudget:
    """The whole-run ZenRows wall clock, with a carve-out pass 1 may not consume."""

    def __init__(self, wait_cap_minutes: int, club_reserve_minutes: int):
        self.wait_cap_minutes = wait_cap_minutes
        self.club_reserve_minutes = club_reserve_minutes
        self._deadline: Optional[float] = None

    def start(self, time_source: Callable[[], float]) -> None:
        """Arm the deadlines against the clock that will be checked against them.

        The budget is built before the client exists, so it has no clock of its
        own to default to. Two clocks make every comparison meaningless: the
        offset between them is whatever the machine's uptime happens to be.
        """
        self._deadline = time_source() + self.wait_cap_minutes * 60

    @property
    def deadline(self) -> float:
        if self._deadline is None:
            raise RuntimeError("RunBudget.start() must be called before reading its deadline")
        return self._deadline

    @property
    def pass1_deadline(self) -> float:
        return self.deadline - self.club_reserve_minutes * 60


def _operator_text(value: Any, api_key: Optional[str] = None) -> str:
    """Redact, then escape Rich markup, for text printed to the console.

    Rich reads square brackets as tags, so unescaped vendor text can silently
    delete itself from the log or raise from inside the handler that was reporting
    the original failure; and text that skips redaction can publish the credential
    into a public repository's logs.
    """
    return escape(_redact(str(value), api_key) or "")


def _validated_api_key(api_key: str) -> str:
    """Reject a credential that cannot travel in a header, before it is ever sent.

    Whitespace in a key defeats redaction. ``requests`` passes a trailing newline
    through, and ``http.client`` then raises a bare ``ValueError`` quoting the
    value — not a ``RequestException``, so it misses the scrub path; a carriage
    return is quoted via ``repr()``, where the escaping stops the exact-substring
    redactor matching. Refusing the value costs a clear configuration error.
    """
    if not api_key:
        raise BatchClientError("ZENROWS_API_KEY is empty")
    if api_key.strip() != api_key or any(character.isspace() for character in api_key):
        raise BatchClientError(
            "ZENROWS_API_KEY contains whitespace; strip it in the environment or .env "
            "(the value is not shown here because it would land in the log)"
        )
    return api_key


class ZenRowsBatchClient:
    """The HTTP surface of the ZenRows Batch API.

    This client owns retry outright and mounts a zero-budget urllib3 Retry, the
    same one a bare session carries. urllib3 leaves its connection-error branch
    ungated by ``allowed_methods``, so a non-zero transport-level mount would
    replay a POST in a layer that knows nothing about the idempotency key rule,
    and would double-retry every GET against both layers.
    """

    def __init__(
        self,
        api_key: str,
        *,
        session: Optional[requests.Session] = None,
        base_url: str = BATCH_API_BASE,
        timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
        attempts: int = DEFAULT_REQUEST_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        time_source: Callable[[], float] = time.monotonic,
    ):
        self.api_key = _validated_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.attempts = attempts
        self._sleep = sleep
        self._now = time_source
        self.session = session if session is not None else self._build_session()
        self._last_idempotency_key: Optional[str] = None

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=0)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _headers(self, idempotency_key: Optional[str] = None) -> dict[str, str]:
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _scrub(self, text: Any) -> str:
        """Redact the key in both the form it is held and the form JSON writes it.

        The redactor replaces an exact substring, so any encoder between the secret
        and the sink defeats it. ``json.dumps`` is the one that actually runs here,
        on a payload echoed back in a failure message.
        """
        scrubbed = _redact(str(text), self.api_key) or ""
        encoded = json.dumps(self.api_key)[1:-1]
        if encoded != self.api_key:
            scrubbed = _redact(scrubbed, encoded) or ""
        return scrubbed

    def _excerpt(self, text: Any) -> str:
        """Redact *then* truncate. Slicing first would leave a key straddling the
        cut as a live, unmatchable fragment."""
        return self._scrub(text)[:BODY_EXCERPT_CHARS]

    def _body_excerpt(self, response: requests.Response) -> str:
        return self._excerpt(response.text)

    def _fail(self, message: str, job: Optional[BatchJob] = None) -> None:
        raise BatchClientError(self._scrub(message), job)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        key_supplier: Optional[Callable[[Optional[str]], str]] = None,
        deadline: Optional[float] = None,
        retry_ambiguous: bool = True,
    ) -> requests.Response:
        """Issue one Batch API call, retrying transport failures and 5xx/429.

        Returns the response for any status it does not retry; each caller maps
        statuses itself. Raises only on an exhausted retry budget, a transport
        failure that never produced a response, or an expired deadline.

        ``retry_ambiguous=False`` is for an endpoint with no dedupe guarantee,
        where an outcome we cannot read is not safe to replay: the request may
        have been accepted, and repeating it would duplicate the work and the bill.

        The deadline bounds when an attempt may *start*, not how long one may run:
        ``requests`` measures socket inactivity, so a server trickling bytes can
        outlast the value passed as ``timeout``. Overshoot is bounded in practice
        because every payload here is small.
        """
        url = f"{self.base_url}{path}"
        reason: Optional[str] = None
        last_detail = "no attempt was made"

        for attempt in range(self.attempts):
            remaining: Optional[float] = None
            if deadline is not None:
                remaining = deadline - self._now()
                if remaining <= 0:
                    raise BudgetExpired(f"budget expired before {method} {path}")

            key = key_supplier(reason) if key_supplier is not None else None
            self._last_idempotency_key = key
            timeout = self.timeout if remaining is None else min(self.timeout, remaining)

            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(key),
                    json=json_body,
                    timeout=timeout,
                )
            except requests.exceptions.RequestException as exc:
                event: dict[str, Any] = {"kind": "timeout", "exc": exc}
                reason = "unknown"
                last_detail = f"{type(exc).__name__}: {exc}"
            else:
                # Retriability is decided by status membership, never by the backoff
                # value: backoff_for_event returns 0.0 for a 503 carrying
                # Retry-After: 0 exactly as it does for a 409 and a 200.
                if response.status_code not in RETRIABLE_STATUSES:
                    return response
                event = {"kind": "response", "response": response}
                reason = "explicit_503" if response.status_code == 503 else "unknown"
                last_detail = f"status {response.status_code}"

            if not retry_ambiguous:
                # The caller owns replay for this endpoint, so hand back what
                # happened rather than deciding for it. A transport failure has no
                # response to hand back and still raises below.
                if "response" in event:
                    return event["response"]
                break
            if attempt >= self.attempts - 1:
                break

            wait = backoff_for_event(event, attempt, self.retry_delay)
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - self._now()))
            logger.warning(
                self._scrub(
                    f"zenrows_batch retry: attempt={attempt + 1}/{self.attempts} reason={last_detail} "
                    f"{method} {path} sleep={wait:.2f}s"
                )
            )
            self._sleep(wait)

        made = attempt + 1
        self._fail(f"{method} {path} failed after {made} attempt(s) ({last_detail})")

    def _json_2xx(self, response: requests.Response, what: str) -> Any:
        if not 200 <= response.status_code < 300:
            self._fail(f"{what}: unexpected status {response.status_code}: {self._body_excerpt(response)}")
        try:
            return response.json()
        except ValueError:
            self._fail(f"{what}: response body was not JSON: {self._body_excerpt(response)}")

    def _submit(
        self,
        path: str,
        payload: Any,
        *,
        key_supplier: Callable[[Optional[str]], str],
        deadline: Optional[float],
        what: str,
    ) -> dict:
        """POST a keyed submission.

        A 409 is always a failure here, never a job to adopt. The vendor's model has
        no state in which one means "your earlier submission succeeded, here it is":
        a genuine replay of the same body returns the original 2xx, and both
        documented causes of the conflict — a key reused with a different body, or a
        key burned by an attempt that failed — leave this submission with no job. The
        error envelope is a Problem document, which defines no job id, so reading one
        out of it and stopping it would act on a job this process does not own.
        """
        response = self._request("POST", path, json_body=payload, key_supplier=key_supplier, deadline=deadline)
        if 200 <= response.status_code < 300:
            return self._json_2xx(response, what)
        if response.status_code == 409:
            self._fail(
                f"{what}: 409 idempotency conflict on key {self._last_idempotency_key}. The API cannot look a job "
                f"up by key, so if one was created it must be found in the ZenRows dashboard. "
                f"body={self._body_excerpt(response)}"
            )
        self._fail(f"{what}: unexpected status {response.status_code}: {self._body_excerpt(response)}")

    def create_job_closed(
        self,
        tasks: list[dict],
        *,
        key_supplier: Callable[[Optional[str]], str],
        deadline: Optional[float],
    ) -> dict:
        payload = {"status": "closed", "tasks": tasks}
        return self._submit("/jobs", payload, key_supplier=key_supplier, deadline=deadline, what="create job")

    def create_job_open(
        self,
        *,
        key_supplier: Callable[[Optional[str]], str],
        deadline: Optional[float],
    ) -> dict:
        payload = {"status": "open"}
        return self._submit("/jobs", payload, key_supplier=key_supplier, deadline=deadline, what="create open job")

    def add_tasks(self, job_id: str, tasks: list[dict], *, deadline: Optional[float]) -> dict:
        """Append one chunk to an open job.

        Sends no Idempotency-Key and never replays an unreadable outcome. The
        vendor declares that header on job creation and rerun only, so this
        endpoint has no dedupe guarantee: a retry after a lost response appends the
        chunk a second time and bills every task in it twice. A 409 and a 429 are
        the exceptions and are retried, because both mean the chunk was *not*
        accepted: the documented cause of the conflict is ingestion still in
        progress, and a rate limit rejects before processing. Everything else —
        a 5xx, a timeout, a reset — leaves the outcome unknown and is sent once.
        """
        response = None
        for attempt in range(ADD_TASKS_CONFLICT_ATTEMPTS):
            response = self._request(
                "POST",
                f"/jobs/{job_id}/tasks",
                json_body={"tasks": tasks},
                deadline=deadline,
                retry_ambiguous=False,
            )
            if 200 <= response.status_code < 300:
                return self._json_2xx(response, "add tasks")
            if response.status_code not in ADD_TASKS_RETRIABLE_STATUSES or attempt == ADD_TASKS_CONFLICT_ATTEMPTS - 1:
                break
            wait = self.retry_delay
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - self._now()))
            logger.warning("add tasks: %s from job %s, retrying in %.1fs", response.status_code, job_id, wait)
            self._sleep(wait)
        self._fail(f"add tasks: unexpected status {response.status_code}: {self._body_excerpt(response)}")

    def close_job(self, job_id: str, *, deadline: Optional[float]) -> None:
        response = self._request("POST", f"/jobs/{job_id}/close", deadline=deadline)
        if 200 <= response.status_code < 300 or response.status_code == 409:
            return
        self._fail(f"close job: unexpected status {response.status_code}: {self._body_excerpt(response)}")

    def get_run(self, job_id: str, run_id: str, *, deadline: Optional[float] = None) -> dict:
        response = self._request("GET", f"/jobs/{job_id}/runs/{run_id}", deadline=deadline)
        return self._json_2xx(response, "get run")

    def iter_results(self, job_id: str, run_id: str, *, deadline: Optional[float] = None) -> Iterator[dict]:
        cursor: Optional[str] = None
        while True:
            path = f"/jobs/{job_id}/runs/{run_id}/results"
            if cursor:
                path = f"{path}?{urllib.parse.urlencode({'cursor': cursor})}"
            body = self._json_2xx(self._request("GET", path, deadline=deadline), "get results")
            for entry in body.get("results") or []:
                yield entry
            next_cursor = body.get("next_cursor")
            if not next_cursor or next_cursor == cursor:
                return
            cursor = next_cursor

    def _resolve_result_url(self, result_url: str) -> tuple[str, dict[str, str]]:
        """Absolute URL plus the headers it should carry.

        A result_url comes in two documented forms needing opposite treatment: a
        presigned link must not receive the credential, and a Batch-API content path
        cannot be fetched without it. The decision is made on the parsed origin
        rather than on a string prefix, so a host that merely starts with ours
        (``async.api.zenrows.com.example.test``) is treated as the third party it is.
        """
        if result_url.startswith("/") and not result_url.startswith("//"):
            origin = self.base_url.rsplit("/v1", 1)[0]
            return f"{origin}{result_url}", {"X-API-Key": self.api_key}
        if _same_origin(result_url, self.base_url):
            return result_url, {"X-API-Key": self.api_key}
        return result_url, {}

    def _get_following_redirects(self, result_url: str, *, timeout: float) -> requests.Response:
        """GET a result body, re-deciding the credential at every hop.

        ``requests`` follows redirects itself and strips only ``Authorization``
        when the host changes, so a custom ``X-API-Key`` would ride a 302 from the
        Batch API's content endpoint to whatever storage host it names. Following
        the chain here means each hop is authorised on its own origin.
        """
        current = result_url
        for _ in range(MAX_RESULT_REDIRECTS):
            url, headers = self._resolve_result_url(current)
            response = self.session.get(url, headers=headers or None, timeout=timeout, allow_redirects=False)
            if response.status_code not in REDIRECT_STATUSES:
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            current = urllib.parse.urljoin(url, location)
        raise BodyFetchError(self._scrub(f"result body redirected more than {MAX_RESULT_REDIRECTS} times"))

    def fetch_body(self, result_url: str, *, deadline: Optional[float] = None) -> Any:
        """Download one task's result body.

        A failed download raises BodyFetchError, which the caller counts against
        that one task rather than ending the run — the links observed from the live
        service expire in 7200s, exactly the default wait cap, so on a full-length
        run the earliest ones can go stale before their bodies are read. One dead
        link must not end a run that has already paid for every fetch.
        """
        detail = "no attempt was made"
        for attempt in range(2):
            remaining: Optional[float] = None
            if deadline is not None:
                remaining = deadline - self._now()
                if remaining <= 0:
                    raise BudgetExpired(f"budget expired before fetching {self._scrub(result_url)}")
            timeout = self.timeout if remaining is None else min(self.timeout, remaining)
            try:
                response = self._get_following_redirects(result_url, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                detail = f"{type(exc).__name__}: {exc}"
            else:
                if 200 <= response.status_code < 300:
                    try:
                        # Parse the bytes, not response.text. These bodies are JSON
                        # served as text/html with no charset, and requests decodes
                        # that as ISO-8859-1 per RFC 2616 — which parses without
                        # error and silently mojibakes every non-ASCII team name.
                        # json.loads detects the real encoding from the bytes.
                        return json.loads(response.content)
                    except ValueError as exc:
                        raise BodyFetchError(self._scrub(f"result body was not JSON: {exc}")) from exc
                detail = f"status {response.status_code}"
            if attempt == 0:
                self._sleep(self.retry_delay)
        raise BodyFetchError(self._scrub(f"result body download failed: {detail}"))

    def stop_run(self, job: BatchJob, *, deadline: Optional[float]) -> dict:
        response = self._request("POST", f"/jobs/{job.job_id}/stop", deadline=deadline)
        if 200 <= response.status_code < 300:
            return self._json_2xx(response, "stop run")
        if response.status_code == 409:
            # The vendor documents exactly one meaning here — the latest run is not
            # in a stoppable state — and never enumerates the `code` values, so the
            # run's own status is the discriminator.
            if job.run_id:
                return self.get_run(job.job_id, job.run_id, deadline=deadline)
            return {}
        self._fail(f"stop run: unexpected status {response.status_code}: {self._body_excerpt(response)}")

    def settle(
        self,
        job: BatchJob,
        *,
        deadline: Optional[float],
        cap_seconds: float = SETTLE_CAP_SECONDS,
    ) -> tuple[int | None, bool]:
        """Wait for the run's dispatched work to drain, then snapshot what it cost.

        Tasks already dispatched keep running after a stop, so a spend read straight
        afterwards is short. What settles is **stabilisation**, not completion: the
        vendor leaves a stopped run's pending tasks as-is — never re-queued, never
        failed — and defines ``completed`` as ``successful + failed``, so on the
        stopped path ``completed`` provably never reaches ``total``. Waiting for it
        would burn the whole cap on every abort and report a lower bound each time.
        Once ``completed`` stops advancing, the in-flight work has drained and the
        figure is final; ``completed >= total`` remains the fast exit for a run that
        finished on its own.

        The counter is only trustworthy when every chunk was acknowledged. An
        add-tasks response lost in transit may still have been accepted, so
        ``total`` itself can grow — while that is outstanding the figure stays a
        lower bound however stable it looks.

        A failure to read the run does not raise: settle returns the last figure it
        read, flagged as a lower bound.
        """
        if not job.run_id:
            return None, True

        counts_acknowledged = job.accepted_tasks >= job.submitted_tasks
        settle_deadline = self._now() + cap_seconds
        if deadline is not None:
            # Stop waiting a request's worth of time early, so the snapshot this
            # method exists to take still fits inside the allowance.
            settle_deadline = min(settle_deadline, deadline - self.timeout)

        run: Optional[dict] = None
        previous_completed: Optional[int] = None
        spend_is_lower_bound = True
        while True:
            try:
                run = self.get_run(job.job_id, job.run_id, deadline=deadline)
            except BatchRunError as exc:
                logger.warning(self._scrub(f"settle could not read job {job.job_id}: {exc}"))
                break
            completed, total = _run_progress(run)
            if counts_acknowledged and completed is not None:
                if total is not None and completed >= total:
                    spend_is_lower_bound = False
                    break
                # Stabilisation only counts once the run itself is terminal. While it
                # is still executing, two equal reads fifteen seconds apart mean the
                # work is slow, not that it has drained.
                if completed == previous_completed and _run_status(run) in TERMINAL_RUN_STATUSES:
                    spend_is_lower_bound = False
                    break
            previous_completed = completed
            remaining = settle_deadline - self._now()
            if remaining <= 0:
                break
            self._sleep(min(POLL_SECONDS, remaining))

        return (_spend_credits(run) if run else None), spend_is_lower_bound


def _same_origin(candidate: str, reference: str) -> bool:
    """Whether two URLs share a scheme, host and effective port."""
    left, right = urllib.parse.urlsplit(candidate), urllib.parse.urlsplit(reference)
    if not left.scheme or not left.hostname:
        return False

    def origin(parts: urllib.parse.SplitResult) -> tuple[str, str, Optional[int]]:
        scheme = parts.scheme.lower()
        # An explicit :443 on https names the same origin as no port at all, and
        # withholding the credential from that form would 401 every body.
        port = parts.port if parts.port is not None else DEFAULT_PORTS.get(scheme)
        return scheme, (parts.hostname or "").lower(), port

    return origin(left) == origin(right)


def _normalized_team_id(value: Any) -> int:
    """The integer GotSport id for ``value``, or a BatchClientError naming why not.

    The scraper writes this as ``int(float(str(id)))`` to absorb a stored "126693.0".
    Reproducing that verbatim would also absorb "126693.9" into a different team, so
    the fractional part is admitted only when it is zero.
    """
    text = str(value)
    if not TEAM_ID_PATTERN.fullmatch(text):
        raise BatchClientError(f"{text!r} is not a usable GotSport team id; expected digits, optionally followed by .0")
    return int(text.split(".", 1)[0])


def _run_status(run: dict) -> str:
    """The status of a *run* payload, which is what the poll endpoint returns.

    Pass a run, never a job. A create response carries a root ``status`` too, but
    that one describes the job — ``open`` or ``closed`` — and nothing here can tell
    the two apart, so a job handed in returns a value that is in neither status
    set. A caller holding a job passes ``payload["latest_run"]``.
    """
    return str(run.get("status") or "").lower()


def _run_progress(run: dict) -> tuple[Optional[int], Optional[int]]:
    """``(completed, total)`` from a run's stats, or ``(None, None)``.

    Both are required fields, and the vendor states ``total`` is correct from the
    first response, which is what makes this a usable completion predicate.
    """
    stats = run.get("stats")
    if not isinstance(stats, dict):
        return None, None
    completed, total = stats.get("completed"), stats.get("total")
    return (
        completed if isinstance(completed, int) else None,
        total if isinstance(total, int) else None,
    )


def _spend_credits(run: dict) -> Optional[int]:
    """Credits charged for a run.

    ``stats.spend`` is an object carrying an integer ``credits`` and a currency
    ``cost``; printing the object whole would report a dict where an operator
    expects a number.
    """
    stats = run.get("stats")
    if not isinstance(stats, dict):
        return None
    spend = stats.get("spend")
    if isinstance(spend, dict):
        credits = spend.get("credits")
        return credits if isinstance(credits, int) else None
    return spend if isinstance(spend, int) else None


def _chunked(values: Iterable[Any], size: int) -> Iterator[list]:
    batch: list = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _match_list_url(provider_team_id: Any, since_date: date) -> str:
    """The team's match-list endpoint, mirroring the scraper's own construction.

    The path segment takes the normalized integer ("126693.0" -> 126693); a raw id
    builds a URL that answers 404, which reads downstream as a team with no games.
    """
    normalized = _normalized_team_id(provider_team_id)
    since = since_date.strftime("%Y-%m-%d")
    query = urllib.parse.urlencode({"since_date": since, "from_date": since})
    return f"{GOTSPORT_API_BASE}/teams/{normalized}/matches?{query}"


def _build_tasks(
    provider_team_ids: Iterable[Any],
    *,
    premium: bool,
    since_date: date = DEFAULT_SINCE_DATE,
) -> list[dict]:
    proxy_params = PREMIUM_PROXY_PARAMS if premium else DATACENTER_PROXY_PARAMS
    return [
        {
            "url": _match_list_url(team_id, since_date),
            "external_id": str(team_id),
            "zenrows_params": dict(proxy_params),
        }
        for team_id in provider_team_ids
    ]


def _plan_submissions(tasks: list[dict]) -> tuple[str, list[list[dict]]]:
    """The lifecycle and task chunks for a submission. Pure, and the only chunker —
    a second one would let the preview disagree with a run."""
    lifecycle = "closed" if len(tasks) <= MAX_TASKS_PER_SUBMISSION else "open"
    return lifecycle, list(_chunked(tasks, MAX_TASKS_PER_SUBMISSION))


def _keyed_submissions(lifecycle: str, chunks: list[list[dict]]) -> list[tuple[str, int, bool]]:
    """The keyed and unkeyed task submissions a plan produces, in order, as
    (kind, task count, keyed). The separate close call is not listed.

    Only job creation is keyed: the vendor declares Idempotency-Key on create and
    rerun alone, so an add-tasks chunk carries none and must never be replayed.
    """
    if lifecycle == "closed":
        return [("create", len(chunk), True) for chunk in chunks]
    return [("create", 0, True)] + [("add_tasks", len(chunk), False) for chunk in chunks]


def _cleanup_deadline(time_source: Callable[[], float]) -> float:
    """The allowance for a terminal stop and settle, which outlives the run budget.

    The abort path reaches cleanup precisely because the run deadline has passed,
    so threading that through would make the first request raise instead of
    stopping the run.
    """
    return time_source() + STOP_CLEANUP_SECONDS


def _job_ids(client: ZenRowsBatchClient, payload: dict, lifecycle: str, what: str) -> tuple[str, str]:
    """The job and run ids from a create response.

    A response naming a job but no run still yields a partial handle: a stop needs
    only the job id.
    """
    job_id = payload.get("job_id")
    latest_run = payload.get("latest_run")
    run_id = latest_run.get("run_id") if isinstance(latest_run, dict) else None
    if not job_id or not run_id:
        excerpt = client._excerpt(json.dumps(payload))
        partial = (
            BatchJob(job_id=job_id, run_id="", lifecycle=lifecycle, submitted_tasks=0, accepted_tasks=0)
            if job_id
            else None
        )
        client._fail(f"{what}: response carries no job_id/latest_run.run_id: {excerpt}", partial)
    return job_id, run_id


def submit_tasks(
    client: ZenRowsBatchClient,
    tasks: list[dict],
    *,
    sequence: SubmissionSequence,
    deadline: float,
    on_job: Optional[Callable[[BatchJob], None]] = None,
) -> BatchJob:
    """Create the job and hand it every task, returning the handle to poll.

    The deadline is passed rather than derived, so a caller can hold pass 1 to the
    budget's pass-1 boundary and keep it out of the club reserve.

    ``on_job`` fires the instant the handle exists, before any output that could
    itself fail. Returning it would be too late:
    an interrupt during an open job's add-tasks or close unwinds before the
    assignment at the call site.
    """
    if not tasks:
        client._fail("submit_tasks was given no tasks; there is nothing to create a job for")

    lifecycle, chunks = _plan_submissions(tasks)
    key_supplier = _key_supplier(sequence)
    job: Optional[BatchJob] = None

    try:
        if lifecycle == "closed":
            payload = client.create_job_closed(chunks[0], key_supplier=key_supplier, deadline=deadline)
            job_id, run_id = _job_ids(client, payload, lifecycle, "create job")
            counted = payload.get("accepted_tasks")
            job = BatchJob(
                job_id=job_id,
                run_id=run_id,
                lifecycle=lifecycle,
                submitted_tasks=len(tasks),
                # Trust what was submitted when the count is absent. Defaulting to
                # zero would trip the "accepted no tasks" guard and abort every run,
                # after the billing job existed.
                accepted_tasks=int(counted) if counted is not None else len(tasks),
            )
            if on_job is not None:
                on_job(job)
            _log_job_ids(job, client.api_key)
        else:
            payload = client.create_job_open(key_supplier=key_supplier, deadline=deadline)
            job_id, run_id = _job_ids(client, payload, lifecycle, "create open job")
            job = BatchJob(
                job_id=job_id,
                run_id=run_id,
                lifecycle=lifecycle,
                submitted_tasks=0,
                accepted_tasks=0,
            )
            if on_job is not None:
                on_job(job)
            _log_job_ids(job, client.api_key)
            for chunk in chunks:
                # Count the chunk as submitted before the call, not after. An
                # add-tasks response lost to a timeout may still have been accepted,
                # and leaving both counts equal would let settle treat the total as
                # trustworthy and call the run settled before that chunk finishes.
                job = dataclasses.replace(job, submitted_tasks=job.submitted_tasks + len(chunk))
                response = client.add_tasks(job_id, chunk, deadline=deadline)
                counted = response.get("accepted_tasks")
                job = dataclasses.replace(
                    job,
                    accepted_tasks=job.accepted_tasks + (int(counted) if counted is not None else len(chunk)),
                )
            client.close_job(job_id, deadline=deadline)

        if job.accepted_tasks <= 0:
            # Inside the try on purpose: the guard's failure must carry the handle out.
            client._fail(f"job {job.job_id} accepted no tasks; nothing would settle", job)
    except BatchRunError as exc:
        # A failure that already carries a partial handle keeps it.
        exc.job = exc.job or job
        raise

    return job


def _log_job_ids(job: BatchJob, api_key: Optional[str] = None) -> None:
    """Emit the ids while the run is still alive; they are what makes a killed run
    recoverable inside the vendor's result retention."""
    job_id = _operator_text(job.job_id, api_key)
    run_id = _operator_text(job.run_id, api_key)
    console.print(f"  job_id={job_id}  run_id={run_id}  lifecycle={job.lifecycle}")
    logger.info("zenrows_batch job_id=%s run_id=%s lifecycle=%s", job.job_id, job.run_id, job.lifecycle)


def poll_until_terminal(client: ZenRowsBatchClient, job: BatchJob, *, deadline: float) -> RunOutcome:
    """Poll the run to a terminal status, or stop and settle it at the deadline.

    Nothing escapes: an expiry, a rejected poll and an exhausted retry budget all
    stop the run and come back as a RunOutcome. Transient 5xx are routine over a
    long poll, and one raised on its way out would leave the run billing.
    """
    warned_statuses: set[str] = set()
    while True:
        if client._now() >= deadline:
            return _stop_and_settle(client, job, termination=TERMINATION_TIMED_OUT)

        try:
            run = client.get_run(job.job_id, job.run_id, deadline=deadline)
        except BudgetExpired:
            # Running out of budget mid-poll is the same operational outcome as
            # reaching the deadline at the top of the loop, and the last poll's
            # timeout is clamped to whatever is left — so this is the ordinary way
            # a full-length run ends, not a failure.
            return _stop_and_settle(client, job, termination=TERMINATION_TIMED_OUT)
        except BatchClientError as exc:
            return _stop_and_settle(client, job, termination=TERMINATION_ABORTED, error=str(exc))

        status = _run_status(run)
        if status in TERMINAL_RUN_STATUSES:
            # A run that ended short — stopped from the dashboard, or failed — can
            # still have dispatched tasks finishing and billing, so its spend is
            # only final once the counter says every task is accounted for.
            completed, total = _run_progress(run)
            finished = completed is not None and total is not None and completed >= total
            return RunOutcome(
                job=job,
                spend=_spend_credits(run),
                spend_is_lower_bound=not finished,
                error=_terminal_run_error(status, run),
            )
        if status not in ACTIVE_RUN_STATUSES and status not in warned_statuses:
            # Name it once. Without this an operator watching a run burn its whole
            # budget has no way to learn which status the loop failed to recognise.
            warned_statuses.add(status)
            logger.warning("Unrecognized run status %r; polling on until the deadline", status)

        remaining = deadline - client._now()
        client._sleep(max(0.0, min(POLL_SECONDS, remaining)))


def _terminal_run_error(status: str, run: dict) -> Optional[str]:
    """Why a terminal run is not a successful one, or None when it completed.

    ``failed`` is an account-level fault — the vendor names running out of credits
    and an inactive subscription — so a run that ends that way has to reach the
    operator as a failure rather than as an empty but successful sweep.
    """
    if status == "completed":
        return None
    if status == "failed":
        return f"ZenRows failed the run: {run.get('failure_reason') or 'no reason given'}"
    return f"ZenRows reported the run {status}"


def _stop_and_settle(
    client: ZenRowsBatchClient,
    job: BatchJob,
    *,
    termination: str,
    error: Optional[str] = None,
) -> RunOutcome:
    """Stop the run and take its final spend snapshot. Best effort throughout.

    A failed stop must not skip the snapshot, and neither failure may replace the
    outcome with an exception: this runs on the paths that most need to report what
    a run cost.
    """
    cleanup = _cleanup_deadline(client._now)
    stop_confirmed = False
    try:
        client.stop_run(job, deadline=cleanup)
        stop_confirmed = True
    except Exception as exc:  # noqa: BLE001 - cleanup must never replace the outcome
        logger.warning(client._scrub(f"Could not stop job {job.job_id}: {exc}"))
        # Keep the reason that brought us here; a failed stop is a consequence, and
        # the operator learns of it from stop_confirmed rather than by losing the
        # original cause.
        error = error or str(exc)

    try:
        spend, spend_is_lower_bound = client.settle(job, deadline=cleanup)
    except Exception as exc:  # noqa: BLE001 - same reason
        logger.warning(client._scrub(f"Could not settle job {job.job_id}: {exc}"))
        spend, spend_is_lower_bound = None, True

    return RunOutcome(
        job=job,
        spend=spend,
        spend_is_lower_bound=spend_is_lower_bound,
        termination=termination,
        error=error,
        stop_confirmed=stop_confirmed,
    )


def _validate_run_args(args: argparse.Namespace) -> list[str]:
    """Human-readable reasons the run cannot start. An empty list means valid."""
    errors: list[str] = []

    if args.wait_cap_minutes < MIN_WAIT_CAP_MINUTES:
        errors.append(f"--wait-cap-minutes must be at least {MIN_WAIT_CAP_MINUTES}; got {args.wait_cap_minutes}")
    if args.club_reserve_minutes < MIN_CLUB_RESERVE_MINUTES:
        errors.append(
            f"--club-reserve-minutes must be at least {MIN_CLUB_RESERVE_MINUTES}; got "
            f"{args.club_reserve_minutes}. A shorter reserve is consumed entirely by stopping and "
            "settling the run, leaving nothing to download results with."
        )
    if args.club_reserve_minutes >= args.wait_cap_minutes:
        errors.append(
            f"--club-reserve-minutes ({args.club_reserve_minutes}) must be less than --wait-cap-minutes "
            f"({args.wait_cap_minutes}); otherwise the first pass has no budget at all"
        )
    if args.premium_proxy is None:
        errors.append(
            "--premium-proxy is required: the datacenter tier bills a tenth of the residential one but is "
            "unproven at volume, so the run will not guess which you meant"
        )
    for team_id in args.team_id:
        try:
            _normalized_team_id(team_id)
        except BatchClientError as exc:
            errors.append(f"--team-id {exc}")

    if not args.dry_run:
        if not args.team_id:
            errors.append("at least one --team-id is required for a real run")
        if not os.getenv("ZENROWS_API_KEY"):
            errors.append("ZENROWS_API_KEY is not set; a real run cannot reach the Batch API")

    return errors


def _print_dry_run_plan(tasks: list[dict], *, sequence: SubmissionSequence) -> int:
    lifecycle, chunks = _plan_submissions(tasks)
    submissions = _keyed_submissions(lifecycle, chunks)

    console.print("\n[bold]Dry run[/bold] [dim]— no ZenRows request will be issued[/dim]")
    console.print(f"  tasks: {len(tasks)}")
    console.print(f"  lifecycle: {lifecycle}")
    console.print(f"  submissions: {len(submissions)}")
    for index, (kind, task_count, keyed) in enumerate(submissions, 1):
        key = f"idempotency key {sequence.next_key()}" if keyed else "no idempotency key"
        console.print(f"    {index}. {kind} ({task_count} task(s)) {key}")

    for task in tasks[:5]:
        console.print(f"  external_id={task['external_id']}  url={task['url']}")
        console.print(f"    zenrows_params={task['zenrows_params']}")
    if len(tasks) > 5:
        console.print(f"  [dim]… and {len(tasks) - 5} more task(s)[/dim]")

    return 0


def run_batch(
    args: argparse.Namespace,
    *,
    premium: bool,
    sequence: SubmissionSequence,
    budget: RunBudget,
    client: Optional[ZenRowsBatchClient] = None,
) -> int:
    if client is None:
        client = ZenRowsBatchClient(os.environ["ZENROWS_API_KEY"])

    tasks = _build_tasks(args.team_id, premium=premium)
    console.print(f"\n[bold]Submitting {len(tasks)} task(s)[/bold] (premium_proxy={str(premium).lower()})")

    budget.start(client._now)
    job: Optional[BatchJob] = None
    outcome: Optional[RunOutcome] = None
    fetched = 0
    failed = 0
    pending = 0
    in_flight = 0
    unknown = 0

    def remember(created: BatchJob) -> None:
        nonlocal job

        job = created

    try:
        job = submit_tasks(client, tasks, sequence=sequence, deadline=budget.pass1_deadline, on_job=remember)
        outcome = poll_until_terminal(client, job, deadline=budget.pass1_deadline)
        # Bounded by the whole-run deadline, not pass 1's: the download tail is
        # still ZenRows' clock, and an unbounded one would outlive the workflow
        # the budget exists to fit inside.
        for entry in client.iter_results(job.job_id, job.run_id, deadline=budget.deadline):
            label = _operator_text(entry.get("external_id"), client.api_key)
            status = str(entry.get("status") or "").lower()
            if status in NON_TERMINAL_TASK_STATUSES:
                # A stopped run leaves these behind. Counting them as failures would
                # read as "GotSport blocked us" when the truth is that the budget ran
                # out — and the two are worth telling apart, because a pending task
                # never started while a processing one was dispatched and may bill.
                if status == "pending":
                    pending += 1
                    console.print(f"  {label}: never started")
                else:
                    in_flight += 1
                    console.print(f"  {label}: still running when the run ended")
                continue
            if status not in TERMINAL_TASK_STATUSES:
                # Name an unrecognized status rather than counting it as a scrape failure.
                unknown += 1
                logger.warning("Unrecognized task status %r for %s", status, entry.get("external_id"))
                console.print(f"  {label}: unrecognized status {_operator_text(status, client.api_key)}")
                continue
            result_url = entry.get("result_url")
            if not result_url:
                failed += 1
                console.print(f"  {label}: error {_operator_text(entry.get('error'), client.api_key)}")
                continue
            try:
                body = client.fetch_body(result_url, deadline=budget.deadline)
            except BodyFetchError as exc:
                failed += 1
                console.print(f"  {label}: [red]body download failed[/red] ({_operator_text(exc, client.api_key)})")
                continue
            fetched += 1
            match_count = len(body) if isinstance(body, list) else 0
            console.print(f"  {label}: {match_count} match(es)")
    except BatchRunError as exc:
        # Prefer the exception's handle: an open job's counts advance chunk by chunk,
        # and the callback only ever saw the first. A stale one would let settle read
        # accepted >= submitted and call an unacknowledged chunk settled.
        job = exc.job or job
        detail = _operator_text(exc, client.api_key)
        if job is None:
            console.print(f"[red]Submission failed before a job existed:[/red] {detail}")
            return 1
        console.print(f"[yellow]Run failed; stopping it.[/yellow] {detail}")
        _log_job_ids(job, client.api_key)
        outcome = _stop_and_settle(client, job, termination=TERMINATION_ABORTED, error=str(exc))
    except BaseException as exc:
        # An interrupt — a workflow cancellation arrives as SIGINT — can land in any
        # phase, and the poll is where a run spends nearly all its time. Unwinding
        # from there without stopping the job leaves it billing every remaining task.
        # The provisional outcome is assigned first so that a second interrupt during
        # cleanup still reports honestly rather than replaying a stale one.
        if job is not None:
            outcome = RunOutcome(
                job=job,
                spend=None,
                spend_is_lower_bound=True,
                termination=TERMINATION_ABORTED,
                error=f"cancelled ({type(exc).__name__})",
                stop_confirmed=False,
            )
            console.print("\n[yellow]Cancelled — stopping the run before exiting.[/yellow]")
            outcome = _stop_and_settle(client, job, termination=TERMINATION_ABORTED, error=outcome.error)
        raise
    finally:
        if outcome is not None:
            console.print(
                f"\n  bodies fetched: {fetched}   tasks without a body: {failed}   "
                f"never started: {pending}   still running: {in_flight}   unrecognized: {unknown}"
            )
            _report_outcome(outcome, client.api_key)

    return 0 if outcome.is_clean else 1


def _report_outcome(outcome: RunOutcome, api_key: Optional[str] = None) -> None:
    """Say how the run ended and what it cost."""
    if outcome.termination == TERMINATION_ABORTED:
        console.print("[red]Run aborted.[/red]")
    elif outcome.termination == TERMINATION_TIMED_OUT:
        console.print("[yellow]The run did not finish inside its budget.[/yellow]")
    if outcome.termination != TERMINATION_COMPLETE:
        if outcome.stop_confirmed:
            console.print("  the run was stopped.")
        else:
            console.print(
                f"  [red]the stop was not confirmed — job {_operator_text(outcome.job.job_id, api_key)} may still be "
                "running. Check the ZenRows dashboard.[/red]"
            )
    if outcome.error:
        console.print(f"[red]Failure:[/red] {_operator_text(outcome.error, api_key)}")
    spend = "unknown" if outcome.spend is None else f"{outcome.spend}"
    qualifier = " (lower bound — the run had not settled)" if outcome.spend_is_lower_bound else ""
    console.print(f"  credits spent: {spend}{qualifier}")


def main(argv: Optional[list[str]] = None, *, client: Optional[ZenRowsBatchClient] = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk-scrape GotSport through the ZenRows Batch API")
    parser.add_argument(
        "--team-id",
        action="append",
        default=[],
        help="A GotSport provider team id to scrape. Repeat for more than one.",
    )
    parser.add_argument(
        "--wait-cap-minutes",
        type=int,
        default=DEFAULT_WAIT_CAP_MINUTES,
        help=f"Whole-run ZenRows budget, minimum {MIN_WAIT_CAP_MINUTES} (default {DEFAULT_WAIT_CAP_MINUTES})",
    )
    parser.add_argument(
        "--club-reserve-minutes",
        type=int,
        default=DEFAULT_CLUB_RESERVE_MINUTES,
        help=f"Budget the first pass may not consume (default {DEFAULT_CLUB_RESERVE_MINUTES})",
    )
    parser.add_argument(
        "--premium-proxy",
        choices=("true", "false"),
        default=None,
        help="Required. Residential proxies bill ~10x the datacenter tier; there is deliberately no default.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the submission plan and issue no request")
    args = parser.parse_args(argv)

    errors = _validate_run_args(args)
    if errors:
        for error in errors:
            console.print(f"[red]ERROR: {escape(error)}[/red]")
        return 1

    premium = args.premium_proxy == "true"
    sequence = SubmissionSequence()
    budget = RunBudget(args.wait_cap_minutes, args.club_reserve_minutes)

    try:
        if args.dry_run:
            return _print_dry_run_plan(_build_tasks(args.team_id, premium=premium), sequence=sequence)
        return run_batch(args, premium=premium, sequence=sequence, budget=budget, client=client)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled by user[/yellow]")
        return 130
    except Exception as exc:
        console.print(f"\n[red]Fatal error:[/red] {_operator_text(exc, os.getenv('ZENROWS_API_KEY'))}")
        logger.exception("Fatal error in batch_drain_queue")
        return 1


if __name__ == "__main__":
    sys.exit(main())
