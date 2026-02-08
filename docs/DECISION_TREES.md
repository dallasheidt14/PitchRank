# Decision Trees for PitchRank Agents

> Structured knowledge for autonomous decision-making. Agents: read this BEFORE acting.

## Format
```
WHEN: <trigger condition>
CHECK: <diagnostic step>
IF: <condition> → <action>
ELSE: <fallback>
ESCALATE: <when to alert D H>
```

---

## 🔧 Model & API Errors

### Model Not Found (404)
```
WHEN: Model error / 404 / "unknown model"
CHECK: Is it using an alias like `-latest` or `haiku`?
IF: Yes → Use pinned version: `anthropic/claude-haiku-4-5` or `anthropic/claude-sonnet-4-5`
IF: Pinned version also fails → Check API key validity
ESCALATE: If pinned model fails with valid key
```

### API Auth Error (401)
```
WHEN: 401 Unauthorized / auth failure
CHECK: Is API key set in environment?
IF: Missing → Check .env file, restart gateway
IF: Present but failing → API key may be revoked/expired
ESCALATE: Immediately — blocks all agents
```

### Rate Limit / Credit Balance
```
WHEN: 429 or credit balance error
CHECK: Is this a long-running operation?
IF: Yes → Add delays, reduce batch size
IF: Persistent → Check billing/credits
ESCALATE: If billing issue persists >1 hour
```

---

## 📊 Data Quality Issues

### High Quarantine Count
```
WHEN: quarantine_games > 100
CHECK: What's the pattern? Run: SELECT age_group, COUNT(*) FROM quarantine_games GROUP BY age_group
IF: Single age group (e.g., U8) → Policy decision, not bug. Ask D H if we support this age.
IF: Mixed ages → Likely team matching issue. Check team_match_review_queue.
IF: Provider-specific → Check provider's data format changed
ESCALATE: If >1000 AND no clear pattern
```

### Zero Games Imported
```
WHEN: Import completes with 0 new games
CHECK: Were there duplicates?
IF: High duplicates (>50%) → Events already scraped. Normal.
IF: High quarantine → Team matching issues (see above)
IF: Neither → Check scraper output, may be empty events
ESCALATE: Only if expected new data and got nothing
```

### Match Review Queue Backlog
```
WHEN: team_match_review_queue > 5000
CHECK: Is D H actively reviewing?
IF: Yes → Don't alert, they know
IF: No + growing → May need automated cleanup rules
IF: Sudden spike → Check recent import for bad data
ESCALATE: Only if D H not reviewing AND queue > 10000
```

---

## 🕷️ Scraping Issues

### Scrape Workflow Timeout
```
WHEN: GH Action hits 6h timeout
CHECK: How many events were requested?
IF: >20 events → Too many. Split into smaller batches (10 max)
IF: <20 events → Import step is slow. Check DB performance.
IF: Stuck on same step → May be deadlock. Cancel and retry.
ESCALATE: If 3+ consecutive timeouts
```

### Scrape Returns No Games
```
WHEN: Scrape completes but 0 games found
CHECK: Is the event ID valid?
IF: Event exists but empty → Tournament may not have started
IF: Event 404s → Invalid event ID
IF: Event has games on website but not scraped → Parser may need update
ESCALATE: If parser seems broken (spawn Codey)
```

### Provider Format Changed
```
WHEN: Scraper errors with parse/format issues
CHECK: Has provider website changed?
IF: Yes → Spawn Codey to investigate and fix parser
IF: No → May be temporary issue, retry once
ESCALATE: If parser fix needed (Codey handles)
```

---

## 📈 Rankings Issues

### Rankings Calculation Fails
```
WHEN: calculate_rankings.py errors
CHECK: What's the error type?
IF: DB connection → Check DATABASE_URL, Supabase status
IF: Memory error → Too many teams? Check for data explosion
IF: Algorithm error → Spawn Codey with full error log
ESCALATE: If rankings are >24h stale
```

### Rankings Look Wrong
```
WHEN: Team ranks seem off / "eye test" fails
CHECK: Does team have enough games? (need 3+ for reliable ranking)
IF: Few games → Expected variance, not a bug
IF: Many games but wrong → Check if games are being double-counted (merge issue)
IF: Sudden rank change → Check recent game imports for that team
ESCALATE: If systematic issue affects many teams
```

---

## 🔄 Workflow Patterns

### Long-Running Script
```
WHEN: Script takes >10 minutes locally
CHECK: Does it hit external APIs or DB heavily?
IF: Yes → Migrate to GitHub Action (saves API credits)
IF: No → Profile for optimization opportunities
ACTION: Create GH workflow, add to appropriate cron schedule
```

### Sub-Agent Task Handoff
```
WHEN: Need specialized work done
CHECK: What type of work?
IF: Code fix/creation → Spawn Codey (Sonnet, or Opus if complex)
IF: Data analysis/content → Spawn Movy
IF: Investigation → Spawn Codey with investigation prompt
IF: Cleanup/hygiene → Usually Cleany's cron handles it
ALWAYS: Include full context + error logs in spawn task
```

### Cron Job Failed
```
WHEN: Cron shows lastStatus: "error"
CHECK: What's the error message?
IF: Model error → Fix model name (see Model Not Found above)
IF: Script error → Spawn Codey to fix
IF: Timeout → Job is too big, split it up
ACTION: Fix autonomously if clear pattern, otherwise escalate
```

---

## 🚨 Escalation Rules

### Always Escalate
- Data pipeline down (0 games for 48h+)
- Multiple agent failures in same day
- Anything affecting live rankings accuracy
- Security/auth issues
- Decisions requiring business judgment

### Handle Autonomously
- Model config fixes
- Small quarantine backlogs (<500)
- Duplicate data (already imported)
- Retry transient failures
- Clear pattern matches from this doc

### Ask First
- Structural changes to DB
- New scraper targets
- Changes to ranking algorithm
- Anything not covered here

---

*Last updated: 2026-02-07 by Moltbot*
*COMPY: Append new patterns below, do not modify above*

## New Patterns (COMPY appends here)

