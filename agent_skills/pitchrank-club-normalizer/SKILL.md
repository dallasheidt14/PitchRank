---
name: pitchrank-club-normalizer
description: Export teams by age/gender/state from Supabase using scripts/view_teams.py, then normalize club names and produce a review queue.
allowed-tools: Bash, Read, Grep, Glob
---

When invoked, ask for:
- age_group (u13..u19)
- gender (Male/Female)
- state (2-letter)
Then:
1) Run: python scripts/view_teams.py -a <age> -g <gender> -s <state> --export <out.csv>
2) Normalize club names into canonical club_id + confidence + action
3) Output:
- exports/<age>_<gender>_<state>.csv (raw)
- exports/<age>_<gender>_<state>__clubs_normalized.csv
- exports/<age>_<gender>_<state>__review_queue.csv (needs-review only)
Return: summary + top 20 review items
