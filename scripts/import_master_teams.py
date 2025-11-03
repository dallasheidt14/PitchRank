"""Import master team CSV files with batch processing and validation"""
import sys
import csv
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import uuid
from datetime import datetime

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track, Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

sys.path.append(str(Path(__file__).parent.parent))
from src.utils.validators import TeamValidator
from config.settings import PROVIDERS, BASE_DIR

console = Console()
load_dotenv()

# Batch size for processing
BATCH_SIZE = 500


class MasterTeamImporter:
    """Import master teams from CSV files with batch processing"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Validate environment variables
        self._validate_environment()
        
        # Initialize Supabase client
        self.supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        
        # Test connection
        self._test_connection()
        
        self.validator = TeamValidator()
        self.stats = {
            'total': 0,
            'valid': 0,
            'invalid': 0,
            'inserted': 0,
            'updated': 0,
            'errors': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'processing_time_seconds': None
        }
        
        # Create required directories
        self.quarantine_dir = BASE_DIR / "data" / "quarantine"
        self.logs_dir = BASE_DIR / "data" / "logs"
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Invalid teams storage
        self.invalid_teams = []
        
        if self.dry_run:
            console.print("[yellow]🔍 DRY-RUN MODE: No changes will be written to database[/yellow]")

    def _validate_environment(self):
        """Validate required environment variables"""
        required_vars = [
            'SUPABASE_URL',
            'SUPABASE_SERVICE_ROLE_KEY'
        ]
        
        missing = []
        for var in required_vars:
            if not os.getenv(var):
                missing.append(var)
        
        if missing:
            console.print(f"[red]❌ Missing required environment variables: {', '.join(missing)}[/red]")
            console.print("[yellow]Please check your .env file[/yellow]")
            sys.exit(1)

    def _test_connection(self):
        """Test Supabase connection"""
        try:
            # Try a simple query
            result = self.supabase.table('providers').select('count', count='exact').execute()
            console.print("[green]✅ Database connection successful[/green]")
        except Exception as e:
            console.print(f"[red]❌ Database connection failed: {e}[/red]")
            sys.exit(1)

    def import_teams(self, filepath: Path, provider_code: str, age_filter: Optional[str] = None):
        """Import teams from CSV file with batch processing"""
        
        # Pre-validate provider exists
        provider_id = self._validate_provider(provider_code)
        
        console.print(f"[bold]Importing teams from {filepath}[/bold]")
        console.print(f"Provider: {PROVIDERS[provider_code]['name']}")
        if age_filter:
            console.print(f"Age filter: {age_filter}")
        if self.dry_run:
            console.print("[yellow]⚠️  DRY-RUN: Preview mode - no database writes[/yellow]")
        
        # Read CSV
        teams = self._read_csv(filepath)
        
        # Apply age filter if provided
        if age_filter:
            age_filter_lower = age_filter.lower()
            teams = [t for t in teams if t.get('age_group', '').lower() == age_filter_lower]
            console.print(f"Filtered to {len(teams)} teams for age group {age_filter}")
        
        self.stats['total'] = len(teams)
        console.print(f"Found {len(teams)} teams to import\n")
        
        # Process teams in batches
        self._process_teams_batch(teams, provider_id, provider_code)
        
        # Save invalid teams to quarantine
        if self.invalid_teams:
            self._save_invalid_teams(filepath)
        
        # Save import summary
        self._save_import_summary(filepath, provider_code)
        
        # Print summary
        self._print_summary()

    def _validate_provider(self, provider_code: str) -> str:
        """Validate provider exists in database before starting"""
        try:
            result = self.supabase.table('providers').select('id').eq(
                'code', provider_code
            ).single().execute()
            
            if not result.data:
                console.print(f"[red]❌ Provider not found in database: {provider_code}[/red]")
                console.print("[yellow]Available providers:[/yellow]")
                all_providers = self.supabase.table('providers').select('code, name').execute()
                for p in all_providers.data:
                    console.print(f"  - {p['code']}: {p['name']}")
                sys.exit(1)
            
            return result.data['id']
        except Exception as e:
            console.print(f"[red]❌ Error validating provider: {e}[/red]")
            sys.exit(1)

    def _process_teams_batch(self, teams: List[Dict], provider_id: str, provider_code: str):
        """Process teams in batches using upsert"""
        # Collect all valid teams
        valid_teams = []
        team_alias_map_entries = []
        
        console.print("[cyan]Validating teams...[/cyan]")
        
        # First pass: validate and prepare data
        for team_data in track(teams, description="Validating"):
            team_data['provider'] = provider_code
            team_data['provider_id'] = provider_id
            
            # Validate
            is_valid, error = self.validator.validate(team_data)
            
            if not is_valid:
                self.stats['invalid'] += 1
                self.invalid_teams.append({
                    **team_data,
                    'validation_error': error
                })
                continue
            
            self.stats['valid'] += 1
            
            # Check if team exists
            existing = self._find_existing_team(
                provider_id=provider_id,
                provider_team_id=team_data.get('provider_team_id'),
                team_name=team_data.get('team_name')
            )
            
            # Generate or get team_id_master
            if existing:
                team_id_master = existing['team_id_master']
                is_update = True
            else:
                team_id_master = str(uuid.uuid4())
                is_update = False
            
            # Prepare team record
            team_record = {
                'team_id_master': team_id_master,
                'team_name': team_data.get('team_name'),
                'provider_id': provider_id,
                'provider_team_id': team_data.get('provider_team_id'),
                'age_group': team_data.get('age_group', '').lower(),
                'birth_year': int(team_data['birth_year']) if team_data.get('birth_year') and str(team_data['birth_year']).isdigit() else None,
                'gender': team_data.get('gender', 'Male'),
                'club_name': team_data.get('club_name'),
                'state_code': team_data.get('state_code'),
            }
            
            valid_teams.append({
                'record': team_record,
                'is_update': is_update,
                'team_id_master': team_id_master
            })
            
            # Prepare alias map entry
            alias_entry = {
                'provider_id': provider_id,
                'provider_team_id': team_data.get('provider_team_id'),
                'team_id_master': team_id_master,
                'match_method': 'csv_import',
                'match_confidence': 1.0,
                'review_status': 'approved'
            }
            team_alias_map_entries.append(alias_entry)
        
        # Second pass: batch upsert teams
        if not self.dry_run:
            console.print(f"\n[cyan]Processing {len(valid_teams)} valid teams in batches of {BATCH_SIZE}...[/cyan]")
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Upserting teams...", total=len(valid_teams))
                
                for i in range(0, len(valid_teams), BATCH_SIZE):
                    batch = valid_teams[i:i + BATCH_SIZE]
                    batch_records = [t['record'] for t in batch]
                    
                    try:
                        # Upsert teams (insert or update)
                        result = self.supabase.table('teams').upsert(
                            batch_records,
                            on_conflict='provider_id,provider_team_id'
                        ).execute()
                        
                        # Update stats
                        for team_info in batch:
                            if team_info['is_update']:
                                self.stats['updated'] += 1
                            else:
                                self.stats['inserted'] += 1
                        
                        progress.update(task, advance=len(batch))
                        
                    except Exception as e:
                        console.print(f"[red]Error processing batch {i//BATCH_SIZE + 1}: {e}[/red]")
                        self.stats['errors'].append({
                            'batch': i//BATCH_SIZE + 1,
                            'error': str(e)
                        })
        else:
            # Dry-run: count what would be inserted/updated
            for team_info in valid_teams:
                if team_info['is_update']:
                    self.stats['updated'] += 1
                else:
                    self.stats['inserted'] += 1
            console.print(f"[yellow]Would process {len(valid_teams)} teams in {len(valid_teams)//BATCH_SIZE + 1} batches[/yellow]")
        
        # Third pass: batch upsert alias map entries
        if not self.dry_run and team_alias_map_entries:
            console.print(f"\n[cyan]Processing {len(team_alias_map_entries)} alias map entries...[/cyan]")
            
            for i in range(0, len(team_alias_map_entries), BATCH_SIZE):
                batch = team_alias_map_entries[i:i + BATCH_SIZE]
                
                try:
                    # Upsert alias map entries
                    self.supabase.table('team_alias_map').upsert(
                        batch,
                        on_conflict='provider_id,provider_team_id'
                    ).execute()
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not upsert alias batch {i//BATCH_SIZE + 1}: {e}[/yellow]")

    def _find_existing_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: str
    ) -> Optional[Dict]:
        """Find existing team by provider ID or name"""
        if self.dry_run:
            # In dry-run, don't query database
            return None
            
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

    def _save_invalid_teams(self, source_file: Path):
        """Save invalid teams to quarantine CSV"""
        if not self.invalid_teams:
            return
        
        quarantine_file = self.quarantine_dir / f"invalid_teams_{self.timestamp}.csv"
        
        try:
            with open(quarantine_file, 'w', newline='', encoding='utf-8') as f:
                if self.invalid_teams:
                    # Get all unique keys from invalid teams
                    fieldnames = set()
                    for team in self.invalid_teams:
                        fieldnames.update(team.keys())
                    fieldnames = sorted(list(fieldnames))
                    
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(self.invalid_teams)
            
            console.print(f"\n[yellow]⚠️  {len(self.invalid_teams)} invalid teams saved to: {quarantine_file}[/yellow]")
        except Exception as e:
            console.print(f"[red]Error saving invalid teams: {e}[/red]")

    def _save_import_summary(self, source_file: Path, provider_code: str):
        """Save import summary to JSON file"""
        end_time = datetime.now()
        self.stats['end_time'] = end_time.isoformat()
        start_time = datetime.fromisoformat(self.stats['start_time'])
        self.stats['processing_time_seconds'] = (end_time - start_time).total_seconds()
        
        summary = {
            'import_timestamp': self.timestamp,
            'dry_run': self.dry_run,
            'source_file': str(source_file),
            'provider_code': provider_code,
            'provider_name': PROVIDERS.get(provider_code, {}).get('name', 'Unknown'),
            'statistics': {
                'total_teams': self.stats['total'],
                'valid_teams': self.stats['valid'],
                'invalid_teams': self.stats['invalid'],
                'inserted': self.stats['inserted'],
                'updated': self.stats['updated'],
                'errors': len(self.stats['errors'])
            },
            'processing_info': {
                'start_time': self.stats['start_time'],
                'end_time': self.stats['end_time'],
                'processing_time_seconds': self.stats['processing_time_seconds']
            },
            'errors': self.stats['errors'][:100],  # Limit to first 100 errors
            'quarantine_file': f"invalid_teams_{self.timestamp}.csv" if self.invalid_teams else None
        }
        
        summary_file = self.logs_dir / f"import_summary_{self.timestamp}.json"
        
        try:
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)
            
            console.print(f"\n[green]✅ Import summary saved to: {summary_file}[/green]")
        except Exception as e:
            console.print(f"[red]Error saving import summary: {e}[/red]")

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
        table = Table(title="Import Summary" + (" (DRY-RUN)" if self.dry_run else ""))
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="yellow")
        
        table.add_row("Total teams", str(self.stats['total']))
        table.add_row("Valid", f"[green]{self.stats['valid']}[/green]")
        table.add_row("Invalid", f"[red]{self.stats['invalid']}[/red]")
        table.add_row("Inserted" + (" (would)" if self.dry_run else ""), f"[green]{self.stats['inserted']}[/green]")
        table.add_row("Updated" + (" (would)" if self.dry_run else ""), f"[yellow]{self.stats['updated']}[/yellow]")
        table.add_row("Errors", f"[red]{len(self.stats['errors'])}[/red]")
        
        if self.stats['processing_time_seconds']:
            table.add_row("Processing time", f"{self.stats['processing_time_seconds']:.2f}s")
        
        console.print("\n")
        console.print(table)
        
        if self.stats['errors']:
            console.print("\n[bold red]Errors:[/bold red]")
            for error in self.stats['errors'][:10]:  # Show first 10
                if 'batch' in error:
                    console.print(f"  - Batch {error['batch']}: {error['error']}")
                else:
                    console.print(f"  - {error.get('team', 'Unknown')}: {error.get('error', 'Unknown error')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import master teams from CSV file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python import_master_teams.py teams.csv gotsport
  python import_master_teams.py --path data/samples/teams.csv --provider gotsport
  python import_master_teams.py --path data/samples --age u10 --provider gotsport
  python import_master_teams.py --path teams.csv --provider gotsport --dry-run
  
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
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview import without writing to database'
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
    importer = MasterTeamImporter(dry_run=args.dry_run)
    for csv_file in csv_files:
        console.print(f"\n[bold]Processing: {csv_file}[/bold]")
        importer.import_teams(csv_file, provider_code, age_filter=args.age)
