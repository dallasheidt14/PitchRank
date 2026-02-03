# PitchRank Gotchas

> Common pitfalls discovered by agents. Auto-updated by COMPY nightly. Append-only.

## Database Gotchas

<!-- COMPY will append database gotchas here -->

## Scraping Gotchas

<!-- COMPY will append scraping gotchas here -->

## Data Quality Gotchas

<!-- COMPY will append data quality gotchas here -->

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

---
*Last updated: 2026-02-02*
