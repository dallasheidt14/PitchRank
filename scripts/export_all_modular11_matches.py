#!/usr/bin/env python3
"""
Export all Modular11 team matches to CSV for detailed review.
"""

import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
import logging

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
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

def export_all_matches(supabase: Client, provider_id: str, output_file: str):
    """Export all Modular11 matches to CSV."""
    
    # Get all approved aliases
    result = supabase.table('team_alias_map').select(
        'id, provider_team_id, team_id_master, match_method, match_confidence, review_status, division'
    ).eq('provider_id', provider_id).eq('review_status', 'approved').execute()
    
    if not result.data:
        print("No matches found.")
        return
    
    print(f"Found {len(result.data)} approved matches. Exporting to {output_file}...")
    
    # Prepare data for CSV
    matches = []
    for alias in result.data:
        provider_team_id = alias.get('provider_team_id')
        team_id_master = alias.get('team_id_master')
        match_method = alias.get('match_method', 'unknown')
        confidence = alias.get('match_confidence', 0)
        division = alias.get('division', '')
        
        # Get team details
        team_result = supabase.table('teams').select(
            'team_name, club_name, age_group, gender, state_code'
        ).eq('team_id_master', team_id_master).execute()
        
        if team_result.data:
            team = team_result.data[0]
            matches.append({
                'Provider Team ID': provider_team_id,
                'Master Team ID': team_id_master,
                'Team Name': team.get('team_name', ''),
                'Club Name': team.get('club_name', ''),
                'Age Group': team.get('age_group', ''),
                'Gender': team.get('gender', ''),
                'State Code': team.get('state_code', ''),
                'Match Method': match_method,
                'Confidence': f"{confidence:.1%}",
                'Division': division or 'N/A'
            })
        else:
            matches.append({
                'Provider Team ID': provider_team_id,
                'Master Team ID': team_id_master,
                'Team Name': 'Unknown',
                'Club Name': '',
                'Age Group': '',
                'Gender': '',
                'State Code': '',
                'Match Method': match_method,
                'Confidence': f"{confidence:.1%}",
                'Division': division or 'N/A'
            })
    
    # Sort by match_method, then by confidence
    matches.sort(key=lambda x: (x['Match Method'], float(x['Confidence'].rstrip('%'))), reverse=True)
    
    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        if matches:
            writer = csv.DictWriter(f, fieldnames=matches[0].keys())
            writer.writeheader()
            writer.writerows(matches)
    
    print(f"✅ Exported {len(matches)} matches to {output_file}")
    
    # Print summary
    by_method = {}
    for match in matches:
        method = match['Match Method']
        if method not in by_method:
            by_method[method] = 0
        by_method[method] += 1
    
    print("\nSummary by Match Method:")
    for method, count in sorted(by_method.items()):
        print(f"  {method:20} {count:4} matches")

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
        
        # Export to CSV
        output_file = project_root / 'scrapers' / 'modular11_scraper' / 'output' / 'all_modular11_matches.csv'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        export_all_matches(supabase, provider_id, str(output_file))
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()













