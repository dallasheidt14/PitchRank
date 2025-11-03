"""Enhanced game import with validation and logging"""
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import uuid

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track

sys.path.append(str(Path(__file__).parent.parent))
from src.models.game_matcher import GameHistoryMatcher
from src.utils.validators import GameValidator
from src.etl.pipeline import ETLContext
from config.settings import ETL_CONFIG, BUILD_ID

console = Console()
load_dotenv()

class EnhancedGameImporter:
    """Import games with validation and build tracking"""
    
    def __init__(self):
        self.supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        self.matcher = GameHistoryMatcher(self.supabase)
        self.validator = GameValidator()
        self.build_id = BUILD_ID
        
    def import_games(self, filepath: Path):
        """Import games with full ETL tracking"""
        
        # Start build log
        self._log_build_start(filepath)
        
        try:
            # Read games
            games = self._read_games(filepath)
            console.print(f"[bold]Processing {len(games)} games[/bold]")
            
            stats = {
                'total': len(games),
                'valid': 0,
                'invalid': 0,
                'matched': 0,
                'partial': 0,
                'failed': 0,
                'duplicates': 0,
                'errors': []
            }
            
            # Process in batches
            batch_size = ETL_CONFIG['batch_size']
            
            for i in range(0, len(games), batch_size):
                batch = games[i:i + batch_size]
                console.print(f"\nProcessing batch {i//batch_size + 1}/{(len(games)-1)//batch_size + 1}")
                
                batch_stats = self._process_batch(batch)
                
                # Aggregate stats
                for key in ['valid', 'invalid', 'matched', 'partial', 'failed', 'duplicates']:
                    stats[key] += batch_stats[key]
                stats['errors'].extend(batch_stats['errors'])
                
            # Complete build log
            self._log_build_complete(stats)
            
            # Print summary
            self._print_summary(stats)
            
        except Exception as e:
            self._log_build_error(str(e))
            console.print(f"[red]Import failed: {e}[/red]")
            raise
            
    def _process_batch(self, games: List[Dict]) -> Dict:
        """Process a batch of games with validation and deduplication"""
        stats = {
            'valid': 0,
            'invalid': 0,
            'matched': 0,
            'partial': 0,
            'failed': 0,
            'duplicates': 0,
            'quarantined': 0,
            'errors': []
        }
        
        for game_data in track(games, description="Processing games"):
            # Stricter validation
            is_valid, error = self._validate_game_strict(game_data)
            
            if not is_valid:
                stats['invalid'] += 1
                stats['quarantined'] += 1
                self._quarantine_game(game_data, error)
                continue
                
            stats['valid'] += 1
            
            try:
                # Match and create game record (includes game_uid)
                game_record = self.matcher.match_game_history(game_data)
                game_record['build_id'] = self.build_id
                
                # Check for duplicate game_uid before inserting
                if game_record.get('game_uid'):
                    duplicate = self._check_duplicate_game_uid(game_record['game_uid'])
                    if duplicate:
                        stats['duplicates'] += 1
                        continue
                
                # Insert game
                result = self.supabase.table('games').insert(game_record).execute()
                
                # Update stats based on match status
                stats[game_record['match_status']] += 1
                
            except Exception as e:
                error_str = str(e).lower()
                if 'duplicate' in error_str or 'unique' in error_str:
                    stats['duplicates'] += 1
                else:
                    stats['errors'].append({
                        'game': game_data,
                        'error': str(e)
                    })
                    # Quarantine on unexpected errors
                    self._quarantine_game(game_data, f"Unexpected error: {str(e)}")
                    
        return stats
    
    def _validate_game_strict(self, game_data: Dict) -> tuple[bool, Optional[str]]:
        """Stricter validation for game data"""
        errors = []
        
        # Basic validation first
        is_valid, error = self.validator.validate(game_data)
        if not is_valid:
            errors.append(error)
        
        # Stricter state code validation
        if 'state_code' in game_data and game_data.get('state_code'):
            state_code = str(game_data['state_code']).strip()
            if len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
                errors.append(f"Invalid state code: {state_code} (must be exactly 2 uppercase letters)")
        
        # Stricter gender validation
        if 'gender' in game_data and game_data.get('gender'):
            gender = str(game_data['gender']).strip()
            if gender not in ['Male', 'Female']:
                errors.append(f"Invalid gender: {gender} (must be 'Male' or 'Female')")
        
        # Stricter age group validation
        if 'age_group' in game_data and game_data.get('age_group'):
            age_group = str(game_data['age_group']).strip().lower()
            valid_age_groups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18']
            if age_group not in valid_age_groups:
                errors.append(f"Invalid age group: {age_group} (must be one of {valid_age_groups})")
        
        if errors:
            return False, '; '.join(errors)
        
        return True, None
    
    def _check_duplicate_game_uid(self, game_uid: str) -> bool:
        """Check if game_uid already exists"""
        try:
            result = self.supabase.table('games').select('id').eq('game_uid', game_uid).limit(1).execute()
            return len(result.data) > 0
        except Exception:
            return False
    
    def _quarantine_game(self, game_data: Dict, error: str):
        """Save invalid game to quarantine"""
        try:
            self.supabase.table('quarantine_games').insert({
                'raw_data': game_data,
                'reason_code': 'validation_failed',
                'error_details': error
            }).execute()
        except Exception as e:
            console.print(f"[yellow]Warning: Could not quarantine game: {e}[/yellow]")
        
    def _log_build_start(self, filepath: Path):
        """Log build start"""
        self.supabase.table('build_logs').insert({
            'build_id': self.build_id,
            'stage': 'game_import',
            'parameters': {
                'filepath': str(filepath),
                'filesize': filepath.stat().st_size
            }
        }).execute()
        
    def _log_build_complete(self, stats: Dict):
        """Log build completion"""
        self.supabase.table('build_logs').update({
            'completed_at': datetime.now().isoformat(),
            'records_processed': stats['total'],
            'records_succeeded': stats['matched'] + stats['partial'],
            'records_failed': stats['failed'] + stats['invalid'],
            'errors': stats['errors'][:100]  # Limit stored errors
        }).eq('build_id', self.build_id).eq('stage', 'game_import').execute()
        
    def _log_validation_error(self, data: Dict, error: str):
        """Log validation error (deprecated - use quarantine instead)"""
        # Keep for backward compatibility, but prefer quarantine
        try:
            self.supabase.table('validation_errors').insert({
                'build_id': self.build_id,
                'record_type': 'game',
                'record_data': data,
                'error_type': 'validation',
                'error_message': error
            }).execute()
        except Exception:
            pass  # Ignore if table doesn't exist
        
    def _print_summary(self, stats: Dict):
        """Print import summary"""
        console.print("\n[bold]Import Summary:[/bold]")
        console.print(f"Build ID: {self.build_id}")
        console.print(f"Total games: {stats['total']}")
        console.print(f"Valid: [green]{stats['valid']}[/green]")
        console.print(f"Invalid: [red]{stats['invalid']}[/red]")
        console.print(f"Fully matched: [green]{stats['matched']}[/green]")
        console.print(f"Partially matched: [yellow]{stats['partial']}[/yellow]")
        console.print(f"Failed to match: [red]{stats['failed']}[/red]")
        console.print(f"Duplicates: [yellow]{stats['duplicates']}[/yellow]")
        console.print(f"Quarantined: [red]{stats.get('quarantined', 0)}[/red]")
        
        if stats['errors']:
            console.print(f"\n[red]Errors: {len(stats['errors'])}[/red]")
            
    def _read_games(self, filepath: Path) -> List[Dict]:
        """Read games from file"""
        with open(filepath, 'r') as f:
            if filepath.suffix == '.json':
                content = f.read()
                try:
                    # Try as single JSON
                    games = json.loads(content)
                    if isinstance(games, dict):
                        games = [games]
                except:
                    # Try as newline-delimited
                    games = []
                    for line in content.strip().split('\n'):
                        if line:
                            games.append(json.loads(line))
            else:
                raise ValueError(f"Unsupported file format: {filepath.suffix}")
                
        return games

if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[red]Usage: python import_game_history_enhanced.py <filepath>[/red]")
        sys.exit(1)
        
    importer = EnhancedGameImporter()
    importer.import_games(Path(sys.argv[1]))