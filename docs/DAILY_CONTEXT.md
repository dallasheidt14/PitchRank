# Daily Context — Shared State for All Agents

> Updated throughout the day. All agents should read this on startup.

**Date:** 2026-02-10 (Tuesday)

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

## 🔄 Today's Activity (Feb 10 - Tuesday)
- ✅ Movy Weekly Report (10am MT) — Generated movers analysis, detected PRE-team SOS anomaly
- ✅ Scrappy Monday Monitor (10am MT) — all checks running
- ✅ Scrape Games workflow triggered (25k limit)
- ⚠️ Missing Games Backfill transient failure (GitHub 500 on repo fetch at 16:54 UTC) — **not escalating**, single occurrence
- ✅ GotSport + Modular11/MLS NEXT scrapes operational
- TGS Event Scrape: cancelled (routine)
- Games (24h): 5,272 ✓
- Quarantine: 365 ✓
- Stale teams: 33,777 (normal pre-scrape state for Monday)

## ⚠️ Known Issues
- **[CRITICAL]** API Credit Exhaustion — Persistent across 3 days (Feb 7-9). 53 total errors. D H needs to verify Anthropic account/billing.
- **[MONITOR]** PRE-team movement driven purely by SOS, no game data — may indicate scraping gap for academy divisions
- **[RESOLVED]** TGS import was slow — Codey deployed 10-15x speedup (Feb 7)
- **[TRANSIENT]** GitHub 500 on Process Missing Games (Feb 9 16:54 UTC) — single failure, GH issue not ours

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
