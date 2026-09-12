# MatchBalance completed-tournament intake

Backtest captures a completed GotSport event for later analysis. The Seeding tab remains the separate upcoming-tournament workflow. The intake itself does not reseed or write tournament teams to the PitchRank database. The downstream command-line tools can evaluate an original arrangement and a proposed arrangement after the capture is reviewed.

MatchBalance has three distinct product workflows:

- **Backtest** is the sales proof. It takes a completed tournament's exact entrants and verified structure, reseeds those teams using historical competitive strength, and shows how the projected matchup quality would have changed.
- **Seeding Tab** is the self-service ranking product. It gives a director a ranked list of accepted teams so the director can seed the tournament manually.
- **Auto Seeder** is the future premium product. It will create the tournament assignments and apply operational constraints such as club separation, shared coaches, geography, travel, and rematches.

## Operator workflow

1. Open **Backtest** and enter the completed event URL. **Scrape the whole event** is the primary action; the priced two-division check is optional.
2. Work through **Overview**, **Teams**, **Structure**, and **Capture Details**. The header keeps capture, matching, and division-review progress separate, and Save progress remains available from every section.
3. Review the tournament name, dates when published, total teams, and teams by tournament cohort and gender. Counts follow the **entered division**: a U11 squad entered in U12 counts in U12. Current PitchRank age never changes these totals. Combined brackets stay combined.
   The **Actual tournament results** summary shows games counted, total and average goal margin, and blowout count and rate. Expand the cohort and division breakdowns to inspect where those results occurred.
4. Review one division at a time. Filter to unchecked or attention-needed divisions and use **Next unchecked**. Inspect pools, team membership, final standings, fixtures, participant or advancement-slot labels, results, and source links. Select the verified replay format before checking the division. Final standings are never treated as original seeds.
5. Start team review with **Needs review**. Filter by division, cohort, gender, or issue; search PitchRank by current name/club without forcing the historical bracket age. A team may be linked, cleared, or explicitly marked not found. Distinct registrations resolving to one canonical team require correction or a noted acknowledgement.
6. Record published format, advancement, and tiebreaker notes with a source URL. A sourced cohort correction changes displayed totals without replacing the captured label and resets that division's check.
7. **Save progress** to resume later, or download the JSON bundle containing the capture, totals, displayed matches, saved links, and division reviews.

## Capture verification and recovery

The Capture Details section condenses scraper messages behind one expander. **Verify division list** buys only landing-page reads, up to four, and accepts the list only after the complete observed union repeats twice. It never shrinks a saved capture. If new or unreadable divisions remain, the targeted action fetches only those division pages and reuses every previously observed team-page result, including a prior readable page with no rankings ID.

During a full Backtest capture, progress is emitted on Streamlit's script thread for division discovery, division pages, GotSport ID pages, local recovery save, and read-only database matching. Results remain in source order even when pages finish out of order.

Labels such as `U13 - 5 Team` ignore the format's team count when deriving the tournament cohort. Older saved captures receive this interpretation locally on load. Explicit `U10/U11` and `U17/U18` brackets remain combined; disjoint header and division ages remain attention items until an operator records a sourced interpretation.

## Counting and evidence limits

The total counts distinct event registration IDs, plus separately identified source entries whose registration IDs are missing. An event registration appearing in two cohorts counts once in the overall total and once in each cohort. The interface explains when cohort subtotals exceed the unique total.

Missing-ID teams remain visible and require identity review for possible duplicates. Unknown cohort or gender stays unknown. A readable page is evidence of capture, not proof that unpublished advancement rules were reconstructed. The intake preserves published rules links and operator notes; it does not infer the tournament's original seeds or invent a bracket graph.

### Actual result totals

Goal margin is `abs(home_score - away_score)` using the published scores excluding shootouts. A 5–1 game contributes 4; a draw contributes 0 even if a shootout decides the winner. The total adds one margin per counted game. The average divides that total by the number of counted games, so larger divisions contribute proportionally. A **blowout is a margin of 4 or more goals**; its rate is the blowout count divided by the counted games. Rates and averages are unavailable when no games can be counted.

Both scores must be nonnegative integers. Explicit unplayed, cancelled, postponed, forfeited, unrecognized, and missing-score results are excluded. Valid score pairs from legacy captures whose result status was not retained remain usable, with a visible legacy-status count. The source does not separately identify extra-time goals.

Provider match IDs identify repeated listings across the event; printed match numbers are scoped to their division. Conflicting results or division assignments are excluded rather than choosing a version. Fixtures with neither a provider match ID nor a printed number are excluded because duplicate listings cannot be ruled out. Coverage, duplicates, exclusions, and partial captures are displayed alongside the totals. A conflicting cross-division fixture appears as excluded in each affected breakdown, so those exclusion counts can overlap.

Results use the tournament's entered cohort and gender. They are calculated directly from the saved fixture evidence and included under `tournament_totals.results` in the downloaded JSON. Loading a saved capture with scores makes these numbers available without another scrape; captures with missing fixtures or scores still need that evidence collected.

Observed results remain a descriptive baseline. They are never compared directly with a modeled proposal because that would mix realized scores with predictions. Downstream summaries instead evaluate the original fixture pairs and proposed fixture pairs through the same matchup model. A reported seeding delta therefore measures only the arrangement change. Comparison is unavailable when either arrangement cannot be resolved or when their matchup counts differ. Reversing home and away order does not change the arrangement identity, and identical arrangements produce exact zero deltas.

Each modeled arrangement reports 95% normal-approximation intervals. Probability intervals use each matchup's predicted Bernoulli variance. The goal-margin interval describes variation across scheduled matchup projections; it is not a claim that the rating model itself is perfectly calibrated. Delta intervals conservatively treat the two arrangement summaries as independent unless the arrangements are identical, in which case delta uncertainty is exactly zero.

## Downstream optimizer safeguards

The current command-line backtest and seeding runners validate their inputs before assigning teams. Every tournament entrant needs a unique, nonempty registration ID and a finite PowerScore from 0 through 1. Division names must be unique and nonempty, division and pool capacities must be positive whole numbers, and the requested slots must equal the supplied entrants. Numeric strings remain accepted in JSON input for compatibility. Missing ratings stop the run instead of silently removing a team. Completed output is checked to confirm that every entrant appears exactly once and that each pool retains its requested capacity.

A reviewed intake can be converted directly with `python scripts/backtest_reviewed_intake.py --intake-json <event_intake.json> --point-in-time-model-artifact <model.pkl>`. This adapter uses the captured pool members, source results, and saved `EventLinks` decisions. Only direct GotSport-ID matches and explicit operator choices are eligible; exact-name suggestions, cleared matches, and not-found decisions remain review gaps. Both canonical local snapshots and downloaded intake bundles carry these decisions. Every included division must be checked and assigned one supported replay format: `ROUND_ROBIN`, `F_ONLY`, `SF_F`, or `SF_F_3P`. Pool sizes, pool-game counts, playoff-game counts, and total fixture counts must agree. Unsupported structures stop with an evidence error; game counts never select or guess a format. The legacy event runner applies the same format and pool-shape validation before it marks a cohort runnable.

Backtest strength comes from `prediction_feature_history` before the event start. The snapshot's `created_at` and any `last_calculated` timestamp must also precede the event cutoff, proving the stored features were available at the time; reconstructed later backfills and recalculations are rejected. During model training, each historical game can use only snapshots created and calculated before that game's date. Current `rankings_full`, future or same-day snapshots, synthesized snapshots, and snapshots without provenance are rejected. Every reviewed request requires the normalized tournament start date as its cutoff. Historical game context starts at the configured lookback and ends before that cutoff. Point-in-time model artifacts must declare a `model_data_end_date` before the event; older or future-trained artifacts stop the run. Train an eligible artifact with `train_point_in_time_match_model.py --max-game-date <event-date>`, where the bound is exclusive and the default lookback is measured backward from that historical date. Each cohort output includes `historical_inputs.json`, which freezes the matched IDs, source and tournament cohorts, strength/confidence features, snapshot and creation dates, cutoff, model training metadata, model artifact SHA-256, and an overall input digest.

Historical feature rows are immutable through the ranking writer: a repeated team/date snapshot keeps the first stored values instead of rewriting them under the original `created_at`. Historical snapshot and game queries include IDs that were deprecated by a later merge, then resolve those immutable rows to the current canonical identity. The manifest retains each snapshot's stored source team ID. Historical game context also requires both the played date and the database `created_at` to precede the event cutoff. The manifest freezes those eligible games and every related-team snapshot used for common-opponent features under the same digest.

Backtest uses a `competitive_balance_only` assignment policy. It reseeds the captured entrants solely against the matchup model while preserving the verified division sizes, pool sizes, and advancement format. Club, coach, geography, travel, and rematch constraints belong to the separate upcoming-event Auto Seeding workflow and are not read or enforced here. Combined tournament cohorts such as `U10/U11` and `U17/U18` remain combined in the backtest request while each team's historical rating age stays separate.

Match predictions retain the requested team order, so an A-versus-B prediction cannot be reused as B-versus-A. Symmetric matchup costs use one canonical entrant order and may still be cached once per pair. Model-supplied probabilities keep valid boundary values such as 0 and 1; only absent values use the existing estimated blowout fallback, while nonfinite or out-of-range values stop the run.

The optimizer objective and the reported seeding comparison use the same intra-pool matchup set. Captured group and pool IDs provide stable internal identities when published display labels are blank or repeated; reports retain the published labels for the director. The output verifies that the projected pair-cost total equals the optimizer's recorded total before reporting a delta. Playoff simulation remains a separate schedule projection and does not silently enter the optimization claim. The optimizer still reports its existing projected 3+ and 5+ goal thresholds; the intake's actual-results baseline continues to define a blowout as 4 or more goals.

## Local artifacts

Backtest data lives under `reports/gotsport__<event_id>__<season-or-unknown>/intake/`:

- `last_walk.json`: canonical paid capture written before matching, recoverable without another scrape.
- `event_intake.json`: saved capture, matching outcomes, and division reviews.
- `event_links.json`: editable event team links and persistent clear decisions.

An existing event directory is reused. Locks and atomic writes protect local updates. Recovery and saved captures reject replacements that discard captured entrants, divisions, pool members, fixtures, or table readability. Event IDs and capture generations prevent an interrupted scrape or late matching result from mixing two events.

Fixture protection checks the captured content as well as row identity: populated results, participant IDs, labels, dates, and source details cannot silently become missing on a repeat walk. Unknown fields may gain evidence, and an identified game may carry corrected nonempty source values.

Repeat scrapes retain division notes and rules links. Checks remain valid only for the same structure. Review saves merge the fields an operator actually edited against the saved version under the event lock; conflicting edits require reopening the saved intake. Intentional clearing and unchecking remain available.

Team links also use compare-before-write checks for operator changes. Not-found decisions, clear decisions, and exact-membership duplicate acknowledgements are local and survive reloads; automatic matching cannot undo them. A changed collision membership invalidates the acknowledgement automatically.

Generated Backtest capture files and locks are ignored by Git and remain in these local event folders. Application code stays in `src/tournaments/`, tests in `tests/unit/`, workflow documentation in `docs/`, and development review notes in `.turbo/reports/`.

The CLI's `--completed-event` option selects the same complete-event capture and recovery path. Its existing `--force` option explicitly permits replacing the selected output. Default CLI and Seeding behavior stay unchanged.

## Validation

Offline parser, storage, matching, capture, Streamlit interaction, and optimizer tests cover play-ups, unranked divisions, missing IDs, unresolved matches, manual replacement/clear, historical-name review, source structure round trips, interrupted publication, concurrent link updates, partial-capture preservation, prediction orientation, probability boundaries, malformed assignment inputs, and assignment integrity. A newly scraped production event has not been used as end-to-end acceptance evidence for this change.

Validated 2026-09-11: **4,860 tests passed and 12 were skipped** in the required repository suite (`tests/test_enhanced_pipeline.py` excluded). The shell-hook module was rerun under Git for Windows Bash so its path-sensitive coverage ran correctly. The required backend Ruff check and Git diff check passed. The saved San Antonio Labor Cup 26 export retained 332 teams, 58 divisions, 88 pools, 614 fixtures, 613 scored games, 1,857 total goal margin, and 198 blowouts after local cohort repair.
