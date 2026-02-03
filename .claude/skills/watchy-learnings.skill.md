# Watchy Learnings

> Auto-updated by COMPY nightly. Append-only.

## Monitoring Patterns Discovered

### 2026-02-02: Model Name Configuration Issue
Watchy encountered a 404 error for `claude-3-5-haiku-latest` model. This model name alias may not be valid on the API.
- **Fix**: Use explicit model versions like `claude-3-5-haiku-20241022` instead of `-latest` aliases
- **Impact**: Health checks failed to run due to model lookup failure

<!-- COMPY will append learnings here -->

## Alert Thresholds Tuned

<!-- COMPY will append threshold insights here -->

## False Positive Patterns

<!-- COMPY will append false positive patterns here -->

---
*Last updated: Initial creation*
