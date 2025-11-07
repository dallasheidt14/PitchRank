#!/usr/bin/env python3
"""
Apply state rankings view migrations to Supabase database
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.panel import Panel

sys.path.append(str(Path(__file__).parent.parent))

console = Console()
load_dotenv()

# Migration files in order
MIGRATIONS = [
    'supabase/migrations/20241106000001_fix_state_rankings_view.sql',
    'supabase/migrations/20241106000002_update_rls_and_views.sql',
    'supabase/migrations/20241106000003_deprecate_state_rankings_function.sql',
    'supabase/migrations/20241106000004_deprecate_state_rank_column.sql',
]


def apply_migration(supabase_client, migration_file: str) -> bool:
    """Apply a single migration file"""
    migration_path = Path(__file__).parent.parent / migration_file
    
    if not migration_path.exists():
        console.print(f"[red]Error: Migration file not found: {migration_file}[/red]")
        return False
    
    console.print(f"[cyan]Applying: {migration_file}[/cyan]")
    
    # Read migration SQL
    with open(migration_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    try:
        # Execute SQL via Supabase RPC (using a custom function) or direct SQL execution
        # Note: Supabase Python client doesn't have direct SQL execution
        # We'll use the REST API with the SQL endpoint if available, or provide instructions
        
        # For now, we'll use the Supabase REST API to execute SQL
        # This requires using the PostgREST endpoint directly
        response = supabase_client.rpc('exec_sql', {'sql': sql}).execute()
        
        console.print(f"[green]✅ Successfully applied: {migration_file}[/green]")
        return True
        
    except Exception as e:
        # If RPC doesn't exist, we'll need to use a different approach
        error_str = str(e).lower()
        
        if 'exec_sql' in error_str or 'function' in error_str:
            # RPC function doesn't exist - we need to use Supabase Dashboard or provide SQL
            console.print(f"[yellow]⚠️  Cannot execute SQL directly via Python client[/yellow]")
            console.print(f"[yellow]Please apply this migration manually via Supabase Dashboard SQL Editor[/yellow]")
            console.print(f"\n[bold]SQL to execute:[/bold]")
            console.print(Panel(sql, title=migration_file, border_style="blue"))
            return False
        else:
            console.print(f"[red]Error applying {migration_file}: {e}[/red]")
            return False


def main():
    """Apply all migrations"""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    console.print("[bold green]Applying State Rankings Migrations[/bold green]\n")
    
    # Try to apply migrations
    # Since Supabase Python client doesn't support direct SQL execution,
    # we'll provide the SQL for manual application
    console.print("[yellow]Note: Supabase Python client doesn't support direct SQL execution.[/yellow]")
    console.print("[yellow]Please apply these migrations via Supabase Dashboard SQL Editor.[/yellow]\n")
    
    all_sql = []
    for migration_file in MIGRATIONS:
        migration_path = Path(__file__).parent.parent / migration_file
        if migration_path.exists():
            with open(migration_path, 'r', encoding='utf-8') as f:
                sql = f.read()
            all_sql.append(f"-- {migration_file}\n{sql}\n")
            console.print(f"[green]✅ Loaded: {migration_file}[/green]")
        else:
            console.print(f"[red]❌ Not found: {migration_file}[/red]")
    
    if all_sql:
        console.print("\n[bold]Combined SQL for Supabase Dashboard:[/bold]")
        combined_sql = "\n".join(all_sql)
        console.print(Panel(combined_sql, title="Copy this SQL to Supabase Dashboard SQL Editor", border_style="green"))
        
        # Also save to a file for easy copy-paste
        output_file = Path(__file__).parent.parent / 'supabase' / 'migrations' / 'combined_state_rankings_migrations.sql'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(combined_sql)
        console.print(f"\n[cyan]Also saved to: {output_file}[/cyan]")


if __name__ == '__main__':
    main()

