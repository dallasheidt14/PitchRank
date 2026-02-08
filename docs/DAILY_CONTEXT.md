# Daily Context — Shared State for All Agents

> Updated throughout the day. All agents should read this on startup.

**Date:** 2026-02-07

## 🚫 PROTECTED (Never Touch Without Asking)
- Rankings algorithm
- Team merge logic

## 🚫 Don't Alert About
- **Review queue count** — D H is actively working through it manually
- **Last scrape age** — Scrappy runs Mon/Wed, gaps on other days are normal

## ✅ FULL AUTONOMY GRANTED (9:50pm Feb 7)
D H: "you can do whatever without my approval just don't mess with algo and start randomly merging teams"

**We can now:**
- Commit fixes without asking
- Spawn agents freely  
- Try new approaches
- Optimize anything
- Build new tools
- Just DO things

## 📋 D H is Currently
- Manually reviewing each age group for data cleanliness
- Working through match review queue

## 🔄 Today's Activity
- TGS Event Scrapes: 3850-3880 (3 runs, 2 complete, 1 in progress)
- Decision trees implemented (`docs/DECISION_TREES.md`)
- All 9 sub-agent crons updated to read DAILY_CONTEXT + DECISION_TREES
- Incident playbook created (`docs/INCIDENT_PLAYBOOK.md`)
- Performance baselines added to decision trees
- Heartbeat interval changed 30m → 1h

## ⚠️ Known Issues
- TGS import step is extremely slow (~6h for 10 events) — Codey diagnosed, fix ready pending approval
- Root cause: Teams created one-by-one (200k+ queries). Fix: batch pre-create teams.

## 🎯 Priorities
1. Let D H focus on data review without noise
2. Be autonomous — act, don't just suggest
3. Track mistakes and learn from them

## 💰 Cost Tracking

### Today's Spend (2026-02-07)
| Session | Model | Est. Cost |
|---------|-------|-----------|
| Main (heartbeats + tasks) | Opus | ~$2-3 |
| Watchy 8am | Haiku | ~$0.02 |
| Codey (TGS investigation) | Sonnet | ~$0.15 |
| COMPY (tonight 10:30pm) | Haiku | ~$0.05 |

**Running total:** ~$2.50 (estimate)

### Cost Reduction Wins Today
- Heartbeat interval 30m → 1h = ~50% fewer heartbeat calls
- All sub-agents on Haiku (not Sonnet/Opus)

### Cost Targets
- Daily main session: <$5
- Weekly sub-agents: <$2
- Alert if daily exceeds $10

---
*Auto-updated by agents. COMPY consolidates nightly.*
