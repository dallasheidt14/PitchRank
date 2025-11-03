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
        """Process a batch of games"""
        stats = {
            'valid': 0,
            'invalid': 0,
            'matched': 0,
            'partial': 0,
            'failed': 0,
            'duplicates': 0,
            'errors': []
        }
        
        for game_data in track(games, description="Processing games"):
            # Validate
            is_valid, error = self.validator.validate(game_data)
            
            if not is_valid:
                stats['invalid'] += 1
                self._log_validation_error(game_data, error)
                continue
                
            stats['valid'] += 1
            
            try:
                # Match and create game record
                game_record = self.matcher.match_game_history(game_data)
                game_record['build_id'] = self.build_id
                
                # Insert
                result = self.supabase.table('games').insert(game_record).execute()
                
                # Update stats based on match status
                stats[game_record['match_status']] += 1
                
            except Exception as e:
                if 'duplicate' in str(e).lower():
                    stats['duplicates'] += 1
                else:
                    stats['errors'].append({
                        'game': game_data,
                        'error': str(e)
                    })
                    
        return stats
        
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
        """Log validation error"""
        self.supabase.table('validation_errors').insert({
            'build_id': self.build_id,
            'record_type': 'game',
            'record_data': data,
            'error_type': 'validation',
            'error_message': error
        }).execute()
        
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