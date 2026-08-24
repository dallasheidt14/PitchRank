---
status: done
spec: C:/PitchRank/.turbo/specs/seo-geo-authority-push.md
---

# Plan: Target List Build — Scrape, Enrich, Verify

## Context

The outreach campaign is only as safe as its list. Scraped and pattern-guessed addresses for small club/association domains routinely carry 10–30% invalid rates, and sending to them is the fastest way to burn the freshly-warmed domain. This shell builds the segmented target list using the owned scraping stack, enriches contacts, and — critically — runs every address through real-time verification before it is allowed into a send batch. The output populates the `outreach_targets` table from shell 1.

**Resolved at expansion:**
- **Scrapers:** fork the existing Scrapy project as the template and write new, config-driven contact-harvesting spiders (the existing spiders scrape soccer data, not contacts). Reuse the ZenRows request shape (a new helper kept local to the outreach project) and the app retry layer; swap the CSV pipeline for a Supabase sink.
- **Vendors:** Hunter for email finding/enrichment, NeverBounce for the verification gate. Both keyed via `os.getenv` from `C:/PitchRank/.env`, matching the ZenRows secret convention.
- **Personalization storage:** add a structured `personalization JSONB` column to `outreach_targets`; exact token selection per segment is finalized with shell 3's templates.
- **Right-sized for solo/sequential operation:** this is a solo, ~150–250-contact/week pipeline run one script at a time, not a concurrent multi-worker queue. So there is **no batch-lease/`processing`-status/`batch_id`/reaper machinery** — that distributed-queue rigor is unnecessary here. Resumability comes from the `status`/`verification_status` fields (a re-run skips already-enriched/already-verified rows). Dedupe is Python-side on `(segment, source_domain, org)` plus one `lower(contact)` unique index as a DB safety net. (If spiders are ever parallelized, revisit and add the lease/RPC machinery then.)
- **Lifecycle:** `status: queued -> verified | held`. The invalid-rate gate counts **hard-invalid only**; catch-all/unknown and no-email rows go to `held` (manual review, never auto-sent), so they don't threaten the domain or block clean batches.

## Pattern Survey

### Analogous Features
- `src/scrapers/gotsport.py:619` — `_make_zenrows_request(url, params)`: the canonical ZenRows call shape (`zenrows_params = {apikey, url, js_render, premium_proxy, proxy_country:"us"}`, `session.get("https://api.zenrows.com/v1/", params=..., timeout=...)`). New contact spiders model a **local** helper on this shape; do NOT refactor the existing methods — `gotsport.py` already has several (`_make_zenrows_request` at 619 and 1587 with different signatures, module-level `_zenrows_get` at 1008, `_fetch_json_via_zenrows` at 1605) with intentional per-caller timeout/CAPTCHA handling.
- `src/scrapers/_http.py:1` — app-level retry/backoff (`retry_session_get`, `RateLimitedError`, `backoff_for_event`) over urllib3 `Retry`; owns 429 + `Retry-After`; env toggle `SCRAPER_DISABLE_APP_RETRY=1`. Reuse for scraping politeness AND for the Hunter/NeverBounce HTTP calls.
- `scrapers/modular11_scraper/` — the only full Scrapy project. Layout: `scrapy.cfg`, `modular11_scraper/{settings,items,pipelines}.py`, `spiders/`. Persists to timestamped CSV (`pipelines.py:open_spider` → `output/...csv`) then a separate importer loads it. The cleanest spider template; the pipeline needs a new Supabase sink instead of CSV. Note `settings.py` ships `ROBOTSTXT_OBEY = False` — the outreach project overrides this to `True`.
- `scripts/backfill_rankings_full.py:154-180` — canonical Supabase batch loop (`batch_size`, `.insert()/.upsert(...).execute()`, `failed_batches` retry-once). The model for the sink + status-update writes.

### Reusable Utilities
- `src/etl/bulk_ops.py:67` — `bulk_update_last_scraped_at(supabase, updates, chunk_size)` + `:33` `call_rpc_with_fallback`: chunked writes that halve chunk size on HTTP 413. Use for the status-promotion updates against `outreach_targets`.
- `src/scrapers/_http.py` — `retry_session_get`, `RateLimitedError` (rate-limit-aware HTTP).
- `config/settings.py:16-17` — repo-rooted `load_dotenv(.env.local)` then `load_dotenv(.env)`; exports `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.

### Convention Anchors
- **Secrets:** `ZENROWS_API_KEY`, `ZENROWS_PREMIUM_PROXY` via `os.getenv` at scraper `__init__` (`gotsport.py:318,324`); ZenRows param key is `apikey`. New `HUNTER_API_KEY` / `NEVERBOUNCE_API_KEY` follow the same `os.getenv` pattern in `C:/PitchRank/.env`.
- **Env loading in scripts:** inline `load_dotenv(.env.local)` + `load_dotenv(.env)` with `sys.path.insert` (`scripts/backfill_team_leagues.py:29-33`, `scripts/normalize_team_names.py:34-35`).
- **Supabase write client:** ad-hoc `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)` (`backfill_rankings_full.py:19,42`); service-role key required (RLS service-role-only on `outreach_targets`).
- **Migrations:** `supabase/migrations/YYYYMMDDHHMMSS_*.sql`, RLS + `service_role` policy, `SET search_path=''` on any function (see `20260615000000_create_outreach_targets.sql`).
- **Personalization storage today:** `outreach_targets` has `notes TEXT`; no JSONB column yet. Lifecycle vocab from the migration comments: `status: queued -> verified -> sent -> replied -> linked | declined`; `verification_status` holds the verifier result.

### Gaps (greenfield — no prior art)
- **Email finding / enrichment / address verification:** none. Only transactional Resend in `frontend/lib/email/` (TypeScript, send-only). Hunter + NeverBounce clients are new.
- **Per-batch quality-rate gate:** no analog; build the compute-rate-then-gate logic new.

### Proposed Alignment
Fork `scrapers/modular11_scraper/` as the spider template; swap the CSV pipeline for a Supabase sink built on the `backfill_rankings_full.py` insert loop + `bulk_ops.py` chunked helpers; reuse `_http.py`'s retry layer; keep a new ZenRows helper **local** to `outreach_scraper/` (do NOT refactor `gotsport.py`). DB writes use `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)` + the script env-loader convention. Hunter client, NeverBounce client, and the invalid-rate gate are new standalone modules, keys behind `os.getenv`. All cited anchors verified present on `origin/main`; staged somsports files are working-tree-only and excluded.

## Implementation Steps

1. **Migration: personalization, dedupe safety net, lifecycle** (`supabase/migrations/<timestamp>_extend_outreach_targets_for_list_build.sql`, mirroring `20260615000000_create_outreach_targets.sql`)
   - `ADD COLUMN IF NOT EXISTS source_domain TEXT` — the org's domain; Hunter enrichment input + the Python-side dedupe key.
   - `ADD COLUMN IF NOT EXISTS personalization JSONB NOT NULL DEFAULT '{}'::jsonb` — scraped tokens (state, league mix, a team/standing) for shell 3.
   - `CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_targets_contact ON outreach_targets (lower(contact)) WHERE contact IS NOT NULL;` — the DB safety net that guarantees no two targets share an email (primary dedupe is Python-side, Step 4).
   - Extend the `status` `COMMENT ON COLUMN` to `queued -> verified | held` for the list-build (`sent -> replied -> linked | declined` follow `verified` in shell 3; `held` = invalid/catch-all/no-email/gate-failed).
   - Apply via Supabase MCP `apply_migration` against project `pfkrhmprwxtghtpinrot`. `ADD COLUMN ... NOT NULL DEFAULT` is safe on existing rows. No new RPC, no `batch_id`, no partial org index — those belong to a concurrent design this pipeline doesn't need.

2. **Scaffold the contact-harvesting Scrapy project** (`scrapers/outreach_scraper/`)
   - Fork `scrapers/modular11_scraper/`: `scrapy.cfg`, `outreach_scraper/{settings,items,pipelines}.py`, `spiders/`.
   - `items.py`: an `OutreachTargetItem` whose fields map 1:1 to the table — `segment`, `org`, `contact` (nullable until enriched), `source_domain`, `link_url` (the public source page), `personalization` (dict: `state`, `league_mix`, a `team`/`standing` signal). No top-level `source_url`/`state` fields (`link_url` carries the page, `state` lives in `personalization.state`).
   - `settings.py`: `ROBOTSTXT_OBEY = True` — an **intentional override** of modular11's `ROBOTSTXT_OBEY = False` for this shell's compliance posture — plus `DOWNLOAD_DELAY`, `AUTOTHROTTLE_ENABLED`, a descriptive `USER_AGENT`.
   - `outreach_scraper/zenrows.py` `make_zenrows_request(url, **params)` modeled on the `gotsport.py:619` param shape (`apikey` from `ZENROWS_API_KEY`, `premium_proxy` from `ZENROWS_PREMIUM_PROXY`, `proxy_country="us"`). Lightweight sites can use `_http.py:retry_session_get` directly.

3. **Build config-driven spiders per segment**
   - Drive scraping from checked-in configs `scrapers/outreach_scraper/sources/<segment>.yaml` (per site: `org`, `source_domain`, `start_url`, contact-page pattern, CSS/XPath selectors for org/name/email/state/league signals). Keeps 50+ heterogeneous sites maintainable without bespoke spiders.
   - One generic spider per segment (`spiders/{associations,clubs,media,bloggers}.py`) loads its YAML, fetches each source (ZenRows helper or `retry_session_get`), and yields `OutreachTargetItem`s with `source_domain` set and personalization signals captured. Seed `associations.yaml` with the ~50 US Youth Soccer / US Club state associations; seed media/blogger YAMLs with known mastheads (SoccerWire, TopDrawer, SBNation desks). Scope to publicly-listed role inboxes (info@, DOC role addresses) and honor robots.txt.

4. **Supabase sink pipeline with Python-side dedupe** (`outreach_scraper/pipelines.py`)
   - In `open_spider`, build `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)` (inline `load_dotenv` convention) and load two in-memory dedupe sets from existing rows: the `(segment, source_domain, org)` keys and the `lower(contact)` emails already present. (The list is small — a single `select` is cheap.)
   - Per item: skip if its `(segment, source_domain, org)` is already in the set or its email (if present) is already known; otherwise add to the buffer and the sets. Batch-`insert` new rows (`backfill_rankings_full.py:154-180` loop shape) as `status='queued'`, `verification_status='unverified'`, with `segment`, `org`, `source_domain`, `link_url`, `personalization` populated (`contact` only if already found). The `uq_outreach_targets_contact` index backstops the in-memory set against any gap. Sequential runs make this race-free without DB-level claim machinery.

5. **Email enrichment module** (`src/outreach/enrich.py`)
   - `find_email(source_domain, full_name=None) -> tuple[str|None, float]` via Hunter Email Finder / Domain Search (`HUNTER_API_KEY` via `os.getenv`), wrapped in `_http.py:retry_session_get`.
   - `enrich_queued(limit)` selects `status='queued'` rows missing `contact` (resumable — already-enriched rows have `contact` set and are skipped), resolves emails, and writes `contact` + the Hunter confidence merged into `personalization` via **read-merge-write** (safe here because the runner is sequential — no concurrent writer to clobber). **Collision policy:** if writing `contact` raises a `uq_outreach_targets_contact` unique violation (two orgs share a role inbox), catch it and set that row to `status='held'` (the email is already tracked on another target) instead of crashing.

6. **Verification + gate** (`src/outreach/verify.py`)
   - `verify_email(email) -> str` via NeverBounce (`NEVERBOUNCE_API_KEY`; prefer the bulk-job API for the initial large list, single-check for incremental top-ups). Map → `verification_status`: `valid`→`valid`, `invalid`/disposable→`invalid`, `catchall`/`unknown`→`risky`.
   - `verify_and_gate(slice)` takes a slice of `status='queued'` rows (a `--limit` slice or a whole segment), verifies those still `verification_status='unverified'` (resumable — already-verified rows are skipped, so a crashed run never re-charges NeverBounce for them), then gates: hard-invalid fraction = `count(verification_status='invalid') / count(rows in the slice with a verification result)`, no-op on an empty slice (no divide-by-zero).
     - If invalid fraction ≤ ~2–3%: promote `valid` rows to `status='verified'`; move `risky`/no-email rows to `status='held'`.
     - If invalid fraction > ~2–3%: move the whole slice to `status='held'` and log it for cleaning; promote nothing.
   - `held` is terminal for the automated pipeline (re-runs select only `status='queued'`), so bad/unverifiable rows never loop.

7. **Orchestration runner** (`scripts/build_outreach_list.py`)
   - CLI (argparse `--segment`, `--limit`, `--dry-run`): trigger the segment's spider → `enrich.enrich_queued(limit)` → `verify.verify_and_gate(slice)` → report per-segment counts, the invalid fraction, and verified/held tallies. Inline `load_dotenv` + `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)`.
   - **Idempotent + resumable via status fields, run sequentially.** A crashed run is recovered simply by re-running: enrichment skips rows that already have `contact`, verification skips rows that already have a `verification_status`, and the gate finalizes once the slice is fully verified. No lease, heartbeat, or reaper. (Don't run two instances at once; if concurrency is ever needed, add a claim mechanism then.)

## Verification

- **Migration:** after `apply_migration`, `list_tables` (verbose) shows `source_domain` + `personalization` on `outreach_targets` and `uq_outreach_targets_contact` exists as a partial unique index; the `status` comment reads `queued -> verified | held`; an INSERT omitting `personalization` defaults to `{}`; RLS still service-role-only. (No `batch_id` column, no org partial index, no new RPC.)
- **Dedupe:** run the sink twice over the same scraped source and confirm one row results (Python-side set skips the repeat); attempt to `UPDATE` two rows to the same `lower(contact)` and confirm `uq_outreach_targets_contact` rejects the second.
- **Spider (single source):** run one spider against 1–2 known association sites (`--dry-run`); confirm items carry `org`, `source_domain`, `personalization` (state, league signal), and the sink writes `status='queued'`, `verification_status='unverified'`. Confirm `ROBOTSTXT_OBEY=True` + `DOWNLOAD_DELAY` honored.
- **Enrichment + merge + collision:** `find_email()` returns an email + confidence for a domain with a known role inbox; `HUNTER_API_KEY` missing fails loudly. After `enrich_queued`, the row's `personalization` retains scraped tokens AND gains `enrich_confidence` (read-merge-write didn't clobber). Force two batch rows to the same role inbox and confirm the loser goes to `held`, not a crash.
- **Verify + gate + resumability:** `verify_email()` maps a known-valid and known-invalid address correctly. A >3% hard-invalid slice → whole slice `held` (promotes nothing); a clean slice → only `valid` rows reach `verified`, `risky`/no-email → `held`. Empty slice no-ops (no divide-by-zero); the gate divides by rows actually verified (a 10-row slice with 1 invalid reads 10%). Kill the runner mid-verify, re-run, and confirm it resumes without re-charging NeverBounce for already-verified rows and finalizes correctly. `held` rows are not reprocessed.
- **Load + segmentation:** `SELECT segment, status, count(*) FROM outreach_targets GROUP BY 1,2` shows the four segments and the `queued/verified/held` distribution; only gate-passing `valid` rows sit at `verified`, with real verified emails.
- **Risk (surfaced at expansion):** scraping contact data has ToS/compliance considerations — scope to publicly-listed org/role inboxes, honor robots.txt; check NeverBounce bulk-job cost against list size before the first full run.

## Context Files

- `src/scrapers/gotsport.py` — the ZenRows request param shape (~line 619) to model the LOCAL helper on (do not refactor it).
- `src/scrapers/_http.py` — `retry_session_get` / `RateLimitedError`; reuse for scraping and vendor HTTP.
- `scrapers/modular11_scraper/` — the Scrapy project to fork: `settings.py` (note `ROBOTSTXT_OBEY=False` to override), `items.py`, `pipelines.py` (CSV sink to replace), `spiders/`.
- `scripts/backfill_rankings_full.py` — the Supabase batch insert/upsert loop (lines ~154-180) for the sink + status writes.
- `src/etl/bulk_ops.py` — chunked write helpers for the status-promotion updates.
- `config/settings.py` — env loading + `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (lines ~16-17).
- `scripts/normalize_team_names.py` — inline `load_dotenv` script convention (lines ~29-40).
- `supabase/migrations/20260615000000_create_outreach_targets.sql` — the target table + migration conventions to mirror for the new columns/index.
