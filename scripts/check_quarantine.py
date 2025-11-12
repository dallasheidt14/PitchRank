"""Check quarantined games to see why they weren't accepted"""
from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('.env.local')

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

# Get recent quarantined games
since_time = datetime(2025, 11, 11, 11, 4, 0).isoformat()
recent = supabase.table('quarantine_games').select('*').gte('created_at', since_time).order('created_at', desc=True).limit(50).execute()

print(f"=== Quarantined Games (since 11:04 AM) ===\n")
print(f"Total quarantined: {len(recent.data) if recent.data else 0}\n")

if recent.data:
    # Group by error type
    error_counts = {}
    for game in recent.data:
        errors = game.get('error_details', 'Unknown')
        if errors:
            # Extract first error
            first_error = errors.split(';')[0].strip()
            error_counts[first_error] = error_counts.get(first_error, 0) + 1
    
    print("Error breakdown:")
    for error, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {error}: {count}")
    
    print(f"\n=== Sample Quarantined Games ===")
    for i, game in enumerate(recent.data[:5], 1):
        print(f"\n{i}. Game Date: {game.get('raw_data', {}).get('game_date', 'N/A')}")
        print(f"   Home Team: {game.get('raw_data', {}).get('home_team_master_id', 'N/A')}")
        print(f"   Away Team: {game.get('raw_data', {}).get('away_team_master_id', 'N/A')}")
        print(f"   Reason: {game.get('reason_code', 'N/A')}")
        print(f"   Errors: {game.get('error_details', 'N/A')}")
else:
    print("No quarantined games found")

