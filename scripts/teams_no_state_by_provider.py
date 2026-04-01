#!/usr/bin/env python3
"""Count teams with no state_code, grouped by provider."""

import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from supabase import create_client

if Path(".env.local").exists():
    load_dotenv(".env.local", override=True)
else:
    load_dotenv()

url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
db = create_client(url, key)

# Get providers
providers = db.table("providers").select("id,code,name").execute().data or []
provider_lookup = {p["id"]: p for p in providers}

# Fetch teams with no state_code (NULL or empty)
by_provider: dict = defaultdict(int)
no_provider = 0
page_size = 1000
offset = 0

while True:
    # NULL state_code
    r1 = (
        db.table("teams")
        .select("team_id_master,provider_id")
        .eq("is_deprecated", False)
        .is_("state_code", "null")
        .range(offset, offset + page_size - 1)
        .execute()
    )
    for t in r1.data or []:
        pid = t.get("provider_id")
        if pid:
            by_provider[pid] += 1
        else:
            no_provider += 1

    if len(r1.data or []) < page_size:
        break
    offset += page_size

offset = 0
while True:
    # Empty state_code
    r2 = (
        db.table("teams")
        .select("team_id_master,provider_id")
        .eq("is_deprecated", False)
        .eq("state_code", "")
        .range(offset, offset + page_size - 1)
        .execute()
    )
    for t in r2.data or []:
        pid = t.get("provider_id")
        if pid:
            by_provider[pid] += 1
        else:
            no_provider += 1

    if len(r2.data or []) < page_size:
        break
    offset += page_size

# Dedupe: teams could appear in both NULL and empty if we're not careful
# Actually NULL and empty are mutually exclusive per row. So we're good.
# But wait - we're counting the same teams twice if a team has state_code NULL
# in one query and we also query for empty. A team can't have both. So we're fine.

print("Teams with no state_code, by provider:\n")
print(f"{'Provider':<20} {'Count':>8}")
print("-" * 30)

total = 0
for pid, count in sorted(by_provider.items(), key=lambda x: -x[1]):
    p = provider_lookup.get(pid, {})
    code = p.get("code", str(pid)[:8])
    name = p.get("name", "?")
    label = f"{code} ({name})"
    print(f"{label:<20} {count:>8,}")
    total += count

if no_provider:
    print(f"{'<no provider_id>':<20} {no_provider:>8,}")
    total += no_provider

print("-" * 30)
print(f"{'Total':<20} {total:>8,}")
