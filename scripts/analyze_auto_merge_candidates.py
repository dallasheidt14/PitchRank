#!/usr/bin/env python3
"""
Analyze team_match_review_queue for auto-merge candidates.

This script identifies queue entries that could be safely auto-approved
based on confidence score and matching criteria.

Usage:
    python3 scripts/analyze_auto_merge_candidates.py [--dry-run] [--min-confidence 0.85] [--execute]
"""
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

load_dotenv(Path(__file__).parent.parent / '.env')

def get_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

def analyze_candidates(min_confidence=0.85, limit=100):
    """Find auto-merge candidates with safety checks."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get candidates with suggestions above threshold
    cur.execute('''
        SELECT 
            q.id,
            q.provider_id,
            q.provider_team_id,
            q.provider_team_name,
            q.suggested_master_team_id,
            q.confidence_score,
            q.match_details,
            t.team_name as master_team_name,
            t.club_name as master_club_name,
            t.gender as master_gender,
            t.age_group as master_age_group
        FROM team_match_review_queue q
        LEFT JOIN teams t ON q.suggested_master_team_id = t.id
        WHERE q.status = 'pending'
          AND q.suggested_master_team_id IS NOT NULL
          AND q.confidence_score >= %s
        ORDER BY q.confidence_score DESC
        LIMIT %s
    ''', (min_confidence, limit))
    
    candidates = cur.fetchall()
    conn.close()
    return candidates

def categorize_candidates(candidates):
    """Categorize candidates by safety level."""
    safe = []      # High confidence + metadata matches
    review = []    # Medium confidence or slight mismatches
    risky = []     # Lower confidence or mismatches
    
    for c in candidates:
        score = float(c['confidence_score'])
        details = c['match_details'] or {}
        
        # Check if metadata matches
        queue_gender = details.get('gender', '').lower()
        queue_age = details.get('age_group', '').lower()
        master_gender = (c['master_gender'] or '').lower()
        master_age = (c['master_age_group'] or '').lower()
        
        gender_match = not queue_gender or not master_gender or queue_gender == master_gender
        age_match = not queue_age or not master_age or queue_age == master_age
        
        if score >= 0.95 and gender_match and age_match:
            safe.append(c)
        elif score >= 0.88 and gender_match and age_match:
            review.append(c)
        else:
            risky.append(c)
    
    return safe, review, risky

def display_candidate(c, verbose=False):
    """Display a single candidate."""
    score = float(c['confidence_score'])
    details = c['match_details'] or {}
    
    print(f"  [{c['id']}] {c['provider_team_name']}")
    print(f"       → {c['master_team_name']} ({c['master_club_name']})")
    print(f"       Confidence: {score:.1%} | Provider: {c['provider_id']}")
    
    if verbose:
        queue_info = f"Queue: gender={details.get('gender')}, age={details.get('age_group')}"
        master_info = f"Master: gender={c['master_gender']}, age={c['master_age_group']}"
        print(f"       {queue_info}")
        print(f"       {master_info}")
    print()

def execute_auto_merge(candidates, dry_run=True):
    """Execute auto-merge for safe candidates."""
    if dry_run:
        print("\n🔍 DRY RUN - No changes will be made\n")
    else:
        print("\n⚡ EXECUTING AUTO-MERGE\n")
    
    conn = get_connection()
    cur = conn.cursor()
    
    approved = 0
    failed = 0
    
    for c in candidates:
        try:
            if not dry_run:
                # Create alias linking provider team to master team
                cur.execute('''
                    INSERT INTO team_alias_map (team_id, provider_id, provider_team_id, provider_team_name)
                    SELECT %s, p.id, %s, %s
                    FROM providers p WHERE p.code = %s
                    ON CONFLICT (provider_id, provider_team_id) DO NOTHING
                ''', (c['suggested_master_team_id'], c['provider_team_id'], 
                      c['provider_team_name'], c['provider_id']))
                
                # Update queue status
                cur.execute('''
                    UPDATE team_match_review_queue 
                    SET status = 'approved', 
                        reviewed_by = 'auto-merge-script',
                        reviewed_at = NOW()
                    WHERE id = %s
                ''', (c['id'],))
                
                conn.commit()
            
            approved += 1
            action = "Would approve" if dry_run else "Approved"
            print(f"  ✅ {action}: [{c['id']}] {c['provider_team_name']} → {c['master_team_name']}")
            
        except Exception as e:
            failed += 1
            print(f"  ❌ Failed [{c['id']}]: {e}")
            if not dry_run:
                conn.rollback()
    
    conn.close()
    return approved, failed

def main():
    parser = argparse.ArgumentParser(description='Analyze auto-merge candidates')
    parser.add_argument('--min-confidence', type=float, default=0.85,
                        help='Minimum confidence score (default: 0.85)')
    parser.add_argument('--limit', type=int, default=500,
                        help='Max candidates to analyze (default: 500)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed info')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Show what would be merged (default: True)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute the merges (BE CAREFUL)')
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔍 AUTO-MERGE CANDIDATE ANALYSIS")
    print("=" * 60)
    print(f"Min confidence: {args.min_confidence:.0%}")
    print(f"Limit: {args.limit}")
    print()
    
    # Get candidates
    candidates = analyze_candidates(args.min_confidence, args.limit)
    print(f"Found {len(candidates)} candidates with suggestions >= {args.min_confidence:.0%}")
    print()
    
    if not candidates:
        print("No candidates found!")
        return
    
    # Categorize
    safe, review, risky = categorize_candidates(candidates)
    
    print("=" * 60)
    print("CATEGORIZATION")
    print("=" * 60)
    print(f"✅ SAFE (>=95% + metadata match): {len(safe)}")
    print(f"⚠️  REVIEW (88-94% + metadata match): {len(review)}")
    print(f"❌ RISKY (lower confidence or mismatches): {len(risky)}")
    print()
    
    # Show safe candidates
    if safe:
        print("=" * 60)
        print("✅ SAFE TO AUTO-MERGE")
        print("=" * 60)
        for c in safe[:20]:  # Show first 20
            display_candidate(c, args.verbose)
        
        if len(safe) > 20:
            print(f"  ... and {len(safe) - 20} more")
        print()
    
    # Show review candidates
    if review and args.verbose:
        print("=" * 60)
        print("⚠️  NEEDS REVIEW (88-94%)")
        print("=" * 60)
        for c in review[:10]:
            display_candidate(c, args.verbose)
        print()
    
    # Execute if requested
    if args.execute:
        confirm = input(f"\n⚠️  About to merge {len(safe)} SAFE candidates. Type 'yes' to confirm: ")
        if confirm.lower() == 'yes':
            approved, failed = execute_auto_merge(safe, dry_run=False)
            print(f"\n✅ Approved: {approved}, ❌ Failed: {failed}")
        else:
            print("Cancelled.")
    elif safe:
        # Dry run on safe candidates
        approved, failed = execute_auto_merge(safe, dry_run=True)
        print(f"\n📊 DRY RUN SUMMARY: {approved} would be approved")
        print("\nTo execute, run with --execute flag")

if __name__ == '__main__':
    main()
