"""Check the review queue"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

# Get all queue entries
queue = supabase.table('team_match_review_queue').select('*').eq('provider_id', 'modular11').execute()
print(f"Total entries: {len(queue.data)}")
print()
for item in queue.data:
    conf = item.get('confidence_score', 0)
    name = item.get('provider_team_name', 'Unknown')
    status = item.get('status', '?')
    has_suggestion = 'Yes' if item.get('suggested_master_team_id') else 'No'
    print(f"{conf:.2f} - {name} (status: {status}, has_suggestion: {has_suggestion})")

