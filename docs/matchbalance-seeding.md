# MatchBalance Seeding sheets

Seeding is an internal service workflow: the operator prepares PDF cheat sheets
and sends them to tournament directors. Directors use the sheets to place teams
in competitive divisions and pools. Each age/gender cohort gets its own section.
Sell a complete event pack or a pack containing only the requested cohorts.

## Prepare and deliver a pack

1. Run `python -m streamlit run tournament_intake.py` and select **Seeding**.
   Python requirements, Node.js, and `npm ci --prefix frontend` must be installed.
   Configure the existing PitchRank Supabase environment variables. PDF export
   uses installed Edge/Chrome or Playwright Chromium; if needed, run
   `npx --prefix frontend playwright install chromium`.
2. Name the event. Paste its accepted teams with age/gender headings, reopen a
   saved run, or capture the GotSport event. Pasted rows may include an optional
   fourth column for the team's requested flight. A captured event's published
   division is retained separately as its listed division; it is not treated as
   a request from the team. A two-division probe is only a sample;
   finish the whole-event capture before selling a complete tournament pack.
   Confirm the imported team and cohort counts against the director's list.
3. Resolve team identities. A unique same-name result still requires review when
   the submitted and matched club or state conflict. The review table also flags
   every registration row that resolves to the same PitchRank team within one
   cohort. Every accepted row stays in the sheet, including teams whose identity
   or eligibility needs review.
4. Under **Competitive seeding sheets**, select **All imported cohorts** for the
   event pack or **Choose cohorts** for an à la carte order. Click
   **Build matchup tiers**. This reads current data and compares every eligible
   pairing within each selected cohort.
5. Review the tier sizes, boundary explanations, placement alternatives, and
   warnings. Edit the Tier column and **Save tier decisions** when tournament
   knowledge calls for an adjustment. Manual saves preserve the entered tier
   order; adding placement notes alone does not reorder teams.
   A manual combination exceeding the selected limits keeps a visible warning
   in the PDF. **Restore suggested tiers** removes that cohort's manual grouping.
6. Click **Generate PDF pack**, preview the sheets, then **Download PDF pack**.
   Each cohort starts on a fresh Letter page; long lists continue with repeated
   table headings. Printable HTML is also available for browser printing.

Team fixes, tier decisions, notes, preferences, predictions, and rating dates are
saved in `reports/seeding/<event-name>/seeding_run.json`. Reopening a run uses its
saved prediction snapshot. **Build matchup tiers** explicitly refreshes it and
replaces its prior tier decisions and notes. An identity, roster, or cohort
selection change hides outdated exports until the pack is rebuilt.

The existing scrape queue requests new games. A scrape does not recalculate
rankings; wait for scraping and the rankings run to finish, then rebuild the pack.
The sheet displays its prediction date and the oldest known selected-team
ratings date. Missing dates are labeled unknown.

## What a tier means

Tiers identify groups whose teams are projected to play competitive games.
They have variable sizes and are advisory: they are not fixed six-team blocks,
finished pool assignments, or a guarantee about any result.

Seeding uses the website Compare predictor, calibration files, team inputs,
and 365-day scored-game window. It does not convert the displayed
PowerScore difference into a separate estimate. PowerScore is displayed on the
website's 0–100 scale, already adjusts for age, and orders teams within each
tier, including younger teams playing up. A state rank still describes the
team's own PitchRank age and gender cohort.

The default placement preferences require **every pairing** within a suggested
tier to have both:

- At most **2.0 goals** of absolute expected goal margin.
- At most a **30% chance of a 4+ goal margin**, from Compare's score distribution.

These are adjustable operator preferences, not empirically validated universal
cutoffs. Equal expected scores can still have a high blowout risk. A group average
cannot conceal a badly overmatched team, and a chain of similar neighbors cannot
join incompatible endpoints.

PowerScore sets the suggested seed order. Compare evaluates every pair, and a
deterministic partition finds the fewest contiguous safe groups in that order.
Among equally small safe partitions, it places boundaries at the largest
PowerScore breaks; lower within-group matchup risk breaks any remaining tie.
This means Compare can split the rankings into safer flights but cannot silently
place a lower-PowerScore team above a higher-PowerScore team. A singleton is
explicitly labeled as having no peer in that tier. A **Boundary option** can only be the last
suggested seed in the stronger tier or the first suggested seed in the weaker
tier. It appears only when moving that one team leaves both resulting tiers
within the matchup limits; interior teams are never suggested for movement.
Cross-tier reversals produce review warnings.
"Clear separation" requires directional evidence across the tier boundary:
at least 75% of upper/lower pairings favor the upper tier, at least half exceed
the grouping limits, and their average signed edge reaches half the margin limit.

Any matched, active team with a valid PowerScore is seeded, including teams with
a provisional score or little recent history. Unresolved, duplicate-identity,
inactive, missing-score, wrong-gender, and older-than-cohort teams stay in
**Placement review**. Younger teams may play up. Low prediction confidence alone
does not exclude a team: close matchups can naturally have an uncertain winner.

The customer PDF uses the registered tournament name as the primary name. When
PitchRank's matched name differs, it appears beneath it for verification. A
**Plays up** badge identifies starred registrations, and requested-flight or
listed-division context appears beside the PowerScore when available. Duplicate
PitchRank matches remain visible and carry a review warning.

The customer PDF leads with the recommended tier sizes and three direct steps:
build flights from the same tier, seed each tier from top to bottom, and use a
Boundary option when pool sizes do not fit. Technical thresholds, probabilities,
and predictor diagnostics remain in the operator workflow. The PDF translates
them into placement actions and labels incomplete teams **Manual placement
needed** so a director can identify the recommended groups at a glance.

## Implementation and checks

- `seeding_predictions.py` invokes `run-seeding-predictions.ts`, which shares
  `matchPredictionService.ts` and `matchPredictor.ts` with Compare. Failures abort
  the new snapshot; there is no approximate fallback.
- `seeding_pack.py` freezes and validates cohort/entrant/pair coverage, predictor
  identity, dates, and roster fingerprint. `seeding_tiers.py` applies the grouping
  policy. `seeding_run_store.py` saves atomically.
- `seeding_sheet.py` renders one HTML source for preview and PDF.
  `seeding_pdf.py` uses the headless Playwright worker; fonts are embedded and
  remote requests and document scripts are blocked during PDF rendering.
- Relevant regression suites: `test_seeding_tiers.py`, `test_seeding_pack.py`,
  `test_seeding_predictions.py`, `test_seeding_intake_ui.py`,
  `test_seeding_run_store.py`, `test_seeding_sheet.py`, `test_seeding_pdf.py`,
  and the frontend `seedingPredictions.test.ts` parity checks.

This workflow does not assign final pools, enforce club/coach/travel constraints,
or change rankings. Those decisions remain with the operator and director.
