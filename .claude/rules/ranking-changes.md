# Ranking Algorithm Changes

## Diagnose before changing anything
Run `python scripts/diagnose_ranking.py <team_uuid>` before proposing any ranking engine fix. Trace the full pipeline layer-by-layer (games -> Glicko-2 passes -> SOS/SCF -> ML Layer 13 -> evidence gates -> final score) to find where the problem actually is. Don't do incremental config toggles hoping something sticks.

## Fix confirmed bugs before adding new ingredients
When investigating a ranking issue, fix the confirmed bug first. Don't mix bug fixes with new scoring features in the same change — keep experiments clean so you can isolate what actually moved the needle.

## Measure the blast radius before shipping
A change to what the engine reads moves teams the change is not about. Measure it read-only first
and put the numbers in the PR: how many games it removes or adds, how many teams on the other side
of those games are affected, and how many cross `MIN_GAMES_PROVISIONAL` (12) in either direction —
crossing it takes a team's published rank away. A team that ends at zero games is usually a sign
the change caught something it should not have, or that the team belonged to the same population.

## Single source of truth
Never allow dual computation paths for the same value. If a score is computed in two places, delete one and add a hard assertion that they match during the transition. Dual paths always diverge silently.

## rankings_full is a subset
`rankings_full` only contains teams that made it through the full pipeline, so it cannot be used as a proxy for `global_strength_map`. Neither is the source data: `fetch_games_for_rankings` drops every game touching a team in `team_ranking_exclusions`, so a team with games is absent from the strength map by design. Query `games` minus that list.
