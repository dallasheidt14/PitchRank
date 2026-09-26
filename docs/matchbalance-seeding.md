# MatchBalance Seeding sheets

Seeding is an internal service workflow: the operator prepares a numbered seed
order for each tournament age/gender cohort, reviews any evidence that challenges
that order, and sends PDF or Excel reference sheets to the tournament director.
The sheets support final division and pool placement; they do not assign either
one automatically. Sell a complete event pack or only the requested cohorts.

## Prepare and deliver a pack

1. **Import the accepted teams.** Run
   `python -m streamlit run tournament_intake.py`, select **Seeding**, and name or
   reopen the run. Capture the complete GotSport U10+ event or paste the accepted
   teams under their tournament age/gender headings. The heading is the cohort
   the tournament supplied; Seeding does not second-guess it from the team name.
   Pasted rows may include an optional fourth column for a requested flight. A
   captured event's published division is kept only as listed context. Confirm
   the imported counts against the director's list; a two-division probe is not
   a complete event.
2. **Match the teams to PitchRank.** Review the proposed database identity for
   each registration. A same-name result still needs attention when the club or
   state conflicts, and duplicate registrations resolving to one PitchRank team
   are flagged. Every accepted row is retained. Unmatched, inactive, or otherwise
   ineligible rows remain visible for placement review instead of disappearing.
3. **Build and review the seed order.** Under **Competitive seeding sheets**,
   choose all imported cohorts or a subset and click **Build seeding sheets**.
   The build reads current ratings and runs the canonical Compare predictor for
   every eligible pairing. Review the numbered PowerScore order, supported score
   steps, limited-history labels, placement checks, local-consensus proposals,
   and director notes. A proposal asks for operator review; it does not silently
   move the team. Complete any required placement review before delivery.
4. **Export the director pack.** Click **Generate PDF pack**, preview it, and
   download the PDF. The same reviewed content is available as an Excel workbook
   and printable HTML. Each cohort starts on a fresh Letter page; long lists
   continue with repeated table headings.

Python requirements, Node.js, and `npm ci --prefix frontend` must be installed.
Configure the existing PitchRank Supabase environment variables. PDF export uses
installed Edge/Chrome or Playwright Chromium; if needed, run
`npx --prefix frontend playwright install chromium`.

Team matches, cohort choices, director notes, placement-review state, policy,
predictions, and rating dates are saved in
`reports/seeding/<event-name>/seeding_run.json`. Reopening a run uses its saved
prediction snapshot. **Build seeding sheets** refreshes ratings and predictions
while preserving the independent roster choices and director notes. A completed
placement review counts only while its evidence fingerprint still matches. An
identity, roster, or cohort-selection change hides outdated exports until the
pack is rebuilt.

The existing scrape queue requests new games. A scrape does not recalculate
rankings; wait for scraping and the rankings run to finish, then rebuild the pack.
The sheet displays its prediction date and the oldest known selected-team
ratings date. Missing dates are labeled unknown.

## How the seed order is built

Seeding uses the website Compare predictor, calibration files, team inputs,
and 365-day scored-game window. It does not convert the displayed
PowerScore difference into a separate estimate. PowerScore is displayed on the
website's 0–100 scale, already adjusts for age, and establishes the starting seed
order, including for younger teams playing up. A state rank still describes the
team's own PitchRank age and gender cohort.

Compare then adds evidence without replacing that starting order:

- A **score step** appears only when an adjacent PowerScore gap is conspicuous
  and every available three-, four-, and five-team window supports the stronger
  side in at least 75% of its cross-line matchups. A score step is a strength
  marker, not an automatic division or pool boundary.
- A **very-close range** identifies nearby seeds for which every pairing is
  competitive enough and every adjacent pairing meets the stricter very-close
  limit. Overlapping ranges are not combined into a larger claim of equal
  strength.
- A **placement check** starts when Compare materially favors a lower
  PowerScore seed over a higher one. Smaller reversals remain visible only in
  diagnostics.

The default policy keeps three separate decisions:

- **Competitive enough:** no more than **2.0 expected goals** of absolute
  difference and no more than a **30% chance of a 4+ goal margin**. This asks
  whether teams can reasonably belong together.
- **Very close:** adjacent teams are within **1.0 expected goal**, in addition
  to every pairing passing the competitive-enough limits. This is a stronger
  label than merely being suitable for the same group.
- **Material reversal:** Compare favors the lower seed by at least **1.0 expected
  goal** before the matchup can enter placement review.

The three decisions use separate settings. Changing the
competitive-enough limit does not automatically change the very-close or
material-reversal thresholds. They are operator policy, not empirically
validated universal cutoffs. Equal expected scores can still carry meaningful
blowout risk, which is why the probability limit remains a separate check.

## How local-consensus review works

A direct Compare reversal is only the trigger. It earns a move proposal only if
all of these safeguards also pass:

1. Both teams have established ranked history.
2. The lower seed has the stronger profile against a strict majority of the same
   nearby opponents, with a positive average profile advantage.
3. That conclusion remains true in every available five-, six-, and seven-team
   neighborhood and when each neighboring opponent is removed one at a time.
4. The proposed change moves no more than two seed positions from the original
   PowerScore order.
5. A two-position move is separately supported over every seed it would cross.

Passing those checks produces a **PowerScore-anchored local-consensus proposal**
for the operator. It never rewrites the sheet automatically. The original seed,
proposed seed, direct Compare advantage, shared-opponent support, tested windows,
and evidence limitations remain visible in the internal placement review. Failed
proposals remain explainable diagnostics with the blocking reason.

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

The customer PDF leads with the numbered seed order and supported score-step
markers. Technical thresholds, probabilities, local-consensus diagnostics, and
move proposals remain in the operator workflow. The PDF labels incomplete teams
**Manual placement needed** so the director can see which registrations require
separate handling.

## Implementation and checks

- `seeding_predictions.py` invokes `run-seeding-predictions.ts`, which shares
  `matchPredictionService.ts` and `matchPredictor.ts` with Compare. Failures abort
  the new snapshot; there is no approximate fallback.
- `seeding_pack.py` freezes and validates cohort/entrant/pair coverage, predictor
  identity, dates, policy, and roster fingerprint. `seeding_tiers.py` builds the
  PowerScore order, strength observations, and local-consensus review evidence.
  `seeding_run_store.py` saves atomically.
- `seeding_sheet.py` renders one HTML source for preview and PDF.
  `seeding_pdf.py` uses the headless Playwright worker; fonts are embedded and
  remote requests and document scripts are blocked during PDF rendering.
- Relevant regression suites: `test_seeding_tiers.py`, `test_seeding_pack.py`,
  `test_seeding_predictions.py`, `test_seeding_intake_ui.py`,
  `test_seeding_run_store.py`, `test_seeding_sheet.py`, `test_seeding_pdf.py`,
  and the frontend `seedingPredictions.test.ts` parity checks.

This workflow does not assign final pools, enforce club/coach/travel constraints,
or change rankings. Those decisions remain with the operator and director.
