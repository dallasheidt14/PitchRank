---
status: ready
spec: .turbo/specs/zenrows-batch-bulk-scrape.md
---

# Plan: Batch client and run control

## Context

Everything else in this project depends on being able to hand ZenRows a list of URLs and get
bodies back. This shell builds that layer and nothing else: the HTTP surface of the ZenRows
Batch API, the rules that keep submissions legal, and the clock that stops a run before the
workflow times out.

The contract is fully verified against the live API (2026-09-03), which removes the usual
risk of building against documentation. Two details are load-bearing and contradict ZenRows'
own prose docs, so they are worth restating: submissions cap at **1,000 tasks**, not the
10,000 the marketing page claims, and an **open job starts fetching immediately** rather than
waiting for the close call — so later chunks stream in while earlier ones are already in
flight.

This shell ends with a runnable command, so the code is reachable and the contract is
provable before any database work exists.

### Expansion notes

**Baseline.** Expanded against `origin/main` @ `fe455f921`. The checkout sat 8 commits behind
at expansion time; every citation below was confirmed against source, and the drifted
commits touch only the team-state assignment surface, none of which this plan references.

**Working-tree state the implementer will meet.** The spec, this plan file, and the
`### ZenRows Batch API` section of `.claude/skills/scraper-patterns/SKILL.md` are all
uncommitted working-tree content produced by the planning sessions — the skill edit is a
modification to a tracked file, the rest are untracked. They are the planning workflow's own
artifacts, not a dirty tree to clean up. `.turbo/shells/` also loses one file during
expansion, for the same reason. The checkout is also shared with other live sessions: stage
only the files this plan names.

**Some vendor details are recorded as verified but have no captured payload behind them** —
the premium-tier parameter names, the per-task counter fields under `stats`, and the open
create's response shape. They are named as risks rather than written into steps as fact, and
each has a `_fail` or an assertion attached so it breaks loudly rather than silently. See
*Risks* at the end of Verification.

**Read the Contracts section before the steps.** It carries the one invariant round 2 added:
every value crossing between the client, the run budget, the CLI and the later shells has
exactly one named producer and one stated type, listed in a table there. Sixteen review
findings were all instances of that invariant being unstated, so a step that seems to need a
value the table does not list is a signal to add the row first, not to invent the value locally.

## Pattern Survey

Baseline for every citation below: `origin/main` @ `fe455f921` ("Buy GotSport anchors for
unconfirmed clubs…"). Every file was read via `git show origin/main:<path>` or
`git cat-file -p <blob>`, not from the working tree.

### Analogous Features

**Existing ZenRows HTTP callers — all five use the *synchronous proxy* endpoint (Q1)**

- `src/scrapers/_zenrows.py:35` — `ENDPOINT = "https://api.zenrows.com/v1/"`. Raw `requests`, GET-only `ZenRowsSession` shim. `_build_session` (`:74-88`) mounts one `HTTPAdapter(Retry(total=3, backoff_factor=0.5, status_forcelist=[500,502,503,504], allowed_methods=["GET","HEAD"]))`. Params built at `:90-104` (`apikey`, `url`, conditional `premium_proxy`/`proxy_country`/`js_render`, `original_status=true`). `timeout` defaults to 120s (`:57`). **Only caller that redacts**: `get()` at `:113-114` rewrites `resp.url` through `_redact` before returning. `premium_proxy` default from `ZENROWS_PREMIUM_PROXY` env (`:66-68`).
- `src/scrapers/gotsport.py:619-636` — `GotSportScraper._make_zenrows_request`. Hard-codes the endpoint string at `:621`, builds `{apikey, url, js_render:"false", premium_proxy, proxy_country:"us"}`, folds the caller's params into the `url` value via `urlencode` (`:629-634`), and issues `self.session.get(..., timeout=self.timeout)` — the caller cannot override the timeout. **No redaction anywhere.** Config at `:312-324` (`GOTSPORT_MAX_RETRIES` 3, `GOTSPORT_TIMEOUT` 30, `ZENROWS_API_KEY`, `ZENROWS_PREMIUM_PROXY` default true). Retry lives in the session adapter at `:362-365`; the app-level retry is a `for attempt in range(self.max_retries)` loop around the call site at `:455-461`.
- `src/scrapers/gotsport.py:1589-1605` — the **event-scrape path**'s second, separate `_make_zenrows_request` on `GotsportScraper`. Same endpoint literal at `:1597`, `premium_proxy` hard-wired `"true"` (not env-driven, unlike the team scraper), same `timeout=self.timeout` override problem — called out explicitly in the docstring at `:1615-1617`. Its config block is `:1489-1501` (different defaults: retries 2, timeout 15).
- `src/scrapers/gotsport.py:1008-1047` — module-level `_zenrows_get(session, api_key, url, *, timeout, delay_min, delay_max)`. The one shared, testable function: honours the caller's `timeout` on both branches, falls back to a direct `session.get` when `api_key` is falsy, and sleeps jitter **after** the response (`:1044-1045`). `_fetch_json_via_zenrows` (`:1607-1626`) is the class-level shim onto it.
- `scrapers/outreach_scraper/outreach_scraper/zenrows.py:22` — a deliberate third copy (`ZENROWS_ENDPOINT`), `_zenrows_params` at `:25-39`, `zenrows_url()` at `:42-44` builds a full proxied URL string for Scrapy, `make_zenrows_request()` at `:47-50` with `timeout=30`. No retry, no redaction. Module docstring (`:4-7`) records that the duplication is intentional.
- `scripts/assign_team_states.py:864-895` — `probe_associations` lazily imports `_zenrows_get` inside the function (`:864`, with a documented rationale: module-scope import drags pandas/scipy/sklearn/xgboost in), builds a bare `requests.Session()`, and calls `_zenrows_get(session, api_key, url, timeout=15, delay_min=0.1, delay_max=0.3)` at `:875` under a `ThreadPoolExecutor`. Classifies per-call outcomes into a `Counter` rather than swallowing them — the docstring at `:843-847` explains that a blocked probe must look blocked, not like "no data". Writes happen on the main thread, never in workers (`:897-900`).
- `scripts/audit_polluted_gotsport_aliases.py:130` — identical shape: `_zenrows_get(session, api_key, api_url, timeout=10, delay_min=0.1, delay_max=0.3)` wrapped in `try/except requests.RequestException`, then a status-code ladder (`:134-143`) mapping 404 → `registration_id`, non-200 → `unknown_status_{n}`, unparseable body → `unknown_non_json_body`.

**What carries over vs. what does not.** Carries over: raw `requests` (never the SDK — it is in neither `requirements.txt` nor `requirements.lock`, verified); the urllib3 `Retry` mount shape from `_zenrows.py:78-85`; the per-call status ladder and outcome-`Counter` discipline from `assign_team_states.py`; `_redact(text, secret)` at `_zenrows.py:39`. Does **not** carry over: every one of these six call sites puts the key in the **query string** (`"apikey"`), which is precisely why redaction is about `resp.url`. The Batch API uses a different host and an `X-API-Key` **header**, so the key will never land in `Response.url` — the redaction surface moves to request/response bodies, `job_id` logs, exception text, and the `Idempotency-Key`-bearing headers dict. Also: `allowed_methods=["GET","HEAD"]` in the shared Retry means **POST is not retried** by the existing adapter config, and `retry_session_get` (below) is GET-only — the Batch client's creates/adds/close/stop are all POSTs, so neither existing retry layer applies as written.

**Load-bearing negative (Q8): nothing in the repo talks to `async.api.zenrows.com`.** `git grep -n "async\.api\.zenrows" origin/main` returns zero matches across all tracked files. There is no Batch-API client, no async-job polling, no presigned-S3 body fetch anywhere. This shell is greenfield on the transport.

**Operator CLI scripts (Q2) — the house shape**

- `scripts/drain_queue.py` (925 lines) — the closest analogue by function. `sys.path.append(str(Path(__file__).parent.parent))` at `:34` *before* the `src.*` imports; `console = Console()` at `:46`; `load_dotenv()` at `:47` then `.env.local` with `override=True` at `:52`; `logging.basicConfig(...)` + `logger` at `:56-57` — it uses **both** `rich` console (operator-facing progress/summary) and `logger` (diagnostics). `main()` at `:878` builds the parser, `args = parser.parse_args()` at `:904`, then wraps the call in `try/except KeyboardInterrupt → sys.exit(130) / except Exception → sys.exit(1)` (`:906-921`), with `if __name__ == "__main__": main()` at `:924-925`. Supabase client built inline: `create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))` at `:568`. Flags: `--limit` (default 2000), `--concurrency`, `--output`, `--dry-run` (`:880-902`). Exit code `2` is reserved for the WAF abort *after* import+finalize (`:866`).
- `scripts/retire_stranded_scrape_requests.py` — the cleaner, more recent convention. `truststore.inject_into_ssl()` at `:40`, `sys.path.append` at `:42`, and dotenv loaded as **both files, `.env.local` first** (`:50-52`) with a comment explaining why. Module-level constants `PAGE_SIZE = 1000`, `UPDATE_BATCH = 100` at `:63-64`. Its `--dry-run` / `--execute` precedence is the documented rule: `dry_run = args.dry_run or not args.execute` at `:159`, with `--dry-run` explicitly winning when both are passed (`:150-158`). Validates args and `sys.exit(1)`s before touching the client (`:161-179`); requires `SUPABASE_SERVICE_ROLE_KEY` only on the write path (`:174-179`). Summary via `rich` printing, `sys.exit(1)` on partial failure (`:204-206`).
- `scripts/process_missing_games.py` — the every-15-min drainer. `sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` at `:30`; `load_dotenv()` + `.env.local` override at `:36-41`; `logging.basicConfig` at `:44`; **no `rich`** — pure logging. `main()` at `:782` with `--limit` (default 40), `--dry-run`, `--continuous`, `--interval`; exits `0`/`1` at `:842-846`.
- `scripts/assign_team_states.py:2029-2187` — the largest operator tool: ~14 `add_argument` calls, `--dry-run`/`--execute`/`--snapshot`, a long validation ladder each ending in `sys.exit(1)` (`:2107-2139`), then `create_client` at `:2141`. Its module docstring (`:25-44`) carries the usage examples, which is the convention for the bigger scripts.

**Time-budget / deadline / wait-cap patterns (Q3)**

- `scripts/pr_wait.py:193-209` — **the closest reusable pattern.** `deadline = time.monotonic() + args.timeout * 60`, then `while True:` doing the work, breaking on a settled condition, `if time.monotonic() > deadline: print(...); return 1` before `time.sleep(POLL_SECONDS)`. Returns an int that `main` turns into an exit code. This is the shape a Batch poll loop and settle-wait should mirror.
- `scripts/scrape_new_gotsport_events.py:20-35` and `scripts/scrape_upcoming_gotsport_events.py:27-37` — the *other* pattern: module-level `_start_time` / `_max_runtime_seconds` / `_timeout_triggered` globals with a `check_timeout()` predicate, driven by a `--max-runtime` int-minutes flag (`:1230`, default 150) plumbed through as `max_runtime_minutes` (`:691`). Uses wall-clock `datetime.now()` rather than `time.monotonic()`. The `9000` default carries the comment "leave 30min buffer for 3h limit" — the same reserve-below-`timeout-minutes` reasoning `wait_cap_minutes` needs.
- `src/tournaments/storage/_file_lock.py:88-95` — `deadline = time.monotonic() + timeout if timeout > 0 else None` with the `deadline is None or time.monotonic() >= deadline` guard; the idiom for "0/None means no cap".
- `src/scrapers/gotsport.py:193-256` — `WAFBreaker` uses `time.monotonic()` for `_open_until` cooldown arithmetic. `tests/unit/test_gotsport_waf_breaker.py:187` shows the test convention: **set `_open_until` directly rather than sleeping**, and `:269-271` asserts elapsed `< 0.05` for a no-wait path.

**Nothing existing carves out a *nested* reserve** (a sub-budget the first phase may not consume). `club_reserve_minutes` has no prior art here.

**JSONL writers under `data/raw/` (Q6)**

- `scripts/drain_queue.py:732` — `output_file = f"data/raw/scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}_drain.jsonl"`; `scripts/scrape_games.py:442` and `scripts/weekly/update.py:65` use the same shape without the `_drain` suffix. Directory created with `output_path.parent.mkdir(parents=True, exist_ok=True)` (`:735`), handle opened `"w"` with a `threading.Lock` (`:738-739`).
- Per-line record: `scraper._game_data_to_dict(game_data, team_id)` at `:451`, written as `output_file_handle.write(json.dumps(game) + "\n")` at `:461`. One game per line, not one team.
- Consumed by `scripts/import_games_enhanced.py:52` `stream_games_jsonl(file_path, batch_size=1000)` → `json.loads(line)` at `:59`; streaming auto-enables for `.jsonl`/`.ndjson` (`:275`, `:302`). Invoked as a `subprocess.run([sys.executable, import_script, str(output_path), provider, "--stream", "--batch-size", "1000"])` at `drain_queue.py:824-834`, with the return code checked at `:836` (and — per the spec's R27 — merely *warned* about at `:838-845`, which shell 04 diverges from).
- `.gitignore:7-8` excludes `data/*` except `data/calibration/` and `data/profiles/`, so the JSONL is workflow-artifact material, never committed. Both `.github/workflows/clear-queue.yml:115` and `scrape-games.yml:359` upload `data/raw/scraped_games_*.jsonl` as an artifact.

### Reusable Utilities

- `src/scrapers/_zenrows.py:39` — `_redact(text, secret)` — replaces `secret` with `"REDACTED"`, null-safe on both arguments. R38 names this directly; it is importable as-is and already unit-tested (`tests/unit/test_zenrows.py:46-55`).
- `src/scrapers/_zenrows.py:74-88` — `ZenRowsSession._build_session()` — the canonical `HTTPAdapter` + `Retry` mount (`total=3`, `backoff_factor=0.5`, `status_forcelist=[500,502,503,504]`). Reusable as a *template*, not as an import: `allowed_methods=["GET","HEAD"]` excludes the POSTs the Batch API needs, and the class's constructor hard-binds the sync proxy endpoint.
- `src/scrapers/_http.py:86-127` — `backoff_for_event(event, attempt, retry_delay)` — computes a wait from a `{kind: "response"|"timeout"|"short_body"}` event, honouring `Retry-After` (seconds or HTTP-date, `_parse_retry_after` at `:56`), clamped at 120s, exponential otherwise (`_exponential_backoff` at `:80`). **This is directly reusable for the Batch client's 503/retry-after handling** and is the only backoff calculator in the repo. `RateLimitedError` at `:43` is its typed exhaustion error.
- `src/scrapers/_http.py:133-151` — `retry_session_get(...)` — the app-level retry wrapper. **GET-only** (`:162`), so it covers the presigned-S3 body fetch and the poll/results GETs but not any Batch POST. `SCRAPER_DISABLE_APP_RETRY=1` bypasses it (`:129`, `:152-153`).
- `src/scrapers/gotsport.py:1008` — `_zenrows_get(session, api_key, url, *, timeout, delay_min, delay_max)` — the shared sync-proxy fetcher. Relevant as the thing the batch path **replaces**, not extends; both script-level ZenRows callers import it lazily to dodge the ML dependency chain (`assign_team_states.py:858-864` documents why), which is a pattern worth copying if `batch_drain_queue.py` needs `GotSportScraper`.
- **Chunking (Q4): there is no shared helper.** `src/utils/` contains no chunk/batch utility (full listing: `age_group, club_normalizer, club_state_registry, enhanced_validators, gotsport_team_details, merge_resolver, placeholder_clubs, team_association_map, team_name_utils, team_utils, us_states`). Every caller re-rolls it, under four different names:
  - `scripts/find_regid_duplicate_merges.py:79` — `def batched(seq, n=100)`
  - `scripts/prepare_prospective_match_predictions.py:226` and `scripts/settle_prospective_match_predictions.py:69` — `def _chunked(values: Iterable[str], size: int) -> Iterable[List[str]]`
  - `scripts/enqueue_user_interest_teams.py:80` — `def _chunks(items, size=BATCH_SIZE)`
  - `scripts/import_teams_enhanced.py:240` and `src/etl/enhanced_pipeline.py:2720` — nested/local `_chunks(lst, size)`
  - Most sites skip the helper entirely: **21 files** contain a literal `for i in range(0, len(x), 100)` for `.in_()` batching, including `scripts/drain_queue.py:211` and `:352`, `scripts/apply_vetted_team_merges.py:192`, `scripts/decide_team_merges.py:211,219`, `scripts/check_state_skill_assumptions.py:397`, `scripts/extract_and_import_tgs_teams.py:313` (with the comment "Batch to avoid URI length limits"), `src/scrapers/base.py:109`, `dashboard.py:5012,5311,5322`.
- **Run identifiers (Q5)**: the established convention is a timestamp + short uuid4 hex. `scripts/scrape_affinity_wa_tournament.py:87-88` — `SCRAPE_TS = datetime.now(timezone.utc).isoformat()` then `SCRAPE_RUN_ID = f"{SCRAPE_TS}_{uuid.uuid4().hex[:6]}"`; replicated verbatim at `scripts/scrape_playmetrics_league.py:629`, `scripts/scrape_playmetrics_tournament.py:539`, `scripts/scrape_tgs_event.py:869`. `src/etl/pipeline.py:36-39` — `_generate_build_id()` returns `f"{provider_code}_{YYYYmmdd_HHMMSS}_{uuid.uuid4().hex[:8]}"`. Both thread the id into every emitted record (e.g. `scrape_tgs_event.py:593` writes `"scrape_run_id"` into the row).
- **`Idempotency-Key`: nothing in the repo sends one.** A repo-wide grep for "idempotency" returns only SQL-migration guard language, `.turbo/` planning prose, and `frontend/app/api/stripe/webhook/route.ts:452` — which is an *upsert-is-idempotent* comment, not a header. `frontend/app/api/stripe/webhook/__tests__/route.test.ts:829` tests re-delivery de-dup by event id. There is **no header-based idempotency convention to mirror**, in TypeScript or Python; this shell establishes it.

### Convention Anchors

- **New-script placement and shape**: operator CLIs live flat in `scripts/`, one file, `main()` + `if __name__ == "__main__": main()`. Imports ordered stdlib → `sys.path.append(str(Path(__file__).resolve().parent.parent))` → third-party → `src.*`/`scripts.*` with `# noqa: E402` where ruff's `I` rule would complain (`assign_team_states.py:106-112`).
- **CI lint scope**: `.github/workflows/ci.yml:29` runs `ruff check src/ scripts/ config/ tournament_intake.py dashboard.py --output-format=github`. **`scripts/batch_drain_queue.py` is inside that path list; `tests/` is not.** `pyproject.toml:21-31` sets `line-length = 120`, `target-version = "py311"`, `select = ["E","F","W","I"]` — so import ordering is enforced.
- **CI test invocation**: `.github/workflows/ci.yml:43` — `pytest tests/ --ignore=tests/test_enhanced_pipeline.py`, after `pip install -r requirements.lock`. `pyproject.toml:9-19` sets `testpaths = ["tests"]`, `python_files = ["test_*.py"]`, `python_classes = ["Test*"]`, `addopts = "-ra --tb=short"`, `strict_markers = true` with only `slow` registered — **a new marker must be declared in `pyproject.toml` or the test errors.**
- **Test HTTP mocking (Q7): there is no HTTP-mocking library.** `requirements.txt` carries only `pytest>=9.0`, `pytest-asyncio>=0.21.0`, `pytest-cov>=4.1.0`; `requirements.lock` pins `pytest==9.0.2`, `pytest-asyncio==1.3.0`, `pytest-cov==7.0.0`. **No `responses`, no `requests-mock`, no `vcrpy`, no `freezegun`.** `tests/unit/test_zenrows.py:1-6` states the rule outright: "Pure tests only — exercise param-building and key redaction with no network, matching the repo's no-HTTP-mocking convention." The established substitutes are:
  - `unittest.mock.MagicMock(spec=requests.Response)` with `.status_code` / `.json.return_value` set — `tests/unit/test_resolve_api_team_id_from_event_page.py:31-39`, and stubbing the *method* rather than the socket (`:42-53` binds the real function onto a `MagicMock(spec=...)` so the heavyweight `__init__` never runs; its docstring at `:14-16` explains why).
  - `tests/conftest.py:25-42` — `FakeResponse(text, url)` with `.headers`, `.history`, `.status_code`, `raise_for_status()`, written because "bare `MagicMock()` does not satisfy that contract."
  - `Mock()` with a `side_effect` callable recording calls, for Supabase chains — `tests/unit/test_drain_queue_topup.py:36-55`.
  - `tests/unit/test_scrapers_http.py:15-19` — a 3-line `_response()` factory for pure backoff assertions.
- **Testing a `scripts/` module**: `tests/unit/test_drain_queue_topup.py:7-9` — `sys.path.append(...)` up three levels, then `from scripts.drain_queue import _fetch_topup_teams`. Private functions are imported directly; there is no package-export ceremony.
- **Fixture directories (Q7)**: `tests/fixtures/` **exists at `origin/main`** with three subdirectories — `tests/fixtures/gotsport/` (~50 HTML files, including `event_synthetic_*` hand-built cases), `tests/fixtures/sincsports_clubs/`, `tests/fixtures/sincsports_events/`. **Mirror `tests/fixtures/sincsports_clubs/`**: it pairs raw captures with a `README.md` table naming each file's purpose and capture date, plus a machine-readable `observations.json` sidecar that production code also reads (`scripts/discover_sincsports_teams.py:83`). Loading convention is a module-level constant: `FIXTURES = Path(__file__).parent.parent / "fixtures" / "<dir>"` (`tests/unit/test_sincsports_clubs.py:19`, `test_gotsport_tier_parser.py:30`, `tests/integration/test_gotsport_tier_persistence.py:28` uses `.resolve().parents[1]`), then `.read_text(encoding="utf-8")`. `scripts/capture_gotsport_fixtures.py:34` is the precedent for a re-runnable capture script writing into `tests/fixtures/`, and `:16-18` documents the `pytest.mark.skipif(not fixture_path.exists())` tolerance so a partial capture never reds CI.
- **Dry-run guard**: `CLAUDE.md` § Code Quality requires a `--dry-run` on any new data-mutating script. The precedence rule to follow is `retire_stranded_scrape_requests.py:159` — `dry_run = args.dry_run or not args.execute`, `--dry-run` wins when both are passed. (`drain_queue.py:898-902` uses the weaker plain-`--dry-run` form; the newer script is the better model.) The spec's R37 needs the read-only-preview variant, which `assign_team_states.py:37-44` documents as the house pattern for "the dry run is the thing that decides".
- **Supabase batching rules**: `CLAUDE.md` § Supabase Patterns — 1000-row pagination limit and ≤100 ids per `.in_()`. In force at `drain_queue.py:349-350` (with the URI-length rationale in the docstring) and `retire_stranded_scrape_requests.py:63-64` (`PAGE_SIZE = 1000`, `UPDATE_BATCH = 100`).
- **Large data files**: `.gitignore:7-8` — `data/*` ignored except `data/calibration/` and `data/profiles/`. `CLAUDE.md` § Git — "Don't commit large CSV files." Recorded Batch fixtures under `tests/fixtures/` are tracked, so keep them trimmed the way `trim_landing_to_gids` (`tests/conftest.py:44`) exists to keep the gotsport corpus small.
- **Secrets**: only `ZENROWS_API_KEY` appears in `.env.example:128`. `ZENROWS_PREMIUM_PROXY` is read by three modules but is in no template — consistent with the `GOTSPORT_DELAY_*` note in `CLAUDE.md`. Repo is public; `.env`/`.env.local` are gitignored at `:43-44`.
- **Logging duality**: `rich` `Console()` for anything an operator reads (progress, summary tables, the final counts), `logging.getLogger(__name__)` for diagnostics and swallowed-exception warnings. `drain_queue.py:46,56-57` runs both; `process_missing_games.py:44` is logging-only; `retire_stranded_scrape_requests.py:44` is `rich`-only. For an artifact-producing bulk run, `drain_queue.py`'s both-of-them shape is the fit.
- **`truststore.inject_into_ssl()`** at module top, before any client construction — used by 14 `scripts/*.py` including `retire_stranded_scrape_requests.py:40` and `assign_team_states.py`. Not used by `drain_queue.py` or `process_missing_games.py`.

### Proposed Alignment

**Blend, with one deliberate deviation.** Follow the operator-CLI shape wholesale — `retire_stranded_scrape_requests.py` for the argparse/validation/dotenv/`--dry-run`-precedence skeleton, `drain_queue.py` for the dual `rich`+`logging` output, the `data/raw/scraped_games_*.jsonl` filename and per-game `json.dumps` line, and the `subprocess.run` import hand-off; `pr_wait.py:193-209` for the `time.monotonic()` deadline loop; the `SCRAPE_TS + uuid4().hex[:6]` run-id convention; `_redact` imported directly from `_zenrows.py:39`; `backoff_for_event` from `_http.py:86` for `Retry-After`/503 waits; and the `tests/fixtures/sincsports_clubs/` layout (captures + a `README.md` table + a JSON sidecar) with the `FIXTURES = Path(__file__).parent.parent / "fixtures" / "zenrows_batch"` loader idiom and pure `MagicMock(spec=requests.Response)` stubs, since no HTTP-mocking library is available and adding one would touch `requirements.lock`.

**Deviate on the transport layer, because there is no prior art to follow.** No existing caller speaks to `async.api.zenrows.com`, none sends a header-borne key, none issues a POST through the shared retry machinery (`_zenrows.py:82` restricts retries to GET/HEAD; `_http.retry_session_get:162` is GET-only), and none sends an `Idempotency-Key`. Copying `_make_zenrows_request`'s query-string-key shape would be actively wrong here — and it would silently defeat R38, since the existing redaction only ever scrubs `Response.url`. Build the Batch client as a self-contained class in `scripts/batch_drain_queue.py`, and redact at the log/exception boundary rather than on the response object. *(Trimmed at round 2: this paragraph originally offered a choice between widening `_zenrows.py:78-85`'s `Retry` mount to POST and leaving retry app-level. Step 2 closes that choice — the client mounts no `Retry` at all — so the option is removed here rather than left to contradict the step. The paragraph's original closing clause, prescribing the `data/raw/scraped_games_*.jsonl` filename, the per-game `json.dumps` line and the `subprocess.run` import hand-off, is removed for the same reason: no Implementation Step in this plan covers any of it, and all three belong to the later shells.)*

**Roll a local `_chunked(values, size)` rather than hunting for a shared one** — there is none in `src/utils/`, and four differently-named local copies plus 21 inline `range(0, len(x), 100)` loops are the actual convention. Name it `_chunked` to match the two most recent instances (`prepare_prospective_match_predictions.py:226`, `settle_prospective_match_predictions.py:69`), and keep the 1,000-task submission cap a named module constant beside a 100-id `.in_()` constant so the two limits are never confused — `retire_stranded_scrape_requests.py:63-64` is the precedent for that pairing.

**Verified at expansion, with two corrections to the survey above.** Every citation was re-read from source. `GotSportScraper.BASE_URL` is at `src/scrapers/gotsport.py:303` and the match-list URL is built at `:431` (`api_url = f"{self.BASE_URL}/teams/{normalized_team_id}/matches"`, with `since_date` / `from_date` params at `:443-447`); note the path segment is `normalized_team_id`, computed at `:409` as `int(float(str(team_id)))`, not the raw provider id. A second identical construction sits at `:854`, which this plan does not touch.

Two survey claims did not survive checking, and the plan follows the corrected version:

- **"`allowed_methods=["GET","HEAD"]` means POST is not retried by the existing adapter config" is only half true.** urllib3 2.5.0's `Retry.increment` gates its *read*-error branch on `_is_method_retryable(method)` but leaves the **connection-error branch ungated**, so a POST that fails to connect is replayed regardless of `allowed_methods`. That is why Step 2 mounts no `Retry` at all rather than reusing or widening `_zenrows.py:74-88`'s shape: retry has to live in one layer that knows R13's idempotency-key rule.
- **A returned backoff of `0.0` does not mean "not retriable".** Measured against `src/scrapers/_http.py:86` at expansion time, `backoff_for_event` returns `0.0` for a `409`, for a `200`, and for a `503` carrying `Retry-After: 0` alike. Step 2 therefore decides retriability by status membership, as `retry_session_get` does at `:178-183`, and uses `backoff_for_event` only for the wait length.

## Contracts

Three review rounds produced 39 findings, and rounds 2 and 3 were each one defect wearing many
faces. Round 2's was: **a value crossing between the client, the run budget, the CLI and the later
shells had no single named producer and no stated type**, so two steps could each describe it
coherently and still disagree. Round 3 confirmed the table below closed that for *data* — and then
found ten more instances on a second axis the table did not cover: **callables, exception types,
derived deadlines, and the alternate (dry-run) path**. A zero-argument `key_supplier` could not know
which retry outcome it was in; `main(argv=None)` was called as `main(..., client=fake)`;
`STOP_CLEANUP_SECONDS` had no consumer anywhere; `_fail`'s exception class was never named.

**The invariant, widened, which the rest of this plan is written against: every value, callable,
exception class, derived deadline and alternate execution path that crosses one of those boundaries
appears below with exactly one producer and one stated type or signature. No step may refer to a
crossing thing the tables do not list, and no function may appear with two signatures.** Something
new means a new row first.

### Values

| Value | Type | Produced by | Consumed by |
|---|---|---|---|
| `BATCH_RUN_ID` | `str` | module import, once per process | `SubmissionSequence` only |
| `sequence` | `SubmissionSequence` | `main()` | `_plan_submissions` callers: `submit_tasks` and `_print_dry_run_plan` |
| `budget` | `RunBudget` | `main()` | `run_smoke`, which reads `.deadline` / `.pass1_deadline` |
| idempotency key | `str` | `sequence.next_key()` / `.retry_same()` / `.retry_fresh()` | `_request`, one per attempt |
| `reason` | `str \| None` | `_request`, from the branch it already computes for `backoff_for_event` | `key_supplier(reason)` |
| `premium` | `bool` | `main()`, as `args.premium_proxy == "true"` | the task builder, via `run_smoke`'s `premium` parameter |
| `tasks` | `list[dict]` | the task builder | `_plan_submissions`, `submit_tasks` |
| `(lifecycle, chunks)` | `tuple[str, list[list[dict]]]` | `_plan_submissions(tasks)` | `submit_tasks` and `_print_dry_run_plan` — the same producer, so the preview cannot drift from the submission |
| `job` | `BatchJob` (frozen, 5 fields) | `submit_tasks`, or `BudgetExpired.job` on abort | `poll_until_terminal`, `stop_run`, `settle`, `run_smoke`, shells 02–04 |
| `job.run_id` | `str` | `latest_run.run_id` on the create response | every poll, stop, results walk, settle |
| `job.accepted_tasks` | `int` | closed: the create response's `accepted_tasks`. open: a monotonic sum over the add-tasks responses | the settle predicate |
| `outcome` | `RunOutcome` (frozen) | `poll_until_terminal`, and `run_smoke`'s abort handler | `run_smoke`'s report, and shell 03 |
| `outcome.spend` | `int \| float \| None` | `settle`, from `latest_run.stats.spend` on the final `get_run` | the report, and the bookkeeping shell |
| `outcome.spend_is_lower_bound` | `bool` | `settle` | the report |
| `outcome.timed_out` | `bool` | `poll_until_terminal` | the report, and shell 03's degrade branch |
| `deadline` | `float`, a `time.monotonic()` value | `RunBudget.deadline` / `.pass1_deadline` for the run; `_cleanup_deadline()` for terminal cleanup | `_request`, `submit_tasks`, `poll_until_terminal`, `stop_run`, `settle` |
| `BudgetExpired.job` | `BatchJob \| None` | raised by `_request`; populated by `submit_tasks` before re-raise | the abort path and its report |

### Callables and exception classes

Every function this plan names, with its one signature. A second signature for any of these is the
defect round 3 found, so check this list before writing a call.

| Name | Signature | Notes |
|---|---|---|
| `main` | `main(argv=None, *, client=None)` | `client` exists so the argv-level test can reach a transmitted body |
| `_validate_run_args` | `_validate_run_args(args) -> list[str]` | empty list means valid |
| `_plan_submissions` | `_plan_submissions(tasks) -> tuple[str, list[list[dict]]]` | pure; the single source of chunking and lifecycle |
| `_print_dry_run_plan` | `_print_dry_run_plan(tasks, *, sequence) -> int` | the `--dry-run` path; returns an exit code |
| `run_smoke` | `run_smoke(args, *, premium, sequence, budget, client=None) -> int` | the non-dry-run path |
| `submit_tasks` | `submit_tasks(client, tasks, *, sequence, deadline) -> BatchJob` | `pass1_deadline` for job 1, the whole deadline for job 2 |
| `poll_until_terminal` | `poll_until_terminal(client, job, *, deadline) -> RunOutcome` | stops and settles on expiry |
| `_cleanup_deadline` | `_cleanup_deadline(time_source) -> float` | `time_source() + STOP_CLEANUP_SECONDS` |
| `key_supplier` | `key_supplier(reason) -> str` | `reason` is `None` on the first attempt |
| `ZenRowsBatchClient._request` | `_request(self, method, path, *, json_body=None, key_supplier=None, deadline=None) -> requests.Response` | |
| `.create_job_closed` | `(self, tasks, *, key_supplier, deadline)` | |
| `.create_job_open` | `(self, *, key_supplier, deadline)` | |
| `.add_tasks` | `(self, job_id, tasks, *, key_supplier, deadline)` | |
| `.close_job` | `(self, job_id, *, deadline)` | |
| `.get_run` | `(self, job_id, run_id, *, deadline=None)` | |
| `.iter_results` | `(self, job_id, run_id, *, deadline=None)` | |
| `.fetch_body` | `(self, result_url)` | no key, own retry, no deadline |
| `.stop_run` | `(self, job, *, deadline)` | takes the `BatchJob`, not a bare id |
| `.settle` | `(self, job, *, deadline, cap_seconds=SETTLE_CAP_SECONDS) -> tuple[spend, spend_is_lower_bound]` | |
| `BatchClientError(Exception)` | — | what `_fail` raises: every unmapped status and every named guard |
| `BodyFetchError(BatchClientError)` | — | one task's body could not be fetched; **counted, not fatal** |
| `BudgetExpired(Exception)` | `.job: BatchJob \| None` | a deadline passed; distinct from `BatchClientError` |

The two exception classes are separate on purpose. Shells 02–04 abort on `BatchClientError` and
degrade on `BudgetExpired`, and a single class — or an unnamed one an implementer picks, leaving the
later shells to catch `Exception` — would collapse the two expiry outcomes Step 4 works to keep
distinct.

### Decisions the tables encode

- **`key_supplier(reason)` covers every retriable outcome.** `_request` already computes the branch
  for `backoff_for_event`, so it passes: `None` on the first attempt → `sequence.next_key()`;
  `"explicit_503"` → `retry_fresh()`, the one case the contract says demands a new key; and
  `"unknown"` for a timeout or connection error **and** for 429/500/502/504 → `retry_same()`, because
  in all of those the server may already have accepted the submission and a fresh key would orphan a
  second billing job.
- **`job.run_id` on the open lifecycle.** The spec's contract table pins a response shape on the
  **closed** create row only. Both creates return the job object, so this plan reads
  `latest_run.run_id` from the create response in both lifecycles, and `_fail`s with the redacted
  create response if the open one lacks it rather than proceeding with `run_id=None`. Confirming its
  presence is a named item for the first open-lifecycle run (Risk 6).
- **`accepted_tasks` may be zero or short on an aborted job, and settle must not trust it.** On the
  success path `submit_tasks` `_fail`s if the total is zero, because the predicate
  `results >= accepted_tasks` is satisfied instantly by zero. That guard cannot fire on the abort
  path, where `BudgetExpired.job` deliberately carries however far submission got — an expiry between
  `create_job_open` and the first counted add-tasks response leaves the count at zero, and a lost
  add-tasks response leaves it short of what the server accepted. So `settle` **skips the count
  predicate entirely** when `job.accepted_tasks <= 0` or `job.accepted_tasks < job.submitted_tasks`:
  it waits out its cap and returns `spend_is_lower_bound=True`. An incomplete figure is reported as
  incomplete on the one path R36 says must still report credits.

## Implementation Steps

1. **Stand up `scripts/batch_drain_queue.py` and its CLI surface**
   - Create the file with the operator-CLI header from `scripts/retire_stranded_scrape_requests.py:35-64`: module docstring carrying usage examples, `truststore.inject_into_ssl()`, `sys.path.append(str(Path(__file__).resolve().parent.parent))`, then `load_dotenv(REPO_ROOT / ".env.local")` followed by `load_dotenv(REPO_ROOT / ".env")`. Add both output channels the way `scripts/drain_queue.py:46,56-57` does — `console = Console()` and `logging.basicConfig(...)` + `logger = logging.getLogger(__name__)`.
   - Module constants, all with concrete values:
     ```python
     BATCH_API_BASE = "https://async.api.zenrows.com/v1"
     MAX_TASKS_PER_SUBMISSION = 1000   # vendor OpenAPI maxItems on SubmitJobRequest.tasks
                                       # and AddTasksRequest.tasks; the prose docs' 10,000 is wrong
     RETRIABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
     DEFAULT_REQUEST_TIMEOUT_SECONDS = 30   # matches GOTSPORT_TIMEOUT's default (gotsport.py:313)
     DEFAULT_RETRY_DELAY_SECONDS = 2.0      # base for backoff_for_event's exponential term
     DEFAULT_REQUEST_ATTEMPTS = 3
     POLL_SECONDS = 15
     SETTLE_CAP_SECONDS = 180               # settle's own cap, inside the cleanup allowance
     STOP_CLEANUP_SECONDS = 240             # the whole terminal stop+settle allowance; 240 - 180
                                            # leaves 60s for the stop and its 409 re-fetch
     DEFAULT_WAIT_CAP_MINUTES = 120
     MIN_WAIT_CAP_MINUTES = 5
     DEFAULT_CLUB_RESERVE_MINUTES = 20
     SMOKE_SINCE_DATE = date(2025, 10, 17)  # gotsport.py:427's first-scrape baseline; the smoke
                                            # path has no last_scraped_at to derive one from
     ```
   - Proxy-tier parameters as two named constants, so the flag's effect is written down once and
     the unverified half is visible at the point of use:
     ```python
     # UNCONFIRMED for the Batch API. The sync proxy takes these names
     # (src/scrapers/_zenrows.py:94-96); a Batch task's zenrows_params is only verified to
     # accept `mode`. Confirm against the vendor OpenAPI or a one-task probe before the first
     # live premium run — an unrecognized key is silently dropped and bills the other tier.
     PREMIUM_PROXY_PARAMS = {"premium_proxy": "true", "proxy_country": "us"}
     DATACENTER_PROXY_PARAMS: dict[str, str] = {}
     ```
   - Run identifier following `scripts/scrape_affinity_wa_tournament.py:87-88`: `RUN_TS = datetime.now(timezone.utc).isoformat()` and `BATCH_RUN_ID = f"{RUN_TS}_{uuid.uuid4().hex[:6]}"`, computed once per process.
   - **`main(argv=None, *, client=None)`** builds the parser, calls `parser.parse_args(argv)`, runs `_validate_run_args`, then constructs the three things the Contracts table says it produces — `premium`, `sequence`, `budget` — and dispatches to exactly one of two paths: `_print_dry_run_plan(tasks, sequence=sequence)` when `--dry-run` is set, else `run_smoke(args, premium=premium, sequence=sequence, budget=budget, client=client)`. It ends with the `if __name__ == "__main__": main()` + `except KeyboardInterrupt → sys.exit(130)` / `except Exception → sys.exit(1)` wrapper from `drain_queue.py:906-925`. Both `argv` and `client` exist for Step 6: `argv` so a test drives the CLI without monkeypatching `sys.argv`, `client` so the proxy-tier assertion can follow a flag from `argv` all the way to a transmitted body.
   - Arguments: `--team-id` (repeatable), `--wait-cap-minutes` (int, default `DEFAULT_WAIT_CAP_MINUTES`), `--club-reserve-minutes` (int, default `DEFAULT_CLUB_RESERVE_MINUTES`), `--premium-proxy` (`choices=("true","false")`, `default=None`), and `--dry-run`.
   - **Convert `--premium-proxy` to a bool in `main`, once**: `premium = args.premium_proxy == "true"`. `argparse` with `choices` yields the *string* `"false"`, and `bool("false")` is `True` (verified), so any `if args.premium_proxy:` downstream would send premium parameters on the documented `--premium-proxy false` run and bill the 10x tier. `premium` reaches the task builder as `run_smoke`'s keyword parameter and nowhere else reads `args.premium_proxy`.
   - **`--premium-proxy` has no default on purpose.** R10 says the tier comes from the input and the spec's Open Questions records the default as unresolved pending the operator's ~300-team probe. Validation rejects its absence rather than picking a tier.
   - **`--dry-run` in this shell means "issue no ZenRows request".** `_print_dry_run_plan` prints the submission count, tasks per submission, each submission's idempotency key and the chosen lifecycle — all read from `_plan_submissions(tasks)`, the same function `submit_tasks` uses, so the preview cannot drift from what a real run would do. With no `--team-id` it prints an empty plan and returns 0. R37's other half — previewing team selection and a credit estimate with a read-only queue select — is not in this shell's scope and lands with the selection work.
   - Do not open, import from, or edit `scripts/drain_queue.py`, `.github/workflows/clear-queue.yml`, or `src/scrapers/gotsport.py` (R4). Reading `gotsport.py` for the URL shape is fine; the file must not appear in `git status`.

2. **Build the request layer as a `ZenRowsBatchClient` class in the same file**
   - The client lives inside `scripts/batch_drain_queue.py`, not `src/scrapers/`; promoting it is explicitly deferred in the spec's MVP Scope.
   - Define the three exception classes the Contracts table names: `BatchClientError(Exception)` (what `_fail` raises), `BodyFetchError(BatchClientError)`, and `BudgetExpired(Exception)` with `job: BatchJob | None = None`.
   - Constructor, with every knob a test needs to neutralize:
     ```python
     def __init__(self, api_key, *, session=None, base_url=BATCH_API_BASE,
                  timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
                  retry_delay=DEFAULT_RETRY_DELAY_SECONDS,
                  attempts=DEFAULT_REQUEST_ATTEMPTS,
                  sleep=time.sleep, time_source=time.monotonic):
     ```
     `sleep` and `time_source` are injected for the same reason `RunBudget`'s clock is: `backoff_for_event` adds a `random.uniform(0, 1.0)` jitter term, so even `retry_delay=0` sleeps up to a second per attempt and a retry test would otherwise burn real seconds in CI.
   - **This client owns retry outright. Mount no urllib3 `Retry`** — build the session with `HTTPAdapter(max_retries=0)`. This deviates from `src/scrapers/_zenrows.py:74-88` for two measured reasons. First, urllib3 2.5.0's `Retry.increment` gates its *read*-error branch on `_is_method_retryable(method)` but leaves the **connection-error branch ungated**, so `allowed_methods=["GET","HEAD"]` does not stop a POST being replayed on a connect failure — retry would happen in a layer that knows nothing about the key rule. Second, leaving the mount on would double-retry the GETs against both layers, up to twelve attempts with compounding waits charged to the same run budget, contradicting the division of responsibility `src/scrapers/_http.py:1-20` sets out in its own docstring.
   - `_headers(self, idempotency_key=None)` returns `{"X-API-Key": self.api_key, "Content-Type": "application/json"}` plus `Idempotency-Key` when given. Never log or repr this dict.
   - **`_request` calls `key_supplier(reason)` once per attempt**, passing the branch it already computes for `backoff_for_event`: `None` on the first attempt, `"explicit_503"` on a 503, and `"unknown"` on a timeout, a connection error, or a 429/500/502/504. That parameter is the whole point — a zero-argument supplier cannot know which case it is in, and the closure would need hidden shared state with the loop. The mapping the supplier applies is in the Contracts table.
   - **`_request` does not raise on an HTTP status.** It returns the `requests.Response` for any status it does not retry; each caller maps statuses itself. It raises only when the transport never produced a response, when attempts are exhausted, or when the deadline expires.
     - **Decide retriability by status membership in `RETRIABLE_STATUSES`, never by the backoff value.** `backoff_for_event` returns `0.0` for a `503` carrying `Retry-After: 0` — identical to what it returns for a `409` and a `200` (measured against `src/scrapers/_http.py:86`). Treating `0.0` as "not retriable" would silently skip exactly the 503 retry the contract requires. Use `backoff_for_event` only for *how long* to wait, matching how `retry_session_get` branches at `src/scrapers/_http.py:179-182`.
     - **Deadline propagation.** When `deadline` is given, compute `remaining = deadline - self._now()` before every attempt; if it is `<= 0`, raise `BudgetExpired` **without issuing the request**. Pass `timeout=min(self.timeout, remaining)` to `requests`, and clamp each backoff sleep to `remaining`. Without this a single `Retry-After` wait can be 120 seconds — `backoff_for_event` clamps there — and a chunk started just before `pass1_deadline` would eat into the club reserve.
   - **Redaction (R38).** The key rides in a header, so `_redact` on `Response.url` buys nothing here. `_fail(self, message)` passes the message through `_redact(text, self.api_key)` from `src/scrapers/_zenrows.py:39` and raises `BatchClientError`; route every raise through it. The same redaction wraps every `logger` call the client makes, including the retry-attempt warning, whose text may quote a response body; no path may log the headers dict or a prepared request.
   - **Every method states its status mapping.** Since `_request` returns unretried responses, a caller without a map hands an error body to `.json()`:
     - `create_job_closed` / `create_job_open` / `add_tasks`: `2xx` → parse. **`409` → the server already holds this submission.** Parse the 409 body and, if it carries the job identifier, continue with it — the replay case. If it does not, `_fail` naming the idempotency key used and the redacted 409 body, telling the operator to find the job in the ZenRows dashboard. **This is the design's one manual-recovery path, and it exists because the verified contract exposes no endpoint that looks a job up by key or lists jobs.** Any other non-2xx → `_fail`.
     - `close_job`: `2xx` → done; `409` → already closed, which is success here; any other non-2xx → `_fail`.
     - `get_run`: `2xx` → parse; **any non-2xx → `_fail`**. Left unmapped, a 401 or a wrong `run_id` returns a body with no terminal status and the poll spins to its deadline for a reason no log explains.
     - `iter_results`: `2xx` → yield each entry of `results`, following `next_cursor` until absent or empty; **any non-2xx → `_fail`**. Left unmapped, an error body yields nothing and settle counts zero forever. Stop if a page returns the cursor just used.
     - `fetch_body`: a plain GET with **no** `X-API-Key` and no `Idempotency-Key` — the URL is presigned S3 (`X-Amz-Expires=7200`), and sending the key would ship a credential to a third party for nothing. `2xx` → return `json.loads(resp.text)` **regardless of the reported `type`**, which is `html` even for JSON (R24). Non-2xx or a transport failure → sleep `retry_delay`, retry **once**, then raise **`BodyFetchError`**. It must not be a run-ending `_fail`: the spec's Error handling (line 376) says a failed body download is "retried once, then counted as `error`" — a per-task bucket R28/R30 classify. This is live at this shell's own defaults, since `X-Amz-Expires=7200` (spec line 309) is exactly the 120-minute `wait_cap_minutes` default (spec line 288), so on a full-length run the earliest tasks' presigned links can expire before their bodies are read, and one stale link would otherwise abort a run that had already paid for every fetch. The caller catches `BodyFetchError`, counts that task as `error`, and continues.
     - `stop_run(self, job, *, deadline)`: `2xx` → parse; `409` with `code == "run_not_stoppable"` → re-read via `get_run(job.job_id, job.run_id, deadline=deadline)` and treat the run as terminal; any other 409 and every other non-2xx → `_fail`.
   - Task shape (R10, R11), with `premium` the bool from Step 1:
     ```python
     {"url": <match-list URL>, "external_id": str(provider_team_id),
      "zenrows_params": PREMIUM_PROXY_PARAMS if premium else DATACENTER_PROXY_PARAMS}
     ```
     `zenrows_params` must **never** contain `mode: auto` — the measured cost was 35 credits for 11 tasks on auto against 11 on defaults, and auto escalates a single dead team to 25 credits.

3. **Add submission shaping**
   - Local `def _chunked(values, size)` generator matching `scripts/prepare_prospective_match_predictions.py:226-232`. Keep `MAX_TASKS_PER_SUBMISSION` the only cap it is ever called with.
   - **URL builder.** Reproduce `src/scrapers/gotsport.py:431`'s shape, `f"https://system.gotsport.com/api/v1/teams/{normalized}/matches"`, where `normalized = int(float(str(provider_team_id)))` exactly as `:409` computes it — its comment spells out why (`handle "126693.0" -> 126693`), and a path built from the raw id ships `.../teams/126693.0/matches`, which answers 404 as a silent per-team zero-game outcome. **The normalization applies to the path segment only**: `external_id` stays the raw string per R11. Set both `since_date` and `from_date` to the same `%Y-%m-%d` string (`:443-447`); this shell's smoke path uses `SMOKE_SINCE_DATE`. Copy the shape; do not import from or edit `gotsport.py`.
   - **`_plan_submissions(tasks) -> tuple[str, list[list[dict]]]`** is a pure function returning the lifecycle (`"closed"` when `len(tasks) <= MAX_TASKS_PER_SUBMISSION`, else `"open"`) and the chunks. Both `submit_tasks` and `_print_dry_run_plan` call it, so the dry-run preview and the real submission cannot disagree about how many submissions there will be or which lifecycle is used.
   - **One idempotency sequence for the whole process.** `SubmissionSequence`, constructed once in `main()`: `next_key()` allocates `f"{BATCH_RUN_ID}:{n}"` and advances `n`; `retry_same()` returns the current key unchanged; `retry_fresh()` allocates the next `n`. `n` is monotonic across *every physical submission the process makes, both jobs included* — the club-resolution work creates a second job in the same process, and a per-call counter restarting at 0 would replay `<BATCH_RUN_ID>:0` against `POST /jobs` with a different body, drawing a 409 whose recovery is manual. The first submission of a process is `<BATCH_RUN_ID>:0` and nothing else ever is.
   - **`submit_tasks(client, tasks, *, sequence, deadline) -> BatchJob`.** The deadline is passed explicitly rather than derived from a `RunBudget`, because the same helper serves both jobs against different boundaries: pass 1 gets `budget.pass1_deadline` so it cannot consume the club reserve; the club-resolution job gets `budget.deadline` so it can use the reserve it was carved out of.
     ```python
     @dataclasses.dataclass(frozen=True)
     class BatchJob:
         job_id: str
         run_id: str
         lifecycle: str            # "closed" | "open"
         submitted_tasks: int
         accepted_tasks: int
     ```
   - Submit per `_plan_submissions`: closed → one `create_job_closed`; open → `create_job_open`, one `add_tasks` per chunk, then `close_job`. An open run begins fetching as soon as the first chunk lands, so later chunks stream in while earlier ones are in flight and the close call is not a starting gun.
   - `run_id` and `accepted_tasks` are sourced exactly as the Contracts table specifies, including the `_fail` guards it names (no `latest_run` on an open create; a zero total on the success path).
   - **`submit_tasks` catches `BudgetExpired`, attaches whatever `BatchJob` it has built so far, and re-raises.** The expiry can land during add-tasks or close, after the job exists but before the normal return — and the abort path needs `job_id` and `run_id` to stop the run and report it. Log both immediately after the create succeeds, so a hard kill before the raise still leaves them in the workflow log. If the *initial* create's outcome is unknown there is no handle to attach and the dashboard-recovery path applies; do not build recovery machinery for it.

4. **Add run control**
   - `RunBudget(wait_cap_minutes, club_reserve_minutes, *, time_source=time.monotonic)`. `start()` records `self._deadline = self._now() + wait_cap_minutes * 60`; then `remaining()`, `expired()`, `deadline`, `pass1_deadline` (the deadline less the reserve), and `reserve_remaining()`. The injectable clock lets the tests advance time instead of sleeping, mirroring `tests/unit/test_gotsport_waf_breaker.py:187`.
   - **Start the clock at the first create request** (R14), not at process start — `budget.start()` immediately before the first `POST /jobs`, so it covers submission, the open period, the close call and all polling, and time spent selecting teams in a later shell does not eat the ZenRows budget.
   - **`_validate_run_args(args) -> list[str]`** is a separate importable function returning human-readable errors; `main()` prints each through `console` in red and `sys.exit(1)` if any are returned. Extracting it makes the validation assertions in Step 6 reachable from a unit test. The checks, following the ladder at `scripts/retire_stranded_scrape_requests.py:161-179`:
     - `wait_cap_minutes` is a positive integer of at least `MIN_WAIT_CAP_MINUTES` (5).
     - `club_reserve_minutes` is a positive integer.
     - `club_reserve_minutes < wait_cap_minutes`. Equal or greater leaves pass 1 a zero-or-negative budget.
     - `--premium-proxy` was supplied.
     - **At least one `--team-id` — only when `not args.dry_run`.** A real run with no tasks would submit `create_job_closed(tasks=[])`, drawing a vendor error this plan has no mapping for or creating a zero-task job. A dry run with none is legitimate: it prints an empty plan, and the later shell's dry run previews queue selection rather than `--team-id` values.
     - `ZENROWS_API_KEY` is set — **only when `not args.dry_run`**, matching `scripts/retire_stranded_scrape_requests.py:174`, which gates its service-role key the same way and says why in a comment.
   - **`_cleanup_deadline(time_source) -> float`** returns `time_source() + STOP_CLEANUP_SECONDS`. It is the only producer of a terminal-cleanup deadline, and both callers of stop/settle use it: `poll_until_terminal` on an expiry, and `run_smoke`'s abort handler.
   - **`poll_until_terminal(client, job, *, deadline) -> RunOutcome`** is the poll loop. It follows `scripts/pr_wait.py:193-209` with one change: **check the deadline before each fetch as well as after**, and clamp `time.sleep(POLL_SECONDS)` to the time remaining, so a poll cycle cannot overshoot the boundary it guards.
     ```python
     @dataclasses.dataclass(frozen=True)
     class RunOutcome:
         job: BatchJob
         spend: int | float | None
         spend_is_lower_bound: bool
         timed_out: bool = False
         aborted: bool = False
     ```
     `timed_out` is deliberately deadline-agnostic rather than named for pass 1: the club-resolution shell polls its own job through this same function, where an expiry means abort rather than degrade, and a `pass1_`-prefixed field would be read wrongly there. The caller decides what a timeout means; the loop only reports it.
   - **Two distinct expiry outcomes, which must not be wired to one signal:**
     - **Whole-run `deadline` reached while any submission or the close call is still outstanding** (R14) → `_request` raises `BudgetExpired`, `submit_tasks` attaches the partial job, and `run_smoke`'s handler stops and settles on `_cleanup_deadline(...)` and reports `aborted=True`. This shell only raises the signal; releasing outstanding rows belongs to the selection work.
     - **The poll's `deadline` reached inside `poll_until_terminal`** (R15) → **not** an abort. Stop and settle on `_cleanup_deadline(...)`, then return a `RunOutcome` with `timed_out=True` carrying the settle result, so the caller can collect what exists and fund club resolution from the reserve. R15 is explicit that only a *reserve* expiry aborts; collapsing both into `BudgetExpired` would delete the degrade path.

5. **Add stop handling and the settle-wait**
   - `stop_run` and `settle` take the cleanup deadline from `_cleanup_deadline(...)`, **deliberately not the run deadline**, and thread it through every request they make — the stop, its 409 `get_run` re-fetch, and settle's `get_run` and `iter_results` calls. The reason is concrete: the R14 abort branch reaches them *because* `budget.deadline` has already passed, so threading that through would make the first `get_run` raise `BudgetExpired` — the stop would never be issued and the settle R16 exists for would never run. `SETTLE_CAP_SECONDS` (180) is settle's own cap *inside* the 240-second allowance, leaving 60 seconds for the stop and its re-fetch, so the two bounds compose rather than competing.
   - `stop_run(job)` treats **409 with `code == "run_not_stoppable"`** as "already terminal" (R16): re-fetch with `get_run(job.job_id, job.run_id)` and return that. Any other 409, and every other non-2xx, fails through `_fail`.
   - After a *successful* stop, tasks already in flight can still finish and record results, so a spend figure read immediately is short. `settle` polls until every accepted task has a result entry, then takes the final run and spend snapshot, returning `(spend, spend_is_lower_bound)`. The flag is set when the cap was hit first, or when the count predicate could not be trusted. **A settle-cap lower bound is not an abort**: it means the figure is incomplete, and the run continues to its normal reporting.
   - **The settle predicate counts result entries against `job.accepted_tasks`,** except in the untrustworthy-count cases the Contracts section names, where it waits out its cap and returns a lower bound instead. The spec pins `accepted_tasks` on the create response, and pins that every task produces a result entry either way: "`result_url` is empty for non-successful tasks and `error` is present on failed ones — the two are exclusive", the same guarantee R28's per-team classification rests on. **What is off the table is any *per-task counter* under `stats`** — those field names are unrecorded, and a predicate reading one that does not exist evaluates as "settled" instantly. Counting non-terminal entries fails the same way, because an in-flight task has no entry at all.
   - **The spend figure is `latest_run.stats.spend` on the final `get_run`.** This is not the per-task-counter case: the spec names this exact path — "One job means one `run_id` and one cumulative `stats.spend`" — so it is as pinned as `accepted_tasks`. `run_poll_completed.json` carries a spend value and Step 6 asserts the extracted number, so a wrong path fails a test rather than reaching the operator as a `None` printed like a fact.

6. **Record fixtures and test the client in isolation**
   - Create `tests/fixtures/zenrows_batch/` mirroring `tests/fixtures/sincsports_clubs/`: JSON captures plus a `README.md` table naming each file, what it is, its capture date, and — critically — **whether it is a live capture or hand-built from the documented contract**. The `event_synthetic_*` files under `tests/fixtures/gotsport/` are the precedent for hand-built cases living alongside real ones.
   - Files: `create_closed.json`, `create_open.json`, `add_tasks.json`, `close.json`, `create_409_idempotency_conflict.json`, `close_409_already_closed.json`, `run_poll_running.json`, `run_poll_completed.json` (carrying a `stats.spend` value), `results_page_1.json` (with a `next_cursor`), `results_page_2.json` (without), `stop_409_run_not_stoppable.json`, and one trimmed GotSport match-list body as `result_body_matches.json`. Keep them small the way `trim_landing_to_gids` (`tests/conftest.py:44`) keeps the gotsport corpus small.
   - Hand-build them from the contract in `.claude/skills/scraper-patterns/SKILL.md` § ZenRows Batch API so the suite is green without spending credits, and mark them synthetic in the `README.md`. Replacing them with a live capture is an **operator-run** step. `scripts/capture_gotsport_fixtures.py:34` is the precedent for a re-runnable capture writing into `tests/fixtures/`, and its `pytest.mark.skipif(not fixture_path.exists())` tolerance (`:16-18`) keeps CI green across a partial capture.
   - `tests/unit/test_batch_drain_queue.py` with `sys.path.append(...)` then `from scripts.batch_drain_queue import ...`, as `tests/unit/test_drain_queue_topup.py:7-9` does, and `FIXTURES = Path(__file__).parent.parent / "fixtures" / "zenrows_batch"` per `tests/unit/test_sincsports_clubs.py:19`. Stub responses with `unittest.mock.MagicMock(spec=requests.Response)` or a local `FakeResponse`-style class carrying `.status_code`, `.headers`, `.text`, `.json()` and `raise_for_status()` — there is no `responses`/`requests-mock`/`freezegun` in either requirements file, and adding one would touch `requirements.lock`. Drive every client test through a **fake session that records each call's method, URL, headers, JSON body and `timeout`**.
   - Assertions this shell owes:
     - **The chunk boundary at the real cap**, asserted on `_plan_submissions` and on the calls: exactly 1,000 tasks gives lifecycle `"closed"`, one create and zero `add_tasks`; 1,001 gives `"open"`, two `add_tasks` of 1,000 and 1, and one close.
     - **The dry-run preview matches the real plan**: `_print_dry_run_plan` and `submit_tasks` on the same 1,001 tasks report the same lifecycle, the same submission count and the same keys.
     - **The open path's returned totals**: that 1,001-task submission yields `accepted_tasks == 1001` and a non-empty `run_id`; an add-tasks response omitting a count still contributes its chunk size; a zero total on the success path raises `BatchClientError`.
     - **One continuous key trace across a 503 and a second job**: a 503 on the first create turns `:0` into `:1`, and the next submission uses `:2`. Asserting the rotations separately would pass even if `retry_fresh()` returned a new key without advancing the shared counter.
     - **`key_supplier` receives the right `reason`**: `None` first; `"explicit_503"` on a 503 → a different key; `"unknown"` on a timeout **and** on a 429/500/502/504 → the same key. Assert on the `Idempotency-Key` header the fake session received, not on the sequence's internals.
     - **A 503 carrying `Retry-After: 0` is retried**, not treated as terminal.
     - **Proxy tier through the argv seam**: `main(["--team-id","126693","--premium-proxy","false", ...], client=fake)` sends `DATACENTER_PROXY_PARAMS` in each task's `zenrows_params`, and `"true"` sends `PREMIUM_PROXY_PARAMS`, both read off the JSON body the fake session received. Entering below the CLI would pass while `bool("false")` silently selected premium. No submitted body anywhere contains `mode` set to `auto` (R10).
     - `external_id` is the raw string while the path segment is the normalized integer — from one task built from `"126693.0"`, assert `external_id == "126693.0"` and a path containing `/teams/126693/matches`. Every task's `url` carries both date params (R9).
     - **Status maps, positive and negative, for all seven methods**: the 409 fixtures drive `stop_run` to re-fetch, `close_job` to succeed, add-tasks to replay, and a create 409 with a job id to continue while one without raises naming the key; and a representative rejected status (401 or 404) on `get_run` and `iter_results` raises `BatchClientError` rather than being parsed. Without the negative half, a method that accepts every status stays green.
     - **A failed body download is counted, not fatal**: a non-2xx on `fetch_body` retries once then raises `BodyFetchError`, and the Step 7 dispatcher catches it, marks that task `error`, and still processes the remaining entries.
     - **`type: "html"` through the dispatcher, not just `fetch_body`**: drive a complete `iter_results` entry whose `type` is `"html"` through Step 7's dispatch and assert the body was fetched and reached `json.loads`. `fetch_body` never receives `type`, so testing it alone cannot catch a dispatcher that filters on it.
     - Cursor paging walks `results_page_1.json` → `results_page_2.json` and stops; a repeated cursor terminates rather than looping.
     - **Settle**: with `accepted_tasks = 3` and results arriving 1 → 3, `settle` returns `spend_is_lower_bound=False` **and the spend value from `run_poll_completed.json`'s `stats.spend`**; with results stuck at 2 and the cap reached, `True`. And with a job whose `accepted_tasks` is 0 or below `submitted_tasks`, settle does **not** return immediately — it waits out its cap and returns `True`, which is the abort-path hole the count predicate would otherwise open.
     - **Credential safety at three boundaries, each able to fail**: (a) an exhausted `_request` raises a `BatchClientError` whose message does **not** contain the key — and separately, a stubbed error body echoing the key, passed through `_fail`, comes back with `REDACTED`, the positive test a header-borne key cannot produce on its own; (b) a retry driven by a synthetic exception containing the key emits the expected warning record **and** that record holds `REDACTED` and not the key; (c) the GET `fetch_body` issues carries no `X-API-Key` header.
     - **Both halves of deadline clamping**: with remaining time shorter than `self.timeout`, the `timeout` the fake session recorded equals the remaining time; with the boundary inside the backoff wait, the sleep is clamped and `BudgetExpired` is raised; with the deadline already past on entry, no request is issued at all.
     - **The cleanup deadline is threaded and bounded**: on a poll timeout, every request the stop and settle issue carries a deadline derived from `_cleanup_deadline`, and the combined stop+settle wall time stays inside `STOP_CLEANUP_SECONDS` on the injected clock. Asserting only that stop and settle were called would pass with the constant unused.
     - **Validation**: `_validate_run_args` rejects `wait_cap_minutes=4` and accepts `5`; rejects `club_reserve_minutes >= wait_cap_minutes`; rejects a missing `--premium-proxy`; rejects an empty `--team-id` list **only when `--dry-run` is absent**, and accepts it with `--dry-run`; and requires `ZENROWS_API_KEY` only when `--dry-run` is absent, with the key removed from the environment in-process. Every case supplies otherwise-valid arguments and asserts the specific message. `pass1_deadline` sits exactly `club_reserve_minutes` before the whole-run deadline.
     - **The two expiry outcomes are distinct**: a budget expiring part-way through a chunked submission raises `BudgetExpired` **carrying the partial `BatchJob`** rather than continuing to add tasks; `poll_until_terminal` hitting its deadline returns a `RunOutcome` with `timed_out=True` **carrying the settle result**, does not raise, and has called stop and settle first — asserting the boolean alone would pass if those were removed or their spend discarded.

7. **Wire the end-to-end smoke path**
   - `run_smoke(args, *, premium, sequence, budget, client=None) -> int` — the function `main` calls when `--dry-run` is absent. Every input it needs arrives as a parameter, per the Contracts table: it never re-reads `args.premium_proxy` and never builds its own `sequence`. When `client` is `None` it builds one from the environment as normal.
   - It ties Steps 2–5 together: build tasks from the `--team-id` values and `premium`, `budget.start()`, `job = submit_tasks(client, tasks, sequence=sequence, deadline=budget.pass1_deadline)`, `outcome = poll_until_terminal(client, job, deadline=budget.pass1_deadline)`, then walk `iter_results`, `fetch_body` each entry carrying a `result_url` (catching `BodyFetchError` per task), and print per task its `external_id`, whether it returned a body or an `error`, and the parsed body's match count.
   - Print `job_id` and `run_id` before the first poll, not after the run settles — a cancelled or timed-out run is only recoverable inside ZenRows' 14-day retention if those ids reached the log while the run was still alive.
   - **Report from `outcome`, not around it.** Print `outcome.spend`, labelled a lower bound when `outcome.spend_is_lower_bound`, and say plainly that pass 1 timed out when `outcome.timed_out` — otherwise a timed-out run prints exactly like a complete one, including a spend figure that came from a stopped run, which is the one thing the flag exists to signal.
   - On `BudgetExpired`, stop and settle on `_cleanup_deadline(...)` using `exc.job`, print its ids, and report `aborted=True` with the spend as a lower bound. This is the shape the later shells' run summary grows out of; it does not attempt the full per-reason accounting, which belongs with the bookkeeping work.

## Verification

- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` — the exact python-lint CI path list; `scripts/batch_drain_queue.py` is inside it. Expect no findings. Import ordering is enforced (`select` includes `I`), so the `sys.path.append`-before-`src.*` block needs `# noqa: E402` the way `scripts/assign_team_states.py:106-112` does.
- `python -m pytest tests/unit/test_batch_drain_queue.py -v` — every assertion in Step 6 passes. The file should finish in well under a second: no test sleeps, because `RunBudget`'s clock and the client's `sleep`/`time_source` are all injected.
- `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py` — CI's exact form; nothing else regresses. `ruff` and `pytest` are not on PATH on a stock Windows checkout, so both go through `python -m`.
- `git status --short` shows **only** `scripts/batch_drain_queue.py`, `tests/unit/test_batch_drain_queue.py`, and `tests/fixtures/zenrows_batch/*` as new. `scripts/drain_queue.py`, `.github/workflows/clear-queue.yml` and `src/scrapers/gotsport.py` must not appear (R4). Ignore the planning workflow's own artifacts, already in the tree before the first line of code is written: this plan file, `.turbo/specs/zenrows-batch-bulk-scrape.md`, one deletion under `.turbo/shells/`, the `.claude/skills/scraper-patterns/SKILL.md` modification, and the unrelated staged/untracked work belonging to other sessions.
- Dry-run smoke — no network, no credits, no API key required:
  `python scripts/batch_drain_queue.py --team-id 126693 --premium-proxy false --wait-cap-minutes 30 --club-reserve-minutes 5 --dry-run`
  Expect: one planned submission, one task, the closed-inline lifecycle named, `external_id` printed as the string `"126693"`, the URL path containing `/teams/126693/matches`, the idempotency key printed as `<BATCH_RUN_ID>:0`, and zero HTTP requests issued.
- Argument-validation spot checks. Each supplies otherwise-valid arguments so it can only trip the guard under test, and each is expected to exit non-zero with a red `console` line naming that rule, and to issue no HTTP:
  - `--team-id 126693 --premium-proxy false --wait-cap-minutes 4 --club-reserve-minutes 2 --dry-run`
  - `--team-id 126693 --premium-proxy false --wait-cap-minutes 20 --club-reserve-minutes 20 --dry-run`
  - `--team-id 126693 --wait-cap-minutes 30 --club-reserve-minutes 5 --dry-run` (no `--premium-proxy`)
  - `--premium-proxy false --wait-cap-minutes 30 --club-reserve-minutes 5` (no `--team-id`, and **no** `--dry-run` — with `--dry-run` this is valid and prints an empty plan)
- **The missing-key check is a unit test, not a shell command.** It belongs in Step 6, calling `_validate_run_args` with `--dry-run` absent and `ZENROWS_API_KEY` removed from the environment in-process. Running it as a shell command would require the key to be absent from the process environment *and* from both dotenv files the script loads; `.env` carries no `ZENROWS_API_KEY` and `.env.local` does not exist on this checkout, but the plan cannot guarantee that on the operator's machine or in CI — and the failure is fail-open, since a check meant to exit on a missing key would instead pass validation and submit a **paid** job.
- **Live smoke — operator-run, spends a small number of credits.** With `ZENROWS_API_KEY` set:
  `python scripts/batch_drain_queue.py --team-id <id> --team-id <id> --premium-proxy false --wait-cap-minutes 30 --club-reserve-minutes 5`
  Expect `job_id` and `run_id` printed before the first poll, a poll to completion, results paged, bodies fetched and parsed as JSON, and a spend figure. This proves the client reaches the API and is the natural moment to replace the synthetic fixtures with live captures. Do not run it as part of implementation; hand it to the operator.

### Risks

1. **The premium-tier key names inside a Batch task's `zenrows_params` are unverified.** `PREMIUM_PROXY_PARAMS` carries the sync proxy's names (`src/scrapers/_zenrows.py:94-96`); the contract confirms only that `zenrows_params` is the container and that `mode` works there. An unrecognized key is silently dropped and bills the datacenter tier. The constant and its Step 6 assertion mean one edit fixes it once the operator's probe or the vendor OpenAPI settles the name. Resolve before the first live premium run.
2. **Per-task counter field names under `stats` are unrecorded**, which is why the settle predicate counts result entries against `accepted_tasks`. `stats.spend` is a separate case and *not* covered by this risk — the spec names that exact path — but if a live capture shows `spend` living elsewhere, Step 6's spend assertion is what fails.
3. **A create 409 whose body carries no job identifier is only recoverable by hand**, through the ZenRows dashboard, because the verified contract exposes no endpoint that lists jobs or looks one up by idempotency key. The client makes that case loud — the key and the redacted body are in the failure message — rather than pretending to recover.
4. **Synthetic fixtures pin our parsing, not the vendor's contract.** The point of recording contract fixtures for a beta API is that a vendor change fails a test instead of a production run, and a hand-built fixture cannot do that — only live captures can. The `README.md` must say which files are which.
5. **`premium_proxy`'s default is an open question the spec deliberately left unresolved** and assigns to the workflow shell. This shell requires the flag rather than choosing.
6. **The open create's response shape is unpinned.** The spec's contract table gives a response shape for the closed create row only. This plan reads `latest_run.run_id` from the create response in both lifecycles and `_fail`s loudly if the open one lacks it — but that assumption is only confirmed by the first open-lifecycle run, which is also the first run above 1,000 teams.
7. **The whole-run budget's relationship to `timeout-minutes` is only half-enforced here.** This shell validates the budget's floor, the reserve carve-out, that no single request or sleep overruns a boundary, and that terminal cleanup is separately bounded by `STOP_CLEANUP_SECONDS`; that the budget plus that allowance sits far enough below the workflow timeout to leave import and claim-cleanup time is a property of the workflow file, which a later shell writes.

## Context Files

- `.turbo/specs/zenrows-batch-bulk-scrape.md` — R10–R16, R24 and R38 are this shell's contract; the *Design → Batch API contract* table is the endpoint-by-endpoint reference (and the source of `accepted_tasks` and the result-entry guarantee the settle predicate rests on), R12's closing line pins `stats.spend`, *Error handling* line 376 is why a failed body download is counted rather than fatal, and *Cost model* is why `mode: auto` is banned. Untracked in the working tree.
- `.claude/skills/scraper-patterns/SKILL.md` § ZenRows Batch API — the live-verified 2026-09-03 contract in prose: the 1,000-task `maxItems`, the open-run-fetches-immediately behaviour, the presigned-S3 `result_url`, the `type: 'html'` lie, the 409 `run_not_stoppable`, and the `Idempotency-Key` 409-on-conflict / fresh-key-on-503 rule. Currently an uncommitted modification to a tracked file.
- `src/scrapers/_zenrows.py` — `_redact` at `:39` (imported directly), the missing-key error at `:61`, and the `premium_proxy`/`proxy_country` param names at `:94-96` that Risk 1 is about. Its `HTTPAdapter`/`Retry` mount at `:74-88` is read as the thing this client deliberately does **not** copy; Step 2 says why.
- `src/scrapers/_http.py` — `backoff_for_event` at `:86` (read its event shapes and clamps; used for wait length only, never for the retry decision), `RateLimitedError` at `:43`, and `retry_session_get` at `:133`, whose status-membership branch at `:179-182` is the pattern to copy and whose GET-only restriction at `:162` is why the retry loop is written locally.
- `scripts/retire_stranded_scrape_requests.py` — the header/argparse/validation skeleton to mirror: `:35-64` for the module top and constants, `:140-179` for the parser and the exit-1 validation ladder, and `:174` for gating a credential on the write path only.
- `scripts/drain_queue.py` — read for the dual `rich`+`logging` setup at `:46,56-57` and the `main()` exit-code wrapper at `:906-925`. **Read only — R4 forbids editing it.**
- `scripts/pr_wait.py:185-215` — the `time.monotonic()` deadline loop `poll_until_terminal` and `settle` mirror.
- `src/scrapers/gotsport.py:409,431,443-447` — the team-id normalization, the match-list URL, and the date params to reproduce; `:427` for the `SMOKE_SINCE_DATE` baseline. **Read only — R4 forbids editing it.**
- `tests/conftest.py:25-50` — `FakeResponse` and why a bare `MagicMock()` does not satisfy a response contract; also `trim_landing_to_gids` as the precedent for keeping fixtures small.
- `tests/unit/test_zenrows.py` — the stated no-HTTP-mocking convention and the existing `_redact` tests.
- `tests/unit/test_sincsports_clubs.py:19` and `tests/fixtures/sincsports_clubs/README.md` — the fixture-directory layout and loader idiom to copy.
- `pyproject.toml:9-31` — pytest `strict_markers` (a new marker must be declared here first) and the ruff `line-length = 120` / `select = ["E","F","W","I"]` settings the new file must satisfy.
