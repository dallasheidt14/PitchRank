# Team State Assignment and Correction

**Status**: approved · **Date**: 2026-08-28
**Evidence**: `.turbo/reports/2026-08-28-state-code-landscape.md`

## Overview

`teams.state_code` drives PitchRank's state ranking boards. Today the column is
write-once in practice: all four state-writing steps of `update-missing-club-and-state.yml`
filter on `state_code IS NULL` in their *SELECT*, so nothing in the repo can correct a
wrong state. There is no `state_source`, no `state_confidence`, and no history — a
correction run today would have no rollback. Meanwhile the whole pipeline has been dead
since 2026-08-20, and several code paths manufacture wrong states every week.

This project makes state assignment evidence-driven, auditable and reversible. It adds a
skill plus a backing script that fills missing states and corrects wrong ones, deciding
each team from a tiered evidence model rather than a single heuristic; provenance columns
and an audit ledger; a hand-curated registry of clubs whose state cannot be computed; a
review queue with an approve/reject surface; and two upstream source fixes. It also
repairs the dead workflow.

Missing states are the smaller half of the problem: 3,845 of 211,404 rows (1.82%), of
which 3,761 are live and 3,697 are TGS. The larger half is the roughly 4,000 teams whose
stored state disagrees with their club. (Those two totals are whole-table figures; every
club-level number below counts only the 200,164 non-deprecated rows — see R30.)

**Operational bounds.** One operator (the project owner). The sweep runs weekly at most
and ad-hoc otherwise; there are no concurrent writers of this tool. Rigor tier:
business-critical for correctness of published rankings, but low-concurrency — so the
design invests in auditability and reversibility, not in locking or leases.

## Users

- **Operator** (project owner). Runs the sweep, curates the club registry, works the
  review queue, and reverts a bad batch. Deep domain knowledge of youth soccer clubs;
  wants to spend judgment only where evidence genuinely conflicts.
- **Ranking consumer** (site visitor). Never interacts with the tool; benefits when a
  team appears on the correct state board.

## Requirements

### Evidence and decisions

- **R1.** The system shall decide a team's state from the highest-priority evidence tier
  that fires, and shall record that tier as `state_source` with its confidence.
- **R2.** A team's state means **where its club is based** (home address), not where it
  plays. Travel-derived signals shall never override a club-derived or
  provider-derived state.
- **R3.** When a team has no `state_code` and any of Tiers A–D fires, the system shall
  fill it (a **fill**).
- **R4.** When a team has a `state_code` and any of Tiers A–D proposes a different one,
  the system shall raise a **correction**.
- **R5.** The system shall auto-apply a **fill** from Tiers A, B, C or D, and shall
  auto-apply a **correction** only from Tiers A or B. Every other outcome — including any
  correction proposed by Tier C or D — shall write a review-queue row and change nothing.
  Whether a decision is a fill or a correction is determined **solely** by whether
  `state_code` is NULL; `state_source` never affects that test.
- **R6.** Where a team belongs to a club marked `curate: True` in the registry, Tiers B,
  C and D shall queue rather than auto-apply, for both fills and corrections. **Tier A is
  exempt**: it is a per-team provider record, and the reason a club is curated — that
  club-level inference cannot pick a home state — does not apply to it.
- **R7.** If a team's stored `state_code` is a Canadian province, then no tier shall
  correct it. Canadian provinces are legitimate data — never flagged, never counted as
  malformed.
- **R8.** If a team's stored `state_code` is `DC` and a tier proposes a different state,
  then the system shall queue rather than auto-apply. Every sampled DC team's GotSport
  association reports `MD`, so Tier A would otherwise silently relabel the District.
- **R9.** Before the tier cascade resolves, the system shall compute the name-derived
  state and the club-derived state independently; if both exist and disagree, it shall
  queue the team and stop, whichever tier would otherwise have won.
- **R10.** If a GotSport `team_association` value is not present in the mapping table,
  then Tier A shall not fire for that team. Unlisted codes fail closed.
- **R11.** Where a club has a registry entry carrying a `home` state, that home **is** the
  club's state for every team in the club, replacing the computed meaningful-state test.
  The computed test applies only to clubs with no registry entry.

### Provenance and safety

- **R12.** When any path writes a `teams.state_code`, the system shall append exactly one
  `team_state_audit` row capturing the old and new values, the sources, the confidences,
  the action and the actor.
- **R13.** The ledger shall capture writes from **every** path, including INSERTs — the
  discovery path has created 66,380 teams, 31.4% of the table.
- **R14.** The system shall write `state_source`, `state_confidence` and
  `state_assigned_at` on every `teams` row it updates.
- **R15.** The operator shall be able to revert a batch by date and actor, restoring
  `state_code`, `state_source` and `state_confidence` to their prior values — including
  when the prior confidence was lower than the current one. Where the scope holds more
  than one audit row for a team, the revert shall apply the **oldest** `old_*` row for
  that team, returning it to its pre-batch state.
- **R16.** A revert shall not itself become a batch that a later date-scoped revert undoes.
- **R17.** Before auto-applying state X to team T, the system shall check the ledger for a
  row matching `(T, action = 'revert', old_state_code = X)`; if one exists it shall queue
  instead of auto-applying. Without this a revert survives only until the next sweep
  recomputes the same evidence.
  The key reads `old_state_code`, not `new_state_code`, because a revert row records the
  value being **restored** in `new_state_code` and the value being **undone** in
  `old_state_code` — so X, the value about to be re-applied, is the old one. Keying on
  `new_state_code` would never match, and would instead block re-applying the value the
  operator just restored. This orientation also covers a revert to NULL, where
  `new_state_code IS NULL` and the wrong key could match nothing at all. Note it is the
  mirror image of R24's queue key `(team_id_master, proposed_state_code)`, which reads the
  proposed value directly.
- **R18.** Every new table shall ship with RLS enabled and the repo's
  `<table>_deny_all` / `<table>_service_role_all` policy pair.
- **R19.** The backing script shall default to dry-run; writing shall require an explicit
  `--execute`.
- **R20.** The script shall support `--limit` so a small batch can be applied and
  verified before the rest.
- **R21.** The system shall support assigning a single team by id for ad-hoc operator use.
- **R22.** Every decision shall be computed against a single snapshot taken at the start of
  the dry run and persisted to the `--out` artifact. Each `--execute` — including a second
  one finishing a `--limit` batch — shall consume that same snapshot, passed back via
  `--snapshot <path>`, which `--execute` requires. Taking a fresh snapshot requires a fresh
  dry run.
  Each snapshot row shall record the `state_code` observed at snapshot time, and the write
  shall carry that pre-image as a predicate: a row whose current `state_code` no longer
  matches its pre-image is skipped and reported, never applied. This is not a concurrency
  guard against this tool — the bound rules that out — but against the other weekly
  `state_code` writers, which can turn a recorded Tier C or D *fill* into an unreviewed
  Tier C or D *correction* between the dry run and the apply.
- **R23.** The operator shall be able to approve or reject a review-queue row.
- **R24.** A review-queue proposal the operator rejected shall not be re-raised while the
  same state is being proposed for the same team.
- **R25.** After applying a correction, **reverting one, or approving one from the queue**,
  the system shall mirror `state_code` into `rankings_full` with an UPDATE so the team page
  and the state board agree immediately.

### Platform constraints

- **R26.** Any bulk database operation shall be driven from the caller in batches with a
  cursor. A single RPC gets **8 seconds** and cannot extend its own budget.
- **R27.** Tier D's per-event participant aggregation shall resolve merges through
  `team_merge_map` before grouping. 119,791 game rows sit on deprecated ids.
- **R28.** `.in_()` lists shall be batched to 100 ids or fewer; reads shall paginate at
  1000 rows.
- **R29.** The system shall never DELETE from `teams`.
- **R30.** The sweep shall consider only non-deprecated teams, and club aggregates shall
  count only non-deprecated members. Without the filter the sweep processes 11,240 extra
  rows and computes club aggregates over a different denominator. Every **club-level**
  figure in this document is computed that way; the Overview's table totals and R13's
  share of the table are deliberately whole-table figures, and R36's checker must measure
  each against the denominator its own sentence names.

### Pipeline repair and source fixes

- **R31.** `update-missing-club-and-state.yml` shall run to completion on its weekly cron
  without requiring IPv6 egress.
- **R32.** Every step of that workflow shall fail loudly; a crash shall not exit 0.
- **R33.** The workflow shall not write a `state_code` inferred from opponents.
- **R34.** `scrape_tgs_event.py` shall read the event payload's actual key names.
- **R35.** The unknown-opponent discovery path shall not persist an opponent's state as
  the discovered team's own state.

### Skill

- **R36.** The skill shall carry an executable checker that **asserts** the code
  behaviours it claims and **measures** the counts it quotes, warning on drift rather
  than failing.

## Design

### Evidence model

`Fill` means the team had no `state_code`; `correct` means it had one and the tier
disagrees. That test is on `state_code` alone — `state_source` never enters it (R5).

| Tier | Signal | Confidence | Fill | Correct |
|------|--------|-----------|------|---------|
| **A** | GotSport `team_association`; SincSports state-scoped crawl; Affinity RCL | 0.95 | auto-apply | auto-apply |
| **B** | The club's state — from the registry's `home` if it has an entry, else exactly one computed meaningful state | 0.90 | auto-apply | auto-apply |
| **C** | `team_name` names exactly one US state | 0.85 | auto-apply | **queue** |
| **D** | TGS event participant-modal state, gated | 0.85 | auto-apply | **queue** |

**Precedence of the exceptions**, stated pairwise rather than as a single ordering,
because the intents genuinely differ:

| Rule | Effect | Outranks |
|---|---|---|
| **R7** stored Canadian province | no tier corrects it | everything, including R9 |
| **R9** name-derived and club-derived states disagree | queue, cascade not run | the whole cascade, and R6 and R8 |
| **R8** stored `DC` | queue | Tier A's R6 exemption |
| **R6** team in a `curate: True` club | Tiers B/C/D queue; Tier A auto-applies | applies only when none of R7, R9, R8 fired |
| **R10** `team_association` unmapped | Tier A does not fire | — |
| **R17** ledger holds `(team, action='revert', old_state_code = proposed)` | queue | any auto-apply |
| Event absent from `tgs_events` | Tier D's gate not evaluable; does not fire | — |

This table and R3–R11 state the same rule; they must be changed together.

**Tier B's club state.** If the club has a registry entry, its `home` is the club's state —
full stop (R11). Only clubs with no registry entry fall through to the computed test:
a **meaningful state** is one holding ≥2 of the club's teams *and* ≥5% of its known-state
teams, **counting the club's other teams and excluding the team being decided**, and Tier B
fires only when exactly one state qualifies. The exclusion is load-bearing: a wrongly-coded
team otherwise contributes to the minority bucket it created, and with a single clubmate
sharing the error that bucket reaches `count >= 2`, silencing Tier B and preserving the
error — the correlated-pollution shape described for TCSL below.

**Why the registry's `home` has to be authoritative.** The computed test alone cannot
reach the contamination it was meant to fix. Verified against production with the rule
above: `arizona arsenal soccer club` is AZ 145 / TX 10 (6.41%), `city sc` CA 237 / AZ 15
(5.79%), `soccer chance academy` OR 105 / WA 7 (6.14%), `steel city fc` PA 139 / OH 9
(5.84%). Every minority bucket clears both thresholds, so each club has two meaningful
states and Tier B stays silent — for precisely the four cases the operator confirmed by
hand. R11 is what closes that gap.

**Snapshot (R22).** Club aggregates and every decision are computed once, at the start of
the dry run, and persisted to the `--out` artifact; each `--execute` consumes that
snapshot. Without this the run interferes with itself: Tier C fills auto-apply, and a fill
written early changes the clubmate distribution a later team's Tier B reads, so a minority
bucket can cross `count >= 2` mid-run and silence Tier B for the rest of the club. It also
closes the `--limit` gap — a second `--execute` finishing a batch would otherwise
recompute against a database the first one mutated, producing exactly the drift the
snapshot exists to prevent, with no second dry run required.

For clubs with no registry entry, 6,327 are cleanly single-state and settle **141,023
teams** — 135,910 already agreeing, 1,129 NULL and fillable, 3,984 disagreements to correct.

#### Tier A — `team_association`, validated

An **association code, not a postal code**. `CAN` = California North, not Canada;
`CND` = Canada. Over 231 live probes, 67 distinct values:

- **Identity (45)** — AK AL AR AZ CO CT DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN
  MO MS NC ND NE NH NJ NM NV OH OK OR RI SC SD TN UT VA VT WA WI WV WY.
- **Split-state (8)** — `CAN`/`CAS`→CA, `NYE`/`NYW`→NY, `PAE`/`PAW`→PA, `TXN`/`TXS`→TX.
  Clean in all 37 observations. **Bare CA, NY, PA, TX are never emitted.**
- **Canadian provinces (7)** — AB BC MB NB NS ON QC. Not in the mapping table, so they
  never fire Tier A (R10). Distinct from R7, which protects a *stored* province.
- **Non-US bodies** — BRA CRC GER NED POL RSA, and `OTH`. Also unmapped (R10).

The 45 identity codes plus the four split states cover 49 of 50 US states; **Montana was
never observed**. Per R10 an unlisted code does not fire Tier A, and the R36 checker
reports newly-seen codes so the table is extended deliberately rather than by inference.

The mapping lives in **`src/utils/team_association_map.py`** — one module, one owner,
created in PR2 (its first consumer) and imported by PR4's Tier A.

**Accuracy: 91.3% raw (168/184), 96.2–98.4% adjudicated.** Each of the 16 disagreements
was judged against independent evidence — clubmate distribution and the API's own
`city_state_country`, neither being the audited column. **9 are cases where the
association is right and the stored value is wrong**; 3 are genuine association errors
(cause: the association is a *registration* body, not a location); 4 undetermined. Those
3 are why R17 exists: an operator who reverts one must not have it re-applied next week.

One of the 9 is `pid 615315`, stored TX, association AZ: **Arizona Arsenal SC**,
`city_state_country = 'AZ, US'`, clubmates AZ:157 / TX:9 — the same club the operator
confirmed by hand, reached independently.

Coverage: 97.8% of reachable teams carry the field, and all 25,648 teams the discovery
path created in Aug 2026 have a GotSport provider id (99.95% reachable). It does **not**
help the NULL backlog — only 7 of 3,761 NULL-state teams have a GotSport alias — and
provider ids ≥ 3,000,000 (org_event space) 404, leaving 4,192 residual `unknown_<pid>`
teams out of reach.

#### Tier D — gate, dependency, and maintenance

All three conditions required, because 256 of 557 TGS events are *league* rows whose
`stateCode` is the sanctioning office, not a venue (ECNL RL → Henrico VA;
STXCL → Tomball TX):

1. the event is tournament-type (`eventTypeID == 1`; `2` is league),
2. ≥10 participants with a known state,
3. ≥90% of them from one state.

Gated, this reaches ~96% over 1,317 stateless teams. Ungated it is 73%.

**Condition 1 cannot be evaluated from the database today.** `eventTypeID` appears
nowhere in the repo, there is no TGS event table, and `games.event_name` — the only
persisted event metadata — holds `'Event <id>'` for 91% of TGS games. Conditions 2 and 3
are computable from `games` alone; condition 1 is not.

So Tier D depends on `tgs_events`. Event ids are recoverable retroactively: **verified in
production, all 168,782 TGS game rows carry `source_url`, yielding 557 distinct event
ids** — so no re-scrape is needed to enumerate them.

`tgs_events` is populated twice over: PR4 backfills the 557 known ids once, **and** wires
`scrape_tgs_event.py` to upsert the table on every event it scrapes thereafter. The second
half is not optional — `tgs-event-scrape-import.yml` runs weekly over a rolling id range,
so new event ids keep arriving in `games`, and a backfill-only table would leave Tier D
progressively blind. **An event absent from `tgs_events` makes Tier D's gate
not-evaluable: the tier does not fire, and the run report counts such events**, so a blind
gate is visible rather than silently negative.

Once populated, the participant-modal state — the modal `state_code` of an event's
known-state participants — scores 96.1%, covers 1,555 teams, and agrees with the API's own
`stateCode` 104/104 on gated tournament events. The stored API value is therefore a
**cross-check**, and the per-event decision runs against `games` + `tgs_events` without
further API calls. That aggregation is a per-team aggregate over `games` and must resolve
merges first (R27).

#### Rejected signals

- **`teams.league`** — ECNL_RL spans 44 states, GA 44, MLS_NEXT_AD 42. Not geographic.
- **`teams.state`** (full name) — 52.9% filled; only 14 teams have it without a
  `state_code`. Not a source. It *is* the `txt` discriminator below.
- **Opponent dominance** — under R2 it measures travel, not club home. Its pollution is
  *correlated*: in the TCSL cluster the mislabelled teams play each other, so "opponents
  are 96% IL" is self-confirming. Rejected as a tier, and switched off in the pipeline
  (R33).
- **Venue gazetteer and `games.competition`** — deferred. See Deferred below.

#### The `txt` discriminator

Four writers set the full-name `state` column alongside `state_code`:
`match_state_from_club.py:669`, `backfill_state_from_opponents.py:290`,
`extract_and_import_tgs_teams.py:180-184` (applied at `:212`), and
`frontend/app/api/create-team/route.ts:83-84`. Every other writer sets `state_code` alone.

So **`txt == 0` is hard evidence a state was derived or guessed** — no enumerated writer
touched the row. The converse is weaker than it looks: `txt > 0` means a provider payload
*or* one of two backfills *or* a TGS import *or* an unvalidated admin form, the last of
which writes a two-letter code into the full-name column. Treat `txt > 0` as "not
obviously guessed", never as corroboration.

This is the test that separates a real multi-state club from contamination, and it is what
the operator applied when setting each registry `home` — so its enumeration is an R36
assertion.

### Curated club registry

`src/utils/club_state_registry.py` — a hand-curated dict literal. The repo has zero
precedent for YAML/JSON/CSV lookup tables and consistent precedent for curated dicts in
`.py`, so a Python module, reviewable by PR.

Entries carry `teams`, `known`, per-state `(count, pct, txt)`, a `label`
(`MULTI_STATE_BRAND` / `LEAGUE_BUCKET` / `NAME_COLLISION` / `PLACEHOLDER`), a `home`, and
`curate: bool`. **Both fields are load-bearing and independent**: `home` feeds Tier B via
R11 whenever it is set; `curate` decides whether Tiers B/C/D may auto-apply (R6).

**69 entries, of which 24 are curated.** All 69 clubs with ≥2 meaningful states and ≥100
teams get an entry, because the computed test cannot settle any of them. 24 need human
judgment and carry `curate: True` with no `home`. The other 45 are contamination — the
minority state is `txt0` and the minority team names are geographically identical to the
majority — so they carry `curate: False` plus a `home`, and R11 makes Tier B apply that
home to every team in the club:

- `arizona arsenal soccer club` → AZ. The TX-coded teams are named *"AZ Arsenal 2017 Flagstaff"*.
- `city sc` → CA. All 15 AZ teams are named *"Carlsbad …"*, a California program.
- `soccer chance academy` → OR. The WA bucket holds *"SCA N1 G2011/12 White (OR)"*.
- `fc delco` → PA. *"Black Conshy"* (Conshohocken PA) and *"Black Dtown"* (Doylestown PA)
  sit in the NY and NJ buckets.
- `steel city fc` → PA. All 9 OH teams are *"Steel City FC East"*, the Pittsburgh club's
  own branch.

Marking those 45 `curate: True` instead would push ~45,000 teams into the review queue to
defend against a problem R11 settles with a single stored value.

**Operator validation (2026-08-28).** Those examples were put to the operator
independently of the analysis; all four home states were confirmed by hand —
`arizona arsenal soccer club`→AZ, `city sc`→CA, `soccer chance academy`→OR,
`steel city fc`→PA. 4 of 4 with the `txt0` discriminator. This is the **only external
ground truth this problem has**; every other accuracy figure is measured against the
audited column. Treat it as weak positive evidence, not measured precision, and carry the
four as fixture cases (R36).

**The 24 curated clubs**, in full — the implementer enumerates the module's `curate: True`
entries rather than grepping, and the count must come out at 24:

`no club selection` (placeholder), `st. louis scott gallagher`, `fc stars`,
`kings hammer soccer club`, `missouri rush`, `eastside fc` (collision), `ayso united`,
`cincinnati united soccer club`, `strikers fc` (three-way collision),
`columbia premier soccer club`, `philadelphia union`, `lobos rush`, `elite fc`
(collision), `carolina elite soccer academy`, `kc legends`,
`alliance youth soccer league` (league bucket), `tri-city united`, `seacoast united`,
`mysa independent teams`, `coastal rush`, `sporting city soccer club`, `dasc`,
`wichita regional soccer association`, `wsa`.

**The key must not be `club_normalizer` output.** `normalize_club_name` collapses 9,852
club keys to 8,642 and fails both ways:

- **Over-merges** — it deletes parentheticals, often the only state disambiguator.
  `fc stars` (MA, 343) + `fc stars (il)` (IL, 60, a *different* club) both become `stars`.
  `elite fc (oh)`/`(ut)`/`(nv)` all become `elite`.
- **Under-merges** — branch suffixes survive: `legends fc - san diego`,
  `cedar stars academy - monmouth`, `ayso united - las vegas`.
- **Has a live bug** — `_remove_punctuation` deletes rather than replacing with space, so
  `liverpool fc-ia michigan` → `liverpool fcia michigan`.

The registry keys on raw `lower(btrim(club_name))` and lists sibling keys per entry.
`CITY_ABBREVIATIONS` must not be used for state inference: it expands `sd` → `san diego`,
mangling `ignite soccer club(sd)` where `sd` is South Dakota.

### Data model

```
ALTER TABLE teams
  ADD COLUMN IF NOT EXISTS state_source      text,
  ADD COLUMN IF NOT EXISTS state_confidence  numeric(3,2),
  ADD COLUMN IF NOT EXISTS state_assigned_at timestamptz;
```

These satisfy R14 and are the only thing that can sit in the `WHERE` clause of the ~22
currently-unguarded `state_code` writes.

`team_state_audit` — `team_id_master`, `action`, `old_state_code`, `new_state_code`,
`old_source`, `new_source`, `old_confidence`, `new_confidence`, `applied_at`,
`applied_by`, `reason`. **`old_confidence` is required by R15**, which names confidence
restoration as its hard case. A revert restores `state_code`, `state_source` and
`state_confidence` from the `old_*` columns and stamps `state_assigned_at = now()`. The
ledger is also read by R17 (a revert row blocks re-applying the same value).

`team_state_review_queue` — `id`, `team_id_master`, `current_state_code`,
`proposed_state_code`, `tier`, `confidence`, `reason`, `status`, `reviewed_by`,
`reviewed_at`, `created_at`. It borrows `team_match_review_queue`'s *shape* (a `status`
guarded by approve/reject RPCs, a Streamlit panel) but **none of its columns**, which are
provider-alias specific, and explicitly **not** its
`CHECK (confidence_score >= 0.75 AND confidence_score < 0.90)` — that constraint would
reject both confidences this design queues, Tier B at 0.90 under R6 and Tier A at 0.95
under R8. `proposed_state_code` is required by R24's suppression key.

`tgs_events` — `event_id` (PK), `name`, `event_type_id`, `state_code`, `city`,
`fetched_at`. 557 rows at backfill, growing as PR4's scraper upsert runs weekly.

**The trigger is the sole ledger writer.** It is the only mechanism that can catch all
~22 write paths, including the discovery path's INSERTs (R13). The write function below
touches `teams` only; it does **not** insert its own audit row.

**How the trigger gets its actor and action.** Not from a session GUC set by an earlier
call — that does not work here, and was verified twice against this project's database:
`set_config('pitchrank.probe', …, false)` on backend pid 3262723, then
`current_setting(…)` returned NULL on pid 3262724 on the very next request. PostgREST
pools connections, so a value set in a prior request is invisible to the write, and where
the pool does hand back the same backend the value lingers and mis-stamps unrelated later
writes.

Instead, every tool write goes through a plpgsql function taking `p_actor` and `p_action`:

```
PERFORM set_config('pitchrank.actor',  p_actor,  true);   -- true = TRANSACTION-local
PERFORM set_config('pitchrank.action', p_action, true);
UPDATE teams SET ... ;                                     -- same transaction
```

The trigger reads both with `current_setting(..., true)` and sees them because they are
set in the same transaction as the UPDATE. **`approve_team_state` and the revert function
both write through this same function** — with `p_action = 'approve'` (actor from the
approver argument) and `p_action = 'revert'` respectively. That matters because the
precedent RPC `approve_team_match`
(`supabase/migrations/20240201000003_add_match_review_queue.sql:21-69`) does not merely
flip a status — it applies the change and then marks the row approved, so an approval is a
`teams` write like any other. Writes from any other path — discovery INSERTs, the scrape
drainer, the surviving workflow steps — have no GUC set and fall back to the database role
name with `action = 'external'`, which is what R13 wants.

**Two triggers, not one.** PostgreSQL rejects
`CREATE TRIGGER … AFTER INSERT OR UPDATE … WHEN (OLD.…)` at creation — an INSERT trigger's
WHEN condition cannot reference OLD — so PR3 ships:

- `AFTER UPDATE … WHEN (OLD.state_code IS DISTINCT FROM NEW.state_code)`
- `AFTER INSERT … WHEN (NEW.state_code IS NOT NULL)`

both calling the same trigger function. The WHEN clauses are not optional: unconditional,
the trigger fires on every `teams` write, and the busiest by far is `last_scraped_at` —
roughly 3,840/day from `src/scrapers/base.py::_log_team_scrape` and
`process_missing_games.py::_flush_scrape_log`. Moving the test into the function body is
not equivalent, because it reintroduces a per-row function call on that hot path. No
migration in `supabase/migrations/` creates an INSERT-OR-UPDATE row trigger with a WHEN
clause, and `teams` currently carries only `update_teams_updated_at` (BEFORE UPDATE, no
WHEN), so there is no precedent to copy.

**RLS (R18)** on `team_state_audit`, `tgs_events` and `team_state_review_queue`, with the
`<table>_deny_all` / `<table>_service_role_all` pair from
`supabase/migrations/20240215000000_add_row_level_security.sql`. `pg_default_acl` grants
`arwdDxtm` to `anon` on every new public relation here — exactly how `team_merge_audit`
and `team_link_audit` reached the security advisory. Service-role writes are unaffected.

**Revert is a distinct code path** (R15). A confidence guard using strict `<` blocks both
re-runs (after relabelling a club, a same-confidence rerun matches zero rows and reports
"0 updated") and reverts (restoring a lower-confidence value is what the guard forbids).
Revert rows carry `action = 'revert'` and are excluded from later date-scoped reverts
(R16); where a scope holds several rows for one team, the oldest `old_*` wins (R15).

**Batching is not optional (R26).** `pg_db_role_setting` carries `statement_timeout=8s`
for `authenticator` and has no `service_role` entry; PostgREST logs in as `authenticator`
then `SET ROLE service_role`, which does not re-apply per-role settings. `SET LOCAL
statement_timeout` inside a function body is inert — the timer armed for the outer
`SELECT fn(...)` is untouched. So every bulk operation, including revert and the Tier D
aggregation, takes `(p_after, p_batch_size)` and returns a cursor; the script loops. Model:
`scripts/refresh_team_scrape_activity.py` and its migration (2,000 rows/call, 289 ms).
Do **not** copy `backfill_total_game_stats` — it carries `SET LOCAL statement_timeout =
'300s'` and is cancelled on every production run.

Team-id reads throughout — the club snapshot, the Tier D participant aggregation, and the
`rankings_full` mirror — batch `.in_()` at 100 ids and paginate at 1000 rows (R28), and
consider only non-deprecated teams (R30).

### Review queue

Do **not** reuse `pending_match_reviews` (a dead VIEW, zero consumers) or
`user_corrections` (a dead table, 0 rows, no code references).

**The queue has a consumer (R23).** PR4 ships an `approve_team_state` /
`reject_team_state` RPC pair, both guarded on `status = 'pending'`, and a `dashboard.py`
panel mirroring the existing match-review surface at `dashboard.py:361`. Without this the
queue is write-only, and R24's suppression would depend on a `rejected` status nothing
could set.

R24's suppression keys on **`(team_id_master, proposed_state_code)`**, implemented as a
read-before-insert following `alias_writer.py` — PostgREST cannot reach a partial unique
index via `on_conflict`. Keying on `team_id_master` alone would permanently silence a team
even after the operator curates its club or Tier A later fires with a different state.

Copy **two** of that function's branches, not one. `skipped_rejected`
(`alias_writer.py:412`) is what R24 names, but `deduped_pending` (`:393`) is what prevents
duplicate *open* rows — it updates the matching pending row in place. Without it every
weekly sweep inserts a fresh pending row for the same key, because a queued decision
changes nothing and therefore recomputes identically. The queue carries no unique
constraint to catch that. (The function's docstring at `:283-284` lists all four outcomes;
`skipped_already_approved` is at `:419`.)

**An R9 row is the one queue row with no winning tier**, since the veto fires before the
cascade resolves. It records the **club-derived** state as `proposed_state_code` — that is
what the cascade would have applied via Tier B — with `tier = 'R9'` and Tier B's `0.90`
confidence, and names the conflicting name-derived state in `reason`. Leaving
`proposed_state_code` NULL is not an option: the read-before-insert would never match
(NULL ≠ NULL), so a rejected R9 row would re-queue on every sweep and R24 would be
silently defeated for the entire R9 population.

### `rankings_full` coupling

The boards are split: `get_state_rankings`, `get_state_rankings_count` and
`get_team_state_rank` read `rankings_full.state_code` (stale until Monday 12:30 UTC),
while `rankings_view` and `state_rankings_view` read `teams.state_code` live. A correction
therefore makes the team page and the state board disagree for up to a week; live drift is
1,930 rows. R25's mirror is an `UPDATE`, never an upsert — Monday's
`on_conflict="team_id"` upsert re-derives it idempotently.

It runs on **all three** write paths, not just the sweep's apply:

- **apply** — a batched Python `.in_()` loop over the run's corrections.
- **revert** — same loop; without it a revert leaves the board showing the state the
  operator just rejected.
- **approve** — `approve_team_state` applies the change before flipping the status (the
  `approve_team_match` precedent does exactly that), so an approval is a `teams` write like
  any other. Because it is a Postgres RPC rather than Python, its mirror is a single-row
  `UPDATE` inside the same function; otherwise an operator approving a queued correction
  would see the team page change and the state board stay stale until Monday 12:30 UTC.

### Sources of bad data

Ranked by damage, from the ~22 paths that write `state_code`:

1. **Unknown-opponent chain.** `auto_match_unknown_opponents.py:192` fills a missing state
   with `top_known_team_state` — the state of the team it played — which flows to
   `discover_teams_from_opponents.py:291`. Runs weekly. Fixed in PR2.
2. **The pipeline's own Step 6**, `backfill_state_from_opponents.py`: opponent dominance,
   the signal rejected under R2. Switched off in PR1 (R33).
3. **`enhanced_pipeline.py:536` → `game_matcher.py:569,579`** — game import calls
   `_match_team()` without `state_code`, discarding the correct per-team state the
   PlayMetrics/SincSports scrapers already put in the CSV. *(Deferred.)*
4. **`tgs_matcher.py`, `modular11_matcher.py`** — omit `state_code` entirely (both carry
   TODOs). TGS being the tournament provider is why 3,697 of 3,845 NULLs are TGS.

**Affinity WA is out of scope and correct as-is.** `scrape_affinity_wa_tournament.py` is
named "tournament" but its `TOURNAMENTS` list holds exactly one entry — the 25-26 Regional
Club League. Every team it creates is genuinely a WA league team.

## MVP Scope

Four PRs. **PR1 ships first and alone**, before the 2026-08-31 cron.

### PR1 — Repair the dead workflow (R31, R32, R33)

Root cause: `db.pfkrhmprwxtghtpinrot.supabase.co` is AAAA-only; GitHub runners have no
IPv6 egress, so `psycopg2.connect(DATABASE_URL)` raises `Network is unreachable`. No step
carries `continue-on-error`, so Steps 1–6 never run either.

Four edits, all required:

1. Rewrite `backfill_state_from_team_name.py`'s DB layer from psycopg2 to PostgREST
   (~90 lines), mirroring `backfill_state_from_opponents.py:75-170,275-291`, which already
   supplies every helper.
2. Drop `DATABASE_URL` (workflow `env:`, line 66) and its now-false comment at line 65
   ("Step 0 connects directly rather than through PostgREST; the rest use Supabase"), and
   `psycopg2-binary` from the install step — **and delete Step 0's inline guard at lines
   133-136**,
   `if [ -z "$DATABASE_URL" ]; then echo "::error::Step 0 needs DATABASE_URL…"; exit 1; fi`.
   That guard lives inside the Step 0 `run:` block, independent of the `env:` entry.
   Removing the variable while leaving the guard makes Step 0 exit 1 on the next cron and,
   with no `continue-on-error`, Steps 1–6 still never run — the exact failure this PR
   exists to repair, with a different error message.
3. Add `set -o pipefail` to Steps 1–6 (`run: |` at lines 155, 177, 198, 219, 253, 274). It
   currently appears once, at line 127.
4. **Disable Step 6** (`backfill_state_from_opponents.py`). Its signal is rejected under
   R2, and every state it writes is one the tool would later have to correct. Verified
   safe: Step 6 is the last substantive step, with only the always-run artifact upload and
   summary after it.

The PostgREST rewrite was chosen over repointing `DATABASE_URL` at the Supavisor pooler
(`aws-1-us-west-1.pooler.supabase.com`, IPv4, tenant `postgres.pfkrhmprwxtghtpinrot`,
located by handshake probe) because **that fix is untestable from this checkout** — no
Postgres password exists in any local env file, so its only test is another weekly cycle,
and the pipeline has already missed one. The PostgREST version runs today via `--dry-run`.
Trade-off accepted: apply-atomicity is lost; the dry-run guarantee survives, being control
flow rather than the transaction.

Steps 0, 4 and 5 stay — verified to scope their SELECTs to NULL/empty `state_code`, so
they only fill. They are retired in PR4, when the tool supersedes them; leaving them
beyond that would be the dual computation path `.claude/rules/ranking-changes.md` warns
against.

### PR2 — Source fixes (R34, R35)

`scrape_tgs_event.py:735` reads `event_details.get("eventName")`, but the payload key is
`name` — so 153,815 of 168,782 TGS games (91%) store `event_name = 'Event <id>'`. Read
`name`. This PR fixes the key bug only; event state has no destination until `tgs_events`
exists in PR3.

Create **`src/utils/team_association_map.py`** — the 45 identity codes, the 8 split-state
codes, the unmapped Canadian and non-US bodies, and a fail-closed lookup. PR2 is its first
consumer; PR4's Tier A imports the same module.

`discover_teams_from_opponents.py:183` — stop persisting `unknown_state_used`; derive
state from `team_association` through that module, leaving NULL when it returns nothing.
**`auto_match_unknown_opponents.py:191-192` must not be touched** — `fetch_candidates` at
`:242-243` uses `profile.state_code` as a hard `.eq()` filter; removing it widens the pool
from ~165 to ~5,719 against a 160-row cap.

**The opponent guess is not a fallback — it is the only path.** The live payload's keys are
exactly `id`, `name`, `club_name`, `city_state_country`, `website_url`, `login_url`,
`primary_coach_name`, `coach_names`, `primary_manager_name`, `manager_names`,
`team_logo_url_full`, `image`, `team_association`, `display_gender`, `display_age_group`.
`export_unknown_opponents.py:132-137` and `discover_teams_from_opponents.py:142-148` read
`full_name`, `state`, `age`, `gender` — **none of which exist**. So `unknown_state` is
always `''` and both `or`-fallbacks are inert. Fixing the four key names is part of this PR.

`team_association` is read at `backfill_unknown_team_names.py:173` into an `"association"`
key **no caller ever reads**. `city_state_country` is likewise present and unused; capture
it in the same pass as a second locality signal.

### PR3 — Migration (R12–R18, R26)

Provenance columns on `teams`; `team_state_audit` including `old_confidence`;
`tgs_events`; `team_state_review_queue` with its own column list and no borrowed CHECK;
the two triggers and their shared trigger function; the write function taking
`p_actor`/`p_action`; the cursor-batched revert function; and RLS with the standard policy
pair on all three new tables. No behaviour change.

### PR4 — The skill (R1–R11, R19–R25, R27–R30, R36)

`.claude/skills/assigning-team-states/` mirroring `merging-duplicate-teams`: four-line
frontmatter (`name` + quoted `description`, no `allowed-tools`), H1, two framing
paragraphs, a `Copy this checklist and check off items as you complete them:` line then a
fenced `Task Progress:` block mapping 1:1 to `## Step N: <imperative>` headings, and
`references/*.md` each opening `# Title` then `## Contents`. CI asserts the declared
`name` equals the directory (`tests/unit/test_claude_agent_frontmatter.py:72`).

Write gate, in order: **mandatory dry run → evidence as text → `AskUserQuestion` →
`--execute --snapshot <path>` with a `--limit` escape hatch → verify against the database,
not the script's own report.** The dry run writes the decision snapshot to `--out`; every
`--execute` reads it back via `--snapshot` and refuses to run without one (R22). Rows whose
`state_code` has moved since the snapshot are skipped and reported rather than applied.
Revert documented as one paragraph in the apply step naming the script,
its two scoping keys (date *and* actor), the actor string the apply path stamps, and the
silent-no-op trap.

`scripts/assign_team_states.py` — `--dry-run` (default), `--execute`, `--snapshot <path>`
(required by `--execute`), `--limit`, `--team <uuid>`, `--out`.

`src/utils/club_state_registry.py` — 69 entries, 24 of them `curate: True`.

`approve_team_state` / `reject_team_state` RPCs plus a `dashboard.py` review panel (R23).

The `tgs_events` one-off backfill over ids recovered from `games.source_url`, **and** the
`scrape_tgs_event.py` upsert that keeps it current.

Retire the state-writing Steps 0, 4 and 5 from `update-missing-club-and-state.yml`;
Step 6 is already off from PR1.

`scripts/check_state_skill_assumptions.py` following `check_merge_skill_assumptions.py`
(397 lines): a docstring separating **ASSERTIONS** (code behaviours — these fail the run)
from **MEASUREMENTS** (row counts — these never fail; they print current values and warn
past `DRIFT_TOLERANCE = 0.20`), a `RECORDED` dict with `RECORDED_ON`, and the rule that
*a failure means the skill is now wrong, not the codebase*. Asserted behaviours include the
four-writer `txt` enumeration, the four operator-confirmed registry cases, the 24-entry
`curate: True` count, and the set of observed `team_association` codes.

### Deferred

- **Tier E — venue gazetteer and `games.competition`.** A learned map over 6,421 venues
  and 1,053 competitions derived from ~1M game rows. By its own definition it could only
  annotate a queue row the operator is already reading beside the club name, team name and
  state — the largest computation in the spec serving its weakest consumer. Revisit if the
  queue proves short on evidence.
- **TCSL Minnesota mislabel.** Teams named `TCSL *` (Twin Cities Soccer League, MN) split
  175 MN / 157 IL / 28 IA / 3 ND / 1 SD, with the *same* Minnesota clubs on both sides
  (Bloomington United, Boreal FC, Edina SC, EPSC, St. Croix, St. Paul Blackhawks). This
  one bug puts 7 of the 69 clubs on the registry.
- `enhanced_pipeline.py` dropping per-team CSV state before matching.
- `frontend/app/api/create-team/route.ts:83-84` writes a 2-letter code into `state`, the
  full-name column, unvalidated.
- Merges never reconcile `state_code`; 16,070 `team_merge_audit` snapshots hold a prior
  value and are a recovery source.
- Six scripts duplicate the state dictionary outside `src/utils/us_states.py` (that
  module's own docstring says four — it is stale).
- RLS is disabled on 11 existing tables (`game_history`, `team_trajectory`,
  `team_momentum`, `rankings_full`, `ranking_history`, `team_link_audit`,
  `team_merge_map`, `team_merge_audit`, `scheduled_games`, `announcements`,
  `team_social_profiles`). Enabling RLS without policies breaks reads, so this needs its
  own change.
