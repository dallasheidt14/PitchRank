"""Simple CLI for reviewing team aliases"""
from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from datetime import datetime

load_dotenv()
console = Console()

class AliasReviewer:
    def __init__(self):
        self.supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        
    def review_pending(self):
        """Review pending aliases"""
        while True:
            # Get next alias to review
            result = self.supabase.table('aliases_pending_review').select('*').limit(1).execute()
            
            if not result.data:
                console.print("[green]No more aliases to review![/green]")
                break
                
            alias = result.data[0]
            
            # Display
            console.clear()
            table = Table(title="Alias Review")
            table.add_column("Field", style="cyan")
            table.add_column("Value")
            
            table.add_row("Provider Team ID", alias['provider_team_id'])
            table.add_row("Matched Team", f"{alias['team_name']} ({alias['age_group']} {alias['gender']})")
            table.add_row("Club", alias['club_name'] or "N/A")
            table.add_row("Confidence", f"[{'green' if alias['match_confidence'] > 0.8 else 'yellow'}]{alias['match_confidence']:.2f}[/]")
            table.add_row("Method", alias['match_method'])
            
            console.print(table)
            
            # Get decision
            if Confirm.ask("Approve this match?"):
                self._approve_alias(alias['id'])
                console.print("[green]✓ Approved[/green]")
            else:
                if Confirm.ask("Is this a new team (not in master list)?"):
                    self._mark_new_team(alias['id'])
                    console.print("[yellow]→ Marked as new team[/yellow]")
                else:
                    self._reject_alias(alias['id'])
                    console.print("[red]✗ Rejected[/red]")
                    
            if not Confirm.ask("\nReview another?"):
                break
                
    def _approve_alias(self, alias_id: str):
        """Approve an alias"""
        self.supabase.table('team_alias_map').update({
            'review_status': 'approved',
            'reviewed_by': 'admin',
            'reviewed_at': datetime.now().isoformat()
        }).eq('id', alias_id).execute()
        
    def _reject_alias(self, alias_id: str):
        """Reject an alias"""
        self.supabase.table('team_alias_map').update({
            'review_status': 'rejected',
            'reviewed_by': 'admin',
            'reviewed_at': datetime.now().isoformat()
        }).eq('id', alias_id).execute()
        
    def _mark_new_team(self, alias_id: str):
        """Mark as new team needing addition to master list"""
        self.supabase.table('team_alias_map').update({
            'review_status': 'new_team',
            'reviewed_by': 'admin',
            'reviewed_at': datetime.now().isoformat()
        }).eq('id', alias_id).execute()

if __name__ == "__main__":
    reviewer = AliasReviewer()
    reviewer.review_pending()