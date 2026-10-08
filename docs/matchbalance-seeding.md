# MatchBalance Seeding sheets

Seeding is an internal service workflow: the operator prepares a PDF cheat
sheet and sends it to tournament directors. Each age/gender cohort gets its own
section with consecutive strength tiers and compatible division formats.
PowerScore remains the baseline; directors decide final placement and pool membership.

## Prepare and deliver a pack

1. Install the locked browser dependencies and Playwright Chromium, then start
   Streamlit and select **Seeding**:

   ```powershell
   npm ci --prefix frontend
   Push-Location frontend
   npx playwright install chromium
   Pop-Location
   python -m streamlit run tournament_intake.py
   ```

   Configure the existing PitchRank Supabase environment. PDF export can also
   use an installed Edge or Chrome browser. Do not change `TEMP` or `TMP` to
   work around Windows export failures; MatchBalance creates a
   subprocess-compatible temporary workspace itself.
2. Name the event and import the complete accepted roster. Preserve requested
   flight and listed-division context as separate fields. Confirm every cohort
   and accepted-team count against the director's list.
3. Select the cohorts to finish, then resolve their identities. Unrelated open
   cohorts do not block review; ambiguous entries that could belong to a selected
   cohort still need review. Confirm coverage for the selected cohorts against
   the accepted roster. Unmatched teams, duplicate identities, inactive teams,
   missing ratings, and metadata conflicts remain visible for manual placement.
   A younger team playing up remains eligible when its other data is valid.
4. Click **Build seeding sheets**. The saved pack freezes
   its roster, current ratings, predictions, policy, and original PowerScore
   order for reproducibility.
5. Review three distinct orders:

   - **PowerScore Seed** is the immutable baseline for this run.
   - **MatchBalance Seed** is the conservative algorithmic recommendation.
   - **Effective Seed** follows MatchBalance unless the operator saves a manual override.

6. To override the recommendation, assign unique, contiguous manual seeds. Every
   automatically eligible rated team must either receive a seed or be explicitly
   marked **Hold for manual placement**. Saving notes alone never changes order.
   **Restore MatchBalance suggested order** removes the manual override.
7. Check snapshot freshness and generate the PDF and Excel pack. Dated drafts
   remain available. Final delivery requires a successful current-session check
   or **Accept dated snapshot for delivery** with a recorded reason. This cannot
   bypass identity, roster-integrity, coverage, or placement checks.

Saved runs live under `reports/seeding/<event-name>/seeding_run.json`. Reopening
uses the saved snapshot and reproduces its PowerScore baseline, MatchBalance
suggestion, movement evidence, manual override, and notes. Rebuilding is the
explicit refresh operation.

Freshness is **verified current**, **newer inputs available**, or **not checked**.
The prediction loader hashes the actual rating, merged-identity, and history
inputs per cohort, with a separate model/code identity. Checking compares those
inputs without replacing saved predictions. Reopening offline shows the last
check time but requires another check or a snapshot-specific acknowledgment.
Changes to report contents invalidate its acknowledgment and cached exports.

Cohort fingerprints keep unrelated roster edits from invalidating completed
cohorts. Narrowed rebuilds retain notes, tier names, and manual decisions for
later selection; manual orders restore only while their cohort fingerprint
matches. A stale snapshot may be saved as a rebuild source but cannot be exported
as a current analysis. Legacy snapshots upgrade from their frozen predictions
without querying the database or rewriting the original file during replay.

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

The PDF, printable HTML, Excel, and Streamlit review share one content model.
Effective seed and team name come first, followed by tier, score, and essential
warnings. Baseline comparisons and detailed diagnostics are expandable in the
operator view. Tier names default to Tier 1, Tier 2, etc.; the operator can name
them Gold, Silver, or another useful label.

**Competitive Break** means natural strength separation. **Recommended tier
break** means a practical division boundary supported by complete-division
matchup analysis. Both labels appear when the evidence agrees. Every natural
boundary is evaluated without a display cap. Manual ordering or holds recompute
the guidance for the effective membership. **Very close** ranges survive only
when their full contiguous member sequence survives.

Manual-placement warnings and plays-up/requested-flight/listed-division context
stay visible. Uncertain teams are never silently pushed to the bottom.

## Practical tier selection

The versioned library in `config/matchbalance_format_library.json` describes
exact operational variants for a competitive flight. A flight and its pools are
different layers: one eight-team competitive flight may contain two four-team
pools, but it is still evaluated as one eight-team flight across all 28 possible
pairings.

Run the frozen-pack diagnostic without per-cohort flight counts or sizes:

```powershell
python scripts/suggest_matchbalance_flights.py `
  --snapshot <saved-seeding-run.json> `
  --event-name <event-name> `
  --report-slug <report-slug> `
  --output-dir <internal-output-directory>
```

With no `--cohort`, the command evaluates every cohort selected in the saved
pack. With no `--profile`, it uses the versioned MatchBalance default profile.
An explicit event profile applies event-wide. The command generates every
profile-supported exact cover within the profile's search safeguard, partitions
the unchanged saved order contiguously, and sends every unique membership
through the complete-flight evaluator.

The default recommendation policy considers only structurally valid plans with
complete predictions and no projected matchup violations. It prefers the fewest
competitive flights, then lower worst matchup cost, then lower pair-weighted
average cost, with deterministic ties. It reports limited-history passes as
provisional, retains useful alternatives, and returns review-required status
when no complete within-policy arrangement exists. Team-count compatibility is
not a claim of field, time, referee, or schedule feasibility. The saved profile
filters out formats that fail its minimum-game requirement.

If no arrangement passes, the sheet offers a **review-required compromise**
by lowest worst normalized mismatch risk, then fewer violating pairings, lower
average cost, and fewer divisions. Normalized risk is the maximum of expected
absolute goal difference divided by its limit and four-goal probability divided
by its limit. A compromise never becomes a passing plan after operator review.
Incomplete searches or missing matchup predictions cannot supply a recommendation.

The sheet shows division sizes, compatible pool sizes, minimum games, the worst
remaining mismatch, history concerns, and one useful alternative with the lowest
worst-matchup cost when one exists. Additional alternatives stay internal.
Unplaced entrants remain visible outside the seed order; subset guidance states
its coverage, such as **12 of 14 teams assessed**.

## Implementation and checks

- `seeding_suggested_order.py` contains the isolated deterministic constrained
  optimizer and team-centered movement explanations.
- `seeding_tiers.py` freezes the PowerScore baseline, evaluates local consensus,
  invokes the optimizer, and recomputes display annotations.
- `seeding_pack.py` snapshots the baseline, suggestion, movement reasoning,
  conflicts, and explicit manual override (pack schema 6, analysis schema 9).
- `seeding_freshness.py` binds freshness evidence and acknowledgments to the
  saved snapshot. Shared export content uses schema version 6.
- `seeding_format_library.py` validates exact format variants and resolves the
  event-wide profile; `seeding_flight_suggestions.py` generates and selects
  fixed-order candidate structures without altering the seed or boundary logic.
- `seeding_sheet.py` and `seeding_workbook.py` render the customer cheat sheet;
  `seeding_intake_ui.py` retains the detailed operator evidence and manual editor.
- Relevant regression suites include `test_seeding_suggested_order.py`,
  `test_seeding_guidance.py`, `test_seeding_tiers.py`, `test_seeding_pack.py`,
  `test_seeding_intake_ui.py`, `test_seeding_sheet.py`, and
  `test_seeding_workbook.py`.

Historical prediction validation remains separate from projected benefits of
alternate divisions. See [the historical scorecard](matchbalance-historical-scorecard.md).
