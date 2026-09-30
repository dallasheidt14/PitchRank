"""Tests for the queue finalize that retires a drain's claimed rows.

A row left in 'processing' is invisible to every future drain: there is no lease,
no expiry, no reaper, and claim_queue_items only ever selects 'pending'. So a
finalize that silently writes nothing costs the teams in that batch their place in
the pipeline, and the only signal is the summary line — which is why both halves of
this are guarded: that the write reaches every id, and that the summary reports what
landed rather than what was attempted.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.drain_queue import _finalize_queue_items

# postgrest-py puts an .in_() list in the URL's query component, and the hosted
# project refuses one past a few thousand characters. The exact ceiling is the
# server's, not ours; what matters is that a ceiling exists, so the double has one.
MAX_QUERY_CHARS = 4000


class _QueryTooLong(Exception):
    """Stands in for the postgrest error an unbatched id list raises."""


class _Update:
    def __init__(self, db, payload):
        self._db = db
        self._payload = payload
        self._ids = None

    def eq(self, column, value):
        assert column == "id"
        self._ids = [value]
        return self

    def in_(self, column, values):
        assert column == "id"
        self._ids = list(values)
        return self

    def execute(self):
        # Refuse what production refuses. A double that accepts any list cannot see
        # the defect the batching exists to prevent, and would pass hardest on it.
        query = "id=in.(" + ",".join(self._ids) + ")"
        if len(query) > MAX_QUERY_CHARS:
            self._db.refusals += 1
            raise _QueryTooLong("URL component 'query' too long")

        # Only rows still holding the claim are changed, so the result is a subset
        # of the filter — the same way PostgREST answers an update that matches less
        # than it was asked about.
        changed = [i for i in self._ids if i in self._db.claimed]
        for request_id in changed:
            self._db.claimed.discard(request_id)
            self._db.written[request_id] = self._payload
        return _Result([{"id": i} for i in changed])


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, db):
        self._db = db

    def update(self, payload):
        return _Update(self._db, payload)


class _Db:
    """Records at execute(), because update()/in_() build a request that does nothing."""

    def __init__(self, claimed):
        self.claimed = set(claimed)
        self.written = {}
        self.refusals = 0

    def table(self, name):
        assert name == "scrape_requests"
        return _Table(self)

    def failed_ids(self):
        return {i for i, payload in self.written.items() if payload["status"] == "failed"}


def _request_id(n):
    """A uuid-shaped id, so the double's length check sees a realistic query."""
    return f"3f961075-0f3f-4854-833d-{n:012d}"


def _errored_batch(count):
    queue_map = {f"team-{n}": _request_id(n) for n in range(count)}
    log_buffer = [{"team_id_master": team, "status": "error"} for team in queue_map]
    return queue_map, log_buffer


def _reported(capsys):
    text = capsys.readouterr().out
    match = re.search(r"Queue finalized: ([\d,]+) completed, ([\d,]+) failed", text)
    assert match, f"no finalize summary in output: {text!r}"
    return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))


def test_marks_every_failed_request_in_a_batch_too_large_for_one_url():
    """The id list is split, so a batch far past the query ceiling still all lands."""
    queue_map, log_buffer = _errored_batch(2500)
    db = _Db(queue_map.values())

    _finalize_queue_items(db, queue_map, log_buffer)

    assert db.refusals == 0
    assert db.failed_ids() == set(queue_map.values())


def test_reported_failed_count_is_what_was_written_not_what_was_attempted(capsys):
    """The summary counts rows PostgREST changed, not ids handed to it.

    A drain that reports its intended count turns a write that never landed into a
    clean-looking run, which is how stranded rows go unnoticed for days.
    """
    queue_map, log_buffer = _errored_batch(250)
    ids = list(queue_map.values())
    # Half the claims are already gone, so the update matches only the other half.
    db = _Db(ids[:125])

    _finalize_queue_items(db, queue_map, log_buffer)

    _, failed = _reported(capsys)
    assert failed == 125


def test_completed_rows_are_counted_separately_from_failed_ones(capsys):
    """A team with games logged is completed; only a logged error is failed."""
    queue_map = {"team-0": _request_id(0), "team-1": _request_id(1)}
    log_buffer = [
        {"team_id_master": "team-0", "status": "success", "games_found": 4},
        {"team_id_master": "team-1", "status": "error"},
    ]
    db = _Db(queue_map.values())

    _finalize_queue_items(db, queue_map, log_buffer)

    completed, failed = _reported(capsys)
    assert (completed, failed) == (1, 1)
    assert db.written[_request_id(0)]["status"] == "completed"
    assert db.written[_request_id(1)]["status"] == "failed"
