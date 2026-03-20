# SOS Diagnosis Review Guide

Use this guide after running `python scripts/diagnose_bad_sos_rankings.py` to interpret the output and identify what's actually broken.

---

## Quick Triage Checklist

Run through these in order. Stop when you find the root cause.

### 1. How many bad-SOS teams appear in top rankings?

Look at the **CROSS-COHORT SUMMARY** at the bottom.

- **0-2 per cohort** → System is working. The "problem" may be perception, not formula.
- **3-5 per cohort** → Mild issue. Likely shrinkage or component-related.
- **6+ per cohort** → Systemic problem. Something structural is wrong.

### 2. Are the bad-SOS teams concentrated in specific cohorts?

Check "Cohorts with low-SOS teams in top rankings."

- **Concentrated in younger ages (U10-U12)** → Likely a data sparsity issue. Younger ages have fewer cross-league games, creating disconnected components where SOS normalization is unreliable.
- **Concentrated in one gender** → May indicate a provider gap (e.g., fewer girls' games scraped from a source).
- **Spread evenly across cohorts** → Formula-level issue, not data.

### 3. What's the SOS distribution shape?

Look at "SOS Clustering Analysis."

- **% of top teams with sos_norm in [0.40, 0.60] > 50%** → SOS is clustered near the middle. Percentile normalization + shrinkage is compressing everyone toward 0.5, so SOS has no discriminating power. Bad-SOS teams look "average" instead of bad.
- **sos_norm std < 0.15** → Same problem — not enough spread.
- **sos_norm range doesn't reach below 0.10 or above 0.90** → Shrinkage is capping the extremes.

### 4. Check the "schedule dodgers"

These are teams with >70% win rate but sos_norm < 0.40. For each one, ask:

- **How many games played?** If GP < 10, low-sample shrinkage is pulling their SOS toward 0.5, giving them a free boost. This is the shrinkage inflation problem.
- **What state are they in?** Some states have isolated leagues that don't play nationally. These teams dominate their bubble but never face real competition.
- **What's their off_norm?** If off_norm > 0.80 with low SOS, they're beating weak teams by big margins. Opponent-adjustment should penalize this, but if they ONLY play weak teams, there's no strong baseline to adjust against.

### 5. Look at the per-cohort ranking tables

For each flagged team (marked with ⚠️), compare to the teams ranked just above and below:

- **Is their OFF+DEF carrying them?** Calculate: `0.20*OFF + 0.20*DEF`. If this alone is >0.30, their talent metrics are propping them up despite bad SOS.
- **How does their SOS compare to teams ranked ±5 spots?** If there's a big SOS gap but small PowerScore gap, the formula isn't penalizing weak schedules enough.
- **What's their provisional_mult?** If it's < 1.0, they already have a penalty. If it's 1.0, they have enough games to be "full strength" — meaning the ranking trusts them fully despite bad opponents.

---

## Red Flag Patterns

### Pattern A: "Bubble Champion"
```
High OFF (>0.70) + High DEF (>0.70) + Low SOS (<0.30) + High Win% (>80%)
```
Team dominates a weak local league. Beats everyone they play but never plays anyone good. OFF/DEF look elite because opponent-adjustment can't properly calibrate within an isolated bubble.

**Root cause:** Disconnected component where all teams are weak. Percentile normalization within the component gives the best weak team a high sos_norm relative to its peers, or component shrinkage pulls everyone to 0.5.

**Fix direction:** Strengthen component-size shrinkage, or anchor SOS to an absolute scale rather than relative percentile.

### Pattern B: "Shrinkage Beneficiary"
```
Few games (GP 5-9) + SOS near 0.40-0.50 + Decent OFF/DEF
```
Team has played very few games. Their raw SOS should be low, but low-sample shrinkage pulled it toward 0.5. With SOS at 60% weight, that free 0.15-0.20 boost in sos_norm translates to a 0.09-0.12 PowerScore boost — enough to jump 5-10 ranks.

**Root cause:** Shrinkage anchor at 0.5 is too generous for teams that haven't proven their schedule.

**Fix direction:** Lower the shrinkage anchor from 0.5 to 0.35, or make shrinkage asymmetric (pull low-SOS down more, pull high-SOS up less).

### Pattern C: "SOS Compression"
```
Top 30 teams all have sos_norm between 0.45-0.75
```
SOS has almost no variance in the top tier. Every top team looks like they have a "decent" schedule, so rankings are entirely determined by OFF+DEF (which only contribute 40% of the score). A team with mediocre SOS but great OFF/DEF can outrank a team with great SOS but slightly less OFF/DEF.

**Root cause:** PageRank dampening or percentile normalization compresses SOS values. The iterative Power-SOS co-calculation can also cause convergence toward the mean.

**Fix direction:** Use a wider SOS scale, reduce dampening, or increase SOS_POWER_ITERATIONS to let strong schedules separate more.

### Pattern D: "Cross-Age Leak"
```
Team plays opponents from different age groups, SOS seems inflated
```
If a U12 team plays a U14 opponent, the SOS calculation uses the global_strength_map for cross-age lookups. If that map is missing the opponent, it defaults to 0.5 (neutral) — giving free SOS credit for an unknown opponent.

**Root cause:** Missing cross-age opponent data or fallback to neutral strength.

**Fix direction:** Default unknown cross-age opponents to a lower baseline (e.g., 0.35 instead of 0.5).

### Pattern E: "State Cluster"
```
Multiple flagged teams from the same state (e.g., all from a small state)
```
Entire state leagues can be disconnected from the national graph. All teams in the state play each other, creating a closed component where SOS percentiles are meaningless relative to national competition.

**Root cause:** Geographic isolation in the game graph.

**Fix direction:** SCF (Schedule Connectivity Factor) should penalize this, or require a minimum number of out-of-state games for full SOS credit.

---

## Prompt for AI Review

Copy the script output and paste it with this prompt:

```
I ran a diagnostic on my soccer rankings engine. The output below shows
the top 30 teams per age/gender cohort with their PowerScore components.

Teams flagged with ⚠️ have sos_norm < 0.35 (weak schedule) but still
rank in the top 30.

Please analyze:
1. Which pattern best describes the flagged teams? (Bubble Champion,
   Shrinkage Beneficiary, SOS Compression, Cross-Age Leak, or State Cluster)
2. How many cohorts have the problem vs are clean?
3. What's the typical SOS gap between flagged teams and the teams ranked
   just above them?
4. Is the problem concentrated in specific ages, genders, or states?
5. Based on the PowerScore decomposition, is SOS actually differentiating
   teams or is OFF/DEF doing all the work?
6. What specific fix would you recommend and why?

Here's the output:
[PASTE OUTPUT HERE]
```

---

## Decision Matrix

After identifying the pattern, use this to decide what to fix:

| Pattern | Severity | Fix | Complexity | Risk |
|---------|----------|-----|------------|------|
| Bubble Champion | High | Stronger component shrinkage or absolute SOS anchoring | Medium | Low — only affects isolated components |
| Shrinkage Beneficiary | Medium | Lower shrinkage anchor (0.5 → 0.35) | Low | Low — only affects low-GP teams |
| SOS Compression | High | Reduce dampening, widen SOS scale | Medium | Medium — affects all teams |
| Cross-Age Leak | Low | Lower cross-age fallback baseline | Low | Low — only affects cross-age games |
| State Cluster | Medium | Require out-of-state games for full SOS | Medium | Medium — may penalize legitimate small-state teams |

---

## Metrics to Track After a Fix

After implementing any fix, re-run the diagnosis and compare:

1. **Count of bad-SOS teams in top N** — should decrease
2. **SOS std in top teams** — should increase (more differentiation)
3. **Weak-Mid overlap** — the max PowerScore of bottom-tier teams should stay below the min PowerScore of mid-tier teams
4. **Rank correlation with previous week** — shouldn't change more than 5-10% (stability)
5. **GP-SOS correlation** — should stay within ±0.10 (no games-played bias)
