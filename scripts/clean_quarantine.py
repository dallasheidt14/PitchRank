#!/usr/bin/env python3
"""
Clean quarantine_games table of unprocessable entries.
Auto-clears: U19 games, missing game_date

Run manually or via Cleany weekly job.
"""
import os
import psycopg2
from dotenv import load_dotenv

def clean_quarantine(dry_run=False):
    load_dotenv()
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    
    results = {}
    
    # Count before
    cur.execute('SELECT COUNT(*) FROM quarantine_games')
    before = cur.fetchone()[0]
    
    if dry_run:
        # Just count what would be deleted
        cur.execute("SELECT COUNT(*) FROM quarantine_games WHERE error_details LIKE '%U19%'")
        results['u19'] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM quarantine_games WHERE error_details LIKE '%Missing required field: game_date%'")
        results['no_date'] = cur.fetchone()[0]
    else:
        # Delete U19 games
        cur.execute("DELETE FROM quarantine_games WHERE error_details LIKE '%U19%'")
        results['u19'] = cur.rowcount
        
        # Delete missing game_date
        cur.execute("DELETE FROM quarantine_games WHERE error_details LIKE '%Missing required field: game_date%'")
        results['no_date'] = cur.rowcount
        
        conn.commit()
    
    # Count after
    cur.execute('SELECT COUNT(*) FROM quarantine_games')
    after = cur.fetchone()[0]
    
    conn.close()
    
    return {
        'before': before,
        'after': after,
        'deleted_u19': results['u19'],
        'deleted_no_date': results['no_date'],
        'dry_run': dry_run
    }

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Clean quarantine games')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting')
    args = parser.parse_args()
    
    result = clean_quarantine(dry_run=args.dry_run)
    
    mode = '[DRY RUN] ' if result['dry_run'] else ''
    print(f"{mode}Quarantine cleanup:")
    print(f"  U19 games: {result['deleted_u19']}")
    print(f"  No game_date: {result['deleted_no_date']}")
    print(f"  Before: {result['before']} → After: {result['after']}")
