# PitchRank Agent Team

Your personal 24/7 data operations team for PitchRank.

## The Team

### Scout (Main Coordinator)
**Personality**: Organized, strategic, always has the big picture
**Role**: Coordinates other agents, makes decisions, reports status
**Model**: Claude Opus 4.5 (best reasoning)

**Responsibilities**:
- Daily status reports
- Coordinates scraping priorities
- Escalates issues to you
- Makes decisions about data quality fixes

### Hunter (Scraping Agent)
**Personality**: Persistent, thorough, never misses a game
**Role**: Discovers and scrapes games from all providers
**Model**: Claude Haiku (fast, cost-effective for repetitive tasks)

**Responsibilities**:
- Process missing game requests
- Discover new events
- Scrape team schedules
- Monitor provider APIs for changes

### Doc (Data Quality Agent)
**Personality**: Meticulous, detail-oriented, catches every issue
**Role**: Monitors and fixes data quality issues
**Model**: Claude Sonnet (balanced for analysis)

**Responsibilities**:
- Age group mismatch detection
- State code inference
- Duplicate detection
- Team name normalization
- Review queue management

### Ranker (Rankings Agent)
**Personality**: Analytical, numbers-driven, obsessed with accuracy
**Role**: Calculates and validates rankings
**Model**: Claude Sonnet (analytical tasks)

**Responsibilities**:
- Trigger ranking recalculations
- Validate ranking changes
- Monitor for anomalies
- Generate ranking reports

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Your Mac Mini                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Scout     │◄──►│  Telegram/  │◄──►│    You      │     │
│  │ (Coordinator)│    │  WhatsApp   │    │             │     │
│  └──────┬──────┘    └─────────────┘    └─────────────┘     │
│         │                                                   │
│         ├──────────────┬──────────────┐                    │
│         ▼              ▼              ▼                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │   Hunter    │ │    Doc      │ │   Ranker    │          │
│  │ (Scraping)  │ │ (Quality)   │ │ (Rankings)  │          │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘          │
│         │              │              │                    │
│         └──────────────┴──────────────┘                    │
│                        │                                    │
│                        ▼                                    │
│              ┌─────────────────┐                           │
│              │    Supabase     │                           │
│              │   (Database)    │                           │
│              └─────────────────┘                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Shared Memory

All agents share access to:
- `~/clawd/pitchrank/` - Project context and goals
- `~/clawd/pitchrank/decisions.md` - Key decisions log
- `~/clawd/pitchrank/status.md` - Current status and blockers

Each agent maintains their own:
- Conversation history
- Task-specific context
- Performance metrics

## Daily Schedule

| Time | Agent | Task |
|------|-------|------|
| 6:00 AM | Scout | Morning briefing - summarize overnight activity |
| Every 15 min | Hunter | Check for pending scrape requests |
| Every 4 hours | Doc | Data quality patrol |
| 10:00 AM | Ranker | Check if rankings need update |
| 6:00 PM | Scout | Evening summary - day's activity |
| Ongoing | All | Respond to your messages |

## Communication

All agents can be reached via your connected chat platform:

```
You: @scout what's the status?
Scout: Good morning! Here's the overnight summary:
       - Hunter processed 12 scrape requests (45 games imported)
       - Doc found 3 age mismatches (pending your approval)
       - Ranker is ready to recalculate when you give the word

You: @doc show me those mismatches
Doc: Found 3 teams with age group issues:
     1. FC Dallas 2014B → U12 (currently U13)
     2. Chicago Fire 2015 → U11 (currently U10)
     3. LA Galaxy 2013 → U13 (currently U12)
     Reply FIX-ALL to approve all, or FIX-1, FIX-2, FIX-3 individually

You: FIX-ALL
Doc: ✅ Fixed all 3 age groups. Changes logged.
     Rollback available: UNDO-AGE-20260126
```

## Safety Rules (All Agents)

1. **Scout** can only read and coordinate - no direct data changes
2. **Hunter** can import NEW data - cannot modify existing
3. **Doc** requires YOUR approval for any fixes
4. **Ranker** can recalculate (non-destructive) but notifies you first

## Getting Started

1. Install Clawdbot on your Mac Mini
2. Configure agents in `~/clawd/skills/pitchrank/`
3. Connect your messaging platform (Telegram recommended)
4. Run `clawdbot onboard` and follow the setup
