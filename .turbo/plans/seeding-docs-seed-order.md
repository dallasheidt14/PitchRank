---
status: approved
---

# Plan: Describe the Seeding sheet MatchBalance actually ships (seed order, score steps, unseeded teams)

## Context

Line numbers refer to origin/main 35103130c.

The 2026-09-23 audit (K1) found that every description of the Seeding sheet still describes the retired tier product. #1177 (2026-09-19) replaced it with a PowerScore seed order, "Score step" markers and an "Unseeded teams" table. The owner answered K1 on 2026-09-24: the tier sheet is retired for good. They chose to split fix 8 into two PRs, words first:

- **8a, this plan.** Every description in words: the operator guide, the spec, runtime strings, and the public landing copy.
- **8b, next.** A committed script that renders the public sample PDF/PNG and the design workbook/PNGs from a synthetic run, plus a renderer-hash test (audit O1, IMP-251).

The stale descriptions, confirmed by a read-only survey of the current code:

- `docs/matchbalance-seeding.md`. It describes "Build matchup tiers", an editable Tier column, "Save tier decisions", "Restore suggested tiers", adjustable limits, a three-condition "Clear separation" rule, a PDF that "leads with recommended tier sizes", "Manual placement needed", and "rebuild replaces … notes". None of these controls or behaviours exist. The guide never mentions the Excel, CSV or HTML downloads, director notes, placement review, draft status, or the interrupted-build restore.
- `.turbo/specs/matchbalance-seeding-intake.md:4`. It reads `Status: draft, awaiting review` and still says seeding intake is disabled.
- Runtime strings:
  - `frontend/lib/seedingPredictions.ts:161`. The reason is "… Then rebuild matchup tiers. Your team match is saved." It becomes a Data review reason on the sheet.
  - `src/tournaments/seeding_pack.py:311-312`. It reads "The roster or team matches changed. Rebuild seeding sheets; Rebuild matchup tiers are replaced as part of that action before exporting." The sentence is garbled, and it is shown to the operator.
  - `tournament_intake.py:4894`. The docstring reads "Review matchup tiers and generate the selected cohort PDF pack."
- Public landing copy, `frontend/app/matchbalance/page.tsx`:
  - `:38` sells "teams grouped into tiers of the closest projected matchups, with close calls and teams that need manual placement flagged".
  - `:74` says unrated teams are "marked for manual placement".

The current sheet (survey):

- Seed order is by PowerScore.
- Up to three "Score step" markers appear. A gap qualifies at ≥ max(2 points, 3 × the median of the other adjacent gaps), and every available 3-, 4- and 5-team window across it must favour the upper side in ≥75% of pairings with a positive average (`seeding_tiers.py:463-520`). Steps within two seeds of either end become notes, not markers.
- An "Unseeded teams" table lists teams whose status is Not found in PitchRank, No current rating, or Data review required.
- Director notes are included in the PDF and Excel.
- Downloads: Excel workbook, PDF pack, printable HTML, and the all-teams CSV.

Out of scope, and unchanged here:

- The tier-era helpers in `seeding_sheet.py` (`_tier_options`, `_tier_tables`, `_director_guidance`) have no callers. They belong to the audit's dead-code PR (X1–X7).
- The sample PDF/PNG and the design workbook/PNGs belong to 8b. Their README prose already matches the workbook code.
- The widget key `_seeding_build_tiers` is not visible, and renaming it would reset the widget for open sessions.

## Implementation Steps

1. **Rewrite `docs/matchbalance-seeding.md`** as a current operator guide. Keep the prerequisites paragraph (Streamlit command, Node, `npm ci`, PDF browser). Sections:
   - **Prepare and deliver a pack.** Steps with the exact UI labels:
     - Name the run, and open a saved run.
     - Import: paste with headings, or capture the GotSport event (a probe is only a sample).
     - Confirm counts.
     - Resolve identities in Review teams.
     - Choose Sheet pack.
     - Build seeding sheets.
     - Review seed order and director notes.
     - Mark placement review complete where it is asked for.
     - Download the Excel workbook, PDF pack (Generate PDF pack first), printable HTML, or the all-teams CSV.
   - **Delivery status.** The draft rules from `seeding_intake_ui.py:436-441`, in plain words. A draft carries "DRAFT — review needed" on every export.
   - **What the sheet shows.** In plain words:
     - seed order;
     - score steps, stating the rule;
     - Unseeded teams and their three statuses;
     - Plays up;
     - PitchRank name lines;
     - Requested/Listed context;
     - Limited history;
     - director notes.
     - State that score steps do not assign divisions or pools, as the director legend says.
   - **Saving and recovery.** Cover:
     - the run file and history archive;
     - MATCHBALANCE_SEEDING_DIR;
     - a rebuild keeps every cohort's director notes;
     - an interrupted build is offered back (Restore / Discard);
     - which changes hide the exports until a rebuild.
   - **Refreshing ratings.** The optional Refresh team data expander, then rankings, then a rebuild.
   - **Implementation and checks.** Keep the existing module list and correct it:
     - `seeding_tiers.py` builds the seed-order analysis;
     - add `seeding_content.py` and `seeding_workbook.py`;
     - the regression suite list gains `test_seeding_workbook.py` and `test_seeding_content.py`, if they exist (grep before listing).
2. **Mark the spec superseded.** Change `.turbo/specs/matchbalance-seeding-intake.md:4` to `- **Status**: superseded — the shipped workflow is documented in docs/matchbalance-seeding.md` and leave the body as the historical design.
3. **Fix the runtime strings:**
   - `seedingPredictions.ts:161`: "… Then rebuild the seeding sheets. Your team match is saved."
   - `seeding_pack.py:311-312`: "The roster or team matches changed. Build seeding sheets again before exporting."
   - Update the two `pytest.raises(..., match="Rebuild matchup tiers")` pins in `tests/unit/test_seeding_pack.py:322,331` to the new literal.
   - Add an assertion pinning the new `seedingPredictions.ts` reason if a test already covers that branch (grep `seedingPredictions.test.ts`).
   - `tournament_intake.py:4894`: the docstring becomes "Review the seed order and generate the selected cohorts' director sheets."
4. **Landing copy (`page.tsx`), wording for owner approval:**
   - `:38` body: "Each covered age group and gender gets its own sheet: teams in a suggested seed order by PitchRank score, with the larger score gaps marked and any team PitchRank can't place listed separately for your review."
   - `:74` answer: "They stay on the sheet in their own section, without a seed. PitchRank has no current rank for these teams, so nothing is guessed for them; you place them using recent results, prior division or club input."
   - `:41-43`, the "An editable team file" deliverable, stays as is, because this plan does not add the Excel workbook to what is sold.
   - Run `npm run generate-llms` in case the page feeds `public/llms.txt`, and commit any change.

## As built (2026-09-24)

- **`frontend/lib/seedingPredictions.ts` is unchanged.** It is hashed into `seeding_predictor_sha256`, so rewording its metadata-conflict reason would make every saved run report a predictor update and need a rebuild. The owner chose to log it (IMP-278) and change it with the next real predictor update.
- **The operator guide leaves out the workbook's "diagnostics stay out" claim** from the design README, since the PDF was not checked for it.

## Verification

- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
- `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`
- `cd frontend && npx eslint . && npx prettier --check . && npm run typecheck && npm run test && npm run generate-llms && git diff --exit-code public/llms.txt`
- Check every UI label quoted in the rewritten guide against the code with `git grep -F` on the exact string.
- `git grep -n -i "tier"` over the touched files. Only intentional mentions may remain, such as a module name.
