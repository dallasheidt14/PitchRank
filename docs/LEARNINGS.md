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

<!-- COMPY will append system patterns here -->

## Integration Learnings

<!-- COMPY will append integration insights here -->

---
*Last updated: 2026-02-01*
