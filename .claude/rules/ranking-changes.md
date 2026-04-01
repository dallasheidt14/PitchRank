# Ranking Algorithm Changes

## Diagnose before changing anything
Run `python scripts/diagnose_ranking.py <team_uuid>` before proposing any ranking engine fix. Trace the full pipeline layer-by-layer (games -> v53e -> ML -> SOS -> final score) to find where the problem actually is. Don't do incremental config toggles hoping something sticks.

## Fix confirmed bugs before adding new ingredients
When investigating a ranking issue, fix the confirmed bug first. Don't mix bug fixes with new scoring features in the same change — keep experiments clean so you can isolate what actually moved the needle.

## Single source of truth
Never allow dual computation paths for the same value. If a score is computed in two places, delete one and add a hard assertion that they match during the transition. Dual paths always diverge silently.

## rankings_full is a subset
`rankings_full` only contains teams that made it through the full pipeline. It cannot be used as a proxy for `base_strength_map` which includes all teams with games. If you need all teams, query the source data, not the output table.
