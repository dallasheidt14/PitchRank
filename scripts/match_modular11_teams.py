#!/usr/bin/env python3
"""
Modular11 Team Matching Script
==============================

This script:
1. Reads unique teams from the Modular11 scraped CSV
2. Queries existing teams from the database
3. Fuzzy matches Modular11 club names to database teams
4. Creates pending alias entries in team_alias_map
5. Outputs a report for manual review

Usage:
    # Preview matches (no database changes)
    python scripts/match_modular11_teams.py --preview
    
    # Create pending aliases in database
    python scripts/match_modular11_teams.py --create-pending
    
    # Specify custom CSV file
    python scripts/match_modular11_teams.py --csv scrapers/modular11_scraper/output/modular11_results_20251203_105706.csv --preview
"""

import argparse
import csv
import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client
from rapidfuzz import fuzz, process

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


@dataclass
class Modular11Team:
    """Team from Modular11 scrape"""
    provider_team_id: str
    club_name: str
    age_groups: set
    divisions: set  # HD, AD
    game_count: int


@dataclass
class DatabaseTeam:
    """Team from database"""
    team_id_master: str
    team_name: str
    club_name: str
    age_group: str
    gender: str


@dataclass
class MatchResult:
    """Result of matching a Modular11 team to database"""
    modular11_team: Modular11Team
    db_team: Optional[DatabaseTeam]
    confidence: int
    match_type: str  # 'exact', 'fuzzy_high', 'fuzzy_medium', 'fuzzy_low', 'no_match'
    age_group: str
    division: str


def extract_modular11_teams(csv_path: str) -> Dict[str, Modular11Team]:
    """Extract unique teams from Modular11 CSV"""
    teams = {}
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row.get('team_id', '').strip()
            club_name = row.get('club_name', '').strip()
            age_group = row.get('age_group', '').strip()
            team_name = row.get('team_name', '').strip()
            
            # Determine division from team_name (ends with HD or AD)
            division = ''
            if team_name.endswith(' HD'):
                division = 'HD'
            elif team_name.endswith(' AD'):
                division = 'AD'
            
            if not team_id or not club_name:
                continue
            
            if team_id not in teams:
                teams[team_id] = Modular11Team(
                    provider_team_id=team_id,
                    club_name=club_name,
                    age_groups=set(),
                    divisions=set(),
                    game_count=0
                )
            
            teams[team_id].age_groups.add(age_group)
            if division:
                teams[team_id].divisions.add(division)
            teams[team_id].game_count += 1
    
    return teams


def fetch_database_teams(supabase) -> List[DatabaseTeam]:
    """Fetch all teams from database"""
    print("Fetching teams from database...")
    
    # Fetch ALL teams (not just first 1000)
    all_teams = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('teams').select(
            'team_id_master, team_name, age_group, gender'
        ).range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        all_teams.extend(result.data)
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    teams = []
    for row in all_teams:
        team_name = row.get('team_name', '')
        club_name = extract_base_club_name(team_name)
        
        teams.append(DatabaseTeam(
            team_id_master=row['team_id_master'],
            team_name=team_name,
            club_name=club_name,
            age_group=row.get('age_group', ''),
            gender=row.get('gender', '')
        ))
    
    print(f"  Found {len(teams)} teams in database")
    
    # Show some sample extractions
    print("  Sample club name extractions:")
    for t in teams[:5]:
        print(f"    '{t.team_name}' -> '{t.club_name}'")
    
    return teams


def get_provider_id(supabase, provider_code: str) -> Optional[str]:
    """Get provider UUID from code"""
    result = supabase.table('providers').select('id').eq('code', provider_code).execute()
    if result.data:
        return result.data[0]['id']
    return None


def normalize_club_name(name: str) -> str:
    """Normalize club name for comparison"""
    # Uppercase, remove common suffixes
    name = name.upper().strip()
    
    # Remove common suffixes (order matters - longer first)
    suffixes = [
        ' SOCCER CLUB', ' FUTBOL CLUB', ' YOUTH SC', ' YOUTH SOCCER', 
        ' SOCCER', ' ACADEMY', ' SC', ' FC', ' SA', ' YSC'
    ]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    
    # Also try removing location qualifiers that might differ
    # e.g., "ALBION SC SAN DIEGO" -> "ALBION"
    return name


def extract_base_club_name(team_name: str) -> str:
    """Extract just the club name from full team name"""
    # Handle names like "IdeaSport 2009 Elite" -> "IdeaSport"
    # or "Tampa Bay United 2010 MLS NEXT" -> "Tampa Bay United"
    parts = team_name.split()
    club_parts = []
    
    for part in parts:
        # Stop at year (4 digits) or age indicator
        if part.isdigit() and len(part) == 4:
            break
        if part.upper().startswith('U') and part[1:].isdigit():
            break
        if part in ['MLS', 'NEXT', 'Elite', 'NAL', 'Pro', 'DPL', 'AD', 'HD']:
            break
        club_parts.append(part)
    
    return ' '.join(club_parts) if club_parts else team_name


def match_teams(
    modular11_teams: Dict[str, Modular11Team],
    db_teams: List[DatabaseTeam],
    age_group: str,
    division: str
) -> List[MatchResult]:
    """Match Modular11 teams to database teams for a specific age group"""
    results = []
    
    # Filter database teams by age group (case-insensitive)
    age_group_lower = age_group.lower()
    db_teams_filtered = [t for t in db_teams if t.age_group.lower() == age_group_lower]
    
    # Build lookup of normalized club names -> teams
    db_club_lookup = defaultdict(list)
    for t in db_teams_filtered:
        normalized = normalize_club_name(t.club_name)
        db_club_lookup[normalized].append(t)
    
    # Get list of normalized names for fuzzy matching
    db_club_names = list(db_club_lookup.keys())
    
    for team_id, m11_team in modular11_teams.items():
        # Skip if this team doesn't have this age group
        if age_group not in m11_team.age_groups:
            continue
        
        # Skip if division doesn't match (if division is specified)
        if division and division not in m11_team.divisions:
            continue
        
        normalized_m11 = normalize_club_name(m11_team.club_name)
        
        # Try exact match first
        if normalized_m11 in db_club_lookup:
            db_matches = db_club_lookup[normalized_m11]
            # If multiple matches (e.g., HD and AD teams), pick the best one
            for db_team in db_matches:
                results.append(MatchResult(
                    modular11_team=m11_team,
                    db_team=db_team,
                    confidence=100,
                    match_type='exact',
                    age_group=age_group,
                    division=division
                ))
            continue
        
        # Fuzzy match
        if db_club_names:
            matches = process.extract(
                normalized_m11, 
                db_club_names, 
                scorer=fuzz.token_sort_ratio,
                limit=3
            )
            
            if matches and matches[0][1] >= 80:
                best_match_name, score, _ = matches[0]
                db_matches = db_club_lookup[best_match_name]
                
                match_type = 'fuzzy_high' if score >= 90 else 'fuzzy_medium' if score >= 80 else 'fuzzy_low'
                
                for db_team in db_matches:
                    results.append(MatchResult(
                        modular11_team=m11_team,
                        db_team=db_team,
                        confidence=score,
                        match_type=match_type,
                        age_group=age_group,
                        division=division
                    ))
            else:
                # No good match found
                results.append(MatchResult(
                    modular11_team=m11_team,
                    db_team=None,
                    confidence=0,
                    match_type='no_match',
                    age_group=age_group,
                    division=division
                ))
        else:
            # No database teams for this age group
            results.append(MatchResult(
                modular11_team=m11_team,
                db_team=None,
                confidence=0,
                match_type='no_match',
                age_group=age_group,
                division=division
            ))
    
    return results


def print_report(all_results: List[MatchResult]):
    """Print a summary report of matches"""
    print("\n" + "="*80)
    print("MODULAR11 TEAM MATCHING REPORT")
    print("="*80)
    
    # Group by match type
    by_type = defaultdict(list)
    for r in all_results:
        by_type[r.match_type].append(r)
    
    # Summary
    print(f"\n📊 SUMMARY:")
    print(f"  ✅ Exact matches:       {len(by_type['exact'])}")
    print(f"  🟢 High confidence (≥90): {len(by_type['fuzzy_high'])}")
    print(f"  🟡 Medium confidence (80-89): {len(by_type['fuzzy_medium'])}")
    print(f"  🔴 No match found:      {len(by_type['no_match'])}")
    print(f"  ─────────────────────────")
    print(f"  Total:                  {len(all_results)}")
    
    # Show exact matches
    if by_type['exact']:
        print(f"\n✅ EXACT MATCHES ({len(by_type['exact'])}):")
        for r in sorted(by_type['exact'], key=lambda x: x.modular11_team.club_name)[:20]:
            print(f"  {r.modular11_team.club_name} ({r.age_group} {r.division})")
            print(f"    → {r.db_team.team_name}")
        if len(by_type['exact']) > 20:
            print(f"  ... and {len(by_type['exact']) - 20} more")
    
    # Show high confidence matches (for review)
    if by_type['fuzzy_high']:
        print(f"\n🟢 HIGH CONFIDENCE MATCHES - REVIEW RECOMMENDED ({len(by_type['fuzzy_high'])}):")
        for r in sorted(by_type['fuzzy_high'], key=lambda x: -x.confidence)[:20]:
            print(f"  {r.modular11_team.club_name} ({r.age_group} {r.division}) [{r.confidence}%]")
            print(f"    → {r.db_team.team_name}")
        if len(by_type['fuzzy_high']) > 20:
            print(f"  ... and {len(by_type['fuzzy_high']) - 20} more")
    
    # Show medium confidence matches (need review)
    if by_type['fuzzy_medium']:
        print(f"\n🟡 MEDIUM CONFIDENCE - NEEDS REVIEW ({len(by_type['fuzzy_medium'])}):")
        for r in sorted(by_type['fuzzy_medium'], key=lambda x: -x.confidence)[:20]:
            print(f"  {r.modular11_team.club_name} ({r.age_group} {r.division}) [{r.confidence}%]")
            print(f"    → {r.db_team.team_name}")
        if len(by_type['fuzzy_medium']) > 20:
            print(f"  ... and {len(by_type['fuzzy_medium']) - 20} more")
    
    # Show unmatched teams
    if by_type['no_match']:
        print(f"\n🔴 NO MATCH FOUND ({len(by_type['no_match'])}):")
        # Group by club name to avoid duplicates
        unmatched_clubs = defaultdict(set)
        for r in by_type['no_match']:
            unmatched_clubs[r.modular11_team.club_name].add(f"{r.age_group} {r.division}")
        
        for club, age_divs in sorted(unmatched_clubs.items())[:30]:
            print(f"  {club}: {', '.join(sorted(age_divs))}")
        if len(unmatched_clubs) > 30:
            print(f"  ... and {len(unmatched_clubs) - 30} more clubs")


def create_pending_aliases(
    supabase,
    provider_id: str,
    results: List[MatchResult],
    min_confidence: int = 80
):
    """Create pending alias entries in database"""
    # Filter to only matches with sufficient confidence
    good_matches = [r for r in results if r.db_team and r.confidence >= min_confidence]
    
    print(f"\nCreating {len(good_matches)} pending alias entries...")
    
    # Group by provider_team_id to avoid duplicates
    unique_mappings = {}
    for r in good_matches:
        key = (r.modular11_team.provider_team_id, r.db_team.team_id_master)
        if key not in unique_mappings or r.confidence > unique_mappings[key].confidence:
            unique_mappings[key] = r
    
    created = 0
    skipped = 0
    
    for (provider_team_id, team_id_master), r in unique_mappings.items():
        # Check if mapping already exists
        existing = supabase.table('team_alias_map').select('id').eq(
            'provider_id', provider_id
        ).eq(
            'provider_team_id', provider_team_id
        ).eq(
            'team_id_master', team_id_master
        ).execute()
        
        if existing.data:
            skipped += 1
            continue
        
        # Create pending alias
        try:
            supabase.table('team_alias_map').insert({
                'provider_id': provider_id,
                'provider_team_id': provider_team_id,
                'team_id_master': team_id_master,
                'match_method': 'fuzzy_auto' if r.match_type != 'exact' else 'direct_id',
                'match_confidence': r.confidence / 100.0,  # Store as decimal 0.0-1.0
                'review_status': 'pending',
            }).execute()
            created += 1
            print(f"  ✓ {r.modular11_team.club_name} ({r.age_group}) → {r.db_team.team_name} [{r.confidence}%]")
        except Exception as e:
            print(f"  Error creating alias: {e}")
    
    print(f"  Created: {created}")
    print(f"  Skipped (already exists): {skipped}")
    
    return created, skipped


def main():
    parser = argparse.ArgumentParser(description='Match Modular11 teams to database teams')
    parser.add_argument('--csv', type=str, help='Path to Modular11 CSV file')
    parser.add_argument('--preview', action='store_true', help='Preview matches without creating aliases')
    parser.add_argument('--create-pending', action='store_true', help='Create pending alias entries in database')
    parser.add_argument('--min-confidence', type=int, default=80, help='Minimum confidence for auto-matching (default: 80)')
    args = parser.parse_args()
    
    # Find latest CSV if not specified
    if not args.csv:
        output_dir = Path('scrapers/modular11_scraper/output')
        csv_files = sorted(output_dir.glob('modular11_results_*.csv'), reverse=True)
        if csv_files:
            args.csv = str(csv_files[0])
            print(f"Using latest CSV: {args.csv}")
        else:
            print("ERROR: No CSV file found. Specify with --csv")
            sys.exit(1)
    
    if not Path(args.csv).exists():
        print(f"ERROR: CSV file not found: {args.csv}")
        sys.exit(1)
    
    # Connect to database
    supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("ERROR: Missing SUPABASE_URL or SUPABASE_KEY")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Get provider ID
    provider_id = get_provider_id(supabase, 'modular11')
    if not provider_id:
        print("ERROR: Provider 'modular11' not found in database")
        sys.exit(1)
    
    print(f"Provider ID: {provider_id}")
    
    # Extract teams from CSV
    print(f"\nExtracting teams from: {args.csv}")
    modular11_teams = extract_modular11_teams(args.csv)
    print(f"  Found {len(modular11_teams)} unique Modular11 teams")
    
    # Show sample teams
    print("\n  Sample teams:")
    for team_id, team in list(modular11_teams.items())[:5]:
        print(f"    ID {team_id}: {team.club_name} | Ages: {', '.join(sorted(team.age_groups))} | Divs: {', '.join(sorted(team.divisions))} | Games: {team.game_count}")
    
    # Fetch database teams
    db_teams = fetch_database_teams(supabase)
    
    # Match for each age group and division
    all_results = []
    age_groups = ['U13', 'U14', 'U15', 'U16', 'U17']
    divisions = ['HD', 'AD']
    
    print("\nMatching teams...")
    for age_group in age_groups:
        for division in divisions:
            results = match_teams(modular11_teams, db_teams, age_group, division)
            all_results.extend(results)
            matched = len([r for r in results if r.db_team])
            print(f"  {age_group} {division}: {matched}/{len(results)} matched")
    
    # Print report
    print_report(all_results)
    
    # Create pending aliases if requested
    if args.create_pending:
        create_pending_aliases(supabase, provider_id, all_results, args.min_confidence)
        print("\n✅ Pending aliases created. Review them in the database, then approve with:")
        print("   UPDATE team_alias_map SET review_status = 'approved' WHERE provider_id = '...' AND review_status = 'pending';")
    elif not args.preview:
        print("\n💡 Run with --preview to see matches, or --create-pending to create alias entries")


if __name__ == '__main__':
    main()

