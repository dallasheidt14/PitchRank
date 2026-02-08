# Watchy Learnings

> Auto-updated by COMPY nightly. Append-only.

## Monitoring Patterns Discovered

### 2026-02-02: Model Name Configuration Issue
Watchy encountered a 404 error for `claude-3-5-haiku-latest` model. This model name alias may not be valid on the API.
- **Fix**: Use explicit model versions like `claude-3-5-haiku-20241022` instead of `-latest` aliases
- **Impact**: Health checks failed to run due to model lookup failure

### 2026-02-03: Model Error Persists in Health Check Cron
Daily health check cron (2026-02-03 08:23) failed again with 404 on `claude-3-5-haiku-latest`:
- **Issue**: Model alias still not fixed in cron job configuration
- **Priority**: HIGH — health checks are not running, blind spot for system monitoring
- **Action**: Need to update cron model configuration to use explicit pinned model version
- **Blocker**: Watchy sessions cannot initialize without valid model specification

<!-- COMPY will append learnings here -->

## Alert Thresholds Tuned

<!-- COMPY will append threshold insights here -->

## False Positive Patterns

<!-- COMPY will append false positive patterns here -->

## Date: 2026-02-04

### What Worked Well
- **Data quality metrics discovery:** Successfully identified 475 teams with "No Club Selection" and 3,772 teams with missing `club_name` field
- **Quarantine analysis:** Baseline established for quarantine trends — can now track if this number grows/shrinks over time
- **Health pattern consistency:** Same monitoring approach works reliably when model is configured correctly

### Metrics & Thresholds Discovered
From Feb 4 data quality check:
- **Teams with no club:** 475 (concerning — these can't be ranked properly)
- **Teams with missing club_name:** 3,772 (data quality debt)
- **Stale teams:** 47,996 teams not scraped recently
- **Quarantine games:** 0 (clean state)

**Alert suggestions:**
- 🟡 WARN if teams_without_club > 500
- 🔴 CRITICAL if teams_without_club > 1000 (breaks ranking engine)
- 🟡 WARN if missing_club_name > 5000

### Gotchas Discovered
- **Club selection status:** Teams created without explicit club selection remain orphaned. Need data cleanup or UI validation on team creation
- **Stale team tracking:** High number (47k) suggests scraping isn't covering all teams or isn't triggering frequently enough

### For Next Time
- Compare club selection metrics week-to-week to detect data entry problems
- Alert D H immediately if any team without club exceeds 1,000
- Consider blocking team creation without explicit club assignment in UI

## Date: 2026-02-06

### What Worked Well
- **Quarantine investigation pattern:** Successfully identified root cause (U8 age group rejections) and clearly presented three options to D H
- **No false alarm:** Watchy correctly assessed this as "working as designed" not a bug
- **Clear escalation:** Presented decision matrix to D H: (1) Clear quarantine, (2) Expand age range, (3) Filter upstream
- **Sub-agent spawning:** Handed off investigation to Codey for deeper analysis while continuing scheduled monitoring

### Gotchas Discovered
- **Policy-dependent data validation:** What's a "bug" depends on project scope (U10+ only vs U8+ support). Need to confirm business rules before flagging anomalies.
- **Quarantine backlog persistence:** Same U8 games appearing multiple days (916 + 794 = 1,710) suggests they're not being auto-cleared or archived

### For Next Time
- When identifying consistent backlog patterns, propose architectural solutions (auto-clear vs expand support)
- Age group filtering is a business policy decision, not just a data quality issue
- Scraper filtering upstream (GotSport step) may be more efficient than quarantine processing

## Date: 2026-02-07

### Daily Health Check (8:00 AM MT)
Executed successfully with full autonomy mode enabled:
- **Review queue:** 6,121 pending (D H is actively working, not an alert condition)
- **Key decision:** With autonomy granted, Watchy can now triage alerts more aggressively based on DECISION_TREES
- **Alert discipline:** Confirmed rule from DAILY_CONTEXT — don't alert about review queue when D H actively working through it

### Pattern: Autonomy Changes Alert Behavior
Before autonomy (ask first):
- Flag everything as "FYI, here's what I found"
- Wait for D H to decide if it's actionable

After autonomy (act on known patterns):
- Apply DECISION_TREES to triage automatically
- Only escalate truly exceptional conditions
- Report summary, not raw data

**Watchy's new role:** Filter noise, report only genuine anomalies
