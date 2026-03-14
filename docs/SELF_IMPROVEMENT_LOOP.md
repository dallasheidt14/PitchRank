# SELF_IMPROVEMENT_LOOP.md — PitchRank

_Last updated: 2026-03-12_

## Purpose
Turn the PitchRank automation stack into a continuous-learning system that can observe, measure, improve, and revert safely.

```
Observe → Measure → Analyze → Improve → Repeat
```

## 1. Metrics Per Agent

| Agent | Core Metrics | Targets |
|-------|--------------|---------|
| Scrappy | games discovered per run, scrape success %, freshness lag | >5k/week, <1% errors, <24h lag |
| Cleany | duplicates resolved, quarantine backlog, false merge rate | >50/week, <1000 backlog, 0% false merge |
| Qualityy | anomaly rate, invalid scores detected, volatility flags | <5 WARN/week, 0 FAILs without escalation |
| Ranky | runtime, ranking volatility, PASS/FAIL status | <20 min runtime, <100 median movement |
| Movy | movers detected, preview accuracy | >=10 movers, 95% preview match accuracy |
| Explainy | stories delivered, citation accuracy | >=3/edition, 100% sourced |
| Socialy | drafts/week, engagement (CTR) | >=3/week, CTR up MoM |
| Blogy | posts/week, organic clicks | 1/week, clicks up MoM |
| COMPY | learnings promoted, stale learnings removed | ≥3 promotions/week, stale items cleared |
| Overseer/Watchy | cron failures caught, incident MTTR | 0 misses, <1h MTTR |

All metrics go into `reports/system_scorecard.json` (machine readable) and `reports/system_status.md` (narrative).

## 2. What Counts as an Optimization
- Changes to scrapers, cleaning thresholds, anomaly detectors.
- Performance tweaks (runtime, caching) that alter SLAs.
- Messaging/SEO experiments (copy, headlines, CTAs).
- Any automation that changes workflow order or gating logic.

## 3. Controlled Experiment Layer
1. **Proposal:** Agent documents hypothesis, metric to move, rollback plan.
2. **Shadow mode:** Run new logic alongside current (“control vs experiment”).
3. **Compare:** Evaluate against metrics table.
4. **Decide:** If improvement, promote; else revert.

Use `reports/optimization_log.md` to record every experiment (see section 5).

## 4. Promotion Pathway for Learnings
```
Daily log (memory/YYYY-MM-DD.md)
→ docs/LEARNINGS.md (repeated issue)
→ .claude/skills/* (operational pattern)
→ SOURCE_OF_TRUTH.md (critical rule)
```
COMPY owns the promotion queue and references evidence for every promotion/demotion.

## 5. Optimization + Rollback Registry
Create entries in `reports/optimization_log.md` with:
- timestamp
- agent proposing change
- hypothesis
- files/scripts touched
- before metrics
- after metrics
- rollback instructions + status

No optimization leaves shadow mode until this record exists.

## 6. Escalation Bands
- **Auto:** Safe documentation updates, read-only analysis, telemetry scripts.
- **Review:** Scraper logic, anomaly thresholds, SEO strategy, automation wiring.
- **Human-only:** Ranking algorithm, team merge logic, irreversible publishing, secrets.

Overseer enforces the bands; anything in human-only must be approved explicitly by D H.

## 7. Beliefs Layer
- `memory/beliefs.md` captures distilled truths. COMPY reviews weekly and keeps it lean.

## 8. Scorecard
- JSON: `reports/system_scorecard.json`
- Markdown: `reports/system_status.md`
- Refresh at least once per day (blocked until Supabase DB creds fixed).

## 9. Shadow Mode Guidance
- Always run control + experiment in parallel (Scrappy vs Scrappy-Shadow, Cleany vs Cleany-Shadow, etc.).
- Compare duplicates removed, anomalies, runtime before promoting.

## 10. Responsibilities
- **Overseer:** Owns telemetry + enforcement.
- **Qualityy:** Gate for Ranky, validates experiment safety.
- **COMPY:** Promotion pipeline + beliefs + documentation.
- **Codey/Fixy:** Implement code when experiments graduate.

This file is the single source of truth for the self-improvement engine. Update it whenever processes change.
