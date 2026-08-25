# Improvements

Out-of-scope improvement opportunities captured during work sessions. Review periodically and pull items into active work when appropriate.

### Restructure middleware to cover API routes or audit self-contained auth

- **Category**: reliability
- **Where**: `frontend/middleware.ts:128`
- **Why**: Middleware excludes all /api paths. Premium-gated APIs must self-enforce auth, creating fragile dual-auth surface. `/api/chat` and `/api/create-team` have zero auth enforcement (confirmed 2026-04-13).
- **Noted**: 2026-03-26

### Deprecate national_power_score in favor of power_score_true

- **Category**: refactor
- **Where**: `src/rankings/data_adapter.py` (national_power_score derivation at lines ~614 and ~921), `src/etl/glicko_engine.py:1378`, `scripts/calculate_rankings.py:276`, `rankings_full` table, `rankings_view`, frontend API consumers
- **Why**: After PR #540, `national_power_score` is derived from `power_score_true` with a legacy fallback. The column is still actively written in 3+ places despite a DEPRECATED comment. Frontend types already mark it as `?: never`. Full removal requires migrating all write paths, updating DB migrations, and auditing ~15 consuming files.
- **Noted**: 2026-03-27

### Fix data leakage in ML training (temporal splitting)

- **Category**: reliability
- **Where**: `scripts/train_ml_match_predictor.py:79-123`, `src/predictions/ml_match_predictor.py:301`
- **Why**: Backtest fixed in PR #551 (temporal split + point-in-time snapshots via `prediction_feature_history`). Training script still uses current rankings snapshot as features for historical games and sklearn random train/test split. The `prediction_feature_history` infrastructure needed for the fix already exists but is not wired into the training pipeline.
- **Noted**: 2026-03-27 (updated 2026-04-13)
- **Status**: Backtest fully fixed. Training script still affected.

### Upgrade TypeScript 5→6

- **Category**: dx
- **Where**: `frontend/package.json`
- **Why**: TypeScript 6.0 released stable 2026-03-23. Project is on TypeScript 5.9.3. Large scope, needs separate PR.
- **Noted**: 2026-03-27 (updated 2026-04-13)
- **Status**: Now actionable — TS 6.0 is stable.

### Test coverage gaps (consolidated)

- **Category**: testing
- **Where**: Backend (`src/`, `scripts/`) and frontend (`frontend/app/api/`)
- **Why**: Significant test coverage gaps remain across the codebase. Progress has been made on ML pipeline, ETL, calculator, and payment routes, but critical API routes and utility modules remain untested.
- **Noted**: 2026-03-26 (consolidated 2026-04-13, updated 2026-04-13)
- **Checklist**:
  - [x] `layer13_predictive_adjustment.py` — `test_ml_layer13_sos_scaling.py` exists
  - [x] `data_adapter.py` — `test_data_adapter_predictive_priors.py` exists
  - [x] `handleCheckoutCompleted` — `route.test.ts` exists
  - [x] `_build_features`, `_aggregate_team_residuals`, `compute_rankings_with_ml` — tests in `test_glicko_sos_role.py` and `test_ml_layer13_sos_scaling.py`
  - [x] ETL pipeline, scrapers — tests in `test_enhanced_pipeline.py`, `test_glicko_full_pipeline.py`, `test_scrape_games.py`
  - [x] `calculator.py` — tests in `test_glicko_sos_role.py` and `test_same_age_evidence_gates.py`
  - [x] `game_matcher` — tests in `test_game_matcher.py`
  - [x] `validators` — tests in `test_enhanced_pipeline.py` and `test_same_age_evidence_gates.py`
  - [ ] `agent-webhook` route (295 lines, state machine) — zero tests
  - [ ] `team-merge` route (272 lines, 3 methods) — zero tests
  - [ ] `link-opponent` route (353 lines, complex backfill) — zero tests
  - [ ] `requireAdmin` guard — used by 10+ routes, no dedicated tests
  - [ ] Stripe portal/sync routes — zero tests
  - [ ] `MergeResolver` (290 lines) — zero tests
  - [ ] Frontend `utils.ts` (138 lines) — zero tests
  - [ ] `confidenceEngine.ts` — zero tests
  - [ ] `shared.py` (rankings module) — zero tests
  - [ ] `insights engine` (frontend components) — zero tests
  - [ ] `predictMatch` calibrated draw-override branch (`matchPredictor.ts:1294-1297`) — only fires for u13/u15 ages per `heuristic_outcome_calibration.json`; existing tests use 14B (U12) so it's never exercised. Need a u13 near-symmetric test that awaits `warmMatchPredictorCalibration()` and verifies override fires when `rawDrawProbability >= drawOverrideThreshold && rawWinGap < draw_override_max_win_gap`. Surfaced 2026-04-29.

### Vectorize compute_game_explainability inner loop

- **Category**: performance
- **Where**: `src/etl/glicko_engine.py` `compute_game_explainability()` inner per-game loop
- **Why**: The scalar Python loop over each team's games (~15K iterations per cohort) could be vectorized with NumPy for 5-10x speedup. The non-cross-age path (majority case) is pure math suitable for array ops. The sibling `derive_offense_defense` already demonstrates the vectorized pattern.
- **Noted**: 2026-04-01

### Consolidate duplicated code patterns (Q-5, Q-7)

- **Category**: refactor
- **Where**: Q-5: `_fuzzy_match_team`/`_create_new_*_team`/`_match_team` in 5 provider matchers in `src/models/` (~80 lines each; TGS+SincSports are 95% identical). Q-7: watchlist fallback in 3 route files (`frontend/app/api/watchlist/{add,init,remove}/route.ts`).
- **Why**: Two cross-file duplication issues. Q-5 is highest impact (~300+ lines across 5 files).
- **Noted**: 2026-04-07 (updated 2026-04-13 — Q-6 removed as resolved; updated 2026-05-07 — Q-3 removed as resolved: `sigmoid_zscore_normalize()` helper at `glicko_engine.py:843` and `v53e.py:427` inline is intentional hybrid blend)

### Replace in-memory rate limiter with external store

- **Category**: reliability
- **Where**: `frontend/lib/api/rateLimit.ts`
- **Why**: In-memory Map grows unbounded and is ineffective on serverless (Vercel) where each invocation may get a fresh instance. Actively used by 3 routes: `newsletter`, `match-prediction`, `reports/team-card`. Replace with Upstash Redis or similar for production rate limiting.
- **Noted**: 2026-04-07

### Audit P2 code quality refactors (Q-8, Q-9, Q-10)

- **Category**: refactor
- **Where**: Q-8: `_determine_result` in 4 scrapers (gotsport, sincsports, surfsports, template). Q-9: `_init_http_session()` in 5 scrapers (gotsport, gotsport_event, sincsports, surfsports, template). Q-10: TEAM_COLORS drift — `game_matcher.py` has 16 colors (set), `team_name_utils.py` has 19 (frozenset, includes royal/crimson/teal).
- **Why**: Three P2 quality findings involving duplicated logic and drifted constants. Lower priority than Q-5/Q-7 but contribute to maintenance burden. (Q-11, Q-12, Q-13, Q-14, Q-15 resolved as of 2026-04-13.)
- **Noted**: 2026-04-07 (updated 2026-04-13 — Q-11 through Q-15 removed as resolved)
- **Status (2026-05-07 audit)**: All three still valid. Q-8: 4 scrapers; Q-9: 6 occurrences across 5 scrapers (sincsports has 2 — see also separate `_sincsports_http` extraction item); Q-10: still 16 vs 19 colors.

### Add reverse-sync for orphaned Stripe customers

- **Category**: reliability
- **Where**: `scripts/reconcile_stripe_subscriptions.py` or new script
- **Why**: If the anonymous checkout webhook fails (e.g., Supabase down during user creation), the user pays in Stripe but has no `stripe_customer_id` in DB. Current reconciliation only queries users WITH `stripe_customer_id`, so these orphans are invisible. A reverse-sync would query all active Stripe subscriptions and check for missing DB links.
- **Noted**: 2026-04-10

### Add user_id column to report_card_leads for authenticated user tracking

- **Category**: feature
- **Where**: `supabase/migrations/`, `frontend/app/api/reports/team-card/route.ts`
- **Why**: The spec requires `optionalAuth` on `/api/reports/team-card` to track authenticated users, but `report_card_leads` has no `user_id` column. Add `ALTER TABLE report_card_leads ADD COLUMN user_id UUID` migration, then wire `user?.id` into the insert payload to capture which authenticated users request report cards.
- **Noted**: 2026-04-13
- **Status (2026-05-07 audit)**: Migration `20260329000000_create_report_card_leads.sql` defines table without `user_id` (anonymous-by-design); route uses `optionalAuth()` correctly. Confirm whether spec intent is still to track authenticated users, or accept anonymous-only as the design.


### Consolidate duplicated matcher/scraper logic across TGS, Affinity WA, and PlayMetrics

- **Category**: refactor
- **Where**: `src/models/{tgs,affinity_wa,playmetrics}_matcher.py`, `scripts/scrape_{playmetrics_league,affinity_wa_tournament}.py`, `src/utils/team_utils.py`
- **Why**: Three drift points worth closing before a fourth provider is added: (1) Autocreate-on-miss is triplicated in the matchers — MD5 fallback for missing `provider_team_id`, pre-lookup on `(provider_id, provider_team_id)`, UUID insert, gender normalization, `23505` duplicate-key race recovery, and the surrounding `_match_team` override (base miss → autocreate → `_create_alias` with `direct_id`/`import` + `confidence=1.0` + `review_status=approved` → `{matched: True, created: True}`). Extract a `CreatingMatcherMixin` or `_auto_create_team_on_miss()` helper on the base `GameHistoryMatcher`. (2) HTTP retry helpers drift between scrapers (`_post` in PlayMetrics: `1*(attempt+1)` backoff; `_fetch` in Affinity: `1+attempt`; neither jitters). Extract `src/utils/http_retry.py` with a single idiom. (3) `"Male" if gender.upper() in ("M","MALE","BOYS","B") else "Female"` is inlined 3x. Add a single `normalize_gender_label()` helper in `src/utils/team_utils.py`.
- **Noted**: 2026-04-21

### Fix pipeline metric attribution for PlayMetrics (and likely AffinityWA) matchers

- **Category**: reliability
- **Where**: `src/etl/enhanced_pipeline.py` (metric-increment logic), `src/models/playmetrics_matcher.py`, `src/models/affinity_wa_matcher.py`
- **Why**: First PlayMetrics import reported `Teams created: 0` and `Auto-matched: 0` while actually creating 431 new teams and fuzzy-matching ~92 to existing TGS teams (verified via SQL counts on `teams` and `team_alias_map`). The matcher returns `{"matched": True, "created": True, "method": "direct_id", ...}` from the autocreate branch but the pipeline isn't crediting that to `teams_created`. Likely because the counter branches on `method` (treating `direct_id` as an existing-team match) rather than on the `created` flag. AffinityWA returns the same shape so it probably has the same misreport. Data integrity is fine; only the console/build_log summaries are wrong. Fix by having the pipeline read `metrics.teams_created` from the `created=True` signal, independent of `method`.
- **Noted**: 2026-04-21

### Make the Python birth-year filter dynamic so it stays in sync with SQL RPC

- **Category**: reliability
- **Where**: `scripts/scrape_games.py:352`
- **Why**: Hardcoded `birth_year in [2005, 2006, 2017, 2018, 2019]` will drift on 2027-01-01 from the SQL RPC `get_teams_to_scrape_limited` (which computes the same set via `EXTRACT(YEAR FROM NOW())`). Correct today; wrong next year. Either derive from `datetime.now().year` (`[yr-21, yr-20, yr-9, yr-8, yr-7]`) or drop the Python post-filter entirely now that the RPC enforces it. Flagged by review-correctness during /polish-code on scrape-games-perf; the plan's own tech-debt section also called this out.
- **Noted**: 2026-04-22

### Add integration tests for the three scrape-games RPCs

- **Category**: testing
- **Where**: `supabase/migrations/20260422*_*.sql`, a new `tests/integration/test_scrape_rpcs.py` or similar
- **Why**: `bulk_update_last_scraped_at`, `get_approved_aliases`, and `get_teams_to_scrape_limited` encode real business logic (hash sharding via `hashtext() % p_shard_count`, dynamic birth-year exclusion, NULLS-FIRST priority order, covering partial index) that Python `FakeSupabase` tests cannot verify. A migration-level test against real Postgres (pytest-postgres or a disposable Supabase local instance) would verify: (a) 5-shard disjointness sums to full set, no duplicates; (b) birth-year filter element-parity with the Python post-filter; (c) NULLS-FIRST ordering preserved; (d) `bulk_update_last_scraped_at` returns correct rowcount when some team_id_master values miss; (e) covering partial index is actually picked by the planner. Noted from /polish-code /review-test-coverage on scrape-games-perf.
- **Noted**: 2026-04-22

### Add explicit `REVOKE EXECUTE FROM PUBLIC, anon, authenticated` to service-role RPCs

- **Category**: reliability
- **Where**: `supabase/migrations/20260422000000_*.sql`, `20260422000001_*.sql`, `20260422000002_*.sql` (and retroactively on earlier service-role-only RPCs for consistency)
- **Why**: The new RPCs rely on the Supabase platform default (which revokes EXECUTE from `anon`/`authenticated`) rather than stating the access posture in the migration. With `SECURITY INVOKER` + RLS, there is no exploit path today, but an explicit REVOKE makes the grant-level intent auditable in the migration file itself and hardens against future Supabase platform default changes. Flagged by review-security on scrape-games-perf as P3 hygiene.
- **Noted**: 2026-04-22
- **Status (2026-05-07 audit)**: All 3 migration headers state "service_role-only RPC; no GRANT needed", suggesting REVOKE omission is intentional. Decide: keep platform-default reliance (close item) or add explicit REVOKE for auditability (hygiene-only).

### Consolidate duplicated `STATE_CODE_TO_NAME` mapping into `src/utils/us_states.py`

- **Category**: refactor
- **Where**: `scripts/backfill_state_from_state_code.py:28-80`, `scripts/backfill_missing_state_codes.py:35-87`, `scripts/match_state_from_club.py:37+`, `scripts/match_missing_state_codes.py:41+`, `scripts/update_single_team_state.py:28+`
- **Why**: The 50-state postal-code → full-name dict is duplicated across 5 scripts with no shared source. Some copies include DC, others don't, showing real drift risk. The SincSports discovery plan (`.turbo/plans/sincsports-team-discovery.md`) extracts the mapping to a new `src/utils/us_states.py` for the new scraper only (scope control). Once that lands, sweep the 5 existing scripts to import from the shared module — one commit per script for easy review, no functional change. Every future change to state handling (territories, DC normalization, etc.) currently requires 5 parallel edits.
- **Noted**: 2026-04-23
- **Status (2026-05-07 audit)**: `src/utils/us_states.py` now exists; `discover_sincsports_teams.py:57` migrated. The 5 older scripts still inline STATE_CODE_TO_NAME (consciously deferred per us_states.py:13 header). 5 of 6 callers pending.

### Make `match_state_from_club.py:617` UPDATE write-time monotonic

- **Category**: reliability
- **Where**: `scripts/match_state_from_club.py:617` (invoked by `.github/workflows/data-hygiene-weekly.yml` Step 2)
- **Why**: The UPDATE uses `.in_("team_id_master", batch)` with no `state_code IS NULL` re-assertion at write time; the batch is built from a stale snapshot at line 173. Any concurrent process that writes `state_code` between the snapshot and the UPDATE gets its authoritative value overwritten by the club-inferred inference. Real concrete risk: the SincSports discovery workflow writes authoritative `state_code` from explicit filter inputs; a concurrent hygiene run silently overwrites with a guess. One-line fix: add `.is_("state_code", "null")` to the UPDATE filter. Backward-compat for the intended use case (NULL rows are what the script targets). **Deployment blocker** for automating discovery on a schedule — until this lands, discovery and hygiene must be manually serialized (discovery workflow has a best-effort pre-flight `gh run list` check but can't prevent a hygiene run that starts mid-discovery).
- **Noted**: 2026-04-23

### Extract shared `_init_http_session` between SincSports scrapers

- **Category**: refactor
- **Where**: `src/scrapers/sincsports.py:85-112`, `src/scrapers/sincsports_clubs.py:_init_http_session`
- **Why**: The new discovery scraper's `_init_http_session` is byte-identical to the existing event scraper's: same `HTTPAdapter(pool_connections=10, pool_maxsize=10)`, same `Retry(total=3, backoff_factor=0.5, status_forcelist=[500,502,503,504], allowed_methods=["GET","HEAD"])`, same browser UA + headers block. The clubs scraper only adds docstring prose. Next UA bump or retry-policy tweak will silently drift between the two. Move to `src/scrapers/_sincsports_http.py` exposing `build_sincsports_session()` and import from both.
- **Noted**: 2026-04-24

### Consolidate Supabase / provider / alias-pre-check boilerplate across driver scripts

- **Category**: refactor
- **Where**: `scripts/discover_sincsports_teams.py` (load_dotenv block at :65-69, `ensure_provider_exists` at :87-102, `bulk_existing_aliases` at :280-298), `scripts/extract_and_import_tgs_teams.py:39-44,144-161,296-300`, `scripts/import_sincsports_teams.py:47-68`
- **Why**: Three recurring blocks are now cloned across 3+ driver scripts: (1) the `.env.local`→`.env` fallback loader, (2) the 100-row batched `team_alias_map.in_()` pre-check, (3) `ensure_provider_exists` (the new discovery driver even has an inline comment flagging it as a "Synchronous copy of scripts/import_sincsports_teams.py::ensure_provider_exists"). The TGS and SincSports-discovery drivers also silently differ on Supabase key fallback (TGS reads only `SUPABASE_SERVICE_ROLE_KEY`; discovery accepts either). Extract to `src/utils/provider_bootstrap.py` exposing `load_env()`, `ensure_provider(supabase, code, name, base_url)`, `bulk_existing_aliases(supabase, provider_id, ids)`. One cleanup commit per caller for easy review.
- **Noted**: 2026-04-24

### Add driver-level unit tests for SincSports discovery classification, resume gate, and enrich batching

- **Category**: testing
- **Where**: `scripts/discover_sincsports_teams.py` — bucket classifier (`:543-570`), `load_resume_artifacts` + mode/fingerprint/integrity gates (`:198-234`, `:393-420`), `enrich_state_codes` grouping + chunking (`:288-325`)
- **Why**: The 596-line driver has zero unit tests despite branch-heavy pure logic. The scraper + matcher extensions are well-covered (37 tests), but the driver's classification (5 buckets + unclassified `else`), resume gating (mode / scope-fingerprint / integrity), and state-code enrichment (51 buckets × 100-row chunking with monotonic `.is_("state_code", "null")`) only get exercised by the live dry-run today. A silent regression in any of these would corrupt a 1,020-combo run. Mock `supabase` + `scraper` and add a small targeted suite.
- **Noted**: 2026-04-24

### SincSports discovery workflow blocked on GitHub-hosted runners

- **Category**: reliability
- **Where**: `.github/workflows/sincsports-team-discovery.yml`, `src/scrapers/sincsports_clubs.py::_validate_response_shape`
- **Why**: The ubuntu-latest runner IP range gets a 29 MB non-envelope response from `sicclubs.aspx` (vs. the expected ~100 KB-700 KB EO callback CDATA from residential IPs). Observed on PR #663 first live GHA invocation with WI/u14/female (2026-04-24). The scraper correctly treats the malformed response as a shape-fail, hits the 3-strike block threshold, and aborts with `CaptchaOrBlockError("blocked")`. No regression — the discovery workflow is simply unusable from GHA today. Operator workaround: run the driver locally (residential IP), which works cleanly. Three long-term options: (1) route the scraper through a residential-IP proxy (ScraperAPI / Bright Data, cost per run); (2) self-hosted runner on a residential connection; (3) script a Playwright warm-up step inside the workflow to pre-acquire cookies before the requests-level scrape. Until then, the workflow stays in-repo for the GHA ergonomics (pre-flight hygiene check, artifact upload, permissions) but documented as operator-local-only in the workflow file's top comment.
- **Noted**: 2026-04-24

### [HIGH PRIORITY] SincSports re-scrape path breaks after team merges

- **Category**: reliability
- **Where**: `scripts/scrape_games.py` (sources teams via `teams.provider_id = sincsports`), `src/utils/merge_resolver.py`, `supabase/migrations/20251230000001_fix_merge_idempotency.sql::execute_team_merge`
- **Why**: `scrape_games.py --provider sincsports` queries the `teams` table filtering on `provider_id = sincsports`. When `find_fuzzy_duplicate_teams.py` (or the weekly `data-hygiene-weekly.yml` Step 5) merges a SincSports-originated team into a canonical GotSport team, the canonical row's `provider_id` stays `gotsport`. The merged team's SincSports alias lives in `team_alias_map` pointing to the canonical `team_id_master`, but the scraper driver never looks at `team_alias_map` — so future `--provider sincsports` invocations silently skip every merged team. Concrete scope from the 2026-04-24 u14 Female full-grid discovery: ~666 teams `fuzzy_auto_linked` at run time, plus another ~5-8 hygiene merges on Tuesdays. All of them lose their SincSports re-scrape path after merge. GotSport's weekly cron still covers their GotSport games, but SincSports-only events (regional tournaments, certain leagues) go un-scraped going forward. **Fix (~1-3 hours)**: write `scripts/scrape_sincsports_games_via_aliases.py` that sources teams from `team_alias_map WHERE provider_id = sincsports AND match_method = direct_id` joined to `teams` for `last_scraped_at`, then runs the same scrape loop as `scrape_games.py`. Provider-agnostic, safe alongside existing crons. Longer-term: refactor `scrape_games.py` to always query via `team_alias_map`, deprecating the `teams.provider_id` sourcing path — that's the root-cause fix but heavier. Flagged by operator 2026-04-24 immediately after the u14 Female full-grid run as "super super important to take care of asap."
- **Noted**: 2026-04-24

### [HIGH PRIORITY] import_games_enhanced.py drops records silently when ingesting tournament-schedule data

- **Category**: reliability
- **Where**: `scripts/import_games_enhanced.py`, `src/etl/enhanced_pipeline.py` (especially around `_check_duplicates` and the master-id-regenerated `game_uid` recheck at line ~485)
- **Why**: The pipeline reports four buckets in IMPORT_RESULT (`accepted`, `duplicates_skipped`, `duplicates_found`, `quarantined`). Validated 2026-04-25 against Puri Cup schedule.aspx ingest: 882 records processed → 442 dup, 0 accepted, 0 quarantined, 0 duplicates_found. **440 records vanished into an unreported 5th bucket.** Plus, because `game_uid` is symmetric (sorted team IDs), per-team-perspective JSONL emits two records per physical game that collide within a single batch, accounting for the 442 dup. Net: ~219 genuinely-new schedule.aspx games for Puri Cup didn't land. Scope: every tournament we scrape via `scripts/scrape_sincsports_tournament_schedule.py` will under-import until this is fixed. Diagnostic path: (1) feed 3 known-new games through the importer in isolation, query `build_logs` table for their disposition, identify the silent filter; (2) decide whether the scraper-side emit shape should change (one record per game instead of H+A perspectives) or the importer should accept a non-perspective shape; (3) handle master-id `game_uid` overlap with prior per-team imports — likely UPDATE-on-match for richer schedule fields (clean scores, division name, game number) rather than skip. Estimated 1-2 hours diagnostic + 30 min fix on each side. Validation: re-ingest Puri Cup, expect ~219 new games inserted on top of the existing 224.
- **Noted**: 2026-04-25
- **Status (2026-05-07 audit)**: Per build_logs query 2026-04-29, all 9 internal counters DO sum (drift=0). The "5th drop" is `failed_games_count` already in IMPORT_RESULT JSON (line 636) but hidden from rich-console summary at `enhanced_pipeline.py:2395-2454` — surface it in `print_modular11_summary()`. Downscoped from data-loss to console-UX fix; symmetric H+A collision still warrants validation.

### Auto GotSport Event Scrape never re-scrapes events after first capture

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/scrape_new_gotsport_events.py:822` (`excluded_event_ids = scraped_event_ids | blocked_event_ids`) + `data/raw/scraped_events.json`
- **Why**: `scraped_events.json` is a permanent allow-list. Once an event_id is scraped once, the cron auto-scrape (Mon + Thu) never returns to it. Original design assumed short-lived tournaments; long-running league/season events (NPL/CCL/ECNL season brackets running Feb–May) get discovered once when registered, then continuously add played games over months that the cron never picks up. Today only manual `Scrape Specific GotSport Event` re-runs catch them. Fix: add a stale-window re-scrape policy — re-include event_ids whose `last_scraped_at > 7 days` AND `event_end_date` is in the future or recent past. Complements the per-team schedule walk fix in PR #703 (which solves the page-coverage gap; this is the discovery-side gap).
- **Noted**: 2026-04-30

### Bump `lookback_days` default for Scrape Specific GotSport Event workflow

- **Type**: direct
- **Category**: dx
- **Where**: `.github/workflows/scrape-specific-event.yml:13` (input default `'30'`) + `scripts/scrape_specific_event.py:246` (argparse default `30`)
- **Why**: Filter applied at `src/scrapers/gotsport.py:2287-2290` drops `game_date < (today − N)` post-parse. For manual runs against season-long events (now the dominant use case after PR #703's per-team walk surfaces full history), 30d silently drops most of the season — confirmed on event 51028 (games back to Feb 15; 30d run only captured Apr 4 onward). Doesn't reduce HTTP work either, since per-team page is fetched whole then filtered. Bump default to 365 in both places, OR treat `0` as "no filter" and switch the workflow default to 0. Don't touch the auto-scrape default (different script).
- **Noted**: 2026-04-30


### canonicalize_age_group slash branch contradicts the older-cohort business rule

- **Type**: plan
- **Category**: reliability
- **Where**: `src/utils/team_name_utils.py:503-512` (logic), `:443` (docstring example), `:453-456` (rationale comment)
- **Why**: Slash dual-age branch uses `max(y1, y2)` for 2-digit slash tokens like `'10/11`, picking the YOUNGER birth year (→ u15 in 2025-2026). PR #711 just merged the older-cohort fix into `scripts/fix_team_age_groups.py` and `scripts/normalize_team_names.py` per the PitchRank business rule (Dallas, 2026-05-01): dual-age teams classify as the OLDER cohort — older birth year for year pairs, higher U-age for U-age pairs. The canonical helper still has the inverted logic. Low blast radius today (helper takes single fullmatch token, narrow scope vs. the scripts' free-form parsing) but any caller that flows slash 2-digit tokens silently gets the wrong cohort. Fix: flip `max` → `min` on `:508`, update docstring example `'10/11 → u15` to `→ u16`, rewrite rationale comment to state older-cohort rule. Audit callers of `canonicalize_age_group` and `_RE_SLASH_DUAL` first to confirm no downstream depends on younger-cohort behavior. Add tests for both 2-digit (`'10/11`, `15/16U`) and 4-digit (`2010/2011`) slash forms.
- **Noted**: 2026-05-01


### Matcher autocreate writes ignore pipeline dry_run

- **Type**: plan
- **Category**: reliability
- **Where**: `src/models/game_matcher.py` (base `_create_alias`), `src/models/playmetrics_matcher.py`, `src/models/tgs_matcher.py`, `src/models/affinity_wa_matcher.py`, `src/models/sincsports_matcher.py`, `src/models/modular11_matcher.py` (each subclass `_create_new_*_team`), `src/etl/enhanced_pipeline.py` (`_ensure_initialized`)
- **Why**: `EnhancedETLPipeline.dry_run` only gates the games-table insert. Base `_create_alias` writes to `team_alias_map` and each subclass `_create_new_*_team` writes to `teams` unconditionally. Confirmed live 2026-05-01: `import_games_enhanced.py --dry-run` for `playmetrics_tournament` provider silently inserted 193 `teams` + 262 `team_alias_map` rows into production despite the flag — required manual SQL DELETE cleanup. Affects all 5 matcher subclasses. Fix: add `dry_run: bool = False` to `GameHistoryMatcher.__init__` (partially started — base accepts kwarg, but `_create_alias` and `_create_new_*_team` don't gate yet); gate all writes; return a deterministic stub UUID (`uuid.uuid5` over `(team_name, age, gender, provider_team_id)`) without inserting; thread `dry_run=self.dry_run` from `EnhancedETLPipeline._ensure_initialized()` to all 5 matcher constructors. Until landed, treat `import_games_enhanced.py --dry-run` as unsafe — use a standalone analytics dryrun that monkey-patches `_create_new_*_team` and `_create_alias` post-construction for safe simulation.
- **Noted**: 2026-05-01
- **Status (2026-05-07 audit)**: PR #729 (origin/main `136e292c0`) added dry_run gating for playmetrics path. Verify scope — base `_create_alias` and the other 4 subclasses (tgs, affinity_wa, sincsports, modular11) likely still write unconditionally.
- **Status (2026-08-19)**: Hit again in production. A `--dry-run` TGS import of event 4125 created 118 `teams` and 117 `team_match_review_queue` rows while printing "Teams created: 0" and "no changes were made"; the queue rows were deleted, the teams were kept since the authorized real import would have created them. Root cause was two-part and the same shape everywhere: `_ensure_initialized` never passed `dry_run` to `TGSGameMatcher`, so the base class's *existing* gates on `_create_alias` and the review-queue insert saw `dry_run=False`, and `tgs_matcher._create_new_tgs_team` had no gate of its own. **Fixed for tgs in PR #974** (constructor threads the flag, insert is gated, 5 regression tests in `tests/unit/test_tgs_matcher_dry_run.py` incl. one asserting the pipeline wiring). **Still open: `sincsports` and `affinity_wa`** — both constructed without `dry_run` in `_ensure_initialized`, both with unconditional inserts (`sincsports_matcher.py:741`, `affinity_wa_matcher.py:396`). modular11 and playmetrics already receive the flag. The stub-UUID idea above was not adopted: the TGS fix returns the real generated UUID unwritten, which keeps downstream match reporting accurate.


### Add `.vercel/` to repo-root `.gitignore`

- **Type**: direct
- **Category**: dx
- **Where**: `.gitignore` (repo root)
- **Why**: The Vercel CLI generates a `.vercel/` link directory containing project IDs and a deployment-protection bypass token. Currently untracked but un-ignored, so a careless `git add -A` would leak the token. Discovered while running `vercel curl` against preview deployments during /finalize on PR #722.
- **Noted**: 2026-05-05


### Token-aware truncation for canvas infographic renderers

- **Type**: plan
- **Category**: readability
- **Where**: `frontend/components/infographics/{canvasRenderer,headToHeadRenderer,rankingMoversRenderer,stateChampionsRenderer,teamSpotlightRenderer}.ts` — the `while (ctx.measureText(name).width > max && name.length > N) { name = name.slice(0, -4) + '...' }` block in each
- **Why**: After PR #722 + the composeTeamDisplay rollout PR, all 5 renderers truncate the post-`composeTeamDisplay(team).toUpperCase()` string. Composition deliberately puts the differentiator at the end (e.g., `Carolina Rapids ECNL White`); end-anchored slice-by-4 truncation removes the squad-distinguishing tail first, collapsing distinct teams into `{club abbrev}…` on tight platforms (Instagram landscape rows in BiggestMovers/rankingMovers; small State Champions cards). Two adjacent fallers can lose their distinction simultaneously and become indistinguishable. Fix: token-aware truncator that drops `formatLeague(league)` before `formatDistinction(distinction)`, or drops common-prefix tokens before differentiator tokens. Pre-existing pattern from PR #722's renderer truncation; flagged 2026-05-05 during /polish-code on the rollout PR.
- **Noted**: 2026-05-05


### UnknownOpponentLink subline duplicates club_name visible in composed line above

- **Type**: plan
- **Category**: readability
- **Where**: `frontend/components/UnknownOpponentLink.tsx` (search dropdown row :549-552 + selected-team confirmation panel :677-679); same pattern likely exists in `RankingsTable.tsx` after PR #722
- **Why**: After the composeTeamDisplay rollout, the composed top line begins with `abbreviateClubName(club_name)`, and the muted subline immediately below renders raw `team.club_name` again — e.g. `Phoenix Rising SC ECNL White` / `Phoenix Rising Soccer Club • AZ • U14 Boys`. Visually duplicates club identity in two forms. PR #722 introduced this for the rankings table by design ("keep club identity and region visible at a glance"), but in a search dropdown row where vertical space matters more, the redundancy is more pronounced. Fix: drop `club_name` from subline in UnknownOpponentLink dropdown + selected-team confirmation; keep state/age/gender. Consider mirroring in rankings table for consistency. Pre-existing PR #722 design choice; flagged 2026-05-05 during /polish-code on the rollout PR. **Partially addressed 2026-08-18** (branch fix/search-result-labels): both sublines now delegate state/age/gender to composeTeamMeta, fixing a literal U0 and a double bullet in the confirmation panel. The club_name redundancy this entry describes is unchanged and still open.
- **Noted**: 2026-05-05


### Finish the composeTeamDisplay unit tests (now partially covered)

- **Type**: plan
- **Category**: testing
- **Where**: new `frontend/lib/utils.test.ts` (or co-located test file)
- **Why**: `composeTeamDisplay` was introduced in PR #722 and has been adopted in the rankings table, GlobalSearch, ComparePanel, TeamSelector, RecentMovers, and (via the rollout PR shipping today) 5 infographic preview components, 5 canvas renderer scripts, and UnknownOpponentLink — but has never had a unit test. Verified by grep across `frontend/**/*.test.*` and `git log -S 'composeTeamDisplay'` across all branches: zero results. Discrete branches to cover: (a) modular11 short-circuit (`has_modular11_alias === true` returns raw `team_name`), (b) `club_name === null` fallback, (c) base composition `[abbreviateClubName, formatLeague, formatDistinction].join(' ')`, (d) `.filter(Boolean)` empty-string filtering when league/distinction are null, (e) `abbreviateClubName` regex replacements (Soccer/Football/Sports/Athletic Club, case-insensitive), (f) `formatLeague` table lookup + underscore-to-space fallback, (g) `formatDistinction` ordering (words reversed → numerals last), roman→arabic, UPPERCASE_HINTS preservation. Helper is pure + deterministic + critical to rendered correctness across ~16 surfaces. Flagged 2026-05-05 during /polish-code on the rollout PR; rollout's "no new tests" stance was defensible (mechanical swap of an already-shipping helper) but the original plan rationale ("already unit-tested upstream") was factually incorrect. **Superseded in part 2026-08-18**: frontend/lib/utils.test.ts now covers (a) the modular11 short-circuit, (b) the club_name null fallback, (c) base composition, the leakage safety net, formatLeague, formatDistinction, the new includeAge option, and composeTeamMeta. Still uncovered: (e) abbreviateClubName regex replacements and formatDistinction UPPERCASE_HINTS preservation.
- **Noted**: 2026-05-05

### Add CI integration smoke test + parity/regression guard for ranking RPCs

- **Type**: plan
- **Category**: testing
- **Where**: new `tests/integration/test_ranking_rpcs.py` (or `tests/sql/`) + CI workflow gated on `supabase/migrations/*.sql` changes; `frontend/lib/utils.ts:219-251` (normalizeAgeGroup contract); `scripts/backfill_rankings_full.py:112` (storage-invariant watch item)
- **Why**: PR #722 shipped a `get_state_rankings` regression that threw `22P02` on every call ("Network connection" on every state page); the bug only surfaces at call time, so SQL-syntax migration tests didn't catch it. A smoke test that exercises each ranking RPC across u10–u19, both genders, and ≥5 states would have failed CI before merge. This is the **second** time `get_state_rankings` regressed similarly (see also `feedback_check_all_rpc_fix_migrations.md`). Run via supabase-py against a `SUPABASE_TEST_URL` secret, assert non-error response + non-empty rows for known-populated cohorts. Hotfix landed in PR #724 / migration `20260505200000`. **Extended 2026-06-04 (migration `20260603000000_sargable_age_filter_rankings_rpcs`):** the sargable age-filter rewrite was proven byte-identical to the prior regex behavior only via a one-off EXCEPT parity diff + EXPLAIN in a session transcript — nothing in the repo encodes it. The new equality-list predicate silently depends on two invariants the test should also pin: (a) callers always pass `p_age` as a bare integer string via `normalizeAgeGroup` — the new `p_age::INTEGER` cast raises `22P02` on `'u12'`-style input that the old regex tolerated; (b) `rankings_full.age_group` is stored exclusively as lowercase `uNN` — non-canonical forms (`u14b`, `14-ECNL`, `U12`, `2014`) the old regex's 3rd arm matched are now silently dropped (fails closed). The committed test should encode a per-RPC EXCEPT parity check and assert the 18→19 fold divergence (national list/count + state count fold; state list does not). Project currently has **no SQL test harness**, so this was out of scope for the timeout-fix PR.
- **Noted**: 2026-05-05 (extended 2026-06-04 with sargable-rewrite parity-guard + age_group storage/input invariants)

### Fix `fetchModular11TeamIds` silent empty-Set under anon RLS — MLS Next short-circuit no-op in global search

- **Type**: investigate
- **Category**: reliability
- **Where**: `frontend/hooks/useTeamSearch.ts` (`fetchModular11TeamIds`, lines ~24-46); Supabase RLS on `team_alias_map` + `providers`
- **Why**: PR #722 added a `has_modular11_alias` short-circuit in `composeTeamDisplay` so MLS Next teams render their clean raw `team_name`. The flag is populated by `fetchModular11TeamIds()` querying `team_alias_map` joined to `providers!inner` filtered by `code = 'modular11'`. Under the anon Supabase key, this returns an empty Set — verified live during PR #726 testing: `Phoenix Rising AD` search showed MLS Next teams as `Phoenix Rising FC MLS Next AD AD` instead of clean `Phoenix Rising FC U13 AD`. ~14k MLS Next teams affected. No console warning fires (zero rows ≠ error), so the failure was invisible until manual UI verification. Likely RLS on `team_alias_map` and/or the embedded join blocking anon SELECT — service-role queries from Python confirm the data is present. Fix candidates: (a) grant anon SELECT on `team_alias_map` + `providers` (low risk, both reference data), or (b) move the modular11 lookup server-side and ship the flag in `useTeamSearch`'s payload (cleaner). Either way, also harden `fetchModular11TeamIds` to log a warning when the Set is empty so future regressions surface in the console. PR #726 (`70d9a097c`) mitigates the UX impact via the disambiguator subline but the short-circuit itself remains broken.
- **Noted**: 2026-05-06

### Parallelize watchlist bulk remove

- **Type**: direct
- **Category**: performance
- **Where**: `frontend/app/watchlist/page.tsx:182-185` (`removeTeams` callback)
- **Why**: `removeTeams` loops `await removeFromSupabaseWatchlist(id)` sequentially per ID. Selecting N teams and hitting Remove makes N round-trips back-to-back. Switch the loop to `Promise.all(teamIds.map(removeFromSupabaseWatchlist))` so the API calls fire in parallel. Bulk-delete UX feels slow because of this. Deferred from PR #774 session.
- **Noted**: 2026-05-14


### Persist watchlist filter + sort state to localStorage

- **Type**: direct
- **Category**: dx
- **Where**: `frontend/app/watchlist/page.tsx:47-50` (`filterAge`, `filterState`, `filterGender`, `sortBy` useState calls)
- **Why**: Dropdown filter values + sort key reset on every page load. Save the chosen values to localStorage keyed by user id and restore on mount so returning users keep their last-used view. Deferred from PR #774 session.
- **Noted**: 2026-05-14


### Show next-game on watchlist card

- **Type**: plan
- **Category**: feature
- **Where**: `frontend/app/api/watchlist/route.ts` (add upcoming game query) + `frontend/app/watchlist/page.tsx` (card UI)
- **Why**: Highest user-facing improvement for the Season Dashboard. For each watched team, pull the next scheduled game from `games` (where `game_date >= today` AND scores are null) and render "vs Lightning FC, Sat 11/15" on the card. The current card answers only "what happened" — next-game answers "what's next", which is the watchlist's actual purpose. Deferred from PR #774 session.
- **Noted**: 2026-05-14


### Wire ComparePanel to watchlist multi-select

- **Type**: plan
- **Category**: feature
- **Where**: `frontend/app/watchlist/page.tsx` (batch actions row near `removeSelected`); reuse `frontend/components/ComparePanel.tsx`
- **Why**: The ComparePanel component is already built. The watchlist already has a multi-select checkbox UX (`selectedIds`). Add a "Compare (N)" button next to Remove that opens the panel with the selected team IDs. Highest "feature ROI" because the heavy lifting already exists. Deferred from PR #774 session.
- **Noted**: 2026-05-14


### Inline insight badge on watchlist cards

- **Type**: plan
- **Category**: feature
- **Where**: `frontend/app/watchlist/page.tsx` (card body, near the stats grid)
- **Why**: API already returns `rank_change_7d` and `new_games_count`. Surface a one-line insight ("↑5 this week — biggest mover", "3 games in last 7 days", "Tournament winner") inline on the card so users don't have to click into the Insights modal to see meaningful changes at a glance. Deferred from PR #774 session.
- **Noted**: 2026-05-14


### Per-team notification preferences in watchlist UI

- **Type**: plan
- **Category**: feature
- **Where**: `frontend/app/watchlist/page.tsx` (card actions row); reuse `frontend/components/NotificationBell.tsx`
- **Why**: The NotificationBell exists on the team header but per-team preference management is one team at a time. The watchlist is the natural place to bulk-manage which teams trigger weekly digests / rank-change alerts. Deferred from PR #774 session.
- **Noted**: 2026-05-14


### Audit frontend `/api/*` routes for missing team_merge_map resolution

- **Type**: investigate
- **Category**: reliability
- **Where**: `frontend/app/api/**/route.ts` — any route that reads a user-stored `team_id_master` (watchlist_items, future favorites/saves, comparisons, etc.)
- **Why**: PR #774 found that `/api/watchlist` (read) and `/api/watchlist/remove` (write) both ignored `team_merge_map`, so deprecated team IDs in `watchlist_items` returned stale pre-merge data and Remove silently failed when the canonical ID was posted back. The team detail page at `app/teams/[id]/page.tsx:140-144` already resolves correctly via redirect, and the insights API was fixed previously (see `gotcha_insights_api_no_merge_map.md`). Sweep every remaining `/api/*` route plus server components for the same gap. When the third surface adds inline merge-resolution logic, extract a shared `resolveCanonicalTeamIds(ids: string[])` helper into `frontend/lib/` so the rule lives in one place. See [[architecture_frontend_merge_resolution]] for the read/write resolution pattern.
- **Noted**: 2026-05-14


### Make GotSport event-side scrape paths WAF-breaker-aware

- **Type**: plan
- **Category**: reliability
- **Where**: `src/scrapers/gotsport.py` — `_resolve_api_team_id_from_event_page` (~line 2096-2208), `extract_event_teams` (~line 1670-1740), `extract_event_teams_by_bracket` (~line 1820-1880)
- **Why**: PR `feat/gotsport-waf-circuit-breaker` (2026-05-18) scoped the CloudFront WAF breaker to `scrape_team_games` only. The three event-side methods above hit the same `system.gotsport.com/api/v1/*` host but silently convert CloudFront 403 to "team/event not found" or generic transient errors and drop the row — partial data loss instead of the clean abort the breaker provides. Defensive `except WAFBlockedError: raise` guards are already in place in two of the three methods. Wire `_is_cloudfront_waf_block(e.response)` checks + `_waf_breaker.trip(...)` calls into their HTTPError branches following the `scrape_team_games` pattern. Surfaced by codex peer review.
- **Noted**: 2026-05-18


### Investigate ~13K gotsport teams with successful scrapes but zero games in `games`

- **Type**: investigate
- **Category**: reliability
- **Where**: `src/etl/enhanced_pipeline.py`, `src/models/game_matcher.py`, `team_alias_map`, `quarantine_games`
- **Why**: 2026-05-19 deprecation candidate-detection found 13,215 gotsport `teams` rows with recent `last_scraped_at` (i.e., the scrape pipeline ran on them) but zero rows in `games` joined on their `team_id_master`. Eyeball sample showed real club teams ("SLSG MO B 2010 Aberdeen", "Broomfield SC 2010 Academy NPL", "2009 MLS NEXT", etc.) — not test data or dead IDs. Hypothesis: gotsport returns matches for these provider_team_ids, but the importer's team-matching pipeline fails to attribute them to the existing master, so games land in `quarantine_games` or under a different master. Triage: pick 3–5 candidate provider_team_ids, hit `system.gotsport.com/api/v1/teams/{id}/matches?past=true` via ZenRows MCP, trace where the returned games end up. This blocks any "is this team active?" criteria built on `games` table absence (see [[feedback-deprecation-criteria-gotcha]] in auto memory).
- **Noted**: 2026-05-19


### WAFBreaker doesn't propagate to outer drain loop — cascade-fails entire batch after first trip

- **Type**: direct
- **Category**: reliability
- **Where**: `src/scrapers/gotsport.py:114` (WAFBreaker) + `scripts/process_missing_games.py:501-514` (broad except) and `:516` (process_all loop)
- **Why**: When `WAFBlockedError` is raised on second WAF trip, the broad `except Exception` in `process_request` catches it and the outer `process_all` loop continues to the next request. Each subsequent request still hits the GotSport API, gets blocked, and is marked `failed`. Observed 2026-05-26 manual run at limit=150: 40 succeeded, 110 cascade-failed in sequence (~110 wasted API calls keeping the WAF counter pegged). PR #838 (limit=40) mitigates but doesn't fix — bug bites again if threshold drifts or priority-1 requests bunch up. Fix: catch `WAFBlockedError` explicitly in `process_all`, break the loop, leave remaining requests as `pending` (don't mark `failed` if they never fetched). ~10-line patch.
- **Noted**: 2026-05-26


### Add `--date` CLI flag to `enqueue_yesterday_games.py` for backfilling missed-cron days

- **Type**: direct
- **Category**: dx
- **Where**: `scripts/enqueue_yesterday_games.py:60` (hard-coded `date.today() - timedelta(days=1)`)
- **Why**: Script only handles "yesterday". When the daily cron fails (2026-05-24 + 2026-05-25 from the now-fixed RPC timeout), backfilling requires writing inline Python — no first-class way to enqueue an arbitrary historical date. Caught during May 23/24/25 backfill (~20 lines of inline Python that should have been `python scripts/enqueue_yesterday_games.py --date 2026-05-23`). Fix: add `--date YYYY-MM-DD` argparse arg overriding the default; optionally accept multiple `--date` flags or `--dates` CSV. Makes future backfills a documented operational procedure instead of ad-hoc recovery.
- **Noted**: 2026-05-26

### Pin Scrapy to a tested major; stop unpinned installs in scraper workflows

- **Type**: direct
- **Category**: reliability
- **Where**: `requirements.txt` (`scrapy>=2.13.0`); `.github/workflows/modular11-events-weekly-scrape.yml` + `modular11-weekly-scrape.yml` (`pip install scrapy twisted`)
- **Why**: No upper bound means a future Scrapy major can silently re-break every spider the way 2.13 did — an overridden `start_requests()` is never called, so the spider makes 0 requests with green CI and 0 data. Add `scrapy>=2.13,<3` (or pin the tested version) in requirements.txt and drop/pin the workflows' unpinned `pip install scrapy`. See auto-memory `gotcha_scrapy_async_start`.
- **Noted**: 2026-06-01

### Untrack committed Python bytecode (`__pycache__/*.pyc`)

- **Type**: direct
- **Category**: dx
- **Where**: tracked `*.pyc` under `scrapers/`, `config/`, `src/` (and elsewhere)
- **Why**: Committed bytecode shows as modified on every spider/test run, creates dirty-tree noise, and blocks clean `git worktree remove`. Add `__pycache__/` + `*.pyc` to `.gitignore` and `git rm -r --cached` the tracked files.
- **Noted**: 2026-06-01

### Wire brand fonts + logo into `@vercel/og` infographic endpoints

- **Type**: direct
- **Category**: refactor
- **Where**: `frontend/app/api/infographic/{movers,spotlight,state}/route.tsx`
- **Why**: All three endpoints fall back to `fontFamily: 'Arial, sans-serif'` and render "PITCHRANK" as letter-spaced gold text instead of the real logo. Both assets already exist and are deployed: fonts at `frontend/public/fonts/{Oswald,DMSans}-{Regular,Bold}.woff`, logos at `frontend/public/logos/logo-primary.svg` + variants. Fix: fetch the .woff files at edge runtime and pass to `ImageResponse`'s `fonts:` option (per memory `feedback_brand_fonts_in_generated_images.md`), and replace the text wordmark with an `<img src="https://pitchrank.io/logos/logo-primary.svg" />` block. ~30 LOC per file. Autogenerated weekly IG/X posts will then match the brand system used in `campaigns/creative/` hero images.
- **Noted**: 2026-06-02

### Rewrite `SOCIAL_TEMPLATES` with brand-voice-aware copy

- **Type**: plan
- **Category**: refactor
- **Where**: `scripts/marketing_pipeline.py` (`SOCIAL_TEMPLATES` constant)
- **Why**: Current templates are functional string substitutions with light personality (e.g. "🚀 {team_name} just climbed..."). Doesn't carry the audience-informed voice from `brand/positioning.md` / `brand/audience.md` / the curated IG carousel drafts in `campaigns/content/social/`. Rewrite with brand-voice templates + coherent hashtag strategy. Weekly posts currently feel like template fills rather than authored content.
- **Noted**: 2026-06-02

### Classify remaining modular11 events + handle MIXED-division events (Fest)

- **Type**: investigate
- **Category**: reliability
- **Where**: `scrapers/modular11_scraper/modular11_scraper/spiders/modular11_events.py` (`EVENT_DIVISIONS` map)
- **Why**: The events spider now skips any event not in `EVENT_DIVISIONS` (only `87`=HD classified). Other events (Gen adidas, Flex, future Cups) stay un-imported until classified. Fest (event 75) is `MIXED` (both HD and AD teams, no per-team division signal in the feed), so it needs a per-team division strategy before it can import at all. See memory `modular11_events_division.md`.
- **Noted**: 2026-06-03

### Backfill HD division label on the 37 division-less U19 Cup teams

- **Type**: plan
- **Category**: reliability
- **Where**: `teams` table (`{num}_U19` records that played event 87)
- **Why**: 37 U19 Cup teams are `{num}_U19` with no `HD` distinction/label (created division-less by earlier events scrapes). Games are correctly placed, but the cohort label is missing. Deferred from this session because rewriting `provider_team_id`/alias to `_U19_HD` risks breaking the match that currently works; safe minimal version is `distinction=hd` only. Needs a verified approach.
- **Noted**: 2026-06-03

## Align SOM Sports import-time scoring with Monday hygiene queue resolver

- **Status**: deferred
- **Where**: `src/models/somsports_matcher.py::SomSportsGameMatcher._calculate_match_score` + `src/models/game_matcher.py::GameHistoryMatcher._fuzzy_match_team` (lines ~1245-1274)
- **Why**: The override delegates to hygiene's `score_team_pair` (which already applies +0.15 club / +0.05 RL/ECNL / -0.08 RL-mismatch). Base `_fuzzy_match_team` then applies the SAME boosts AGAIN on top of the returned score, so SOM Sports import-time auto-merges score higher than the same pair would in the Monday queue resolver. Net effect on U15: ~1-2 extra auto-merges per cohort. Accepted for now because the user explicitly wanted more matches and the missed ones still flow through the queue → Monday hygiene path. The docstring documents this divergence honestly.
- **Fix path**: Override `_fuzzy_match_team` to copy the gated funnel from base but skip the post-score boost block (~40 lines). Strictly mirrors hygiene scoring; reduces auto-merges to ~7-8 per cohort.
- **Trigger**: revisit if a false-positive merge surfaces from the SOM Sports import that hygiene's review queue would have caught.
- **Noted**: 2026-06-05

## Extract cross-provider canonicalize-club wire-in into shared helper

- **Status**: deferred
- **Where**: `src/models/{sincsports,playmetrics,affinity_wa,somsports}_matcher.py` — each has a near-identical 5-line block: extract club if missing → canonicalize via state → log if changed.
- **Why**: The pattern is now duplicated in 4 places (extraction threshold passed per three-strikes principle). Each matcher freelances small variations: log prefix format (`[SincSports]` vs `[PlayMetrics]`), state source (call arg vs `self.default_state_code` vs module `STATE_CODE`), edge handling on empty inputs. A shared `canonicalize_provider_club(club_name, state_code, logger, provider_tag) -> str` helper in `src/utils/` would consolidate this.
- **Fix path**: Create `src/utils/canonicalize_provider_club.py` (~30 lines), update 4 matchers each lose ~5 lines and gain 1 call. Add tests asserting the shared helper logs uniformly and handles None inputs.
- **Trigger**: do alongside the next provider matcher addition, or before the 5th `canonicalize_club_name` wire-in.
- **Noted**: 2026-06-05

## Complete the openclaw decommission — ambiguous-docs judgment pass (clearly-dead set now planned)

- **Type**: plan
- **Status**: deferred
- **Where**: ~14 persona-mentioning SEO/content/data-quality docs that may be live references: `docs/{SEO_ACTION_PLAN,BLOG_CONTENT_PLAN,CONTENT_TEMPLATES,SOCIAL_MEDIA_IDEAS,PARENT_PAIN_POINTS,INSTAGRAM_SETUP,METRICS_BASELINE,DATA_QUALITY_CHECKLIST,DATA_QUALITY_ROADMAP,ALGORITHM_DEEP_DIVE,CANONICAL_TAG_AUDIT,blog-platform-summary(.md/.pages),SEO_OPPORTUNITIES,SEO_WEEKLY_REPORT}.md`, `scripts/blog_research.py`.
- **Why**: The 12 clearly-dead persona artifacts (8 docs + 3 scripts + 1 report) #879 missed are now captured in plan `.turbo/plans/complete-openclaw-decommission-conservative.md` (status: ready) — run that via `/implement-plan` first. This remaining entry is the per-file judgment pass on the AMBIGUOUS docs: verified 2026-06-08 that NONE are consumed by live code/workflows, so each is a standalone-value keep/delete (and de-persona) decision, not a breakage risk.
- **Fix path** (per-file judgment, do NOT bulk-delete): DELETE the pure persona operational artifacts / stale reports — SEO_ACTION_PLAN, BLOG_CONTENT_PLAN, CONTENT_TEMPLATES, SEO_OPPORTUNITIES, SEO_WEEKLY_REPORT, blog-platform-summary(.md/.pages). KEEP + strip persona attribution from genuine standalone assets — PARENT_PAIN_POINTS, SOCIAL_MEDIA_IDEAS, ALGORITHM_DEEP_DIVE, METRICS_BASELINE, DATA_QUALITY_CHECKLIST, DATA_QUALITY_ROADMAP. BORDERLINE (decide) — INSTAGRAM_SETUP (likely obsolete, Instagram now via Postiz), CANONICAL_TAG_AUDIT (stale point-in-time), scripts/blog_research.py (working but orphaned). Exclude `memory/2026-02-15.md` and `frontend/supabase/migrations/*`.
- **Trigger**: after the conservative-cleanup PR merges. Validate footprint against `origin/main` (a follow-up branch may predate the cleanup). See auto-memory `feedback_decommission_full_vocab_grep`.
- **Noted**: 2026-06-08 (clearly-dead set split out into a ready plan 2026-06-08)

### Extract shared PostgREST 1,000-row pagination helper

- **Type**: direct
- **Category**: refactor
- **Where**: `frontend/app/api/insights/[teamId]/route.ts` (fetchAllRows), `frontend/app/api/mission-control/model-snapshot/route.ts` (fetchAllProspectiveRows), `frontend/app/api/instagram-review/route.ts`
- **Why**: Three hand-rolled copies of the same .range() paging loop; lift the generic insights version into `frontend/lib` so bounds/termination logic can't drift between copies.
- **Noted**: 2026-06-11

### Test compute_rankings_with_ml cache-invalidation branch

- **Type**: plan
- **Category**: testing
- **Where**: `src/rankings/calculator.py` (~line 2113, games_used cache load)
- **Why**: Corrupt games_used parquet on a cache hit now raises to force a full rebuild (audit C15); behavior is unpinned — needs parquet cache fixtures + engine mocks.
- **Noted**: 2026-06-11

### calculate_rankings.py --dry-run still persists game residuals + explainability

- **Resolved**: 2026-08-24 by fix/dry-run-skip-residual-history-writes (persist flags + save_snapshot wired at both call sites; test_dry_run_skips_persistence.py)

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/calculate_rankings.py` (compute_all_cohorts call sites ~745-770), `src/rankings/calculator.py:50`
- **Why**: `--dry-run` gates the rankings save (lines 987-997) but never passes `persist_game_residuals=False`, so a `--dry-run --ml` run still writes `batch_update_ml_overperformance` + explainability to prod games during Pass 2. Fix: pass `persist_game_residuals=not args.dry_run` at all compute_all_cohorts call sites.
- **Noted**: 2026-06-11

### Commit the Glicko backtest harness to the repo

- **Type**: plan
- **Category**: testing
- **Where**: `experiments/glicko_backtest/` (fetch_data.py, glicko_engine_exp.py, backtest.py, analyze_scf_split.py, guardrail_isolated.py, verify_port.py, test_fork_equivalence.py)
- **Why**: It validated the SCF/tier production change (164K-game holdout, 72/72 cells) but is untracked, and its docs live in gitignored `.turbo/glicko2-backtest-results.md` — future accuracy work or CI regression-gating can't reuse it. Plan: decide parquet-cache handling and whether the engine fork stays a fork or becomes a fixture.
- **Noted**: 2026-06-11

### Verify email recipients before sending (double-opt-in)

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/api/reports/team-card/route.ts`, `frontend/app/api/newsletter/route.ts`
- **Why**: Both public endpoints email attacker-supplied addresses unverified (audit S9) — sender-domain reputation risk. Needs a confirm-before-send step designed around the report-card lead funnel and Beehiiv flows; per-IP rate limits currently blunt volume.
- **Noted**: 2026-06-12

### Fix main-red test: _DummySupabase mock missing .table after #884

- **Type**: direct
- **Category**: testing
- **Where**: `tests/unit/test_ranking_history_relocation.py` (test_compute_all_cohorts_invokes_calculate_rank_changes_after_final_rank)
- **Status**: Fix authored in PR #886 (2026-06-12), awaiting merge
- **Why**: Red on main at 8044d8477 — #884's metadata fetch path now calls `client.table(...)` which the `_DummySupabase` mock lacks (`AttributeError`). Every PR inherits the failure. Fix: add a `table()` stub returning the dummy query chain (test_glicko_sos_role.py's `_DummySupabaseQuery` has the pattern).
- **Noted**: 2026-06-12

### Add a pytest job to CI

- **Type**: direct
- **Category**: testing
- **Where**: `.github/workflows/ci.yml`
- **Why**: CI runs only ruff lint for Python, so test regressions merge silently — PR #884 broke `tests/unit/test_ranking_history_relocation.py` undetected. `tests/unit` is ~1,600 tests in ~5 min, viable CI scope.
- **Noted**: 2026-06-12

### Age-group rankings page — progressive loading (Option B) to cut mobile interaction jank (TBT)

- **Type**: plan
- **Category**: performance
- **Where**: `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx`, `frontend/components/RankingsTable.tsx`, `frontend/hooks/useRankings.ts`
- **Why**: Seeding the table from the RSC fetch (PR on branch `perf/mobile-rankings-homepage`) killed the duplicate client fetch (verified: 0 `/api/rankings` calls on load) but mobile TBT only went ~650ms→~576ms (noisy 177–576ms). Lighthouse shows ~1,180ms scriptEval; the biggest piece (~770ms) is hydrating the full seeded cohort + heavy page components. Fix: server-render only top ~50–100 teams, load the rest on scroll. **Design decision**: instant client-side search relies on the full cohort in memory — move search server-side OR lazy-load the full set on search focus. Consider deferring/code-splitting the SEO modules/filters too (page is heavy beyond the table). Needs a fresh plan; Option B is documented in `.turbo/plans/fix-mobile-perf-rankings-homepage.md`.
- **Noted**: 2026-06-15

### Dedupe ML∩cap overlap in diagnose_bubble_teams attribution math

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/diagnose_bubble_teams.py` `check_attribution()`
- **Why**: `n_base = n - n_ml - n_cap` and the `(n_ml + n_cap)` verdict threshold assume ML-lifted and cap-bound are disjoint, but a team can be both — double-counting the overlap understates the "base/SCF-driven" bucket and can overstate the attribution verdict. Pre-existing; currently inert (cap-bound = 0 on both the 2026-06-16 prod and SCF-off boards). Surfaced by Codex peer review during the SCF-off staging review. Fix: count `cap_bound` and `(ml_lifted AND NOT cap_bound)` separately.
- **Noted**: 2026-06-19

### GoogleAnalytics leaks Stripe session_id to GA4 on /upgrade/success

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/components/GoogleAnalytics.tsx` (GoogleAnalyticsContent gtag config)
- **Why**: GA4 still sends `session_id` in the auto-collected `dl=` param despite the component sanitizing `page_location` — a prod browser smoke test observed `google-analytics.com/g/collect?...dl=...session_id=...`. session_id is a replayable bearer secret for the anonymous `/api/stripe/sync` path; same class of leak just fixed for the Meta/Google Ads pixels (which skip the page via usePathname). GA's page_location strip doesn't cover dl=, so fully fixing it needs either gating GA on pathname (loses the GA pageview for that page) or a server-side URL scrub — warrants a plan. Pre-existing; out of scope of the pixel PR (payment flow left untouched).
- **Noted**: 2026-06-20

### Complete the prod→base rename in ranking_stability_check.py compare functions

- **Type**: direct
- **Category**: readability
- **Where**: `scripts/ranking_stability_check.py` (compare_movement / compare_top_movers / compare_stage_shift / compare_topn_composition)
- **Why**: The `--baseline-table` change rebranded print headers, help text, verdict strings, and the block comment to "baseline" but left the internal SQL CTE/aliases and locals as `prod` / `r_prod` / `prod_avg` / `prod_med`, so one line prints `baseline avg {prod_avg}`. Rename prod→base / r_prod→r_base / prod_avg→base_avg / prod_med→base_med across the four functions to remove the var/label mismatch. Rendered output is already correct; pre-existing naming, skipped for scope discipline during the `--baseline-table` change (surfaced by the consistency reviewer).
- **Noted**: 2026-06-22

### Switch the webhook set-password email to a token_hash callback URL (not raw action_link)

- **Type**: investigate-then-plan
- **Category**: reliability
- **Where**: `frontend/app/api/stripe/webhook/route.ts` (anonymous-checkout set-password email: `linkData.properties.action_link` → `sendPasswordSetupEmail`)
- **Why**: The webhook emails Supabase's raw `action_link` to new guest-checkout users. A server-generated recovery link forwarded to a browser that never started the flow hits the PKCE `code` path in `auth/callback/route.ts` with no `code_verifier` cookie and falls through to `/login` instead of the recovery session — the same P1 the monitor was fixed for (PR #928), and it matches the manual rescue runbook ([[stripe_guest_checkout_lockout]]) which uses `?token_hash=<hashed_token>&type=recovery`. This is the PRIMARY set-password path and currently "works" for many users, so do NOT change blindly: validate end-to-end in staging (does the current action_link actually succeed, or do most users fall back to forgot-password?) before switching `properties.action_link` → a `${SITE_URL}/auth/callback?token_hash=${properties.hashed_token}&type=recovery&next=/reset-password` URL. Owner deferred for safety during PR #928.
- **Noted**: 2026-06-30

### De-dup the stuck-signup monitor so it doesn't rotate recovery tokens every run

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/check_stuck_signups.py` (`find_stuck_users` calls `generate_recovery_link` for every stuck user every 6h run)
- **Why**: Each scan mints a fresh recovery token, invalidating the prior digest's link, so forwarding a stale admin digest yields a dead link. Mitigated for now with a "use the latest alert" digest note (PR #928); the plan already deferred per-user alert de-dup as a V1 follow-up. Proper fix: track per-user "already alerted / link still fresh" state (or skip users whose `recovery_sent_at` is recent) so links aren't churned, and/or send the customer a stable link directly. Keep the admin-digest design (owner chose to keep it).
- **Noted**: 2026-06-30

### Align HomeStats fallback floors with getPublicStats to avoid outage-time cross-page mismatch

- **Type**: direct
- **Category**: reliability
- **Where**: `frontend/components/HomeStats.tsx` (`fallbackGames=16000`, `fallbackTeams=2800` defaults) vs `frontend/lib/stats.ts` (`FALLBACK_STATS` 59,000 / 1,100,000)
- **Why**: During a Supabase outage the homepage renders 2,800 teams / 16,000 games while /rankings, /report-card, and /upgrade render 59,000 / 1.1M via `getPublicStats` — a ~20x contradiction for the same site-wide numbers. Raise HomeStats' fallbacks to match `FALLBACK_STATS` (or feed HomeStats from the shared source). Flagged by consistency review during /finalize on the dynamic-count change, skipped as out-of-scope.
- **Noted**: 2026-07-10

### Reconcile remaining hardcoded site stats (blog MDX teams + games count) with the live-count approach

- **Type**: plan
- **Category**: docs
- **Where**: `frontend/content/blog/what-predicts-winning-beyond-goals.mdx` ("77,000+ teams" / "700,000+ games", 2 spots); games-count copy: `1.1M+` in report-card/upgrade tiles vs `700K+` in `app/rankings/[region]/page.tsx` national metadata + `RankingsPillar.tsx` prose
- **Why**: The dynamic-count change unified the "Teams Ranked" number but deliberately left (a) editorial blog prose still citing stale 77,000+/700,000+ figures, and (b) the games count, itself inconsistent across the site (1.1M+ tiles vs 700K+ rankings copy). Decide a canonical games number and wire tiles/copy to it the way teams was; reconcile or refresh the blog figures. Flagged as follow-ups during /finalize.
- **Noted**: 2026-07-10

### Fix blog FAQ schema/body drift and add a question→answer parity test

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/blog-faqs.ts` (32 slugs), post bodies in `frontend/content/blog/*.mdx`, new test
- **Why**: FAQs are dual-source — visible copy in each post body, schema copy in `BLOG_FAQS` — and `BlogFAQSchema` emits JSON-LD with zero visible DOM, so nothing keeps them in sync. Already drifted on `youth-soccer-levels-explained` (`blog-faqs.ts:958`): "What is the difference…" vs body "What's the difference…", "two parallel sanctioning structures" vs "two parallel structures". Google requires FAQPage content be visible on the page, so this risks rich-result eligibility on a post drawing ~24,900 impressions/28d. Audit all 32, then add a vitest asserting question→answer PAIRS (independent string matching lets swapped answers pass); normalize frontmatter, curly/straight apostrophes, markdown links, and `**`. Single-source prior art exists at `RankingsPillar.tsx:12` but is TSX-only.
- **Noted**: 2026-07-27

### Add a deterministic sort tiebreak to getAllBlogPosts

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/blog.tsx:54,62` (5 consumers incl. `app/blog/page.tsx:41`, `app/sitemap.ts:61`)
- **Why**: Sorts by date only, over an unsorted `fs.readdirSync`, so same-date markdown posts inherit filesystem order — alphabetical on Windows/NTFS, hash order on Ubuntu CI ext4. `public/llms.txt` is generated from that order and drift-checked in CI (`ci.yml:97-114`), so local and CI output can disagree and fail the build despite correct regeneration. Latent today: nine duplicate-date groups exist but none yet pairs two non-pillar markdown posts. Needs its own PR — two of the five consumers are user/crawler-facing, so adding a tiebreak reshuffles the live `/blog` order and `sitemap.xml` and is not an additive change.
- **Noted**: 2026-07-27

### Roll config/settings.py _BIRTH_YEARS forward for the 2026-27 season

- **Resolved**: 2026-08-24 by fix/derive-birth-years-from-season (derived from team_utils.CURRENT_YEAR; consumer audit done — display sites auto-correct, and the dashboard's birth_year write was removed: a band year is not a team's actual birth year)

- **Type**: plan
- **Category**: reliability
- **Where**: `config/settings.py:88-102` (`_BIRTH_YEARS` feeding `AGE_GROUPS`), consumer `dashboard.py:4407`, stale copy `dashboard.py:641,658`, stale comment `config/settings.py:90`
- **Why**: `_BIRTH_YEARS` hardcodes the 2025-season map (`10: 2016 … 17: 2009, 19: 2007`) and never rolls, while `_soccer_season_year()` advances on its own every Aug 1. `dashboard.py:4407` writes `'birth_year': AGE_GROUPS.get(new_age_group, {}).get('birth_year')` on every admin team edit, so once the Aug 2026 rollover relabels `teams.age_group`, setting a team to u11 writes `birth_year` 2015 when a 2026-27 u11 is born 2016 — and `scripts/fix_team_age_groups.py` then reads that wrong year and rolls the team's `age_group` back down a cohort. Goes live the moment the migration is applied. Deferred out of the rollover PR (plan item 6) because the constant has 12+ consumers whose blast radius was never surveyed; start with that audit. Surfaced by review-consistency during /polish-code on the age rollover.
- **Noted**: 2026-07-31

### Make U18-named queue entries matchable after the age rollover

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/find_queue_matches.py` `extract_age_group` Priority 1/1b (U-age-token paths, ~592-605)
- **Why**: The U-age path deliberately preserves `u18` — an in-code comment explains Priority 1b must not route through `_canonicalize_age_token`, which remaps U18→U19 and would diverge from Priority 1. The rollover migration merges u17 and u18 into u19, leaving zero `u18` rows, so an entry named "Rush U18 Red" derives `u18`, `build_age_group_filter_clause` hard-filters on it, and it matches nothing on both the primary query and the cohort fallback. Fail-closed — lost matching, not wrong matching, so nothing is corrupted. Verified NOT introduced by the rollover PR: that path is unchanged there and the birth-year paths now correctly yield `u19`. Fix by folding 18→19 in the U-age path too, or widening the filter to `{u18, u19}` during the transition; either must land AFTER the migration, since u18 rows are the correct target until then. Surfaced by review-consistency during /polish-code on the age rollover.
- **Noted**: 2026-07-31

### Escape the bare % in find_queue_matches argparse help so --help stops crashing

- **Type**: direct
- **Category**: dx
- **Where**: `scripts/find_queue_matches.py:1425` (`--include-high` help string)
- **Why**: The help text reads `"Include 90%+ matches in auto-merge (not just 95%+)"`. argparse %-formats help strings when rendering, so `%+ m` parses as a format spec and `parser.parse_args()` raises `ValueError: unsupported format character 'm' (0x6d) at index 13` out of `_expand_help` — `python scripts/find_queue_matches.py --help` exits 1 with a traceback instead of printing usage. Normal execution is unaffected; only help rendering breaks, after the module and parser build fine. The script is driven by `data-hygiene-weekly.yml` Step 4 and `auto-merge-queue.yml`, so anyone debugging those cannot read its own usage. Fix is `90%%+` / `95%%+`; grep the other `scripts/` argparse help strings for bare `%` at the same time. Pre-existing since `52bded4f6` (2026-02-03), verified absent from the age-rollover diff. Found by smoke test during /polish-code on the age rollover.
- **Noted**: 2026-07-31

### Drive age-group matching and ingestion from explicit U labels, not birth-year inference

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/find_queue_matches.py` (`extract_age_group`), `scripts/fix_team_age_groups.py`, `src/etl/enhanced_pipeline.py:467-473`, `src/utils/team_utils.py:calculate_age_group_from_birth_year`, plus the five provider matchers that auto-create teams from the derived value
- **Why**: Cohorts are derived by parsing a birth year out of a team name (`2016`, `B2016`, `14B`) and applying `season_year - birth_year + 1`. That derivation moves on a wall clock every Aug 1 while stored labels move only when someone hand-applies a migration, and the gap between them is exactly what the 2026-27 rollover freeze exists to hold. It recurs every season. Trusting explicit provider/division U labels (`U11`, `11U`), with a U token in the name as fallback and no hard candidate filter when neither exists, removes the drift and a whole class of failure where a graduation or event year is mistaken for a birth year. Product-direction change, not a bug fix: it reverses what CLAUDE.md's Domain Knowledge section teaches (`14B` = 2014 = U12), so that section changes with it. Overlaps rollover-plan deferred items 3, 5, 6 and 9 — do as one pass. Explicitly NOT introducing a separate U18 board; PitchRank's U19 deliberately spans U18 and U19, and the rollover map `u17->u19` + `u18->u19` is correct. From peer review of PR #942.
- **Noted**: 2026-08-01

### Rotate and untrack the live Supabase service-role key committed to the public repo

- **Type**: direct
- **Category**: reliability
- **Where**: `.env.local` (tracked since `904e8a809`, 2026-03-25), `.gitignore`
- **Why**: `.env.local` is tracked in git and is not gitignored, on a **public** repo. It holds `SUPABASE_SERVICE_ROLE_KEY` (a 219-char JWT) and a credentialed `DATABASE_URL`. Hash comparison against the working local key confirms the committed value is the **current live key**, not a rotated one. A service-role key bypasses RLS entirely: full read/write on every table. Order matters — rotate in the Supabase dashboard first (the key is already public and may be harvested), then update Vercel + GitHub Actions secrets + local `.env.local`, then `git rm --cached .env.local` and add to `.gitignore`. History purge via `git filter-repo` is optional; assume the key is compromised regardless, so rotation is the actual remedy. Rotate the `DATABASE_URL` password too.
- **Noted**: 2026-08-11

### Correct the drain-rate figure in four enqueue script docstrings

- **Type**: direct
- **Category**: docs
- **Where**: `scripts/enqueue_active_teams.py:10`, `enqueue_discovery_teams.py:8`, `enqueue_safety_net.py:8-9`, `enqueue_yesterday_games.py:7`
- **Why**: All four state "process_missing_games (every 15min, 200/run) drains", but `.github/workflows/process-missing-games.yml:42` runs `--limit 40`. Real throughput is ~3,840 teams/day, not 19,200 — a 5x overstatement. The figure is load-bearing for capacity reasoning: it is why the queue backs up and why the manual "Help Clear Queue" action exists at all. Either correct the docstrings to 40/run or raise the workflow limit, but stop them disagreeing.
- **Noted**: 2026-08-11

### Set the ANTHROPIC_API_KEY secret so automated PR review runs again

- **Type**: direct
- **Category**: dx
- **Where**: repo secrets, consumed by `.github/workflows/claude-code-review.yml`
- **Why**: The `claude-review` check logs `ANTHROPIC_API_KEY:` empty and fails. It has failed on **every** PR for at least 10 days (verified back through 2026-08-01), including PRs that were merged. Every PR therefore shows a red check that reviewers learn to ignore, which also masks a genuine failure if one appears. Either set the secret or remove the workflow.
- **Noted**: 2026-08-11

### Extract one shared highlightMatch and settle which yellow is the brand yellow

- **Type**: direct
- **Category**: refactor
- **Where**: `frontend/components/GlobalSearch.tsx:19-49`, `TeamSelector.tsx:23-52`, `UnknownOpponentLink.tsx:51-80`, `ScopedTeamSelector.tsx:26-50`
- **Why**: `escapeRegex` and `highlightMatch` are copy-pasted into all four search components. Three copies are verbatim and use `bg-yellow-200 px-1`; ScopedTeamSelector uses `bg-[#F4D03F]/40 px-0.5` — Electric Yellow, the accent CLAUDE.md names as the design-system token. So the one brand-correct copy is precisely the one nobody editing the others will find, and search highlighting looks different depending on which box you are in. Extracting a single `highlightMatch` into `lib/` collapses the 4-way fork and forces the color question to be answered once.
- **Noted**: 2026-08-18

### Converge MergeTeamsDialog's team metadata line onto composeTeamMeta

- **Type**: plan
- **Category**: readability
- **Where**: `frontend/components/MergeTeamsDialog.tsx:263-267`, `frontend/lib/utils.ts` (composeTeamMeta)
- **Why**: The dialog renders `[age_group, gender, state_code].filter(Boolean).join(' • ')` → "u14 • Male • AZ", while the search dropdowns now render "AZ • U14 Boys". Opposite field order, raw DB values instead of display values. An admin who finds a team in nav search then opens the merge dialog on it sees two different labels for the same team, immediately before confirming an irreversible merge. Not a one-line swap: the dialog declares its own local `Team` interface fed by `/api/teams/search` (`age_group: string`, `gender: 'Male'|'Female'`, `state_code`), whereas `composeTeamMeta` takes the `RankingRow` shape (`age: number`, `gender: 'M'|'F'|'B'|'G'`, `state`). Normalize at that component's fetch boundary the way `hooks/useTeamSearch.ts` already does, then call the shared helper — do not widen `composeTeamMeta` to accept both shapes.
- **Noted**: 2026-08-18

### Use composeTeamDisplay for the report-card selector's team label

- **Type**: plan
- **Category**: readability
- **Where**: `frontend/components/ScopedTeamSelector.tsx:207-211,222-224`, `frontend/app/api/teams/search/route.ts`
- **Why**: It renders `team.team_name` raw where every other search surface renders `composeTeamDisplay(team)`, so one team reads "Dynamos SC U10" in global search and "Dynamos SC - Dynamos SC 2017 SC" in the report-card flow — the unabbreviated duplicated-club name that composeTeamDisplay exists to clean up. Blocked on a prerequisite: `ScopedTeam` carries no `league`, `distinction`, or `has_modular11_alias`, so the search route must select those columns first. Caveat: do **not** give this component `composeTeamMeta` — it is gated on age + gender + state being chosen before it searches, so that subtitle would print identical values on every row.
- **Noted**: 2026-08-18

### Cover UnknownOpponentLink's search rows with a component test

- **Type**: plan
- **Category**: testing
- **Where**: `frontend/components/UnknownOpponentLink.tsx:549-552`, new `frontend/components/UnknownOpponentLink.test.tsx`
- **Why**: The only rendering logic in the three-dropdown family no test exercises. Its subtitle is not a copy of the other two — it prefixes a highlighted `club_name` and uses a three-armed `{team.club_name && meta ? ' • ' : ''}` separator, so `GlobalSearch.test.tsx` cannot reach it. Three reviewers flagged it, and both genuine defects found in the 2026-08-18 review (a literal `U0`, a double bullet) lived in this file. ~70 lines on the `ComparePanel.test.tsx` pattern: mock `@/hooks/useTeamSearch`, `useQueryClient`, and `ui/dialog`+`select` as passthroughs; two fixtures (club_name + state:null + age:0 → no trailing bullet; club_name:null + populated meta → no leading bullet). Reviewers explicitly agreed `TeamSelector` does NOT need its own test — its row is behaviourally identical to GlobalSearch's.
- **Noted**: 2026-08-18

### Give TeamSelector and UnknownOpponentLink the combobox roles GlobalSearch has

- **Type**: direct
- **Category**: refactor
- **Where**: `frontend/components/TeamSelector.tsx:234-248`, `frontend/components/UnknownOpponentLink.tsx:537-557`; reference in `frontend/components/GlobalSearch.tsx:236-247`
- **Why**: GlobalSearch implements the full combobox pattern (`role="combobox"` + `aria-controls` on the input, `role="listbox"` on the container, `role="option"` + `aria-selected` per row). The other two carry `aria-autocomplete="list"` and `aria-expanded` with no `role="combobox"` to make those valid, and their rows have no role and no `aria-selected` despite tracking the same `selectedIndex` and painting the same `bg-accent` highlight. After the 2026-08-18 label/subtitle unification the three row bodies are otherwise near-identical, so this now reads as drift. Concrete cost: `GlobalSearch.test.tsx` selects rows via `querySelectorAll('[role="option"]')`, so anyone copying it to cover TeamSelector gets zero matches — a vacuously green test, worse than a red one.
- **Noted**: 2026-08-18

### Test useTeamSearch — it silently feeds every search subtitle

- **Type**: direct
- **Category**: testing
- **Where**: `frontend/hooks/useTeamSearch.ts` (select list ~:60, transforms ~:83 and :139-142), new `frontend/hooks/useTeamSearch.test.ts`
- **Why**: Sole producer of the three fields every dropdown subtitle reads — `state` ← `state_code`, `age` ← `normalizeAgeGroup(age_group) ?? 0`, `gender` ← a `'Male'|'Female'` → `'M'|'F'` coercion that silently defaults to `'M'`. Zero tests, and `GlobalSearch.test.tsx` mocks it away with fixtures hardcoding all three. If someone trimmed the `.select()` column list — the obvious move against the known full-table-download cost — `composeTeamMeta` would return `''` and every subtitle would render blank with the whole suite still green. ~40 lines mocking `@/lib/supabase/client`, capturing the `.select()` argument and asserting it contains `state_code`, `age_group`, `gender`, plus one row-transform assertion pinning `age: ageInt ?? 0` and the gender coercion.
- **Noted**: 2026-08-18

### Make the e2e search test fail when zero results render

- **Type**: direct
- **Category**: testing
- **Where**: `frontend/e2e/search.spec.ts:40-51`
- **Why**: `typing in search shows results dropdown` polls a disjunction that `searchingVisible` satisfies on the first iteration, while the component still shows its `InlineLoader`. The test passes when the dropdown renders zero rows — whether the query returned nothing, the DB columns went missing, or RLS blocked the read. It is the only check that rows arrive from a real database at all, and as written it verifies nothing. Fix: assert the loader is hidden first, then poll only the terminal arms (`resultCount > 0 || noResultsVisible || networkErrorVisible`).
- **Noted**: 2026-08-18

### Consolidate the six-plus independent team-metadata line implementations

- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/lib/utils.ts` (`composeTeamMeta`), `MergeTeamsDialog.tsx:265-266`, `RankingsTable.tsx:264`, `UnknownOpponentLink.tsx`, `app/api/infographic/movers/route.tsx:73`, `app/api/infographic/spotlight/route.tsx:78`, `TeamHeader.tsx:354`, `RankingsStickyFilters.tsx:45`
- **Why**: An adversarial pass counted 66 occurrences of the U+2022 glyph across frontend `.ts`/`.tsx` (excluding node_modules/.next). The same "club • state • age • gender" concept is independently reimplemented in at least six places with differing field order, raw-vs-display values, and separator handling. This is the real finding underneath a narrower proposal rejected 2026-08-18: exporting a `TEAM_META_SEPARATOR` constant threaded through 2 of 66 sites was rejected because it would leave the stated failure mode intact while falsely implying centralization. The genuine fix is converging these call sites on `composeTeamMeta`, normalizing each component's data shape at its own fetch boundary the way `hooks/useTeamSearch.ts` already does. A narrower sibling entry covers MergeTeamsDialog specifically.
- **Noted**: 2026-08-18

### Middleware drops rotated Supabase session cookies on early redirects

- **Type**: direct
- **Category**: reliability
- **Where**: `frontend/middleware.ts` (the `NextResponse.redirect` returns after `getUser()`)
- **Why**: `setAll` writes refreshed tokens onto the local `response`, but each early redirect builds a new response carrying none of them, so a rotation in flight is lost and the browser keeps an already-consumed refresh token. Supabase documents this exact pattern as a cause of users being randomly signed out. Fix is `redirectResponse.cookies.setAll(response.cookies.getAll())` before each return.
- **Noted**: 2026-08-18

### Emailed auth tokens are not bound to the recipient (session fixation)

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/auth/confirm/`, `frontend/app/auth/callback/route.ts`
- **Why**: Either path redeems whatever `token_hash` the URL carries with nothing tying it to the person holding the browser, so an attacker can link a victim a token for the attacker's own account and have the victim end up signed in as them. Pre-existing on the callback; the interstitial's Confirm button makes the phish look more legitimate. No clean fix — Supabase won't reveal the account behind a token without spending it — so this needs design work (e.g. refuse when a different user is already signed in).
- **Noted**: 2026-08-18

### Extract a shared redeemEmailToken module

- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/app/auth/callback/route.ts`, `frontend/app/auth/confirm/actions.ts`
- **Why**: Both paths carry their own copy of the verifyOtp call, the error-to-/login shape, and the recovery-vs-next routing; they build the Supabase client differently too (one uses `createServerSupabase`, the other hand-rolls `createServerClient`). Two reviewers flagged it. Deferred to keep the scanner fix reviewable.
- **Noted**: 2026-08-18

### PKCE ?code= links are still redeemed by a plain GET

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/auth/callback/route.ts` (the `if (code)` branch)
- **Why**: The interstitial protects `token_hash` links, but a link that arrives as `?code=` is exchanged on GET, so a scanner can spend it. Measured live: of 29 recovery flows in 60 days, 5 issued a PKCE code, plus 5 of 9 signup flows — so this shape is in real use. Repointing the Supabase dashboard email templates at `/auth/confirm?token_hash={{ .TokenHash }}` removes most of the exposure; closing it fully needs the same render-then-confirm treatment for `code`, without breaking OAuth sign-in (which legitimately arrives as `?code=` and should not need a button).
- **Noted**: 2026-08-18

### Weekly digest emails a live recovery token to a shared admin mailbox

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/check_stuck_signups.py` `generate_recovery_link` (~line 156)
- **Why**: The job mints an unsolicited, live 24h recovery token for every paying-but-never-signed-in customer and mails it to `pitchrankio@gmail.com` for an admin to forward. That token grants a full session on the customer's paid account, so anyone with access to that mailbox, the forwarded copy, or Resend's delivery history can take the account over. `reset_password_for_email(email)` sends the same token to the account owner instead, leaving the digest to carry only the list of who is stuck.
- **Noted**: 2026-08-18

### normalize_gender turns an unknown gender into "Male"

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/extract_and_import_tgs_teams.py:226` (empty input) and `:234` (else fallback)
- **Why**: An unparseable gender becomes a confidently wrong one instead of a rejection, so the team is created as Male at confidence 1.0 with `review_status: approved` and no queue entry for anyone to catch it. Reachable from any division label without a B/G prefix — `U11 Girls`, `U10 GIRLS 7v7`. The TGS scraper now resolves gender from the provider's `divisionGender` field so it no longer feeds this path, but the default is still live for every other caller. Prefer returning None and queueing for review over guessing. Related to the shared `normalize_gender_label()` helper proposed above.
- **Noted**: 2026-08-19

### Two GotSport tier-persistence tests are failing on main

- **Type**: investigate
- **Category**: testing
- **Where**: `tests/integration/test_gotsport_tier_persistence.py` (`test_golden_path_persists_tier_fields_to_jsonl`, `test_u7_micro_cohort_dropped_loose_age_kept`), raised from `src/scrapers/gotsport_tier_parser.py:764`
- **Why**: Both fail with `TierSubfetchError: event 42433 group 365847 subfetch failed (malformed_html) ... zero ?team= anchors; residue='Red'`.
- **Noted**: 2026-08-19
- **Resolved (2026-08-19)**: Not a main-is-red problem — CI was green throughout; I mischaracterised it. The tests fail only where `ZENROWS_API_KEY` is set, which flips `use_zenrows` so `_subpage_fetcher` routes through `_make_zenrows_request` instead of the mocked `session.get`; the unmocked call returns a MagicMock whose `.text` yields zero anchors. Fixture and parser were both fine. Fixed in PR #978 by pinning `use_zenrows = False` in the fixture.


### Implement validatePagination and route the hand-rollers through it

- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/api/validatePagination.ts` (to create), `frontend/app/api/teams/search/route.ts:74`, `frontend/app/api/announcements/route.ts:17`, plus four other `/api` routes
- **Why**: CLAUDE.md described this as an existing shared helper in three places, but it is implemented nowhere, so six routes hand-roll limit/offset parsing. Two of them pass unvalidated input straight through and produce NaN. The correct logic already exists inline in `app/api/rankings/national/route.ts:21-37` and can be lifted. The stale doc rows were removed in PR #1005; the helper itself was left out as a code change.
- **Noted**: 2026-08-22

### Decide whether data/master belongs in git

- **Type**: plan
- **Category**: dx
- **Where**: `data/master/` (11 CSVs, 345 MB), `scripts/weekly/update.py:255`
- **Why**: After PR #1005 untracked venv, node_modules, and the generated data trees, this is by far the largest tracked tree left. It was kept because it holds source CSVs rather than generated output, but its only reference in the repo is a path named in one script's help text. Either confirm it is a real input and document how a fresh clone obtains it, or untrack it.
- **Noted**: 2026-08-22

### Retire the "never git stash" rule once PR #1005 merges

- **Type**: direct
- **Category**: dx
- **Where**: `.claude/rules/git-workflow.md`
- **Why**: The rule exists because `git stash pop` failed on `.pyc` binary conflicts, which cost implementation work outright. That was caused by 9,381 tracked bytecode files, which PR #1005 untracks. Once it merges and a stash round-trips cleanly, the prohibition is a workflow amputation with no remaining cause. Confirm in practice before deleting.
- **Noted**: 2026-08-22

### Stop calculate-rankings from starting while data-hygiene is still merging teams

- **Type**: plan
- **Category**: reliability
- **Where**: `.github/workflows/calculate-rankings.yml:8`, `.github/workflows/data-hygiene-weekly.yml`
- **Why**: Hygiene starts Mon 11:00 UTC and has been running about 2.5 hours; rankings start 12:30, so rankings read team identities while hygiene is still merging them. Observed overlapping on 3 of the last 4 Mondays. A `workflow_run` trigger gated on hygiene completing removes the race without guessing at a longer delay.
- **Noted**: 2026-08-22

### Route the weekly blog commit through a PR now that main has a ruleset

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/marketing_pipeline.py:976`, `.github/workflows/marketing-pipeline.yml`
- **Why**: The script runs `git push origin main` with `GITHUB_TOKEN`; the `main` ruleset (2026-08-22: PR + 7 CI checks required, squash only) rejects that push, so the next publish fails at the push step. A PAT secret plus push-branch + `gh pr create` + `gh pr merge --auto --squash` fixes it and also closes the Vercel-webhook gap in `.claude/rules/vercel-ops.md`. Rulesets cannot list `GITHUB_TOKEN` as a bypass actor.
- **Noted**: 2026-08-22

### Fix the .pre-commit-config.yaml install instruction, or route ruff through lint-staged

- **Type**: direct
- **Category**: dx
- **Where**: `.pre-commit-config.yaml:3`, `frontend/package.json` (lint-staged), `CLAUDE.md:594`
- **Why**: The header says `pip install pre-commit && pre-commit install`, which refuses while husky owns `core.hooksPath`, so the Python pre-commit hook has never run on any clone. Either add a `*.py` lint-staged entry that runs `python -m ruff check --fix` (same scope) or rewrite the header to say CI and `.claude/hooks/ruff-fix.sh` are the ruff gates. CLAUDE.md:594 also still says pre-commit "may silently revert edits".
- **Noted**: 2026-08-23

### Make calculate_rankings --dry-run actually skip every write

- **Resolved**: 2026-08-24 by fix/dry-run-skip-residual-history-writes (persist flags + save_snapshot wired at both call sites; test_dry_run_skips_persistence.py)

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/calculate_rankings.py:741-768`, `src/rankings/calculator.py:2306-2335,2476,3347`
- **Why**: `--dry-run` prints "no database writes" but calls `compute_all_cohorts` without passing it, so game residuals (`_persist_game_residuals`) and the `ranking_history` snapshot (`save_snapshot=True` default) are persisted before the CLI's guards. Pass `persist_residuals=False, save_snapshot=False` when `args.dry_run`.
- **Noted**: 2026-08-23

### Add the missing power_score_true migration for rankings_full

- **Type**: direct
- **Category**: reliability
- **Where**: `supabase/migrations/`, `src/rankings/data_adapter.py:1006-1065`
- **Why**: The adapter upserts `power_score_true`/`power_score_final`, but no checked-in migration ever adds those columns (only `rank_in_cohort_final` got one); the live DB has them from a hand-applied change. A fresh `supabase db push` from migrations alone would make the ranking save fail. Add an idempotent `ALTER TABLE rankings_full ADD COLUMN IF NOT EXISTS` migration and repair the ledger.
- **Noted**: 2026-08-23

### Make the reviewer agents' fallback diff survive a missing origin/main ref

- **Type**: direct
- **Category**: reliability
- **Where**: `.claude/agents/ranking-change-reviewer.md`, `.claude/agents/migration-reviewer.md`
- **Why**: Codex P2 on PR #1011 (merged as-is): `git diff --merge-base origin/main` errors with "ambiguous argument" on checkouts lacking the origin/main ref. Add "fetch first; fall back to local main" wording.
- **Noted**: 2026-08-23

### Strip or explain the retired-pack provenance stamps in brand/*.md

- **Type**: direct
- **Category**: docs
- **Where**: `brand/learnings.md`, `brand/stack.md`, `brand/voice-profile.md`, `brand/positioning.md`
- **Why**: Their "updated_by: /brand-voice" / "Vibe Marketing Skills" stamps point at a pack with zero definitions left in the tree (menu doc deleted 2026-08-23; commands were already dead). Strip the four stamps or add a one-line retirement note.
- **Noted**: 2026-08-23

### Fix or disable the always-failing claude-review workflow

- **Type**: direct
- **Category**: dx
- **Where**: `.github/workflows/` Claude Code Review workflow + repo Actions secrets
- **Why**: `ANTHROPIC_API_KEY` secret is empty, so the check fails in ~2s on every PR ($0 spend, no comments posted) and shows a permanent red X beside real checks. Set the secret or remove/disable the workflow.
- **Noted**: 2026-08-23
### Speed up ML residual + explainability persistence in the weekly ranking run

- **Type**: plan
- **Category**: performance
- **Where**: `src/rankings/calculator.py:1883` (`_persist_game_residuals`), `src/rankings/calculator.py:91` (`_persist_game_explainability`)
- **Why**: ~55 of 150 min of the weekly run is these row-batch writes (profile: `.turbo/reports/ranking-run-profile-2026-08-17.md`). Larger RPC payloads or a staging-table merge would cut the run by a third.
- **Noted**: 2026-08-24

### Fix _backfill_game_stats_python NOT NULL failures for unpublished teams

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/calculate_rankings.py:564` (`_backfill_game_stats_python`)
- **Why**: It upserts stats for every team seen in games; teams with no `rankings_full` row make the INSERT violate the `age_group` NOT NULL constraint, killing whole 500-row batches (incl. retry) so existing teams in those batches keep stale stats. Filter to team_ids present in `rankings_full` first. Seen in the 2026-08-17 run log ("Backfill batch 318 failed").
- **Noted**: 2026-08-24

### Silence the false "SUPABASE_KEY is not set" warning in ranking runs

- **Type**: direct
- **Category**: dx
- **Where**: startup logging in the calculate-rankings path (module logs "SUPABASE_KEY is not set — database calls will fail" while the run proceeds on SUPABASE_SERVICE_ROLE_KEY)
- **Why**: Every weekly run log opens with a scary false warning, training readers to ignore real credential errors. Accept SUPABASE_SERVICE_ROLE_KEY as satisfying the check.
- **Noted**: 2026-08-24

### Give compute_all_cohorts a single no-persistence preset instead of four loose kwargs

- **Type**: plan
- **Category**: reliability
- **Where**: `src/rankings/calculator.py:2473-2477` (`compute_all_cohorts` flags; `RankingContext` at :49-51 already groups three)
- **Why**: Callers hand-assemble persist_game_residuals / persist_game_explainability / save_snapshot / calculate_rank_changes_enabled, and the three non-production callers disagreed three ways — which produced the backfill_prediction_feature_history explainability leak fixed 2026-08-24. A `read_only` flag or NO_PERSISTENCE kwargs constant would make a future fifth writer fail closed. Escalated from the dry-run-fix code review; deferred by scope discipline. Would also obsolete the two hand-enumerated flag lists (replay test in tests/unit/test_backfill_prediction_feature_history.py and the caller kwarg blocks), closing the round-3 P3 about a future persist_* flag slipping the replay path.
- **Noted**: 2026-08-24
### Add the prediction-feature snapshot writer to SKILL.md's stage 10

- **Type**: direct
- **Category**: docs
- **Where**: `.claude/skills/rankings-algorithm/SKILL.md` stage 10 vs `src/rankings/calculator.py:3347-3358`
- **Why**: Stage 10 names `save_ranking_snapshot()` but omits its sibling `_save_prediction_feature_snapshot_safe()` → `prediction_feature_history`, and presents both as unconditional; both are gated by `save_snapshot` (skipped under --dry-run). Round-3 review P3, deferred as pre-existing text outside the dry-run branch.
- **Noted**: 2026-08-24

### URGENT: scrape-eligibility filters roll on the calendar year, excluding real U10 teams every Aug-Dec

- **Resolved**: 2026-08-24 by fix/scrape-eligibility-season-year (PR #1018) — season-year derivation in the five RPCs + drain_queue/scrape_games/dashboard via team_utils.scrape_excluded_birth_years. Still open from this entry: the audit of teams.birth_year rows the old dashboard write stamped (name/provider-sourced correction).

- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/drain_queue.py:84-93` (`_excluded_birth_years`), `scripts/scrape_games.py:389` (hardcoded `[2005, 2006, 2017, 2018, 2019]`), and six RPCs using `c.yr - 9` (`get_teams_to_scrape_limited`, `get_scrape_eligibility_counts`, `find_discovery_teams`, `find_stale_teams`, `find_recently_active_teams`, `resolve_merges_in_scrape_enqueue_rpcs`) — the RPC fix needs a migration; mind the CREATE OR REPLACE overload trap
- **Why**: The "U8/U9" exclusions derive years from `date.today().year` while cohorts roll Aug 1, so from Aug 1 to Dec 31 they exclude the U10 cohort: 2017-born U10 teams are dropped from every enqueue path, drain_queue, and scrape_games right now. Surfaced by the birth-year-derivation review 2026-08-24. Follow-up in the same pass: audit `teams.birth_year` rows the dashboard's old stale-map write overwrote (needs name/provider-sourced correction, not a blanket increment; the write itself was removed 2026-08-24). `scripts/enrich_instagram_handles.py` searches and scores on the stored year, so corrupted rows actively mislead it. The same off-by-one also fails open on the old end: 2007-born (real U20) teams are NOT excluded Aug-Dec.
- **Noted**: 2026-08-24

### Single-source modular11's age-to-birth-year derivation

- **Type**: plan
- **Category**: refactor
- **Where**: `src/models/modular11_matcher.py:184-196` (`_birth_year_from_age_group`)
- **Why**: A third live age→birth-year derivation with its own season arithmetic (`now.year + 1 if month >= 8`) that returns None outside ages 13-18 — diverges from `team_utils`/`AGE_GROUPS` and violates the ranking-changes single-source rule. Read `AGE_GROUPS[age]["birth_year"]` or a shared helper instead.
- **Noted**: 2026-08-24

### Pick one owner for the age-groups reference (CLAUDE.md vs pitchrank-domain skill)

- **Type**: plan
- **Category**: docs
- **Where**: `CLAUDE.md` "Age Groups (2026-27 Season)" vs `.claude/skills/pitchrank-domain/SKILL.md:16-53`
- **Why**: Near-verbatim twins (same table, naming rule, U18-merge paragraph, counts) that drift independently — the season-trap note landed only in the skill copy. One owner (or generation from one source) keeps a future rollover edit from leaving them disagreeing.
- **Noted**: 2026-08-24

### Move the Supabase MCP server to Supabase's hosted HTTP/OAuth endpoint

- **Type**: plan
- **Category**: dx
- **Where**: `.mcp.json`; the `SUPABASE_ACCESS_TOKEN` block in `.env.example`; CLAUDE.md § Environment Variables
- **Why**: Supabase's Claude Code docs prescribe `https://mcp.supabase.com/mcp` (`read_only=true`, `project_ref`) over the npx stdio package, removing the account-wide PAT — which `--read-only`/`--project-ref` do not constrain — and the local `npx -y` execution surface. Costs a browser login per machine/worktree, and headless/CI runs would still need a token, so stdio + PAT stays the default.
- **Noted**: 2026-08-24

### Infographics Biggest Movers generator fabricates rank changes

- **Type**: direct
- **Category**: reliability
- **Where**: `frontend/components/infographics/rankingMoversRenderer.ts:247`, call sites in `frontend/app/infographics/page.tsx`
- **Why**: `generateMoverData` fills `change` with `Math.floor(Math.random()*15)-7`, so downloaded social graphics name real teams with invented rank changes; the rows already carry real `rank_change_7d/30d` and `/api/infographic/movers` shows the correct pattern. Violates the no-fabricated-data rule.
- **Noted**: 2026-08-24

### Decide whether all movers surfaces adopt the homepage's stricter definition

- **Type**: plan
- **Category**: feature
- **Where**: `frontend/lib/movers.ts` (band+recency filters), `frontend/lib/cohort-seo.ts:56-80` (Rising/Falling), `get_biggest_movers` RPC → `/api/infographic/movers`
- **Why**: The homepage now filters movers to the top-500 band (both endpoints) plus played-in-window; cohort SEO pages and the social-graphic RPC still surface churn-driven 2,000-spot swings, so three surfaces answer "who moved most" differently. Product call: unify or document the difference.
- **Noted**: 2026-08-24

### Extract one shared rank-delta badge component

- **Type**: plan
- **Category**: refactor
- **Where**: `components/RecentMovers.tsx`, `components/RankingsTable.tsx:549-570`, `components/CohortSEOContent.tsx:86-125`, `components/insights/InsightModal.tsx` (`DeltaIndicator`)
- **Why**: Four implementations of icon + abs(change) + green/red each pick their own sign semantics — the watchlist shipped inverted colors because of it (fixed 2026-08-24). Move `DeltaIndicator` out of InsightModal, add a filled-badge variant, and make it the single home for direction semantics.
- **Noted**: 2026-08-24

### Work through items 2–8 of the 2026-08-24 agent-readiness review

- **Type**: plan
- **Category**: dx
- **Where**: https://claude.ai/code/artifact/9e4525fa-4bb1-4844-9ea4-873e36de5d6f (98 cited findings); CLAUDE.md, .claude/, .github/workflows, docs/
- **Why**: The review's ranked plan lives only in the artifact. Shipped: item 1 agent-reachable credentials (#1019), item 2 documented commands = CI commands plus the wrong code patterns (#1023), item 3 part 1 the doc-reference parity test (#1024), item 3 part 2 the seven remaining contradictions given one owner each (#1025). Still open: item 3 part 3 (the prose de-duplication — 31 duplicated bodies replaced by pointers, ownership already settled); item 4 improvements.md lifecycle incl. `/sweep-improvements`; item 5 per-change wait (auto-merge, tracked allowlist, PR template, CI concurrency); item 6 a richer session-start hook; item 7 the git-guard gaps; item 8 retiring contradicting docs, the always-red claude-review workflow, and the stale worktree/branches.
- **Noted**: 2026-08-24 (updated 2026-08-25, after #1025)

### Extract the React mount/unmount test harness into frontend/test/

- **Type**: direct
- **Category**: testing
- **Where**: `frontend/test/`, `frontend/components/{GlobalSearch,ComparePanel,RecentMovers}.test.tsx`, `frontend/components/insights/DeltaIndicator.test.tsx`
- **Why**: Four files hand-roll the same createElement/createRoot/`act(unmount)`/remove lifecycle, so a React `act` semantics change needs four fixes — `ComparePanel.test.tsx` still imports `act` from the removed `react-dom/test-utils` path while the newer files import it from `react`. `frontend/test/` now exists (fixtures.ts, setup.ts, supabase-mock.ts) as a home for a `mountComponent()`/`cleanup()` pair.
- **Noted**: 2026-08-24
