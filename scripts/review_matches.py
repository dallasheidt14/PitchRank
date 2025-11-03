"""Manual review queue for team matches needing human decision"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

sys.path.append(str(Path(__file__).parent.parent))
from config.settings import PROVIDERS

console = Console()
load_dotenv()


class MatchReviewer:
    """Review and approve/reject pending team matches"""
    
    def __init__(self):
        self.supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        self.stats = {
            'total': 0,
            'approved': 0,
            'rejected': 0,
            'skipped': 0
        }
    
    def review_pending(self, limit: Optional[int] = None):
        """Review pending matches from team_alias_map"""
        console.print(Panel.fit(
            "[bold green]🔍 PitchRank Match Review Queue[/bold green]",
            style="green"
        ))
        
        # Get pending matches (confidence 0.75-0.9)
        query = self.supabase.table('team_alias_map').select(
            '*, teams(team_name, club_name, state_code)'
        ).eq('review_status', 'pending').gte(
            'match_confidence', 0.75
        ).lt('match_confidence', 0.9).order('match_confidence', desc=True)
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        
        if not result.data:
            console.print("\n[green]✅ No pending matches to review![/green]")
            return
        
        matches = result.data
        self.stats['total'] = len(matches)
        
        console.print(f"\n[cyan]Found {len(matches)} pending matches to review[/cyan]")
        console.print("[yellow]Matches with confidence 0.75-0.9 need manual review[/yellow]\n")
        
        for i, match in enumerate(matches, 1):
            self._review_match(match, i, len(matches))
        
        self._print_summary()
    
    def _review_match(self, match: Dict, current: int, total: int):
        """Review a single match"""
        console.print(f"\n[bold]Match {current}/{total}[/bold]")
        console.print("=" * 60)
        
        # Display match information
        table = Table(title="Match Information", show_header=True, header_style="bold cyan")
        table.add_column("Field", style="cyan", width=20)
        table.add_column("Value", width=40)
        
        table.add_row("Provider Team ID", match.get('provider_team_id', 'N/A'))
        table.add_row("Provider Team Name", match.get('team_name', 'N/A'))
        table.add_row("Age Group", match.get('age_group', 'N/A'))
        table.add_row("Gender", match.get('gender', 'N/A'))
        
        # Get matched team info (teams is a list or single object from Supabase)
        matched_team = match.get('teams', {})
        if isinstance(matched_team, list) and len(matched_team) > 0:
            matched_team = matched_team[0]
        elif not isinstance(matched_team, dict):
            matched_team = {}
        
        matched_team_name = matched_team.get('team_name', 'N/A') if matched_team else 'N/A'
        matched_club = matched_team.get('club_name', 'N/A') if matched_team else 'N/A'
        matched_state = matched_team.get('state_code', 'N/A') if matched_team else 'N/A'
        
        table.add_row("Matched Team", matched_team_name)
        table.add_row("Club", matched_club)
        table.add_row("State", matched_state)
        
        confidence = match.get('match_confidence', 0)
        confidence_color = 'green' if confidence >= 0.85 else 'yellow' if confidence >= 0.80 else 'red'
        table.add_row("Confidence", f"[{confidence_color}]{confidence:.2f}[/{confidence_color}]")
        table.add_row("Match Method", match.get('match_method', 'N/A'))
        
        console.print(table)
        
        # Get decision
        console.print("\n[bold]Decision:[/bold]")
        decision = Prompt.ask(
            "Approve, Reject, or Skip?",
            choices=['a', 'r', 's', 'approve', 'reject', 'skip'],
            default='a'
        ).lower()
        
        if decision in ['a', 'approve']:
            self._approve_match(match['id'])
            self.stats['approved'] += 1
            console.print("[green]✅ Match approved[/green]")
        elif decision in ['r', 'reject']:
            reason = Prompt.ask("Rejection reason (optional)", default="")
            self._reject_match(match['id'], reason)
            self.stats['rejected'] += 1
            console.print("[red]❌ Match rejected[/red]")
        else:
            self.stats['skipped'] += 1
            console.print("[yellow]⏭️  Match skipped[/yellow]")
    
    def _approve_match(self, alias_id: str):
        """Approve a match"""
        try:
            self.supabase.table('team_alias_map').update({
                'review_status': 'approved',
                'reviewed_by': os.getenv('USER', 'admin'),
                'reviewed_at': datetime.now().isoformat()
            }).eq('id', alias_id).execute()
        except Exception as e:
            console.print(f"[red]Error approving match: {e}[/red]")
    
    def _reject_match(self, alias_id: str, reason: str = ""):
        """Reject a match"""
        try:
            self.supabase.table('team_alias_map').update({
                'review_status': 'rejected',
                'reviewed_by': os.getenv('USER', 'admin'),
                'reviewed_at': datetime.now().isoformat()
            }).eq('id', alias_id).execute()
        except Exception as e:
            console.print(f"[red]Error rejecting match: {e}[/red]")
    
    def _print_summary(self):
        """Print review summary"""
        table = Table(title="Review Summary")
        table.add_column("Action", style="cyan")
        table.add_column("Count", style="yellow")
        
        table.add_row("Total reviewed", str(self.stats['total']))
        table.add_row("Approved", f"[green]{self.stats['approved']}[/green]")
        table.add_row("Rejected", f"[red]{self.stats['rejected']}[/red]")
        table.add_row("Skipped", f"[yellow]{self.stats['skipped']}[/yellow]")
        
        console.print("\n")
        console.print(table)
    
    def show_stats(self):
        """Show statistics about pending matches"""
        try:
            # Get counts by confidence level
            result = self.supabase.table('team_alias_map').select(
                'match_confidence, review_status'
            ).eq('review_status', 'pending').execute()
            
            if not result.data:
                console.print("[green]No pending matches[/green]")
                return
            
            high_conf = sum(1 for m in result.data if m.get('match_confidence', 0) >= 0.85)
            med_conf = sum(1 for m in result.data if 0.80 <= m.get('match_confidence', 0) < 0.85)
            low_conf = sum(1 for m in result.data if 0.75 <= m.get('match_confidence', 0) < 0.80)
            
            table = Table(title="Pending Matches by Confidence")
            table.add_column("Confidence Level", style="cyan")
            table.add_column("Count", style="yellow")
            
            table.add_row("High (0.85-0.89)", f"[green]{high_conf}[/green]")
            table.add_row("Medium (0.80-0.84)", f"[yellow]{med_conf}[/yellow]")
            table.add_row("Low (0.75-0.79)", f"[red]{low_conf}[/red]")
            table.add_row("Total", str(len(result.data)))
            
            console.print(table)
        except Exception as e:
            console.print(f"[red]Error getting stats: {e}[/red]")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Review pending team matches")
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of matches to review'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show statistics about pending matches'
    )
    
    args = parser.parse_args()
    
    reviewer = MatchReviewer()
    
    if args.stats:
        reviewer.show_stats()
    else:
        reviewer.review_pending(limit=args.limit)

