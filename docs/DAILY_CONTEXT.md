# Daily Context — Shared State for All Agents

> Updated throughout the day. All agents should read this on startup.

**Date:** 2026-02-15 (Sunday) — Updated by Cleany 7pm MT

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

## 🔄 Today's Activity (Feb 15 - Sunday)
- 🧹 **Cleany 7pm weekly run:** Quarantine cleaned (239 → 39 U19 games removed). GH secrets fixed. Auto Merge Queue workflow re-triggered.
- 📱 **Socialy:** Awaiting GSC credential fix from D H
- 🕷️ **Scrappy:** Next scheduled Mon/Wed 10am (CA/TX/AZ rotation)
- ✅ **Data pipeline:** Healthy, no new issues detected
- ℹ️ **GitHub Actions:** Weekly Data Hygiene ✅ (all success). Auto Merge Queue fixed & running.

## ⚠️ Known Issues
- **[🔴 CRITICAL]** API Credit Exhaustion — Originally Feb 7-12. Monitor if errors return (Feb 13 plateau suggests healing).
- **[🔴 CRITICAL]** GSC credentials missing (`gsc_credentials.json`) — blocks Socialy SEO reporting. D H needs to restore or regenerate.
- **[⚠️ FIXED]** Auto Merge Queue GH Action — Missing Supabase secrets in Actions. Fixed by Cleany (Feb 15 7pm): added SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY, re-triggered workflow.
- **[MONITOR]** PRE-team movement driven purely by SOS, no game data — may indicate scraping gap for academy divisions
- **[RESOLVED]** TGS import was slow — Codey deployed 10-15x speedup (Feb 7)
- **[INFO]** Quarantine data quality: 39 remaining entries (down from 239). All validation_failed: TGS (26, missing IDs) + GotSport (13, team=opponent parsing edge case). Expected, not critical.

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
