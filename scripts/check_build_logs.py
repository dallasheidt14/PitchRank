"""Check build logs for latest import"""
from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('.env.local')

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
provider_id = provider_result.data['id']

# Check logs since 11:04 AM (when latest scrape started)
since_time = datetime(2025, 11, 11, 11, 4, 0).isoformat()
logs = supabase.table('build_logs').select('*').eq('provider_id', provider_id).gte('started_at', since_time).order('started_at', desc=True).limit(10).execute()

print("=== Recent Build Logs (since 11:04 AM) ===\n")

if logs.data:
    for log in logs.data:
        print(f"Build ID: {log.get('build_id', 'N/A')}")
        print(f"  Stage: {log.get('stage', 'N/A')}")
        print(f"  Processed: {log.get('records_processed', 0)}")
        print(f"  Succeeded: {log.get('records_succeeded', 0)}")
        print(f"  Failed: {log.get('records_failed', 0)}")
        print(f"  Started: {log.get('started_at', 'N/A')}")
        if log.get('errors'):
            print(f"  Errors: {log.get('errors')}")
        print()
else:
    print("No build logs found - import may not have run")

