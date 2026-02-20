## Real-data A/B validation (2026-02-19)

### Scope

Ran real-data A/B comparisons for the v53e opponent-adjustment change:

- **Legacy-like config**
  - `OPPONENT_ADJUST_EXPONENT=1.0`
  - `OPPONENT_ADJUST_USE_COMPONENT_STRENGTH=False`
  - `OPPONENT_ADJUST_RENORM_MODE="percentile"`
- **Current config**
  - default `V53EConfig()` (component strength + exponent + zscore re-norm)

Data source and date:

- Supabase production fetch via `fetch_games_for_rankings(...)`
- `lookback_days=365`
- `today=2026-02-19`
- Fetched rows: **980,915** perspective rows
- Unique teams: **77,477**

### Code-path coverage reviewed

Validated and read through the ranking execution path end-to-end:

- `scripts/calculate_rankings.py`
- `src/rankings/calculator.py`
- `src/rankings/data_adapter.py`
- `src/etl/v53e.py`
- `src/rankings/__init__.py`
- `src/rankings/layer13_predictive_adjustment.py`

---

## Pass 1: Large cohort A/B (no SCF state-map injection in this pass)

Tested largest male cohorts plus U14 male:

| age | gender | teams | mean_ps_delta | median_ps_delta | comp_n | comp_mean_off_delta | comp_mean_ps_delta | comp_mean_rank_delta | pad_n | pad_mean_off_delta | pad_mean_ps_delta | pad_mean_rank_delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 13 | male | 8154 | 0.002334 | 0.000956 | 4 | 0.218966 | 0.075849 | 389.00 | 47 | -0.040129 | 0.037565 | 129.08 |
| 12 | male | 7984 | 0.001398 | 0.000422 | 9 | 0.162468 | 0.010471 | 108.75 | 17 | -0.000854 | 0.000638 | -50.91 |
| 11 | male | 7621 | 0.000214 | -0.000650 | 2 | 0.081509 | -0.003085 | 189.00 | 15 | -0.005570 | 0.046723 | 422.64 |
| 14 | male | 6376 | 0.000563 | -0.003031 | 9 | 0.140316 | 0.008596 | 37.50 | 30 | -0.035687 | 0.095614 | 496.91 |

Where:

- `comp_*` = "competitive profile" proxy segment
- `pad_*` = "weak-schedule blowout profile" proxy segment

---

## Pass 2: U14 male A/B with SCF enabled (team_state_map fetched from teams table)

To better mirror production behavior, reran U14 male with SCF metadata:

- Cohort rows: **96,750**
- Teams: **6,376**
- `team_state_map` size: **10,667**

Summary:

- `mean_ps_delta`: **+0.000958**
- `median_ps_delta`: **-0.004382**
- Competitive profile:
  - `n=7`
  - `comp_mean_off_delta=+0.123658`
  - `comp_mean_ps_delta=-0.011926`
  - `comp_mean_rank_delta=-44.25`
- Weak-schedule blowout profile:
  - `n=38` (29 Active with rank)
  - `pad_mean_off_delta=-0.037369`
  - `pad_mean_ps_delta=+0.035771`
  - `pad_mean_rank_delta=+195.55`

Additional overlap check (Active teams only):

- Competitive profile Active teams: 4
- Blowout profile Active teams: 29
- Median rank (new):
  - Competitive = **841**
  - Blowout = **915**
- But several blowout teams still outrank some competitive teams (e.g., 13/29 outrank one comp team, 22/29 outrank another).

---

## Artifacts

Generated CSVs in `data/validation/`:

- `ab_summary_real_cohorts.csv`
- `ab_movers_11_male.csv`
- `ab_movers_12_male.csv`
- `ab_movers_13_male.csv`
- `ab_movers_14_male.csv`
- `ab_competitive_profile_11_male.csv`
- `ab_competitive_profile_12_male.csv`
- `ab_competitive_profile_13_male.csv`
- `ab_competitive_profile_14_male.csv`
- `ab_padding_profile_11_male.csv`
- `ab_padding_profile_12_male.csv`
- `ab_padding_profile_13_male.csv`
- `ab_padding_profile_14_male.csv`
- `ab_movers_14_male_scf.csv`
- `ab_competitive_profile_14_male_scf.csv`
- `ab_padding_profile_14_male_scf.csv`

---

## Key takeaway from this real-data run

The new opponent-adjust logic **does** raise offense credit in competitive/tight-game profiles, but in this real U14 male run it did **not consistently convert into better overall power/rank** once defense + SOS interactions are included; weak-schedule blowout profiles also still show cases of net rank gains.

### Refresh status

- Refreshed at (UTC): 2026-02-19T05:31:52Z
- Window reference date: 2026-02-19
- Rows fetched: 980,915
- Teams fetched: 77,477
- Data date range in fetch: 2025-02-19 to 2026-02-16

