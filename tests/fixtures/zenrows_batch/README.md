# ZenRows Batch API — contract fixtures

Backs `tests/unit/test_batch_drain_queue.py`, which drives
`scripts/batch_drain_queue.py` against a fake session so no test spends credits.

## Provenance — read this before trusting a green suite

**No file here is a live capture.** Every one is built from the vendor's published
OpenAPI schema (`ZenRows/zenrows-python-sdk`, `docs/openapi.yaml`), which is a much
stronger source than the prose docs but is still not the running service. A
schema-built fixture pins that our parsing matches the published contract; it
cannot prove the deployed API matches its own schema, and it cannot catch a change
ZenRows makes after this date. A fixture written from the prose docs is worse than
none: it goes green while encoding a shape the API never sends.

Replace a fixture with a live capture the first time the script runs against the
real API, and update its Source cell.

| File | What it is | Source |
|------|------------|--------|
| `create_closed.json` | `POST /jobs` with `status: closed`, tasks inline. `SubmitJobResponse`: `job_id`, `status`, `accepted_tasks` and a nested `latest_run`. All four are required by the schema. | openapi 2026-09-03 |
| `create_open.json` | `POST /jobs` with `status: open`. Same envelope; `accepted_tasks` is 0 because an open create carries no tasks yet. | openapi 2026-09-03 |
| `add_tasks.json` | `POST /jobs/{id}/tasks`. Its `accepted_tasks` counts **that submission**, not the job total. | openapi 2026-09-03 |
| `close.json` | `POST /jobs/{id}/close`. `last_batch_received` flips true here. | openapi 2026-09-03 |
| `create_409_idempotency_conflict.json` | The conflict a reused `Idempotency-Key` draws when the body differs. The Problem envelope names **no** job, so the client fails the submission rather than acting on a job it cannot identify. | openapi 2026-09-03 |
| `close_409_already_closed.json` | Closing an already-closed job. Success for our purposes. | openapi 2026-09-03 |
| `run_poll_running.json` | `GET /jobs/{id}/runs/{run_id}` mid-run — a bare `Run`, non-terminal status, `stats.completed` short of `stats.total`. | openapi 2026-09-03 |
| `run_poll_completed.json` | The same call once terminal. `stats.spend.credits` is the credit count; `stats.completed >= stats.total` is settlement's fast exit. | openapi 2026-09-03 |
| `run_poll_failed.json` | A run auto-failed on an account-level fault, carrying `failure_reason`. | openapi 2026-09-03 |
| `results_page_1.json` | First results page, carrying `next_cursor`. Both entries succeeded and have a presigned `result_url`, whose `X-Amz-Expires=7200` is the value seen from the live service — the schema says 24 hours, and the shorter figure is the one to plan against. | openapi 2026-09-03 |
| `results_page_2.json` | Last page, `next_cursor` null. Holds the failed-task shape (empty `result_url`, populated `error`) and a **pending** row, which is what a stopped run leaves behind. | openapi 2026-09-03 |
| `stop_409_run_not_stoppable.json` | `POST /jobs/{id}/stop` against an already-terminal run. Treated as "already terminal", not a failure. | openapi 2026-09-03 |
| `result_body_matches.json` | A trimmed GotSport match-list body as it arrives from a presigned link. Two matches, the scraped team on each side once. | trimmed from the live GotSport shape |

## Traps this contract sets

**The poll response is a run, the create response is a job.** `GET .../runs/{run_id}`
answers with `status` and `stats` at the root; a create nests the same run under
`latest_run`. Reading the wrong one means a finished run is never recognised and the
client polls until its budget runs out.

**`stats.spend` is an object, not a number.** It carries an integer `credits` and a
currency `cost`. Printing it whole reports a dict where an operator expects a count.

**`type` is `html` even when the body is JSON**, and the body must be parsed from
bytes rather than decoded text — it arrives as `text/html` with no charset, which
`requests` decodes as ISO-8859-1, silently mangling every non-ASCII name.

**Settlement is the run's counter, not a row count.** A task row exists from
creation and carries a `pending` status, so counting rows counts work that has not
happened. `completed` is `successful + failed`, so `completed >= total` settles a
run that finished on its own but never arrives for a stopped one, whose pending
tasks are left as-is — there settlement waits for `completed` to stop advancing.

**`result_url` has two forms.** A presigned link, which must not carry the
credential, or a `/v1/jobs/.../content` path on the Batch API, which cannot be
fetched without it. Only the presigned form has a fixture; the content path is
covered by routed unit tests.

**`result_url` and `error` are exclusive in the two terminal states only.** A
failed task has an empty `result_url` and a populated `error`; a successful one
has the reverse; a pending one has neither. So outcome is read from `status`,
never inferred from an empty `result_url`. The run-level rollup never says which
task failed.

## The status vocabulary these pin

`RunStatus` is exactly `running`, `pending`, `completed`, `stopped`, `failed`,
`deleted` — the first two active, the rest terminal. `TaskStatus` is `pending`,
`processing`, `successful`, `failed`, the first two non-terminal. A value outside
either set is logged and counted separately rather than guessed at, so a
vocabulary change shows up in the log instead of silently burning a budget or
reading as a scrape failure. The fixtures carry only the values an ordinary run
produces — `stopped`, `deleted` and `processing` have none.
