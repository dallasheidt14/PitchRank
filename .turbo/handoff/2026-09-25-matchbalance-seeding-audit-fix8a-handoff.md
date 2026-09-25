# Handoff: MatchBalance seeding audit, fix 8a in progress, review blocked on rate limit

## Why this handoff exists

The session working this (Claude Code) hit the account's Opus rate/spend limit mid-review:
6 of 7 `/review-code` subagents for fix 8a failed with HTTP 429 ("You've hit your monthly
spend limit" / weekly limit resets 2026-09-30 05:00 America/Phoenix). Only the security
reviewer completed. The user asked for a handoff so Codex (or a fresh Claude session once
the limit resets) can finish the remaining steps of the seeding audit.

Read `.turbo/handoff/2026-09-23-matchbalance-seeding-audit-apply.md` first — it is the
original audit handoff and still describes the audit artifacts, finding-ID scheme, and the
recommended fix order. This file only covers what changed since then.

## Fix order and what's done

The audit's "Recommended first fixes" order (see the 2026-09-23 handoff), followed one PR at
a time, each on its own branch/worktree from `origin/main`, with `python scripts/pr_wait.py
--no-merge` run after opening each PR and merge left to the owner's explicit "merge"/"go":

1. C1+K5 — **merged**, PR #1211
2. C4 — **merged**, PR #1212
3. S2+S3 — **merged**, PR #1214
4. C6+C7+C8+C22 — **merged**, PR #1216
5. S1 — **merged**, PR #1217
6. C5+C10+C11+K4 (shared cohort/gender label reader) — **merged**, PR #1220
7. C2+C3 (Seeding rebuild keeps notes; interrupted-build recovery) — **merged**, PR #1221.
   Codex's one review finding (recovery keyed by run name, so renaming mid-build hides the
   build under the old name) was logged, not fixed: **IMP-277** in `.turbo/improvements.md`.
8. **K1+O1 — split into two PRs, words first (owner's choice 2026-09-25):**
   - **8a (this one, in progress):** every word describing the Seeding sheet — operator
     guide, old spec, two runtime error/docstring strings, two sentences on the public
     `/matchbalance` landing page.
   - **8b (not started):** a committed script to render the public sample PDF/PNG and the
     design workbook/PNGs from a synthetic run, plus a renderer-hash test (audit O1,
     backlog IMP-251).
9. G1+G2 (agentic-setup git-guard rule for junctioned worktrees; lock the live worktree) —
   **not started**.
10. T1+T8+T5 (the enqueue test double, four unpinned shipping rules, Streamlit test doubles)
    — **not started**.

K1's owner decision, recorded 2026-09-24: **the tier sheet is retired for good.** The shipped
product is a PowerScore seed order with "Score step" markers and an "Unseeded teams" table
(shipped in #1177, 2026-09-19). Every doc, spec and runtime string that still describes the
old "matchup tiers" / editable-Tier-column product is stale and should describe the current
one. Do not re-ask this — it was already asked and answered once.

## Fix 8a: exact state right now

- **Worktree:** `C:/pitchrank-seeding-docs`, branch `fix/seeding-docs-seed-order`, based on
  `origin/main` at `35103130c` (which is PR #1221's merge commit). No PR opened yet.
- **Plan:** `C:/pitchrank-seeding-docs/.turbo/plans/seeding-docs-seed-order.md`, status
  `approved`, with an "As built" section already filled in (two deliberate deviations
  recorded there — read it before touching anything).
- **Staged** (`git -C C:/pitchrank-seeding-docs diff --cached --stat`: 8 files changed,
  236 insertions, 115 deletions):
  - `docs/matchbalance-seeding.md` — fully rewritten for the current sheet.
  - `.turbo/specs/matchbalance-seeding-intake.md` — Status line changed to
    `superseded — the shipped workflow is documented in docs/matchbalance-seeding.md`.
  - `src/tournaments/seeding_pack.py` — the garbled `ValueError` string
    ("Rebuild seeding sheets; Rebuild matchup tiers are replaced as part of that action
    before exporting.") replaced with "The roster or team matches changed. Build seeding
    sheets again before exporting."
  - `tests/unit/test_seeding_pack.py` — the two `pytest.raises(ValueError,
    match="Rebuild matchup tiers")` pins updated to match the new string.
  - `tournament_intake.py` — the stale docstring on the Seeding-sheet render function
    corrected (it said "Review matchup tiers and generate the selected cohort PDF pack.").
  - `frontend/app/matchbalance/page.tsx` — two sentences changed, **owner-approved wording,
    already shown to the owner in a live preview and confirmed "Looks good, shut it down"**:
    - the PDF-deliverable card body (line ~38): now "Each covered age group and gender gets
      its own sheet: teams in a suggested seed order by PitchRank score, with the larger
      score gaps marked and any team PitchRank can't place listed separately for your
      review." (Note: this required switching the string from single- to double-quoted,
      because the approved wording contains an apostrophe in "can't" — verify that quote
      conversion didn't get re-broken by any later edit.)
    - the FAQ answer about unrated teams (line ~74): now "They stay on the sheet in their
      own section, without a seed. PitchRank has no current rank for these teams, so
      nothing is guessed for them; you place them using recent results, prior division or
      club input."
  - `.turbo/improvements.md` — new entry **IMP-278**: logs that
    `frontend/lib/seedingPredictions.ts`'s `metadata_conflict` reason string still says
    "Then rebuild matchup tiers. Your team match is saved." **Deliberately left unchanged**
    in fix 8a — that file is hashed into `seeding_predictor_sha256()`
    (`src/tournaments/seeding_predictions.py`), so editing its wording would make every
    saved Seeding run report "the predictor has been updated" and need a rebuild. The owner
    chose (2026-09-25) to fix that wording later, alongside a real predictor update, rather
    than force a mass-rebuild now for a cosmetic string. **Do not "fix" this file in 8a** —
    it was left alone on purpose.

## Verification already run and green, on this exact staged tree

- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` — clean.
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`
  — 7,555 passed, 12 skipped (pre-existing, unrelated), 0 failed.
- Frontend (with a `frontend/node_modules` junction to `C:\PitchRank\frontend\node_modules`
  in the worktree — junction the same way, and `rmdir` it before removing the worktree):
  `eslint .` (1 pre-existing warning in an unrelated file, 0 errors), `prettier --check .`
  (clean), `npm run typecheck` (clean), `npm run test` (852 vitest tests passed, re-checked
  stderr separately — genuinely clean, not just exit-0), `npm run generate-llms` then
  `git diff --exit-code frontend/public/llms.txt` (no drift).
- Every `**Bolded**` UI label quoted in the rewritten `docs/matchbalance-seeding.md` was
  grep-verified against the live code (script in this session's scratchpad, not saved to
  the repo — re-derive with `git grep -F` per label if you need to re-check).
- `git grep -n -i tier` over the touched files: only deliberate mentions remain (module
  filenames `seeding_tiers.py`/`test_seeding_tiers.py`, and two unrelated "tier"/"tiers"
  uses in the old spec body that this fix does not touch).

## What is still needed to finish 8a

This was mid-`/polish-code` (called from `/finalize`) when the review subagents started
failing. **Resume at `/review-code`** (full six-dimension review + peer review) on
`git -C C:/pitchrank-seeding-docs diff --cached`. Five internal dimensions
(correctness, api-usage, consistency, simplicity, coverage) plus the peer review still need
to run — only security completed (verdict: **secure, no findings** — the diff is 9 files
including the plan file `.turbo/plans/seeding-docs-seed-order.md`, which the security
reviewer also checked and found no identifiers/secrets in, since `.turbo/plans/` is one of
the seven un-ignored `.turbo/*` paths published from this public repo).

Give the reviewers these specific claims to refute (from the original review prompt, still
valid):
- (a) every quoted UI label in the new doc matches real current code, not the retired tier
  product;
- (b) the corrected `ValueError` text and the two `test_seeding_pack.py` `match=` pins agree
  with each other;
- (c) no other test or frontend assertion anywhere in the repo still expects
  "Rebuild matchup tiers" (grep the whole tree, not just the diff);
- (d) the `page.tsx` single→double-quote change is syntactically and semantically the file's
  only change, and the apostrophe was fixed correctly;
- (e) this PR changes no live sheet-building logic — only two error-string literals, a
  docstring, two marketing sentences, and docs.

After review: `/evaluate-findings` → `/apply-findings` (re-verify any new guard the same way
prior fixes in this audit did) → `/smoke-test` (this is a docs/copy change with no new
interactive surface beyond the two `page.tsx` sentences, which were already shown live and
approved — the smoke-test skill may reasonably find nothing further to exercise and route to
the read-only fallback, or re-confirm the `page.tsx` sentences render correctly one more
time) → then the rest of `/finalize`: `/simplify-docs` on the diff, `/update-changelog`
(skip — this repo has no `CHANGELOG.md`), `/self-improve`, then ship: commit with `git -C`,
`git merge-tree --write-tree` check against `origin/main` before pushing (a
`.turbo/improvements.md` conflict is likely and routine — resolve by keeping both sides,
main's entries first then this branch's, per `backlog-files-conflict-on-every-parallel-pr`),
push, open the PR (confirm title/body with the owner first), then
`python scripts/pr_wait.py --no-merge` from the worktree. **Do not merge** — the owner
merges explicitly ("merge"/"go") after seeing the check results, same as every prior fix in
this audit.

## Environment facts the next session must not trip over

- **Never touch `.turbo/worktrees/matchbalance-main-live` or port 8503.** It is a live
  Seeding app the owner may still have running.
- **Never touch `.turbo/worktrees/*` generally** for anything other than reading — they hold
  stale copies that pollute a recursive grep. Use `git grep` or the `Grep` tool, not
  `grep -r`.
- `C:/pitchrank-seeding-docs/frontend/node_modules` is a Windows junction to
  `C:\PitchRank\frontend\node_modules`. `rmdir` the junction (not a recursive delete) before
  `git worktree remove`, or the recursive delete destroys the shared install for every other
  worktree.
- This checkout (`C:\PitchRank`) and its sibling worktrees are shared with other concurrent
  sessions. Several other worktrees exist for unrelated in-flight work
  (`C:/pitchrank-affinity-or`, `C:/pitchrank-measure`, `C:/pitchrank-none-opponent`,
  `C:/pitchrank-team-share-card`, `C:/pitchrank-traffic-spike`, plus two Codex-branded
  worktrees under `.turbo/worktrees/`). Do not touch, stage, or clean up anything in them.
- `origin/main` is ahead of what any stale local checkout shows — always `git fetch
  --all --prune` before trusting branch/PR state, and check PR state with
  `gh pr view <n> --json state`, not `git merge-base --is-ancestor`, because
  `delete_branch_on_merge` removes the merged branch's remote ref the moment it merges.
- CI (`ci.yml`) is the only merge gate: Python Lint, Python Tests, Frontend Lint, Frontend
  Format, Frontend Typecheck, Frontend Tests, Frontend llms.txt Drift Check. Codex's PR
  review is advisory and reviews roughly half of PRs; `claude-review` does not run on PRs at
  all currently (disabled, see root `CLAUDE.md`).
- Attribution lines for commits/PRs opened from *this* session used Claude Opus 5.5, then
  switched mid-session to Claude Sonnet 5 when the harness's model changed. Whichever agent
  finishes 8a should use its own correct attribution footer, not copy one of these blindly —
  check the current session's system reminder for the exact lines.

## Fix 8b: regenerate the stale public sample and design workbook (audit O1, backlog IMP-251)

Finding, verbatim from `.turbo/audit-2026-09-23/findings-combined.md`:

> **O1 · P2 · CONFIRMED** the public sample PDF is unreproducible and stale (= K1 sample
> part): rendered 2026-09-17 by an uncommitted script from a gitignored run with live data;
> six PRs since changed the renderers (+656/−84); IMP-251 asks for a re-render but no tool
> exists. Fix: committed regeneration script + renderer-hash test.

Concretely:

- `frontend/public/matchbalance/sample-u13-boys.pdf` and `.png` were rendered by a one-off,
  uncommitted script against a real (gitignored) run with live PitchRank ratings on
  2026-09-17 — before #1177 (2026-09-19, the tier→seed-order rewrite) and five more PRs
  that touched the renderers since. Nine lines of its content ("Tier 1 STRONGEST GROUP",
  "Manual placement needed", "Boundary option", etc.) no longer exist in any current
  renderer. This is the same staleness fix 8a's landing-page copy fix addresses in words;
  8b fixes the actual sample artifact.
- `docs/design/matchbalance-excel/director-workbook-sample.xlsx`,
  `docs/design/matchbalance-excel/u10-boys.png` and `u12-girls.png` are equally stale
  (last touched in #1174, 2026-05-01-era commit `24f85cb3d`): their headers read
  "Recommended tier" / "Placement guidance" / "Final flight", freeze pane `E11`; the live
  `seeding_workbook.py` now writes "Strength marker" / "Placement status" / "Final
  division", freeze pane `D7`. `docs/design/matchbalance-excel/README.md`'s prose already
  matches the live code (it was fixed in #1177) — only the sample files themselves are
  stale.
- Fix: a **committed** script (not a scratch one-off) that builds a synthetic Seeding run
  with frozen, non-live fixture data (no real ratings, no Supabase calls) and drives the
  real renderers — `seeding_sheet.py`/`seeding_pdf.py` for the PDF/PNG,
  `seeding_workbook.py` for the xlsx/PNGs — to produce all five artifacts
  (`sample-u13-boys.pdf`, `sample-u13-boys.png`, `director-workbook-sample.xlsx`,
  `u10-boys.png`, `u12-girls.png`) deterministically from that fixture. Pair it with a
  renderer-hash test: hash the script's synthetic input plus the renderer module versions,
  compare against a committed hash, and fail loudly (pointing at the regeneration script)
  when a renderer changes without the samples being regenerated. Update the four binary
  artifacts in the same PR by actually running the new script.
- `.gitignore:72` is relevant context (cited in the O1 row) — check what it currently
  excludes near there before adding the new script's own scratch output to it.
- IMP-251 in `.turbo/improvements.md` (on `origin/main`) already describes wanting this;
  close it in the same PR per this repo's rule that a shipped fix must close its own
  backlog entry (`.turbo/improvements.md` → move the closed entry into
  `.turbo/improvements-archive.md` by hand, per CLAUDE.md's Improvement Backlog section —
  do not run `scripts/sweep_improvements.py`, which reorders unrelated entries).

## Fix 9: G1 (junction-aware worktree-remove guard) + G2 (lock the live worktree)

These are about the **Claude Code tooling in this repo** (`.claude/settings.json`,
`.claude/hooks/git-guard.sh`), not about the seeding app's own code. If Codex is not itself
a Claude Code session, G1's fix (a Claude-specific hook) still needs building and is still
in scope — other Claude sessions use this repo and hit the same guard gap — but Codex should
not expect its own tool-approval flow to be affected by it.

**G1**, verbatim:

> **G1 · P1 · CONFIRMED mechanism (toy repo Git 2.50.1; git-guard payloads)**
> `git worktree remove` needs no approval and no guard (`.claude/settings.json:15`;
> `.claude/hooks/git-guard.sh`; `test_claude_config_json.py:72,84` justifies the wildcard
> with a false claim) while the documented worktree setup junctions `frontend/node_modules`
> to the shared install; removal deletes through the junction, emptying the shared install
> that the predictor (`node_modules/tsx`) and the PDF worker (`@playwright/test`) need;
> session-start reports the worktree clean (`status --porcelain` never lists ignored
> content). Memory records it happening before (2026-09-13); the shared install is empty
> now (emptied 10:35:53 today, ~50 s after #1208 merged, before this audit started; cause
> unattributed). Fix: guard `worktree remove` when the target's `node_modules` is a
> junction; refuse `git clean -x/-X` in the main checkout; narrow the allowlist to
> add/list/prune.

**Status update (2026-09-25): `C:\PitchRank\frontend\node_modules` is populated again**
(581 entries) — someone ran `npm ci --prefix frontend` since the audit. The *guard gap*
itself is still open: `.claude/settings.json:15` still reads the wildcard
`"Bash(git worktree *)"`, unguarded, verified today. Fix:

- In `.claude/hooks/git-guard.sh`, add a check that fires on `git worktree remove` (and
  `git worktree prune`, which can also delete a junctioned directory's target contents
  depending on Git version/config — verify this before deciding whether to guard it too):
  resolve the target worktree's `frontend/node_modules` path and check `fsutil reparsepoint
  query` (Windows) or the equivalent junction/symlink test; if it is a junction/reparse
  point, refuse and tell the operator to `rmdir` the junction first (this repo's own
  established pattern, used throughout the last several fixes in this audit).
- Also refuse `git clean -x` / `-X` in the main checkout (`C:\PitchRank` itself, not a
  linked worktree) per the finding — these can delete gitignored content across the whole
  shared checkout, including another session's `node_modules` or scratch files.
- Narrow `.claude/settings.json:15`'s `"Bash(git worktree *)"` allowlist entry to the
  specific safe subcommands (`add`, `list`, `prune` — reconsider `prune` per above) rather
  than the wildcard, once the guard hook covers `remove` itself; the audit's fix note says
  "owner applies settings changes" for this file specifically, so **confirm with the owner
  before editing `.claude/settings.json`**, even though the hook script itself
  (`.claude/hooks/git-guard.sh`) is an ordinary code change.
- `tests/unit/test_claude_config_json.py:72,84` currently justifies the wildcard allowlist
  with a claim the audit found false — read those exact lines, correct or remove the false
  justification, and add a test that a `git worktree remove` targeting a junctioned
  `node_modules` is refused (or at minimum that the settings allowlist no longer contains
  the bare wildcard).

**G2**, verbatim:

> **G2 · P1 · CONFIRMED (netstat, Win32_Process, `git diff`)**
> `.turbo/worktrees/matchbalance-main-live` (detached at 7575b28ea = #1198) is the code
> behind a RUNNING MatchBalance Seeding app: PID 31776
> `python -u C:/PitchRank/.turbo/validation/seeding-reference-live/launch.py`, started
> 2026-09-21 13:34, listening on 127.0.0.1:8503 with a connection held by the OpenAI Codex
> desktop app, loading `C:/PitchRank/.env` with `override=True` (production keys). No
> tracked file or handoff mentions it. Routine cleanup (the PR is merged, removal needs no
> approval, session-start calls it clean) would delete the code under a live session; if a
> seeding fix merges, this app keeps serving 7575b28ea with nothing on screen saying so
> (today the seeding-scope diff to origin/main is empty). Fix:
> `git worktree lock --reason "live Seeding app :8503"`; document or retire the launcher;
> show the served commit in the app.

This is an **Escalate** verdict, not a plain Apply — it needs an owner decision on whether
that launcher/app should keep running at all, be documented as a standing fixture, or be
retired. **Do not decide this unilaterally; ask first.** Once decided:

- `git worktree lock --reason "live Seeding app :8503"` on
  `.turbo/worktrees/matchbalance-main-live` prevents an accidental `git worktree remove`
  regardless of the G1 guard's own coverage — belt and suspenders.
- Add a short doc (a new file under `.turbo/` or `docs/`, or a section in
  `docs/matchbalance-seeding.md`) recording: what `launch.py` does, that it uses production
  Supabase keys, who/what depends on it staying up, and how to find/stop it (PID via the
  listening port, as this session and the 2026-09-23 audit both did:
  `netstat -ano | grep ":8503"`).
- Show the served commit somewhere in the running app itself (a footer line reading the
  worktree's current `git rev-parse HEAD`, computed at Streamlit startup) so nobody has to
  reverse-engineer which code is live the way this audit had to.
- This finding, and the standing rule "never touch port 8503 or
  `.turbo/worktrees/matchbalance-main-live`", has held for the entire audit so far (fixes
  1–8a). Verify it is *still* accurate before acting — `netstat -ano | grep ":8503"` and
  `git -C .turbo/worktrees/matchbalance-main-live log -1` — because the owner may have
  stopped or moved it since 2026-09-23.

## Fix 10: T1 (untested enqueue write) + T8 (four unpinned shipping guards) + T5 (test doubles more permissive than production)

All three are **coverage** findings — the code they describe already exists and is (as far
as this audit found) behaving correctly; the gap is that nothing would catch a regression.
Each needs a real test, not a behavior change. Read
`.turbo/audit-2026-09-23/findings-combined.md` lines ~286-303, ~310-312 in full before
starting (search for `**T1 ·`, `**T5 ·`, `**T8 ·`) — the excerpts below are trimmed.

**T1** (`src/tournaments/seeding_enqueue.py:158-206`; `tests/unit/test_seeding_enqueue.py`):
the only database write in the enqueue path — `make_enqueue_caller` and
`make_provider_team_id_lookup` — is never exercised by a real double; the existing tests
inject a plain callable that can't tell a correct RPC call from a broken one. Per this
audit's own project-wide test-double rules (see root `CLAUDE.md`'s "A double for a
deferred builder must record at the terminal call, not at construction" and "A double must
refuse what production refuses"): build a `_Db`-style double that records at `.execute()`,
assert the literal RPC name and arguments, add a case with a non-GotSport provider row
(should be filtered, per the `.eq("provider_id", …)` clause), and a test that the "Check
teams available to refresh" button makes zero RPC executes (dry-run path).

**T8** (`roster_paste.py:150`; `seeding_pack.py:288-290,403-407`; `seeding_intake_ui.py`
`:380-381`, `:95`, `:102` — **these line numbers are from the pre-fix-6/7 tree**; the
heading-parsing code at `roster_paste.py:150` in particular was substantially rewritten by
fix 6 (PR #1220, the shared `cohort_labels.py` reader) — **re-locate each guard by symbol
name, not by these line numbers**, before writing a mutation-verified test):
four guards that decide what ships are unpinned, each confirmed by a surviving one-line
mutation against the full suite:
1. the "heading wins" rule — a team name whose own band disagrees with the section heading
   must still file under the heading's cohort (the audit's example:
   `BLACK LIONS 14/15 U13B SELECT` under a `U13` heading must stay U13, not silently move to
   U12 from the name's own band);
2. a placement-check forecast reversal on its own must be sufficient reason to hold delivery
   in `needs_placement_review` (`seeding_pack.py`, near the current `_review_reason`/
   `needs_placement_review`, moved since the audit — grep for `placement_checks` and
   `limited_history` in `seeding_pack.py` to relocate), independent of limited-history
   status;
3. a partial (à la carte) cohort selection with an orphan roster row above any heading must
   still produce a DRAFT pack (the `could_belong` clause in
   `seeding_intake_ui.py`/`seeding_assessment.py` — relocate by symbol);
4. no existing test ever seeds a correctly-matched **girls'** team end-to-end
   (`seeding_pack.py:288-290`'s era — the whole-tournament test fixtures the audit found
   only check totals, not that a specific matched girls' entrant actually reaches
   `SEEDED` status with `gender == "Female"`).

Each of these four needs its own test, verified the way every guard in this audit has been
verified so far: write the test, then deliberately break the guard in a scratch/throwaway
copy and confirm the new test (by name) is what fails — not a pre-existing test. Follow the
mutation-verification pattern used in fixes 6 and 7 of this same audit (see either PR
#1220's or #1221's description for the pattern, or this repo's root `CLAUDE.md` section "A
mutation has to kill *your* test, not just redden the suite").

**T5** (`tests/unit/test_seeding_event_intake.py:48-126,175,298,387`): the shared Streamlit/
GotSport-walk test doubles in this file are more permissive than what they stand in for,
which is how several other confirmed defects in this audit (C6, C8, S3) shipped green in
the first place:
- `_FakeSt` keeps warnings/errors across a simulated rerun (real Streamlit clears them);
- `_FakeStatus.update` / `_FakeProgress.progress` are no-ops, hiding the Backtest
  mid-walk yield points and the "recovery must be written before any Streamlit call"
  ordering rule (which fix 7 of this same audit, PR #1221, later encoded properly for the
  Seeding side — T5's fix should bring the Backtest-shared doubles up to the same standard);
- `_FakeSt.radio` always returns `"GotSport event"`, so no existing test ever drives the
  paste-path "Import and match teams" button through this fixture file;
- the `app` fixture's autosave stub always returns `True` (a real failed save is never
  simulated here);
- the challenge/wait-for tests feed challenge response bodies where production would
  actually answer with a 422 (this is the S3 rule — check whether S3's shipped fix, PR
  #1214, already covers this from the production side; T5 is specifically about the *test
  double* not reflecting that, which could let a regression back in even with S3's
  production code fixed).

Fix: tighten each double to match its real counterpart's behavior (clear state on rerun,
make status/progress no-ops observable, let the radio actually vary per test, let autosave
fail, feed real 422 bodies), then re-run every test in the file and confirm none was
silently relying on the over-permissive behavior to pass; a test that starts failing once a
double is tightened is *itself* a shipped-but-uncaught defect and belongs in scope here or
as a fresh backlog entry, not swept under the rug.

## Backlog entries this audit has produced so far (do not duplicate)

IMP-251 (regenerate the stale public sample PDF/design workbook — this is fix 8b),
IMP-268 through IMP-277 were created by fixes 3–7 of this same audit (CLI partial-keeping,
GotSport scraper's gender reader, wall-clock test pinning, and the renamed-run recovery gap
most recently). **IMP-278** (this session) logs the `seedingPredictions.ts` wording left
alone in 8a. Check `.turbo/improvements.md` on `origin/main` for the current highest ID
before minting a new one — main is worked from several machines in parallel and the ID
sequence there is authoritative, not whatever a stale worktree shows.
