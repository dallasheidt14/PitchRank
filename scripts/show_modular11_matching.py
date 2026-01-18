#!/usr/bin/env python3
"""
Show detailed Modular11 team matching process and results.

This script displays:
1. Teams that were matched (with confidence scores)
2. Teams in the review queue (with suggestions)
3. Fuzzy matching details
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
import logging

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables - prioritize .env.local if it exists
env_local = project_root / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
    logger.info("Loaded .env.local")
else:
    load_dotenv(project_root / '.env')
    logger.info("Loaded .env")

def get_supabase_client() -> Client:
    """Initialize Supabase client."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment")
    
    return create_client(supabase_url, supabase_key)

def show_matched_teams(supabase: Client, provider_id: str):
    """Show teams that were successfully matched."""
    print("\n" + "="*80)
    print("✅ SUCCESSFULLY MATCHED TEAMS")
    print("="*80)
    
    # Get all approved aliases for Modular11
    result = supabase.table('team_alias_map').select(
        'id, provider_team_id, team_id_master, match_method, match_confidence, review_status, division'
    ).eq('provider_id', provider_id).eq('review_status', 'approved').execute()
    
    if not result.data:
        print("No approved matches found.")
        return
    
    print(f"\nFound {len(result.data)} approved matches:\n")
    
    # Group by match_method
    by_method = {}
    for alias in result.data:
        method = alias.get('match_method', 'unknown')
        if method not in by_method:
            by_method[method] = []
        by_method[method].append(alias)
    
    for method, aliases in sorted(by_method.items()):
        print(f"\n📌 {method.upper()} Matches ({len(aliases)}):")
        print("-" * 80)
        
        for alias in aliases[:20]:  # Show first 20
            provider_team_id = alias.get('provider_team_id')
            team_id_master = alias.get('team_id_master')
            confidence = alias.get('match_confidence', 0)
            division = alias.get('division', 'N/A')
            
            # Get team name
            team_result = supabase.table('teams').select(
                'team_name, club_name, age_group, gender'
            ).eq('team_id_master', team_id_master).execute()
            
            team_name = team_result.data[0].get('team_name', 'Unknown') if team_result.data else 'Unknown'
            club_name = team_result.data[0].get('club_name', 'Unknown') if team_result.data else 'Unknown'
            age_group = team_result.data[0].get('age_group', 'Unknown') if team_result.data else 'Unknown'
            
            print(f"  Provider ID: {provider_team_id:>6} → {team_name:40} ({age_group})")
            print(f"    Confidence: {confidence:.1%} | Division: {division} | Method: {method}")
        
        if len(aliases) > 20:
            print(f"  ... and {len(aliases) - 20} more")

def show_review_queue(supabase: Client, provider_id: str):
    """Show teams in the review queue with suggestions."""
    print("\n" + "="*80)
    print("⏳ TEAMS IN REVIEW QUEUE (Pending Manual Review)")
    print("="*80)
    
    # Get review queue entries
    result = supabase.table('team_match_review_queue').select(
        'id, provider_team_id, provider_team_name, confidence_score, match_details, status'
    ).eq('provider_id', provider_id).eq('status', 'pending').order('confidence_score', desc=True).execute()
    
    if not result.data:
        print("No teams in review queue.")
        return
    
    print(f"\nFound {len(result.data)} teams pending review:\n")
    
    for entry in result.data:
        provider_team_id = entry.get('provider_team_id')
        provider_team_name = entry.get('provider_team_name', 'Unknown')
        confidence = entry.get('confidence_score', 0)
        match_details = entry.get('match_details', {})
        
        # Extract age_group and gender from match_details JSONB
        age_group = match_details.get('age_group', 'Unknown')
        gender = match_details.get('gender', 'Unknown')
        
        print(f"\n🔍 {provider_team_name} (ID: {provider_team_id})")
        print(f"   Age: {age_group} | Gender: {gender} | Confidence: {confidence:.1%}")
        
        # Show suggestions
        candidates = match_details.get('candidates', [])
        if candidates:
            print(f"   Top {min(5, len(candidates))} suggestions:")
            for i, candidate in enumerate(candidates[:5], 1):
                team_id = candidate.get('team_id_master', 'Unknown')
                score = candidate.get('score', 0)
                
                # Get team name
                team_result = supabase.table('teams').select(
                    'team_name, club_name, age_group'
                ).eq('team_id_master', team_id).execute()
                
                if team_result.data:
                    team_name = team_result.data[0].get('team_name', 'Unknown')
                    club_name = team_result.data[0].get('club_name', 'Unknown')
                    print(f"     {i}. {team_name:40} ({club_name}) - {score:.1%}")
        else:
            print("   No suggestions available")

def show_fuzzy_matching_details(supabase: Client, provider_id: str):
    """Show fuzzy matching statistics."""
    print("\n" + "="*80)
    print("📊 FUZZY MATCHING STATISTICS")
    print("="*80)
    
    # Get all aliases
    result = supabase.table('team_alias_map').select(
        'match_method, match_confidence, review_status'
    ).eq('provider_id', provider_id).execute()
    
    if not result.data:
        print("No aliases found.")
        return
    
    # Count by match_method
    by_method = {}
    confidence_scores = []
    
    for alias in result.data:
        method = alias.get('match_method', 'unknown')
        confidence = alias.get('match_confidence', 0)
        
        if method not in by_method:
            by_method[method] = {'total': 0, 'approved': 0, 'pending': 0}
        
        by_method[method]['total'] += 1
        if alias.get('review_status') == 'approved':
            by_method[method]['approved'] += 1
        elif alias.get('review_status') == 'pending':
            by_method[method]['pending'] += 1
        
        if confidence:
            confidence_scores.append(confidence)
    
    print("\nMatch Methods:")
    for method, counts in sorted(by_method.items()):
        print(f"  {method:20} Total: {counts['total']:4} | Approved: {counts['approved']:4} | Pending: {counts['pending']:4}")
    
    if confidence_scores:
        avg_confidence = sum(confidence_scores) / len(confidence_scores)
        min_confidence = min(confidence_scores)
        max_confidence = max(confidence_scores)
        print(f"\nConfidence Scores:")
        print(f"  Average: {avg_confidence:.1%}")
        print(f"  Range:   {min_confidence:.1%} - {max_confidence:.1%}")

def show_recent_games(supabase: Client, provider_id: str, limit: int = 10):
    """Show recently imported games and their team matches."""
    print("\n" + "="*80)
    print(f"🎮 RECENTLY IMPORTED GAMES (Last {limit})")
    print("="*80)
    
    # Get recent games
    result = supabase.table('games').select(
        'game_uid, home_team_master_id, away_team_master_id, game_date, home_score, away_score'
    ).eq('provider_id', provider_id).order('imported_at', desc=True).limit(limit).execute()
    
    if not result.data:
        print("No games found.")
        return
    
    print(f"\nFound {len(result.data)} recent games:\n")
    
    for game in result.data:
        game_uid = game.get('game_uid', 'Unknown')
        game_date = game.get('game_date', 'Unknown')
        goals_home = game.get('home_score', '?')
        goals_away = game.get('away_score', '?')
        home_team_id = game.get('home_team_master_id')
        away_team_id = game.get('away_team_master_id')
        
        print(f"Game: {game_uid}")
        print(f"  Date: {game_date} | Score: {goals_home} - {goals_away}")
        
        # Get team names
        if home_team_id:
            home_result = supabase.table('teams').select('team_name').eq('team_id_master', home_team_id).execute()
            home_name = home_result.data[0].get('team_name', 'Unknown') if home_result.data else 'Unmatched'
        else:
            home_name = 'Unmatched'
        
        if away_team_id:
            away_result = supabase.table('teams').select('team_name').eq('team_id_master', away_team_id).execute()
            away_name = away_result.data[0].get('team_name', 'Unknown') if away_result.data else 'Unmatched'
        else:
            away_name = 'Unmatched'
        
        print(f"  {home_name} vs {away_name}")
        print()

def main():
    """Main function."""
    try:
        supabase = get_supabase_client()
        
        # Get Modular11 provider ID
        provider_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
        if not provider_result.data:
            print("❌ Modular11 provider not found in database")
            return
        
        provider_id = provider_result.data[0]['id']
        print(f"Provider ID: {provider_id}")
        
        # Show all information
        show_matched_teams(supabase, provider_id)
        show_review_queue(supabase, provider_id)
        show_fuzzy_matching_details(supabase, provider_id)
        show_recent_games(supabase, provider_id, limit=10)
        
        print("\n" + "="*80)
        print("✅ Analysis complete!")
        print("="*80)
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()

