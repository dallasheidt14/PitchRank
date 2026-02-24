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

### Persistent Connection Errors (Billing Crisis Pattern - Feb 7-13)
```
WHEN: Multiple agents see "Connection error" in same 24h window
CHECK: Is this happening across >2 agents?
IF: Yes across Codey + Main + Scrappy → Likely API/infrastructure issue
IF: Error count rising day-over-day (Feb 10: 5 → Feb 11: 14 → Feb 12: 9) → Sustainability concern
IF: Correlates with Anthropic billing status → CRITICAL
ESCALATE: IMMEDIATELY if error trend shows sustained elevation
NOTE: Feb 7-13 billing crisis caused 28+ errors across 6 days. System remained functional but at risk.
LEARNED: Monitor error rate as leading indicator of infrastructure health.
```

### Timeout Spikes on High-Load Days (Feb 23 Pattern - NEW)
```
WHEN: See "Request timed out" errors across multiple agents in same 24h window
CHECK: What day/time are these occurring?
IF: Monday afternoon (post-scrape window, ~10am-2pm) → Likely concurrent load spike
IF: Error count >4x baseline (baseline 5-7/day, spike 20+/day) → Load saturation
IF: Cleany heartbeat + Ranky calculation running concurrently → High database query load

PATTERN DISCOVERED (Feb 23):
- Monday 10am: Scrappy monitors scrape
- Monday 12pm: Ranky calculates rankings (heavy query load)
- Monday evening: Cleany heartbeat (agent status checks, cron list queries)
- Result: 30 errors (4x baseline) across 7 sessions, mostly timeouts

DIAGNOSIS:
- All agents completed work successfully (errors are non-blocking)
- Suggest concurrent cron jobs creating API/database saturation
- Timeout signature: "Request timed out" (not connection error)

IF: Single occurrence on Monday → Normal load pattern, monitor for weekly trend
IF: Sustained >20 errors/day → System capacity concern
IF: Escalating trend (e.g., Wed reaches 30 errors) → Infrastructure bottleneck

ACTION:
- Continue monitoring Feb 24-25 to establish if this is weekly pattern
- If sustained: Consider cron staggering (Ranky 12:30pm, Watchy 8:30am)
- If escalating: Escalate to D H for infrastructure review

ESCALATE: If error rate stays >20/day for 3+ consecutive days

LEARNED: High-concurrency windows (post-scrape) are normal stress points. System handles gracefully but worth monitoring for capacity planning.
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

### U19 Recurring Quarantine Pattern (Feb 16-18 Discovery)
```
WHEN: Same age group (U19) re-appearing in quarantine across multiple scraper runs
CHECK: Which scrapers are pulling U19 events?

PATTERN DISCOVERED (Feb 16-18):
- Feb 16 7:35am: TGS pulled 726 U19 games → quarantine spiked to 777
- Feb 17 8:00am: Quarantine dropped to 65 (cleanup or auto-decision)
- Feb 18 8:00am: GotSport pulled 632 U19 games → quarantine spiked to 697

ROOT CAUSE: Both TGS and GotSport independently pulling U19 (high school) events from their data sources.
This is NOT a bug — it's a business policy decision about age group support.

DECISION OPTIONS (LEVEL 4 ESCALATION - AWAITING D H):
A) Add U19 to supported ages → Update validate logic (2 lines), update calculate_rankings.py
B) Filter U19 at BOTH scrapers (TGS + GotSport config) → Upstream prevention
C) Leave in quarantine → Accept that these events queue up, don't rank them

CURRENT STATUS (Feb 18):
- Decision still pending (since Feb 16)
- Quarantine will continue to oscillate as scrapers run
- Each scraper cycle adds ~600-700 U19 games if both are pulling

ALERT: D H must choose A/B/C TODAY — each delay means another scraper run will repopulate quarantine

IF: A chosen → Make changes immediately (Codey can do in <5 min)
IF: B chosen → Update TGS + GotSport scraper config to exclude U19
IF: C chosen → Accept oscillating quarantine, no further action

ESCALATE: LEVEL 4 (❓ Decision Needed) — This cannot wait. Escalate as "U19 policy decision needed ASAP"
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

## ⚙️ GitHub Actions & Secrets Management

### Action Fails with "Secret Not Found" / "Undefined"
```
WHEN: GitHub Action fails because env var is undefined (e.g., SUPABASE_URL, API_KEY)
CHECK: Is the secret defined in repo Settings > Secrets?
IF: Missing → Must add it to GitHub repo secrets AND reference in action YAML
IF: Present → Check action YAML for typo in ${{ secrets.SECRET_NAME }}
IF: Typo not obvious → Check the workflow file path is correct in .github/workflows/

LEARNED PATTERN (Feb 15):
- Auto-merge-queue workflow failed because GH Actions didn't have SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
- Fix: Cleany added both secrets to repo + re-triggered workflow
- Now passes consistently

PREVENT: Before spawning any agent that writes DB in GH Actions:
  1. Verify all required secrets exist in GitHub repo
  2. Verify YAML references them correctly
  3. Test locally first if possible
  
ESCALATE: Only if secret can't be recovered (lost credentials)
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

## 🚨 Escalation Ladder (Alert Routing)

**All agents: Follow this ladder strictly. No surprises.**

### LEVEL 0: SILENT (Log Only)
**When:** Issue is expected, non-blocking, or already being handled
- Transient network errors (auto-retry)
- Duplicate data imports (normal)
- Scrape age on non-scrape days (expected gaps)
- Review queue count (D H actively working it)
- Stale teams refreshed Mon/Wed (expected)

**Action:** Log to AGENT_COMMS.md, continue working.

---

### LEVEL 1: FILE UPDATE (AGENT_COMMS.md)
**When:** Issue found, fix in progress, no human input needed
- Code fix spawned to Codey (note in comms what was spawned)
- Data quality pattern identified (log finding + action)
- Slow operation detected but within 3x baseline (log, profile later)
- New pattern discovered worth documenting

**Action:** Post to AGENT_COMMS.md Live Feed with:
```
### [TIME] AGENT_NAME
Issue: [what you found]
Action: [what you're doing]
Status: [in progress / fixed / blocked]
```

**Wait for:** Nothing. Move on.

---

### LEVEL 2: TELEGRAM ALERT (This Chat)
**When:** Issue needs human awareness but NOT emergency

- Single cron job failed (agent error, you should know)
- API/auth error that required workaround
- Data quality issue that can't be auto-fixed
- Slow operation >3x baseline (needs investigation)
- Quarantine spike >500 in single import
- Codey spawned to fix something significant
- Ranking accuracy concern (needs eye test)

**Action:** Use sessions_send() or message tool to post to this chat:
```
⚠️ **[Agent Name] Alert**
Issue: [what happened]
Action taken: [what we're doing]
Need decision on: [if anything]
```

**Example:**
```
⚠️ **Codey Alert**
Found 847 quarantine games after GotSport import.
Spawned Cleany to analyze patterns.
Checking if data quality issue or known pattern.
```

**Wait for:** D H response if you included a question. Otherwise, continue.

---

### LEVEL 3: CRITICAL TELEGRAM (RED ALERT)
**When:** System is broken or data integrity at risk

- 0 games imported for 48h+ (non-scrape periods OK)
- Multiple agents failing in same day (systemic issue)
- Data pipeline completely down
- API credits exhausted (blocks everything)
- Auth/security breach
- Rankings calculation returning 0 teams (data integrity)

**Action:** Post to chat with 🚨 prefix:
```
🚨 **CRITICAL: [Issue]**
Impact: [what's broken]
Next: [immediate fix being applied]
```

**Example:**
```
🚨 **CRITICAL: Zero Games Imported (48h)**
Monday 6am scrape returned 0 games.
Wednesday scrape also 0 games.
Watchy spawned Scrappy for investigation.
```

**Wait for:** D H will respond immediately.

---

### LEVEL 4: ASK FIRST (Don't Execute)
**When:** Decision is outside agent scope

- Changing ranking algorithm
- Team merge logic (beyond what's in TEAM_MERGE_RULES.md)
- Major structural DB changes
- New scrape targets / providers
- Anything not covered in CODEY_TRUST_ZONE.md or this doc

**Action:** Post to chat with ❓ prefix:
```
❓ **Decision Needed**
Situation: [context]
Options: [A, B, C]
Recommendation: [what we'd do if approved]
```

**Example:**
```
❓ **New Scrape Target**
GotSport's youth championships available.
Could be high-value content for CA/TX.
Recommend adding to Wednesday scrape rotation.
Approve?
```

**Wait for:** D H approval before implementing.

---

## Quick Reference for Agents

```
Level 0: Silent logging → AGENT_COMMS.md only
Level 1: Regular update → AGENT_COMMS.md + note in DAILY_CONTEXT.md  
Level 2: Needs attention → 📢 Post to Telegram (use sessions_send)
Level 3: System broken → 🚨 Post to Telegram (use sessions_send)
Level 4: Out of scope → ❓ Ask D H (use sessions_send)
```

**When in doubt, Level 2 (Telegram alert). Better safe than silent.**

---

## 🚨 Escalation Rules (Original)

### Always Escalate to Telegram (LEVEL 2+)
- Data pipeline issues
- Multiple agent failures
- Anything affecting live rankings
- Security/auth problems
- Decisions requiring business judgment

### Handle Autonomously (LEVEL 0-1)
- Model config fixes
- Expected data patterns
- Clear pattern matches from DECISION_TREES
- Codey-handled code fixes
- Performance within baselines

### Ask First (LEVEL 4)
- Algorithm changes
- Team merge logic changes
- Major structural changes
- New scrape targets
- Anything not covered here

---

## ⏱️ Performance Baselines

Use these to detect anomalies. If runtime exceeds 3x baseline, investigate.

| Operation | Normal | Warning (>2x) | Critical (>3x) |
|-----------|--------|---------------|----------------|
| TGS import (10 events) | 30 min* | >1h | >2h |
| GotSport event scrape | 10 min | >20 min | >30 min |
| Rankings calculation | 15-20 min | >40 min | >1h |
| Watchy health check | <1 min | >2 min | >5 min |
| Cleany weekly job | 5-10 min | >20 min | >30 min |
| Team merge batch | 5 min | >15 min | >30 min |
| GSC report | 2 min | >5 min | >10 min |

*After batch team creation fix is implemented

### Slow Operation Decision Tree
```
WHEN: Operation taking >2x baseline
CHECK: Is data volume unusually high?
IF: Yes (>2x normal records) → Expected, let it finish
IF: No → Possible code issue or resource constraint
CHECK: Are there errors in logs?
IF: Errors present → Spawn Codey to investigate
IF: No errors, just slow → Profile after completion, add to backlog
ESCALATE: If >3x baseline AND blocking other work
```

### Data Volume Baselines
```
Normal daily volumes:
- Games imported: 500-2,000/day during scrape days
- Teams created: 50-200/day
- Quarantine: <100 new/day
- Match reviews: Variable (D H working through backlog)

Warning thresholds:
- 0 games for 48h+ (not counting weekends)
- Quarantine spike >500 in single import
- >1000 new teams in single import (data quality check needed)
```

---

*Last updated: 2026-02-07 by Moltbot*
*COMPY: Append new patterns below, do not modify above*

## New Patterns (COMPY appends here)

### 2026-02-07: API Credit Exhaustion Warning
```
WHEN: Multiple sub-agent runs fail with "credit balance too low"
PATTERN: Cleany ran 58 failed attempts in single session (Feb 7, 21:35)
CAUSE: Long-running batch operations (club standardization) consuming credits too fast
CHECK: How many sub-agents running simultaneously?
IF: >2 agents with heavy API load → Stagger runs, use longer heartbeat intervals
IF: Single agent consuming all credits → Profile and optimize (Cleany case: batch SQL faster than API loops)
ACTION: Migrate batch operations to GitHub Actions (compute cost 0, API cost minimal)
ESCALATE: If billing shows unusual overage (>$20/day)
```

### 2026-02-07: Codey Performance Optimization Pattern (TGS Import)
```
WHEN: Long-running script takes 5-6 hours
PATTERN: TGS import bottleneck identified by Codey
ROOT_CAUSE: Teams created one-by-one during import loop (200k+ API queries)
FIX: Batch pre-create all teams before import (single query)
RESULT: 10-15x speedup (5-6h → 30min)
LESSON: Always check for loop-in-loop patterns. Batch operations dramatically faster.
AUTOMATION: This fix deployed 2026-02-07 21:55 by Codey, merged to main
```

### 2026-02-07: Full Autonomy Framework Enabled
```
WHEN: D H grants explicit autonomy (2026-02-07 21:42 approval message)
SCOPE: 
  🚫 Protected (never touch): algorithm, team merge logic
  ✅ Autonomous: everything else
MINDSET: 
  - OLD: Suggest → Wait → Implement
  - NEW: See opportunity → Do it → Report results
EXAMPLES:
  - Commit fixes without asking ✅
  - Spawn agents freely ✅
  - Try new approaches ✅
  - Optimize anything ✅
  - Build new tools ✅
ESCALATE_ONLY: Strategic decisions, data policy changes, security
```

### 2026-02-08: Anthropic Credit Exhaustion Error Pattern
```
WHEN: Agent run fails with "Your credit balance is too low to access the Anthropic API"
PATTERN: Cleany (4 sessions) and Watchy (1 session) both hit credit errors on Feb 8
SCOPE: 33 failed API calls across agents in 24h window
ROOT_CAUSE: Unknown (needs D H to check billing / API credits)
CHECK: Is this a billing issue or usage spike?
IF: Billing issue → Contact Anthropic support, check account
IF: Usage spike → Check what triggered multiple simultaneous agent runs
ACTION: When credit error hits an agent:
  1. Agent should log to AGENT_COMMS.md (LEVEL 2 alert)
  2. Set to retry after 30 minutes (auto-backoff)
  3. If persists >2h → Escalate to D H (LEVEL 3: 🚨 CRITICAL)
PREVENTION: Monitor daily cost in DAILY_CONTEXT.md, alert if >$10/day
```


### Rankings Calculation Timing
**IF** rankings calculation started  
**THEN** wait at least 60 minutes before polling for completion  
**REASON** Rankings takes 1hr+ to process all teams. Polling frequently wastes resources.

### 2026-02-10: Persistent Connection Errors (Non-Blocking)
```
WHEN: Agent session encounters connection errors
PATTERN: Cleany (3 errors), Scrappy (2 errors), Movy (0 errors) across 6 sessions on Feb 10
SCOPE: 9 total connection errors; all sessions continued and completed successfully
TYPE: "Connection error." (generic, no specific error details)
BEHAVIOR: Does not block agent task completion — agents retry and continue
ROOT_CAUSE: Unknown (could be network transience, external API rate limit, or provider throttling)
CHECK: Are other agents/systems affected simultaneously?
IF: Only affecting one agent → Likely provider-specific (Cleany might hit GotSport rate limit, Scrappy might hit TGS)
IF: Affecting multiple agents → Could be network/infrastructure issue
ACTION: Log to AGENT_COMMS.md, continue work (non-blocking). Monitor for spike (>5 in 1h = escalate)
ESCALATE: If same agent hits >10 connection errors in single run OR all agents hit errors simultaneously
PREVENTION: None yet (transient), but if pattern repeats, profile which API/provider causing it
```

### 2026-02-10: PRE-team SOS Movement Without Game Data
```
WHEN: Movy detects rank movement in teams without corresponding new games
PATTERN: Some PRE-age-group teams (e.g., academy divisions) show SOS changes but no game data
SCOPE: Detected in Movy's 2026-02-10 weekly movers report
ROOT_CAUSE: Possible scraping gap for academy divisions (MLS NEXT, academy cups)
IMPACT: Rankings appear to move without game justification — SOS recalculation happens but we're not capturing games
CHECK: Are academy divisions being scraped?
IF: Yes, but games not captured → Parser issue (missing academy event IDs or format change)
IF: No, not being scraped → Working as designed (we only scrape select events, not all academies)
IF: Uncertain → Spawn Codey to investigate scrape coverage for that cohort/state
ACTION: If parser issue confirmed → Codey creates fix. If design decision → Document in governance.
ESCALATE: If SOS anomaly affects >50 teams (data quality concern)
```

### 2026-02-11: Extended Connection Errors + API Overload Pattern
```
WHEN: Multiple agents hit connection errors + overload errors in same cycle
PATTERN: Feb 11 24h review shows:
  - Scrappy: 5 connection errors during Wed scrape (carrying over from Feb 10)
  - Cleany: 9 connection errors across sessions (escalation from Feb 10's 3)
  - Watchy: 4 NEW API errors (Overloaded x3, Internal Server Error x1) — NEW ERROR TYPE
SCOPE: 18 errors across 5 agent sessions in 24h
ROOT_CAUSE: Likely cascading effect of underlying credit exhaustion + provider throttling
BEHAVIOR: Non-blocking (agents continue), but increasing error frequency suggests system under strain
CHECK: Is Anthropic API credit issue still unresolved?
IF: Yes (credit balance still low) → Provider is throttling. Needs D H billing fix (escalated since Feb 7).
IF: No, credit restored → Connection errors should drop. If not, may be provider-side issue.
ACTION: 
  1. Log error frequency spike to DAILY_CONTEXT.md
  2. Monitor for >20 errors/24h (indicates systemic issue)
  3. If >20 errors in next cycle → Escalate to D H (possible Anthropic account issue)
ESCALATE: If error frequency increases OR if errors become blocking (agents fail tasks)
PREVENTION: Resolve credit issue (CRITICAL since Feb 7). Once resolved, monitor if error rate returns to baseline.
```

### 2026-02-11: Missing Infrastructure Credentials (GSC)
```
WHEN: Socialy SEO agent cannot access Google Search Console
ISSUE: File not found: `/Users/pitchrankio-dev/Projects/PitchRank/scripts/gsc_credentials.json`
ERROR: Invalid JWT Signature (service account authentication failed)
SCOPE: Blocks all Google Search Console analytics (search queries, CTR, impressions, indexing)
IMPACT: Cannot validate SEO strategy effectiveness or keyword rankings
ROOT_CAUSE: Credentials file missing or deleted (likely during infrastructure cleanup)
ACTION: D H must restore `gsc_credentials.json` from backup or re-generate service account key
WORKAROUND: Socialy can proceed with technical SEO checks (sitemap, robots.txt) until GSC restored
NEXT_STEPS:
  1. D H restores GSC credentials
  2. Re-run Socialy with full suite enabled
  3. Document in team wiki: "GSC credentials backed up to [location]"
ESCALATE: If >1 critical credentials missing (indicates backup/recovery process broken)
```

### 2026-02-12: Connection Error Pattern Continues (Escalation Threshold Approaching)
```
WHEN: Multiple agents encounter connection errors across 24h cycle
PATTERN: Feb 11-12 shows:
  - Main session: 2 connection errors (heartbeat work)
  - Scrappy: 7 connection errors (scraping operations)
  - Total: 9 errors in latest 24h
TREND: Cumulative (Feb 10: 5 errors → Feb 11: 14 errors → Feb 12: 9 errors) = sustained high error load
CORRELATION: Still following API credit exhaustion hypothesis (Feb 7-12 = 5 DAYS PENDING RESOLUTION)
CHECK: Is Anthropic billing/credit issue still unresolved?
IF: Yes → Error rate will continue/escalate. System approaching failure threshold (recommend immediate escalation to D H)
IF: No, credits restored → Error rate should drop by next cycle. If not, may indicate different root cause.
ACTION: Track error rate daily in DAILY_CONTEXT.md. If exceeds 15 errors/24h in next cycle → CRITICAL escalation
PREVENTION: Resolve billing issue immediately. Monitor credit balance visibility.
NOTE: Agents still completing tasks (non-blocking errors), but trend is unsustainable.
```

### 2026-02-14: Error Plateau Pattern (System Healing Under Stress)
```
WHEN: Error rate peaks then plateaus at lower level despite root cause unresolved
PATTERN: Feb 7-14 trend shows:
  - Feb 10: 5 errors (early)
  - Feb 11: 14 errors (PEAK — billing crisis full impact)
  - Feb 12: 9 errors (declining)
  - Feb 13: 6 errors (further decline)
  - Feb 14: 6 errors (PLATEAU — stabilized, not escalating)
INTERPRETATION: 57% reduction from peak despite Anthropic billing issue still unresolved (8 days)
ROOT_CAUSE: Likely D H made partial fix, or API load-balancing kicked in, or system found equilibrium
LOAD_CORRELATION: 100% of errors on heavy agents (Main, Codey); 0 on light agents (Watchy, Scrappy)
  - Learning: Error rate = load-proportional, not random
  - Learning: System architecture is sound; focus on root cause, not defensive code
CHECK: Is error trend continuing to decline or holding at 6/day?
IF: Continuing to decline (5 or fewer) → System healing confirmed. Remove escalation urgency.
IF: Holding at 6/day for 3+ cycles → Acceptable plateau, monitor for reversal.
IF: Reversing (7+) → Root cause not fixed. Escalate immediately.
ACTION: Continue daily error trend monitoring in LEARNINGS.md. Plot 7-day moving average.
PREVENTION: Once plateau confirmed at <5/day for 1 week, declare "crisis resolved" and stand down escalation.
NOTE: Non-blocking errors are acceptable; blocking errors (agents fail tasks) are critical.
```

### 2026-02-16: Age Group Support Policy Decision (U19)
```
WHEN: Quarantine contains high count of single unsupported age group
PATTERN: Feb 16 8am Watchy alert shows:
  - Quarantine jumped: 39 (Feb 15) → 777 (Feb 16 morning)
  - 738 new games added overnight (7:35-47am)
  - 726 games = U19 age group rejections
TRIGGER: Scraper (TGS or auto-scraper) now pulling U19 games
  - Age group validation rejects: "U19 must be one of ['U10'...'U18']"
  - This is intentional validation, not a bug
BUSINESS_DECISION: Does PitchRank support U19 (high school age)?
OPTIONS:
  A) **Add U19 support** → Update `calculate_rankings.py` age_groups validation list
     - Impact: Expand rankings to include high school
     - Effort: 2-line change in rankings algorithm
     - Consideration: Touches protected algorithm (requires D H approval)
  
  B) **Filter U19 at scraper** → Modify scraper config to exclude U19 events
     - Impact: No high school coverage, cleaner import pipeline
     - Effort: Update TGS/GotSport event filters
     - Owner: Scrappy or source config
  
  C) **Leave in quarantine** → Accept U19 games accumulate, do nothing
     - Impact: Data sits unranked; unclear signal to users
     - Effort: None
     - Consideration: Not a good long-term solution
ESCALATE: LEVEL 4 (❓ Decision Needed) — This is a business policy decision outside agent scope.
ACTION_PENDING: Wait for D H to choose A/B/C, then implement.
MONITORING: Track quarantine U19 count daily until decision made.
```
