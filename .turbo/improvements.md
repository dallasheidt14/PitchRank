# Improvements

Out-of-scope improvement opportunities captured during work sessions.

Every entry carries an `ID` (stable, never reused) and a `Status`:

| Status | Meaning | Also required |
|--------|---------|---------------|
| `open` | Still wanted, nobody has done it | — |
| `done` | Shipped | `Refs` — the PR, branch or commit |
| `deferred` | Deliberately not now | `Trigger` — what would make it now |
| `dropped` | Will not do | `Refs` — why |

A deferred entry has no closing reference, it has a resumption condition, so it carries
a `Trigger` rather than a `Refs`.

`done` and `dropped` entries move to `.turbo/improvements-archive.md` so this file
stays the list of live work. `tests/unit/test_improvements_backlog.py` pins the
vocabulary; the `sweep-improvements` skill does the periodic pass.

### Extract one shared highlightMatch and settle which yellow is the brand yellow

- **ID**: IMP-079
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `frontend/components/GlobalSearch.tsx:19-49`, `TeamSelector.tsx:23-52`, `UnknownOpponentLink.tsx:51-80`, `ScopedTeamSelector.tsx:26-50`
- **Why**: `escapeRegex` and `highlightMatch` are copy-pasted into all four search components. Three copies are verbatim and use `bg-yellow-200 px-1`; ScopedTeamSelector uses `bg-[#F4D03F]/40 px-0.5` — Electric Yellow, the accent CLAUDE.md names as the design-system token. So the one brand-correct copy is precisely the one nobody editing the others will find, and search highlighting looks different depending on which box you are in. Extracting a single `highlightMatch` into `lib/` collapses the 4-way fork and forces the color question to be answered once.
- **Noted**: 2026-08-18

### Converge MergeTeamsDialog's team metadata line onto composeTeamMeta

- **ID**: IMP-080
- **Status**: open
- **Type**: plan
- **Category**: readability
- **Where**: `frontend/components/MergeTeamsDialog.tsx:263-267`, `frontend/lib/utils.ts` (composeTeamMeta)
- **Why**: The dialog renders `[age_group, gender, state_code].filter(Boolean).join(' • ')` → "u14 • Male • AZ", while the search dropdowns now render "AZ • U14 Boys". Opposite field order, raw DB values instead of display values. An admin who finds a team in nav search then opens the merge dialog on it sees two different labels for the same team, immediately before confirming an irreversible merge. Not a one-line swap: the dialog declares its own local `Team` interface fed by `/api/teams/search` (`age_group: string`, `gender: 'Male'|'Female'`, `state_code`), whereas `composeTeamMeta` takes the `RankingRow` shape (`age: number`, `gender: 'M'|'F'|'B'|'G'`, `state`). Normalize at that component's fetch boundary the way `hooks/useTeamSearch.ts` already does, then call the shared helper — do not widen `composeTeamMeta` to accept both shapes.
- **Noted**: 2026-08-18

### Cover UnknownOpponentLink's search rows with a component test

- **ID**: IMP-082
- **Status**: open
- **Type**: plan
- **Category**: testing
- **Where**: `frontend/components/UnknownOpponentLink.tsx:549-552`, new `frontend/components/UnknownOpponentLink.test.tsx`
- **Why**: The only rendering logic in the three-dropdown family no test exercises. Its subtitle is not a copy of the other two — it prefixes a highlighted `club_name` and uses a three-armed `{team.club_name && meta ? ' • ' : ''}` separator, so `GlobalSearch.test.tsx` cannot reach it. Three reviewers flagged it, and both genuine defects found in the 2026-08-18 review (a literal `U0`, a double bullet) lived in this file. ~70 lines on the `ComparePanel.test.tsx` pattern: mock `@/hooks/useTeamSearch`, `useQueryClient`, and `ui/dialog`+`select` as passthroughs; two fixtures (club_name + state:null + age:0 → no trailing bullet; club_name:null + populated meta → no leading bullet). Reviewers explicitly agreed `TeamSelector` does NOT need its own test — its row is behaviourally identical to GlobalSearch's.
- **Noted**: 2026-08-18
- **Update (2026-09-08)**: Verified — no `UnknownOpponentLink.test.tsx` exists. But the subtitle logic this guarded moved into shared `TeamRowSubtitle.tsx` (used at `UnknownOpponentLink.tsx:551,676`), which `GlobalSearch.test.tsx:60,137-170` and `TeamSelector.test.tsx` now exercise. The remaining gap is narrower than written: nothing tests UnknownOpponentLink's own opponent-resolution flow.

### Give TeamSelector and UnknownOpponentLink the combobox roles GlobalSearch has

- **ID**: IMP-083
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `frontend/components/TeamSelector.tsx:234-248`, `frontend/components/UnknownOpponentLink.tsx:537-557`; reference in `frontend/components/GlobalSearch.tsx:236-247`
- **Why**: GlobalSearch implements the full combobox pattern (`role="combobox"` + `aria-controls` on the input, `role="listbox"` on the container, `role="option"` + `aria-selected` per row). The other two carry `aria-autocomplete="list"` and `aria-expanded` with no `role="combobox"` to make those valid, and their rows have no role and no `aria-selected` despite tracking the same `selectedIndex` and painting the same `bg-accent` highlight. After the 2026-08-18 label/subtitle unification the three row bodies are otherwise near-identical, so this now reads as drift. Concrete cost: `GlobalSearch.test.tsx` selects rows via `querySelectorAll('[role="option"]')`, so anyone copying it to cover TeamSelector gets zero matches — a vacuously green test, worse than a red one.
- **Noted**: 2026-08-18

### Test useTeamSearch — it silently feeds every search subtitle

- **ID**: IMP-084
- **Status**: open
- **Type**: direct
- **Category**: testing
- **Where**: `frontend/hooks/useTeamSearch.ts` (select list ~:60, transforms ~:83 and :139-142), new `frontend/hooks/useTeamSearch.test.ts`
- **Why**: Sole producer of the three fields every dropdown subtitle reads — `state` ← `state_code`, `age` ← `normalizeAgeGroup(age_group) ?? 0`, `gender` ← a `'Male'|'Female'` → `'M'|'F'` coercion that silently defaults to `'M'`. Zero tests, and `GlobalSearch.test.tsx` mocks it away with fixtures hardcoding all three. If someone trimmed the `.select()` column list — the obvious move against the known full-table-download cost — `composeTeamMeta` would return `''` and every subtitle would render blank with the whole suite still green. ~40 lines mocking `@/lib/supabase/client`, capturing the `.select()` argument and asserting it contains `state_code`, `age_group`, `gender`, plus one row-transform assertion pinning `age: ageInt ?? 0` and the gender coercion.
- **Noted**: 2026-08-18

### Make the e2e search test fail when zero results render

- **ID**: IMP-085
- **Status**: open
- **Type**: direct
- **Category**: testing
- **Where**: `frontend/e2e/search.spec.ts:40-51`
- **Why**: `typing in search shows results dropdown` polls a disjunction that `searchingVisible` satisfies on the first iteration, while the component still shows its `InlineLoader`. The test passes when the dropdown renders zero rows — whether the query returned nothing, the DB columns went missing, or RLS blocked the read. It is the only check that rows arrive from a real database at all, and as written it verifies nothing. Fix: assert the loader is hidden first, then poll only the terminal arms (`resultCount > 0 || noResultsVisible || networkErrorVisible`).
- **Noted**: 2026-08-18

### Consolidate the six-plus independent team-metadata line implementations

- **ID**: IMP-086
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/lib/utils.ts` (`composeTeamMeta`), `MergeTeamsDialog.tsx:265-266`, `RankingsTable.tsx:264`, `UnknownOpponentLink.tsx`, `app/api/infographic/movers/route.tsx:73`, `app/api/infographic/spotlight/route.tsx:78`, `TeamHeader.tsx:354`, `RankingsStickyFilters.tsx:45`
- **Why**: An adversarial pass counted 66 occurrences of the U+2022 glyph across frontend `.ts`/`.tsx` (excluding node_modules/.next). The same "club • state • age • gender" concept is independently reimplemented in at least six places with differing field order, raw-vs-display values, and separator handling. This is the real finding underneath a narrower proposal rejected 2026-08-18: exporting a `TEAM_META_SEPARATOR` constant threaded through 2 of 66 sites was rejected because it would leave the stated failure mode intact while falsely implying centralization. The genuine fix is converging these call sites on `composeTeamMeta`, normalizing each component's data shape at its own fetch boundary the way `hooks/useTeamSearch.ts` already does. A narrower sibling entry covers MergeTeamsDialog specifically.
- **Noted**: 2026-08-18
- **Update (2026-09-08)**: Re-anchored. Converged since noted: UnknownOpponentLink now goes through `TeamRowSubtitle`→`composeTeamMeta`. Still independent: `MergeTeamsDialog.tsx:265-266`, `RankingsTable.tsx:264`, `RankingsStickyFilters.tsx:45`, and both `app/api/infographic/{movers,spotlight}/route.tsx`. The `TeamHeader.tsx:354` citation is stale — that join is gone.

### Emailed auth tokens are not bound to the recipient (session fixation)

- **ID**: IMP-088
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/auth/confirm/`, `frontend/app/auth/callback/route.ts`
- **Why**: Either path redeems whatever `token_hash` the URL carries with nothing tying it to the person holding the browser, so an attacker can link a victim a token for the attacker's own account and have the victim end up signed in as them. Pre-existing on the callback; the interstitial's Confirm button makes the phish look more legitimate. No clean fix — Supabase won't reveal the account behind a token without spending it — so this needs design work (e.g. refuse when a different user is already signed in).
- **Noted**: 2026-08-18

### Extract a shared redeemEmailToken module

- **ID**: IMP-089
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/app/auth/callback/route.ts`, `frontend/app/auth/confirm/actions.ts`
- **Why**: Both paths carry their own copy of the verifyOtp call, the error-to-/login shape, and the recovery-vs-next routing; they build the Supabase client differently too (one uses `createServerSupabase`, the other hand-rolls `createServerClient`). Two reviewers flagged it. Deferred to keep the scanner fix reviewable.
- **Noted**: 2026-08-18
- **Update (2026-09-08)**: Verified — PR #967 (2026-08-19) architecturally split the flows and extracted `frontend/lib/auth/emailTokens.ts`, so the entry's headline duplication is largely gone. What remains: the recovery-vs-next redirect logic is still reimplemented in both files (`callback/route.ts:96-104` vs `confirm/actions.ts:33-42`), and client construction still differs (hand-rolled `createServerClient` vs `createServerSupabase()`).

### PKCE ?code= links are still redeemed by a plain GET

- **ID**: IMP-090
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/auth/callback/route.ts` (the `if (code)` branch)
- **Why**: The interstitial protects `token_hash` links, but a link that arrives as `?code=` is exchanged on GET, so a scanner can spend it. Measured live: of 29 recovery flows in 60 days, 5 issued a PKCE code, plus 5 of 9 signup flows — so this shape is in real use. Repointing the Supabase dashboard email templates at `/auth/confirm?token_hash={{ .TokenHash }}` removes most of the exposure; closing it fully needs the same render-then-confirm treatment for `code`, without breaking OAuth sign-in (which legitimately arrives as `?code=` and should not need a button).
- **Noted**: 2026-08-18
- **Update (2026-09-08)**: **The in-code half of this entry cannot work as written — the dashboard half is the whole fix.** Verified against installed source: `@supabase/ssr` 0.9.0 hardcodes `detectSessionInUrl` and `flowType: "pkce"` in `createBrowserClient` (caller options are spread *before* those keys, so they cannot be overridden), and `@supabase/auth-js` 2.100.1 `_isPKCECallback` fires on `!!(params.code && verifier)` reading `url.searchParams` — query params are parsed, not just the hash. The root layout renders `Navigation` -> `useUser` -> `createClientSupabase()` on **every** route, so serving `/auth/confirm?code=` would spend the code on page load, before any button. A second obstacle: `frontend/middleware.ts:35` exempts `/auth/confirm` only when `token_hash` is present, and its own comment says routing a `code` there "is an infinite redirect loop"; any future attempt must widen that exemption first. **The threat model also needs correcting.** The auto-exchange requires the verifier from *that browser's* storage, so a mail scanner cannot redeem a `?code=` at all — what spends it is the recipient's own browser or prefetcher. That makes this a reliability bug (a reset link that silently fails) rather than the account-takeover risk the entry's wording implies, and it is why this was pulled out of the security batch. The entry's own first recommendation stands and is now the entire remedy: repoint the Supabase dashboard email templates at `/auth/confirm?token_hash={{ .TokenHash }}`, which routes every reset through the interstitial that already works. That is a hosted-dashboard setting, not a code change, so it cannot be done in a PR. The 5-of-29 measurement in this entry is the count of flows still on the `ConfirmationURL` shape; re-derive it from `auth.flow_state.auth_code_issued_at` after changing the template to confirm it reaches zero.

### Implement validatePagination and route the hand-rollers through it

- **ID**: IMP-094
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/api/validatePagination.ts` (to create), `frontend/app/api/teams/search/route.ts:74`, `frontend/app/api/announcements/route.ts:17`, plus four other `/api` routes
- **Why**: CLAUDE.md described this as an existing shared helper in three places, but it is implemented nowhere, so six routes hand-roll limit/offset parsing. Two of them pass unvalidated input straight through and produce NaN. The correct logic already exists inline in `app/api/rankings/national/route.ts:21-37` and can be lifted. The stale doc rows were removed in PR #1005; the helper itself was left out as a code change.
- **Noted**: 2026-08-22

### Stop calculate-rankings from starting while data-hygiene is still merging teams

- **ID**: IMP-097
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `.github/workflows/calculate-rankings.yml:8`, `.github/workflows/data-hygiene-weekly.yml`
- **Why**: Hygiene starts Mon 11:00 UTC and has been running about 2.5 hours; rankings start 12:30, so rankings read team identities while hygiene is still merging them. Observed overlapping on 3 of the last 4 Mondays. A `workflow_run` trigger gated on hygiene completing removes the race without guessing at a longer delay.
- **Noted**: 2026-08-22

### Route the weekly blog commit through a PR now that main has a ruleset

- **ID**: IMP-098
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/marketing_pipeline.py:976`, `.github/workflows/marketing-pipeline.yml`
- **Why**: The script runs `git push origin main` with `GITHUB_TOKEN`; the `main` ruleset (2026-08-22: PR + 7 CI checks required, squash only) rejects that push, so the next publish fails at the push step. A PAT secret plus push-branch + `gh pr create` + `gh pr merge --auto --squash` fixes it and also closes the Vercel-webhook gap in `.claude/rules/vercel-ops.md`. Rulesets cannot list `GITHUB_TOKEN` as a bypass actor.
- **Noted**: 2026-08-22

### Add the missing power_score_true migration for rankings_full

- **ID**: IMP-101
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `supabase/migrations/`, `src/rankings/data_adapter.py:1006-1065`
- **Why**: The adapter upserts `power_score_true`/`power_score_final`, but no checked-in migration ever adds those columns (only `rank_in_cohort_final` got one); the live DB has them from a hand-applied change. A fresh `supabase db push` from migrations alone would make the ranking save fail. Add an idempotent `ALTER TABLE rankings_full ADD COLUMN IF NOT EXISTS` migration and repair the ledger.
- **Noted**: 2026-08-23
- **Update (2026-09-08)**: Verified — `power_score_true` has no `ADD COLUMN` or `CREATE TABLE` anywhere in `supabase/migrations/*.sql`, only a code comment at `20260404000000_add_rank_in_cohort_final.sql:2-3`. The entry overstates by one column: `power_score_final` **does** have provenance (`20250120130000_create_rankings_full.sql:71`). One missing column is still enough to fail a fresh `supabase db push`, because `v53e_to_rankings_full_format` (`src/rankings/data_adapter.py:1063-1064`) is the single adapter for both engines and upserts both unconditionally.

### Make the reviewer agents' fallback diff survive a missing origin/main ref

- **ID**: IMP-102
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `.claude/agents/ranking-change-reviewer.md`, `.claude/agents/migration-reviewer.md`
- **Why**: Codex P2 on PR #1011 (merged as-is): `git diff --merge-base origin/main` errors with "ambiguous argument" on checkouts lacking the origin/main ref. Add "fetch first; fall back to local main" wording.
- **Noted**: 2026-08-23

### Strip or explain the retired-pack provenance stamps in brand/*.md

- **ID**: IMP-103
- **Status**: open
- **Type**: direct
- **Category**: docs
- **Where**: `brand/learnings.md`, `brand/stack.md`, `brand/voice-profile.md`, `brand/positioning.md`
- **Why**: Their "updated_by: /brand-voice" / "Vibe Marketing Skills" stamps point at a pack with zero definitions left in the tree (menu doc deleted 2026-08-23; commands were already dead). Strip the four stamps or add a one-line retirement note.
- **Noted**: 2026-08-23

### Speed up ML residual + explainability persistence in the weekly ranking run

- **ID**: IMP-105
- **Status**: open
- **Type**: plan
- **Category**: performance
- **Where**: `src/rankings/calculator.py:1883` (`_persist_game_residuals`), `src/rankings/calculator.py:91` (`_persist_game_explainability`)
- **Why**: ~55 of 150 min of the weekly run is these row-batch writes (profile: `.turbo/reports/ranking-run-profile-2026-08-17.md`). Larger RPC payloads or a staging-table merge would cut the run by a third.
- **Noted**: 2026-08-24

### Give compute_all_cohorts a single no-persistence preset instead of four loose kwargs

- **ID**: IMP-108
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/rankings/calculator.py:2473-2477` (`compute_all_cohorts` flags; `RankingContext` at :49-51 already groups three)
- **Why**: Callers hand-assemble persist_game_residuals / persist_game_explainability / save_snapshot / calculate_rank_changes_enabled, and the three non-production callers disagreed three ways — which produced the backfill_prediction_feature_history explainability leak fixed 2026-08-24. A `read_only` flag or NO_PERSISTENCE kwargs constant would make a future fifth writer fail closed. Escalated from the dry-run-fix code review; deferred by scope discipline. Would also obsolete the two hand-enumerated flag lists (replay test in tests/unit/test_backfill_prediction_feature_history.py and the caller kwarg blocks), closing the round-3 P3 about a future persist_* flag slipping the replay path.
- **Noted**: 2026-08-24

### Add the prediction-feature snapshot writer to SKILL.md's stage 10

- **ID**: IMP-109
- **Status**: open
- **Type**: direct
- **Category**: docs
- **Where**: `.claude/skills/rankings-algorithm/SKILL.md` stage 10 vs `src/rankings/calculator.py:3347-3358`
- **Why**: Stage 10 names `save_ranking_snapshot()` but omits its sibling `_save_prediction_feature_snapshot_safe()` → `prediction_feature_history`, and presents both as unconditional; both are gated by `save_snapshot` (skipped under --dry-run). Round-3 review P3, deferred as pre-existing text outside the dry-run branch.
- **Noted**: 2026-08-24

### Audit the `teams.birth_year` rows the dashboard's old stale-map write stamped

- **ID**: IMP-110
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `teams.birth_year` (database column); `scripts/enrich_instagram_handles.py`, which searches and scores on the stored year
- **Why**: The dashboard once wrote a stale age→birth-year map over `teams.birth_year`. The write itself was removed 2026-08-24, but the rows it stamped were never audited, and they need name- or provider-sourced correction rather than a blanket increment — a corrupted year actively misleads `enrich_instagram_handles.py`. Scope the affected population first; nobody has measured it.
- **Noted**: 2026-08-24
- **Update (2026-09-07)**: Retitled. The original entry was the calendar-year scrape-eligibility bug, marked URGENT, and **that half is done** — #1018 moved `scrape_games.py` and `drain_queue._excluded_birth_years` onto `team_utils.scrape_excluded_birth_years` (season-derived), and migration 20260824120000 moved the six RPCs to match. Verified live 2026-09-07. Only the `teams.birth_year` audit, always a follow-up rather than the headline, is still open, so the title and `Where` now name it. Left open rather than closed because that audit has not been done.

### Single-source modular11's age-to-birth-year derivation

- **ID**: IMP-111
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `src/models/modular11_matcher.py:184-196` (`_birth_year_from_age_group`)
- **Why**: A third live age→birth-year derivation with its own season arithmetic (`now.year + 1 if month >= 8`) that returns None outside ages 13-18 — diverges from `team_utils`/`AGE_GROUPS` and violates the ranking-changes single-source rule. Read `AGE_GROUPS[age]["birth_year"]` or a shared helper instead.
- **Noted**: 2026-08-24

### Move the Supabase MCP server to Supabase's hosted HTTP/OAuth endpoint

- **ID**: IMP-113
- **Status**: deferred
- **Type**: plan
- **Category**: dx
- **Where**: `.mcp.json`; the `SUPABASE_ACCESS_TOKEN` block in `.env.example`; CLAUDE.md § Environment Variables
- **Why**: Supabase's Claude Code docs prescribe `https://mcp.supabase.com/mcp` (`read_only=true`, `project_ref`) over the npx stdio package, removing the account-wide PAT — which `--read-only`/`--project-ref` do not constrain — and the local `npx -y` execution surface. Costs a browser login per machine/worktree, and headless/CI runs would still need a token, so stdio + PAT stays the default.
- **Noted**: 2026-08-24
- **Trigger**: Revisit only if the stdio+PAT setup breaks or Supabase deprecates it. The hosted HTTP/OAuth move was reviewed and explicitly declined on 2026-08-24 in favour of staying on stdio+PAT, citing the same per-machine-browser-login tradeoff this entry names. Open by decision, not neglect.

### Decide whether all movers surfaces adopt the homepage's stricter definition

- **ID**: IMP-115
- **Status**: open
- **Type**: plan
- **Category**: feature
- **Where**: `frontend/lib/movers.ts` (band+recency filters), `frontend/lib/cohort-seo.ts:56-80` (Rising/Falling), `get_biggest_movers` RPC → `/api/infographic/movers`
- **Why**: The homepage now filters movers to the top-500 band (both endpoints) plus played-in-window; cohort SEO pages and the social-graphic RPC still surface churn-driven 2,000-spot swings, so three surfaces answer "who moved most" differently. Product call: unify or document the difference.
- **Noted**: 2026-08-24

### Extract one shared rank-delta badge component

- **ID**: IMP-116
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `components/RecentMovers.tsx`, `components/RankingsTable.tsx:549-570`, `components/CohortSEOContent.tsx:86-125`, `components/insights/InsightModal.tsx` (`DeltaIndicator`)
- **Why**: Four implementations of icon + abs(change) + green/red each pick their own sign semantics — the watchlist shipped inverted colors because of it (fixed 2026-08-24). Move `DeltaIndicator` out of InsightModal, add a filled-badge variant, and make it the single home for direction semantics.
- **Noted**: 2026-08-24

### Extract the React mount/unmount test harness into frontend/test/

- **ID**: IMP-118
- **Status**: open
- **Type**: direct
- **Category**: testing
- **Where**: `frontend/test/`, `frontend/components/{GlobalSearch,ComparePanel,RecentMovers}.test.tsx`, `frontend/components/insights/DeltaIndicator.test.tsx`
- **Why**: Four files hand-roll the same createElement/createRoot/`act(unmount)`/remove lifecycle, so a React `act` semantics change needs four fixes — `ComparePanel.test.tsx` still imports `act` from the removed `react-dom/test-utils` path while the newer files import it from `react`. `frontend/test/` now exists (fixtures.ts, setup.ts, supabase-mock.ts) as a home for a `mountComponent()`/`cleanup()` pair.
- **Noted**: 2026-08-24

### Remove `has_modular11_alias` end-to-end

- **ID**: IMP-119
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/hooks/useTeamSearch.ts` (`fetchModular11TeamIds` :23-46, field at :139), `frontend/lib/api.ts:301-314,536`, `frontend/lib/matchPredictionService.ts:249-262`, `frontend/lib/types.ts:60`, `frontend/types/RankingRow.ts:14`, plus fixtures in four test files
- **Why**: After `teamDisplayName` (branch `show-team-name-in-rankings`) the flag's only reader is `utils.ts:192` inside `composeTeamDisplay`, reachable only when `team_name` is blank or `unknown_`-prefixed. Production count of teams meeting both conditions was 0 on 2026-08-27; only a newly scraped modular11 team makes it nonzero, and in that window it is actively harmful — it forces `return team.team_name`, rendering the literal `unknown_12345` instead of the club-composed label. Supersedes IMP-034. Not urgent: `useTeamSearch` has a module-level 10-minute cache, so its ~3 serial PostgREST round-trips cost once per session, not per search. Remove all three writers together — deleting only the `useTeamSearch` fetch leaves the field populated on some paths and not others.
- **Noted**: 2026-08-27

### Get RankingsTable under unit test despite the virtualizer

- **ID**: IMP-120
- **Status**: open
- **Type**: plan
- **Category**: testing
- **Where**: `frontend/components/RankingsTable.tsx` (648 lines, no test file), `frontend/vitest.config.ts`
- **Why**: The rankings table is the primary surface of the team-name display change and has zero unit coverage — a revert of any of its four `teamDisplayName` call sites (visible cell :582, sort comparator :148-149, aria-label :525, Schema.org payload :337) would ship with all seven required `ci.yml` checks green. `e2e/rankings.spec.ts` does not gate: `vitest.config.ts:9` excludes `e2e/**` and Playwright is not a required check. The obvious test is not writable as-is — a scratch probe reusing this repo's harness showed `useVirtualizer` renders **zero** rows under happy-dom (the scroll element measures zero height), so everything inside `virtualItems.map` never executes. Either mock `@tanstack/react-virtual` (no precedent here) or scope the test to the Schema.org payload and sort comparator, both of which sit outside the virtual list.
- **Noted**: 2026-08-27

### No tests anywhere under components/infographics/

- **ID**: IMP-122
- **Status**: open
- **Type**: plan
- **Category**: testing
- **Where**: `frontend/components/infographics/` (10 modules: 5 canvas renderers + 5 preview components), `frontend/components/infographics/Top10Infographic.tsx:254-266`
- **Why**: Ten modules, zero tests. `smoke-infographics.yml` checks HTTP status on the OG routes daily, not rendered text, and is not a required `ci.yml` check. The five `*Preview.tsx` components need no canvas and are assertable today. Pairs with IMP-030, which covers the truncation helper the renderers should share.
- **Noted**: 2026-08-27
- **Update (2026-09-08)**: Re-anchored — `rankingMoversRenderer.test.ts` now exists but covers `generateMoverData`'s data logic only, not rendering. All five `*Preview.tsx` components (BiggestMovers, HeadToHead, LeagueDistribution, StateChampions, TeamSpotlight) still have zero test files, and `smoke-infographics.yml` checks HTTP status only.

### Fold ScopedTeamSelector into the shared search-row pattern

- **ID**: IMP-123
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/components/ScopedTeamSelector.tsx:120,207-212,222-223`, `frontend/components/TeamSelector.tsx`, `frontend/app/api/teams/search/route.ts:33`, `frontend/hooks/useTeamSearch.ts:90`, `frontend/CLAUDE.md` pitfall 10
- **Why**: `ScopedTeamSelector` is a near-clone of `TeamSelector` — same `highlightMatch`, same `selectedIndex` keyboard model, same markup — but hand-rolls its row label three different ways and has no `aria-label` at all, where its three siblings do. Pitfall 10 lists only the three `useTeamSearch` consumers, so this fourth surface is missed by exactly the grep the pitfall tells you to run; it fetches `/api/teams/search`, whose select list returns neither `league` nor `distinction`.
- **Noted**: 2026-08-27

### Clamp the Top10 infographic preview so it matches the canvas export

- **ID**: IMP-124
- **Status**: open
- **Type**: direct
- **Category**: readability
- **Where**: `frontend/components/infographics/Top10Infographic.tsx:254-266`, compare `frontend/components/infographics/StateChampionsPreview.tsx:181-186`
- **Why**: The name div sets `lineHeight: 1.2` with no `whiteSpace: 'nowrap'` and no line clamp, while its sibling preview clamps at 2 lines and the canvas export truncates by measured width. Registered names are materially longer than the club labels they replaced (see IMP-030), so a long name wraps and grows the row in the preview while the exported PNG ellipsizes it — the operator approves one image and ships another. Split out of IMP-122 so it does not close with that entry's test work.
- **Noted**: 2026-08-27

### Correct the searchable_name comment in useTeamSearch

- **ID**: IMP-125
- **Status**: open
- **Type**: direct
- **Category**: docs
- **Where**: `frontend/hooks/useTeamSearch.ts:89-91`
- **Why**: The comment says the `searchable_name` tokens exist "so users can search using the same string they see in the rankings table". The rankings table now renders `teamDisplayName` over club + state, so U{age}, league and distinction appear in no visible row — they are index-only, feeding the hidden filter string at `RankingsTable.tsx:201`. State what the index actually widens past. Split out of IMP-123, which is a component refactor this does not depend on.
- **Noted**: 2026-08-27

### Give the unknown_ placeholder predicate one definition

- **ID**: IMP-126
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/drain_queue.py:70` and `scripts/scrape_games.py:51` (byte-identical `_is_placeholder_unknown_team`), `frontend/lib/utils.ts:201` (`UNRESOLVED_NAME`)
- **Why**: One canonical shape, three definitions, and the frontend one already drifted. It shipped as `/^unknown_/i`, which classifies any name starting with `unknown_` as a placeholder; a real team with a club would then render its club label instead of its name, recreating the cohort collapse PR #1043 fixed. Caught in review and tightened to `/^unknown_\d+$/i`, but `tests/unit/test_scrape_games.py:98` had asserted `unknown_elite` is a real name the whole time and nothing stopped the frontend disagreeing. The two Python copies are identical and want one import. The frontend cannot do the backend's exact `team_name == f"unknown_{provider_team_id}"` comparison because the payload carries no `provider_team_id` — decide whether that column should reach the frontend or whether the regex stays the sanctioned approximation.
- **Noted**: 2026-08-27
- **Update (2026-09-08)**: Verified — the frontend half already shipped: `frontend/lib/utils.ts:201` is now `/^unknown_\d+$/i`, pinned by `tests/unit/test_scrape_games.py:98`. Still open: `scripts/drain_queue.py:70-78` and `scripts/scrape_games.py:51-59` remain byte-identical copies with no shared import.

### Hoist the team_scrape_log bulk writer into src/etl/bulk_ops.py

- **ID**: IMP-129
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `scripts/drain_queue.py:113-153` and `scripts/scrape_games.py:62-103` (byte-identical `_bulk_log_team_scrapes`), `scripts/process_missing_games.py` (`_flush_scrape_log`)
- **Why**: Three copies of the same writer — same 500-row batching, same row shape, same `update_last_scraped_at` flag, same swallowed-insert warning, same `bulk_update_last_scraped_at` handoff. `src/etl/bulk_ops.py` already hosts that RPC helper and all three files import from it. The third copy is a method rather than a module function and does not share the name, so a grep for the other two misses it. Generalising needs only `provider_id` per entry instead of per call, which `_flush_scrape_log` already does.
- **Noted**: 2026-08-27

### Give the scrape-eligibility predicate one definition via a security_invoker view

- **ID**: IMP-130
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `supabase/migrations/20260827100200_find_topup_teams.sql`, `supabase/migrations/20260827100300_scrape_eligibility_skips_inactive_teams.sql`, `tests/unit/test_scrape_activity_predicate.py`
- **Why**: The rule is currently pasted byte-identically into `find_stale_teams`, `find_discovery_teams` and `find_topup_teams`, held together by a drift test. Sharing it as a scalar SQL function genuinely will not work — `inline_function()` refuses a body with `hasSubLinks` and the rule carries an `EXISTS`. A view does: `is_simple_subquery()` does not reject sublinks, so the qual is pulled up into each caller's `WHERE` and the plan is unchanged. Needs an explicit `REVOKE SELECT ... FROM anon, authenticated`, since Supabase's default privileges would otherwise expose it over PostgREST. Would retire three copies, most of the drift test, and the requirement that the block stay schema-qualified to suit whichever caller runs under `search_path = ''`.
- **Noted**: 2026-08-27

### process_missing_games advances last_scraped_at after a window-limited scrape

- **ID**: IMP-132
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `scripts/process_missing_games.py` (`scrape_games_for_date`, `_flush_scrape_log`), `scripts/drain_queue.py:687-700` (`scrape_dates_cache`)
- **Why**: `teams.last_scraped_at` is not only the re-probe clock; it is the incremental watermark `drain_queue.py` and `scrape_games.py` pass as `since_date`, and `GotSportScraper.scrape_team_games` enforces it hard. But this path scrapes only `[game_date-90, game_date+90]`, and `game_date` is today or yesterday for essentially every request. Stamping `now()` therefore claims coverage the scrape did not have: for a never-scraped team the history older than 90 days becomes unreachable, inside the 365-day ranking window, and the provider caps a response at 30 matches so a later full scrape cannot recover it. Rated P2 in review only because the watermark's consumers are manual-dispatch — but those are the same surface the activity filter benefits. Consider advancing only when the scraped window starts at or before the existing watermark, or keeping the re-probe clock in its own column.
- **Noted**: 2026-08-27

### Merging a double-import duplicate leaves the fixture recorded twice against the survivor

- **ID**: IMP-137
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `src/rankings/data_adapter.py:291`, `scripts/cleanup_dupe_games_by_composite.py`
- **Why**: `execute_team_merge` never touches `games`, so when two rows held the same match because it was imported twice, both rows now resolve to the survivor and its schedule contains the match twice. Nothing downstream removes them: the adapter dedupes with `drop_duplicates(subset=["id"])` — the game row's own id — so both copies feed the engine, and `game_uid` embeds master team ids so they never collided on insert either. Measured 604 duplicated fixture tuples across a 200-merge sample of the 2026-08-27 batch; no ranking run has consumed them yet (last run 101 days ago). `cleanup_dupe_games_by_composite.py` cannot find them — it keys on the raw master ids, which still differ — and it deletes rows outright, against the game-immutability rule. Decide between merge-resolved dedupe in the adapter and marking the redundant copies `is_excluded`.
- **Noted**: 2026-08-27
- **Update (2026-08-31)**: Decided in favour of `is_excluded`, and the existing backlog is cleared. `scripts/exclude_merge_duplicate_games.py` groups every game in a merge cluster by merge-resolved `(home, away, date, home_score, away_score)`, keeps the copy naming the surviving row and excludes the rest. Applied 2,135 exclusions (50 verified, then 2,085); merge-created duplicates now measure 0, all 2,135 kept counterparts verified still live. The full 639-merge batch held 2,062 of them, not the 604 the 200-merge sample projected. What remains open is prevention: this is a manual repair that must be remembered after every merge batch, and it belongs in `execute_team_merge` or a post-merge workflow step, the way `20260822000000` closed the stranded-fixture hole at the source. Two findings for whoever takes that on — the discriminator is that the two rows carry *different* raw master ids, since a genuine same-day rematch recorded once carries identical ones; and the grouping key must keep home/away orientation or it collapses real reverse fixtures. Separately, 842 same-date same-score groups sharing identical raw ids remain untouched here: those are the pre-existing double-import class `cleanup_dupe_games_by_composite.py` targets, not merge damage.
- **Update (2026-08-31, second)**: `is_excluded` **cannot** fix that same-id class, and the attempt was reverted. `EnhancedETLPipeline`'s auto-exclude cascade (`src/etl/enhanced_pipeline.py:1899-1926`) keys on `(sorted raw master ids, scores)` for a `game_date`, which both copies of a same-id duplicate share exactly. Excluding one therefore makes the next import touching that fixture exclude its twin, and the match leaves the rankings entirely. Measured: 50 rows excluded 2026-08-31, 48 twins gone within minutes (`process-missing-games` runs every 15 min); all 100 restored, `games.is_excluded` back to 8,088. The merge-damage class is immune only because its two copies carry differing raw ids, so the excluded copy's cascade key never matches the survivor's — the same property that distinguishes the two classes. `scripts/exclude_merge_duplicate_games.py` now refuses the same-id class at every scope and prints `SAME_ID_NOTE` explaining why. Fixing it needs the source: a `game_uid` stable across recipe changes and across a team holding two provider ids, or an importer matching on merge-resolved fixture identity. Diagnosis of the 842: ~97% modular11, whose uid moved from integer team ids to UUIDs so an Apr 2026 re-scrape did not collide with its own Dec 2025 rows; the rest gotsport/tgs where one team held both a registration id and a real team id.
- **Update (2026-09-08)**: Verified — the repair half shipped (`scripts/exclude_merge_duplicate_games.py`, `2d84ab056`, PR #1068). The prevention half has not: a repo-wide search finds no caller at all — no merge script and no workflow invokes it — so it is still a manually-remembered step after every merge batch.

### Modular11 import files some U13 fixtures onto the U14 team row

- **ID**: IMP-138
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: Modular11 / MLS NEXT import path; `games` rows whose `source_url` is under `modular11.com`
- **Why**: `Los Angeles Football Club U14 HD` carries games such as `LAFC U14 HD 6-2 San Diego FC U13 HD` on the same date and with the same score as the real `LAFC U13 HD 6-2 San Diego FC U13 HD`. The same shape repeats against FC Golden State, SoCal Reds, Santa Barbara, LA Galaxy, Total Futbol Academy and Phoenix Rising. Both LAFC rows are genuine squads, so this is game mis-attribution rather than a team duplicate — it inflates the U14 row's record and makes shared-fixture duplicate detection fire on legitimately distinct team pairs across MLS NEXT clubs (Hoover-Vestavia HD/AD, Michigan Wolves U15/U16, Albion SC U15/U16). Surfaced while sizing duplicate candidates on 2026-08-27; Modular11 was excluded from that work by operator decision, so this was noted rather than pursued.
- **Noted**: 2026-08-27

### Unknown-name backfill has no record of a failed resolution attempt

- **ID**: IMP-139
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/backfill_unknown_team_names.py` (`fetch_placeholder_teams`), `.github/workflows/backfill-unknown-team-names.yml`
- **Why**: Candidates are selected only by the placeholder name pattern plus the new provider-ID bound, so nothing marks a team as already tried and 404'd, or tried and returned no usable name. Every rankings-space placeholder that fails to resolve is re-fetched by the every-15-minute cron at 12s/call indefinitely, on the shared per-IP GotSport WAF budget that workflow's own cron comment exists to protect, and the pool cannot drain below its unresolvable residue. The run summary already prints "Gone from GotSport (404, needs marking)" — the marking is the missing half. Wants a persisted attempt/outcome marker (a `teams` column or a small attempts table) that `fetch_placeholder_teams` excludes on. Surfaced by the code review of the max-provider-id change on 2026-08-28; out of scope for that PR.
- **Noted**: 2026-08-28

### Seven hand-copied GotSport resolvers, two of them still reading keys that do not exist

- **ID**: IMP-142
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/backfill_missing_state_codes.py:152-157`, `scripts/backfill_missing_club_names.py:103-108`, plus five more copies in `scripts/`
- **Why**: Seven scripts carry a byte-identical `GotSportResolver` against `team_ranking_data/team_details`, differing only in timeout default and output key prefixes. Four were corrected on `fix/opponent-cohort-inheritance`; these two still read `full_name`/`state`/`age`/`gender`, which that endpoint has never returned. Both run in `update-missing-club-and-state.yml` (Mon 10:00 UTC), currently failing — the state backfill's entire GotSport tier is inert because `_normalize_to_state_code` receives `""` on every call while the run reports success. `state_code` is load-bearing for location-scoped fuzzy matching. Fix both, then extract one dependency-free resolver into `src/utils` so the next copy cannot drift; `src/utils/team_association_map.py` and `src/utils/age_group.py` are the precedent for a module these three-package workflows can import. Note `src/scrapers/gotsport.py:1008` `_zenrows_get` already probes this endpoint with a retry policy and an outcome taxonomy, and `scripts/assign_team_states.py:395-414` uses it -- but it imports bs4, which the hygiene workflow does not install, so it can be the model rather than the import. `tests/unit/test_team_association_map.py` now derives the script list from the endpoint and names these two in `KNOWN_BROKEN`; fixing one turns that list red until it is removed.
- **Noted**: 2026-08-30
- **Update (2026-08-30)**: The impact claim in this entry was wrong, measured after writing it. Missing `state_code` is a TGS problem, not a GotSport one: of 2,345 teams without a state, 2,192 are TGS and only **6** have a GotSport alias at all, so correcting that resolver reaches six rows. `backfill_missing_club_names.py` is not broken either -- it reads `club_name`, which is a real key, and GotSport genuinely returns `"club_name": null` for its candidates (verified against four live records). Both steps report 0 because there is nothing to find. What remains is consistency, not impact: two copies still read keys the endpoint lacks, and a future caller will copy whichever it opens first. `src/utils/gotsport_team_details.py` now exists as the extraction target.

### The unknown-opponent due-diligence gate approves when it has no evidence

- **ID**: IMP-143
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/due_diligence_unknown_opponents.py:362-450`
- **Why**: Every component of `core_ok` is spelled `!= "mismatch"`, so a missing provider field scores `"unknown"` and passes. A GotSport outage therefore disables the gate wholesale rather than closing it, and `apply_unknown_opponent_matches.py` then upserts `team_alias_map` and updates `games` FKs under the service-role key on matches nothing compared. Games are immutable, so a bad backfill is not cleanly reversible. Should require positive cohort evidence to approve rather than absence of contradiction. Related: IMP-144 makes the no-evidence path more likely. Round-two review measured the other side of the same gate: `team_association` agrees with stored `state_code` on only 91.3% of probes, so activating `state_check` demotes roughly one correct link in twelve to manual review. The verdict logic is inline in `main()` between two Supabase round trips and cannot be tested; lifting it into a pure `_verdict(unknown, team, ...)` is the precondition for measuring either effect.
- **Noted**: 2026-08-30
- **Update (2026-09-08)**: Exposure is higher than this entry assumes. CLAUDE.md's claim that only `export_unknown_opponents.py` builds a resolver on the weekly run is wrong: `due_diligence_unknown_opponents.py:282` and `discover_teams_from_opponents.py:543` both construct `GotSportResolver()` unconditionally, with no flag. Verified 2026-09-08. So the vacuous-approval gate at `due_diligence_unknown_opponents.py:429-439` is reachable on live weekly runs, not theoretical.

### No GotSport resolver throttles, retries, or identifies itself

- **ID**: IMP-144
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: all seven `GotSportResolver` copies in `scripts/`
- **Why**: Each uses a bare `session.get` with no `Retry` adapter, no inter-request delay and the default `python-requests` User-Agent, against an endpoint family the `scraper-patterns` skill documents as CloudFront-WAF-fronted with a multi-minute per-IP lockout. A 403 lockout, a 429, a timeout and a genuine 404 are indistinguishable at the `except Exception` boundary. Partly addressed on `fix/opponent-cohort-inheritance`: a 404 is now cached as the permanent answer it is, and transient failures are no longer cached, so a WAF block costs one retry per row rather than poisoning the id for the run (measured at ~1.6 resolve calls per team). Still absent everywhere: the prescribed `Retry(total=2, backoff_factor=1, status_forcelist=[429,500,502,503,504])`, an explicit User-Agent, and a `random.uniform` delay. Do not hand-roll an eighth policy -- `src/scrapers/gotsport.py` already has `get_waf_breaker()` and `_zenrows_get`; the open question is how to reach them from a workflow that installs only supabase, python-dotenv and requests.
- **Noted**: 2026-08-30
- **Update (2026-09-08)**: Corrected — the claim that no resolver retries is not uniform. `scripts/backfill_unknown_team_names.py` has had `get_waf_breaker()` plus a 2-attempt retry and 12s delay since 2026-08-18 (`eebe2b757`), predating this entry. The other copies (`auto_match_unknown_opponents.py`, `discover_teams_from_opponents.py`, `export_unknown_opponents.py`, `due_diligence_unknown_opponents.py`) still have none; two sleep 0.2s with no retry. No copy sets a custom User-Agent — that half of the entry holds everywhere.

### The repo asserts two contradictory readings of GotSport's display_age_group

- **ID**: IMP-145
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `scripts/backfill_unknown_team_names.py:27-29` vs `scripts/discover_teams_from_opponents.py:_build_team_metadata`
- **Why**: The backfill states as a deliberate decision that `display_age_group` is the registered event cohort rather than the birth-year cohort, that the two disagree across the Aug 1 rollover, and that it therefore never writes `age_group`. Discovery now treats the same field as its highest-precedence cohort source, and due diligence compares it against stored rows. Live sampling on 2026-08-30 found them agreeing, but that is one point in the season — the claimed divergence is a rollover effect. One position is wrong; whichever loses, the other's comment should be corrected in the same change so the contradiction does not outlive it. Same hazard class as the TGS U-age labels in CLAUDE.md.
- **Noted**: 2026-08-30

### Repair the 2,937 teams stored outside the boarded cohorts

- **ID**: IMP-147
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `teams.age_group` (database column), `scripts/repair_out_of_board_cohorts.py`
- **Why**: This is three populations, not one. **u8/u9 (2,871 rows) are accurate** -- GotSport reports real U8 and U9 teams and PitchRank does not board them; leave them. **u20 (1,597) needs season evidence**: a blanket fold into u19 would put aged-out 2006 squads on the U19 board, because a stored U-age does not say which season wrote it (sampled names include `Milan 2006` and `Delaware County FC 2006 1` alongside genuine `U19 MLS NEXT HD`). **The impossible cohorts (u0/u3-u7/u21) are the tractable part** and are handled by `scripts/repair_out_of_board_cohorts.py`.
- **Noted**: 2026-08-30
- **Update (2026-09-08)**: **Re-derive the counts before acting** — the figures in this entry do not foot (u8/u9 2,871 + u20 1,597 exceeds the title's 2,937). Verified 2026-09-08: `scripts/repair_out_of_board_cohorts.py:45` covers u0-u7/u21/u22 and deliberately excludes u8/u9 and u20, so u20 has no repair path. The creation path is still live, not historical debt — `src/utils/age_group.py:32-47` passes through any `u<N>` with no range check, and IMP-149 is still open.

### Carry provenance on a derived cohort so an opponent's can never be persisted

- **ID**: IMP-148
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/auto_match_unknown_opponents.py::build_unknown_profile`, `scripts/discover_teams_from_opponents.py::_build_team_metadata`
- **Why**: The derivation ladder ends in `top_known_team_age_group`, the cohort of the team this one played, and the CSV column that carries it downstream is indistinguishable from a cohort the team's own record supplied. `fix/opponent-cohort-inheritance` made the provider tier work so the fallback fires far less, but it is still reachable: a row with no provider data and an unparseable name is created in its opponent's cohort. The same applies to state, which is worse after that change — the export now writes the team's own mapped association into `unknown_state_used`, so discovery's comment calling it "the opponent's state" is stale and it discards authoritative data on a transient lookup failure. Tag each field with the tier that produced it, let candidate narrowing use an opponent-derived value, and refuse to persist one.
- **Noted**: 2026-08-30
- **Update (2026-09-08)**: Verified — the state-staleness half is fixed (`discover_teams_from_opponents.py` now describes `unknown_state_used` correctly; no `top_known_team_*` reference remains there). The core ask is untouched: `UnknownProfile` (`scripts/auto_match_unknown_opponents.py:156-161`) still carries plain untagged `age_group`/`gender`/`state_code`, and `build_unknown_profile` still falls back to `top_known_team_*` with no tier tag and nothing refusing to persist it.

### GotSport labels aged-out teams U21, and the chain now creates them

- **ID**: IMP-149
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `src/utils/age_group.py`, consumed by `scripts/discover_teams_from_opponents.py`
- **Why**: `team_utils.calculate_age_group_from_birth_year` returns None for a computed age of 21 because 2006 has aged out, but the shared normalizer passes `u21` through, so discovery creates the team and the queue scrapes it forever. Live probing found 11 of 12 sampled 2006-cohort teams labelled `U21`, roughly 21 of 2,553 distinct unknown ids per weekly run. Refusing it outright is not the fix — a bare None hands the row to the opponent fallback — so this wants an explicit aged-out outcome that skips creation with a reason, alongside the IMP-147 cleanup of the 8 `u21` rows already stored.
- **Noted**: 2026-08-30
- **Update (2026-08-30)**: The impossible-cohort pass ran. 13 teams were re-resolved onto real boards (u3 -> u10/u12/u13/u14/u15) and u3 fell from 44 to 31. 58 candidates were deliberately left alone: their GotSport record reads exactly one cohort higher than stored, which is the Aug 1 rollover rather than a correction, so writing it would move them between two unboarded cohorts and churn again next August. 6 more have no cohort at the provider. Remaining here: the u20 population, which still wants its own evidence-based pass.

### A blank state_code is decided as a fill but can never be written

- **ID**: IMP-150
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/assign_team_states.py` `_decision` / `apply_decision`, `apply_team_state` in `supabase/migrations/20260829120000_add_team_state_provenance.sql`
- **Why**: `_decision` normalizes `state_code` with `(... or "").strip() or None`, so a team stored blank rather than NULL records `pre_image: None` and is classified as a fill. `apply_team_state` then predicates on `state_code IS NOT DISTINCT FROM p_expected_state_code::character(2)`, which NULL cannot match against a blank-padded `'  '`, so the write returns false, the run reports the team as "moved", and the next run decides it identically — a team that can never be filled and is retried forever. Zero rows are affected today (3,080 NULL, 0 blank, measured 2026-08-31), but `scripts/import_teams_enhanced.py:73` still writes `""` on a CSV import and `scripts/match_state_from_club.py:180-189` pages for both spellings because they have existed. Fix by carrying the raw pre-image separately from the fill/correction classification, or by making the predicate accept both blanks. Found by Codex on #1066; pre-existing, not introduced by `--fills-only`. Related: #1065 closed the creation side of the same split in `GameHistoryMatcher._resolve_state_from_club`.
- **Noted**: 2026-08-31

### `--team <uuid>` on a deprecated team logs a false "no stored state" in the probe ledger

- **ID**: IMP-151
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/assign_team_states.py` `build_snapshot` — the `only_team` branch and the `stored_states` map
- **Why**: `stored_states` is built from `fetch_live_teams`, which filters `is_deprecated = false`, but the `only_team` branch sets `candidates = [only_team]` with no membership check against it. `team_alias_map` carries no such filter, so a deprecated id still resolves a GotSport alias and is still probed. The resulting `team_state_probe_log` row records `stored_state_code` NULL and so `agreed` NULL, which reads as "we asked and it had no state" rather than "it was not in the snapshot" — and the contradiction audit that consumes this ledger cannot tell those apart. Measured 2026-08-31: exactly 2 deprecated teams carry a GotSport alias and both have a `state_code`, so the blast radius is small today, but a row is permanent once written. Fix: check membership in `stored_states` in the `only_team` branch and warn-and-skip rather than probing, which also saves a wasted paid ZenRows call. Raised by two independent reviewers on the probe-ledger branch and kept out of that change to keep it scoped to the ledger.
- **Noted**: 2026-08-31

### Three tables in the team-state provenance migration still carry anon's default grants

- **ID**: IMP-152
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `supabase/migrations/20260829120000_add_team_state_provenance.sql` — `team_state_audit`, `team_state_review_queue`, `tgs_events`
- **Why**: `pg_default_acl` grants anon and authenticated `arwdDxtm` on every new public relation here, and RLS governs SELECT/INSERT/UPDATE/DELETE but not TRUNCATE or REFERENCES — so a deny-all policy leaves those two intact. Verified live 2026-08-31: all three read `anon=arwdDxtm/postgres,authenticated=arwdDxtm/postgres` in `pg_class.relacl`, while the two tables shipping `REVOKE ALL ON public.<table> FROM anon, authenticated` (`20260801000000_age_group_rollover_2026_27.sql:84-85`) read only `postgres` and `service_role` — the remedy works and does not lock out the ETL writer. `team_state_audit` is the append-only ledger every state write lands in; emptying it destroys the provenance `revert_team_states` depends on. `team_state_probe_log` ships the REVOKE plus a test scoped to itself, because widening that assertion to all four would fail for these three. Fix: one REVOKE per table in a follow-up migration, then widen the test to loop over `NEW_TABLES`. Worth deciding at the same time whether the REVOKE belongs in the shared RLS convention so new tables get it by default. Raised during the probe-ledger review and kept out of that change to keep it scoped.
- **Noted**: 2026-08-31

### anon retains DELETE and TRUNCATE on public.user_profiles

- **ID**: IMP-153
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `public.user_profiles`; lockdown migration `20260610120000`
- **Why**: Verified live 2026-08-31: `user_profiles` reads `anon=rdDxtm/postgres`. The 2026-06-10 lockdown revoked INSERT and UPDATE and left DELETE (`d`) and TRUNCATE (`D`). DELETE is constrained by RLS policies; TRUNCATE is not governed by RLS at all. Not reachable today — anon reaches Postgres only through PostgREST, which exposes no TRUNCATE verb — so this is defence-in-depth rather than a live hole, and the table's current policies should be read before acting. `user_profiles` holds the Stripe subscription state `reconcile-stripe-daily.yml` reconciles, so loss would be user-visible. Typed investigate because the right fix depends on which roles legitimately delete rows today. Surfaced incidentally by a security review on the probe-ledger branch; unrelated to that change.
- **Noted**: 2026-08-31

### The `--team --execute` write path has both its guards and no test of either

- **ID**: IMP-155
- **Status**: open
- **Type**: plan
- **Category**: testing
- **Where**: `scripts/assign_team_states.py` — `report_team`
- **Why**: `report_team` is the terminal writer of the documented one-off route `--team <uuid> --execute`, and two mutations survive the whole suite: removing the `decision["action"] != "apply"` refusal, and neutering `if not execute: return`. The first would write a decision the tiers deliberately queued — a DC relabel under R8, a value the operator reverted under R17, a curated club, a Tier C/E correction — unattended, exiting 0. The second makes the documented dry run write. CLAUDE.md § Code Quality requires a dry-run guard on every mutating path; this one has the guard and nothing pinning it. Pre-existing and untouched by the contradiction-audit branch, whose diff hunks jump 1307 → 1435. It matters more now because that branch's first review round fixed a P1 filed against exactly this route, and its three new named-team tests all stop at `build_snapshot` and assert the *decision* where the defect was the *write*. Mutation-verified in an isolated worktree 2026-09-01; the operator chose to backlog it rather than widen that PR.
- **Noted**: 2026-09-01

### `--limit` validates itself where the argv test harness cannot reach it

- **ID**: IMP-157
- **Status**: open
- **Type**: direct
- **Category**: dx
- **Where**: `scripts/assign_team_states.py` — the `--limit` check inside `apply_snapshot`, against the argv guard block in `main()`
- **Why**: The contradiction-audit branch added four numeric-flag guards to `main()`'s argv block, deliberately ahead of the credential check so they are testable: CI sets no keys, so anything after that check exits 1 for every argv and a test asserting the exit code alone could never fail. `--limit`'s near-identically-worded check ("it would apply all but the last") stayed buried in `apply_snapshot` and gets none of that, so `--execute --snapshot missing.json --limit -1` dies on the missing file rather than on the negative limit. Two same-shaped validations in two places for no stated reason; moving `--limit`'s up makes all three uniform and reachable by the harness that branch already built.
- **Noted**: 2026-09-01

### `--workers` is unbounded while its three sibling numeric flags are guarded

- **ID**: IMP-158
- **Status**: open
- **Type**: direct
- **Category**: dx
- **Where**: `scripts/assign_team_states.py` — the `--workers` argument in `main()`
- **Why**: `--workers 0` raises a bare `ValueError` out of `ThreadPoolExecutor` rather than the named refusal every other numeric flag on this tool now gives; `--limit`, `--probe-limit` and `--reprobe-after-days` all reject out-of-range values by name. Cosmetic rather than dangerous — it fails closed, before any paid call — but it is the one remaining flag that fails as a stack trace. Surfaced by an api-usage review on the contradiction-audit branch and kept out of it as pre-existing.
- **Noted**: 2026-09-01

### An interrupted probe run still loses the calls that were in flight

- **ID**: IMP-159
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/assign_team_states.py` — `probe_associations`
- **Why**: The contradiction-audit PR put the probe-log flush in a `try/finally`, which closed the large loss — before it, a Ctrl-C discarded everything buffered since the last drain. What remains is the calls already in flight across the pool when the interrupt lands. Measured on the shipped code with a stubbed 2 ms round trip: n=1200 workers=10 → 72 paid against 60 ledgered (12 lost); n=200 workers=10 → 79 paid against 60 ledgered (19 lost). The loss is bounded by `--workers` rather than by queue depth, because `Executor.map`'s result generator cancels pending futures as the exception unwinds, before the pool's `__exit__` — which is also why an interrupt does not keep spending through the remaining ~1,100 candidates. The lost teams stay due and are re-bought next run. Closing it means bounded submission — a window of futures, drained and resubmitted — rather than `Executor.map`, which is real machinery for a bounded cost, so it was typed plan and kept out. Two round-3 reviewers appeared to contradict each other here; both reproduce, one at n=5/workers=1 where a single worker races ahead, the other at production shape. The production shape governs.
- **Noted**: 2026-09-01

### Tier B tells both halves of a two-and-two club to swap states, forever

- **ID**: IMP-161
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/assign_team_states.py` — `club_derived_state`, the exclude-the-team-being-decided count
- **Why**: A club stored as exactly two teams in state X and two in Y makes every one of its teams a correction: excluding the team being decided leaves its own side below the two-team floor and the other side as the only meaningful state. Seen in one free-tier dry run on 2026-09-02: RSL-AZ Yuma (2 CA + 2 TX, and really Arizona) proposed as two CA→TX and two TX→CA, Amigos FC (2 MO + 2 CA + 1 KS) the same shape. Applying the swap recreates the 2/2 split, so the club oscillates every sweep and never settles; with Tier A on, only the teams the provider answers escape it. The fix is a test for the shape — abstain when excluding the team would drop its own side below the floor while the rest of the club is not a clear majority — plus a fixture at 2/2 and 3/2 (3/2 already behaves: excluding a minority team leaves 3 v 1 and fires correctly).
- **Noted**: 2026-09-02

### A state correction leaves the full-name `teams.state` column contradicting the code it just wrote

- **ID**: IMP-162
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `apply_team_state` (`supabase/migrations/20260829120000_add_team_state_provenance.sql`) and `decide` in `scripts/assign_team_states.py` at the `stored value was reported` test
- **Why**: The RPC writes `state_code` and provenance and leaves `state` as it was, so after a Tier A correction the row reads e.g. `state_code = TX, state = 'Alabama', state_source = tier_a`. Measured 2026-09-02: 158 live teams carry a full-name column that contradicts their code (17 TX/"Washington" under Valencia CF with no provenance, 16 HI/"Washington" on Hawaii Rush set by the operator, 11 AZ/"California" on Legends FC AZ, and ~100 tier_a rows whose old name survived). The `decide` reported test reads a non-empty `state` as "a provider reported this" and queues instead of applying, so a stale name from a backfill now protects a code the provider has already overruled. Decide whether a correction should clear the name, rewrite it to match, or whether the reported test should require the name to agree with the code before it counts.
- **Noted**: 2026-09-02

### A cached probe answer is not bound to the alias it was bought through

- **ID**: IMP-166
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/assign_team_states.py` `fetch_recent_probes`, `bought_answers`, `probe_list`, `anchor_candidates`
- **Why**: The ledger reader keys a cached answer by team, so an answer bought via an alias later quarantined (`review_status = pending`) would be reused for up to `REPROBE_AFTER_DAYS` while the approved sibling alias is suppressed, and anchor mode prefers such a cached mapping. Measured 2026-09-02: 0 probe rows in the window for the 30 affected masters, so latent. Fix: the reader returns `provider_team_id` and a cached answer is reused only when it matches the alias the approved-only reader would pick now. Touches paths the `C:/pitchrank-state-converge` worktree also edits. Raised by the Codex peer reviewer.
- **Noted**: 2026-09-02

### Collapse the five copies of get_gotsport_provider_id into enqueue_helpers

- **ID**: IMP-167
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `scripts/enqueue_active_teams.py`, `enqueue_yesterday_games.py`, `enqueue_discovery_teams.py`, `enqueue_safety_net.py`, `enqueue_viewed_teams.py`, `audit_polluted_gotsport_aliases.py`, `maintain_gotsport_direct_id_aliases.py`, `enqueue_helpers.py`
- **Why**: `GOTSPORT_PROVIDER_CODE` plus `get_gotsport_provider_id` is byte-identical in all seven, and `enqueue_helpers.py` now exists expressly to hold what the enqueue scripts share. A `providers` change — a second GotSport row, a code rename, a `.single()` → `.maybe_single()` fix — has to land five times, and missing one leaves a job selecting against a stale id, which reads as "enqueues nothing" rather than an error. Pure move plus an import swap; the existing suite covers all five. Left out of the viewed-teams PR because it edits four daily jobs that change did not otherwise touch. Raised by the consistency reviewer; user chose to defer, 2026-09-03.
- **Noted**: 2026-09-03
- **Update (2026-09-07)**: Now seven copies, not five — `audit_polluted_gotsport_aliases.py` and `maintain_gotsport_direct_id_aliases.py` carry it too, so the count in the original text was corrected. The two new ones are not enqueue jobs, which is why a grep over `enqueue_*.py` missed them.

### Recover an orphaned ZenRows batch job instead of reporting nothing to recover

- **ID**: IMP-170
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/batch_drain_queue.py` — `run_batch`'s `exc.job is None` branch; `.turbo/specs/zenrows-batch-bulk-scrape.md` Risks
- **Why**: When the initial `POST /jobs` times out, `BudgetExpired.job` is `None` and the run prints "Submission failed before a job existed" and exits — but the job may well have been accepted and is billing. The spec states as fact that "the verified contract exposes no endpoint that lists jobs or looks one up by idempotency key", and the vendor OpenAPI (`ZenRows/zenrows-python-sdk`, `docs/openapi.yaml`, read 2026-09-03) contradicts it twice: `Idempotency-Key` on `POST /jobs` is documented as "Re-submitting with the same key returns the original response (or 409 on body mismatch)", and `GET /jobs` (`operationId: listJobs`) exists. So replaying the same keyed create inside the cleanup allowance recovers the handle, and if the create never landed the replay simply creates the job — correct either way. **Correct the spec's premise in the same change**, since the later slices read it and it also justifies the manual-dashboard-only recovery path. Parked to keep the fetching-layer PR to defect fixes.
- **Noted**: 2026-09-03
- **Update (2026-09-08)**: Verified — the spec half is done: `.turbo/specs/zenrows-batch-bulk-scrape.md` no longer carries the false no-lookup claim and R13 documents `Idempotency-Key` correctly. The code fix is not: `scripts/batch_drain_queue.py:1223-1225`'s `job is None` branch still prints failure and returns 1 with no replay.

### Lift a chunking helper into src/utils/ instead of a seventh local copy

- **ID**: IMP-171
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `scripts/batch_drain_queue.py:_chunked`, `scripts/prepare_prospective_match_predictions.py:226`, `scripts/settle_prospective_match_predictions.py:69`, `scripts/import_teams_enhanced.py:240`, `src/etl/enhanced_pipeline.py:2720`, `scripts/enqueue_user_interest_teams.py:80`, `scripts/find_regid_duplicate_merges.py:79`
- **Why**: There is no shared chunk helper in `src/utils/`, so every caller re-rolls one under three different names, and 14 further files inline `for i in range(0, len(x), 100)` for the same `.in_()` batching (counted 2026-09-03 over `src/` and `scripts/`). `itertools.batched` would settle it but is 3.12+ and this repo targets 3.11, so a helper is genuinely needed rather than merely tidy. The cost of the status quo is that a fix to the batching rule — an empty-input guard, a size assertion against the documented 100-id cap — needs the same edit in seven places with nothing linking them. Deferred from the ZenRows fetching-layer PR as out of scope: creating the util means rewiring unrelated scripts, each needing its own verification.
- **Noted**: 2026-09-03
- **Update (2026-09-08)**: Re-counted 2026-09-08 — six of the seven named sites still duplicate it (`batch_drain_queue.py:810`, `prepare_prospective_match_predictions.py:226`, `settle_prospective_match_predictions.py:69`, `import_teams_enhanced.py:240`, `src/etl/enhanced_pipeline.py:2720`, `find_regid_duplicate_merges.py:79`). `enqueue_user_interest_teams.py` has moved off. There is now an eighth copy under a fourth name at `scripts/enqueue_helpers.py:42`.

### Give the event-roster CLI the same seeding intake as the app

- **ID**: IMP-174
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `scripts/scrape_event_roster.py` (the `roster.json` path in `main`), `src/tournaments/event_roster_intake.py`, `src/tournaments/seeding_run_store.py`
- **Why**: The CLI still writes `reports/seeding/gotsport_<id>/roster.json` and nothing reads it — a grep over `*.py`, `*.md` and `*.yml` on 2026-09-05 finds only the writer. The Streamlit path now converts a walk into a seeding run instead, so a scrape started from the terminal produces an artifact the app cannot open while a scrape started from the app produces one the terminal cannot. The option not taken when wiring the UI: have the CLI call `to_seeding_rows` and the `SeedingRun` writer, so both entry points land in the same place. Deliberately left out to keep the UI change to one path.
- **Noted**: 2026-09-05

### Fold the WAF-clearing fetch mode into the one GotSport event scraper

- **ID**: IMP-177
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `src/scrapers/gotsport.py:1466`, `src/tournaments/gotsport_event_roster.py` `EVENT_BASE`
- **Why**: Both define the same `EVENT_BASE`, both walk `.../schedules?group=`, and they share no code. The newer one exists because the older meets an AWS WAF challenge on `/org_event/*` that only a JS-rendered proxied fetch clears. That is a fetch-layer difference, not a parsing one, so a single walker taking its fetcher as a parameter would leave one implementation to fix when GotSport's markup next moves. These two have already drifted once: IMP-173 records the charset fix that landed in the roster module's fetch and not in the other.
- **Noted**: 2026-09-05

### Carry a club name through the scraped seeding rows

- **ID**: IMP-178
- **Status**: open
- **Type**: direct
- **Category**: ux
- **Where**: `src/tournaments/event_roster_intake.py` `to_seeding_rows`, `tournament_intake.py` `_render_seeding_override`
- **Why**: `EventRosterTeam` carries no club name, so every scraped row has `club_raw=""`: the results table's "Club" column is blank and the manual-override heading renders as a leading separator followed by the team name. This is legibility only — nothing in the seeding path matches on a club name, since `search_gotsport_teams` and `make_exact_name_lookup` both read the team name and cohort alone — but it is what an operator reads while deciding the rows the scrape could not link. The team page the walk already fetches for the rankings link is where a club name would come from, at no extra request.
- **Noted**: 2026-09-05

### Consider saving a scraped seeding run without a button press

- **ID**: IMP-179
- **Status**: deferred
- **Type**: plan
- **Category**: ux
- **Where**: `tournament_intake.py` `_run_event_roster_scrape`, `_autosave_seeding_run`
- **Why**: A scraped run is deliberately not saved for the operator: the run name is widget-backed and only applies on the following script run, and an automatic save let a cheap two-division probe replace a completed full walk on disk, let a second event overwrite the first under the first's name, and interacted with the resume selector so a saved run reloaded over a fresh scrape. Requiring a name and a press removes all four. The walk itself is not at risk — `_write_event_roster_recovery` drops the rows and resolutions to `reports/seeding/gotsport_<id>/last_walk.json` before any session-state write — so the remaining cost is that recovering from that file is a manual step.
- **Noted**: 2026-09-05
- **Trigger**: The manual step proves annoying in practice. The safe shape is a save that refuses to replace a more complete run of the same event, mirroring the guard `_write_roster` already applies to the CLI's roster file.
- **Update (2026-09-09)**: Recovering that file is no longer manual in the sense written above — `_render_recovered_walk` offers it back with one press whenever the disk holds more teams than the tab does. The entry stands: this is about *saving* a named run without a press, which is still deliberate, and the reload parks a run rather than naming one.
- **Update (2026-09-24)**: `save_run` refuses a different source (another event, or a paste against an event) and a partial walk over a complete walk of the same event (`RunSourceChanged`). A roster refused that way detaches from the open run, resets the resume selector in the browser, and waits for a new name. A walk into a named run of the same event saves before matching. Still deferred: an unnamed scrape waits for a name and a press.

### Give the GotSport event walk one home for its tuned concurrency

- **ID**: IMP-181
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `tournament_intake.py` `_SEEDING_EVENT_WORKERS`, `scripts/scrape_event_roster.py`'s `--concurrency` default
- **Why**: Both callers of `scrape_event_roster` pick 8 workers, independently. The scraper itself defaults `max_workers=1` deliberately — serial is the safe default for a caller that has not thought about it — so the 8 is a caller policy rather than a restatement of a module default, and there is nowhere it currently belongs: `gotsport_event_roster.py`'s module constants are all structural (URLs, regexes, headings), and `config/settings.py` carries no per-provider tuning of this kind. If GotSport tightens its WAF and the safe concurrency drops, both numbers have to move together with nothing linking them. Deciding the home is the work; the move itself is two lines.
- **Noted**: 2026-09-05

### Honour an injected Supabase client without also requiring the env vars

- **ID**: IMP-182
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `src/tournaments/event_roster_intake.py` `resolve_master_ids`
- **Why**: The function takes `client_factory` so a caller can hand in a live client, and the Streamlit app does exactly that. But it still returns `({}, ["No Supabase credentials..."])` when `SUPABASE_URL` is absent, or when neither `SUPABASE_SERVICE_ROLE_KEY` nor `SUPABASE_KEY` is set, before `client_factory` is consulted — so an injected client is only honoured when env vars the caller does not own happen to be set. In the app this is masked because `config/settings.py` loads them at import, but a caller supplying its own client and no env would silently get name matching instead of the direct-id resolution the walk paid for. The guard exists for the CLI, which builds its client from those values; splitting the two paths would let the injected client stand on its own.
- **Noted**: 2026-09-05

### Give an ambiguous exact-name match candidates the operator can tell apart

- **ID**: IMP-183
- **Status**: open
- **Type**: direct
- **Category**: ux
- **Where**: `src/tournaments/roster_resolver.py` `make_exact_name_lookup`, and the `len(local) > 1` branches in `resolve_row` and `event_roster_intake._relink_known_id`
- **Why**: When a team name matches two live teams in one cohort, both branches build `candidates` as `{"team_id_master": id}` only, so `_seeding_candidate_label`'s `team_name or team_id_master` fallback renders the review card as a list of bare UUIDs — the operator cannot choose between them without looking each one up by hand. `make_exact_name_lookup` already selects `team_id_master,team_name` and discards the name on the way out, so the fix is in the shared lookup's return shape rather than in either caller; both would then match the richer shape `resolve_row` produces from a GotSport search hit. Left out of the event-intake change because the two callers are consistent with each other today and changing `ExactNameLookup`'s contract touches the pasted path as well.
- **Noted**: 2026-09-05

### Populate `tgs_events` and implement Tier D, the only path the stateless TGS teams have

- **ID**: IMP-184
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/scrape_tgs_event.py` (`get_event_details` at :394, the stale comment at :587), `scripts/assign_team_states.py:563-567`, `tgs_events` (created by `supabase/migrations/20260829120000_add_team_state_provenance.sql`)
- **Why**: The table shipped and nothing has ever written to it -- 0 rows, no backfill script, and the scraper was never wired to upsert it -- so `assign_team_states.py` hardcodes `tier_d_ready = False` and prints "Tier D is not implemented; it fires for nothing". That leaves **2,192 live stateless TGS teams (~96% of every remaining blank `state_code`)** with no assignment path, all of them ranked and therefore absent from every state board, and the count grows each Monday via `tgs-event-scrape-import.yml`. Club evidence cannot rescue them: 1,434 sit under clubs with <75% single-state dominance and 443 under clubs with no stated sibling at all. The fix is cheaper than it looks -- `get_event_details` already calls `get-event-details-by-eventID` on every event and keeps only the name, and that payload was verified live to carry `eventTypeID`, `stateCode`, `city`, `zip` and `country`, so the ongoing upsert costs **zero extra API calls**; backfill is 558 one-off calls, since all 168,976 TGS games carry a recoverable event id in `source_url`. Note the event's own `stateCode` is where the tournament was held -- a travel signal -- so it stays a gate and cross-check, with the participant-modal state as the value, per the tier design. While in there, fix `:587`, which still says state "will be matched later via club name script"; that script is Step 4 of `update-missing-club-and-state.yml` and is `if: false`.
- **Noted**: 2026-08-31

### Provider matchers stamp a constant `state_code` with no provenance

- **ID**: IMP-185
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/models/affinity_wa_matcher.py:390`, `src/models/playmetrics_matcher.py` `_create_new_playmetrics_team`
- **Update (2026-09-15)**: The PlayMetrics league path now takes the state from each CSV row (written by `scrape_playmetrics_league.py` from the league's governing body) rather than the `"WI"` constructor constant, so a second state (NC, governing body 1207) files its teams correctly. It writes `state_code` only, no longer the full-name `state` column, so `assign_team_states` can still correct it. Still a per-league constant with no `state_source`, and affinity_wa is untouched.
- **Why**: Two tracked creation paths write a fixed state rather than deciding one: affinity_wa hardcodes `"WA"` (729 teams, 100% WA) and playmetrics' league path takes `default_state_code` (702 teams, 92% WI). A third population, 25 NJ teams stamped by a Squadi matcher, is **historical only**: no Squadi writer exists in any tracked file (`.turbo/plans/squadi-scraper.md` is the design note, not an implementation), and the unmerged branch that carried `SquadiGameMatcher` was deleted 2026-09-07 — so those rows need a data fix, not a code fix, and nothing recreates them. None sets `state_source`, so the corrector cannot distinguish a provider-reported state from a constant. Worse, the constant feeds Tier B's documented blind spot -- a club whose teams are uniformly stamped agrees with itself and is never corrected, which is why only **1 of 729** affinity_wa teams was touched by the full 2026-08-30 sweep. A visiting out-of-state club would be mislabelled permanently and invisibly. There is already a correct pattern to mirror in the same file family: PlayMetrics' tournament path passes `default_state_code=None` and falls back to `_resolve_state_from_club(club_name)`. No contamination is measurable in affinity_wa's names today (0 of 729 clubs read as out-of-state), so this is a latent-risk and provenance fix rather than a live-damage one.

### Ingest Fall League Washington from the sctour JSON API

- **ID**: IMP-190
- **Status**: deferred
- **Type**: plan
- **Category**: feature
- **Where**: new `scripts/scrape_sctour_league.py`; `src/models/affinity_wa_matcher.py` for reuse; `.github/workflows/wa-scraper.yml` if it joins the weekly run
- **Why**: A WA league PitchRank does not ingest, on Affinity's newer Blazor platform rather than the classic `.asp` pages `scrape_affinity_wa_tournament.py` speaks, so it needs its own scraper. The data is easy once reached: same-origin REST at `https://sctour.sportsaffinity.com/api/schedules?organizationId=<org>&tournamentId=<tourn>` returns JSON with team ids, club ids, goals, forfeit flags, play dates and venue `stateCode`; `/api/standings` carries `ageGroupName` + `flightKey`, which is the only way to age-group a game since `flightName` is empty on the schedules payload. **Blocked on a season id**: the known pair (org `7379E8F5-2B0D-4729-BDF9-967A08999A37`, tourn `fd4c6e27-142e-448e-8fb3-e83a5bcc15de`) is "2025 Fall League Washington", Sep 6 - Nov 23 2025, 570 played games — already historical. No endpoint enumerates a league's tournaments (`/api/tournaments`, `/api/organization` both 404), so the current-season id has to come from the organizers. Verified live 2026-08-31.
- **Noted**: 2026-08-31
- **Trigger**: An organizer supplies a current-season tournament id. `/api/tournaments` and `/api/organization` both 404 as of 2026-09-08, so there is nothing to point an ingester at. Confirmed 2026-09-08 to be a genuinely new source — the existing Affinity WA scrapers hit `wys.sportsaffinity.com` classic bracket pages, not the sctour JSON API.

### Ingest North Puget Sound League once Demosphere publishes scores

- **ID**: IMP-191
- **Status**: deferred
- **Type**: investigate
- **Category**: feature
- **Where**: new scraper against `https://elements.demosphere.com/74274/schedules/Fall2026/`
- **Why**: A WA league PitchRank does not ingest, on Demosphere (OttoSport) rather than Affinity. The public page `northpugetsoundleague.ottosport.ai/fall-2026-schedule` renders nothing server-side; the content is an embedded Demosphere element at the URL above, which is clean static HTML needing no JS — an index of ~50 divisions (BU9-BU19, GU9-GU19) each linking to a per-division schedule page. Division labels are U-age with no birth year (`BU13 Division 1`), and the season is unambiguous from the URL path, so cohorting is safe. **Blocked on scores**: the game tables carry only `GAME# | Time | Home | Away | Location` — no score column exists, so there is nothing to import yet. Season opens 2026-09-12; re-check a week or two after to see whether scores land in the same table or a separate results view, which decides the scope. Verified live 2026-08-31.
- **Noted**: 2026-08-31
- **Trigger**: Demosphere publishes played scores for North Puget Sound League. The season opens 2026-09-12 and the schedule endpoint returned HTTP 403 on 2026-09-08, so there is nothing to import yet. Confirmed 2026-09-08 that no Demosphere/OttoSport scraper exists anywhere in the repo, so this is not a duplicate.

### Bound the open-invoice fetch the way the paid one beside it is bounded

- **ID**: IMP-186
- **Status**: open
- **Type**: direct
- **Category**: performance
- **Where**: `frontend/lib/admin/subscription-metrics.ts` (`getSubscriptionMetrics`, the `{ status: 'open' }` call)
- **Why**: The paid-invoice fetch carries `created: { gte: now - COHORT_FETCH_DAYS }`; the open one carries no date floor and no page cap, so it auto-paginates every unpaid invoice the account has ever accumulated on each render of a `force-dynamic` page with a Refresh link. Not a regression — the pre-existing `safeList({ status: 'canceled' })` is unbounded the same way — and fine at today's 47 invoices. It scales badly, and unlike the canceled list the open list only grows while collection keeps failing, which is exactly the condition under which someone reloads the page. **A `created` floor is the wrong remedy here**, despite the symmetry with the paid fetch: the paid list is evidence for a bounded conversion cohort, while this one feeds `buildUnpaidInvoices` (`month-projection.ts:472`), a *current* outstanding-debt total that sums `amount_remaining`. Bounding it by creation date would silently omit any invoice still owed from before the window and could show "No unpaid invoices" while collection is failing on an old one. Take the cost off pagination instead — a page cap with an explicit "showing N of M" affordance, or a cached total — and leave the date range open. The unbounded `safeList({ status: 'canceled' })` beside it is a separate call and can take the cohort floor safely, since nothing reads it as a current total.
- **Noted**: 2026-09-04

### Settle whether subscription items are read as a list or as `data[0]`

- **ID**: IMP-187
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `frontend/lib/admin/subscription-metrics.ts` (`getInterval`, `bucketActivePaid`), `frontend/lib/admin/month-projection.ts` (`countAnnualRenewals`)
- **Why**: One feature now reads the same Stripe object two ways. `computeMrr` iterates `sub.items.data` in full, and `countAnnualRenewals` was changed to match after review; `getInterval` and `bucketActivePaid` still read `items.data[0]` only. Stripe designates no canonical item, and `current_period_end` is documented per item, so a multi-item subscription can renew its items on different dates. Verified unreachable today: 0 of 188 subscriptions carry more than one item, `items.has_more` is false throughout, and no code path in the product creates a second item (both checkout calls pass a single `line_items` entry, and the billing portal swaps a price rather than adding items). So this is consistency, not a live bug — but the divergence is the kind that silently decides a number once an add-on or a second plan ever ships. Pick one convention and apply it to all four.
- **Noted**: 2026-09-04

### Price projected churn at the revenue actually at risk

- **ID**: IMP-188
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/admin/month-projection.ts` (`buildMonthProjection`, `lostMrr`)
- **Why**: `lostMrr` multiplies churned subscribers by `arpu`, which is the blended monthly-equivalent of the historical paid-*acquisition* cohort. The population actually at risk in a month is different: currently 100% monthly at $6.99, where the acquisition mix is about 18% annual at $5.83 monthly-equivalent. Measured on live data the code reports $50.09 against $51.68 for the at-risk mix, a $1.58 gap on a $50 line. Left alone because that is an order of magnitude below the sampling error on the churn rate feeding it — the same report shows that rate swinging five points on lookback choice alone, worth roughly $10. Worth revisiting only alongside a better churn estimate, and note that neither formulation handles annual correctly: a lapsed annual renewal removes $69.99 of cash, not $5.83.
- **Noted**: 2026-09-04

### Treat a pending cancellation as a certainty rather than an average-rate risk

- **ID**: IMP-189
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/admin/month-projection.ts` (`countAnnualRenewals`, `buildMonthProjection`), `frontend/lib/admin/subscription-metrics.ts` (`bucketActivePaid`)
- **Why**: A subscription carrying `cancel_at_period_end: true` will definitely lapse at its period end, but both the annual-renewal count and the active monthly base fold it into a population that is then multiplied by an average churn rate, understating the loss. `buildTrialPipeline` already reads the flag for trials and even reports the count separately, so the asymmetry is within one file. Zero effect until April 2027 at the earliest: exactly one active subscription carries the flag, it is annual, and its period ends 2027-06-12 — at which point it would be charged at roughly 0.16 instead of 1.0, understating that month by about $4.90 of the $5.83 at stake. The flag is already fetched on every subscription, so this needs no new data.
- **Noted**: 2026-09-04
- **Update (2026-09-16)**: The "exactly one" count read `cancel_at_period_end` alone. Counting `cancel_at` as well (as `isCancellationScheduled` in `frontend/lib/stripe/server.ts` does), 14 active subscriptions had a scheduled cancellation on 2026-09-16, 13 of them monthly. So the effect is not deferred to April 2027: every monthly subscription whose cancellation falls before month end is a certain loss the projection still weights at the average churn rate.

### Skip operator-decided teams in the contradiction audit's paid probe list

- **ID**: IMP-192
- **Status**: deferred
- **Type**: direct
- **Category**: performance
- **Where**: `scripts/assign_team_states.py` — `contradiction_candidates`, the `state_source != TIER_A_SOURCE` clause
- **Why**: The selection excludes teams the provider already answered but not teams a person decided — 31 set by hand (`state_source = 'operator'`) and 98 approved from the review queue. Since the authority test added in `state-corrections-converge` can only ever queue a correction over an operator decision, each of those buys a GotSport call whose answer is unappliable. **Deferred deliberately on 2026-09-02**: the stored-`DC` clause keeps such teams in the population on the grounds that a review row carrying the provider's answer is worth the call, and the same argument applies here. Revisit only if paid probe volume becomes a concern. Whichever way it goes, the selection tests should assert the choice — they currently enumerate exclusions one literal at a time rather than deriving them from what `decide` can act on, so neither the present behaviour nor its opposite is pinned. Raised by the coverage reviewer.
- **Noted**: 2026-09-02
- **Trigger**: paid GotSport probe volume becomes a cost concern, or the audit's candidate count stops falling
- **Update (2026-09-08)**: Half of the premise is now stale — `vouched_for()` (PR #1082, `fe455f92`) covers `OPERATOR_SOURCE`, so the 31 hand-set teams are already excluded from `contradiction_candidates` (`scripts/assign_team_states.py:687-692`). The 98 review-queue approvals still are not: their `state_source` is stamped `tier_x`, so `vouched_for("tier_c")` is False and they stay in the paid-probe population. `contradiction_candidates` never got the `approved_states` check that IMP-165 added to `decide()`.

### A reverted approval still grants operator authority if the value later returns

- **ID**: IMP-194
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/assign_team_states.py` — `fetch_approved_states`
- **Why**: The reader collects every historical `approve` row as a `(team, new_state_code)` pair and never asks whether that approval was later undone. Keying on the written value covers the ordinary case -- once a team's state moves on, the pair stops matching -- but not the return trip: approve to ID, revert, then some other writer puts the team back in ID, and the stale pair matches again and hands an operator-level authority of 1.0 to a value the operator's own revert had rejected. `decide()` then refuses every correction away from it, permanently and silently, which is the exact failure the authority test was added to prevent, inverted. Not reachable through the sweep alone, since `fetch_revert_blocks` already refuses to re-apply a reverted value; it needs a provider import or a by-hand write to restore the state. Zero pairs are affected today (98 approvals, no reverted-then-restored team). The fix is to fold the ledger in event order per team -- the last of approve/revert wins -- rather than accumulating approvals as a flat set, which is why it was kept out of the PR that added the reader. Raised by Codex on #1102.
- **Noted**: 2026-09-07

### The Sunday enqueue jobs cannot tell that the activity refresh failed ahead of them

- **ID**: IMP-195
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `.github/workflows/refresh-team-scrape-activity.yml`, `.github/workflows/enqueue-discovery.yml`, `.github/workflows/enqueue-safety-net.yml`
- **Why**: `refresh_team_scrape_activity` recomputes the four `teams` columns the scrape-eligibility functions read, and the Sunday crons are ordered around it deliberately -- refresh 12:19, discovery 14:41, safety net 16:56 -- so both selectors read fresh values. Nothing enforces that ordering as a dependency. When the refresh died at page 0 on 2026-08-30 and 2026-09-06 it wrote nothing, and both downstream jobs still ran and still succeeded, selecting on values up to a week stale. Verified from run times: the whole Sunday chain is delayed 2-4 hours by GitHub's scheduler but its *relative* order held both weeks, so the ordering assumption is sound and only the failure case is unhandled. Impact is a week of mis-targeted enqueues -- teams that became active look idle and are passed over, retired ones look live and are queued -- self-correcting the following Sunday, and bounded by the fixed `--limit` on every selector, so the volume never changes. #1097 closed the refresh's own failure mode by retrying a stalled page three times, which makes this rarer but not impossible. Options: have the refresh write a freshness marker the enqueue jobs assert on, or make them `workflow_run` consumers of it rather than independent crons. Worth deciding only if a scheduled refresh fails again now that the retry is in.
- **Noted**: 2026-09-07

### v53e sets four `total_*` columns that the rankings_full adapter then drops

- **ID**: IMP-196
- **Status**: open
- **Type**: direct
- **Category**: readability
- **Where**: `src/etl/v53e.py` (the `teams["total_games_played"] = teams["gp"]` block and its three siblings), against `v53e_to_rankings_full_format`'s `expected_columns` list in `src/rankings/data_adapter.py`
- **Why**: v53e copies the CAPPED engine `gp`/`wins`/`losses`/`draws` onto `total_games_played`/`total_wins`/`total_losses`/`total_draws`, which reads as a writer of the four uncapped columns. It is not one: `v53e_to_rankings_full_format` builds its payload from an explicit `expected_columns` allowlist, and `total_` appears nowhere in `src/rankings/data_adapter.py`, so all four are dropped before the upsert. Verified 2026-09-07. So this is a dead assignment rather than a correctness risk -- but it is dead code that looks exactly like a third writer competing with `backfill_total_game_stats_page`, which is how it was first reported. Delete the four lines, or comment them with the reason they cannot reach the database.
- **Noted**: 2026-09-07

### Two definitions of the CSV formula guard, and the shared one is the weaker

- **ID**: IMP-197
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `csv_safe` in `src/tournaments/reports/render_csv.py` (imported by `tournament_intake.py`) and `csv_safe` in `scripts/reconcile_teams_with_gotsport.py`
- **Why**: Both prefix a leading `=` `+` `-` `@` or whitespace with `'`, over the same frozen prefix set. The reconcile copy also escapes a value that ALREADY starts with `'`, without which the encoding is not injective -- `=x` and `'=x` both encode to `'=x`, so an undo restores the wrong one. The shared copy lacks that, so the module named as the common home is the weaker of the two. Verified 2026-09-08. Fold the reconcile behaviour into the shared function and import it there too. Noted after PR #1111 promoted the shared one to public and its description claimed "one definition" -- there were two, which is why the claim is corrected here rather than left in the PR body.
- **Noted**: 2026-09-08

### Two regexes detect pipefail-substitution, and the newer one is the weaker

- **ID**: IMP-198
- **Status**: open
- **Type**: direct
- **Category**: testing
- **Where**: `_PIPEFAIL` in `tests/unit/test_workflow_pipefail_substitutions.py` and `PIPEFAIL_ENABLE` in `.claude/skills/review-workflows/scripts/audit_workflows.py`
- **Why**: Both decide whether a workflow step has enabled `pipefail`, over the same files, for the same defect. The skill's has been correct from the start; the test's first draft matched only the literal `set -o pipefail` and silently skipped three workflows using `set -euo pipefail` / `set -uo pipefail` until a reviewer caught it. Verified 2026-09-08 by reading both. Nothing links them, so the next spelling has to be added twice. Importing across the boundary is not the repo's habit -- no test imports from `.claude/skills/` -- so the realistic fix is a cross-reference in each, naming the other as the sibling to update. Noted while closing IMP-133.
- **Noted**: 2026-09-08
- **Update (2026-09-08)**: Corrected — the multi-spelling bug this entry names is already fixed on both sides: the test's `_PIPEFAIL` (`tests/unit/test_workflow_pipefail_substitutions.py:42`) and the skill's `PIPEFAIL_ENABLE` (`.claude/skills/review-workflows/scripts/audit_workflows.py:479`) both match `set -euo`/`set -uo` now. The one behavioural difference left is the skill's end-of-line anchor, which rejects `set -o pipefail; echo x` where the test accepts it — narrower, not weaker. The real remaining ask is that neither file cross-references the other, so a fourth spelling still has to be added twice with nothing to prompt it.

### The missing-game completion toast has never fired

- **ID**: IMP-199
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/hooks/useScrapeRequestNotifications.ts` `useScrapeRequestNotifications` (the `postgres_changes` subscription), consumed by `frontend/components/MissingGamesForm.tsx`
- **Why**: The hook subscribes to `scrape_requests` over Supabase Realtime with no polling fallback, but `postgres_changes` delivers nothing for a table outside the `supabase_realtime` publication, whatever its RLS says. Verified 2026-09-08 against production: `pg_publication_tables` for that publication returns exactly one public table, `announcements`. No migration adds `scrape_requests` — no migration mentions `supabase_realtime` at all except the two `DROP TABLE` calls in `20260608000000` — so membership was never set, and a user who clicks "find my missing game" has never seen a completion notification; they must reload to see the result. Fix candidates: add the table to the publication (`relreplident` is `d`, so an RLS-gated subscription may also need `REPLICA IDENTITY FULL`), or replace the subscription with polling against a service-role route, which would also free the anon SELECT grant that `.turbo/plans/batch-1-outsider-reachable-security.md` deliberately preserves for it.
- **Noted**: 2026-09-08

### Five migration-guard tests carry divergent copies of the same SQL helpers

- **ID**: IMP-200
- **Status**: open
- **Type**: plan
- **Category**: testing
- **Where**: `_executable` and `_flat` in `tests/unit/test_scrape_requests_rls_migration.py`, `test_team_page_views_migration.py`, `test_team_state_provenance_migration.py`, `test_backfill_total_game_stats_migration.py` and `test_scrape_activity_predicate.py`; `_executable_updates` in `test_age_rollover_migration_map.py` solves the same problem a sixth way
- **Why**: `_executable` (strip SQL comments before asserting, so a commented-out clause cannot satisfy a guard) exists in five files with a near-verbatim docstring, and `_flat` exists in four with **three** different contracts under one name — one strips comments and trims, one does neither, one trims only. Only the newest copy strips `/* */` block comments, which was added after a block-commented REVOKE was shown to satisfy an assertion the server would never execute. Every one of these files exists because CI applies no SQL, so a helper that silently stops comment-stripping turns its whole module green for the wrong reason. Copying between them is the expected path — the newest was seeded from `test_team_page_views_migration.py` — and copying the wrong direction is silent. Lift them into a shared `tests/unit/_migration_sql.py` (or conftest) carrying the strongest contract, and re-verify each module's guards still redden under their own mutations afterwards. Deliberately deferred from the scrape_requests lockdown: touching four unrelated guards inside a security fix makes both harder to review.
- **Noted**: 2026-09-08

### MomentumMeter samples 8 scheduled games, not 8 played ones

- **ID**: IMP-201
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `calculateMomentum` in `frontend/components/MomentumMeter.tsx`
- **Why**: It slices the 8 most recent rows and only then skips games with a null score, so a team whose scores have not been scraped yet gets its momentum from whatever is left — 5 games instead of 8. The two sibling generators do the opposite deliberately and say so: `formBadge.ts` and `consistency.ts` both walk newest-first and collect until they hold N *played* results. Verified 2026-09-09 against production: 34,540 of 187,266 teams (18.4%) currently have at least one unscored game among their last 8 played-or-past fixtures. Nothing on screen is false — the card labels the count it actually used — so this is sample quality, not a wrong number. Fix is to mirror the sibling walk. Kept out of the trajectory/insights fix on 2026-09-09 by user decision, because it shifts a headline metric for a fifth of the site.
- **Noted**: 2026-09-09

### Team page swallows notFound(), so a bad URL reaches the queries

- **ID**: IMP-202
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: the `try`/`catch` wrapping `notFound()` in `frontend/app/teams/[id]/page.tsx`; `getTeamTrajectory` in `frontend/lib/api.ts`
- **Why**: Verified 2026-09-09 by reading the file: four `notFound()` calls (lines 118, 132, 146, 168) sit inside a `try` opened at 113 whose `catch` at 171 logs and continues, and `unstable_rethrow` appears nowhere in `frontend/`. Next's `notFound()` throws an ordinary Error, so a malformed id falls through to `TeamPageShell` and is interpolated into the PostgREST `.or()` expression with no `isValidUuid` guard — unlike the sibling insights route, which validates first. Exposure is bounded: `games_anon_select` already grants `anon` SELECT `USING (true)`, and supabase-js percent-encodes the expression, so a crafted link spoofs which team's games are shown rather than reaching private data. The same swallowed `notFound()` also disables the deprecated-team `redirect()` and the zero-games 404, which is why the fix belongs at the `catch` and not as a per-query guard. Logged rather than patched by user decision on 2026-09-09: a single-query guard would read as fixed while the page's other queries kept the gap.
- **Noted**: 2026-09-09

### getTeamTrajectory hand-rolls the merge resolution its siblings share

- **ID**: IMP-203
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `getTeamTrajectory` in `frontend/lib/api.ts`; `resolveMergedTeamIds` in `frontend/lib/team-merge.ts`
- **Why**: The trajectory queries `team_merge_map` inline while `app/api/insights/[teamId]/route.ts` calls the shared helper. `lib/api.ts` already imports that helper for `getRankHistory` and still carries inline `from('team_merge_map')` queries elsewhere, so a cascade-merge fix would reach the route and miss the chart.
- **Noted**: 2026-09-09

### The played-scores predicate is repeated at 11 query sites

- **ID**: IMP-204
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `.not('home_score', 'is', null)` pairs across 7 files — `lib/api.ts` (`getTeam`, `getTeamTrajectory`, both `getCommonOpponents` queries), `lib/matchPredictionService.ts`, and the `insights`, `watchlist`, `reports/team-card`, `teams/[teamId]/clutch` and `mission-control/model-snapshot` routes
- **Why**: Counted 11 occurrences across those 7 files on 2026-09-09. If "played" ever gains a status column or forfeit semantics, every site needs the same edit and nothing enumerates them. A `withPlayedScores(query)` helper in `lib/api/` is the obvious extraction; typing a generic PostgREST builder passthrough is the awkward part.
- **Noted**: 2026-09-09

### Final trajectory period reports period_end as the current time

- **ID**: IMP-205
- **Status**: open
- **Type**: direct
- **Category**: correctness
- **Where**: the tail-period push in `getTeamTrajectory`, `frontend/lib/api.ts`
- **Why**: Every other period ends at `periodStart + periodDays`, but the last is pushed with `new Date().toISOString()`, so a team whose last result was months ago gets an eleven-month span described as a 30-day period. Invisible today — `components/TeamTrajectoryChart.tsx` reads only `period_start`, `avg_goals_*`, `games_played` and `win_percentage` — but any consumer that renders the range would print a window the data does not cover.
- **Noted**: 2026-09-09

### The Backtest scrape surface still strands its in-progress flag

- **ID**: IMP-206
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `_run_scrape` and `_render_intake_section` in `tournament_intake.py`
- **Why**: `_run_scrape` sets `st.session_state._scrape_in_progress = True` inside its lock and clears it in a `finally`, and `_render_intake_section` reads it raw into four widget `disabled=` params. Verified 2026-09-09 by reading both: Streamlit 1.50.0 defaults `runner.fastReruns` to True, so touching a widget mid-walk stops the running script, and a STOP request is sticky (`script_requests.py`) — that `finally` cannot be relied on, and a flag nobody cleared disables that tab's URL box and Scrape button for the rest of the session. The Seeding surface was fixed on 2026-09-09: it records its lock key in `_seeding_scrape_lock_key` and `_scrape_still_running()` clears the flag once that lock probes free. `_run_scrape` already computes the same `key`, so the same treatment is a few lines. Measured the same day: `msvcrt.locking` refuses a second handle inside one process and `fcntl.flock` binds to the open file description, so the probe conflicts on both platforms.
- **Noted**: 2026-09-09

### Two hand-written EventRoster payload dicts, already drifted apart

- **ID**: IMP-207
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `_write_event_roster_recovery` in `tournament_intake.py`; the `payload` dict in `scripts/scrape_event_roster.py`
- **Why**: Both serialize the same frozen dataclass by hand, and read on 2026-09-09 they disagree. `EventRoster.is_complete` is a property over five counters, so a payload keeping only `divisions_found`/`divisions_walked` rebuilds a walk that lost divisions as a whole one — which is why the intake side now persists `divisions_stable` too. The CLI side does not, and spells its timestamp `scraped_at` where the intake writes `walked_at`; only the CLI runs `printable_text` over the names and warnings it writes. A shared `roster_payload(roster)` beside the dataclass, or in `event_roster_intake` which both already import, makes the next counter a one-line change instead of a two-file one that has been forgotten once.
- **Noted**: 2026-09-09

### A one-division walk outranks a real partial walk of the same event

- **ID**: IMP-208
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `_write_event_roster_recovery` and `_recovery_holds_a_complete_walk` in `tournament_intake.py`; `EventRoster.is_complete` in `src/tournaments/gotsport_event_roster.py`
- **Why**: The overwrite guard asks only whether the file already holds a *complete* walk, and `is_complete` is satisfied by any walk that read every division it found — including a one-division event. So a small complete roster replaces a large partial one, which is backwards: the partial walk of 57 divisions is the expensive artifact. This is not theoretical. On 2026-09-09 a process sharing this checkout wrote a synthetic 1-division roster over `reports/seeding/gotsport_52975/last_walk.json`, and 9 of the real walk's 11 team entries were unrecoverable; the surviving file carries a `_restored_note` recording it. Comparing team counts, or refusing to replace a walk of a different `divisions_found`, would both have held. Related: the same file is the one `_recovered_walk` now reads back, so a wrong winner here is offered to the operator as the walk they paid for.
- **Noted**: 2026-09-09

### Games where a team plays itself reach the ranking engine

- **ID**: IMP-214
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `src/rankings/data_adapter.py` `drop_duplicates(subset=["id"])` (no self-play filter); origin likely `src/etl/enhanced_pipeline.py` team-id backfill / provider matchers
- **Why**: 1,028 game rows across 552 live teams carry `home_team_master_id = away_team_master_id`, verified by direct SQL 2026-09-12 (894 GotSport, 124 TGS, 5 PlayMetrics, 3 Modular11, 2 Affinity WA; dates 2024-03-29 to 2027-03-13). Nothing filters them before Glicko, so a team is rated against itself. They also mark rows that are two squads fused into one record — `XF 2016 RCL 1` (`ab31993f`) holds 42 games against 17-20 for each sibling squad and plays every flight opponent twice. Root cause unknown: could be a matcher resolving two provider ids to one master, or a provider feed listing both sides identically.
- **Noted**: 2026-09-12

### A dry run reports `Teams created: 0` no matter how many teams it would create

- **ID**: IMP-212
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: the `teams_created` metric fold in `EnhancedETLPipeline.import_games` (`src/etl/enhanced_pipeline.py`), against the `"created": True` flag the provider matchers return from `_match_team`
- **Why**: Verified 2026-09-11 on `affinity_or`: the matcher returns `{"created": True, ...}` and the teams table is genuinely untouched, but the dry-run summary prints `Teams matched: 226 / Teams created: 0` while a direct pass over the same 57 distinct names creates 41 of them. So the one number an operator would read to size an autocreate before letting it write is always zero, for every provider. CLAUDE.md already warns that a new provider's dry run has to be verified against the database rather than its summary; this is the specific reason why.
- **Noted**: 2026-09-11

### A same-day rematch is deduped away for every provider but `playmetrics_tournament`

- **ID**: IMP-213
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `_make_composite_key` and the `schedule_id` branch of `_validate_and_dedup` in `src/etl/enhanced_pipeline.py`
- **Why**: The composite key mirrors the DB constraint — provider, both team ids, date, and the two scores — and only `playmetrics_tournament` folds `schedule_id` in. Two meetings of the same pair on one date therefore collapse to one row for every other provider, and while both are unplayed their scores are equal too, so the scores in the key do not separate them either. No live instance: 437 games across four OYSA cohorts on 2026-09-12 had zero same-date repeat pairings, because a round-robin league does not schedule them. It becomes real the moment a tournament-shaped event is imported under a league provider — which is exactly why the `playmetrics_tournament` carve-out exists. Raised by Codex on PR #1133 against `affinity_or`; left alone there because the fix belongs in the shared dedup path, not in one provider.
- **Noted**: 2026-09-12

### SincSports live tournament scrape imports a partial event

- **ID**: IMP-216
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `main` in `scripts/scrape_sincsports_tournament_schedule.py`; `SincSportsScheduleScraper.fetch_tournament` in `src/scrapers/sincsports_schedule.py`
- **Why**: `fetch_tournament` records a failed division on `self.errors` and continues, and the `--tid` branch of `main` prints the error count, writes the JSONL and runs `--auto-import` with exit 0, so a 403 on one division's later page drops that division's games silently. The `--from-bundle` branch refuses an incomplete capture with exit 1. Return 1 when `scraper.errors` is non-empty, at least under `--auto-import`.
- **Noted**: 2026-09-14

### Two SincSports tournament games may have been imported from a forfeit and a cancellation

- **ID**: IMP-217
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `parse_sched2` in the local helper `data/exports/sincsports_session_scripts_20260914/bundle_to_jsonl_s1.py`; capture `data/raw/sincsports_schedules_aug_all_states_20260913.json` (both local only)
- **Why**: That helper read only `.sched2-mark`/`.sched2-typechip` text and never the `.sched2-gstat-off` label, so a game marked Forfeit and one marked Cancelled that both carry a recorded score were emitted as Played (counted from the capture 2026-09-14; one is HFCLAB U13M02, 0-3). Whether both reached `games` is unverified. Games are immutable, so find the rows (provider `sincsports`, competition `"<event> - <div>"`, date, team pair) and quarantine them.
- **Noted**: 2026-09-14

### Watchlist activity counts games that have been excluded

- **ID**: IMP-220
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `GET` handler in `frontend/app/api/watchlist/route.ts` — the recent-game `homeRecentResult`/`awayRecentResult` queries and the fallback `homeLastResult`/`awayLastResult` queries
- **Why**: Read on `origin/main` 2026-09-14. Those four `games` queries lack `.eq('is_excluded', false)`, although the same file's other queries (`:355`, `:364`) and `getTeamGames` (`frontend/lib/api.ts:720`) filter it. So `new_games_count` and `last_game_date` still count excluded rows: futsal, merge duplicates, and the ~4,850 phantom games `scripts/exclude_none_opponent_games.py` excludes. Add the filter to all four queries, plus a route test showing an excluded game changes neither field.
- **Noted**: 2026-09-14

### A GotSport import dry run still writes aliases and review-queue rows

- **ID**: IMP-221
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `EnhancedETLPipeline._ensure_initialized` in `src/etl/enhanced_pipeline.py` (the fallback `GameHistoryMatcher(...)` construction, `:304`); `GameHistoryMatcher.__init__` in `src/models/game_matcher.py`
- **Why**: Read on `origin/main` 2026-09-14. The provider-specific branches of that `if/elif` pass `dry_run=self.dry_run`. The final `else`, which GotSport and every other standard-matcher provider reach, does not, and `GameHistoryMatcher.__init__` defaults `dry_run=False`. `_create_alias` and `_create_review_queue_entry` therefore write during `import_games_enhanced.py --dry-run`, breaking CLAUDE.md's rule that the pipeline pass `dry_run` to every matcher it builds. `tests/unit/test_provider_matcher_dry_run.py` covers only the autocreating matchers.
- **Noted**: 2026-09-14

### TGS teams and aliases keyed on placeholder provider ids

- **ID**: IMP-222
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `team_alias_map` and `teams` rows for provider `tgs`; `TGSGameMatcher._match_by_provider_id` in `src/models/tgs_matcher.py`
- **Why**: In live data on 2026-09-14, two TGS teams are keyed on placeholder ids, each with an approved `direct_id` alias. "Winner Game 4" is a bracket placeholder with id `"None"`, 2 games and a `rankings_full` row. The other has an empty name and id `""`, with 0 games. The GotSport twin of this shape pulled 4,846 unrelated games onto one team, and its cleanup (`scripts/exclude_none_opponent_games.py`) is GotSport-only. Import lookups cannot reach these rows: `match_game_history` and `GameHistoryMatcher._match_team` blank a placeholder id first, and the alias preload skips one. Still open: rejecting the two aliases, the ranked `"None"` row, and how the rows were created. `TGSGameMatcher._match_team` still passes whatever id it receives to `_create_new_tgs_team`.
- **Noted**: 2026-09-14

### Future-dated games already carry scores

- **ID**: IMP-223
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `games` rows with `game_date` after the import date; GotSport path `GotSportScraper._parse_api_match` in `src/scrapers/gotsport.py`; loader `fetch_games_for_rankings` in `src/rankings/data_adapter.py`
- **Why**: On 2026-09-14, 211 games dated after that day already had both scores set. 80 are in the GotSport `"None"` sink that `scripts/exclude_none_opponent_games.py` excludes, and many of those read 1-0 or 0-1 weeks ahead of play. The other 131 are not part of it. `fetch_games_for_rankings` skips future dates, so the other 131 count as real results once their date passes. Unknown whether GotSport publishes pre-set or forfeit results or the import assigns scores to scheduled matches.
- **Noted**: 2026-09-14

### Give the Modular11 scrape workflows a fixed start date instead of days-back

- **ID**: IMP-224
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `Modular11ScheduleSpider.__init__` (`scrapers/modular11_scraper/modular11_scraper/spiders/modular11_schedule.py`) and `Modular11EventsSpider.__init__` (`modular11_events.py`), both deriving `start_date = now - days_back`; the `days_back` input of `modular11-weekly-scrape.yml` and `modular11-events-weekly-scrape.yml`
- **Why**: The operator decision (2026-09-14) is to import only Modular11 games dated 2026-09-01 or later. Today that must be re-expressed as a days count on every run, and the default of 365 re-scrapes last season. Since the 2026-09-14 alias roll, a pre-rollover game labelled U16 resolves to last season's U15 squad and passes the matcher's age check, so it is misfiled silently rather than rejected. Modular11 code is operator-gated; this entry needs the owner to open it.
- **Noted**: 2026-09-14

### Modular11 team creation reuses a team by stored provider ID without checking its age

- **ID**: IMP-225
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `Modular11GameMatcher._create_new_modular11_team` in `src/models/modular11_matcher.py` (the `teams` select on `provider_id` + aliased `provider_team_id` that returns `existing.data["team_id_master"]`, and the same lookup in its duplicate-key fallback)
- **Why**: `_match_by_provider_id` rejects an alias whose team is in another age group (`_validate_team_age_group`), but team creation then looks up `teams.provider_team_id = "{club}_U{age}_{div}"` and returns whatever it finds with no age check. Read 2026-09-14: a stale ID therefore attaches a new squad's games to an older squad, which is why every rollover must roll `teams.provider_team_id` as well as the aliases. Operator-gated like all Modular11 code.
- **Noted**: 2026-09-14

### Commit a reusable rollover script for Modular11 team names and provider IDs

- **ID**: IMP-226
- **Status**: open
- **Type**: plan
- **Category**: dx
- **Where**: new script under `scripts/`; reads `teams_age_rollover_backup_<year>` and writes `teams.team_name`, `teams.provider_team_id`, `team_alias_map.provider_team_id`
- **Why**: The Aug 1 relabel migration moves only `teams.age_group`, so Modular11 U-ages in names and `{club}_U{age}_{div}` IDs fall a year behind every season. The 2026-09-14 fix was a one-off scratch script, not kept; rollback data is in gitignored `data/backups/modular11_*_2026-09-14.*`. Rules that held:
  - Roll IDs for every rolled team whose ID age equals its prior label, including deprecated rows (they still hold the unique index) and Modular11 aliases on GotSport/TGS teams. Rolling only renamed teams held back 249.
  - Rename only names whose single U-age equals the prior label and that carry no birth year or season.
  - Park the u19 board at U18, write the oldest board first, guard each write on its old value, and dry run by default.
- **Noted**: 2026-09-14

### SincSports teams carry their team-ID state prefix as an unmarked state, and Tier B overrides it from a shared club name

- **ID**: IMP-227
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `SincSportsGameMatcher._create_new_sincsports_team` (`state_code` param) in `src/models/sincsports_matcher.py`; `club_derived_state` and `outranked` in `scripts/assign_team_states.py`
- **Why**: Measured 2026-09-14: 19,596 of the 19,616 SincSports teams created 09-13/14 have `state_code` equal to the first two letters of their SincSports ID (`VAM11811` = VA), with no `state` name and no `state_source`, so the sweep treats it as a guess. That day's free sweep proposed about 30 Tier B corrections on those teams. By hand, about half were right (Gwinnett Soccer Academy NC→GA) and about half rested on a club name belonging to a different club (a Gunston SC team, which is in VA, filed under KEYSTONE FC PA; Winchester, Woodbury, Pasadena, Hub City). Settle whether the prefix is the registering state or the event's host state, then either stamp it as a provider source or stop writing it.
- **Noted**: 2026-09-14

### GotSport's unset AL default passes the guard for teams with no club-mates

- **ID**: IMP-228
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `unset_default_disputed` and its callers in `decide` and the confirm builder, `scripts/assign_team_states.py`
- **Why**: The guard drops an `AL` answer only when the team's name, club or a place word in its name disagrees. A team in `--probe-unclubbed` has no club-mates and often no place word, so AL goes through. 2026-09-14 rehearsal (ledger answers, no calls): "MAFC 2017 Royal" TX→AL auto-apply (all 4 opponents TX), and an "Arlington Soccer Association" team confirmed as AL (all 3 opponents VA). Both were withheld by hand. Needs a rule for AL with no local reading that doesn't also block real Alabama teams.
- **Noted**: 2026-09-14

### Pin the find_topup_teams and refresh RPC REVOKE and GRANT as whole statements

- **ID**: IMP-229
- **Status**: open
- **Type**: direct
- **Category**: testing
- **Where**: `test_topup_is_locked_down_to_service_role` and `test_refresh_is_locked_down_to_service_role` in `tests/unit/test_scrape_activity_predicate.py`
- **Why**: The top-up test asserts four separate substrings of the newest migration defining `find_topup_teams` (a SECURITY DEFINER RPC), so `TO service_role, anon;` still contains `TO service_role`, and nothing checks for an extra `GRANT EXECUTE ... TO authenticated` line; both stay green. Nothing is exposed today (live ACL 2026-09-15: `postgres` and `service_role` only). Assert each full-signature REVOKE and GRANT through its closing `;`, against `_executable` text, and that no other GRANT on the function appears. The refresh test pins the signature but has the same two holes, so fix both together. Surfaced by review of the top-up timeout fix.
- **Noted**: 2026-09-15

### Base matcher review-queue and alias writes fail without the caller knowing

- **ID**: IMP-230
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/models/game_matcher.py` `GameHistoryMatcher._create_review_queue_entry` and `_create_alias`
- **Why**: `_create_review_queue_entry` inserts `confidence_score` unclamped, so a birth-year-demoted match scoring 0.90 or more violates the `team_match_review_queue` CHECK (0.75 <= score < 0.90); the `except` logs one error and the row is gone. The first Soccer Events Group execute on 2026-09-14 lost two rows this way until that matcher clamped to `src/tournaments/alias_writer.REVIEW_QUEUE_CLAMP`; every other provider still sends the raw score. Its dry run also logs "Created review queue entry" having written nothing, and `_create_alias` swallows its own write failure while the caller reports the team linked. Clamp and surface failures in the base class once rather than per provider.
- **Noted**: 2026-09-14

### Oregon and WA matchers reject same-squad names and pick equal-score candidates arbitrarily

- **ID**: IMP-231
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/models/game_matcher.py` `extract_team_variant`; `src/models/affinity_or_matcher.py` and `src/models/affinity_wa_matcher.py` `_fuzzy_match_team`; `tests/unit/test_provider_matcher_dry_run.py` create-helper parametrization
- **Why**: Building the Soccer Events Group matcher on 2026-09-14 showed `extract_team_variant` reading tier and band tokens such as "ECNL-RL" or the "/13" of "G2012/13" as a coach name, so two spellings of one squad fail the variant gate and a duplicate team is created; SEG replaced the gate with `extract_distinctions` colours, directions and squad number plus tier tokens. Both matchers also take the first of several equal-score candidates in iteration order, where SEG now sends a tie to review. Separately, the dry-run test's create-helper list covers sincsports, affinity_wa and soccereventsgroup but not `_create_new_affinity_or_team`.
- **Noted**: 2026-09-14

### Event scrapers each carry their own copy of the game-import CSV contract

- **ID**: IMP-232
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `REQUIRED_COLUMNS` in `scripts/scrape_affinity_or_tournament.py`, `scrape_affinity_wa_tournament.py`, `scrape_playmetrics_league.py`, `scrape_tgs_event.py`, `import_soccereventsgroup_event.py`; `_compute_result` in three of them; `bulk_existing_aliases` in `scripts/discover_sincsports_teams.py` and `discover_sincsports_via_tournament.py`, `existing_aliases` in `import_soccereventsgroup_event.py`
- **Why**: What `scripts/import_games_enhanced.py` reads is restated in five scripts, so a column added or renamed there drifts per scraper and fails only at import time for whichever copy was missed. The alias pre-check has three near-identical copies. One shared module for the column list, result computation and the alias lookup removes the drift.
- **Noted**: 2026-09-14

### The backlog sweep silently drops a repeated field label

- **ID**: IMP-233
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `parse_entry` in `scripts/sweep_improvements.py`
- **Why**: Fields are stored with `entry.fields.setdefault(label, value)`, so when an entry carries two lines with the same label (two `Update (YYYY-MM-DD)` notes written the same day) only the first is kept, the second never reaches `extras`, and the next sweep that rewrites the file deletes it. Keep repeated labels, or fail loudly; `tests/unit/test_improvements_backlog.py` could also reject a duplicate label.
- **Noted**: 2026-09-15

### pr_wait reports "Codex did not review" when Codex's review was clean

- **ID**: IMP-234
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `codex_findings` in `scripts/pr_wait.py`
- **Why**: It reads only the PR's review objects and inline comments. A clean Codex review arrives as a "Codex Review Summary ... Completed" issue comment plus a +1 reaction, with no review object, so the script prints "Codex did not review this PR" and waits out `CODEX_WINDOW_MINUTES` anyway. Seen on #1151 (2026-09-15): summary comment completed two minutes after open, +1 reaction, script reported no review. Findings still arrive as review objects, so this misreports and delays rather than merging past findings.
- **Noted**: 2026-09-15
- **Update (2026-09-23)**: Recurred on #1208 and was relayed to the user as "Codex did not review this PR" while the review had completed 5m42s after open with a 👍 and no findings. Two things this narrows for whoever fixes it: `CODEX_LOGIN` is *not* the cause (it carries the `[bot]` suffix REST returns and matches correctly), and the summary comment is created within ~10s of the PR opening but only reaches `Completed` minutes later, so presence of the comment is not the signal -- parse its status cell. The workaround note has now failed to prevent this twice, which is the argument for fixing the script rather than documenting it again.

### A game import exits 0 when its inserts fail

- **ID**: IMP-235
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `main` exit handling in `scripts/import_games_enhanced.py`; `EnhancedETLPipeline._bulk_insert_games` and its caller `import_games` in `src/etl/enhanced_pipeline.py`
- **Why**: Read 2026-09-15: no insert failure reaches `main`'s exit code. `_bulk_insert_games` catches each one, records whole-chunk failures only on the shared `self.metrics.errors` (never the batch metrics `import_games` returns) and returns the inserted count, which is what `games_accepted` holds; `import_games` catches its own exceptions after initialization, so `main`'s all-batches-failed `sys.exit(1)` cannot fire for one. `failed_games_count` counts games whose teams did not resolve. That is how the RLS `42501` run behind IMP-215 exited 0, and the weekly TGS and PlayMetrics import steps gate on this exit code. Count inserts that failed for a non-duplicate reason and exit non-zero when any did; attempted-versus-inserted is the wrong test, because the per-row fallback skips duplicate-key rows on purpose.
- **Noted**: 2026-09-15

### The backlog sweep detaches indented bullet lines from the field they belong to

- **ID**: IMP-236
- **Status**: open
- **Type**: direct
- **Category**: dx
- **Where**: `parse_entry` and `Entry.render` in `scripts/sweep_improvements.py`
- **Why**: Read 2026-09-15: `parse_entry` puts every line that does not match `FIELD_RE` into `Entry.extras`, and `render` writes all fields first and extras last. A real sweep on an entry whose Why ends in an indented bullet list (IMP-226, "Rules that held:") put its Noted line between the Why and the bullets, so the rules rendered as sub-points of the date; `tests/unit/test_improvements_backlog.py` stayed green and the entry was fixed by hand. Attach continuation lines to the preceding field and render them under it, with a test on a multi-line Why. Until then, re-check such entries after every sweep.
- **Noted**: 2026-09-15

### Find out why recent games are stored with one side unmatched

- **Type**: investigate
- **Category**: reliability
- **Where**: `src/etl/enhanced_pipeline.py` partial-match branch (`match_status == "partial"` appended to `game_records`); `src/models/game_matcher.py` `GameHistoryMatcher._validate_team_age_group`
- **Why**: Measured read-only 2026-09-15: games created since 2026-08-15, not excluded, with exactly one master id NULL — gotsport 2,572, sincsports 49. The cause is not established. GotSport opponents missing from the database are one known source. A second showed up on that day's Soccer Events Group import: an approved alias whose team's stored `age_group` no longer matched the game's, which the age check refuses, leaving that side blank. Count how many NULL sides have an approved alias for their provider id to size the second cause before changing any importer.
- **Noted**: 2026-09-15

### Pass each CSV row's `state_code` through the base matcher for every provider

- **ID**: IMP-237
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/models/game_matcher.py` `GameHistoryMatcher.match_game_history` (calls `_match_team` without `state_code`); `src/models/playmetrics_matcher.py` `_row_state_code` stash
- **Why**: `scripts/import_games_enhanced.py` loads `state_code` on every game and base `_match_team` already accepts and forwards it, but only the PlayMetrics matcher consumes it, via a per-call stash the next provider would have to copy. Affinity WA/OR, SEG and TGS scrapers already write the column. `.turbo/specs/team-state-assignment.md` records this as deferred. `tgs_matcher` deliberately leaves state NULL, so the base needs an opt-in per matcher rather than a blanket pass.
- **Noted**: 2026-09-15
- **Refs**: review of branch `fix/playmetrics-nc-governing-body`

### Stop `affinity_or_matcher` writing the full-name `state` column from a derived value

- **ID**: IMP-238
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `src/models/affinity_or_matcher.py` `_create_new_affinity_or_team` (`"state": new_state` in the insert payload); `scripts/assign_team_states.py` "stored value was reported" gate
- **Why**: Verified 2026-09-15: `assign_team_states` treats a filled `state` as provider-reported and queues instead of correcting. The value is derived (club unanimity or the league's own "Oregon"), so a visiting club is mislabelled with no auto-correction. `tgs_matcher`, `affinity_wa_matcher` and `playmetrics_matcher` write `state_code` only. `soccereventsgroup_matcher` also writes `state`, from a per-team registration payload; decide that one rather than assume.
- **Noted**: 2026-09-15
- **Refs**: review of branch `fix/playmetrics-nc-governing-body`

### Share one supabase-py builder double across the matcher unit tests

- **ID**: IMP-239
- **Status**: open
- **Type**: plan
- **Category**: testing
- **Where**: `tests/unit/test_playmetrics_matcher_row_state.py` `_Db`; `tests/unit/test_provider_matcher_dry_run.py` `_db_with_no_existing_team`; `tests/unit/test_soccereventsgroup_matcher.py`; `tests/unit/test_affinity_or_matcher.py`; `tests/unit/test_sincsports_matcher_extensions.py`
- **Why**: Five files hand-roll the `table().select().eq()…execute()` chain. Verified 2026-09-15: the dry-run test's double records at `insert()` rather than `execute()` and returns `data=None` from `.single().execute()`, which postgrest never does (it raises `APIError` PGRST116), while parametrizing over every autocreating matcher. Only the PlayMetrics double honours both CLAUDE.md double rules; Affinity OR's yields rows at `execute()` but still logs its filter at `eq()`. A `tests/conftest.py` double that raises on `.single()` with zero rows and records at `execute()` lets the rest adopt it.
- **Noted**: 2026-09-15
- **Refs**: review of branch `fix/playmetrics-nc-governing-body`

### Read a two-year band written with apostrophes

- **ID**: IMP-240
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/normalize_team_names.py` `_resolve_band` (its two-digit alternation); `src/utils/team_utils.py` `_BAND_RUN_RE`
- **Why**: Verified against `main` 2026-09-16: `_resolve_band("BRAUSA '11/'12 Blue")` returns `None` while `_resolve_band("BRAUSA 11/12 Blue")` returns `U15`, and a single leading apostrophe (`"Club '11/12 Blue"`) is enough to lose it. A band is the one season-independent cohort fact in a name, so a name that carries one reads as carrying no cohort and no year at all. That silence is what let a wrong cohort write through on 2026-09-15: `BRAUSA '11/'12 Blue` was moved u16 -> u12 on GotSport's `U12 Girls (2014/15)` record, which is a different squad; it was caught by hand and reverted. `extract_band_birth_year` refuses both apostrophe forms the same way, so the queue matcher, TGS and PlayMetrics lose the band too. Accepting `'` before either year in both patterns is the whole fix.
- **Noted**: 2026-09-16

### Merge the duplicate teams a cohort correction cannot move

- **ID**: IMP-241
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: teams data, not code; the candidates are derivable from `teams` alone (below), and `merging-duplicate-teams` owns the decision
- **Why**: 512 teams as of the 2026-09-16 re-check are held from an otherwise-confirmed age-group correction because a team with the same name and gender already sits in the target cohort. Moving one onto the other would put two identical teams on one board; leaving it holds a known-wrong cohort. Most likely one copy of a duplicate pair was mislabelled, which kept the pair apart and out of reach of the fuzzy duplicate merge (disabled: `FUZZY_AUTO_MERGE_ENABLED: 'false'` in `data-hygiene-weekly.yml`).
- **First**: matching name and gender is a candidate signal, not proof of one squad, so each pair needs the positive evidence `merging-duplicate-teams` requires -- both names resolving to the same birth-year set, plus schedules that either never share a season or share at least two opponents (`.claude/skills/merging-duplicate-teams/references/evidence-rules.md`, "What a merge requires"). Validate first; merge direction is the last question, not the only one. Pairs failing that bar are the more interesting half: a real cohort error the correction is still blocked on.
- **Reproduce the candidates** without the gitignored re-check output -- live teams sharing a name and gender across more than one cohort, 3,040 such groups covering 12,336 teams on 2026-09-16, a superset of the 512:
  ```sql
  SELECT lower(btrim(team_name)) AS name, gender, COUNT(*) AS teams
  FROM teams WHERE is_deprecated = false AND btrim(team_name) <> ''
  GROUP BY 1, 2 HAVING COUNT(DISTINCT age_group) > 1;
  ```
- **Noted**: 2026-09-16

### Match Stripe's MRR rules in computeMrr: discounts, interval_count, metered items

- **ID**: IMP-243
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/admin/subscription-metrics.ts` (`computeMrr`, `listAll`)
- **Why**: The dashboard MRR is meant to equal Stripe's Billing MRR. Stripe subtracts forever discounts, excludes metered prices, and normalizes every interval (with `interval_count`) to monthly; `computeMrr` does none of this and divides only `year`, so day/week read as monthly. None of it is reachable on 2026-09-16: zero discounts on any active or past_due subscription or item, and every item licensed with `interval_count` 1 on month or year. But checkout sets `allow_promotion_codes: true`, so a coupon can go live with no deploy. Repeating and one-time discounts follow a Billing "Configure" setting the API cannot read, and discounts come back as IDs unless expanded on the list call.
- **Noted**: 2026-09-16

### Make the canceling email routing survive out-of-order Stripe webhooks

- **ID**: IMP-246
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/api/stripe/webhook/route.ts` (`handleCheckoutCompleted` enrollment dedupe, `handleInvoicePaid` paid routing, `handleSubscriptionUpdated` reactivation branch)
- **Why**: The stored `cancel_at_period_end` flag is how the webhook detects a canceling or reactivation transition, and two orderings still misroute. A checkout event retried after fulfillment that finds a newly scheduled cancellation stores the flag and sets lifecycle `canceling`, but enrollment is skipped because `priorStatus` equals the status, so Cancellation Save never starts and the later update sees no change. And `handleInvoicePaid` routes a trialing or past_due subscriber to `paid` without clearing a stored flag, so if it lands before the update that removed the cancellation, the update routes `paid` again and starts a second Paid Drip journey. Both need delayed, out-of-order delivery; the owner chose to ship without them (PR #1162 review).
- **Noted**: 2026-09-16

### Fix blog FAQ schema/body drift and add a question→answer parity test

- **ID**: IMP-070
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/lib/blog-faqs.ts` (`BLOG_FAQS`), `frontend/lib/blog-faqs.test.ts` (`NEW_SLUGS`), post bodies in `frontend/content/blog/*.mdx`
- **Why**: FAQs are dual-source: the visible copy lives in each post body and the JSON-LD copy in `BLOG_FAQS`. Google requires FAQPage answers to be visible on the page, so drift risks rich-result eligibility. The parity test guards only the three slugs hard-coded in `NEW_SLUGS`. With the test's own normalization applied, 22 of the 34 registered slugs that have an MDX post fail question→answer parity. Three questions are registered by several posts ("Should my child be on the highest-ranked team possible?" on 6), so a duplicate allowance must name its owning slugs. Derive the guarded slugs from `STATE_PILLAR_SLUGS` plus the registry keys, so a pillar that never registers FAQs cannot go unguarded, and skip keys with no MDX post. Name known-broken posts in a set that fails once a member is fixed.
- **Noted**: 2026-07-27
- **Update (2026-09-17)**: Re-opened from the 2026-09-08 age-out after the Tennessee/Oregon guide review re-measured the drift.

### Correct three shared template claims in the older state guides

- **ID**: IMP-247
- **Status**: open
- **Type**: plan
- **Category**: docs
- **Where**: `frontend/content/blog/*-youth-soccer-rankings-guide.mdx` (the 23 guides other than Tennessee and Oregon): "How … Rankings Actually Work", "State Cup and Rankings" and "What Coaches Actually Look At" sections
- **Why**: Three template lines carry claims the Tennessee/Oregon review found wrong or unverified, each under several spellings, so grep every variant. A claim that ranking systems count tournament games only appears in all 23 ("count tournament games only" or "only count tournament games"); 19 attribute it to GotSoccer, and Arizona, Colorado, Michigan and Pennsylvania say "most ranking systems". GotSport awards placement points for leagues too. "GPA and test scores filter players" appears in all 23; NCAA Division I dropped the standardized-test requirement for students enrolling from 2023-08-01. "Higher-ranked teams generally earn better draws" appears in 20 as "better draws" or "better tournament draws". Check it against each state's own State Cup rules rather than removing it: Oregon uses a blind draw and Tennessee qualifies from State League (both verified against the associations' State Cup pages), while Idaho and Oklahoma reportedly seed by prior results (unverified: check their State Cup rules).
- **Noted**: 2026-09-17

### Remove the Utah state from English club teams on the Utah rankings

- **ID**: IMP-248
- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `teams.state_code` for GotSport teams whose raw `teams.state` is NULL, surfacing through `rankings_view` / `state_rankings_view` (state `UT`)
- **Why**: About 63 of Utah's 272 ranked teams are English academies with `state_code = 'UT'` and no raw state, among them Bromley FC, York City FC, Luton Town Community Trust and 7 Elite Academy (GB). They fill 57 of the 71 places on the Utah U19 boys board (measured 2026-09-17), and they block the Utah state guide. Find how UT was assigned before clearing it. The fix removes the wrong US state; it does not assign a foreign one, since non-US clubs get no state-assignment effort.
- **Noted**: 2026-09-17
- **Update (2026-09-17)**: How UT was assigned: `discover_teams_from_opponents.py` gave each newly discovered team the state of the team it had played until #1055 (2026-08-29), and the 2026-08-30 state sweep then propagated the label to clubmates through Tier B. The league is not Utah-only -- the same teams sit under MI (~320) and CA (~195) as well. Being addressed a layer up rather than by clearing the state: `team_ranking_exclusions` (PR #1168) drops these teams and their games from the rankings entirely, which takes them off every state board and the national ones. 817 reviewed teams were written to that table on 2026-09-17. Close this entry once the following Monday's run is verified; clearing `state_code` afterwards is optional and would leave them nationally ranked.

### Revise the blog line that says PitchRank is not for tournament directors

- **ID**: IMP-249
- **Status**: open
- **Type**: direct
- **Category**: docs
- **Where**: `frontend/content/blog-posts.tsx` (the "built PitchRank for parents and coaches" paragraph, ~line 819)
- **Why**: It says PitchRank was built "not for tournament directors or league administrators", which contradicts the /matchbalance sales page aimed at exactly those directors. Kept out of the page build so the blog edit ships as its own change with its `modifiedDate` bumped.
- **Noted**: 2026-09-16

### Build the Streamlit MatchBalance quote on the public page's fixed tiers

- **ID**: IMP-250
- **Status**: open
- **Type**: plan
- **Category**: feature
- **Where**: `tournament_intake.py` Seeding tab and `src/tournaments/seeding_intake_ui.py` (`render_seeding_pack`); no quote code exists yet
- **Why**: /matchbalance publishes fixed tier prices (`EVENT_PRICING` and `COHORT_PRICING` in `frontend/app/matchbalance/page.tsx`) in place of the original build brief's $3 per team. A grep of `src/tournaments/` and `tournament_intake.py` on 2026-09-16 found no quote or pricing logic, so nothing is wrong today, but whoever builds the operator quote step must use these tiers or quotes will disagree with the page.
- **Noted**: 2026-09-16

### Seeding sheet state ranks mix full state names and codes

- **ID**: IMP-251
- **Status**: open
- **Type**: direct
- **Category**: readability
- **Where**: `src/tournaments/seeding_pack.py` (`snapshot_ratings`), `src/tournaments/seeding_sheet.py` (`_state_rank`)
- **Why**: One sheet shows both "Texas #60" and "TX #101". `snapshot_ratings` keeps the Compare predictor's team `state` and only falls back to `make_ratings_lookup`'s `state_rankings_view.state` when the predictor lacks one. The view returns only codes (live: 14,238 rows `TX`, none `Texas`), while `matchPredictionService.ts` selects both `teams.state` and `state_code`, so the full name most likely comes from the predictor side. Visible on the public sample `frontend/public/matchbalance/sample-u13-boys.pdf`; normalize to one form in the sheet, then re-render that sample.
- **Noted**: 2026-09-16

### Share the MatchBalance inquiry rate limit across serverless instances

- **ID**: IMP-252
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `frontend/app/api/matchbalance-inquiry/route.ts` (`POST`, the ``checkRateLimit(`matchbalance:${ip}`, ...)`` call) and `frontend/lib/api/rateLimit.ts` (`checkRateLimit`)
- **Why**: The 5-per-hour limit lives in a per-instance in-memory `Map`, so each Vercel instance grants its own quota and a scripted caller spread across instances or IPs gets more; the route emails a confirmation to whatever address is submitted. One option is counting `matchbalance_leads` rows with the same `source_ip_masked` in the last hour before the insert. Deferred by the owner on 2026-09-17: the route already refuses non-JSON bodies (so another site cannot post from its visitors' browsers) and the confirmation carries nothing the submitter typed.
- **Noted**: 2026-09-17

### Extract the helpers the MatchBalance build copied instead of sharing

- **ID**: IMP-253
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: admin `formatDate`/`formatRelative`/`KpiCard` in `frontend/app/mission-control/leads/page.tsx` and `subscriptions/page.tsx`; `formatSupabaseError` in `frontend/lib/admin/matchbalance-leads.ts` and `subscription-metrics.ts`; `bad`/`maskIp`/`isStringWithLen` in `frontend/app/api/matchbalance-inquiry/route.ts` and `app/api/feedback/route.ts`; `escapeHtml` in `frontend/lib/email/matchbalance-inquiry.ts`, `lib/email/feedback.ts` and `app/api/stripe/webhook/route.ts`; the hero stripe band and FAQ `<details>` markup in `frontend/app/matchbalance/page.tsx` and `app/report-card/page.tsx`; `_executable` in six `tests/unit/test_*` migration guards and `_newest_statement` in two of them
- **Why**: Copies already disagree: the Stripe webhook's `escapeHtml` escapes only `&`, `<` and `>` (enough for its Telegram messages, not for an HTML attribute), and `test_team_page_views_migration.py`'s `_executable` strips only `--` comments, so a block-commented REVOKE passes that guard; only the `test_scrape_requests_rls_migration.py` and `test_matchbalance_leads_migration.py` copies also strip `/* */` comments (helper bodies read 2026-09-17). A fix to date rendering or escaping otherwise has to find every copy. Deferred by the owner on 2026-09-17 to keep the MatchBalance change scoped.
- **Noted**: 2026-09-17

### Bound the email check and require JSON on the other public POST routes

- **ID**: IMP-254
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `frontend/lib/validation.ts` (`isValidEmail`, `EMAIL_REGEX`), called uncapped from `POST` in `frontend/app/api/feedback/route.ts`, `frontend/app/api/newsletter/route.ts` and `frontend/app/api/reports/team-card/route.ts`
- **Why**: `EMAIL_REGEX` backtracks quadratically on a long malformed value (node, 2026-09-17: 16 KB 48 ms, 32 KB 188 ms, 64 KB 731 ms), and these public routes run it with no length cap, so a large body ties up the function. They also read the body with `request.json()` / `parseJsonBody`, which parse a `text/plain` body, so another site can post to them from visitors' browsers with no CORS preflight. `/api/matchbalance-inquiry` already caps the email at 254 characters and returns 415 without `Content-Type: application/json`; capping inside `isValidEmail` would cover every caller.
- **Noted**: 2026-09-17

### Match each side of an imported game at its own cohort, not the game's

- **Type**: plan
- **Category**: reliability
- **Where**: `src/models/game_matcher.py` `GameHistoryMatcher.match_game_history` (home and away `_match_team` both take `game_data.get("age_group")`); `src/etl/enhanced_pipeline.py` `_transform_game_perspective`
- **Why**: Scrapers write an `age_group` per team on each perspective row, but one row per game reaches matching and both sides are matched or autocreated at that row's cohort. So one misread name also misfiles its correctly named opponent. On the Wisconsin SECL Fall 2026 PlayMetrics scrape, a reviewer's import-order replay put 16 misparsed names' spread at up to 36 of 261 teams (the name parse is fixed on `playmetrics-wi-secl-fall-2026`; the spread path is not). Provider-wide, not PlayMetrics-only.
- **Noted**: 2026-09-17

### Find Wisconsin PlayMetrics teams filed a cohort off by last season's name parse

- **Type**: investigate
- **Category**: reliability
- **Where**: `scripts/scrape_playmetrics_league.py` `derive_team_age_group` (as it stood before `playmetrics-wi-secl-fall-2026`); WI teams holding PlayMetrics aliases
- **Why**: The Fall 2025 (`1014-1514`) and Spring 2026 (`1014-1926`) Wisconsin leagues were imported while the parser missed a U-age with a gender letter fused on (`U11B`, `11uG`), falling back to the division's play-up age, and read `2013/2014` bands by the older year. Some WI teams may exist as wrong-cohort duplicates bound by approved aliases. Measure read-only first: WI PlayMetrics-alias teams whose name U-age disagrees with the stored cohort, and whether a same-name sibling sits at the name's cohort. Then use the `correcting-team-age-groups` and `merging-duplicate-teams` skills.
- **Noted**: 2026-09-17

### Share the operator-script and test-double scaffolding instead of copying it per file

- **ID**: IMP-255
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `get_client` (10 files under `scripts/`, e.g. `exclude_english_teams.py`, `exclude_none_opponent_games.py`, `apply_vetted_team_merges.py`); `_paged` (3, incl. the `order("id")` variant in `enqueue_helpers.py`); the `_Query`/`_DB` PostgREST double (8 files under `tests/unit/`); `_executable` and friends in the migration guards (7 files under `tests/unit/`)
- **Why**: Counts verified by grep on 2026-09-17, and the guard-helper spread is wider than it looks -- 7 files define `_executable` while only 3 define `_tree`, so the copies have already drifted. CLAUDE.md requires a test double to refuse what production refuses; that rule now has 8 homes, and a fix to how the double pages or rejects a call has to reach every one, with any copy left behind still passing for the wrong reason. The same holds for the guards' comment-stripping: correcting it in one leaves the others matching commented-out SQL. Pre-existing duplication that the English-team exclusion work extended by one copy of each rather than introduced.
- **Noted**: 2026-09-17

### Catch English-league teams that arrive after the exclusion list was built

- **ID**: IMP-256
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/exclude_english_teams.py` (`grow`, `build_snapshot`); `scripts/discover_teams_from_opponents.py` (`_build_team_metadata`, `create_team_and_alias`)
- **Why**: `team_ranking_exclusions` keeps a listed team out however many new fixtures it plays, but nothing stops a *new* English identity entering. Discovery creates a team from name, age and gender alone and queues it for scraping, and the weekly state job runs with `--no-tier-a`, so nothing asks the provider where a new registration is. A fresh English team playing other unlisted English teams accumulates games and becomes nationally ranked exactly as this population did. The exclusion script is manual, so nobody is told. Wanted: a recurring report of candidates the graph rule reaches but nobody has decided on, and an admission-time rule using the provider's association rather than the opponent's state. Raised by a design review of PR #1168 on 2026-09-17.
- **Noted**: 2026-09-17

### Give team_ranking_exclusions a correction path when later evidence contradicts a row

- **ID**: IMP-257
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/exclude_english_teams.py` (`apply_snapshot`); `team_ranking_exclusions`
- **Why**: `--execute` only inserts what is missing, so a row survives evidence that arrives after it was written: a later GotSport probe confirming the team as US, or a fresh snapshot that no longer reaches it, changes nothing, and the team stays unranked with nobody told. Merge expansion compounds it in the other direction -- an exclusion transfers to whatever team absorbs a listed one, so a wrong merge can suppress a US survivor's whole record without a new row being written. Wanted: a report of listed teams whose current evidence disagrees with the reason they were listed, covering both shapes, and a recorded basis for rows admitted by the game graph alone rather than by a provider answer. Deleting a row already restores the team at the next run, so this is about noticing, not about mechanism. Raised by a design review of PR #1168 on 2026-09-17.
- **Noted**: 2026-09-17

### Let the team-name normalizer read bands through extract_band_birth_year

- **ID**: IMP-258
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `scripts/normalize_team_names.py` `_resolve_band` / `_BAND_RE`; `src/utils/team_utils.py` `extract_band_birth_year`
- **Why**: The normalizer's band reader disagrees with the shared one. Verified 2026-09-18: `_resolve_band` reads a spaced three-year list by its first pair (`"CSC 2014 / 2015 / 2016 Boys"` -> `"CSC U12 / 2016 Boys"`), which the shared helper declines; reads nothing from a band touching a hyphen or word (`"FC Academy-2013/2014 Boys"`, `"Eternal 2012/2013Black"`, `"Club 2013/2014-Red"`), which the shared helper reads; and files the aged-out 2007/06 band as U19 through `calculate_age_group_from_birth_year`'s age-20 fold (`"Team 2007/2006"` -> `"Team U19"`), where the shared path assigns no cohort. The normalizer rewrites stored team names weekly, so converging changes stored names: take a dry-run rename diff before shipping.
- **Noted**: 2026-09-18

### Club-name override entries that name a U-age go stale every Aug 1

- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `CLUB_CANONICAL_OVERRIDES` in `scripts/full_club_analysis.py`
- **Why**: 15 `exact` entries match a club name carrying a U-age that moves each season: eight "SOZO FC ... - GU14/BU12" rows in WA plus "Sporting Kansas City U16", "Michgan jaguars u17", "columbus crew u16", "Real Colorado u17", "Chicago Fire FC U16", "Real Salt Lake U16" and "la galaxy u16". Once the provider relabels the squad, the new label matches no entry and keeps its U-age as a club spelling, while the old entry matches nothing. Birth-year squad codes ("Sound FC B14A", "PacNW G12E") do not age the same way. Wanted: match the club part, or drop entries that have not matched a live club in a season.
- **Noted**: 2026-09-18

### Three copies of the club-suffix normalization

- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: `normalize_for_grouping` in `scripts/full_club_analysis.py`; `normalize_club_for_comparison` in `src/utils/team_name_utils.py`; `normalize_club_name` in `scripts/match_state_from_club.py`
- **Why**: Each folds "Soccer Club"/"S.C."/"Football Club" suffixes its own way, so the weekly cleanup, team-name utilities and the retired state lookup can disagree about whether two spellings are one club. `_light_form` in `src/utils/club_normalizer.py` does the same folding to codes and could be the one implementation.
- **Noted**: 2026-09-18

### Team matchers score differently wherever rapidfuzz is installed

- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `HAVE_RAPIDFUZZ` branches in `GameHistoryMatcher._calculate_similarity` and `_calculate_match_score` (`src/models/game_matcher.py`), which the SincSports and TGS matchers inherit; their own `HAVE_RAPIDFUZZ` flags are set and never read
- **Why**: rapidfuzz is in neither `requirements.txt` nor `requirements.lock`, so CI and every workflow take the difflib path, while a local run with rapidfuzz installed scores fuzzy team matches with a different library. Thresholds measured locally are therefore measured against something production does not run. `src/utils/club_normalizer.py` and `src/models/squad_name_gates.py` are difflib-only for this reason.
- **Noted**: 2026-09-18

### Damaged club spellings from weekly cleanups before 2026-09-14 are not repaired

- **Status**: open
- **Type**: investigate
- **Category**: reliability
- **Where**: `caps_winner` and `merge_case_variants` in `scripts/full_club_analysis.py`; `parse_cleanup_log` in `scripts/repair_swapped_club_names.py`
- **Why**: The weekly cleanup's re-case, before it learned a vocabulary, lowered articles and inner capitals as well as abbreviations ("SoCal" -> "Socal", "McLean" -> "Mclean"). `repair_swapped_club_names.py` undoes only the runs whose logs it is given (the 2026-09-14 run), and `caps_winner` adopts a group's majority mixed-case spelling, so a majority damaged by an earlier run is copied onto the correct minority: the 2026-09-18 dry run moves CA "ALBION SC Los Angeles" to "Albion SC los Angeles". Finding them needs the older run logs (GitHub keeps about 90 days) or a pass comparing each spelling with the learned vocabulary.
- **Noted**: 2026-09-18

### The weekly club cleanup rewrites a tracked SQL file even on a dry run

- **Status**: open
- **Type**: direct
- **Category**: dx
- **Where**: `main` and `SQL_OUTPUT_PATH` in `scripts/full_club_analysis.py`
- **Why**: Every run, `--dry-run` included, overwrites the tracked `scripts/club_name_fixes_male_all_states.sql`, so a local preview leaves a modified tracked file that is easy to commit by accident; the file is regenerated each Monday anyway. Write it only under `--execute`, or to `logs/` beside the other outputs.
- **Noted**: 2026-09-18

### An unregistered club's club_id still merges clubs that are_same_club keeps apart

- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `normalize_to_club` (unmatched branch) and `group_by_club` in `src/utils/club_normalizer.py`
- **Why**: For a name that resolves to no registered club, `club_id` comes from the suffix-stripped `normalize_club_name`, so "Tyler FC" and "Tyler SA" (or "Charlotte SC" and "Charlotte Soccer Academy") share a `club_id` and `group_by_club` puts them in one group, while `are_same_club` keeps them apart. No live matcher is affected: `_calculate_match_score` in the base, SincSports and TGS matchers compares `club_id` only when both names are registered. `group_by_club` has no production caller, but the matching-tournament-rosters skill reference points agents at it.
- **Noted**: 2026-09-18

### Decide the future of the pitchrank-alias-normalizer skill

- **Type**: plan
- **Category**: docs
- **Where**: `.claude/skills/pitchrank-alias-normalizer/SKILL.md`
- **Why**: 24 lines, one commit, last touched 2026-01-30 — the only project skill never revised. It predates the club-normalizer rewrite and every data-hygiene skill, and its stated job (raw name to canonical club_id plus extracted birth year, gender, tier and branch) now overlaps `normalizing-club-names` on the club half and `correcting-team-age-groups` on the age half. It describes a CSV-producing workflow with no driver script in the repo, so a session it triggers gets guidance written against a codebase that has moved. Retire it, narrow it to what nothing else covers, or bring it current.
- **Noted**: 2026-09-20

### Split the merging-duplicate-teams skill body into its references

- **Type**: plan
- **Category**: docs
- **Where**: `.claude/skills/merging-duplicate-teams/SKILL.md`, the "What the signals are actually worth" and containment delta-class sections
- **Why**: 660 lines against the 500-line authoring guideline, and by far the largest of the hygiene skills (the others are 398, 296 and 184). It already carries three `references/` files those two measured tables could move into, which would bring the body under the guideline without losing content. A review also reported the candidate-bucketing rule being stated in more than one place within the package; that duplication was asserted rather than measured here, so confirm it while splitting.
- **Noted**: 2026-09-20

### The PDA and TFA branch splits are one-time moves that nothing reproduces

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/full_club_analysis.py:CLUB_CANONICAL_OVERRIDES` and `analyze_state`; the moves are logged in `data/exports/nj_pda_split_log.csv` and `ca_tfa_split_log.csv`
- **Why**: 326 teams were moved onto branch clubs their own team names identify -- 104 under Players Development Academy, 222 under Total Futbol Academy -- on the owner's decision of 2026-09-22. No override can reproduce it: `analyze_state` and `_matches_override` key on `club_name` alone and never read `team_name` (verified 2026-09-22), so a team re-imported under the parent stays there even when its name says TFA-SELA or PDA Hibernian. The parents will accumulate branch teams again, and unrelated branches sharing one `club_name` enter the same duplicate-matching pool. Raised by the Codex review on PR #1204; the split itself was accepted knowing this, so the fix is a recurring classifier -- in the weekly cleanup or at team creation -- not a revert.
- **Noted**: 2026-09-22

### Teach the shared state-name reader that "Washington County" is not Washington

- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/backfill_state_from_team_name.py:state_from_name` (beside `_PLACE_PREFIX` and `FALSE_FRIENDS`); the guard to move is `names_a_place` (with `PLACE_SUFFIXES` and `STATE_NAMED_TOWNS`) in `scripts/review_state_queue_by_name.py`
- **Why**: `state_from_name` reads "Washington County SC - U14" and "Washington City FC" as WA (verified 2026-09-22), so the weekly sweep's Tier C keeps proposing those moves and only the queue-review script knows to leave them. Moving the suffix check into the shared reader fixes every caller, but it changes what the scheduled sweep proposes, so measure the blast radius first. It was held out of the 2026-09-22 queue-review change because the owner asked to leave the weekly job's decisions alone.
- **Noted**: 2026-09-22

### Doorway C pairs only on club equality, so a club spelled two ways stays invisible

- **ID**: IMP-259
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/find_cross_provider_duplicates.py` (`build_pairs`), `.claude/skills/merging-duplicate-teams/SKILL.md` Doorway C
- **Why**: The committed detector pairs two rows only when their `club_name` values are equal once punctuation and case are stripped, which is the rule the 692-pair batch of 2026-09-22 was measured on. A club that two providers spell differently -- `Westy SC` against `Westy Soccer Club` -- therefore never produces a pair at all, and the skill's own rebrand-bridge route past that (mining `team_merge_map` for clubs already joined by a vetted merge, rebrand bridges only, branch bridges reject at 8.5% head-to-head) is still a hand-built query. `are_same_club` is already called in this file for the competing-partner screen, where a false positive only costs a review; using it to *pair* is the opposite risk and needs its own calibration before it ships. What that calibration needs: a labelled set the way the existing table was built -- owner-made merges as positives, same-club same-cohort pairs that played each other as negatives -- scored at several similarity thresholds, and a head-to-head rate per threshold to compare against the 0.43% base rate. The two containment tiers the skill tabulates (club prefix at 4x cleaner than base, `rl` / Roman numeral / bare number / colour as rejects) are unimplemented for the same reason and belong in the same piece of work.
- **Noted**: 2026-09-22

### Two merge-resolution semantics coexist, and six scripts carry their own copy of one of them

- **ID**: IMP-260
- **Status**: open
- **Type**: plan
- **Category**: refactor
- **Where**: chain-following copies in `scripts/apply_vetted_team_merges.py`, `decide_team_merges.py`, `enqueue_stranded_merge_fixtures.py`, `exclude_merge_duplicate_games.py`, `find_regid_duplicate_merges.py`, `find_cross_provider_duplicates.py`; single-hop in `src/utils/merge_resolver.py` (`MergeResolver.resolve`) and `scripts/enqueue_helpers.py` (`resolve_merges`)
- **Why**: Six scripts follow merge chains with `while tid in map and tid not in seen`; `MergeResolver` and `enqueue_helpers.resolve_merges` do a single `dict.get`, the latter documenting the assumption that `execute_team_merge` flattens chains so one hop suffices. Both answer identically today -- `team_merge_map` held 14,121 rows with 0 canonical ids that are themselves deprecated and 0 cycles when measured 2026-09-22 -- so this is latent, not a live defect, which is why it was left alone rather than fixed inside the Doorway C port. **Standardise on the chain-following semantics, not `MergeResolver`'s**: swapping the chain-follower for `MergeResolver` would make A->B->C read B and would break agreement with `apply_vetted_team_merges.py`, which consumes the detectors' output and follows chains itself. CLAUDE.md's "Use `MergeResolver` for any team ID lookup" points at the weaker of the two and wants updating in the same pass. `scripts/enqueue_helpers.py` is the landing pad -- it already holds `_paged`, `_chunks` and `resolve_merges` and is imported packaged by three scripts plus its own test -- and the same extraction covers the third copy of the ordered pager and the twelfth of `get_client`. Note `find_cross_provider_duplicates.page` is the strongest pager of the three (it advances by rows returned, so a server cap below the requested size cannot truncate it silently); extract that one rather than the older short-page variants. Surfaced by the consistency and peer reviews of the Doorway C port; out of scope there because it spans six unrelated scripts.
- **Noted**: 2026-09-22

### csv_safe is copy-pasted into five scripts

- **ID**: IMP-261
- **Status**: open
- **Type**: direct
- **Category**: refactor
- **Where**: `scripts/fix_band_cohorts.py:135,138`, `scripts/reconcile_teams_with_gotsport.py:116,156`, `scripts/repair_swapped_club_names.py:140,153`, `scripts/full_club_analysis.py:3030,3646`, imported from the first by `scripts/find_cross_provider_duplicates.py`
- **Why**: Four scripts declare an identical `_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r", "\n"})` and a `csv_safe` beside it; three of the four share a byte-identical implementation line under differently-worded docstrings, and `full_club_analysis.py`'s body differs. This is a security control against spreadsheet formula injection in operator-facing CSVs, so the copies drifting apart is the failure that matters -- a prefix added to one set protects one export. The Doorway C detector imports from `fix_band_cohorts` rather than adding a fifth copy, which makes a 700-line data-fix script an unlikely dependency of a detector. Wants one home in `src/utils/`, with the four declaring copies switched to import it. Small and self-contained; kept out of the Doorway C port only because that change was already touching the CSV-escaping path itself.
- **Noted**: 2026-09-22

### .pytest_cache is not gitignored, so every test run leaves an untracked directory

- **ID**: IMP-262
- **Status**: open
- **Type**: direct
- **Category**: dx
- **Where**: `.gitignore` (the `__pycache__/` entry at line 15 has no `.pytest_cache/` counterpart)
- **Why**: Verified 2026-09-22: `git check-ignore -v __pycache__` resolves to `.gitignore:15`, while `git check-ignore -v .pytest_cache` matches nothing. Any `python -m pytest` run therefore leaves `.pytest_cache/` in `git status --untracked-files=all`, in the main checkout and in every linked worktree. The cost is not the noise itself but that this checkout is shared: an untracked directory you did not create is the signal that another session is mid-work, and a per-run artifact that looks identical erodes it. Two review agents this session passed `-p no:cacheprovider` specifically to avoid creating it, which is a workaround each reader has to rediscover. One line in `.gitignore`.
- **Noted**: 2026-09-22

### pr_wait polls required checks on a conflicting PR, where none can ever start

- **ID**: IMP-264
- **Status**: open
- **Type**: direct
- **Category**: dx
- **Where**: `scripts/pr_wait.py` (the poll loop; it reads `statusCheckRollup` but never `mergeable` / `mergeStateStatus`)
- **Why**: A PR whose branch conflicts with main gets no `ci.yml` run at all, so the seven required checks never appear. The script has no conflict check and waits out its full window reporting "waiting on Frontend Format, Frontend Lint, ..." for jobs GitHub is never going to schedule. Observed on #1208 (2026-09-23): nine minutes of polling before the Codex ceiling ended it, after which `gh pr view --json mergeable` returned `CONFLICTING` / `DIRTY` immediately. One `mergeable` read at the top of the loop turns a silent wait into a named conflict. Report the base rather than prescribing a command: `resolve_pr` already selects `baseRefName` (`:85`) and keys `required_contexts` off it (`:185`), and a stacked PR's base is another feature branch, so "merge origin/main" would be the wrong instruction and could pull in unrelated commits. Merging the base is the resolution rather than rebasing, since the guard blocks the force-push a rebase needs.
- **Noted**: 2026-09-23

### The commit guard reads the branch of the payload cwd, not the directory git will run in

- **ID**: IMP-265
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `.claude/hooks/git-guard.sh:87` (`target` is resolved at `:77-84`, then `branch=$(branch_of "$cwd")` at `:87`)
- **Why**: The hook computes `target` correctly at `:77-84`, honouring a `git -C <dir>` or an earlier `cd <dir>`, and its own comment says every check below "answers about the wrong repository otherwise". Line 87 then reads `branch_of "$cwd"` rather than `branch_of "$target"`; only the `git -C` form re-resolves, at `:88-90`. The consequence is a false rejection: `cd <feature-branch worktree> && git commit` is refused whenever the main checkout happens to sit on main, which is routine while worktrees are in use and was hit on 2026-09-23. **It is not a bypass** -- a separate check at `:103-111` resolves the `cd` target independently and denies when *that* checkout is on main, covered by `test_git_guard_blocks_commit_on_main`; an earlier draft of this entry claimed otherwise and was wrong. So the fix is narrow: read `$target` at `:87`, which also makes `:88-90` redundant. Hooks here go live for every session the moment the file is saved, so fixture-test the change before committing it.
- **Noted**: 2026-09-23

### Decide whether an older or different-gender matched team should still hold a seeding pack in draft

- **ID**: IMP-266
- **Status**: open
- **Type**: plan
- **Category**: feature
- **Where**: `src/tournaments/seeding_pack.py:_review_reason` (the gender-group and "older than this age group" branches)
- **Why**: Both branches return "Data review required", and any such status forces the pack into draft. The owner said on 2026-09-23 that the director's list decides a team's division whatever its own age: "It doesnt matter what age the team is. Example if they are u11 and they signed up for the u12 bracket then that is what we are using." Younger teams already pass; older and different-gender matches do not, so the two rules may disagree. Ask the owner before changing it.
- **Noted**: 2026-09-23

### Show a dash instead of "None" for unseeded rows in the Seeding tab's seed grid

- **ID**: IMP-267
- **Status**: open
- **Type**: direct
- **Category**: readability
- **Where**: `src/tournaments/seeding_intake_ui.py:_render_cohort_review` (the rows passed to `st.data_editor`, `"Seed": row.seed`)
- **Why**: Unseeded rows carry `seed=None`, which the grid renders as "None", while the neighbouring empty cells use "—". A 2026-09-23 smoke run also saw the "PitchRank match" column stay empty after "Load PitchRank team names" when the pasted names matched PitchRank's exactly; the cause is unverified and may be intended.
- **Noted**: 2026-09-23

### Keep a blocked walk's pages in the command-line event walk too

- **ID**: IMP-268
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `scripts/scrape_event_roster.py:main` (the `except WafChallengeError` branch)
- **Why**: A blocked walk exits with "Blocked: ..." and drops `exc.partial`, the roster it already paid for, while the Seeding and Backtest tabs now save it through `tournament_intake._keep_blocked_walk`. Saving it here means routing the partial through the CLI's own roster writes, and never replacing a saved file that already holds as many distinct provider team ids, the rule `_keep_blocked_walk` applies. The `_write_roster` docstring already describes a blocked walk writing, which becomes true only once this is done.
- **Noted**: 2026-09-23

### Keep the Backtest view's "published no teams" warning across its rerun

- **ID**: IMP-269
- **Status**: open
- **Type**: direct
- **Category**: ux
- **Where**: `tournament_intake.py` `_run_event_roster_scrape` (the `if not parked:` branch)
- **Why**: A Backtest walk that parks no teams calls `st.warning(message)` and then `st.rerun()`, so the rerun erases the warning and the operator sees an empty result with no reason given. The Seeding arm of the same `if` queues its copy through `_add_seeding_notice`, which survives the rerun. Backtest already has a carry-across-rerun pattern to reuse: `bt_history_notice_{event_key}` in `src/tournaments/backtest_intake_ui.py`, set before the rerun and popped when drawn.
- **Noted**: 2026-09-24

### The first pick in "Open a saved run" is dropped right after a save adds a run

- **ID**: IMP-270
- **Status**: open
- **Type**: investigate
- **Category**: ux
- **Where**: `tournament_intake.py` `_render_seeding_run_controls` (the `seeding_resume_choice` selectbox)
- **Why**: Streamlit 1.50's selectbox folds `options` into its element id (`key_as_main_identity={"options", ...}` in `streamlit/elements/widgets/selectbox.py`). "Save this run" writes a new run after the picker has already drawn, so the next rerun draws the picker with a longer list under a new id, and the browser's first choice, made against the old one, is discarded. A browser smoke run on 2026-09-24 reproduced it: saving "Cup B" and then choosing "Cup A" left the page on Cup B, and a second pick worked. Main draws the picker before the save controls too, so this likely predates the Seeding run-safety change; it has been reproduced only with that change applied. Candidate fixes: rerun after a save that adds a run, or draw the picker after the save controls.
- **Noted**: 2026-09-24

### Close the DNS-rebinding path into the local Streamlit apps

- **ID**: IMP-271
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `.streamlit/config.toml` `[server]`, shared by `dashboard.py` and `tournament_intake.py`
- **Why**: The loopback bind and origin check refuse a foreign page, but a page whose domain re-points to 127.0.0.1 mid-visit passes. Tornado's same-host origin check sees Origin and Host agree, and Streamlit has no Host allowlist. Against Streamlit 1.50, a request of that shape gets a 101 on the websocket (checked 2026-09-24). XSRF does not help, because the websocket checks the token only on the login-cookie path. The owner declined adding a password on 2026-09-24, which leaves a Host allowlist hooked into Tornado; that hook is fragile across Streamlit upgrades, so it would need a test against the installed version.
- **Noted**: 2026-09-24

### Decide whether the Codespaces launch should keep CORS and XSRF off

- **ID**: IMP-272
- **Status**: deferred
- **Type**: investigate
- **Category**: reliability
- **Where**: `.devcontainer/devcontainer.json` `postAttachCommand`
- **Why**: The command passes `--server.enableCORS false --server.enableXsrfProtection false`, and CLI flags beat `.streamlit/config.toml`, so inside a Codespace the dashboard runs without the origin check `.streamlit/config.toml` enables. It still binds 127.0.0.1, and Codespaces forwards ports privately by default. The flags are probably what lets the dashboard load behind the `*.app.github.dev` proxy, so removing them untested could break it. The owner does not use Codespaces (2026-09-24).
- **Noted**: 2026-09-24
- **Trigger**: Anyone opens PitchRank in a Codespace or devcontainer.

### Bundle the state-run helpers into the merging-duplicate-teams skill

- **ID**: IMP-273
- **Status**: open
- **Type**: plan
- **Category**: dx
- **Where**: `.claude/skills/merging-duplicate-teams/scripts/` (new), beside `build_review_page.py` and `collect_review_decisions.py`
- **Why**: Running Doorway D state by state on 2026-09-24 (OK, KY, NC, TX; 1,488 merges) relied on three helpers that exist only in a session scratchpad: a post-apply check over the apply logs (self-play, names stating both genders, names two or more birth years apart, same-day two-event dates), a classifier that splits those dates into already-on-one-row / recorded-twice / merge-created (on TX it cut 331 flagged dates to 3 merge-created, 1 real), and the reviewer brief with its input-to-output name check, which caught two swapped verdict lines in OK. Bundle them as skill scripts with unit tests through the Supabase double and point `references/state-runs.md` at them.
- **Noted**: 2026-09-24

### Batch the team lookup that auto-hides twins of excluded games

- **ID**: IMP-274
- **Status**: open
- **Type**: direct
- **Category**: reliability
- **Where**: `src/etl/enhanced_pipeline.py` `EnhancedETLPipeline._propagate_exclusions_to_new_games`
- **Why**: It builds one `.or_()` filter naming every master team on a date (`home_team_master_id.eq.X,away_team_master_id.eq.X` per team) and sends it in a single request. `_check_duplicates_by_master_ids` batches the same query with `self._chunks(..., 50)`; this second copy does not. A date with enough teams can exceed the URI limit, and the method's broad `except` then logs a warning and skips the date, so a new copy of an already-excluded game is inserted live (failure mode reported by review, not reproduced). Apply the same batching, with a test whose two teams fall in different batches.
- **Noted**: 2026-09-24

### Move the GotSport scraper's division-gender reader onto the shared label reader

- **ID**: IMP-275
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/scrapers/gotsport.py` `_parse_division_gender`; `src/tournaments/cohort_labels.py` `read_label`
- **Why**: The seeding paste parser and event walker read labels through `read_label`, but the scraper feeding the scheduled imports keeps its own gender grammar, which ignores a gender letter on a birth year or band (`B2013`, `G2015/2016`). The owner kept it out of the seeding fix on 2026-09-24 because changing it moves how scraped divisions are gendered, and with that the rankings. Measure the before and after against real scraped divisions before switching.
- **Noted**: 2026-09-24

### Pin the walker's birth-year tests to a season instead of the wall clock

- **ID**: IMP-276
- **Status**: open
- **Type**: direct
- **Category**: testing
- **Where**: `tests/unit/test_gotsport_event_roster.py` `test_completed_birth_year_uses_the_event_date_for_published_age`, `test_reads_a_birth_year_label_onto_its_board`, `test_a_boardable_birth_year_still_resolves`, `test_names_a_cohort_the_boards_exclude`
- **Why**: It asserts the current-identity cohort of a `B2014` team as `u13`, which is true only in the 2026-27 season. The age comes from `resolve_cohort`, which reads the live season, so the test goes red on 2027-08-01 with no code change. Pin the season with a `team_utils._soccer_season_year` monkeypatch, as the label tests beside it do. The same wall-clock dependence breaks `TestResolveCohort.test_reads_a_birth_year_label_onto_its_board` and `test_a_boardable_birth_year_still_resolves` (both `G2007 Gold`, which ages out of u19), and the `B2018 Silver` case in `TestNamesCohortOutside.test_names_a_cohort_the_boards_exclude` (which ages onto the u10 board).
- **Noted**: 2026-09-24

### Keep an interrupted Seeding build findable after the run is renamed mid-build

- **ID**: IMP-277
- **Status**: open
- **Type**: plan
- **Category**: reliability
- **Where**: `src/tournaments/seeding_run_store.py` `PackRecovery`; `tournament_intake.py` `_render_seeding_sheet`
- **Why**: The recovery file is keyed by the run name, so renaming the run while a build runs files the finished build under the old name, and the renamed page never offers it. It is not lost: a named run is autosaved when its roster is imported, so the old name appears under "Open a saved run" and reopening it offers the build. Keying the file by roster fingerprint, or listing recovery-only folders in the run picker, would close it. Raised by the Codex review on #1221; the owner chose to log it on 2026-09-24.
- **Noted**: 2026-09-24

### Reword the Seeding metadata-conflict reason that still says "rebuild matchup tiers"

- **ID**: IMP-278
- **Status**: open
- **Type**: direct
- **Category**: readability
- **Where**: `frontend/lib/seedingPredictions.ts` `metadata_conflict` reason; `src/tournaments/seeding_predictions.py` `seeding_predictor_sha256`
- **Why**: A team whose PitchRank details conflict is sent to data review with "... Then rebuild matchup tiers. Your team match is saved.", naming a button the Seeding tab no longer has ("Build seeding sheets"). The file is hashed into the predictor identity, so editing it makes every saved run report "The predictor has been updated" and need a rebuild; the owner chose on 2026-09-24 to change it with the next real predictor update instead. `seedingPredictions.test.ts` asserts only "Your team match is saved", so the wording change needs no test edit.
- **Noted**: 2026-09-24
