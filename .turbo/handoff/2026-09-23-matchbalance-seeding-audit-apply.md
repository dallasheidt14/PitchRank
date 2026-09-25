# Handoff: Apply the MatchBalance seeding intake audit

## Where this stands

A 29-reviewer audit of the MatchBalance seeding intake (the Seeding tab of `tournament_intake.py` and the
`src/tournaments/{roster_*,seeding_*,event_roster_intake,gotsport_event_roster,compare_predictor_bridge}.py`
modules, the Node predictor bridge and the PDF/Excel/CSV renderers) finished on 2026-09-23. It was analysis
only: **no code, config or doc was changed.** Target was `origin/main` ba5fd2141; every in-scope file was
identical to the checkout's HEAD at the time.

Artifacts (all gitignored under `.turbo/*` except this handoff):

- `.turbo/audit.md` — the report: dashboard, headline, method, ranked "first fixes", owner decisions, all
  114 findings by category with severity and verdict. `.turbo/audit.html` is the same report styled.
- `.turbo/audit-fixes-plain-english.md` — every fix in plain English, grouped by area, same IDs.
- `.turbo/audit-2026-09-23/` — `evaluated-findings.md` (the table `/apply-findings` reads: 102 Apply,
  11 Escalate, 1 Skip; 19 High, 49 Medium, 46 Low), `findings-combined.md` (deduplicated findings with
  reviewer evidence), `audit-brief.md` (the reviewers' shared brief, with domain facts), `da-findings.md`,
  and `reports/` (all 29 reviewer reports, with the harnesses and mutation results they cite).
- `.turbo/audit-2026-06-10.*` — the earlier whole-repo audit, preserved.

Finding IDs are stable across all of these: C = correctness, S = security, A = api-usage, K = consistency,
M = simplicity, T = coverage, D = dependencies, O = tooling, X = dead code, G = agentic setup.

## Environment facts the next session must not trip over

- `frontend/node_modules` in `C:\PitchRank` is **empty** (emptied 2026-09-23 10:35, before the audit;
  likely a junctioned-worktree removal, finding G1). Until the owner runs `npm ci --prefix frontend`,
  "Build seeding sheets", "Generate PDF pack", vitest, tsc and two `test_compare_predictor_bridge.py`
  tests fail here. The auto-mode classifier refused to let an agent run the install; do not retry it,
  ask the owner.
- `.turbo/worktrees/matchbalance-main-live` is **serving a live Seeding app** on 127.0.0.1:8503 (PID 31776,
  launched 2026-09-21 by `.turbo/validation/seeding-reference-live/launch.py`, Codex desktop client,
  production keys). Do not remove or check out over that worktree (finding G2). The other four
  `.turbo/worktrees/*` are stale and pollute Glob/`grep -r`; use Grep or `git grep`.
- `scripts/full_club_analysis.py` shows as modified; another session did that. Leave it.
- The checkout is shared with other live sessions; the usual rule applies (branch for any change, never
  `git add -A`, never stage or delete files you did not create).

## Owner decisions still open (Escalate verdicts)

K1 confirm the tier sheet is retired for good before the doc/sample/copy rewrite (Codex argued the reverse;
three later PRs build on the seed-order sheet) · G2 lock the live worktree and decide the launcher's future ·
S4 spend ceiling and failure breaker on event walks · M1b/M2/M3b the three refactors (split the interleaved
walk, split the 229-line walk function, one typed snapshot + shared Node runner) · X1 delete the three
orphaned Backtest-era modules · X10 delete the superseded optimizer script · X8 the published-cohort-label
field · A5 merge-map paging without an order (out of scope) · K15 policy carry-forward and Backtest's proxy
blowout definitions · G7 Codex guard rails · O9 a Windows CI job.

## Suggested order of work

The report's "Recommended first fixes" section orders them by what a director or the operator notices
first. Each is a small PR on its own branch from `origin/main`:

1. C1 + K5 — reason codes from the predictor, one status map, cross-language test.
2. C4 — delete the sheet-level autofilter, fix validator and three tests.
3. S2 + S3 — cancel queued pages on a block, save the partial walk, treat an exhausted wait-for 422 as a block.
4. C6 + C7 + C8 + C22 — bind runs to their source, keep the name out of the widget key, rerun only after success.
5. S1 — bind localhost, drop CORS-off, add a login.
6. C5 + C10 + C11 + K4 — one shared cohort-label reader.
7. C2 + C3 — preserve notes across partial rebuilds; recovery file for builds.
8. K1 (after the decision) + O1 — doc rewrite, reproducible sample.
9. G1 + G2 — git-guard rule for junctioned worktrees; lock the live worktree.
10. T1 + T8 + T5 — the enqueue double, the four unpinned shipping rules, the Streamlit doubles.

Then the Medium and Low rows in `evaluated-findings.md`, and the dead-code removals (X1–X7) as their own PR.

Rules that bite here: every writer needs a dry-run guard; a test double must refuse what production
refuses and record at `.execute()`; name expected values as literals; mutate each half of a multi-part
guard on its own; `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py` and the ruff path list
are the gate; run `scripts/pr_wait.py --no-merge` after opening a PR. The audit brief's domain-facts section
(`.turbo/audit-2026-09-23/audit-brief.md`) is the fastest refresher on age bands and the heading-wins rule.

## Next step

Ask the owner for the K1 decision (is the tier sheet retired for good?) and confirm `npm ci --prefix frontend`
has been run, then open a branch from `origin/main` and start with fix 1 (C1 + K5): read
`src/tournaments/seeding_tiers.py:399-405`, `frontend/lib/seedingPredictions.ts:128-145` and
`src/tournaments/seeding_intake_ui.py:376-388`, add a reason code to the TypeScript result, map codes to
placement status and to the draft gate in one table, and write the test that feeds every TypeScript reason
through the classifier.
