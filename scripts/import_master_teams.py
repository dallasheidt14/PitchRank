"""Import master team CSV files"""
import sys
import csv
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import uuid
from datetime import datetime

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track
from rich.table import Table

sys.path.append(str(Path(__file__).parent.parent))
from src.utils.validators import TeamValidator
from config.settings import PROVIDERS

console = Console()
load_dotenv()


class MasterTeamImporter:
    """Import master teams from CSV files"""

    def __init__(self):
        self.supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        self.validator = TeamValidator()
        self.stats = {
            'total': 0,
            'valid': 0,
            'invalid': 0,
            'inserted': 0,
            'updated': 0,
            'errors': []
        }

    def import_teams(self, filepath: Path, provider_code: str, age_filter: Optional[str] = None):
        """Import teams from CSV file"""
        
        # Get provider ID
        provider_id = self._get_provider_id(provider_code)
        
        console.print(f"[bold]Importing teams from {filepath}[/bold]")
        console.print(f"Provider: {PROVIDERS[provider_code]['name']}")
        if age_filter:
            console.print(f"Age filter: {age_filter}")
        
        # Read CSV
        teams = self._read_csv(filepath)
        
        # Apply age filter if provided
        if age_filter:
            age_filter_lower = age_filter.lower()
            teams = [t for t in teams if t.get('age_group', '').lower() == age_filter_lower]
            console.print(f"Filtered to {len(teams)} teams for age group {age_filter}")
        
        self.stats['total'] = len(teams)
        
        console.print(f"Found {len(teams)} teams to import\n")
        
        # Process teams
        for team_data in track(teams, description="Processing teams"):
            self._process_team(team_data, provider_id, provider_code)
        
        # Print summary
        self._print_summary()

    def _process_team(self, team_data: Dict, provider_id: str, provider_code: str):
        """Process a single team record"""
        # Add provider info
        team_data['provider'] = provider_code
        team_data['provider_id'] = provider_id
        
        # Validate
        is_valid, error = self.validator.validate(team_data)
        
        if not is_valid:
            self.stats['invalid'] += 1
            self.stats['errors'].append({
                'team': team_data.get('team_name', 'Unknown'),
                'error': error
            })
            return
        
        self.stats['valid'] += 1
        
        try:
            # Check if team exists
            existing = self._find_existing_team(
                provider_id=provider_id,
                provider_team_id=team_data.get('provider_team_id'),
                team_name=team_data.get('team_name')
            )
            
            # Generate or get team_id_master
            if existing:
                team_id_master = existing['team_id_master']
            else:
                # Generate new UUID for team_id_master
                team_id_master = str(uuid.uuid4())
            
            # Prepare team record
            team_record = {
                'team_id_master': team_id_master,
                'team_name': team_data.get('team_name'),
                'provider_id': provider_id,
                'provider_team_id': team_data.get('provider_team_id'),
                'age_group': team_data.get('age_group', '').lower(),
                'birth_year': team_data.get('birth_year'),  # Optional
                'gender': team_data.get('gender', 'Male'),
                'club_name': team_data.get('club_name'),
                'state_code': team_data.get('state_code'),
            }
            
            if existing:
                # Update existing team
                self.supabase.table('teams').update(team_record).eq(
                    'team_id_master', team_id_master
                ).execute()
                self.stats['updated'] += 1
            else:
                # Insert new team
                self.supabase.table('teams').insert(team_record).execute()
                self.stats['inserted'] += 1
            
            # Create alias map entry
            self._create_alias(
                provider_id=provider_id,
                provider_team_id=team_data.get('provider_team_id'),
                team_id_master=team_id_master,
                team_name=team_data.get('team_name'),
                age_group=team_data.get('age_group', '').lower(),
                gender=team_data.get('gender', 'Male')
            )
            
        except Exception as e:
            self.stats['errors'].append({
                'team': team_data.get('team_name', 'Unknown'),
                'error': str(e)
            })

    def _find_existing_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: str
    ) -> Optional[Dict]:
        """Find existing team by provider ID or name"""
        try:
            # Try provider_team_id first
            if provider_team_id:
                result = self.supabase.table('teams').select('team_id_master').eq(
                    'provider_id', provider_id
                ).eq('provider_team_id', provider_team_id).single().execute()
                
                if result.data:
                    return result.data
            
            # Try name match
            result = self.supabase.table('teams').select('team_id_master, team_name').eq(
                'provider_id', provider_id
            ).ilike('team_name', team_name).limit(1).execute()
            
            if result.data:
                return result.data[0]
                
        except Exception:
            pass
        
        return None

    def _create_alias(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_id_master: str,
        team_name: str,
        age_group: str,
        gender: str
    ):
        """Create alias map entry"""
        try:
            alias_data = {
                'provider_id': provider_id,
                'provider_team_id': provider_team_id,
                'team_id_master': team_id_master,
                'team_name': team_name,
                'age_group': age_group,
                'gender': gender,
                'match_method': 'csv_import',
                'match_confidence': 1.0,
                'review_status': 'approved',
                'created_at': datetime.now().isoformat()
            }
            
            # Check if alias exists
            query = self.supabase.table('team_alias_map').select('id')
            if provider_team_id:
                query = query.eq('provider_id', provider_id).eq(
                    'provider_team_id', provider_team_id
                )
            else:
                query = query.eq('provider_id', provider_id).eq(
                    'team_name', team_name
                ).eq('age_group', age_group).eq('gender', gender)
            
            existing = query.execute()
            
            if existing.data:
                # Update
                self.supabase.table('team_alias_map').update(alias_data).eq(
                    'id', existing.data[0]['id']
                ).execute()
            else:
                # Insert
                self.supabase.table('team_alias_map').insert(alias_data).execute()
                
        except Exception as e:
            console.print(f"[yellow]Warning: Could not create alias: {e}[/yellow]")

    def _get_provider_id(self, provider_code: str) -> str:
        """Get provider UUID from code"""
        result = self.supabase.table('providers').select('id').eq(
            'code', provider_code
        ).single().execute()
        
        if not result.data:
            raise ValueError(f"Provider not found: {provider_code}")
        
        return result.data['id']

    def _read_csv(self, filepath: Path) -> List[Dict]:
        """Read teams from CSV file"""
        teams = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys (handle various column name formats)
                team_data = {}
                for key, value in row.items():
                    # Normalize column names
                    normalized_key = key.lower().strip().replace(' ', '_')
                    team_data[normalized_key] = value.strip() if value else None
                
                teams.append(team_data)
        
        return teams

    def _print_summary(self):
        """Print import summary"""
        table = Table(title="Import Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="yellow")
        
        table.add_row("Total teams", str(self.stats['total']))
        table.add_row("Valid", f"[green]{self.stats['valid']}[/green]")
        table.add_row("Invalid", f"[red]{self.stats['invalid']}[/red]")
        table.add_row("Inserted", f"[green]{self.stats['inserted']}[/green]")
        table.add_row("Updated", f"[yellow]{self.stats['updated']}[/yellow]")
        table.add_row("Errors", f"[red]{len(self.stats['errors'])}[/red]")
        
        console.print("\n")
        console.print(table)
        
        if self.stats['errors']:
            console.print("\n[bold red]Errors:[/bold red]")
            for error in self.stats['errors'][:10]:  # Show first 10
                console.print(f"  - {error['team']}: {error['error']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import master teams from CSV file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python import_master_teams.py teams.csv gotsport
  python import_master_teams.py --path data/samples/teams.csv --provider gotsport
  python import_master_teams.py --path data/samples --age u10 --provider gotsport
  
Provider codes:
""" + "\n".join(f"  - {code}: {info['name']}" for code, info in PROVIDERS.items())
    )
    
    parser.add_argument(
        'filepath',
        nargs='?',
        type=Path,
        help='Path to CSV file or directory containing CSV files'
    )
    parser.add_argument(
        'provider_code',
        nargs='?',
        help='Provider code (gotsport, tgs, usclub)'
    )
    parser.add_argument(
        '--path',
        type=Path,
        help='Path to CSV file or directory containing CSV files'
    )
    parser.add_argument(
        '--provider',
        choices=list(PROVIDERS.keys()),
        help='Provider code'
    )
    parser.add_argument(
        '--age',
        help='Filter by age group (e.g., u10, u12)'
    )
    
    args = parser.parse_args()
    
    # Get filepath (prefer --path, then positional)
    filepath = args.path or args.filepath
    provider_code = args.provider or args.provider_code
    
    # Validation
    if not filepath:
        parser.print_help()
        console.print("\n[red]Error: CSV file or path required[/red]")
        sys.exit(1)
    
    if not provider_code:
        parser.print_help()
        console.print("\n[red]Error: Provider code required[/red]")
        sys.exit(1)
    
    if not filepath.exists():
        console.print(f"[red]File or directory not found: {filepath}[/red]")
        sys.exit(1)
    
    # Find CSV files
    csv_files = []
    if filepath.is_file():
        if filepath.suffix.lower() == '.csv':
            csv_files = [filepath]
        else:
            console.print(f"[red]File is not a CSV: {filepath}[/red]")
            sys.exit(1)
    elif filepath.is_dir():
        csv_files = list(filepath.glob("*.csv"))
        if not csv_files:
            console.print(f"[red]No CSV files found in {filepath}[/red]")
            sys.exit(1)
        console.print(f"[cyan]Found {len(csv_files)} CSV file(s) in directory[/cyan]")
    else:
        console.print(f"[red]Invalid path: {filepath}[/red]")
        sys.exit(1)
    
    # Process files
    importer = MasterTeamImporter()
    for csv_file in csv_files:
        console.print(f"\n[bold]Processing: {csv_file}[/bold]")
        importer.import_teams(csv_file, provider_code, age_filter=args.age)

