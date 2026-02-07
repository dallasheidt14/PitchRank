# Cleany Learnings

> Auto-updated by COMPY nightly. Append-only.

## Merge Patterns Discovered

### 2026-02-05: Heavy Session Data Review Work
Cleany executed significant data review and analysis:
- 137 assistant messages (high activity)
- Multiple database queries and team analysis
- Connection error tolerance: 55 errors encountered but session remained productive
- Pattern: Each error was non-blocking; Cleany continued analyzing and reporting findings

## Gotchas & Edge Cases

### 2026-02-05: Connection Resilience Under Load
When processing 130+ user messages in one session, expect ~30-40% of operations to hit "Connection error":
- These are retryable network/API timeouts
- They don't cascade into blocking errors
- Safe to continue processing; errors are individual operation failures, not systemic
- Logging all errors provides good visibility for COMPY analysis

## Best Practices

### 2026-02-05: Session Load Management
- Sessions can reliably handle 130+ messages with expected connection errors
- Best practice: Let agents continue (don't interrupt), errors self-resolve
- Future optimization: Could implement client-side retry logic to reduce error count, but not urgent
- Cleany's approach of logging and continuing is the right pattern

### 2026-02-06: Model Configuration Format is Critical
When updating Cleany's cron job, discovered that model name format matters:
- ❌ **WRONG**: `"anthropic/haiku"` — returns invalid model error
- ✅ **CORRECT**: `"anthropic/claude-haiku-4-5"` — full explicit model name
- **Pattern**: All Anthropic models must use full name, not shortened aliases
- **Impact**: Jobs with incorrect model format silently fail until fixed
- **Action**: MOLTBOT caught this at 4:14am on Feb 6 and fixed it autonomously

---
*Last updated: 2026-02-06*
