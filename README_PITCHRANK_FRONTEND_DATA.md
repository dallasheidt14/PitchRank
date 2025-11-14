# ⚽️ PitchRank Frontend Data Contract & Implementation Guide

This document explains exactly how the PitchRank frontend must consume and display rankings data from the backend.

It exists so Cursor (and future engineers) always follow the correct rules when updating components.

---

# 🟦 1. Primary Metrics (Frontend MUST Use These)

### **PowerScore**

- **Field:** `power_score_final`
- **Range:** `0.0 – 1.0`
- **Meaning:**  
  ML-enhanced ranking score (Layer 13), with fallback to non-ML adjusted score.
- **Display format:**
  ```ts
  formatPowerScore(value) = (value * 100).toFixed(2)
  ```
  Example: `0.4150` → `"41.50"`

### **Strength of Schedule (SOS)**

- **Field:** `sos_norm`
- **Range:** `0.0 – 1.0`
- **Meaning:**
  Normalized strength of schedule within each age group and gender.
- **Display format:**
  ```ts
  formatSOSIndex(value) = (value * 100).toFixed(1)
  ```
  Example: `0.731` → `"73.1"`

---

# 🟦 2. Required TypeScript Interface

Frontend must use shared type:

```ts
import type { RankingRow } from "@pitchrank/types";
```

**Shape includes:**

- `team_id_master`
- `team_name`
- `club_name`
- `age`, `gender`, `state`
- `games_played`
- `power_score_final`
- `sos_norm`
- `offense_norm`, `defense_norm`
- `rank_in_cohort_final`, `rank_in_state_final`
- ML diagnostic fields (optional)

---

# 🟦 3. Formatting Utilities

**Located in:** `frontend/lib/utils.ts`

```ts
export function formatPowerScore(ps?: number | null) {
  if (ps == null) return "—";
  return (ps * 100).toFixed(2);
}

export function formatSOSIndex(sosNorm?: number | null) {
  if (sosNorm == null) return "—";
  return (sosNorm * 100).toFixed(1);
}
```

**All front-end components MUST use these helpers.**

---

# 🟦 4. Components That MUST Use These Metrics

### RankingsTable.tsx

- Display → `formatPowerScore(row.power_score_final)`
- Display → `formatSOSIndex(row.sos_norm)`
- Sort by `power_score_final` & `sos_norm`

### TeamHeader.tsx

- PowerScore → `formatPowerScore()`
- SOS → `formatSOSIndex()`
- Add tooltips for both metrics

### ComparePanel.tsx

- All PowerScore values → `formatPowerScore()`

### HomeLeaderboard.tsx

- PowerScore → `formatPowerScore()`

### test/page.tsx

- PowerScore → `formatPowerScore()`

---

# 🟦 5. Fields Frontend MUST NOT Use

These are backend-internal or deprecated:

- ❌ `power_score`
- ❌ `national_power_score`
- ❌ `strength_of_schedule`
- ❌ `abs_strength`
- ❌ `anchor`
- ❌ `powerscore_adj` (diagnostic only)
- ❌ `powerscore_ml` (use `power_score_final` instead)
- ❌ `sos` (raw SOS, not normalized)

---

# 🟦 6. Tooltip Text (Canonical)

### PowerScore (ML Adjusted)

> A machine-learning–enhanced ranking score that measures overall team strength based on offense, defense, schedule difficulty, and predictive performance patterns.

### SOS Index

> Strength of Schedule normalized within each age group and gender (0 = softest schedule, 100 = toughest).

---

# 🟦 7. API / OpenAPI Notes

The backend guarantees:

- `power_score_final` always exists
- `sos_norm` always exists
- Ranking order is sorted by `power_score_final` DESC

OpenAPI schema lives in:
`docs/openapi-rankings.json`

---

# 🟦 8. Versioning Strategy

- Backward-compatible additions are allowed anytime
- Removing fields requires a `/v2/rankings` endpoint
- Frontend must ignore unknown fields
- Shared types live in `@pitchrank/types` package
- Backend will never break `power_score_final` or `sos_norm`

---

# 🟩 Summary

This document ensures:

- Frontend always uses the correct metrics
- Backend can evolve safely (ML upgrades, SOS improvements, global rankings, etc.)
- Cursor can safely perform updates without accidentally breaking UI
- PitchRank stays stable, scalable, and accurate

---

# 🚀 Next Steps  

If you'd like, I can also generate:

- ✅ **A GitHub Issue template**  
- 📦 **A monorepo structure diagram**  
- 🧪 **A Vitest/Jest test suite for formatters**  
- 📘 **Docs for future engineers on "How PitchRank Rankings Work"**  

Just tell me!

