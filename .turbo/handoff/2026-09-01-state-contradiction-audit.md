# Handoff: the contradiction audit (PR2), reviewed but not committed

## Where to work

`C:/pitchrank-probe-ledger` — a git worktree on branch `state-contradiction-audit`, cut from
merged `origin/main`, currently `0 0` against it because **PR2 is not committed**.

Use absolute paths for every command: the Bash tool resets CWD to `C:\PitchRank` between calls.
**Never touch `C:/PitchRank`.** That is the shared main checkout, sitting on another session's
branch (`note-remaining-wa-leagues`, PR #1071) with their uncommitted files.

The worktree has no `.env`. Source credentials per command with
`set -a && . /c/PitchRank/.env && set +a`; do not copy the file in.

## The task

Implement `.turbo/plans/state-contradiction-audit.md`, a two-PR plan. Every free tier that
decides a team's state is learned from `teams.state_code`, the column being audited, so a club
whose teams are uniformly mislabelled agrees with itself and no tier disputes it. The plan
closes that hole using the one external signal available: the GotSport registration record.

## PR1 — shipped

The probe ledger (`team_state_probe_log`): every paid GotSport probe is recorded, including the
ones that change nothing. Previously only a probe that *moved* a state left a trace, so an
agreement was indistinguishable from never having asked, and a budgeted audit would re-probe the
same head of the list forever.

- Merged as **PR #1074**, commit `1bb6c8072` on `main`.
- Migration `20260831120000` applied to production by the operator through the Supabase SQL
  editor, then recorded in `supabase_migrations.schema_migrations` by hand (the MCP server is
  read-only and the CLI path is blocked by the firewalled direct-Postgres connection).
- Verified live: table present, RLS on, both policies, index present, `relacl` is `postgres` +
  `service_role` only (anon/authenticated revoked), and the security advisor does not name it.
- Two live single-team probes wrote 2 rows, both `agreed = true`.
- One Codex P1 on that PR was answered with a measurement and **no code change**
  (comment 5497721522): a fatal flush strands at most `max_workers` (~10) further paid calls,
  not thousands, because `Executor.map`'s generator cancels pending futures as the exception
  unwinds. Reproduced at 12-14 with a realistic per-call delay.

## PR2 — built, reviewed, NOT committed. This is the state to resume.

`--audit-contradictions` selects teams whose stored state contradicts a club-mate a GotSport
record already confirmed (`state_source = 'tier_a'`), probes those instead of the
disputed/stateless set, and writes **only decisions the provider answered**.

Live-measured against production 2026-09-01: **1,173 candidates** (1,210 raw, 37 Canadian
excluded), 2,123 anchored clubs, 622 anchored by 2+ and 588 by one. Two capped `--probe-limit 50`
runs had **zero overlap** in probed ids; the second reused the first's 38 answers for free and
decided 75 teams on 50 calls; **86.2%** of answered teams in the 2+-anchor bucket were genuinely
wrong, against 2.9% for a randomly chosen team.

### Working tree

Six files carry the change. `git status` shows `MM` on several — the apply round's edits are
**not re-staged**, so stage before committing:

    scripts/assign_team_states.py
    scripts/check_state_skill_assumptions.py
    tests/unit/test_assign_team_states.py
    .claude/skills/assigning-team-states/SKILL.md
    .claude/skills/assigning-team-states/references/evidence-tiers.md
    .claude/skills/assigning-team-states/references/failure-modes.md

`.turbo/improvements.md` is also modified (IMP-154, see below) and belongs in the same commit.

### Verified state

- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` — clean
- `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py -q` — **3075 passed**,
  12 skipped, 0 failed
- `python scripts/check_state_skill_assumptions.py` — every assertion holds, no drift
- **24 of 24 mutations caught.** The script is at
  `%TEMP%/claude/C--PitchRank/2112d646-.../scratchpad/verify_pr2_round2.py` if it survives;
  otherwise the mutation list is in the findings file below.

## Where this sits in the workflow

`/finalize` → `/polish-code` **iteration 1**. Steps 1-5 are done: stage, deterministic gate,
seven-way `/review-code`, `/evaluate-findings`, `/apply-findings`.

**Remaining, in order:**

1. `/smoke-test` (Step 6). No interactive surface — this is a CLI plus docs, and the probing
   modes cost money, so it falls to the Integration Test Path plus static checks. The PR1
   smoke plan is the model: `--help`, a credential-absent fail-closed run, an import/symbol
   check, and the suite. `--audit-contradictions --probe-limit 0` is free and worth including.
2. Step 7's convergence gate. **Expect it to recommend a second iteration.** Iteration 1 found
   three P1 defects in the *production code* plus one already shipping in the reporting layer —
   16 of 28 applies were in the change itself, not the scaffolding. That is a first round on new
   logic, not a converged one. The signal to stop is a round whose findings sit in the guards.
3. `/simplify-docs`, `/update-changelog` (a no-op — this repo has no `CHANGELOG.md`),
   `/self-improve`, then Ship It.

## What iteration 1 fixed

**Three P1s with one root cause.** `build_snapshot`'s `if only_team:` arm won over
`elif audit_contradictions:` while `audit_contradictions` stayed true downstream, so every audit
behaviour keyed on that flag misfired on the named-team path. Fixed structurally by deriving
`auditing = audit_contradictions and not only_team` and using it at six sites:

- **A1** `--team --audit-contradictions --execute` on a blocked probe auto-applied a Tier B
  correction and exited 0 — on exactly the uniformly-mislabelled club `--team` is documented
  for. The abort now fires immediately on that path, which has no cache to protect.
- **A2** `--probe-limit 0` still made a paid call on the `--team` path. The budget now binds
  there (recency deliberately does not: a named team is asked because someone wants it asked).
- **A3** a negative `--reprobe-after-days` put the cutoff in the *future*, so nothing counted as
  recent and the whole population was re-bought (~1,110 paid calls). Values below 1 are rejected.

Also: **B1** the answered total excluded cached answers (a live run printed "0 answered (87 from
earlier runs)"); **B2** the capped-run caveat now keys on a recorded `budget_applied` rather than
inferring it from the probe list; eight coverage guards including the one that bounds the audit's
entire spend (defaulting the anchor lookup would select **176,857** teams instead of 1,173);
prose corrections across four files; and two constants `TIER_A_SOURCE` / `MAPPED_OUTCOME` with
`state_source_for()`, so the writer and the two readers cannot drift apart silently.

Full findings: `%TEMP%/claude/C--PitchRank/2112d646-.../scratchpad/pr2-findings.md` and
`pr2-evaluated.md`.

## Decisions already made — do not re-ask

- **An operator's approved state is NOT exempt from an audit correction.** The provider record
  wins; that is the policy the module docstring states. R17 protects a *reverted* value and
  nothing protects an *approved* one, and the operator accepted that asymmetry.
- **Two pre-existing readers paging without `ORDER BY`** (`fetch_live_teams`,
  `fetch_revert_blocks`) — noted as IMP-154, deliberately not fixed here.
- **F2, rejecting `--team` with `--audit-contradictions` at the parser — skipped.** It reverses
  the plan's recorded "`--team` wins" decision, and the structural fix removed the untested
  clauses it objected to anyway.
- PR2's ship intent is **not yet decided**. For PR1 the operator chose commit-only, then later
  asked to push and open the PR.

## Cost discipline — this spends real money

A probing run costs paid ZenRows calls; a full audit is ~1,110. **Free modes only:**
`--no-tier-a`, `--audit-contradictions --probe-limit 0`, `--help`. **Never `--execute` without
asking.** Roughly 100 paid calls were spent on verification this session.

The MCP Supabase server is **read-only** — it rejects `INSERT` with "cannot execute INSERT in a
read-only transaction" and exposes no `apply_migration`. Read-only SQL through it is fine and is
the right way to verify a measured claim.

## Not done, deliberately

**No `--execute` has been run, so the audit has corrected nothing in production.** It has
*found* roughly a thousand wrong states across the two capped runs and written none of them.
Applying them is a separate decision for the operator, and the same caution that keeps
corrections out of the weekly job applies: a snapshot is applied from the file it was previewed
from, small batch first, verified against the database rather than the run's own output.

## Also from this session

Four backlog entries were added (all in `.turbo/improvements.md`, which is tracked):

- **IMP-151** a deprecated id passed to `--team` logs a false NULL stored state (2 teams today)
- **IMP-152** three sibling ledger tables still carry anon's default grants; only the probe log
  revokes them
- **IMP-153** anon retains DELETE and TRUNCATE on `public.user_profiles`
- **IMP-154** the `ORDER BY` paging item above

Two installed turbo skills were also edited with fixes learned here: `implement-plan` gained a
fetch step before it may report a plan absent (this session reported the plan missing when it
was one commit away on `origin/main`), and `note-improvement` gained the tracked-file case (the
backlog is tracked, so the note belongs in the current worktree, not the main tree).

## Next concrete action

Run `/smoke-test` for PR2 in `C:/pitchrank-probe-ledger`, using only the free modes
(`--help`, a credential-absent run, an import/symbol check, `--audit-contradictions
--probe-limit 0`, and the full suite). Then take `/polish-code` Step 7's convergence decision —
and expect to recommend a second iteration rather than stopping, because iteration 1's findings
landed in the production code rather than in the tests guarding it.
