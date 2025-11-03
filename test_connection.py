"""Test PitchRank database connection"""
from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
load_dotenv()


def test_connection():
    """Test connection to PitchRank database"""
    
    console.print(Panel.fit("⚽ PitchRank Database Connection Test", style="bold green"))
    
    try:
        supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_KEY')
        )
        
        result = supabase.table('teams').select('count', count='exact').execute()
        console.print("✅ Successfully connected to Supabase!", style="green")
        
        table = Table(title="Database Status")
        table.add_column("Table", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Records", style="yellow")
        
        tables_to_test = [
            ('teams', 'Master team list'),
            ('games', 'Game history'),
            ('team_alias_map', 'Team aliases'),
            ('current_rankings', 'Current rankings'),
            ('providers', 'Data providers')
        ]
        
        for table_name, description in tables_to_test:
            try:
                result = supabase.table(table_name).select('count', count='exact').execute()
                table.add_row(f"{table_name}\n[dim]{description}[/dim]", "✓ Ready", str(result.count))
            except:
                table.add_row(f"{table_name}\n[dim]{description}[/dim]", "[red]✗ Error[/red]", "-")
        
        console.print(table)
        console.print("\n[bold green]PitchRank is ready to go! ⚽[/bold green]")
        
    except Exception as e:
        console.print(f"\n❌ Connection failed: {e}", style="bold red")
        console.print("\n[yellow]Please check:[/yellow]")
        console.print("1. Your .env file has the correct Supabase credentials")
        console.print("2. You've run: supabase db push")
        console.print("3. Your Supabase project is active")


if __name__ == "__main__":
    test_connection()

