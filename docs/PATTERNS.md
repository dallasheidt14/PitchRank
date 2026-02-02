# PitchRank Patterns

> Proven solutions discovered by agents. Auto-updated by COMPY nightly. Append-only.

## Data Processing Patterns

<!-- COMPY will append data patterns here -->

## Error Handling Patterns

### 2026-02-01: API Error Detection and Halting
When API authentication fails, implement circuit breaker pattern:
1. Detect 401/400 errors from API providers
2. Stop retrying immediately on auth failures  
3. Alert user about credential/billing issues
4. Don't cascade hundreds of failed requests

## Tool Usage Patterns

### 2026-02-01: Core Workflow Tools
High-activity sessions show consistent tool usage patterns:
- `exec` (2 uses) - Essential for system operations
- `read` (1 use) - File access for context
- `edit` (1 use) - Content modification  
- `message` (1 use) - Communication
- `browser` (1 use) - Web interaction

**Insight**: These 5 tools form the core workflow. Ensure they're optimized and reliable.

## Performance Patterns

<!-- COMPY will append performance patterns here -->

## Testing Patterns

<!-- COMPY will append testing patterns here -->

---
*Last updated: 2026-02-01*
