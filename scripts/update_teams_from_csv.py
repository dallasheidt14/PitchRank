#!/usr/bin/env python3
"""
Update teams in database from CSV file.

This script reads a CSV file (typically exported from view_teams.py) and updates
team information in the database. It will update:
- club_name
- state_code
- state
- Any other fields present in the CSV

Usage:
    python scripts/update_teams_from_csv.py <csv_file> [--dry-run]
    
Example:
    python scripts/update_teams_from_csv.py u13_male_az.csv
    python scripts/update_teams_from_csv.py u13_male_az.csv --dry-run  # Preview only
"""
import os
import csv
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment[/red]")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)


def validate_state_code(state_code: str) -> bool:
    """Validate state code is 2 characters."""
    if not state_code:
        return True  # Empty is valid (will be set to None)
    return len(state_code.strip()) == 2


def get_current_team_data(team_id: str) -> dict:
    """Fetch current team data from database."""
    try:
        result = supabase.table('teams').select(
            'team_id_master, team_name, club_name, state_code, state, age_group, gender, birth_year'
        ).eq('team_id_master', team_id).execute()
        
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        console.print(f"[yellow]Warning: Error fetching team {team_id}: {e}[/yellow]")
        return None


def update_teams_from_csv(csv_path: str, dry_run: bool = False, auto_yes: bool = False):
    """Update teams from CSV file."""
    
    csv_file = Path(csv_path)
    
    if not csv_file.exists():
        # Try relative to current directory or data/exports
        if not csv_file.is_absolute():
            csv_file = Path('data/exports') / csv_path
        if not csv_file.exists():
            csv_file = Path(csv_path)
    
    if not csv_file.exists():
        console.print(f"[red]Error: CSV file not found: {csv_path}[/red]")
        console.print(f"Tried: {csv_file.absolute()}")
        return
    
    console.print(f"[blue]Reading teams from: {csv_file}[/blue]")
    
    updates = []
    skipped = []
    errors = []
    
    # Fields that can be updated in teams table
    updatable_fields = ['club_name', 'state_code', 'state', 'team_name', 'age_group', 'gender', 'birth_year']
    
    # Fields that can be updated in team_alias_map table
    alias_updatable_fields = ['division', 'alias', 'modular11_alias']
    
    # Try different encodings (Excel often saves with different encodings)
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    file_handle = None
    selected_encoding = None
    
    for encoding in encodings:
        try:
            test_handle = open(csv_file, 'r', encoding=encoding, errors='strict')
            # Test read entire file to verify encoding works
            test_handle.read()
            test_handle.close()
            # If successful, use this encoding
            selected_encoding = encoding
            break
        except (UnicodeDecodeError, UnicodeError):
            if test_handle:
                test_handle.close()
            continue
    
    if selected_encoding is None:
        console.print(f"[red]Error: Could not read CSV file with any supported encoding[/red]")
        return
    
    # Open file with the selected encoding
    file_handle = open(csv_file, 'r', encoding=selected_encoding, errors='replace')
    
    try:
        reader = csv.DictReader(file_handle)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (row 1 is header)
            team_id = row.get('team_id_master', '').strip()
            
            if not team_id:
                skipped.append({
                    'row_num': row_num,
                    'team_name': row.get('team_name', 'Unknown'),
                    'reason': 'Missing team_id_master'
                })
                continue
            
            # Get current team data
            current_data = get_current_team_data(team_id)
            if not current_data:
                errors.append({
                    'row_num': row_num,
                    'team_id': team_id,
                    'team_name': row.get('team_name', 'Unknown'),
                    'reason': 'Team not found in database'
                })
                continue
            
            # Build update payload with only changed fields
            update_payload = {}
            alias_update_payload = {}
            changes = []
            
            # Process teams table fields
            for field in updatable_fields:
                csv_value = row.get(field, '').strip()
                current_value = current_data.get(field)
                
                # Handle None values
                if current_value is None:
                    current_value = ''
                
                # Normalize empty strings to None for database (except for birth_year which can be empty)
                if csv_value == '':
                    if field == 'birth_year':
                        csv_value = None  # Allow empty birth_year
                    else:
                        csv_value = None
                else:
                    csv_value = csv_value.strip()
                
                # Normalize current value for comparison
                if current_value == '':
                    current_value = None
                
                # Special handling for state_code
                if field == 'state_code' and csv_value:
                    csv_value = csv_value.upper()
                    if not validate_state_code(csv_value):
                        errors.append({
                            'row_num': row_num,
                            'team_id': team_id,
                            'team_name': row.get('team_name', 'Unknown'),
                            'reason': f'Invalid state_code: {csv_value} (must be 2 characters)'
                        })
                        continue
                
                # Special handling for age_group - normalize to lowercase
                if field == 'age_group' and csv_value:
                    csv_value = csv_value.lower().strip()
                    # Validate format (u## or ##)
                    if not (csv_value.startswith('u') and csv_value[1:].isdigit()) and not csv_value.isdigit():
                        errors.append({
                            'row_num': row_num,
                            'team_id': team_id,
                            'team_name': row.get('team_name', 'Unknown'),
                            'reason': f'Invalid age_group: {csv_value} (must be u## or ##)'
                        })
                        continue
                
                # Special handling for gender - normalize to title case
                if field == 'gender' and csv_value:
                    csv_value = csv_value.title().strip()
                    if csv_value not in ['Male', 'Female']:
                        errors.append({
                            'row_num': row_num,
                            'team_id': team_id,
                            'team_name': row.get('team_name', 'Unknown'),
                            'reason': f'Invalid gender: {csv_value} (must be Male or Female)'
                        })
                        continue
                
                # Special handling for birth_year - convert to integer
                if field == 'birth_year' and csv_value:
                    try:
                        csv_value = int(csv_value)
                        # Validate reasonable birth year (e.g., 2000-2020)
                        if csv_value < 2000 or csv_value > 2020:
                            errors.append({
                                'row_num': row_num,
                                'team_id': team_id,
                                'team_name': row.get('team_name', 'Unknown'),
                                'reason': f'Invalid birth_year: {csv_value} (must be between 2000-2020)'
                            })
                            continue
                    except ValueError:
                        errors.append({
                            'row_num': row_num,
                            'team_id': team_id,
                            'team_name': row.get('team_name', 'Unknown'),
                            'reason': f'Invalid birth_year: {csv_value} (must be a number)'
                        })
                        continue
                
                # Only include if value changed
                if csv_value != current_value:
                    update_payload[field] = csv_value
                    changes.append({
                        'field': field,
                        'old': str(current_value) if current_value is not None else '(empty)',
                        'new': str(csv_value) if csv_value is not None else '(empty)'
                    })
            
            # Process team_alias_map fields (division, alias, modular11_alias)
            # Get current alias data from team_alias_map
            current_aliases = {}
            current_division = None
            
            # Get Modular11 provider ID
            try:
                provider_result = supabase.table('providers').select('id, name').eq('name', 'Modular11').execute()
                modular11_provider_id = provider_result.data[0]['id'] if provider_result.data else None
            except:
                modular11_provider_id = None
            
            try:
                alias_result = supabase.table('team_alias_map').select(
                    'provider_id, provider_team_id, division'
                ).eq('team_id_master', team_id).execute()
                
                if alias_result.data:
                    for alias_row in alias_result.data:
                        provider_id = alias_row.get('provider_id')
                        provider_team_id = alias_row.get('provider_team_id')
                        
                        # Store division (prefer non-null)
                        if alias_row.get('division') and (current_division is None or current_division == ''):
                            current_division = alias_row.get('division')
                        
                        # Store aliases by provider
                        if provider_id:
                            current_aliases[str(provider_id)] = provider_team_id
                            
                            # Also store as modular11_alias if it's Modular11
                            if modular11_provider_id and str(provider_id) == str(modular11_provider_id):
                                current_aliases['modular11'] = provider_team_id
                        
                        # Store first alias as generic 'alias'
                        if 'generic' not in current_aliases and provider_team_id:
                            current_aliases['generic'] = provider_team_id
            except Exception as e:
                console.print(f"[yellow]Warning: Error fetching aliases for team {team_id}: {e}[/yellow]")
            
            # Check if division needs updating
            csv_division = row.get('division', '').strip()
            if csv_division == '':
                csv_division = None
            else:
                csv_division = csv_division.strip().upper()  # Normalize to uppercase (HD/AD)
                # Validate division values
                if csv_division not in ['HD', 'AD', None]:
                    errors.append({
                        'row_num': row_num,
                        'team_id': team_id,
                        'team_name': row.get('team_name', 'Unknown'),
                        'reason': f'Invalid division: {csv_division} (must be HD, AD, or empty)'
                    })
                    continue
            
            if csv_division != current_division:
                alias_update_payload['division'] = csv_division
                changes.append({
                    'field': 'division (team_alias_map)',
                    'old': current_division or '(empty)',
                    'new': csv_division or '(empty)'
                })
            
            # Check if modular11_alias needs updating
            csv_modular11_alias = row.get('modular11_alias', '').strip()
            if csv_modular11_alias:
                current_modular11 = current_aliases.get('modular11', '')
                if csv_modular11_alias != current_modular11:
                    alias_update_payload['modular11_alias'] = csv_modular11_alias
                    changes.append({
                        'field': 'modular11_alias (team_alias_map)',
                        'old': current_modular11 or '(empty)',
                        'new': csv_modular11_alias
                    })
            
            # Check if alias needs updating (handle multiple aliases)
            csv_alias = row.get('alias', '').strip()
            if csv_alias:
                # Split by semicolon to get all aliases (clean up whitespace)
                csv_alias_values = [a.strip() for a in csv_alias.split(';') if a.strip()]
                
                # Get all current aliases for this team (all providers)
                current_alias_list = []
                try:
                    all_aliases_result = supabase.table('team_alias_map').select(
                        'provider_team_id'
                    ).eq('team_id_master', team_id).execute()
                    if all_aliases_result.data:
                        current_alias_list = [a.get('provider_team_id') for a in all_aliases_result.data if a.get('provider_team_id')]
                except:
                    pass
                
                # Find aliases that need to be added (not in current list)
                aliases_to_add = [a for a in csv_alias_values if a not in current_alias_list]
                
                # Only update if there are new aliases to add
                if aliases_to_add:
                    alias_update_payload['alias'] = csv_alias_values[0] if csv_alias_values else csv_alias
                    alias_update_payload['alias_all'] = csv_alias_values  # Store all aliases to process
                    changes.append({
                        'field': 'alias (team_alias_map)',
                        'old': ', '.join(current_alias_list) if current_alias_list else '(empty)',
                        'new': ', '.join(current_alias_list + aliases_to_add) + f' ({len(aliases_to_add)} new)'
                    })
            
            # Skip if no changes
            if not update_payload and not alias_update_payload:
                skipped.append({
                    'row_num': row_num,
                    'team_name': row.get('team_name', 'Unknown'),
                    'reason': 'No changes detected'
                })
                continue
            
            updates.append({
                'team_id': team_id,
                'team_name': row.get('team_name', current_data.get('team_name', 'Unknown')),
                'update_payload': update_payload,
                'alias_update_payload': alias_update_payload,
                'changes': changes
            })
    finally:
        if file_handle:
            file_handle.close()
    
    # Display summary
    console.print()
    console.print(Panel(
        f"[bold]Summary[/bold]\n"
        f"Teams to update: [green]{len(updates)}[/green]\n"
        f"Skipped (no changes): [yellow]{len([s for s in skipped if s['reason'] == 'No changes detected'])}[/yellow]\n"
        f"Errors: [red]{len(errors)}[/red]",
        border_style="blue"
    ))
    
    # Show errors
    if errors:
        console.print("\n[red]Errors:[/red]")
        error_table = Table(show_header=True, header_style="bold red")
        error_table.add_column("Row", style="dim")
        error_table.add_column("Team ID", style="dim")
        error_table.add_column("Team Name", max_width=40)
        error_table.add_column("Reason", style="red")
        
        for error in errors[:20]:  # Show first 20 errors
            error_table.add_row(
                str(error['row_num']),
                error['team_id'][:8] + '...',
                error['team_name'][:40],
                error['reason']
            )
        
        console.print(error_table)
        if len(errors) > 20:
            console.print(f"[dim]... and {len(errors) - 20} more errors[/dim]")
    
    # Show preview of updates
    if updates:
        console.print("\n[bold]Preview of updates (first 10):[/bold]")
        preview_table = Table(show_header=True, header_style="bold cyan")
        preview_table.add_column("Team Name", max_width=40)
        preview_table.add_column("Changes", style="yellow")
        
        for update in updates[:10]:
            changes_str = ", ".join([
                f"{c['field']}: {c['old']} → {c['new']}"
                for c in update['changes']
            ])
            preview_table.add_row(
                update['team_name'][:40],
                changes_str
            )
        
        console.print(preview_table)
        
        if len(updates) > 10:
            console.print(f"[dim]... and {len(updates) - 10} more updates[/dim]")
    
    # Dry run mode
    if dry_run:
        console.print("\n[yellow]DRY RUN MODE - No changes will be made[/yellow]")
        return
    
    # Confirm before updating
    if not updates:
        console.print("\n[yellow]No teams to update.[/yellow]")
        return
    
    if not auto_yes:
        console.print("\n" + "="*80)
        response = input(f"Update {len(updates)} teams in the database? (yes/no): ").strip().lower()
        
        if response != 'yes':
            console.print("[yellow]Update cancelled.[/yellow]")
            return
    else:
        console.print(f"\n[green]Auto-confirming update of {len(updates)} teams...[/green]")
    
    # Get Modular11 provider ID for alias updates
    try:
        provider_result = supabase.table('providers').select('id, name').eq('name', 'Modular11').execute()
        modular11_provider_id = provider_result.data[0]['id'] if provider_result.data else None
    except:
        modular11_provider_id = None
    
    # Update teams in batches
    console.print("\n[blue]Updating teams...[/blue]")
    batch_size = 50  # Smaller batches for updates
    updated_count = 0
    failed_count = 0
    
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        
        for update in batch:
            try:
                # Update teams table if needed
                if update['update_payload']:
                    result = supabase.table('teams').update(
                        update['update_payload']
                    ).eq('team_id_master', update['team_id']).execute()
                    
                    if not result.data:
                        console.print(f"[yellow]Warning: No team found with ID {update['team_id']}[/yellow]")
                        failed_count += 1
                        continue
                
                # Update team_alias_map if needed
                if update['alias_update_payload']:
                    alias_payload = update['alias_update_payload']
                    
                    # Handle division update (applies to all aliases for this team)
                    if 'division' in alias_payload:
                        supabase.table('team_alias_map').update({
                            'division': alias_payload['division']
                        }).eq('team_id_master', update['team_id']).execute()
                    
                    # Handle modular11_alias update
                    if 'modular11_alias' in alias_payload and modular11_provider_id:
                        modular11_alias = alias_payload['modular11_alias']
                        # Check if Modular11 alias already exists for this team
                        existing = supabase.table('team_alias_map').select('id, provider_team_id').eq(
                            'team_id_master', update['team_id']
                        ).eq('provider_id', modular11_provider_id).execute()
                        
                        if existing.data:
                            # Only update if the value actually changed
                            if existing.data[0].get('provider_team_id') != modular11_alias:
                                result = supabase.table('team_alias_map').update({
                                    'provider_team_id': modular11_alias
                                }).eq('team_id_master', update['team_id']).eq(
                                    'provider_id', modular11_provider_id
                                ).execute()
                                
                                if not result.data:
                                    console.print(f"[yellow]Warning: Failed to update modular11_alias for team {update['team_id']}[/yellow]")
                        else:
                            # Create new alias entry
                            try:
                                result = supabase.table('team_alias_map').insert({
                                    'team_id_master': update['team_id'],
                                    'provider_id': modular11_provider_id,
                                    'provider_team_id': modular11_alias,
                                    'match_method': 'manual',
                                    'match_confidence': 1.0,
                                    'review_status': 'approved',
                                    'division': alias_payload.get('division')
                                }).execute()
                                
                                if not result.data:
                                    console.print(f"[yellow]Warning: Failed to create modular11_alias for team {update['team_id']}[/yellow]")
                            except Exception as alias_error:
                                # Check if it's a duplicate key error
                                if 'duplicate key' in str(alias_error).lower() or '23505' in str(alias_error):
                                    console.print(f"[yellow]Warning: Modular11 alias {modular11_alias} already exists for another team, skipping[/yellow]")
                                else:
                                    raise
                    
                    # Handle generic alias update (process all aliases - only add new ones)
                    if 'alias_all' in alias_payload:
                        all_aliases = alias_payload['alias_all']
                        
                        # Get all existing aliases for this team to know which ones already exist
                        existing_aliases = {}
                        try:
                            existing_result = supabase.table('team_alias_map').select(
                                'id, provider_id, provider_team_id'
                            ).eq('team_id_master', update['team_id']).execute()
                            
                            if existing_result.data:
                                for alias_row in existing_result.data:
                                    existing_aliases[alias_row.get('provider_team_id')] = {
                                        'id': alias_row.get('id'),
                                        'provider_id': alias_row.get('provider_id')
                                    }
                        except Exception as e:
                            console.print(f"[yellow]Warning: Error fetching existing aliases: {e}[/yellow]")
                        
                        # Process each alias from CSV - only add new ones
                        for alias_value in all_aliases:
                            alias_value = alias_value.strip()
                            if not alias_value:
                                continue
                            
                            # Check if this alias already exists for this team
                            if alias_value in existing_aliases:
                                # Alias already exists for this team, skip (don't remove, just skip)
                                continue
                            
                            # Try to find which provider this alias might belong to
                            # Check if it exists in the database for any team (to infer provider)
                            provider_id_to_use = None
                            try:
                                # Check if this alias exists elsewhere to get its provider
                                check_result = supabase.table('team_alias_map').select('provider_id').eq(
                                    'provider_team_id', alias_value
                                ).limit(1).execute()
                                
                                if check_result.data:
                                    provider_id_to_use = check_result.data[0].get('provider_id')
                            except:
                                pass
                            
                            # If we couldn't infer provider, use Modular11 as default (or first existing provider)
                            if not provider_id_to_use:
                                if existing_aliases:
                                    # Use provider from first existing alias
                                    first_existing = list(existing_aliases.values())[0]
                                    provider_id_to_use = first_existing.get('provider_id')
                                elif modular11_provider_id:
                                    provider_id_to_use = modular11_provider_id
                                else:
                                    # Can't create alias without a provider
                                    console.print(f"[yellow]Warning: Cannot create alias {alias_value} - no provider available[/yellow]")
                                    continue
                            
                            # Try to create the new alias
                            try:
                                result = supabase.table('team_alias_map').insert({
                                    'team_id_master': update['team_id'],
                                    'provider_id': provider_id_to_use,
                                    'provider_team_id': alias_value,
                                    'match_method': 'manual',
                                    'match_confidence': 1.0,
                                    'review_status': 'approved',
                                    'division': alias_payload.get('division')
                                }).execute()
                                
                                if not result.data:
                                    console.print(f"[yellow]Warning: Failed to create alias {alias_value} for team {update['team_id']}[/yellow]")
                            except Exception as alias_error:
                                # Check if it's a duplicate key error (alias exists for different team)
                                if 'duplicate key' in str(alias_error).lower() or '23505' in str(alias_error):
                                    console.print(f"[yellow]Warning: Alias {alias_value} already exists for another team, skipping[/yellow]")
                                else:
                                    console.print(f"[yellow]Warning: Error creating alias {alias_value}: {alias_error}[/yellow]")
                    
                    # Fallback: handle single alias if alias_all not present
                    elif 'alias' in alias_payload:
                        generic_alias = alias_payload['alias']
                        # Find first alias entry for this team
                        existing = supabase.table('team_alias_map').select('id, provider_id, provider_team_id').eq(
                            'team_id_master', update['team_id']
                        ).limit(1).execute()
                        
                        if existing.data:
                            # Only update if the value actually changed
                            if existing.data[0].get('provider_team_id') != generic_alias:
                                result = supabase.table('team_alias_map').update({
                                    'provider_team_id': generic_alias
                                }).eq('id', existing.data[0]['id']).execute()
                                
                                if not result.data:
                                    console.print(f"[yellow]Warning: Failed to update alias for team {update['team_id']}[/yellow]")
                        else:
                            # Create new alias entry (need a provider - use Modular11 if available, otherwise skip)
                            if modular11_provider_id:
                                try:
                                    result = supabase.table('team_alias_map').insert({
                                        'team_id_master': update['team_id'],
                                        'provider_id': modular11_provider_id,
                                        'provider_team_id': generic_alias,
                                        'match_method': 'manual',
                                        'match_confidence': 1.0,
                                        'review_status': 'approved',
                                        'division': alias_payload.get('division')
                                    }).execute()
                                    
                                    if not result.data:
                                        console.print(f"[yellow]Warning: Failed to create alias for team {update['team_id']}[/yellow]")
                                except Exception as alias_error:
                                    # Check if it's a duplicate key error
                                    if 'duplicate key' in str(alias_error).lower() or '23505' in str(alias_error):
                                        console.print(f"[yellow]Warning: Alias {generic_alias} already exists for another team, skipping[/yellow]")
                                    else:
                                        raise
                
                updated_count += 1
                    
            except Exception as e:
                console.print(f"[red]Error updating team {update['team_id']}: {e}[/red]")
                failed_count += 1
        
        console.print(f"  Processed {min(i + batch_size, len(updates))}/{len(updates)} teams...")
    
    # Final summary
    console.print("\n" + "="*80)
    console.print(Panel(
        f"[bold]Update Complete![/bold]\n"
        f"Successfully updated: [green]{updated_count}[/green]\n"
        f"Failed: [red]{failed_count}[/red]",
        border_style="green" if failed_count == 0 else "yellow"
    ))
    
    if skipped:
        skipped_no_changes = [s for s in skipped if s['reason'] == 'No changes detected']
        skipped_other = [s for s in skipped if s['reason'] != 'No changes detected']
        
        if skipped_other:
            console.print(f"\n[yellow]Skipped {len(skipped_other)} rows (missing data or invalid):[/yellow]")
            reasons = {}
            for skip in skipped_other:
                reason = skip['reason']
                reasons[reason] = reasons.get(reason, 0) + 1
            for reason, count in reasons.items():
                console.print(f"  - {reason}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description='Update teams in database from CSV file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Update teams from CSV
  python scripts/update_teams_from_csv.py u13_male_az.csv
  
  # Preview changes without updating (dry run)
  python scripts/update_teams_from_csv.py u13_male_az.csv --dry-run
        """
    )
    parser.add_argument('csv_file', help='CSV file to import (exported from view_teams.py)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without updating the database')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Auto-confirm updates without prompting')
    
    args = parser.parse_args()
    
    update_teams_from_csv(args.csv_file, dry_run=args.dry_run, auto_yes=args.yes)


if __name__ == '__main__':
    main()

