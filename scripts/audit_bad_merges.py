#!/usr/bin/env python3
"""
Identify and fix bad club name merges from SQL files.
Focus on clearly wrong merges where different clubs were combined.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
import re

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY'))

# Known bad merges from SQL analysis - clubs that should NOT have been merged
# Format: (wrong_club_name, correct_club_name, state, gender, team_name_pattern)
BAD_MERGES = [
    # Tennessee - already fixed
    # ('Tennessee SC', 'Tennessee United SC', 'TN', 'Female', r'united|tusc'),
    
    # California
    ('Beach Futbol Club', 'Beach United FC', 'CA', 'Female', r'beach united|bufc'),
    ('Central Coast United SC', 'Central Coast FC', 'CA', 'Female', r'central coast fc|ccfc(?! united)'),
    ('Elk Grove Soccer', 'Elk Grove United Soccer Club', 'CA', 'Female', r'elk grove united|egus'),
    ('Los Angeles Soccer Club', 'Los Angeles United FC', 'CA', 'Female', r'la united|los angeles united'),
    ('Valley United SC', 'Valley FC', 'CA', 'Female', r'valley fc(?! united)'),
    ('Legends FC', 'Legends Futbol Academy', 'CA', 'Female', r'legends academy|legends futbol academy|lfa'),
    
    # Check if these exist and need fixing
]

def find_and_fix(wrong_club, correct_club, state, gender, pattern):
    """Find teams with wrong club_name and fix based on team_name pattern."""
    result = supabase.table('teams').select('id, club_name, team_name').eq('club_name', wrong_club).eq('state_code', state).eq('gender', gender).eq('is_deprecated', False).execute()
    
    if not result.data:
        return 0, []
    
    to_fix = []
    for t in result.data:
        if re.search(pattern, t['team_name'], re.IGNORECASE):
            to_fix.append(t)
    
    return len(result.data), to_fix

print("=== Auditing Bad Merges ===\n")

for wrong, correct, state, gender, pattern in BAD_MERGES:
    total, to_fix = find_and_fix(wrong, correct, state, gender, pattern)
    print(f"[{state}] {wrong} → {correct}")
    print(f"  Total with wrong club: {total}")
    print(f"  Should be restored: {len(to_fix)}")
    if to_fix:
        for t in to_fix[:3]:
            print(f"    - {t['team_name']}")
        if len(to_fix) > 3:
            print(f"    ... and {len(to_fix) - 3} more")
    print()
