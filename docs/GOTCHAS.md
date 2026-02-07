# PitchRank Gotchas

> Common pitfalls discovered by agents. Auto-updated by COMPY nightly. Append-only.

## Database Gotchas

<!-- COMPY will append database gotchas here -->

## Scraping Gotchas

<!-- COMPY will append scraping gotchas here -->

## Data Quality Gotchas

<!-- COMPY will append data quality gotchas here -->

## Infrastructure Gotchas

### 2026-02-04: Supabase Connection Types Have Different Requirements
Supabase provides two connection URLs with different purposes:
- **Direct Connection** (`db.REGION.supabase.co:5432`): Uses IPv6, works great for local CLI/scripts, NOT accessible from GitHub Actions
- **Pooler Connection** (`aws-1-us-west-1.pooler.supabase.com:5432`): Uses IPv4, required for GitHub Actions and remote CI/CD

**Gotcha**: GitHub Actions runners only have IPv4 connectivity. Direct Supabase connections fail silently with connection timeouts (no error message). Solution: Use pooler URL for all CI/CD workflows.

**Username format differs too:**
- Direct: `postgres` (use `postgres:[password]@db.xxx.supabase.co`)
- Pooler: `postgres.[PROJECT_ID]` (use `postgres.xxx:[password]@pooler...`)

### 2026-02-04: GitHub Actions IPv6-Only Services Are Unreachable
GitHub Actions runners only have IPv4 network access. Services that only listen on IPv6 (like direct Supabase connections) are unreachable, producing timeouts with no error output.

**Error signature:** Workflow hangs or times out on database connection step with generic "connection timeout" message.

**Solution:** Always use pooler URLs or services that support IPv4 in CI/CD workflows.

## Network Gotchas

### 2026-02-03: Connection Errors Under Load
When running 900+ messages in main session with concurrent sub-agent spawning, expect ~200-250 "Connection error" entries:
- These appear to be network timeouts or brief connectivity issues
- They don't block agent operation (main session stayed functional)
- Likely caused by API rate limits or server-side resource constraints under load
- Mitigation: Spread workload across multiple sessions, use exponential backoff on retries

### 2026-02-05: Connection Errors Pattern Confirmed
Cleany session hit 55 "Connection error" entries over 137 messages during data review work. Main session concurrently hit 46 errors over 160 messages.
- **Pattern**: Heavy agent activity (>130 user messages) correlates with ~40-55 connection errors
- **Tolerance**: System remains fully functional despite error rate (~30-40% of heavy sessions)
- **Likely cause**: API/network throttling, brief hiccups on Anthropic API under load
- **Best practice**: Continue current pattern (errors are expected, not critical), but add connection error metrics to monitoring

## API Gotchas

### 2026-01-31: Anthropic API Error Patterns
When encountering Anthropic API errors, check these in order:
1. **401 "invalid x-api-key"** → API key is wrong or expired. Verify `ANTHROPIC_API_KEY` env var.
2. **400 "credit balance too low"** → Account needs credits. Check billing at console.anthropic.com
3. **Connection errors** → Network issues or API outage. Retry with exponential backoff.

These errors can cascade (136 errors in one session) when the root cause isn't addressed. Fix auth/billing first before retrying.

### 2026-02-01: API Error Cascading Confirmed
Today's main session had 174 errors, confirming the cascading pattern:
- Multiple 401 "invalid x-api-key" errors
- 400 "credit balance too low" errors  
- Several connection errors

**Key insight**: Once API auth fails, it creates a storm of follow-up errors. The agent keeps retrying with the same bad credentials. Need better error handling to detect and halt on auth failures.

### 2026-02-02: Model Name Aliases Can Fail
Watchy hit a 404 for `claude-3-5-haiku-latest` model. The `-latest` alias may not resolve on all API endpoints.
- **Gotcha**: Don't assume `-latest` model aliases work everywhere
- **Fix**: Use explicit dated model versions (e.g., `claude-3-5-haiku-20241022`)

### 2026-02-02: Session/Agent Attribution Mismatch
Sessions can be attributed to different agents than who's actually running:
- Movy session showed "You are Codey 💻" prompts
- Codey session ran as "Ranky 📊"

**Gotcha**: Cron job naming may not match actual agent identity. When debugging, check the prompt content, not just the session label.

### 2026-02-06: Model Name Format in Cron Jobs
When updating model configuration in cron jobs, use the full explicit model name:
- ❌ **WRONG**: `"anthropic/haiku"` — Returns "model not found" error
- ✅ **CORRECT**: `"anthropic/claude-haiku-4-5"` — Full explicit name required

**Gotcha**: Shortened aliases that work in some contexts (like CLI overrides with `model=haiku`) don't work in cron job YAML configuration. The cron system requires full provider/model-version format.

**Where this bit us**: Cleany's weekly cron was set to `"anthropic/haiku"` and silently failed until MOLTBOT fixed it at 4:14am on Feb 6. The agent caught the error during model initialization.

---
*Last updated: 2026-02-06*
