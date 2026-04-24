# Tournament Seeding Beta

This beta is isolated on the `codex/tournament-seeding-beta` branch. It does not change production compare or predict behavior.

## Goal

Given a tournament's entered teams and a provided tournament format, generate a suggested seeding layout that reduces likely lopsided games.

Current scope:

- resolves teams against active `rankings_full` + `teams`
- accepts explicit structure for divisions and pools
- runs pairwise matchup predictions through the Python predictor and seeds to reduce likely lopsided games
- can benchmark the optimized projection against a historical event's actual results when you provide `actual_event_name`
- supports point-in-time tournament replay, which now defaults to `poisson_draw_gate` for more realistic draw behavior
- only targets `u10-u19`

## Input Shape

Save a JSON file like this:

```json
{
  "event_name": "Desert Cup",
  "event_date": "2026-08-15",
  "cohorts": [
    {
      "age_group": "u11",
      "gender": "female",
      "actual_event_name": "2025 Desert Cup",
      "format": {
        "divisions": [
          {
            "name": "Gold",
            "team_count": 8,
            "pool_sizes": [4, 4],
            "advancement": "pool_winners_to_final"
          },
          {
            "name": "Silver",
            "team_count": 8,
            "pool_sizes": [4, 4],
            "advancement": "pool_winners_to_final"
          },
          {
            "name": "Bronze",
            "team_count": 8,
            "pool_sizes": [4, 4],
            "advancement": "pool_winners_to_final"
          }
        ]
      },
      "teams": [
        "Phoenix Rising 15 Girls",
        "SC Del Sol 15 Girls",
        { "team_name": "Legacy 15 Girls", "state_code": "AZ" }
      ]
    }
  ]
}
```

Notes:

- `format.divisions[*].team_count` must add up exactly to the number of teams in that cohort.
- Use `pool_sizes` when a division has multiple brackets or uneven pods.
- You can use `pool_count` instead of `pool_sizes` only when pools are evenly sized.
- Team requests can be plain strings or objects with `team_name`, optional `club_name`, optional `state_code`, or canonical `team_id`.
- Name matching is beta quality. If a request is ambiguous or not found, the script stops and shows suggestions.
- The format is supplied by you. The beta does not need to scrape GotSport to understand the structure.
- `actual_event_name` is optional. When present, the script fetches completed `games` rows for the event and reports actual average goal differential, close-game rate, and blowout rates next to the optimized projection.

## Run

```bash
python scripts/optimize_tournament_seeding.py --input path/to/request.json
```

Outputs land in `reports/tournament_seeding_beta/`:

- `summary.json`
- one JSON file per cohort

The output echoes back:

- requested divisions and pool sizes
- optimized team placement by division
- optimized team placement by pool
- projected tournament metrics based on the current matchup predictor
- optional `actual_results` and `comparison_to_actual` when `actual_event_name` is provided

Projection note:

- the current projection basis is `all_intra_pool_pairings`
- in plain English, the optimizer scores every possible matchup inside each pool/division bucket
- this is good enough for the beta seeding objective, but it is not yet a full game-by-game schedule simulator for partial-play formats

## Model Track

For competitive-match experiments, the point-in-time trainer now supports:

```bash
python scripts/train_point_in_time_match_model.py --selection-objective competitive_match_quality
```

That objective changes strategy selection to favor:

- lower margin error
- higher close-game recall/precision
- better blowout calibration

It leaves the default training objective unchanged unless you opt into it.

For historical tournament cohort replay:

```bash
python scripts/backtest_tournament_cohort.py \
  --input path/to/cohort.json \
  --predictor-source point_in_time \
  --point-in-time-model-artifact path/to/point_in_time_match_model.pkl
```

If you do not pass `--point-in-time-probability-strategy`, the beta replay defaults to `poisson_draw_gate`.
