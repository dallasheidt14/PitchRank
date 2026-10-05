# Combined ranking release: implementation review

Reviewed the complete release diff against its main merge base, including the
production entry point, Glicko configuration/convergence, connectivity transport,
ceiling decisions, offline harness, scorer and regression tests.

The implementation review found no remaining code blocker. This is not approval
to merge or publish: full frozen-data validation and the untouched-month decision
remain separate gates.

- The normal workflow calls `calculate_rankings.py --ml --force-rebuild --engine
  glicko`. Both Glicko CLI paths enable the existing ceiling-connectivity boolean.
  The library default remains false for the pinned reference comparisons.
- Enabled mode rejects SCF-on and non-Glicko settings. Missing, duplicate,
  nonfinite or wrong-source diagnostic rows raise before final snapshot saving.
- Connectivity has one measurement implementation, shared with legacy SCF. The
  restored values travel separately from engine/ML rows and are overlaid onto a
  private row only for the ceiling decision. Cache reads and writes are bypassed.
- The rule-order correction retains the freshness restriction while evaluating
  stricter evidence restrictions. Earlier supported play-up and broad-evidence
  relief stay in place. It does not redesign thresholds or ceiling score bands.
- Score clamps and the ML time split are unchanged. No rankings table is used as
  a substitute for the source strength map. No database migration is introduced.
- The offline harness still blocks external reads/writes independently of the
  production permission change. Stage receipts and exact boundary comparisons
  are required; a completed job by itself does not prove a valid comparison.
- The release scorer preserves C1's statistical calculation and adds the approved
  cumulative board/isolation harm veto. It requires a separate locked comparison
  record; neither a missing statistic nor a failed prerequisite can become a pass.
- Seven independent in-memory faults each failed the intended new regression
  tests, covering both CLI paths, dry-run saving, the gender mask, production
  execution, cumulative harm, and comparison-lock enforcement. The measured
  source was not edited for these probes.

The frozen Texas and Washington diagnoses and prior ceiling-only replay are
documented in `2026-10-05-ceiling-rule-order.md`. The full batch and descriptive
September results belong in the separate release report. They must not be
inferred from that earlier diagnostic replay.

## CI portability correction

The first Linux CI run found one last-bit difference in the independently saved
Windows SCF fixture (`unique_states`: 0.8316870804994441 versus
0.8316870804994442). The fixture comparison now permits at most two representable
floating-point steps for decimal fields. Team/field coverage and categorical
values remain exact, as do the same-runtime wrapper and full-run boundary checks.
All 15 connectivity tests pass locally. A deliberate one-step perturbation passes;
a 1e-10 change still fails the pinned-original test. All 15 frozen ranking,
entry-point and measurement-source file hashes remain unchanged. The running
validation batch is unaffected.
