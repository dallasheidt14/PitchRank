---
name: orchestrator-patterns
description: Patterns for coordinating PitchRank sub-agents. Use when spawning agents, handling failures, maintaining memory continuity, or making decisions about which agent to use for a task.
---

# Orchestrator Patterns

## Agent Selection Matrix

| Task Type | Primary Agent | Fallback | Model Tier |
|-----------|--------------|----------|------------|
| Data hygiene (names, dupes) | Cleany 🧹 | Codey | Haiku |
| Scraping issues | Scrappy 🕷️ | Codey | Haiku |
| Code fixes | Codey 💻 | — | Sonnet → Opus |
| Rankings calculation | Ranky 📊 | Codey | Haiku |
| Content/movers | Movy 📈 | — | Haiku |
| System health | Watchy 👁️ | Orchestrator | Haiku |
| Knowledge extraction | COMPY 🧠 | — | Sonnet |
| SEO/social | Socialy 📱 | Movy | Haiku |

## Spawn Templates

### Quick Fix (Haiku)
```
You are [Agent] [emoji]. Be concise.
Task: [TASK]
Workspace: /Users/pitchrankio-dev/Projects/PitchRank
Report what you did.
```

### Investigation (Sonnet)
```
You are [Agent] [emoji]. Investigate thoroughly.
Problem: [DESCRIPTION]
Workspace: /Users/pitchrankio-dev/Projects/PitchRank
Steps:
1. [diagnostic command]
2. Analyze output
3. Identify root cause
4. Fix if possible, else report findings
```

### Complex Fix (Opus)
```
You are [Agent] [emoji].
Task: [COMPLEX TASK]
Workspace: /Users/pitchrankio-dev/Projects/PitchRank
Skills: Read relevant .claude/skills/*.skill.md files first.
Protected files: [list if applicable]
Report: Analysis, changes, testing, risks.
```

## Failure Handling

### Model Errors
1. Check `cron action=list` for `lastStatus: "error"`
2. Valid models: `anthropic/claude-haiku-4-5`, `anthropic/claude-sonnet-4-5`
3. Update cron: `cron action=update jobId=X patch={payload:{model:"correct-model"}}`
4. Log to `logs/agent-errors.log`

### Agent Hangs
1. Check `sessions_list` for stuck sessions
2. If >10 min with no progress, note in memory and retry later
3. Don't spawn same task twice simultaneously

### Escalation Path
1. Agent fails once → Retry with more context
2. Agent fails twice → Try different agent or model tier
3. Agent fails 3x → Alert D H with findings

## Memory Maintenance

### After Each Sub-Agent Completes
1. Update `memory/agent-runs.md` with summary
2. If failed, log to `logs/agent-errors.log`
3. If learned something new, note for COMPY

### Daily
1. Ensure `memory/YYYY-MM-DD.md` exists with session summary
2. Check if MEMORY.md needs updates
3. Review `memory/heartbeat-state.json` timestamps

## Autonomous vs Escalate

### Do Autonomously
- Fix model errors in crons
- Spawn Codey for clear code bugs
- Clear quarantine < 1000 records
- Update memory files
- Retry failed agents

### Escalate to D H
- 0 games imported in 24h
- Multiple agents failing same task
- Data decisions (what to delete/merge)
- New feature requests
- Security concerns
