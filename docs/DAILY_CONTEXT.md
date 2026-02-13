# Daily Context — Shared State for All Agents

> Updated throughout the day. All agents should read this on startup.

**Date:** 2026-02-12 (Thursday)

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

## 🔄 Today's Activity (Feb 12 - Thursday)
- 📱 **Socialy scheduled 9am today** (awaiting GSC credential fix)
- 🕷️ **Scrappy scheduled Mon/Wed 10am** — next cycle begins Monday 6am (CA/TX/AZ rotation)
- ✅ **Watchy 8am health check:** Teams 97,124 | Games 691,093 | Quarantine 769 (all U19 filtered correctly)
- ✅ **Cleany weekly run ready:** Next Sunday 7pm (Feb 15)
- ✅ **Data pipeline healthy:** 5k games/24h flowing, quarantine stable

## ⚠️ Known Issues
- **[🔴 CRITICAL]** API Credit Exhaustion — PERSISTENT for 5 DAYS (Feb 7-12). 28 errors in latest 3 days alone. D H MUST verify Anthropic account/billing immediately.
- **[🔴 CRITICAL]** Error rate escalating: Feb 10 (5) → Feb 11 (14) → Feb 12 (9) = unsustainable. System approaching failure threshold.
- **[🔴 CRITICAL]** GSC credentials missing (`gsc_credentials.json`) — blocks Socialy SEO reporting. D H needs to restore or regenerate.
- **[MONITOR]** PRE-team movement driven purely by SOS, no game data — may indicate scraping gap for academy divisions
- **[RESOLVED]** TGS import was slow — Codey deployed 10-15x speedup (Feb 7)
- **[TRANSIENT]** Connection errors non-blocking (agents continue tasks), but frequency indicates API strain

## 🎯 Priorities
1. Let D H focus on data review without noise
2. Be autonomous — act, don't just suggest
3. Track mistakes and learn from them

## 💰 Cost Tracking

### Today's Spend (2026-02-09)
| Session | Model | Est. Cost |
|---------|-------|-----------|
| Scrappy 10am | Haiku | ~$0.02 |
| (COMPY tonight 10:30pm) | Haiku | ~$0.05 |

**Running total (10am):** ~$0.07 (Haiku = ultra-low cost)

### Cost Reduction Wins (Feb 8)
- ✅ Main session: Opus → Haiku = **-80% per token**
- ✅ All sub-agents on Haiku (established Feb 7)
- ✅ Heartbeat interval 30m → 1h = ~50% fewer calls

### Cost Targets
- Daily main session: <$5
- Weekly sub-agents: <$2
- Alert if daily exceeds $10

---
*Auto-updated by agents. COMPY consolidates nightly.*
