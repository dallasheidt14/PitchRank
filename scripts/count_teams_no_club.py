#!/usr/bin/env python3
"""Quick count of teams with missing club_name."""
import os
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

r1 = db.table("teams").select("team_id_master", count="exact", head=True).eq("is_deprecated", False).is_("club_name", "null").execute()
r2 = db.table("teams").select("team_id_master", count="exact", head=True).eq("is_deprecated", False).eq("club_name", "").execute()

null_count = r1.count if hasattr(r1, "count") else 0
empty_count = r2.count if hasattr(r2, "count") else 0

print(f"Teams with club_name NULL: {null_count:,}")
print(f"Teams with club_name empty: {empty_count:,}")
print(f"Total: {null_count + empty_count:,}")
