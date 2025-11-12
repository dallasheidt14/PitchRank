#!/usr/bin/env python3
"""Check detailed import metrics"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv('.env.local')

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Get latest build log
result = supabase.table('build_logs').select('*').eq('build_id', '20251111_124332').eq('stage', 'game_import').order('created_at', desc=True).limit(1).execute()

if result.data:
    log = result.data[0]
    metrics = log.get('metrics', {})
    
    print('=== Latest Import Metrics (Build: 20251111_124332) ===')
    print(f"Games processed: {metrics.get('games_processed', 0)}")
    print(f"Games accepted: {metrics.get('games_accepted', 0)}")
    print(f"Games quarantined: {metrics.get('games_quarantined', 0)}")
    print(f"Duplicates found (existing): {metrics.get('duplicates_found', 0)}")
    print(f"Duplicates skipped (perspective): {metrics.get('duplicates_skipped', 0)}")
    print(f"Skipped empty scores: {metrics.get('skipped_empty_scores', 0)}")
    print(f"Teams matched: {metrics.get('teams_matched', 0)}")
    print(f"Teams created: {metrics.get('teams_created', 0)}")
    
    errors = metrics.get('errors', [])
    print(f"\nErrors: {len(errors)}")
    if errors:
        print("\nFirst few errors:")
        for e in errors[:5]:
            print(f"  - {e}")
else:
    print("Build log not found")



