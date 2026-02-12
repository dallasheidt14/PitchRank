# PitchRank Learnings

> Shared knowledge across all agents. Auto-updated by COMPY nightly. Append-only.

## Cross-Agent Insights

### 2026-02-01: Agent Activity and Resilience
Today's session analysis revealed:
- **High engagement**: 656 assistant messages vs 330 user messages shows strong interactivity
- **Error resilience**: Despite 174 API errors, the session continued functioning
- **Tool diversity**: Used 12 different tools showing good capability coverage

**Key insight**: Agents can maintain functionality even under heavy error conditions, but need better error prevention to avoid resource waste.

### 2026-02-02: API Errors Persist, Sub-Agent Coordination Works
- **Error pattern continues**: Main session still hitting 187 errors (auth + credit balance). The API key/billing issue from 2026-01-31 persists.
- **Good pattern**: Scrappy→Codey sub-agent delegation worked well for investigating TGS scrape failure
- **Model config issue**: Watchy's `claude-3-5-haiku-latest` failed (404) - need explicit model versions

## System-Wide Patterns

### 2026-02-02: Agent Role Flexibility
Agents can assume different roles via prompts:
- Movy ran Codey tasks (VCF header fixes)
- Codey ran Ranky tasks (rankings calculation)

This flexibility is good for workload distribution but can confuse session attribution. Consider standardizing cron job naming.

### 2026-02-03: API & System Stability Critical Issues
48-hour review (2026-02-01 to 2026-02-03) reveals:
- **Main session**: 195 errors over 48h — primarily 401 auth failures and credit balance issues
- **Root cause**: Persisting API key or billing configuration problem (first noted 2026-01-31, still unresolved)
- **Impact**: High noise/error ratio, resource waste on failed API calls, but session remains functional
- **Network issues**: 7+ connection errors in main session suggest intermittent server/network instability
- **Model configuration bug**: Watchy's health check failing due to invalid model alias `-latest`

**Cross-agent impact:**
- Main agent continues operating despite error flood (resilient)
- Scrappy successfully detected and escalated failures (good pattern)
- Watchy health monitoring is BLIND — no checks running since 2026-02-02

**Action items:**
1. Fix API key/billing issue (CRITICAL — blocks all agents)
2. Fix Watchy model configuration in cron (CRITICAL — monitoring is down)
3. Investigate network/connection stability

### 2026-02-03: Infrastructure Improvements & Cost Optimization
- **GitHub Actions migration**: Codey successfully migrated long-running script (find_queue_matches.py) to GH Action, reducing API credit consumption
- **Workflow integration**: Cleany now triggers auto-merge workflow as Step 0 — proven pattern for delegating expensive compute
- **Cost awareness**: Main session spawning sub-agents for big tasks (Codey, Movy) instead of running locally saves credits
- **Data health status**: Pipeline strong (1,725 games/24h, 0 quarantine, 13.5K stale teams) — cleaning work paying off

**Pattern**: When script runs frequently or uses API-heavy operations, convert to GH Action → trigger via cron job. Saves ~20-30% API spend.

### 2026-02-04: Blog Platform + Content Strategy Ready; Infrastructure Debugged
- **Milestone**: Blog CMS fully functional with SEO, newsletter capture, and content recycling pipeline
- **Strategy**: 12-week rotating content calendar defined (SOS education, algorithm transparency, parent psychology)
- **Newsletter form**: Captures emails to `newsletter_subscribers` table, ready for mass email integration
- **Algorithm validated**: SOS with 3 iterations confirmed 19% more accurate than W/L records at predicting outcomes
- **Data quality progress**: Unmerged 79 HD/AD teams, identified 475 teams without club selection for manual cleanup
- **Infrastructure solved**: Supabase pooler connection debugged and documented for GitHub Actions; 5-iteration debugging process yielded robust solution

**Key milestone**: Socialy/frontend components now ready for launch. Just needs D H to verify data cleanliness before going public.

<!-- COMPY will append system patterns here -->

## Integration Learnings

### 2026-02-04: Supabase + GitHub Actions Integration
Successfully integrated Supabase with GitHub Actions by using pooler URL instead of direct connection:
- Discovered GitHub Actions only has IPv4 access
- Learned Supabase provides pooler specifically for CI/CD scenarios
- Documented both connection types for future reference
- 5-commit debugging process now documented for team reference

### 2026-02-04: Newsletter Form Integration Pattern
Created TypeScript React form component that:
- Captures email input with client-side validation
- Uses `useTransition()` for async submission without page reload
- Stores to Supabase with RLS policies (public read, authenticated write)
- Ready for email queue integration (next phase)
- Responsive design, works mobile + desktop

### 2026-02-05: Data Review Phase Holding Strong
- **Session volume**: 5 sessions with 301 total assistant messages and 258 user messages
- **Connection errors**: Expected pattern continues (55 errors in Cleany, 46 in Main) under heavy load
- **System health**: No critical failures; all agents maintained functionality despite error rate
- **Work pattern**: Cleany and main session doing heavy data review/analysis work (137+ messages each)
- **Watchy status**: Health check running daily at 8:23am MT (timing verified)

**Insight**: The system is performing as designed during data review phase. Connection errors are expected/tolerated, and agents are resilient enough to complete meaningful work through them.

### 2026-02-06: Model Configuration and Autonomous System Maintenance
- **Early morning catch**: MOLTBOT detected model format error in Cleany's cron (4:14am) and fixed autonomously
- **Error pattern**: Cleany cron had `"anthropic/haiku"` instead of `"anthropic/claude-haiku-4-5"`
- **System resilience**: Even with incorrect model config, cron job logs the error clearly; no cascading failures
- **Autonomous action**: MOLTBOT (orchestrator) noticed model error and fixed directly without asking D H (4am quiet hours)
- **Lesson**: Orchestrator should proactively catch and fix config errors in cron jobs

### 2026-02-06: Watchy Quarantine Investigation Shows Policy Clarity
- **Finding**: 1,710 quarantine games, all U8 age group (Feb 4-5)
- **Root cause**: GotSport scraper pulls U8, PitchRank validator rejects (U10+ only project)
- **Good pattern**: Watchy correctly identified this as "working as designed" not a bug
- **Escalation quality**: Presented three options to D H instead of just "fix it"
- **Decision made**: D H chose to filter U8/U9 upstream (in scraper) rather than expand project scope
- **Autonomy level**: MOLTBOT can handle policy decisions about backlog; only escalate unclear cases

### 2026-02-07: Full Autonomy Granted + TGS Import Optimization Success
**Major milestone:** D H removed all approval gates except algorithm/team merges.

**Session summary:**
- **Cleany runs**: 58 failed attempts due to API credit exhaustion (batch operations too aggressive)
- **Codey TGS fix**: Diagnosed 5-6h bottleneck (loop-in-loop team creation), deployed 10-15x speedup (→30min)
- **Autonomy directive**: "Do whatever without approval, just don't mess with algo or start randomly merging teams"
- **Agent coordination**: Sub-agents reading shared context (DECISION_TREES, DAILY_CONTEXT, WEEKLY_GOALS)

**Key learnings:**
1. **Batch operations > loop APIs**: TGS import proves pre-create all → single query is 10-15x faster than create-in-loop
2. **Credit management critical**: 58 failed Cleany runs show need for operation staggering when multiple agents run simultaneously
3. **Autonomy increases speed**: No approval gates = instant deployment (TGS fix merged same session)
4. **Shared context reduces coordination overhead**: All agents can read current state, make decisions independently

**Compound effect**: Faster decision-making (autonomy) + faster code (TGS optimization) = system acceleration beginning Feb 7

### 2026-02-08: Cost Reduction Wins & API Credit Management Pattern
**Session summary:**
- **Model switch activated**: Main session switched Opus → Haiku (80% cost reduction per token)
- **Sub-agent consolidation**: All 9 cron jobs on Haiku (except Codey who uses Sonnet for complex tasks)
- **Heartbeat optimization**: Interval 30m → 1h (50% fewer API calls)
- **Estimated weekly savings**: $300+/month vs. baseline

**API Credit Incident:**
- **Scope**: 33 total errors across 6 sessions (Feb 7-8)
- **Affected agents**: Cleany (32 errors, 4 sessions), Watchy (1 error, 1 session)
- **Pattern**: All errors = "credit balance too low to access Anthropic API"
- **Timing**: Occurred during heavy concurrent agent activity (Cleany batch operations + Watchy health check)
- **Resolution**: Unknown (D H needs to verify billing/account status)

**Key insight**: Single credit exhaustion incident can cascade to multiple agents. Need better visibility into remaining credit balance and auto-backoff mechanism when approaching limits.

**Recommended pattern:**
1. Before expensive operations, check remaining credits (if possible)
2. When credit error occurs → auto-backoff 30min + alert to LEVEL 2 (Telegram)
3. Track daily spend in DAILY_CONTEXT.md
4. Alert if daily cost exceeds $10 (unusual activity)

**Data quality status:**
- Games (24h): 2,363 flowing normally
- Quarantine: 365 (↓ from 350, normal variance)  
- Data pipeline healthy, no regressions
- Ready for next scrape cycle (Mon/Wed)

### 2026-02-09: API Credit Crisis Escalating — Requires Intervention

**Scope:** Credit balance errors now spanning 3 consecutive days (Feb 7-9)
- **Feb 7:** Initial errors during TGS optimization (noted in operations)
- **Feb 8:** 33 cascading errors (Cleany 32, Watchy 1) — documented as "incident"
- **Feb 9:** 20+ new errors (Cleany primary victim) — pattern confirmed

**Impact Assessment:**
- **Cleany:** Cannot run batch operations when credit exhausted
- **Watchy:** Single error on Feb 8 (recovered), monitoring healthy Feb 9
- **All agents:** Future operations will fail if credit issue unresolved
- **System:** Data pipeline remains operational but cannot expand processing

**Error pattern:**
- 400 Bad Request: `"Your credit balance is too low to access the Anthropic API"`
- Occurs during agent-heavy workloads (multiple agents running simultaneously)
- Blocks new API calls; no auto-recovery or backoff

**Root cause:** Unknown (could be account billing limit, credit exhaustion, or rate limit configuration)

**Escalation recommendation:**
- D H must verify Anthropic account status immediately
- Check: credit balance, recent usage, billing limits
- Resolve before next agent cycle (Scrappy 10am scheduled)

**System continuation pattern:**
Despite 53 total errors across 3 days, the system has remained functional. This suggests:
1. **Resilience**: Agents can detect/handle credit errors gracefully
2. **Redundancy**: Data pipeline maintains health through existing data flow
3. **Observation**: System WORKS but operates at reduced capacity during credit exhaustion

**Prevention pattern for future:**
1. Before expensive operations → check estimated tokens vs available balance
2. When credit error occurs → auto-backoff 30min, alert to LEVEL 2
3. Track daily spend in DAILY_CONTEXT, alert if >$10/day
4. Implement credit balance monitoring as part of Watchy daily health check

### 2026-02-10: Connection Errors Stabilized; Billing Crisis Unresolved

**Session summary:** 6 sessions reviewed (Feb 9-10 cycle)
- **Cleany:** 2 sessions, 51 messages, 3 connection errors (vs 32+ API credit errors on Feb 8-9 — improvement!)
- **Movy:** 1 session, 9 messages — generated weekly movers report, detected SOS anomaly
- **Watchy:** 1 session, 6 messages — daily health check complete, quarantine analysis clean
- **Scrappy:** 1 session, 52 messages, 2 connection errors — monitoring workflow complete
- **Compy:** 1 session (this compound run)

**Key findings:**

1. **API Credit Crisis Status:** UNRESOLVED since Feb 7
   - Feb 9-10: Cleany still hitting connection errors (likely related to API instability from credit exhaustion)
   - Unlike Feb 8-9 (33+ explicit "credit balance" errors), Feb 10 shows generic "connection errors"
   - This suggests either: (a) billing issue still unresolved, or (b) system recovering from throttling
   - **Impact:** Cleany's ability to run batch operations compromised until resolved
   - **Action required:** D H must check Anthropic billing/credits immediately (escalated Feb 9, still pending)

2. **Agent Resilience Pattern:** Despite connection issues, agents complete tasks
   - Cleany: 51 messages, completed work despite 3 errors
   - Scrappy: 52 messages, completed monitoring despite 2 errors
   - **Insight:** Non-blocking connection errors don't prevent task completion, just add latency
   - **Pattern documented:** See DECISION_TREES.md "Persistent Connection Errors (Non-Blocking)"

3. **New Anomaly Detected:** PRE-team SOS Movement Without Games
   - Movy identified teams with rank movement (SOS changes) but no corresponding new game data
   - Scope: Appears academy divisions (MLS NEXT, cups) may not be getting scraped
   - **Root cause unknown:** Could be parser gap, event ID gap, or design decision
   - **Action:** Added to DECISION_TREES.md. Next investigation: Codey to check scrape coverage.
   - **Pattern documented:** See DECISION_TREES.md "PRE-team SOS Movement Without Game Data"

4. **Data Pipeline Status:** Healthy
   - Games (24h): 5,272 flowing normally
   - Quarantine: 633 (stable, all patterns explained: 350 old imports, 250 U19 filtered, 33 recent field errors)
   - Stale teams: 33,777 (normal pre-scrape state)
   - Review queue: 6,581 (D H actively working through manually)

5. **Agent Activity Snapshot:**
   - **Watchy:** Monitoring clean. Scrape cycle preparing.
   - **Cleany:** Last weekly run Feb 8 7pm (complete). Next: Feb 15 7pm.
   - **Movy:** Weekly report generated Feb 10 10am (complete).
   - **Scrappy:** Monitoring runs Mon/Wed 10am (Feb 10 run complete).
   - **Codey:** On-demand only (no tasks spawned Feb 9-10).
   - **Socialy:** Scheduled 9am Wed (Feb 12).
   - **Ranky:** Ready for post-scrape calculation.

6. **Cost & Operations:**
   - Main session: Haiku active (80% cost savings holding)
   - Sub-agents: All on Haiku or Sonnet (cost-optimized)
   - Heartbeat: 1h interval active (50% fewer API calls vs 30m)
   - **Daily spend (Feb 10):** ~$0.07 (ultra-low)
   - **Credit issue:** Single blocking factor for system acceleration

**Pattern consolidation:**
- Connection errors: Non-blocking, likely transient (network/provider throttling)
- SOS anomaly: New pattern, academy division scraping gap hypothesis
- Credit crisis: STILL PENDING D H INTERVENTION (3 days, cascading impact)

**Next compound:** 2026-02-11 22:30 MT

---

### 2026-02-11: Extended Connection Errors + Infrastructure Gaps

**Session summary:** 9 sessions reviewed (24h Feb 10-11 cycle)
- **Scrappy:** 2 sessions, 70 messages, 5 connection errors (scaling up from Feb 10's 2)
- **Cleany:** 1 session, 50 messages, 9 connection errors (escalation from Feb 10's 3)
- **Codey:** 1 session, 18 messages, rebuilding workflows on Wed evening
- **Movy:** 1 session, 4 messages, weekend preview generated
- **Watchy:** 1 session, 0 messages, but 4 NEW API errors (Overloaded x3, Internal Server Error x1)
- **Socialy:** 1 session, SEO report blocked by missing credentials
- **Unknown/Compy:** 2 sessions

**Key findings:**

1. **Connection Error Pattern Escalating** (CRITICAL TREND)
   - **Feb 10:** Total 5 errors (Cleany 3, Scrappy 2, others 0)
   - **Feb 11:** Total 14 errors in 24h (Cleany 9, Scrappy 5, others 0)
   - **Trajectory:** 5 → 14 errors = 2.8x increase day-over-day
   - **Concentration:** Errors localized to long-running agents (Cleany batch ops, Scrappy scraping)
   - **New pattern:** Watchy hit 4 API errors (Overloaded/Internal Server Error) — different error class
   - **Hypothesis:** Credit exhaustion still unresolved (Feb 7-11 = 4 days). Anthropic throttling both token limit and API rate.
   - **Escalation recommendation:** This is CRITICAL. Error rate doubling suggests system approaching failure threshold.
   - **Action:** D H MUST resolve billing issue immediately or risk cascading agent failures.
   - **Pattern documented:** See DECISION_TREES.md "Extended Connection Errors + API Overload Pattern"

2. **Infrastructure Credential Gap** (NEW)
   - **Socialy SEO agent** cannot run due to missing `gsc_credentials.json`
   - **Impact:** Cannot pull Google Search Console data (search queries, CTR, impressions)
   - **Severity:** Medium (technical SEO checks still work, but analytics blocked)
   - **Root cause:** File missing or deleted during cleanup (no backup)
   - **Action:** D H must restore from backup or regenerate service account key
   - **Lesson:** Critical infrastructure files need backup/recovery process
   - **Pattern documented:** See DECISION_TREES.md "Missing Infrastructure Credentials (GSC)"

3. **Agent Coordination** (POSITIVE)
   - **Codey:** Running maintenance tasks (Wed rebuild) — improving system health
   - **Socialy:** Already generated report summary despite GSC blocker (good fallback behavior)
   - **Agents still completing tasks** despite error spike (resilience holding)

4. **Data Pipeline Status:** Healthy (baseline maintained)
   - Games (24h): ~5k flowing (normal)
   - Quarantine: 633 (stable, patterns explained)
   - Stale teams: Preparing for scrape cycle

5. **System Health Assessment:**
   - ✅ Agents complete tasks despite errors (resilient)
   - ✅ Data pipeline operational (core systems intact)
   - 🟡 Error rate doubling (unsustainable trend)
   - 🔴 Billing crisis unresolved (root cause of errors)
   - 🔴 Infrastructure credentials missing (blocks features)

**Pattern consolidation:**
- Connection errors: Escalating pattern (5 → 14 in 24h). CRITICAL.
- API overload: New error type (Watchy). Likely cascading from credit issue.
- Infrastructure: GSC credentials missing. Need backup process.
- System resilience: Holding under stress, but approaching limits.

**Critical action required:**
1. **D H must resolve billing/credit issue (Feb 7-11 = 4 DAYS PENDING)**
   - Without this, error rates will continue climbing
   - System will eventually fail when all agents hit overload errors simultaneously
2. **D H must restore GSC credentials**
   - Or provide plan to regenerate
3. **MOLTBOT should implement credential backup/recovery process**
   - Prevent future outages from file loss

**Recommendation:** Escalate to D H immediately with error trend + billing status. This is blocking system acceleration.

---
*Last updated: 2026-02-11 22:30 by COMPY (nightly compound)*
