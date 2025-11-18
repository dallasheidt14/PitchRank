# How to Get perf_centered Values

## The Problem

The `rankings_view` only exposes "canonical" fields (power_score_final, sos_norm, offense_norm, defense_norm) but **does NOT expose internal calculation fields** like `perf_centered`.

## Solution

Query `rankings_full` table directly (not the view).

---

## Step 1: Check what columns exist in rankings_full

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'rankings_full'
ORDER BY ordinal_position;
```

**Look for these columns:**
- `perf_centered` (normalized performance, -0.5 to +0.5)
- `perf_raw` (raw performance before normalization)
- `powerscore_core` (before anchor/provisional adjustments)
- `power_score_final` (after all adjustments)

---

## Step 2: Query the data

### Option A: If column names match exactly

```sql
SELECT
    t.team_name,
    t.club_name,
    rf.age_group,
    rf.gender,
    rf.power_score_final,
    rf.powerscore_core,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,
    rf.perf_centered,        -- KEY VALUE!
    rf.perf_raw,
    rf.games_played,
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_final
FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
WHERE (t.team_name ILIKE '%PRFC%Scottsdale%14%'
   OR t.team_name ILIKE '%Dynamos%14%')
  AND rf.gender IN ('M', 'Male', 'Boys')
ORDER BY rf.power_score_final DESC;
```

### Option B: Simpler query (if joins are complex)

```sql
-- First, get team IDs
SELECT team_id_master, team_name
FROM teams
WHERE team_name ILIKE '%PRFC%Scottsdale%14%Pre-Academy%'
   OR team_name ILIKE '%Dynamos%SC%14%';

-- Then use those IDs directly
SELECT *
FROM rankings_full
WHERE team_id IN ('2e39aab1-27c2-4882-95e9-6e68699a36f4',  -- PRFC Scottsdale
                  'c2f8e0aa-2f96-4c23-b5ae-6782ce392bc9')  -- Dynamos SC
LIMIT 2;
```

---

## Step 3: Interpret the results

### What to look for:

| Team | Expected perf_centered | Why? |
|------|----------------------|------|
| **PRFC Scottsdale** | **Negative** (e.g., -0.10) | Underperforming inflated expectations from weak schedule |
| **Dynamos SC** | **Positive** (e.g., +0.15) | Overperforming deflated expectations from strong schedule |

### If you see this pattern:

✅ **Your system is working perfectly!**

The performance metric is correctly identifying:
1. PRFC's offense is inflated by weak schedule → expects high margins → actual margins don't meet inflated expectations → negative performance
2. Dynamos' offense is deflated by strong schedule → expects low margins → actual margins exceed deflated expectations → positive performance

The 0.000094 gap in their power scores is essentially a tie, and the system has already corrected 99% of the double-counting problem.

**Recommendation: Don't change anything!**

---

## Step 4: Calculate the exact contribution

Once you have the `perf_centered` values, you can calculate their exact contribution to power score:

```python
PERFORMANCE_K = 0.15

prfc_perf_contribution = prfc_perf_centered × 0.15
dynamos_perf_contribution = dynamos_perf_centered × 0.15

performance_gap = dynamos_perf_contribution - prfc_perf_contribution
```

This will tell you exactly how much the performance metric is swinging the rankings in Dynamos' favor.

---

## Troubleshooting

### If column doesn't exist:

The column might have a different name. Check the output of Step 1 for similar column names:
- `perf_centered` might be `performance_centered`
- `perf_raw` might be `performance_raw`
- `powerscore_core` might be `power_score_core`

### If no data is returned:

Check:
1. Are the team names spelled exactly right?
2. Are there recent rankings in rankings_full?
3. Try a broader search:
   ```sql
   SELECT team_name FROM teams WHERE team_name ILIKE '%PRFC%' LIMIT 10;
   SELECT team_name FROM teams WHERE team_name ILIKE '%Dynamos%' LIMIT 10;
   ```

### If you get access denied:

You might need to use a different database user with access to `rankings_full`. The views have RLS (Row Level Security) but the underlying table might have different permissions.
