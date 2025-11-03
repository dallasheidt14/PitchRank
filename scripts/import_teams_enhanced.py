#!/usr/bin/env python3
"""
Enhanced team import script with validation and bulk operations
"""
import argparse
import csv
import logging
import sys
from pathlib import Path
from datetime import datetime
import json

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console

from src.utils.enhanced_validators import EnhancedDataValidator

logger = logging.getLogger(__name__)
console = Console()
load_dotenv()


class TeamImporter:
    def __init__(self, supabase, provider_code: str, dry_run: bool = False):
        self.supabase = supabase
        self.provider_code = provider_code
        self.dry_run = dry_run
        self.validator = EnhancedDataValidator()
        self.batch_size = 500
        
        # Get provider UUID
        try:
            result = self.supabase.table('providers').select('id').eq(
                'code', provider_code
            ).single().execute()
            self.provider_id = result.data['id']
        except Exception as e:
            logger.error(f"Provider not found: {provider_code}")
            raise ValueError(f"Provider not found: {provider_code}") from e
        
    def import_teams(self, csv_file: str):
        """Import teams from CSV with direct ID mapping"""
        
        teams = []
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Map CSV columns to our team structure
                team = {
                    'provider_team_id': row.get('team_id') or row.get('id') or row.get('Team_ID', ''),
                    'team_name': row.get('team_name') or row.get('name') or row.get('Team_Name', ''),
                    'age_group': row.get('age_group') or row.get('Age_Group', '').lower(),
                    'gender': row.get('gender') or row.get('Gender', ''),
                    'state_code': row.get('state_code') or row.get('State_Code', ''),
                    'state': row.get('state') or row.get('State', ''),
                    'club_name': row.get('club_name') or row.get('Club_Name', ''),
                    'provider_id': self.provider_code
                }
                
                # Only add if we have at least a name
                if team['team_name']:
                    teams.append(team)
        
        logger.info(f"Loaded {len(teams)} teams from CSV with provider IDs")
        console.print(f"[green]Loaded {len(teams)} teams from CSV[/green]")
        
        # Validate teams
        valid_teams = []
        invalid_teams = []
        
        for team in teams:
            # CRITICAL: Ensure we have provider_team_id
            if not team.get('provider_team_id'):
                team['validation_errors'] = ['Missing team_id in CSV']
                invalid_teams.append(team)
                continue
            
            is_valid, errors = self.validator.validate_team(team)
            if is_valid:
                valid_teams.append(team)
            else:
                team['validation_errors'] = errors
                invalid_teams.append(team)
        
        logger.info(f"Validation: {len(valid_teams)} valid, {len(invalid_teams)} invalid")
        if valid_teams:
            logger.info(f"Sample team IDs: {[t['provider_team_id'] for t in valid_teams[:5]]}")
        
        console.print(f"Validation: [green]{len(valid_teams)} valid[/green], [red]{len(invalid_teams)} invalid[/red]")
        
        if invalid_teams:
            console.print("\n[yellow]Sample invalid teams:[/yellow]")
            for team in invalid_teams[:5]:
                errors = team.get('validation_errors', [])
                console.print(f"  [red]{team.get('team_name', 'Unknown')}:[/red] {'; '.join(errors)}")
        
        if self.dry_run:
            logger.info("Dry run - no changes made")
            console.print("\n[yellow]Dry run - no changes made[/yellow]")
            return
        
        # Insert teams and create DIRECT ID mappings
        try:
            logger.info("Starting team import with direct ID mappings")
            inserted_count = 0
            alias_count = 0
            
            for team in valid_teams:
                # Check if team already exists by provider_team_id
                existing_team = self.supabase.table('teams').select('*').eq(
                    'provider_id', self.provider_id
                ).eq(
                    'provider_team_id', team['provider_team_id']
                ).maybe_single().execute()
                
                if existing_team.data:
                    master_team_id = existing_team.data['team_id_master']
                    logger.info(f"Found existing team: {team['team_name']} (ID: {master_team_id})")
                else:
                    # Insert new team
                    import uuid
                    team_id_master = str(uuid.uuid4())
                    
                    team_record = {
                        'team_id_master': team_id_master,
                        'provider_team_id': team['provider_team_id'],
                        'provider_id': self.provider_id,
                        'team_name': team['team_name'],
                        'club_name': team.get('club_name'),
                        'state': team.get('state'),
                        'state_code': team.get('state_code'),
                        'age_group': team.get('age_group', '').lower(),
                        'gender': team.get('gender', ''),
                        'created_at': datetime.now().isoformat()
                    }
                    
                    result = self.supabase.table('teams').insert(team_record).execute()
                    if result.data:
                        master_team_id = result.data[0]['team_id_master']
                        inserted_count += 1
                        logger.info(f"Created new team: {team['team_name']} (ID: {master_team_id})")
                    else:
                        logger.warning(f"Failed to insert team: {team['team_name']}")
                        continue
                
                # CRITICAL: Create direct ID mapping
                existing_mapping = self.supabase.table('team_alias_map').select('*').eq(
                    'provider_id', self.provider_id
                ).eq(
                    'provider_team_id', team['provider_team_id']
                ).maybe_single().execute()
                
                if not existing_mapping.data:
                    alias_record = {
                        'provider_id': self.provider_id,
                        'provider_team_id': team['provider_team_id'],
                        'team_id_master': master_team_id,
                        'match_confidence': 1.0,  # Perfect confidence for direct ID match
                        'match_method': 'direct_id',  # New match type!
                        'review_status': 'approved',
                        'created_at': datetime.now().isoformat()
                    }
                    
                    result = self.supabase.table('team_alias_map').insert(alias_record).execute()
                    if result.data:
                        alias_count += 1
                        logger.info(f"Created direct ID mapping: {self.provider_code}:{team['provider_team_id']} -> {master_team_id}")
                else:
                    logger.info(f"Mapping already exists for {self.provider_code}:{team['provider_team_id']}")
            
            logger.info(f"Successfully imported {len(valid_teams)} teams with direct ID mappings")
            console.print(f"\n[green]Import completed:[/green]")
            console.print(f"  Teams inserted/updated: {inserted_count}")
            console.print(f"  Direct ID mappings created: {alias_count}")
            
        except Exception as e:
            logger.error(f"Import failed: {e}")
            console.print(f"[red]Import failed: {e}[/red]")
            raise
    
    @staticmethod
    def _chunks(lst, size):
        """Yield successive chunks from list"""
        for i in range(0, len(lst), size):
            yield lst[i:i + size]


def main():
    parser = argparse.ArgumentParser(description='Import teams with validation')
    parser.add_argument('file', help='CSV file containing teams')
    parser.add_argument('provider', help='Provider ID (gotsport, tgs, usclub)')
    parser.add_argument('--dry-run', action='store_true', help='Run without committing')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    importer = TeamImporter(supabase, args.provider, args.dry_run)
    
    try:
        importer.import_teams(args.file)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == '__main__':
    main()

