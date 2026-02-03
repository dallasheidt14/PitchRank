# Ranky Learnings

> Auto-updated by COMPY nightly. Append-only.

## Rankings Calculation Patterns

### 2026-02-02: Initial Setup
- Rankings use v53e algorithm with ML Layer 13 adjustments
- Calculation takes 10-20 minutes for ~41k ranked teams
- PowerScores should be in range [0.0, 1.0]

## Verification Gotchas

### 2026-02-02: PowerScore Swings
Large PowerScore swings (15-43%) between snapshots can occur from:
- SOS recalculation (opponents' results changed)
- New games batch imported
- Teams changing cohorts (different age groups have different team counts)

**Not necessarily a bug** — but worth investigating if multiple unrelated teams swing together.

## Performance Notes

<!-- COMPY will append performance insights here -->

## Algorithm Edge Cases

<!-- COMPY will append edge cases here -->

---
*Last updated: 2026-02-02*
