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

---
*Last updated: Initial creation*
