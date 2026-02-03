---
name: agent-quickstart
description: Quick reference for all PitchRank sub-agents. Read this first when spawned to understand your role, tools, and common tasks.
---

# Agent Quickstart Guide

## Your Identity
You are a specialized sub-agent of PitchRank. The orchestrator spawned you for a specific task. Be concise, autonomous, and report results clearly.

## Environment
- **Workspace:** `/Users/pitchrankio-dev/Projects/PitchRank`
- **Database:** Supabase (use `DATABASE_URL` from `.env`)
- **GitHub:** `dallasheidt14/PitchRank`

## Common Commands

### Database Query
```python
import os, psycopg2
from dotenv import load_dotenv
load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("YOUR QUERY")
print(cur.fetchall())
conn.close()
```

### GitHub Actions
```bash
gh run list --repo dallasheidt14/PitchRank --limit 5
gh run view <id> --repo dallasheidt14/PitchRank
gh workflow run "Name" --repo dallasheidt14/PitchRank
```

### Git Commit
```bash
cd /Users/pitchrankio-dev/Projects/PitchRank
git add -A
git commit -m "type: description"
git push
```

## Commit Message Types
- `fix:` — Bug fixes
- `feat:` — New features
- `chore:` — Maintenance, cleanup
- `docs:` — Documentation only

## Protected Files (ASK BEFORE MODIFYING)
- `src/utils/merge_resolver.py`
- `src/utils/merge_suggester.py`
- `src/utils/club_normalizer.py`
- `src/etl/team_matcher.py`
- `scripts/run_all_merges.py`
- `scripts/merge_teams.py`

## When Done
Report to D H:
1. What you did (brief)
2. Results/stats
3. Any issues found
4. Recommendations (if any)

## If Stuck
1. Check relevant `.claude/skills/*.skill.md` for guidance
2. Try a different approach
3. Report what you tried and where you're blocked
