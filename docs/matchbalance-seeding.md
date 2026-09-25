# MatchBalance Seeding sheets

Seeding is an internal service workflow. The operator prepares director sheets and
sends them to tournament directors. Directors use them to place teams in competitive
divisions and pools. Each age/gender cohort gets its own sheet. Sell a complete event
pack or a pack containing only the requested cohorts.

## Prepare and deliver a pack

1. Run `python -m streamlit run tournament_intake.py` and select **Seeding**.
   Python requirements, Node.js, and `npm ci --prefix frontend` must be installed.
   Configure the existing PitchRank Supabase environment variables. PDF export
   uses installed Edge/Chrome or Playwright Chromium; if needed, run
   `npx --prefix frontend playwright install chromium`.
2. Fill in **Run name (for saving)**. Naming the run is what saves it; reopen an
   earlier one from **Open a saved run**.
3. Under **Import or refresh teams**, choose a **Roster source**:
   - **Paste team list**: a tab-separated Club, Team, State list with headings such
     as `Boys U14`. An optional fourth column holds the team's requested flight.
     The heading decides a team's cohort. A line the parser cannot place stays
     visible for correction.
   - **GotSport event**: paste the event URL and **Scrape the whole U10+ event**.
     A captured division's name is kept as its listed division; it is not treated
     as a request from the team. A two-division cost estimate is only a sample;
     finish the whole-event capture before selling a complete tournament pack.

   Confirm the imported team and cohort counts against the director's list, and
   confirm the roster is complete when asked.
4. Resolve team identities under **Review teams**. A unique same-name match still
   needs review when the submitted and matched club or state conflict, and two
   registrations resolving to the same PitchRank team are flagged. Use the GotSport
   link, id, or `team_id_master` box, **Mark team not found in PitchRank**, or
   **Correct cohort or input**. Every accepted row stays in the pack.
5. Under **Competitive seeding sheets**, choose **All imported cohorts** for the
   event pack or **Choose cohorts** for an à la carte order, then click
   **Build seeding sheets**. This reads current ratings and compares every pairing
   within each selected cohort.
6. In **Review seed order and director notes**, check each cohort's seed order and
   write any **Director notes (included in PDF and Excel)**. Where the page asks
   for it, work through **Placement checks — internal** and click
   **Mark placement review complete**. Editing that cohort's notes afterwards
   reopens the review.
7. Download the director files: **Download Excel workbook**, **Generate PDF pack**
   then **Download PDF pack**, or **Download printable HTML**.
   **Download all selected teams as CSV** gives the editable roster.

### Delivery status

The pack is a draft while any of these holds:

- The roster is not confirmed complete.
- A selected team still needs a manual match, a lookup, or a cohort decision, or a
  team of uncertain cohort could belong to a selected one.
- A team is marked **Data review required**.
- A cohort's placement review is pending.
- The analysis failed.

A draft carries "DRAFT — review needed" in the director files' title, and the CSV's
Delivery status column says "Draft — review needed". Otherwise the page reads
"Delivery status: roster assessed".

## What the director sheet shows

- **Suggested seed order.** Seeded teams appear in published PowerScore order, on
  the website's 0–100 scale. PowerScore already adjusts for age, so a younger team
  playing up can be compared directly. State rank is the team's rank within its
  own PitchRank age and gender group.
- **Score steps.** At most three rows are marked where a larger score gap is
  backed by the matchups around it. A gap counts when it is at least the greater
  of 2 points or three times the median of the other adjacent gaps, and every
  three-, four-, and five-team window across it favours the upper side in at
  least 75% of pairings with a positive average advantage. A step within two
  seeds of either end becomes a note instead. Score steps do not assign divisions
  or pools, and they are display heuristics, not calibrated outcome guarantees.
- **Unseeded teams.** Accepted teams that PitchRank cannot place stay on the
  sheet without a seed, marked **Not found in PitchRank**, **No current rating**,
  or **Data review required**. Nothing is guessed for them.
- **Team names.** The registered tournament name leads. When PitchRank's matched
  name differs, it appears beneath it. A starred registration shows **Plays up**,
  or **Plays up from U#** when the team's ranked age is younger. Requested flight
  and listed division appear with the score when known.
- **Limited history.** A seeded team with few ranked games is flagged so its score
  is treated as a starting point.
- **Director notes** close each cohort's sheet.

The PDF starts each cohort on a fresh Letter page and repeats table headings. The
Excel workbook has one sheet per cohort with yellow Final division, Pool, Final
seed and Director notes columns for the director to fill in.

**Analysis details** (operator only) shows the boundary windows, close matchup
ranges, and the 2.0 expected-goal and 30% four-goal-risk diagnostics. Placement
checks flag a lower seed favoured by at least one expected goal.

## Saving and recovery

A named run saves to `reports/seeding/<run-name>/seeding_run.json`: roster, team
fixes, cohort decisions, and the pack with its prediction snapshot and rating date.
Saves archive the previous file under `history/`; automatic progress checkpoints
do not. `MATCHBALANCE_SEEDING_DIR` moves the store, and a relative value resolves
against the primary checkout that every worktree shares.

Reopening a run uses its saved snapshot. **Build seeding sheets** refreshes it and
keeps every cohort's director notes and placement reviews, including cohorts not
selected this time. A review only counts while the evidence it approved is
unchanged. A change to team matches, the roster, or the cohort selection hides the
director files until the pack is rebuilt; the CSV stays available.

A finished build is written to `pack_recovery.json` beside the run before anything
can interrupt it. If a click cut it off, the page offers **Restore the interrupted
build** or **Discard it** on the next interaction. Restore keeps any notes saved
while the build ran, and replaces the saved pack only once its sheets build and the
save succeeds.

## Refreshing ratings

**Refresh team data (optional)** queues matched teams for a scrape of their latest
results. A scrape does not recalculate rankings: wait for the scrapes and the next
rankings run, then build the sheets again. Each sheet shows its prediction date and
ratings date; a missing date reads unknown.

## Implementation and checks

- `seeding_predictions.py` invokes `run-seeding-predictions.ts`, which shares
  `matchPredictionService.ts` and `matchPredictor.ts` with Compare. Failures abort
  the new snapshot; there is no approximate fallback.
- `seeding_pack.py` freezes and validates cohort, entrant and pair coverage,
  predictor identity, dates, and the roster fingerprint. `seeding_tiers.py` builds
  the seed-order analysis. `seeding_run_store.py` saves the run and the recovery
  file atomically.
- `seeding_content.py` holds the director-facing text, `seeding_sheet.py` renders
  one HTML source for preview and PDF, and `seeding_workbook.py` builds the Excel
  file. `seeding_pdf.py` uses the headless Playwright worker; fonts are embedded and
  remote requests and document scripts are blocked during PDF rendering.
- Relevant regression suites: `test_seeding_tiers.py`, `test_seeding_pack.py`,
  `test_seeding_predictions.py`, `test_seeding_intake_ui.py`,
  `test_seeding_run_store.py`, `test_seeding_sheet.py`, `test_seeding_workbook.py`,
  `test_seeding_pdf.py`, and the frontend `seedingPredictions.test.ts` parity checks.

This workflow does not assign final pools, enforce club/coach/travel constraints,
or change rankings. Those decisions remain with the operator and director.
