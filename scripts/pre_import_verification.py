#!/usr/bin/env python3
"""
Comprehensive pre-import verification script

Verifies all critical aspects before running the full import:
- Schema mappings (CSV columns match expected format)
- Data cleaning and normalization logic
- Batch sizes and concurrency settings
- File format recognition
- Record count, unique teams, date ranges
- Bad data handling (quarantine system)
"""
import csv
import sys
import os
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from typing import Dict, List, Set, Optional
from dataclasses import dataclass

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.progress import track

from src.utils.enhanced_validators import EnhancedDataValidator, parse_game_date
from src.etl.enhanced_pipeline import EnhancedETLPipeline

console = Console()
load_dotenv()

# Expected CSV columns (from import script)
EXPECTED_CSV_COLUMNS = {
    'provider', 'team_id', 'team_id_source', 'team_name', 'club_name', 'team_club_name',
    'opponent_id', 'opponent_id_source', 'opponent_name', 'opponent_club_name',
    'age_group', 'gender', 'state', 'competition', 'division_name', 'event_name',
    'venue', 'game_date', 'home_away', 'goals_for', 'goals_against', 'result',
    'source_url', 'scraped_at'
}

# Required columns for validation
REQUIRED_COLUMNS = {
    'provider', 'team_name', 'opponent_name', 'game_date', 'goals_for', 'goals_against'
}

# Optional but important columns
IMPORTANT_COLUMNS = {
    'club_name', 'team_club_name', 'age_group', 'gender', 'state', 'home_away'
}


@dataclass
class VerificationResults:
    """Results from pre-import verification"""
    file_exists: bool = False
    file_size_mb: float = 0.0
    file_format_recognized: bool = False
    schema_mapping_correct: bool = False
    missing_columns: Set[str] = None
    extra_columns: Set[str] = None
    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    unique_teams: int = 0
    unique_opponents: int = 0
    unique_clubs: int = 0
    date_range: tuple = None  # (min_date, max_date)
    age_groups: Set[str] = None
    genders: Set[str] = None
    states: Set[str] = None
    batch_size_ok: bool = False
    concurrency_ok: bool = False
    quarantine_system_ok: bool = False
    sample_validation_errors: List[Dict] = None
    
    def __post_init__(self):
        if self.missing_columns is None:
            self.missing_columns = set()
        if self.extra_columns is None:
            self.extra_columns = set()
        if self.age_groups is None:
            self.age_groups = set()
        if self.genders is None:
            self.genders = set()
        if self.states is None:
            self.states = set()
        if self.sample_validation_errors is None:
            self.sample_validation_errors = []


def check_file_format(file_path: Path) -> tuple[bool, str, float]:
    """Check if file format is recognized and get file size"""
    if not file_path.exists():
        return False, "File not found", 0.0
    
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    
    if file_path.suffix.lower() == '.csv':
        return True, "CSV", file_size_mb
    elif file_path.suffix.lower() in ['.json', '.jsonl', '.ndjson']:
        return True, file_path.suffix.upper(), file_size_mb
    else:
        return False, f"Unknown format: {file_path.suffix}", file_size_mb


def check_schema_mapping(file_path: Path, sample_size: int = 1000) -> tuple[bool, Set[str], Set[str]]:
    """Check if CSV columns match expected schema"""
    if not file_path.exists() or file_path.suffix.lower() != '.csv':
        return False, set(), set()
    
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        actual_columns = set(reader.fieldnames or [])
    
    missing = REQUIRED_COLUMNS - actual_columns
    extra = actual_columns - EXPECTED_CSV_COLUMNS
    
    # Check if we have at least required columns
    schema_ok = len(missing) == 0
    
    return schema_ok, missing, extra


def analyze_data_statistics(file_path: Path, limit: Optional[int] = None) -> Dict:
    """Analyze data statistics from CSV file"""
    stats = {
        'total_records': 0,
        'valid_records': 0,
        'invalid_records': 0,
        'unique_teams': set(),
        'unique_opponents': set(),
        'unique_clubs': set(),
        'dates': [],
        'age_groups': set(),
        'genders': set(),
        'states': set(),
        'validation_errors': []
    }
    
    validator = EnhancedDataValidator()
    
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 1):
            if limit and row_num > limit:
                break
            
            stats['total_records'] += 1
            
            # Convert CSV row to game dict
            game = {
                'provider': row.get('provider', '').strip(),
                'team_id': row.get('team_id') or row.get('team_id_source', ''),
                'team_id_source': row.get('team_id_source', ''),
                'team_name': row.get('team_name', '').strip(),
                'club_name': row.get('club_name') or row.get('team_club_name', '').strip(),
                'opponent_id': row.get('opponent_id') or row.get('opponent_id_source', ''),
                'opponent_id_source': row.get('opponent_id_source', ''),
                'opponent_name': row.get('opponent_name', '').strip(),
                'opponent_club_name': row.get('opponent_club_name', '').strip(),
                'age_group': row.get('age_group', '').strip(),
                'gender': row.get('gender', '').strip(),
                'state': row.get('state', '').strip(),
                'game_date': row.get('game_date', '').strip(),
                'home_away': row.get('home_away', '').strip(),
                'goals_for': row.get('goals_for', ''),
                'goals_against': row.get('goals_against', ''),
            }
            
            # Convert numeric fields
            try:
                if game['goals_for']:
                    game['goals_for'] = float(game['goals_for']) if '.' in str(game['goals_for']) else int(game['goals_for'])
                if game['goals_against']:
                    game['goals_against'] = float(game['goals_against']) if '.' in str(game['goals_against']) else int(game['goals_against'])
            except (ValueError, TypeError):
                pass
            
            # Validate
            is_valid, errors = validator.validate_game(game)
            
            if is_valid:
                stats['valid_records'] += 1
            else:
                stats['invalid_records'] += 1
                if len(stats['validation_errors']) < 10:
                    stats['validation_errors'].append({
                        'row': row_num,
                        'game': game,
                        'errors': errors
                    })
            
            # Collect statistics
            if game.get('team_name'):
                stats['unique_teams'].add(game['team_name'])
            if game.get('opponent_name'):
                stats['unique_opponents'].add(game['opponent_name'])
            if game.get('club_name'):
                stats['unique_clubs'].add(game['club_name'])
            if game.get('game_date'):
                try:
                    date_obj = parse_game_date(game['game_date'])
                    stats['dates'].append(datetime.combine(date_obj, datetime.min.time()))
                except (ValueError, TypeError):
                    pass
            if game.get('age_group'):
                stats['age_groups'].add(game['age_group'])
            if game.get('gender'):
                stats['genders'].add(game['gender'])
            if game.get('state'):
                stats['states'].add(game['state'])
    
    # Convert sets to counts
    stats['unique_teams'] = len(stats['unique_teams'])
    stats['unique_opponents'] = len(stats['unique_opponents'])
    stats['unique_clubs'] = len(stats['unique_clubs'])
    stats['age_groups'] = sorted(stats['age_groups'])
    stats['genders'] = sorted(stats['genders'])
    stats['states'] = sorted(stats['states'])
    
    # Calculate date range
    if stats['dates']:
        stats['date_range'] = (min(stats['dates']), max(stats['dates']))
    else:
        stats['date_range'] = None
    
    return stats


def check_batch_settings(batch_size: int, concurrency: int, file_size_mb: float) -> tuple[bool, bool, List[str]]:
    """Check if batch size and concurrency settings are appropriate"""
    warnings = []
    batch_ok = True
    concurrency_ok = True
    
    # Batch size checks
    if batch_size < 100:
        batch_ok = False
        warnings.append(f"Batch size {batch_size} is too small (recommended: 1000-5000)")
    elif batch_size > 10000:
        batch_ok = False
        warnings.append(f"Batch size {batch_size} is too large (recommended: 1000-5000)")
    elif file_size_mb > 100 and batch_size < 1000:
        warnings.append(f"For large files ({file_size_mb:.1f} MB), consider batch_size >= 2000")
    
    # Concurrency checks
    if concurrency < 1:
        concurrency_ok = False
        warnings.append(f"Concurrency {concurrency} is invalid (must be >= 1)")
    elif concurrency > 10:
        concurrency_ok = False
        warnings.append(f"Concurrency {concurrency} is too high (recommended: 2-8)")
    elif file_size_mb > 100 and concurrency < 2:
        warnings.append(f"For large files ({file_size_mb:.1f} MB), consider concurrency >= 4")
    
    return batch_ok, concurrency_ok, warnings


def check_quarantine_system() -> bool:
    """Check if quarantine system is ready"""
    try:
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not supabase_url or not supabase_key:
            return False
        
        supabase = create_client(supabase_url, supabase_key)
        
        # Check if quarantine tables exist
        try:
            # Try to query quarantine_games (should return empty or error if table doesn't exist)
            result = supabase.table('quarantine_games').select('*').limit(1).execute()
            return True
        except Exception:
            return False
    except Exception:
        return False


def verify_pre_import(file_path: str, batch_size: int = 2000, concurrency: int = 4, 
                     sample_size: int = 10000) -> VerificationResults:
    """Run comprehensive pre-import verification"""
    results = VerificationResults()
    file_path_obj = Path(file_path)
    
    console.print(Panel.fit(
        "[bold cyan]Pre-Import Verification[/bold cyan]\n"
        f"File: {file_path}\n"
        f"Batch Size: {batch_size}\n"
        f"Concurrency: {concurrency}",
        title="Verification Setup"
    ))
    
    # 1. Check file exists and format
    console.print("\n[bold]1. File Format Check[/bold]")
    file_ok, format_name, file_size = check_file_format(file_path_obj)
    results.file_exists = file_ok
    results.file_size_mb = file_size
    results.file_format_recognized = file_ok and format_name == "CSV"
    
    if file_ok:
        console.print(f"  ✅ File found: {file_size:.1f} MB")
        console.print(f"  ✅ Format recognized: {format_name}")
    else:
        console.print(f"  ❌ File check failed: {format_name}")
        return results
    
    # 2. Check schema mapping
    console.print("\n[bold]2. Schema Mapping Check[/bold]")
    schema_ok, missing, extra = check_schema_mapping(file_path_obj)
    results.schema_mapping_correct = schema_ok
    results.missing_columns = missing
    results.extra_columns = extra
    
    if schema_ok:
        console.print("  ✅ Schema mapping correct")
        if extra:
            console.print(f"  ⚠️  Extra columns (will be ignored): {', '.join(sorted(extra))}")
    else:
        console.print(f"  ❌ Missing required columns: {', '.join(sorted(missing))}")
        return results
    
    # 3. Analyze data statistics
    console.print(f"\n[bold]3. Data Statistics (sampling {sample_size:,} records)[/bold]")
    console.print("  [cyan]Analyzing data...[/cyan]")
    stats = analyze_data_statistics(file_path_obj, limit=sample_size)
    
    results.total_records = stats['total_records']
    results.valid_records = stats['valid_records']
    results.invalid_records = stats['invalid_records']
    results.unique_teams = stats['unique_teams']
    results.unique_opponents = stats['unique_opponents']
    results.unique_clubs = stats['unique_clubs']
    results.date_range = stats['date_range']
    results.age_groups = set(stats['age_groups'])
    results.genders = set(stats['genders'])
    results.states = set(stats['states'])
    results.sample_validation_errors = stats['validation_errors']
    
    # Display statistics
    table = Table(title="Data Statistics", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    
    table.add_row("Total Records (sample)", f"{stats['total_records']:,}")
    table.add_row("Valid Records", f"{stats['valid_records']:,} ({stats['valid_records']/stats['total_records']*100:.1f}%)")
    table.add_row("Invalid Records", f"{stats['invalid_records']:,} ({stats['invalid_records']/stats['total_records']*100:.1f}%)")
    table.add_row("Unique Teams", f"{stats['unique_teams']:,}")
    table.add_row("Unique Opponents", f"{stats['unique_opponents']:,}")
    table.add_row("Unique Clubs", f"{stats['unique_clubs']:,}")
    
    if stats['date_range']:
        min_date, max_date = stats['date_range']
        table.add_row("Date Range", f"{min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
    
    table.add_row("Age Groups", f"{len(stats['age_groups'])}: {', '.join(stats['age_groups'][:10])}")
    table.add_row("Genders", f"{len(stats['genders'])}: {', '.join(stats['genders'])}")
    table.add_row("States", f"{len(stats['states'])}: {', '.join(stats['states'][:10])}")
    
    console.print(table)
    
    # 4. Check batch settings
    console.print("\n[bold]4. Batch Size & Concurrency Check[/bold]")
    batch_ok, concurrency_ok, warnings = check_batch_settings(batch_size, concurrency, file_size)
    results.batch_size_ok = batch_ok
    results.concurrency_ok = concurrency_ok
    
    if batch_ok and concurrency_ok:
        console.print(f"  ✅ Batch size: {batch_size}")
        console.print(f"  ✅ Concurrency: {concurrency}")
    else:
        console.print(f"  ❌ Batch size: {batch_size} ({'OK' if batch_ok else 'NOT OK'})")
        console.print(f"  ❌ Concurrency: {concurrency} ({'OK' if concurrency_ok else 'NOT OK'})")
    
    if warnings:
        for warning in warnings:
            console.print(f"  ⚠️  {warning}")
    
    # 5. Check quarantine system
    console.print("\n[bold]5. Quarantine System Check[/bold]")
    quarantine_ok = check_quarantine_system()
    results.quarantine_system_ok = quarantine_ok
    
    if quarantine_ok:
        console.print("  ✅ Quarantine system ready")
    else:
        console.print("  ❌ Quarantine system not ready (check Supabase connection)")
    
    # 6. Show sample validation errors
    if stats['validation_errors']:
        console.print("\n[bold]6. Sample Validation Errors[/bold]")
        error_table = Table(title="Sample Validation Errors", box=box.ROUNDED)
        error_table.add_column("Row", style="cyan", justify="right")
        error_table.add_column("Team", style="yellow")
        error_table.add_column("Date", style="magenta")
        error_table.add_column("Errors", style="red")
        
        for error in stats['validation_errors'][:5]:
            game = error['game']
            error_table.add_row(
                str(error['row']),
                f"{game.get('team_name', 'N/A')[:30]}",
                game.get('game_date', 'N/A'),
                '; '.join(error['errors'][:2])
            )
        
        console.print(error_table)
    
    # Final summary
    console.print("\n" + "="*60)
    console.print(Panel.fit(
        f"[bold]Verification Summary[/bold]\n\n"
        f"File Format: {'✅' if results.file_format_recognized else '❌'}\n"
        f"Schema Mapping: {'✅' if results.schema_mapping_correct else '❌'}\n"
        f"Data Quality: {results.valid_records/results.total_records*100:.1f}% valid\n"
        f"Batch Settings: {'✅' if (batch_ok and concurrency_ok) else '❌'}\n"
        f"Quarantine System: {'✅' if quarantine_ok else '❌'}\n\n"
        f"[bold]Ready for Import: {'✅ YES' if all([results.file_format_recognized, results.schema_mapping_correct, batch_ok, concurrency_ok, quarantine_ok]) else '❌ NO - Fix issues above'}[/bold]",
        title="Final Status"
    ))
    
    return results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Comprehensive pre-import verification')
    parser.add_argument('file', help='CSV file to verify')
    parser.add_argument('--batch-size', type=int, default=2000, help='Batch size to verify (default: 2000)')
    parser.add_argument('--concurrency', type=int, default=4, help='Concurrency to verify (default: 4)')
    parser.add_argument('--sample-size', type=int, default=10000, help='Number of records to sample (default: 10000)')
    
    args = parser.parse_args()
    
    if not Path(args.file).exists():
        console.print(f"[red]Error: File not found: {args.file}[/red]")
        sys.exit(1)
    
    verify_pre_import(args.file, args.batch_size, args.concurrency, args.sample_size)

