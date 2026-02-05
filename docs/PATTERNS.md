# PitchRank Patterns

> Proven solutions discovered by agents. Auto-updated by COMPY nightly. Append-only.

## Data Processing Patterns

### 2026-02-04: Team Division Separation (HD vs AD)
Legitimate squads within the same club must stay separate:
- **AD** (Academy Division): Younger/developing players
- **HD** (Higher Division): Elite/older players  
- **Strategy**: Teams may exist in multiple division sources; use provider aliases (`_AD`, `_HD` suffixes) to determine which division they belong to
- **Tool**: `scripts/unmerge_hd_ad_teams.py --execute` separates incorrectly merged teams
- **Learned**: First-created division determines the original team name; newer divisions get merged aliases

### 2026-02-04: Data Quality Metrics to Track Weekly
Establish baseline metrics and trend them:
- Teams without club selection (should be < 100)
- Teams missing `club_name` field (should be < 500)
- Stale teams (not scraped in 7+ days)

These metrics indicate data entry errors or scraper coverage gaps.

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

### 2026-02-02: Sub-Agent Delegation for Investigation
When monitoring agents (Scrappy, Watchy) detect issues:
1. Don't investigate inline — it blocks monitoring
2. Spawn sub-agent (Codey) with specific investigation task
3. Continue monitoring while investigation runs async
4. Receive completion notification when done

**Example**: Scrappy detected TGS scrape failure → spawned "Codey: Investigate failed TGS scrape" → received findings asynchronously.

## Infrastructure Patterns

### 2026-02-04: Supabase Connection Strategy (Direct vs Pooler)
- **For local scripts/CLI**: Use direct connection (`postgresql://postgres:pass@db.REGION.supabase.co:5432/postgres`)
  - Faster, fewer hops, no connection pooling overhead
  - Only works with IPv6 access (local machines, not CI/CD)
  
- **For GitHub Actions/CI/CD**: Use pooler connection (`postgresql://postgres.REGION:pass@aws-1-us-west-1.pooler.supabase.com:5432/postgres`)
  - IPv4-compatible, works in GitHub Actions runners
  - Check Supabase dashboard for actual pooler hostname (varies by region)

- **For remote/server access**: Use pooler connection
  - More reliable, connection pooling improves concurrency
  - Better for long-lived connections

### 2026-02-04: Multi-Iteration CI/CD Debugging Pattern
When GitHub Actions fails mysteriously:
1. **Try quick fix** (env var, simple workaround)
2. **If fails, diagnose root cause** (protocol? hostname? auth?)
3. **Research the system** (what does GH Actions support?)
4. **Document actual solution** for others
5. **Verify in production** before declaring done

Example: GH Actions pooler issue took 5 commits because each iteration revealed new information about IPv6/IPv4 networking.

## Performance Patterns

<!-- COMPY will append performance patterns here -->

## Testing Patterns

<!-- COMPY will append testing patterns here -->

---
*Last updated: 2026-02-01*
