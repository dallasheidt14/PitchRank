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
   saved run, or capture the GotSport event. A two-division probe is only a sample;
   finish the whole-event capture before selling a complete tournament pack.
   Confirm the imported team and cohort counts against the director's list.
3. Resolve team identities. Every accepted row stays in the sheet, including
   unranked ages and teams whose identity or match history needs review.
4. Under **Competitive seeding sheets**, select **All imported cohorts** for the
   event pack or **Choose cohorts** for an à la carte order. Click
   **Build matchup tiers**. This reads current data and compares every eligible
   pairing within each selected cohort.
5. Review the tier sizes, boundary explanations, placement alternatives, and
   warnings. Edit the Tier column and **Save tier decisions** when tournament
   knowledge calls for an adjustment. Add placement notes for the director.
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
website's 0–100 scale and orders teams within each tier.

The default placement preferences require **every pairing** within a suggested
tier to have both:

- At most **2.0 goals** of absolute expected goal margin.
- At most a **30% chance of a 4+ goal margin**, from Compare's score distribution.

These are adjustable operator preferences, not empirically validated universal
cutoffs. Equal expected scores can still have a high blowout risk. A group average
cannot conceal a badly overmatched team, and a chain of similar neighbors cannot
join incompatible endpoints.

Teams are ordered by average predicted signed margin against the cohort. A
deterministic partition finds the fewest contiguous safe groups, then prefers
lower within-group risk. A singleton is explicitly labeled as having no peer in
that tier. Borderline placement notes identify adjacent tiers a team also fits
without creating an unsafe pairing. Cross-tier reversals produce review warnings.
"Clear separation" requires directional evidence across the tier boundary:
at least 75% of upper/lower pairings favor the upper tier, at least half exceed
the grouping limits, and their average signed edge reaches half the margin limit.

Unresolved, duplicate-identity, unranked/inactive, wrong-gender, older-than-cohort,
and limited-history teams stay in **Placement review**. The history floor is
three scored games in both the published ranking count and the history actually
consumed by Compare under the canonical team ID.
Younger teams may play up. Low prediction confidence alone does not exclude a
team: close matchups can naturally have an uncertain winner.

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
