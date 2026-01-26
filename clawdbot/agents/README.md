# PitchRank Agent Team

Three specialized agents working together to keep PitchRank running 24/7.

## The Team

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR MAC MINI                                │
│                                                                  │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                 │
│   │  CODER   │    │ CLEANER  │    │ SCRAPER  │                 │
│   │          │    │          │    │          │                 │
│   │ Python   │    │  Data    │    │  Game    │                 │
│   │ Expert   │    │ Quality  │    │ Hunter   │                 │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘                 │
│        │               │               │                        │
│        └───────────────┼───────────────┘                        │
│                        │                                        │
│                        ▼                                        │
│              ┌─────────────────┐                                │
│              │    SUPABASE     │                                │
│              │    DATABASE     │                                │
│              └─────────────────┘                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────┐
              │   YOUR PHONE    │
              │   (Telegram)    │
              └─────────────────┘
```

## Agent Roles

| Agent | Role | What They Do | What They DON'T Do |
|-------|------|--------------|-------------------|
| **Coder** | Python Expert | Write scripts, fix bugs, optimize code | Run data operations |
| **Cleaner** | Data Quality | Fix age groups, states, duplicates | Scrape or write code |
| **Scraper** | Game Hunter | Find and import new games | Clean data or write code |

---

## 🧑‍💻 Coder - Expert Python Developer
**File**: `coder.md`
**Model**: Claude Sonnet (excellent at coding)

The engineering expert. Writes all Python scripts, debugs issues, optimizes performance.

**What Coder Does**:
- Write new scripts when needed
- Debug failing scripts
- Optimize slow database queries
- Review code for security issues
- Add features to existing scripts

**Commands**:
```
@coder write script for [task]
@coder debug [error message]
@coder optimize [script name]
@coder add --dry-run to [script]
```

**Example**:
```
You: @coder I need a script to export rankings to CSV

Coder: 📝 Creating script: export_rankings_csv.py

Features:
- Filter by age group, gender, state
- Output to CSV or JSON
- Includes --dry-run flag

Usage:
  python scripts/export_rankings_csv.py --age u14 --state TX --output rankings.csv

✅ Script created and tested.
```

---

## 🧹 Cleaner - Data Quality Specialist
**File**: `cleaner.md`
**Model**: Claude Haiku (fast, efficient for repetitive checks)

The data quality guardian. Finds and fixes data issues with your approval.

**What Cleaner Does**:
- Find age group mismatches
- Identify missing state codes
- Detect duplicate teams
- Flag invalid data
- Execute fixes (with approval)

**Commands**:
```
@cleaner run patrol          # Full data quality scan
@cleaner fix age groups      # Fix age mismatches
@cleaner fix states          # Add missing state codes
@cleaner find duplicates     # Detect duplicate teams
@cleaner show issues         # List all current issues
```

**Schedule**:
- Every 4 hours: Full patrol scan
- Every hour: Quick check for new issues

**Example**:
```
You: @cleaner run patrol

Cleaner: 🔍 Scanning 15,847 teams...

Found:
- 23 age group mismatches
- 47 missing state codes
- 12 potential duplicate pairs

Reply FIX-AGE to fix age groups
Reply FIX-STATE to fix state codes
Reply REVIEW-DUPS to review duplicates

You: FIX-AGE

Cleaner: ⚠️ Preview (dry-run):
- FC Dallas 2014B: U13 → U11
- Solar SC 2013: U11 → U12
... (21 more)

Type CONFIRM-FIX-AGE to apply

You: CONFIRM-FIX-AGE

Cleaner: ✅ Fixed 23 teams. Rollback: UNDO-AGE-123
```

---

## 🔍 Scraper - Game Discovery Specialist
**File**: `scraper.md`
**Model**: Claude Haiku (fast, handles repetitive tasks)

The game hunter. Finds and imports new games from all providers.

**What Scraper Does**:
- Process user missing game requests
- Discover new tournament events
- Scrape team schedules
- Import games (new data only)

**Commands**:
```
@scraper check requests      # Show pending requests
@scraper process requests    # Import requested games
@scraper discover events     # Find new tournaments
@scraper scrape team [name]  # Scrape specific team
@scraper status              # Show scraping stats
```

**Schedule**:
- Every 15 min: Process pending requests
- Every 2 hours: Scrape stale teams (7+ days old)
- Every 6 hours: Discover new events

**Example**:
```
You: @scraper check requests

Scraper: 📥 3 pending requests:
1. FC Dallas 2014B (requested 2h ago)
2. Solar SC 2013 (requested 5h ago)
3. Chicago Fire 2015 (requested 12h ago)

Reply SCRAPE-ALL to process all

You: SCRAPE-ALL

Scraper: 🔍 Processing...

Request 1: FC Dallas 2014B
- Games found: 8
- New games: 3 ✅
- Already imported: 5

Request 2: Solar SC 2013
- Games found: 12
- New games: 7 ✅
- Already imported: 5

Request 3: Chicago Fire 2015
- Games found: 6
- New games: 2 ✅
- Already imported: 4

✅ Total: 12 new games imported
```

---

## Safety Model

All three agents follow strict safety rules:

```
┌────────────────────────────────────────┐
│           SAFETY WRAPPER               │
├────────────────────────────────────────┤
│ ✅ READ operations    → Always allowed │
│ ✅ ADD new data       → Allowed        │
│ ⚠️  MODIFY existing   → Needs approval │
│ 🚫 DELETE             → Forbidden      │
└────────────────────────────────────────┘
```

**Key Protections**:
1. **Games are immutable** - No agent can modify existing games
2. **Approval required** - All fixes need your explicit approval
3. **Dry-run first** - Every modification shows preview first
4. **Full audit trail** - Everything logged with rollback capability

---

## How They Work Together

### Scenario: User Reports Missing Games

```
User website → scrape_requests table
                      │
                      ▼
              ┌───────────────┐
              │   SCRAPER     │ ← Finds and imports games
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │   CLEANER     │ ← Validates imported data
              └───────┬───────┘
                      │
                      ▼
              User notified ✅
```

### Scenario: New Feature Needed

```
You: "@coder I need to export team data with SOS scores"
                      │
                      ▼
              ┌───────────────┐
              │    CODER      │ ← Writes the script
              └───────┬───────┘
                      │
                      ▼
              Script ready for Cleaner/Scraper to use
```

### Scenario: Data Issue Found

```
              ┌───────────────┐
              │   CLEANER     │ ← Patrol finds 23 issues
              └───────┬───────┘
                      │
                      ▼
              You (Telegram): "FIX-AGE"
                      │
                      ▼
              ┌───────────────┐
              │   CLEANER     │ ← Applies fix with approval
              └───────────────┘
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Check overall status | `status` |
| Run data quality scan | `@cleaner run patrol` |
| Fix age group issues | `@cleaner fix age groups` |
| Process game requests | `@scraper process requests` |
| Find new events | `@scraper discover events` |
| Create new script | `@coder write [description]` |
| Debug an error | `@coder debug [error]` |

---

## Configuration

In `~/.clawdbot/clawdbot.json`:

```json
{
  "agents": {
    "coder": {
      "model": "anthropic/claude-sonnet-4",
      "skills": ["pitchrank/coder"]
    },
    "cleaner": {
      "model": "anthropic/claude-haiku-3",
      "skills": ["pitchrank/cleaner"]
    },
    "scraper": {
      "model": "anthropic/claude-haiku-3",
      "skills": ["pitchrank/scraper"]
    }
  }
}
```

---

## Shared Resources

All agents access:
- **Database**: Supabase (read/write per their permissions)
- **Scripts**: `/home/user/PitchRank/scripts/`
- **Logs**: `~/.clawdbot/logs/`

Coder maintains:
- Script repository
- Code documentation

Cleaner maintains:
- Data quality metrics
- Fix history

Scraper maintains:
- Scrape logs
- Provider status
