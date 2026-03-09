#!/usr/bin/env python3
"""
Export merge history with club names for trend analysis.

Outputs a CSV with deprecated team, canonical team, club names, and merge metadata.
Run and share the CSV to analyze club name patterns in manual merges.

Usage:
    python scripts/export_merge_history.py
    python scripts/export_merge_history.py --output data/exports/merge_history.csv
"""
import argparse
import csv
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


def main():
    parser = argparse.ArgumentParser(description='Export merge history with club names')
    parser.add_argument('--output', '-o', default='data/exports/merge_history.csv',
                        help='Output CSV path')
    parser.add_argument('--limit', '-n', type=int, default=500,
                        help='Max merges to export (default 500). Use 0 for all.')
    args = parser.parse_args()

    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return 1

    db = create_client(supabase_url, supabase_key)

    print("Fetching merge history...")
    merges = []
    page_size = 1000
    offset = 0
    while True:
        result = db.table('team_merge_map').select(
            'id, deprecated_team_id, canonical_team_id, merged_at, merged_by, merge_reason'
        ).order('merged_at', desc=True).range(offset, offset + page_size - 1).execute()
        batch = result.data or []
        if not batch:
            break
        merges.extend(batch)
        if args.limit and len(merges) >= args.limit:
            merges = merges[:args.limit]
            break
        if len(batch) < page_size:
            break
        offset += page_size
    if not merges:
        print("No merges found.")
        return 0

    # Fetch team details (name, club_name) for all deprecated and canonical IDs
    dep_ids = list({m['deprecated_team_id'] for m in merges})
    can_ids = list({m['canonical_team_id'] for m in merges})
    all_ids = list(set(dep_ids + can_ids))

    teams = {}
    batch_size = 100
    for i in range(0, len(all_ids), batch_size):
        batch = all_ids[i:i + batch_size]
        r = db.table('teams').select('team_id_master, team_name, club_name, state_code').in_(
            'team_id_master', batch
        ).execute()
        for t in (r.data or []):
            teams[t['team_id_master']] = t

    # Build output rows
    rows = []
    for m in merges:
        dep = teams.get(m['deprecated_team_id'], {})
        can = teams.get(m['canonical_team_id'], {})
        rows.append({
            'merged_at': m.get('merged_at', ''),
            'merged_by': m.get('merged_by', ''),
            'merge_reason': (m.get('merge_reason') or '')[:100],
            'deprecated_team_name': dep.get('team_name', ''),
            'deprecated_club_name': dep.get('club_name', ''),
            'deprecated_state': dep.get('state_code', ''),
            'canonical_team_name': can.get('team_name', ''),
            'canonical_club_name': can.get('club_name', ''),
            'canonical_state': can.get('state_code', ''),
        })

    # Write CSV
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=[
            'merged_at', 'merged_by', 'merge_reason',
            'deprecated_team_name', 'deprecated_club_name', 'deprecated_state',
            'canonical_team_name', 'canonical_club_name', 'canonical_state',
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"Exported {len(rows)} merges to {out_path}")
    print()
    print("Sample (first 5):")
    print("-" * 100)
    for i, r in enumerate(rows[:5], 1):
        print(f"{i}. {r['deprecated_team_name'][:35]:<35} | {r['deprecated_club_name'][:25]:<25} → {r['canonical_club_name'][:25]}")
    return 0


if __name__ == '__main__':
    exit(main())
