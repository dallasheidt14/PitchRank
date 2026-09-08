# Improvement backlog — verified ordering, 2026-09-08

Every one of the 97 then-live entries was checked against `origin/main` @ `e3c81a55b` by
nine parallel read-only verifiers, one per domain. 11 closed, 3 became `deferred`, 15 had
their premise corrected in place. What follows orders the 81 that remain open.

The ordering is by **what is actually going wrong today**, not by category or by age.
Within a batch, cheapest first.

## Two corrections that came out of the verification

**CLAUDE.md is wrong about the unknown-opponent chain.** It states that
`unknown-opponent-hygiene-weekly.yml` passes `--resolve-gotsport-details` to
`export_unknown_opponents.py` alone, "so the other three never construct a resolver on the
weekly run". Two of the three build one unconditionally, with no flag:
`discover_teams_from_opponents.py:543` and `due_diligence_unknown_opponents.py:282`. Only
`auto_match_unknown_opponents.py:446` is genuinely flag-gated. This makes IMP-143 a live
weekly exposure rather than a quarantined one, and it will misdirect the next person who
reads that paragraph. Fix the paragraph in whichever PR touches this chain first.

**The CAPTCHA block is narrower than the seeding entries assume.** The confirmed-blocked
path is `src/scrapers/gotsport.py`'s `scrape_games_from_schedule_pages`. The seeding
walker `src/tournaments/gotsport_event_roster.py` is a different fetch path that clears
the proof-of-work WAF via ZenRows JS-render, and it completed a real walk on
2026-09-06T19:30Z (`reports/seeding/gotsport_52975/last_walk.json`). Treat IMP-174 through
IMP-183 as at-risk, not dead — but confirm the walker still works before scheduling any
of them.

---

## Batch 1 — Reachable by someone who is not logged in

Four entries. Everything here can be exercised by an outsider or costs money when it is.
This is the only batch with a reason to start today.

| ID | What is wrong | Effort |
|----|---------------|--------|
| IMP-168 | `scrape_requests` accepts anonymous inserts. `20251113150557_add_scrape_requests.sql:28-29` is `FOR INSERT WITH CHECK (true)`, and `priority` has no CHECK constraint, so anyone holding the public anon key can inject `priority: 1` rows into the same lane a paying subscriber's click uses. Four later migrations touch the table and none of them alter this policy. | S |
| IMP-153 | **Downgraded on live evidence — moved to batch 4.** See below. | S |
| IMP-091 | `scripts/check_stuck_signups.py` (~155-180) calls `admin.generate_link(type="recovery")` and mails the live `token_hash` into a shared mailbox every 6 hours. Anyone with mailbox or Resend-history access holds a working password reset. Replace with `reset_password_for_email`, which mails the user instead. | S |
| IMP-090 | `frontend/app/auth/callback/route.ts:62-65` spends a PKCE `?code=` on a plain GET, so a scanner or link prefetcher can burn it with no click. The same file already added a `HEAD` override and an interstitial for `token_hash` links — this is the same fix, applied to the branch that was missed. | M |

### Live-database check, 2026-09-08 — read this before working batch 1

The grant questions were settled against the production database rather than the migration
history, and the answer moved one entry out of the batch.

`user_profiles` ACL is `anon=rdDxtm`, so **`anon` does hold SELECT, DELETE and TRUNCATE** —
exactly as IMP-153 says, and matching `20260610120000`, which revoked only INSERT and
UPDATE. But the table carries exactly one policy, `Users can view own profile`, `FOR SELECT
USING (auth.uid() = id)`. There is no DELETE policy at all, and with RLS enabled a command
with no permissive policy is denied. TRUNCATE is not RLS-governed, but `anon` is not a
login role — it is only ever reached by PostgREST switching into it, and PostgREST issues
no TRUNCATE. **So the DELETE and TRUNCATE grants are inert, and IMP-153 is defense-in-depth,
not a live hole.** It belongs with IMP-152 in batch 4's hardening bundle — the same class of
gap on three sibling tables, which the same check confirmed (`team_state_audit`,
`team_state_review_queue` and `tgs_events` all carry `anon=arwdDxtm`, while
`team_state_probe_log` correctly carries no anon entry at all).

`scrape_requests` is the opposite. Its ACL is `anon=arwdDxtm` **and** it carries
`Enable insert for all users` — `FOR INSERT`, role `public`, `WITH CHECK (true)`. Grant and
policy both permit it, so an anonymous caller really can insert queue rows at any priority.
IMP-168 is confirmed live and is the strongest item in the batch.

One thing that check turned up which no entry covers: `scrape_requests` also carries
`Enable read for authenticated users` as `FOR SELECT USING (true)` for role `public`, so
anon can read the whole queue. Worth noting alongside IMP-168 since it is the same policy
set and the same migration.

Deliberately **not** in batch 1: IMP-088 (emailed tokens are not bound to the recipient).
It is outsider-reachable and it is the most serious item in the backlog, but it is an `L`
that needs a design decision before any code. Give it its own spike after batch 1 lands.

## Batch 2 — Wrong data being written right now

| ID | What is wrong | Effort |
|----|---------------|--------|
| IMP-136 | `src/utils/team_name_utils.py:457` contains literal `0x08` backspace bytes where `\b` was intended. Confirmed at byte level: `birth_years('Club 12 Boys')` and `birth_years('Club Boys 12')` both return `set()`. The branch has never once fired. Worse, `scripts/check_merge_skill_assumptions.py:132-134` asserts the broken behaviour as expected — fix both or the guard re-pins the bug. | S |
| IMP-111 | `src/models/modular11_matcher.py:190-196` derives `season_year` from its own wall-clock arithmetic instead of reading `config/settings.py:95`. It is a hard filter in candidate matching, so drift produces wrong-year accepts and rejects. | S |
| IMP-149 | `src/utils/age_group.py` folds `{"u18","u20"}` into u19 but not `u21`, so GotSport's aged-out U21 labels keep creating out-of-board teams. Cheap, and it stops IMP-147's backlog from regrowing. | S |
| IMP-143 | `scripts/due_diligence_unknown_opponents.py:429-439` computes `core_ok` as `all(... != "mismatch")`, which is vacuously true when the resolver returns nothing. Per the correction above this runs weekly, unflagged, so a GotSport outage silently approves unknown-opponent matches on no evidence. | S/M |
| IMP-145 | Two files assert opposite readings of GotSport's `display_age_group`: `backfill_unknown_team_names.py:28-30` says never write it, `discover_teams_from_opponents.py:~200` writes it at highest precedence. One of them is mislabelling teams onto the wrong ranking board. Settle which, in code and in CLAUDE.md. | M |
| IMP-132 | `scripts/process_missing_games.py:187-198` scrapes only ±90 days around the enqueue row's `game_date`, but the success branch at :502-508 stamps `last_scraped_at = now()` regardless. A never-scraped team gets marked fully scraped after one narrow window, and the rest of its history is never fetched. The WAF branch at :556-562 already withholds the stamp correctly — mirror it. | M |
| IMP-097 | Hygiene runs 11:00 UTC with a 180-minute timeout and ~2.5h observed runtime; rankings start 12:30 UTC. Rankings can read half-merged team identities. There is no `workflow_run` gate between them and hygiene carries no concurrency group at all. | S |

## Batch 3 — Money, and one thing that will break on the next fresh checkout

| ID | What is wrong | Effort |
|----|---------------|--------|
| IMP-101 | `power_score_true` has no `ADD COLUMN` anywhere in `supabase/migrations/`, yet `src/rankings/data_adapter.py:1063-1064` upserts it for both engines. A fresh `supabase db push` fails. (`power_score_final` is fine — the entry overstated that half.) | S |
| IMP-139 | `scripts/backfill_unknown_team_names.py:226` selects placeholder rows on name pattern alone, and a 404 does `continue` with no write. Nothing records that a row is unresolvable, so the every-15-minutes cron re-probes the same dead rows forever on paid WAF budget. | S |
| IMP-131 | The `team_flags` CTE rescans the full ~3M-row `games` table every Sunday to recompute what `teams.last_fixture_at` already stores, refreshed weekly by the same migration that added it. | S |
| IMP-192 | 98 review-queue-approved teams still sit in the paid-probe population, because their `state_source` is `tier_x` rather than `operator`. `decide()` got the `approved_states` check in IMP-165; `contradiction_candidates` (`assign_team_states.py:687-692`) never did. The other half of this entry is already stale — hand-set teams are excluded now. | S |
| IMP-147 | **Measure before doing anything.** The entry's own numbers do not foot (2,871 + 1,597 exceeds its title's 2,937). `repair_out_of_board_cohorts.py:45` covers u0-u7/u21/u22 and deliberately skips u8/u9 and u20, so u20 has no repair path at all. Re-derive the counts against the live database first, then decide scope. | L |
| IMP-195 | `enqueue-discovery.yml` and `enqueue-safety-net.yml` are pure `schedule` triggers with no dependency on the activity refresh that feeds them. The refresh failed on 2026-08-30 and 2026-09-06; PR #1097 fixed the timeout that caused it, but no scheduled run has happened since, and the ordering gap is unchanged. Next scheduled run is 2026-09-14 — watch it before deciding how much this is worth. | M |

## Batch 4 — State assignment

Do IMP-184 first and alone: it is the only entry in the backlog that unblocks a large,
currently-invisible population.

| ID | What is wrong | Effort |
|----|---------------|--------|
| IMP-184 | Tier D is hardcoded off (`assign_team_states.py:1304 tier_d_ready = False`) and `tgs_events` has a table but zero writers — `scrape_tgs_event.py:392-414` fetches the payload and never upserts it. This is the only state path ~2,192 stateless TGS teams have, roughly 96% of the remaining blanks. They are on no state board today. | M |
| IMP-161 | `club_derived_state` (:873-903) has no shape check, so a club that is 2 CA / 2 TX proposes CA→TX for the CA teams and TX→CA for the TX teams, every sweep, forever. No 2/2 fixture exists in the tests. | M |
| IMP-162 | `apply_team_state` writes `state_code` but never the full-name `state` column, and `decide()` (:1174-1175) queues on any non-empty `state`. A stale full name shields a wrong code from being corrected. | M |
| IMP-185 | `affinity_wa_matcher.py:390` and `playmetrics_matcher.py:451` stamp a constant state on team creation with no `state_source`, on a schedule. Currently 0 of 729 Affinity clubs read out-of-state, so this is latent — but it is unprovenanced writes into a system whose whole design is provenance. | M |
| IMP-166 | `probe_log_row` writes `provider_team_id` (:1588) but `fetch_recent_probes` (:453-475) never selects it back, so a cached probe answer cannot be checked against the alias it was bought through. | M |
| IMP-150, 151, 152, 155, 157, 158 | Small hardening, all `S`, all latent. Worth one combined PR rather than six: blank-vs-null folding, `--team` on a deprecated id writing a false ledger row, three tables that never got the `REVOKE` their sibling got, two unpinned guards in `report_team`, `--limit` validated where the argv harness cannot reach it, `--workers` unbounded. | S each |

## Batch 5 — Guards that would let a regression ship green

Low urgency, high leverage — each of these is a place where CI is currently incapable of
failing. Worth doing before the next round of frontend work, not before batch 1-4.

IMP-120 (no `RankingsTable.test.tsx` at all, 4 unguarded `teamDisplayName` call sites),
IMP-084 (nothing pins `useTeamSearch.ts:63`'s select list — a column trim blanks every
subtitle silently), IMP-085 (`e2e/search.spec.ts:41-49` passes while only the loader is
showing), IMP-122 (five `*Preview.tsx` with zero tests; the smoke workflow checks HTTP
status only), IMP-118 (the mount/act harness is now copied five times, and
`ComparePanel.test.tsx:4` still imports `act` from a removed module).

## Batch 6 — Consolidation

Fifteen entries, each a single sitting, none urgent. Best used as filler between larger
pieces. Grouped by what they collapse:

- **Provider/queue helpers**: IMP-167 (7 copies of the GotSport provider lookup),
  IMP-171 (8 copies of a chunking helper under 4 names), IMP-129 (three copies of the
  scrape-log bulk writer), IMP-130 (eligibility predicate pasted into three SQL functions),
  IMP-126 (two byte-identical `unknown_` predicates).
- **Frontend**: IMP-079 (4 copies of `highlightMatch`, two different yellows),
  IMP-116 (`DeltaIndicator` still inside `InsightModal.tsx:404` plus 3 hand-rolled copies —
  this class already shipped inverted watchlist colours once), IMP-086, IMP-089, IMP-119,
  IMP-123.
- **GotSport**: IMP-177 (`EVENT_BASE` duplicated across two walkers that share no code and
  are being hand-synced — see the comment at `gotsport.py:1644`), IMP-181, IMP-142, IMP-144.

## Batch 7 — Low stakes, or waiting on something

Docs and cosmetics: IMP-103, IMP-109, IMP-125, IMP-102, IMP-124, IMP-197, IMP-198, IMP-196.
Dashboard-display-only billing: IMP-186, IMP-187, IMP-189, and IMP-188 (a ~$1.58 gap on a
~$50 line, smaller than the swing from choosing the lookback window — its own author
recommends deferring). Structural refactors with no live symptom: IMP-094, IMP-098,
IMP-105, IMP-108, IMP-110, IMP-115, IMP-137, IMP-148, IMP-159, IMP-170.

Seeding and event-roster work (IMP-174 to IMP-183) sits here until someone confirms the
roster walker still clears the WAF. IMP-138 stays parked — Modular11 is out of scope by
operator decision.

Already `deferred` with a trigger, needing no attention until it fires: IMP-113, IMP-179,
IMP-190, IMP-191.
