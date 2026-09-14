# MatchBalance completed-tournament intake

Backtest captures a completed GotSport event and reseeds it locally. The Seeding tab remains the separate upcoming-tournament workflow. Backtest never writes tournament teams to the PitchRank database.

MatchBalance Backtest supports tournament cohorts from U10 through U18. Combined brackets such as U10/U11 and U17/U18 remain in scope. Younger divisions and U19 divisions stay in the immutable source capture for audit purposes but are excluded from matching, replay-readiness checks, Backtest runs, and sales metrics.

MatchBalance has three distinct product workflows:

- **Backtest** is the sales proof. It takes a completed tournament's exact entrants and verified structure, reseeds those teams using historical competitive strength, and shows how the projected matchup quality would have changed.
- **Seeding Tab** is the self-service ranking product. It gives a director a ranked list of accepted teams so the director can seed the tournament manually.
- **Auto Seeder** is the future premium product. It will create the tournament assignments and apply operational constraints such as club separation, shared coaches, geography, travel, and rematches.

## Operator workflow

1. Open **Backtest** and enter the completed event URL. **Scrape the whole event** is the primary action; the priced two-division check is optional.
2. Work through **Overview**, **Teams**, and **Backtest**. The header keeps capture, team review, and schedule-readiness progress separate. Structure inspection and capture diagnostics are supporting details on Overview, and Save progress remains available everywhere.
3. Review the tournament name, dates when published, total teams, and teams by tournament cohort and gender. Counts follow the **entered division**: a U11 squad entered in U12 counts in U12. Current PitchRank age never changes these totals. Combined brackets stay combined.
   The **Actual tournament results** summary shows games counted, total and average goal margin, and blowout count and rate. Expand the cohort and division breakdowns to inspect where those results occurred.
4. Inspect structure only when needed. MatchBalance converts the captured fixtures into an exact slot graph, including cross-pool games and winner, loser, pool-rank, and division-wide wildcard advancement references. It preserves division capacities, pool capacities, pool names, and fixture order automatically. A bracket that advances the best records regardless of pool uses the published Wildcard 1/Wildcard 2 slots; if an older capture lacks those slot labels, replay stays blocked until that division is recovered. When every fixture has a match number, those numbers establish replay order; when a fixture is unnumbered but still has a stable provider match ID, the saved page order is preserved so the game cannot be moved behind a playoff. A fixture without either identity remains blocked because duplicate rows cannot be distinguished safely. The operator does not approve every division. Final standings are never treated as original seeds. Open **Tournament tiebreak rule** once for the event, confirm the published order and scoring policy from a public organizer source, add a short verification note, and save. Replay supports the standard points, goal-difference, goals-scored, and wins criteria. It also supports Tiger Tournaments' 3/1/0 scoring; two-team head-to-head; its special three-team handling when the captured pool label identifies a cross-bracket format; five-goal caps for goal difference and goals scored; fewest goals conceded; and the published FIFA penalty-kick fallback. A projected penalty qualifier uses the same frozen pre-event model and is recorded in the simulation evidence.
5. Start team review with **Needs review**. The page opens one unresolved registration at a time; filters and IDs are supporting details. Search PitchRank by current name or club without forcing the historical bracket age. A team may be linked, cleared, or explicitly marked not found. **Not found in PitchRank** completes the identity decision and keeps the entrant using a labeled arithmetic average of eligible pre-event peers from its original division, or its cohort when the division has no eligible peer. No other squad's identity or match history is borrowed. Distinct registrations resolving to one canonical team require correction or a noted acknowledgement.
6. Add a sourced cohort correction only when the published division label assigns the wrong tournament age or gender. The original label remains in the capture.
7. **Save progress** to resume later, or download the JSON bundle containing the capture, totals, displayed matches, saved links, cohort interpretations, and the sourced event tiebreak decision.
8. Open **Backtest**. One readiness table separates your capture and identity decisions from MatchBalance schedule, model, merge-map, and historical-rating checks. Save any tiebreak edit before running so the displayed rule and replay rule are identical. Backtest uses the `score_distribution` strategy, which derives outcomes, expected absolute margin, and every blowout threshold from one score distribution. Existing point-in-time artifacts can supply their frozen score regressors to this strategy; incompatible overrides for older heuristic strategies remain rejected. The artifact path and training command remain under **Advanced model settings**. Run one selected cohort or every ready cohort. Live phases and completed counts remain visible while a cohort runs. **Stop current run** safely terminates the active child process, retains a cancelled diagnostic artifact, and lets the operator run that cohort again.
9. MatchBalance first assigns the strongest appropriate teams to the highest captured division slots, then balances the captured pools within each division. A second deterministic pass scores swaps against the games that the captured fixture graph will actually play, including advancement-dependent games. Coherent models also test persistent team-strength scenarios during that pass so one uncertain rating cannot drive a fragile move. It may move a Bronze team to Silver or a Silver team to Gold, and it also decides which Pool A or Pool B slot each team occupies. Club, travel, coach, and geography constraints are intentionally absent from Backtest.
10. Review the completed result in place. Observed games, average goal margin, 4+ goal blowouts, and blowout rate come directly from the scraped tournament. The proposal uses the same captured fixture graph with the new division and pool placement. Every entrant shows its original and proposed division and pool.
11. Each run also predicts its unchanged original fixture arrangement. Its cohort-level check remains a diagnostic because a small bracket may contain only a handful of games and can swing sharply. These warnings stay in the evidence but do not independently suppress a valid whole-event result.
12. The **Tournament-wide Backtest result** combines the newest compatible result for every cohort. It validates the model once across the full scored event: at least 95% fixture coverage, no more than 1.0 goal of average-margin error, and no more than 10 percentage points of 4+ blowout-rate error. A tournament-director package becomes available only after every cohort finishes and this event-wide unchanged-fixture validation passes. Those tolerances are an operational gate, not proof of prediction accuracy. A coherent score-distribution run does not apply separate margin or blowout multipliers because independent scaling can make nested probabilities contradict each other. The completed event being Backtested never trains, selects, or calibrates its model.

## Capture verification and recovery

Overview's capture diagnostics condense scraper messages behind supporting details. **Verify division list** buys only landing-page reads, up to four, and accepts the list only after the complete observed union repeats twice. It never shrinks a saved capture. If new or unreadable divisions remain, the targeted action fetches only those division pages and reuses every previously observed team-page result, including a prior readable page with no rankings ID.

During a full Backtest capture, progress is emitted on Streamlit's script thread for division discovery, division pages, GotSport ID pages, local recovery save, and read-only database matching. Results remain in source order even when pages finish out of order.

Labels such as `U13 - 5 Team` ignore the format's team count when deriving the tournament cohort. Older saved captures receive this interpretation locally on load. Explicit `U10/U11` and `U17/U18` brackets remain combined; disjoint header and division ages remain attention items until an operator records a sourced interpretation.

## Counting and evidence limits

The total counts distinct event registration IDs, plus separately identified source entries whose registration IDs are missing. An event registration appearing in two cohorts counts once in the overall total and once in each cohort. The interface explains when cohort subtotals exceed the unique total.

Missing-ID teams remain visible and require identity review for possible duplicates. Unknown cohort or gender stays unknown. The fixture graph comes only from captured participant slots and published match dependencies. Published rules links remain attached as evidence; an unavailable source rule is not silently represented as verified source text.

### Actual result totals

Goal margin is `abs(home_score - away_score)` using the published scores excluding shootouts. A 5–1 game contributes 4; a draw contributes 0 even if a shootout decides the winner. The total adds one margin per counted game. The average divides that total by the number of counted games, so larger divisions contribute proportionally. A **blowout is a margin of 4 or more goals**; its rate is the blowout count divided by the counted games. Rates and averages are unavailable when no games can be counted.

Both scores must be nonnegative integers. Explicit unplayed, cancelled, postponed, forfeited, unrecognized, and missing-score results are excluded. Valid score pairs from legacy captures whose result status was not retained remain usable, with a visible legacy-status count. The source does not separately identify extra-time goals.

Provider match IDs identify repeated listings across the event; printed match numbers are scoped to their division. Conflicting results or division assignments are excluded rather than choosing a version. Fixtures with neither a provider match ID nor a printed number are excluded because duplicate listings cannot be ruled out. Coverage, duplicates, exclusions, and partial captures are displayed alongside the totals. A conflicting cross-division fixture appears as excluded in each affected breakdown, so those exclusion counts can overlap.

Results use the tournament's entered cohort and gender. They are calculated directly from the saved fixture evidence and included under `tournament_totals.results` in the downloaded JSON. Loading a saved capture with scores makes these numbers available without another scrape; captures with missing fixtures or scores still need that evidence collected.

Observed results are the baseline presented to the tournament director. MatchBalance estimates the reseeded result because those games were never played. To keep that comparison honest, the same model first replays the unchanged captured placement and must reproduce the actual tournament within the documented tolerances. Only then can the report compare the actual tournament with the MatchBalance estimate. Reversing home and away order does not change symmetric matchup cost.

Each coherent-model run draws the original and MatchBalance arrangements repeatedly from the same scoreline distributions. One persistent uncertainty value is sampled for each team and shared across all of that team's games in a run; the same team scenario and random seed are used for both arrangements. Each cohort receives a stable independent random stream, so tournament-wide ranges do not accidentally correlate unrelated age and gender groups. The output reports empirical 95% ranges and the probability that MatchBalance reduces average margin and the 4+ blowout rate. This represents scoreline and rating uncertainty conditional on the selected model. It does not include uncertainty from choosing a different model family.

The schedule optimizer also creates five candidates from independent strength-uncertainty searches. It scores those candidates on the same 31 holdout strength scenarios and chooses the lowest mean-plus-downside objective. The output records each candidate score and, for every entrant, how often the selected division and pool repeated across candidate searches. A fragile placement remains visible for review instead of being presented with false certainty. These are Backtest competitive-balance checks only; operational constraints remain part of future Auto Seeder work.

## Downstream optimizer safeguards

The current command-line backtest and seeding runners validate their inputs before assigning teams. Every tournament entrant needs a unique, nonempty registration ID and a finite PowerScore from 0 through 1. Division names must be unique and nonempty, division and pool capacities must be positive whole numbers, and the requested slots must equal the supplied entrants. Numeric strings remain accepted in JSON input for compatibility. Missing ratings stop the run instead of silently removing a team. Completed output is checked to confirm that every entrant appears exactly once and that each pool retains its requested capacity.

A reviewed intake can be converted directly with `python scripts/backtest_reviewed_intake.py --intake-json <event_intake.json> --point-in-time-model-artifact <model.pkl>`. This adapter uses the captured pool members, source results, fixture graph, and saved `EventLinks` decisions. Direct GotSport-ID matches and explicit operator choices use the matched team's pre-event rating. A reviewed not-found decision retains the entrant and uses a labeled division or cohort average estimate; exact-name suggestions and cleared matches remain review gaps. Both canonical local snapshots and downloaded intake bundles carry these decisions. An unreadable fixture dependency stops with a software evidence error; it does not become an operator division-review task.

Backtest strength comes from `prediction_feature_history` before the event start. The snapshot's `created_at` and any `last_calculated` timestamp must also precede the event cutoff, proving the stored features were available at the time; reconstructed later backfills and recalculations are rejected. During model training, each historical game can use only snapshots created and calculated before that game's date. Current `rankings_full`, future or same-day snapshots, and snapshots without provenance are rejected. Every reviewed request requires the normalized tournament start date as its cutoff. Historical game context starts at the configured lookback and ends before that cutoff. Point-in-time model artifacts must declare a `model_data_end_date` before the event; older or future-trained artifacts stop the run. Train an eligible artifact with `train_point_in_time_match_model.py --max-game-date <event-date>`, where the bound is exclusive and the default lookback is measured backward from that historical date. Each cohort output includes `historical_inputs.json`, which freezes the matched IDs, source and tournament cohorts, strength/confidence features, snapshot and creation dates, cutoff, model training metadata, model artifact SHA-256, and an overall input digest.

Before any cohort can run, **Check historical ratings** performs the same strict read-only identity resolution, snapshot selection, provenance checks, and PowerScore validation as the runner for every currently ready entrant. If a matched team has no eligible pre-event snapshot, Backtest keeps its canonical identity and uses a separately labeled arithmetic average from eligible teams in its original division, then the cohort. This missing-history estimate is distinct from the estimate for a registration reviewed as Not Found. Neither estimate borrows another team's identity, and both freeze their source entrants in the run evidence. A cohort stays blocked if no eligible peer exists from which to calculate an average. A database or service outage is reported as an unavailable check rather than being mislabeled as missing team history. The saved preflight is reused only while the exact cohort requests and model artifact SHA-256 remain unchanged.

For San Antonio Labor Cup 26, the tournament cutoff is **2026-09-05 exclusive**. Build its local artifact with:

```powershell
python scripts/train_point_in_time_match_model.py --min-game-date 2025-09-05 --max-game-date 2026-09-05 --limit None --calibration-ratio 0.2 --test-ratio 0.2 --min-examples 100 --probability-strategy score_distribution --selection-objective competitive_match_quality --model-dir models/matchbalance_san_antonio_2026_pre_event
```

Add `--save-dataset` when the run will enter the reviewed model registry. The model artifact stays local and is not committed. Select `models/matchbalance_san_antonio_2026_pre_event/point_in_time_match_model.pkl` in Backtest, then run the historical preflight.

Historical feature rows are immutable through the ranking writer: a repeated team/date snapshot keeps the first stored values instead of rewriting them under the original `created_at`. Historical snapshot and game queries include IDs that were deprecated by a later merge, then resolve those immutable rows to the current canonical identity. The manifest retains each snapshot's stored source team ID. Historical game context also requires both the played date and the database `created_at` to precede the event cutoff. The manifest freezes those eligible games and every related-team snapshot used for common-opponent features under the same digest.

Backtest uses a `competitive_balance_only` assignment policy. It reseeds the captured entrants solely against the matchup model while preserving verified division sizes, pool sizes, pool names, fixture slots, and advancement dependencies. Division placement groups similarly strong teams at the appropriate Gold, Silver, or Bronze level. A separate balanced-strength pool policy distributes seed bands across the original pools and minimizes differences between pool-average strength. Club, coach, geography, travel, and rematch constraints belong to the separate upcoming-event Auto Seeding workflow and are not read or enforced here. Combined tournament cohorts such as `U10/U11` and `U17/U18` remain combined while each team's historical rating age stays separate.

Backtest evaluates both team orientations and averages them into one neutral-site forecast. Reversing A and B therefore swaps their win probabilities and signed margin exactly while preserving draw, expected absolute margin, and blowout risk. Model-supplied probabilities keep valid boundary values such as 0 and 1; only absent values use the existing estimated blowout fallback, while nonfinite or out-of-range values stop the run. New training runs use three disjoint chronological partitions: training, calibration/model selection, and a later untouched test. Short named events stay intact; long-running competitions fall back to complete game dates. Mirrored rows remain with their source game. Historical context requires both the played date and, when available, the result's `created_at` to precede the example date; same-day games are excluded when kickoff order is unknown.

Every training run evaluates two interpretable baselines on the exact same untouched examples: a cohort scoring-rate Poisson model and a recency-weighted team attack/defense Poisson model shrunk toward its age and gender cohort. MatchBalance therefore has to beat simple historical alternatives on probability quality, margin error, 4+ blowout probability, and competitive-game detection. The benchmark is written to `point_in_time_model_frozen_holdout_benchmarks.csv` and recorded in the model metadata. It never silently promotes a model. Evaluation bundles also break performance out by age, gender, feature source, and the weaker of the two teams' history coverage.

For a broader offline bake-off, save the point-in-time training dataset and run:

```powershell
python scripts/run_match_model_laboratory.py `
  --dataset models/point_in_time_match_predictor/training_dataset.csv `
  --output-dir reports/matchbalance-model-laboratory
```

The laboratory uses expanding chronological folds and keeps every short tournament, plus any overlapping date interval, entirely inside one fold. It compares the learned MatchBalance model with cohort-average Poisson, recency-weighted hierarchical Poisson, hierarchical negative-binomial, and hierarchical bivariate-Poisson candidates. Every candidate is scored on the same canonical games. The report includes tournament-fold metrics, combined metrics, age/gender/history-coverage slices, exact frozen predictions, failures, the dataset SHA-256, Git commit, configuration, and a report digest. By default, the recency-weighted hierarchical Poisson model is the declared promotion baseline, so the learned `matchbalance_learned` artifact receives its own registration decision. Use `--promotion-baseline` to name another incumbent represented in the same folds. A candidate is marked `promote` only when it covers the same folds, clears minimum evidence, improves repeatedly, stays within the primary-metric noninferiority limits, and does not materially regress an adequately sized age, gender, or history segment. That recommendation is evidence only; it never changes the active artifact automatically.

Register a promoted artifact only after its sidecar metadata carries the same saved-dataset SHA-256 as the laboratory report:

```powershell
python scripts/manage_match_model_registry.py register `
  --version 2026.09.13-v2 `
  --artifact models/matchbalance_candidate/point_in_time_match_model.pkl `
  --laboratory-manifest reports/matchbalance-model-laboratory/laboratory_manifest.json `
  --candidate matchbalance_learned
python scripts/manage_match_model_registry.py activate --version 2026.09.13-v2
```

Registration copies the artifact, metadata, and laboratory manifest into an immutable local version folder and verifies their hashes. It rejects a reused version, a held candidate, a changed laboratory digest, a non-coherent probability strategy, or mismatched training data. Registration does not activate the version. Once explicitly activated, Backtest can select the newest intact registered artifact whose training end date is strictly before the completed event; existing unregistered model folders remain a compatibility fallback.

Running **Check historical ratings** also writes `historical_coverage.json` and `historical_coverage.csv` beside the local event preflight. These files separate established, moderate, limited, missing-history-average, not-found-average, and ineligible evidence. Average-strength entrants retain the requested peer-average central rating but carry zero inherited games and broad rating uncertainty instead of pretending to own their peers' evidence.

Fresh point-in-time datasets also include strictly pre-date schedule-load features: days since each team's previous match and games played in the previous 7 and 30 days. Late-imported and same-day results remain excluded.

Optional accuracy inputs can be tested without adding unverified database columns. Pass `--game-context-csv <path>` to the training command with one unique `game_id` per row and any of `match_duration_minutes`, `players_per_side`, `event_strength`, `home_roster_continuity`, `away_roster_continuity`, `home_rest_minutes`, or `away_rest_minutes`. Every value must describe information known before kickoff. The dataset builder creates explicit missingness indicators, swaps the home/away fields in mirrored examples, and leaves shared match facts unchanged. The saved dataset hash covers the resulting features, and the model metadata separately records the context-file hash. Laboratory feature coverage shows these groups as ready only when the enriched columns contain usable values.

Prospective predictions provide independent evidence for future model promotion. The freezing jobs select only unresolved future fixtures, use expected-state writes, and never replace a completed prediction. Offline predictions require the fixture date to be later than the prediction timestamp. Evaluation compares exact heuristic/offline version pairs only on their shared strictly pregame fixtures. It writes an all-version scorecard plus monthly results and requires at least 500 games across three months, noninferiority on the shared primary metrics, and repeated monthly improvements before labeling a version `eligible_for_review`. That label never activates a model. A registry registration may bind this scorecard with `--prospective-scorecard <json> --prospective-version <version>`; the registry verifies its digest and eligibility decision and preserves it beside the artifact.

The division optimizer and balanced-pool pass retain every entrant exactly once at the captured capacities. Captured group and pool IDs provide stable internal identities when published display labels are blank or repeated; reports retain the published labels for the director. Reported outcome estimates come from the captured schedule graph, including pool games, cross-pool games, and dependent playoff slots. The matchup model calculates the exact probability of a 4+ goal margin from its score distribution. Older cohort outputs without the captured-schedule projection or unchanged-fixture validation are not mixed into a current tournament-director comparison.

## Local artifacts

Backtest data lives under `reports/gotsport__<event_id>__<season-or-unknown>/intake/`:

- `last_walk.json`: canonical paid capture written before matching, recoverable without another scrape.
- `event_intake.json`: saved capture, matching outcomes, and division reviews.
- `event_links.json`: editable event team links and persistent clear decisions.
- `historical_preflight.json`: read-only eligibility results tied to the exact reviewed requests and selected model hash.
- `historical_coverage.json` and `historical_coverage.csv`: evidence-quality totals and the recovery queue created with the historical preflight.
- `scenarios/reviewed-backtest/runs/<run_id>/`: one atomic completed cohort run containing the strict request, frozen historical evidence, original-versus-proposed model summary, team movements, logs, and director report. Failed and operator-stopped attempts remain in `.failed` and `.cancelled` sibling directories for diagnosis and can be rerun from Backtest.
- Each completed run records the Backtest engine version. A scoring or simulation change makes older outputs incompatible with the current tournament-wide result, so the affected cohorts must be rerun instead of silently mixing old and new behavior.

An existing event directory is reused. Locks and atomic writes protect local updates. Completed-run promotion retries brief Windows file locks while keeping the directory rename atomic. Recovery and saved captures reject replacements that discard captured entrants, divisions, pool members, fixtures, or table readability. Event IDs and capture generations prevent an interrupted scrape or late matching result from mixing two events.

Fixture protection checks the captured content as well as row identity: populated results, participant IDs, labels, dates, and source details cannot silently become missing on a repeat walk. Unknown fields may gain evidence, and an identified game may carry corrected nonempty source values.

Repeat scrapes retain existing source notes, rules links, cohort corrections, and the sourced event tiebreak decision. Cohort corrections remain valid only for the same structure. Saves merge operator decisions against the loaded version under the event lock; conflicting edits require reopening the saved intake.

Team links also use compare-before-write checks for operator changes. Not-found decisions, clear decisions, and exact-membership duplicate acknowledgements are local and survive reloads; automatic matching cannot undo them. A changed collision membership invalidates the acknowledgement automatically.

Generated Backtest capture files and locks are ignored by Git and remain in these local event folders. Application code stays in `src/tournaments/`, tests in `tests/unit/`, workflow documentation in `docs/`, and development review notes in `.turbo/reports/`.

The CLI's `--completed-event` option selects the same complete-event capture and recovery path. Its existing `--force` option explicitly permits replacing the selected output. Default CLI and Seeding behavior stay unchanged.

After the San Antonio review, matching, historical preflight, and cohort runs are complete, validate the entire event with one command:

```powershell
python scripts/validate_backtest_event.py --event-key gotsport__51783__unknown --profile san-antonio-51783 --model-artifact models/matchbalance_san_antonio_2026_pre_event/point_in_time_match_model.pkl
```

The command exits successfully only when the fixed raw capture totals, every in-scope division has a supported replay format, every in-scope team identity is matched or explicitly reviewed as not found, duplicate-mapping acknowledgements, the exclusive-cutoff model, the current historical preflight, every cohort output, all in-scope movement rows, event-wide unchanged-fixture validation, and the final event rollup agree. It prints a JSON report and can save the same report with `--output <path>`.

## Validation

Run the saved-event acceptance gate after matching, verification, replay-format support, historical preflight, and cohort execution:

```powershell
python scripts/validate_backtest_event.py --event-key gotsport__51783__unknown --profile san-antonio-51783 --model-artifact models/matchbalance_san_antonio_2026_pre_event/point_in_time_match_model.pkl
```

It checks the exact San Antonio raw-capture baseline of 332 teams, 58 divisions, 88 pools, 614 fixtures, 613 scored games, 1,857 total goal margin, and 198 blowouts. The Backtest scope remains U10-U18. It also requires replay support for every in-scope division, every in-scope identity matched or explicitly reviewed as not found, collision acknowledgements, eligible pre-event rating evidence or a labeled fallback for each entrant, completed compatible cohort outputs, and a reconciled whole-event rollup. The command writes nothing unless `--output` is supplied and exits with status 1 while work remains.

Offline parser, storage, matching, capture, Streamlit interaction, and optimizer tests cover play-ups, unranked divisions, missing IDs, unresolved matches, manual replacement/clear, historical-name review, source structure round trips, interrupted publication, concurrent link updates, partial-capture preservation, prediction orientation, probability boundaries, malformed assignment inputs, and assignment integrity. San Antonio Labor Cup 26 is the saved-event end-to-end acceptance fixture; its generated capture, model, runs, and report remain local and outside Git.
