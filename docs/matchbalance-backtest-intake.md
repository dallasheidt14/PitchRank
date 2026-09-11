# MatchBalance completed-tournament intake

Backtest captures a completed GotSport event for later analysis. The Seeding tab remains the separate upcoming-tournament workflow. This stage does not reseed, run comparisons, or write tournament teams to the PitchRank database.

## Operator workflow

1. Open **Backtest** and enter the completed event URL. The existing probe and full-walk controls show their scrape cost estimates.
2. Review the tournament name, dates when published, total teams, and teams by tournament cohort and gender. Counts follow the **entered division**: a U11 squad entered in U12 counts in U12. Current PitchRank age never changes these totals. Partial captures are identified as partial.
3. Inspect every discovered division, including unreadable or unvisited divisions. Expand a division to inspect published pools, team membership, final standings, fixtures, participant or advancement-slot labels, results, and source links. Final standings are never treated as original seeds. Regulation and shootout scores remain separate.
4. Inspect all team matches or filter to those needing review. Published GotSport team IDs can resolve automatically. Historical name matches are suggestions until confirmed. Any existing match can be changed or cleared; automatic matching cannot undo a saved operator decision.
5. Record published format, advancement, and tiebreaker notes with a source URL. Mark each division checked after verifying its source. A changed structure invalidates that division's saved check.
6. **Save Backtest intake** to resume later, or download the JSON bundle containing the capture, totals, displayed matches, saved links, and division reviews.

## Counting and evidence limits

The total counts distinct event registration IDs, plus separately identified source entries whose registration IDs are missing. An event registration appearing in two cohorts counts once in the overall total and once in each cohort. The interface explains when cohort subtotals exceed the unique total.

Missing-ID teams remain visible and require identity review for possible duplicates. Unknown cohort or gender stays unknown. A readable page is evidence of capture, not proof that unpublished advancement rules were reconstructed. The intake preserves published rules links and operator notes; it does not infer the tournament's original seeds or invent a bracket graph.

## Local artifacts

Backtest data lives under `reports/gotsport__<event_id>__<season-or-unknown>/intake/`:

- `last_walk.json`: canonical paid capture written before matching, recoverable without another scrape.
- `event_intake.json`: saved capture, matching outcomes, and division reviews.
- `event_links.json`: editable event team links and persistent clear decisions.

An existing event directory is reused. Locks and atomic writes protect local updates. Recovery and saved captures reject replacements that discard captured entrants, divisions, pool members, fixtures, or table readability. Event IDs and capture generations prevent an interrupted scrape or late matching result from mixing two events.

Fixture protection checks the captured content as well as row identity: populated results, participant IDs, labels, dates, and source details cannot silently become missing on a repeat walk. Unknown fields may gain evidence, and an identified game may carry corrected nonempty source values.

Repeat scrapes retain division notes and rules links. Checks remain valid only for the same structure. Review saves merge the fields an operator actually edited against the saved version under the event lock; conflicting edits require reopening the saved intake. Intentional clearing and unchecking remain available.

Generated Backtest capture files and locks are ignored by Git and remain in these local event folders. Application code stays in `src/tournaments/`, tests in `tests/unit/`, workflow documentation in `docs/`, and development review notes in `.turbo/reports/`.

The CLI's `--completed-event` option selects the same complete-event capture and recovery path. Its existing `--force` option explicitly permits replacing the selected output. Default CLI and Seeding behavior stay unchanged.

## Validation

Offline parser, storage, matching, capture, and Streamlit interaction tests cover play-ups, unranked divisions, missing IDs, unresolved matches, manual replacement/clear, historical-name review, source structure round trips, interrupted publication, concurrent link updates, and partial-capture preservation. A newly scraped production event has not been used as end-to-end acceptance evidence for this change.

Validated 2026-09-11: the repository's full Python gate passed with **4,649 passed and 12 skipped** (`tests/test_enhanced_pipeline.py` excluded as in CI). The fixture-preservation suite also passed all 36 cases, including two additional regressions completed after full-suite collection. Backend and changed-test Ruff checks passed. Windows validation used Git Bash on the test process's PATH and an isolated temporary directory outside the repository.
