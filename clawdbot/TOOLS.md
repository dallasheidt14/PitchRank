# PitchRank Tools Reference

Local configuration and tool-specific notes for the PitchRank Clawdbot agents.

---

## Database Access

### Supabase Connection
```
URL: Set in SUPABASE_URL env var
Key: Set in SUPABASE_SERVICE_ROLE_KEY env var
Region: US East
```

### Key Tables

| Table | Purpose | Agent Access |
|-------|---------|--------------|
| `teams` | Master team registry | Read: All, Write: @cleaner |
| `games` | Game results (IMMUTABLE) | Read: All, Write: @scraper (new only) |
| `scrape_requests` | User missing game requests | Read: All, Write: @scraper |
| `team_match_review_queue` | Uncertain team matches | Read: All, Write: @cleaner |
| `build_logs` | Import/operation logs | Read: All, Write: All |
| `rankings_full` | Calculated rankings | Read: All, Write: None (via script only) |

---

## Data Providers

### GotSport (Primary)
- **Base URL**: gotsport.com
- **Rate Limit**: 30 concurrent requests
- **Delay**: 2 seconds between batches
- **Timeout**: 60 seconds per request
- **Retry**: 3 attempts with exponential backoff

### TGS (Tournament Grid Series)
- **Event Range**: 4000-4200 (current)
- **Rate Limit**: 10 concurrent requests
- **Delay**: 5 seconds between requests

### Modular11 / MLS NEXT
- **Age Groups**: U13-U17 only
- **Lookback**: 21 days
- **Rate Limit**: 5 concurrent requests

### AthleteOne
- **Usage**: On-demand only
- **Rate Limit**: Low volume, be conservative

---

## Scripts Reference

### Data Quality

| Script | Purpose | Safe? | Dry-run? |
|--------|---------|-------|----------|
| `fix_team_age_groups.py` | Fix age/birth year mismatches | ⚠️ Modifies | ✅ Yes |
| `match_state_from_club.py` | Infer state from club | ⚠️ Modifies | ✅ Yes |
| `find_duplicate_teams.py` | Detect potential duplicates | ✅ Read-only | ✅ Yes |
| `check_data_quality.py` | Generate quality report | ✅ Read-only | N/A |

### Scraping

| Script | Purpose | Safe? | Dry-run? |
|--------|---------|-------|----------|
| `process_missing_games.py` | Import requested games | ✅ Adds only | ✅ Yes |
| `scrape_games.py` | Bulk team scraping | ✅ Adds only | N/A |
| `scrape_new_gotsport_events.py` | Discover events | ✅ Read-only | ✅ Yes |
| `scrape_tgs_event.py` | TGS event import | ✅ Adds only | ✅ Yes |

### Utilities

| Script | Purpose | Safe? |
|--------|---------|-------|
| `show_pending_requests.py` | List scrape queue | ✅ Read-only |
| `show_review_queue.py` | List match reviews | ✅ Read-only |
| `show_recent_changes.py` | Audit log viewer | ✅ Read-only |
| `revert_team_merge.py` | Undo a merge | ⚠️ Modifies |

---

## File Locations

```
~/projects/PitchRank/
├── scripts/                 # Executable scripts
├── src/                     # Core library code
├── clawdbot/               # Clawdbot integration
│   ├── SKILL.md            # Main instructions
│   ├── SOUL.md             # Personality/context
│   ├── TOOLS.md            # This file
│   └── agents/             # Agent definitions
├── frontend/               # Next.js web app (don't touch)
├── supabase/               # DB migrations (don't touch)
└── .env.local              # Secrets (never read/expose)
```

---

## Common Patterns

### Running Scripts

```bash
# Always from project root
cd ~/projects/PitchRank

# Always activate venv if using one
source venv/bin/activate  # if applicable

# Always check dry-run first
python scripts/some_script.py --dry-run

# Then run for real if approved
python scripts/some_script.py
```

### Checking Results

```python
# In Python, use the Supabase client
from supabase import create_client
import os

client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# Count pending requests
result = client.table("scrape_requests")\
    .select("id", count="exact")\
    .eq("status", "pending")\
    .execute()
print(f"Pending requests: {result.count}")
```

---

## Timeouts & Limits

| Operation | Timeout | Max Items |
|-----------|---------|-----------|
| Single scrape request | 60s | 1 team |
| Batch scrape | 6 hours | 25,000 teams |
| Event import | 4 hours | ~200 teams |
| Data quality fix | 5 min | 1,000 records |
| Ranking calculation | 30 min | All teams |

---

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| `RATE_LIMITED` | Provider blocked us | Wait 5 min, retry |
| `AUTH_FAILED` | Bad credentials | Check env vars |
| `TIMEOUT` | Request too slow | Retry with backoff |
| `DUPLICATE` | Record exists | Safe to ignore |
| `VALIDATION_FAILED` | Bad data format | Quarantine record |
| `LOW_CONFIDENCE` | Match score < 75% | Add to review queue |

---

## Quick Diagnostics

### Check Database Connection
```bash
python -c "
from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv('.env.local')
c = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
r = c.table('teams').select('team_id_master', count='exact').limit(1).execute()
print(f'Connected! Teams: {r.count}')
"
```

### Check Pending Work
```bash
python scripts/show_pending_requests.py
python scripts/show_review_queue.py
```

### Check Recent Activity
```bash
python scripts/show_recent_changes.py --hours 24
python scripts/show_import_metrics.py
```

---

## Notes

- **Never commit .env.local** - Contains secrets
- **Games are immutable** - Database trigger prevents updates
- **Rankings run Mondays** - Don't trigger mid-week without reason
- **Quiet hours** - No alerts 10 PM - 6 AM MT unless critical
