# MatchBalance Seeding sheets

Seeding is an internal service workflow: the operator prepares a PDF cheat
sheet and sends it to tournament directors. Each age/gender cohort gets its own
section. MatchBalance recommends an order; it does not publish a ranking, change
PowerScore, or force a tournament format.

## Prepare and deliver a pack

1. Run `python -m streamlit run tournament_intake.py` and select **Seeding**.
   Configure the existing PitchRank Supabase environment. PDF export uses an
   installed Edge/Chrome browser or Playwright Chromium.
2. Name the event and import the complete accepted roster. Preserve requested
   flight and listed-division context as separate fields. Confirm every cohort
   and accepted-team count against the director's list.
3. Resolve identities. Unmatched teams, duplicate identities, inactive teams,
   missing ratings, and metadata conflicts remain visible for manual placement.
   A younger team playing up remains eligible when its other data is valid.
4. Select the cohorts and click **Build seeding sheets**. The saved pack freezes
   its roster, current ratings, predictions, policy, and original PowerScore
   order for reproducibility.
5. Review three distinct orders:

   - **PowerScore Seed** is the immutable baseline for this run.
   - **MatchBalance Seed** is the conservative algorithmic recommendation.
   - **Manual/Effective Seed** appears only when the operator saves an override.

6. To override the recommendation, assign unique, contiguous manual seeds. Every
   automatically eligible rated team must either receive a seed or be explicitly
   marked **Hold for manual placement**. Saving notes alone never changes order.
   **Restore MatchBalance suggested order** removes the manual override.
7. Generate and inspect the PDF and Excel pack. An identity, roster, cohort,
   rating-snapshot, or predictor change invalidates outdated exports.

Saved runs live under `reports/seeding/<event-name>/seeding_run.json`. Reopening
uses the saved snapshot and reproduces its PowerScore baseline, MatchBalance
suggestion, movement evidence, manual override, and notes. Rebuilding is the
explicit refresh operation.

## Ordering policy

PowerScore remains the baseline. Compare material reversals enter the automatic
ordering step only after all local-consensus safeguards pass:

- the two main teams have established history;
- limited-history reference teams are excluded;
- identical nearby 5-, 6-, and 7-team windows are used where available;
- a strict majority of shared-opponent comparisons support the lower
  PowerScore seed and the average profile advantage is positive;
- leave-one-reference-out support is stable;
- direct expected-goal advantage reaches the independently configurable
  material-reversal threshold; and
- a two-seed move has evidence over every crossed seed.

The constrained optimizer considers all supported relationships together. It
first satisfies the maximum number of relationships, then minimizes total
movement, then prefers the original PowerScore order. No team may move beyond
the configured cap. Most importantly, every inversion from PowerScore order
requires an explicit fully supported relationship for the passing team over the
crossed team. Conflicts and cycles therefore resolve to the safest deterministic
subset and remain visible for operator review.

The default policy is:

- competitive enough: expected absolute goal difference at most 2.0 and 4+
  goal blowout probability at most 30%, with every pairing required to pass;
- very close: adjacent expected absolute goal difference at most 1.0;
- material reversal: directional expected-goal advantage at least 1.0; and
- maximum automatic movement: two positions from the original PowerScore seed.

These thresholds and the local-consensus settings are stored explicitly and
remain independently configurable.

## Customer cheat sheet

The customer PDF emphasizes MatchBalance Seed, team, PowerScore, and movement
from PowerScore Seed. Moved teams use plain language such as **up from
PowerScore #6**. Technical support fractions, window diagnostics, probabilities,
and leave-one-out results remain in the internal operator view.

**Competitive Break** separators communicate natural model separation, not a
mandatory bracket, division, or flight size. **Very close** ranges communicate
that adjacent teams occupy the same competitive neighborhood without claiming
they are equal. Both annotations are recalculated from the MatchBalance order's
new adjacency. After a manual override, an annotation survives only when its
exact boundary or contiguous member sequence still survives.

Manual-placement warnings and plays-up/requested-flight/listed-division context
stay visible. Uncertain teams are never silently pushed to the bottom.

## Implementation and checks

- `seeding_suggested_order.py` contains the isolated deterministic constrained
  optimizer and team-centered movement explanations.
- `seeding_tiers.py` freezes the PowerScore baseline, evaluates local consensus,
  invokes the optimizer, and recomputes display annotations.
- `seeding_pack.py` snapshots the baseline, suggestion, movement reasoning,
  conflicts, and explicit manual override under the versioned saved-pack schema.
- `seeding_sheet.py` and `seeding_workbook.py` render the customer cheat sheet;
  `seeding_intake_ui.py` retains the detailed operator evidence and manual editor.
- Relevant regression suites include `test_seeding_suggested_order.py`,
  `test_seeding_guidance.py`, `test_seeding_tiers.py`, `test_seeding_pack.py`,
  `test_seeding_intake_ui.py`, `test_seeding_sheet.py`, and
  `test_seeding_workbook.py`.

Historical backtesting of reversal proposals remains separate validation work.
