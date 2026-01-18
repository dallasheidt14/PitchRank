#!/usr/bin/env python3
"""
Import SincSports teams into database

Scrapes team info from SincSports, checks if teams exist, and creates them if not.
"""
import sys
from pathlib import Path
from datetime import datetime
import asyncio
import json

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from src.scrapers.sincsports import SincSportsScraper
from src.utils.enhanced_validators import EnhancedDataValidator
from src.models.game_matcher import GameHistoryMatcher

load_dotenv()

console = Console()

# Test team IDs - can be expanded
TEST_TEAM_IDS = [
    "NCM14762",  # NC Fusion U12 PRE ECNL BOYS RED
    # Add more team IDs here
]

# Opponent IDs from test games (extracted from games)
OPPONENT_TEAM_IDS = [
    "SCM14140",  # FCC 2014 Boys Gold - BA
    "NCM143BE",  # 14 (12U) CSA UM Elite
    "NCM1473B",  # 14 (12U) CSA CLT Pre-EC..
    "NCM143B5",  # 14 (12U) CSA North Elite
]


async def ensure_provider_exists(supabase):
    """Ensure SincSports provider exists in database"""
    try:
        result = supabase.table('providers').select('*').eq('code', 'sincsports').execute()
        
        if result.data:
            provider = result.data[0]
            return provider['id']
        else:
            console.print(f"  [yellow]⚠[/yellow] Provider not found, creating...")
            new_provider = {
                'code': 'sincsports',
                'name': 'SincSports',
                'base_url': 'https://soccer.sincsports.com'
            }
            result = supabase.table('providers').insert(new_provider).execute()
            if result.data:
                provider_id = result.data[0]['id']
                console.print(f"  [green]✓[/green] Created provider (ID: {provider_id})")
                return provider_id
            else:
                console.print(f"  [red]✗[/red] Failed to create provider")
                return None
    except Exception as e:
        console.print(f"  [red]✗[/red] Error checking/creating provider: {e}")
        return None


def normalize_age_group(age_str: str) -> str:
    """Normalize age group string to standard format (e.g., 'U12', '12U' -> 'u12')"""
    if not age_str:
        return ''
    
    age_str = age_str.upper().strip()
    
    # Remove common prefixes/suffixes
    age_str = age_str.replace('U', '').replace('AGE', '').strip()
    
    # Extract number
    import re
    match = re.search(r'(\d+)', age_str)
    if match:
        age_num = match.group(1)
        return f"u{age_num}"
    
    return age_str.lower()


def normalize_gender(gender_str: str) -> str:
    """Normalize gender string to standard format (Male/Female)"""
    if not gender_str:
        return ''
    
    gender_str = gender_str.upper().strip()
    
    if gender_str in ['M', 'MALE', 'BOYS', 'B']:
        return 'Male'
    elif gender_str in ['F', 'FEMALE', 'GIRLS', 'G']:
        return 'Female'
    
    # Try to match valid formats
    if gender_str in ['MALE', 'FEMALE', 'BOYS', 'GIRLS', 'COED']:
        return gender_str.capitalize()
    
    return gender_str


async def import_teams(team_ids: list, dry_run: bool = False):
    """Import SincSports teams"""
    console.print(Panel.fit("[bold cyan]Importing SincSports Teams[/bold cyan]", style="cyan"))
    
    # Initialize Supabase
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Ensure provider exists
    provider_id = await ensure_provider_exists(supabase)
    if not provider_id:
        console.print("[red]Cannot proceed without provider. Exiting.[/red]")
        return
    
    # Initialize scraper and matcher
    scraper = SincSportsScraper(supabase, 'sincsports')
    validator = EnhancedDataValidator()
    matcher = GameHistoryMatcher(supabase, provider_id=provider_id)
    
    console.print(f"\n[bold]Scraping {len(team_ids)} teams...[/bold]")
    
    teams_to_create = []
    teams_existing = []
    teams_fuzzy_matched = []  # Teams matched via fuzzy matching
    teams_failed = []
    
    for team_id in team_ids:
        try:
            # Scrape team info
            games_url = f"{scraper.BASE_URL}/team/games.aspx?teamid={team_id}"
            response = scraper.session.get(games_url, timeout=scraper.timeout)
            response.raise_for_status()
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            team_info = scraper._extract_team_info(soup, team_id)
            
            if not team_info.get('team_name'):
                console.print(f"  [yellow]⚠[/yellow] Team {team_id}: No team name found, skipping")
                teams_failed.append({'team_id': team_id, 'reason': 'No team name'})
                continue
            
            # Normalize data
            age_group = normalize_age_group(team_info.get('age_group', ''))
            gender = normalize_gender(team_info.get('gender', ''))
            
            team_data = {
                'provider_team_id': team_id,
                'team_name': team_info.get('team_name', '').strip(),
                'club_name': team_info.get('club_name', '').strip() if team_info.get('club_name') else None,
                'age_group': age_group,
                'gender': gender,
                'provider_id': provider_id
            }
            
            # Validate
            is_valid, errors = validator.validate_team(team_data)
            if not is_valid:
                console.print(f"  [yellow]⚠[/yellow] Team {team_id} ({team_data['team_name']}): Validation failed: {errors}")
                teams_failed.append({'team_id': team_id, 'team_name': team_data['team_name'], 'errors': errors})
                continue
            
            # Check if team exists using matching system (includes fuzzy matching)
            try:
                # First, check if team exists from this provider (exact match)
                result = supabase.table('teams').select('team_id_master').eq(
                    'provider_id', provider_id
                ).eq('provider_team_id', team_id).execute()
                
                if result.data:
                    master_id = result.data[0]['team_id_master']
                    teams_existing.append({
                        'team_id': team_id,
                        'team_name': team_data['team_name'],
                        'master_id': master_id,
                        'team_data': team_data
                    })
                    console.print(f"  [dim]✓[/dim] Team {team_id}: {team_data['team_name']} (already exists from SincSports)")
                    # Still need to check/create alias mapping
                    continue
                
                # Team doesn't exist from SincSports - try fuzzy matching against all teams
                if team_data.get('team_name') and team_data.get('age_group') and team_data.get('gender'):
                    match_result = matcher._match_team(
                        provider_id=provider_id,
                        provider_team_id=team_id,
                        team_name=team_data['team_name'],
                        age_group=team_data['age_group'],
                        gender=team_data['gender'],
                        club_name=team_data.get('club_name')
                    )
                    
                    if match_result.get('matched'):
                        # Found a match via fuzzy matching or alias!
                        master_id = match_result['team_id']
                        match_method = match_result.get('method', 'unknown')
                        confidence = match_result.get('confidence', 0.0)
                        
                        teams_fuzzy_matched.append({
                            'team_id': team_id,
                            'team_name': team_data['team_name'],
                            'master_id': master_id,
                            'match_method': match_method,
                            'confidence': confidence,
                            'team_data': team_data
                        })
                        
                        method_label = {
                            'direct_id': 'direct ID',
                            'provider_id': 'provider ID',
                            'alias': 'alias map',
                            'fuzzy_auto': 'fuzzy match'
                        }.get(match_method, match_method)
                        
                        console.print(f"  [green]✓[/green] Team {team_id}: {team_data['team_name']} (matched via {method_label}, confidence: {confidence:.1%})")
                        
                        # Ensure alias mapping exists (matcher may have created it, but double-check)
                        try:
                            alias_check = supabase.table('team_alias_map').select('id').eq(
                                'provider_id', provider_id
                            ).eq('provider_team_id', team_id).execute()
                            
                            if not alias_check.data:
                                # Create alias mapping
                                alias_record = {
                                    'provider_id': provider_id,
                                    'provider_team_id': team_id,
                                    'team_id_master': master_id,
                                    'match_method': match_method if match_method != 'fuzzy_auto' else 'fuzzy_auto',
                                    'match_confidence': confidence,
                                    'review_status': 'approved',
                                    'created_at': datetime.now().isoformat()
                                }
                                supabase.table('team_alias_map').insert(alias_record).execute()
                        except Exception as e:
                            error_str = str(e).lower()
                            if 'unique' not in error_str and 'duplicate' not in error_str:
                                console.print(f"    [yellow]⚠[/yellow] Could not create alias mapping: {e}")
                        
                        continue
                
                # No match found - need to create new team
                teams_to_create.append(team_data)
                console.print(f"  [cyan]→[/cyan] Team {team_id}: {team_data['team_name']} (will create new team)")
                
            except Exception as e:
                console.print(f"  [red]✗[/red] Error checking team {team_id}: {e}")
                teams_failed.append({'team_id': team_id, 'reason': str(e)})
                continue
                
        except Exception as e:
            console.print(f"  [red]✗[/red] Error scraping team {team_id}: {e}")
            teams_failed.append({'team_id': team_id, 'reason': str(e)})
            continue
    
    # Summary
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Existing (SincSports): {len(teams_existing)}")
    console.print(f"  Fuzzy Matched (other providers): {len(teams_fuzzy_matched)}")
    console.print(f"  To Create: {len(teams_to_create)}")
    console.print(f"  Failed: {len(teams_failed)}")
    
    if teams_failed:
        console.print(f"\n[yellow]Failed Teams:[/yellow]")
        for failed in teams_failed:
            console.print(f"  - {failed.get('team_id')}: {failed.get('reason', 'Unknown error')}")
    
    if dry_run:
        console.print(f"\n[yellow]DRY RUN: Would create {len(teams_to_create)} teams[/yellow]")
        if teams_fuzzy_matched:
            console.print(f"\n[green]Teams matched via fuzzy matching (would link to existing teams):[/green]")
            table = Table(box=box.SIMPLE)
            table.add_column("Team ID")
            table.add_column("Team Name")
            table.add_column("Match Method")
            table.add_column("Confidence")
            
            for team in teams_fuzzy_matched:
                method_label = {
                    'direct_id': 'Direct ID',
                    'provider_id': 'Provider ID',
                    'alias': 'Alias Map',
                    'fuzzy_auto': 'Fuzzy Match'
                }.get(team['match_method'], team['match_method'])
                table.add_row(
                    team['team_id'],
                    team['team_name'][:30],
                    method_label,
                    f"{team['confidence']:.1%}"
                )
            console.print(table)
        if teams_to_create:
            console.print(f"\nTeams to create:")
            table = Table(box=box.SIMPLE)
            table.add_column("Team ID")
            table.add_column("Team Name")
            table.add_column("Club")
            table.add_column("Age")
            table.add_column("Gender")
            
            for team in teams_to_create:
                table.add_row(
                    team['provider_team_id'],
                    team['team_name'][:30],
                    (team.get('club_name') or 'N/A')[:25],
                    team.get('age_group', 'N/A'),
                    team.get('gender', 'N/A')
                )
            console.print(table)
        if teams_existing:
            console.print(f"\n[yellow]Would ensure alias mappings for {len(teams_existing)} existing SincSports teams[/yellow]")
        return
    
    if not teams_to_create and not teams_existing:
        console.print(f"\n[green]✅ No teams to process![/green]")
        return
    
    # Create teams and alias mappings
    console.print(f"\n[bold]Processing teams and ensuring alias mappings...[/bold]")
    
    import uuid
    created_count = 0
    alias_count = 0
    
    # First, ensure alias mappings for fuzzy-matched teams (already linked to existing teams)
    for matched in teams_fuzzy_matched:
        try:
            alias_check = supabase.table('team_alias_map').select('id').eq(
                'provider_id', provider_id
            ).eq('provider_team_id', matched['team_id']).execute()
            
            if not alias_check.data:
                alias_record = {
                    'provider_id': provider_id,
                    'provider_team_id': matched['team_id'],
                    'team_id_master': matched['master_id'],
                    'match_method': matched['match_method'],
                    'match_confidence': matched['confidence'],
                    'review_status': 'approved',
                    'created_at': datetime.now().isoformat()
                }
                supabase.table('team_alias_map').insert(alias_record).execute()
                alias_count += 1
                console.print(f"  [green]✓[/green] Created alias for fuzzy-matched team: {matched['team_name']}")
        except Exception as e:
            error_str = str(e).lower()
            if 'unique' not in error_str and 'duplicate' not in error_str:
                console.print(f"  [yellow]⚠[/yellow] Error creating alias for {matched['team_name']}: {e}")
    
    # Second, ensure alias mappings for existing SincSports teams
    for existing in teams_existing:
        try:
            # Check if alias mapping exists
            alias_check = supabase.table('team_alias_map').select('id').eq(
                'provider_id', provider_id
            ).eq('provider_team_id', existing['team_id']).execute()
            
            if not alias_check.data:
                # Create alias mapping for existing team
                alias_record = {
                    'provider_id': provider_id,
                    'provider_team_id': existing['team_id'],
                    'team_id_master': existing['master_id'],
                    'match_method': 'direct_id',
                    'match_confidence': 1.0,
                    'review_status': 'approved',
                    'created_at': datetime.now().isoformat()
                }
                supabase.table('team_alias_map').insert(alias_record).execute()
                alias_count += 1
                console.print(f"  [cyan]✓[/cyan] Created alias mapping for existing team: {existing['team_name']}")
        except Exception as e:
            error_str = str(e).lower()
            if 'unique' in error_str or 'duplicate' in error_str:
                pass  # Already exists
            else:
                console.print(f"  [yellow]⚠[/yellow] Error creating alias for {existing['team_name']}: {e}")
    
    for team in teams_to_create:
        try:
            # Generate master team ID
            team_id_master = str(uuid.uuid4())
            
            # Create team record
            team_record = {
                'team_id_master': team_id_master,
                'provider_team_id': team['provider_team_id'],
                'provider_id': provider_id,
                'team_name': team['team_name'],
                'club_name': team.get('club_name'),
                'age_group': team.get('age_group', '').lower(),
                'gender': team.get('gender', ''),
                'created_at': datetime.now().isoformat()
            }
            
            result = supabase.table('teams').insert(team_record).execute()
            if result.data:
                created_count += 1
                console.print(f"  [green]✓[/green] Created: {team['team_name']} ({team_id_master[:8]}...)")
                
                # Create direct ID mapping
                alias_record = {
                    'provider_id': provider_id,
                    'provider_team_id': team['provider_team_id'],
                    'team_id_master': team_id_master,
                    'match_method': 'direct_id',
                    'match_confidence': 1.0,
                    'review_status': 'approved',
                    'created_at': datetime.now().isoformat()
                }
                
                try:
                    supabase.table('team_alias_map').insert(alias_record).execute()
                    alias_count += 1
                except Exception as e:
                    error_str = str(e).lower()
                    if 'unique' in error_str or 'duplicate' in error_str:
                        console.print(f"    [dim]Mapping already exists[/dim]")
                    else:
                        console.print(f"    [yellow]⚠[/yellow] Failed to create mapping: {e}")
            else:
                console.print(f"  [red]✗[/red] Failed to create: {team['team_name']}")
                
        except Exception as e:
            error_str = str(e).lower()
            if 'unique' in error_str or 'duplicate' in error_str:
                console.print(f"  [yellow]⚠[/yellow] Team {team['team_name']} already exists (race condition?)")
            else:
                console.print(f"  [red]✗[/red] Error creating team {team['team_name']}: {e}")
    
    console.print(f"\n[bold green]✅ Import complete![/bold green]")
    console.print(f"  Teams created: {created_count}")
    console.print(f"  Teams fuzzy-matched (linked to existing): {len(teams_fuzzy_matched)}")
    console.print(f"  Teams already existed (SincSports): {len(teams_existing)}")
    console.print(f"  Alias mappings created/updated: {alias_count}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Import SincSports teams')
    parser.add_argument('--team-ids', nargs='+', help='SincSports team IDs to import', default=TEST_TEAM_IDS)
    parser.add_argument('--include-opponents', action='store_true', help='Also import opponent teams from test games')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (don\'t create teams)')
    
    args = parser.parse_args()
    
    team_ids = list(args.team_ids)
    if args.include_opponents:
        team_ids.extend(OPPONENT_TEAM_IDS)
        # Remove duplicates
        team_ids = list(dict.fromkeys(team_ids))
    
    asyncio.run(import_teams(team_ids, dry_run=args.dry_run))

