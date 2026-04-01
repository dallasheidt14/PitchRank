"""Helper script for Supabase CLI setup and database migration"""

import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

console = Console()

PROJECT_REF = "pfkrhmprwxtghtpinrot"
BASE_DIR = Path(__file__).parent.parent


def check_supabase_cli() -> bool:
    """Check if Supabase CLI is installed"""
    try:
        result = subprocess.run(["supabase", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.strip()
            console.print(f"[green]✅ Supabase CLI found: {version}[/green]")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return False


def install_cli_instructions():
    """Show instructions for installing Supabase CLI"""
    console.print("\n[bold red]Supabase CLI is not installed![/bold red]")
    console.print("\n[cyan]Installation instructions:[/cyan]")
    console.print("\n  [bold]Windows (using Scoop):[/bold]")
    console.print("    scoop install supabase")
    console.print("\n  [bold]Mac (using Homebrew):[/bold]")
    console.print("    brew install supabase/tap/supabase")
    console.print("\n  [bold]Linux:[/bold]")
    console.print("    Visit: https://supabase.com/docs/guides/cli/getting-started")
    console.print("\n  [bold]Or use npm:[/bold]")
    console.print("    npm install -g supabase")
    console.print("\nAfter installation, run this script again.")


def run_supabase_init():
    """Run supabase init"""
    console.print("\n[cyan]Initializing Supabase...[/cyan]")
    try:
        result = subprocess.run(["supabase", "init"], cwd=BASE_DIR, capture_output=True, text=True)

        if result.returncode == 0:
            console.print("[green]✅ Supabase initialized[/green]")
            return True
        else:
            # Check if already initialized
            if "already initialized" in result.stderr.lower():
                console.print("[yellow]⚠️  Supabase already initialized[/yellow]")
                return True
            else:
                console.print(f"[red]❌ Init failed: {result.stderr}[/red]")
                return False
    except Exception as e:
        console.print(f"[red]❌ Error running supabase init: {e}[/red]")
        return False


def run_supabase_link():
    """Run supabase link with project reference"""
    console.print(f"\n[cyan]Linking to Supabase project: {PROJECT_REF}...[/cyan]")

    try:
        result = subprocess.run(
            ["supabase", "link", "--project-ref", PROJECT_REF], cwd=BASE_DIR, capture_output=True, text=True
        )

        if result.returncode == 0:
            console.print("[green]✅ Successfully linked to Supabase project[/green]")
            return True
        else:
            # Check if already linked
            if "already linked" in result.stderr.lower():
                console.print("[yellow]⚠️  Already linked to project[/yellow]")
                return True
            else:
                console.print("[yellow]⚠️  Link may require authentication[/yellow]")
                console.print(f"[yellow]Error: {result.stderr}[/yellow]")
                console.print("\n[cyan]You may need to:[/cyan]")
                console.print("  1. Login: supabase login")
                console.print("  2. Link manually: supabase link --project-ref pfkrhmprwxtghtpinrot")
                return False
    except Exception as e:
        console.print(f"[red]❌ Error linking project: {e}[/red]")
        return False


def run_supabase_db_push():
    """Run supabase db push to apply migrations"""
    console.print("\n[cyan]Applying database migrations...[/cyan]")

    try:
        result = subprocess.run(["supabase", "db", "push"], cwd=BASE_DIR, capture_output=True, text=True)

        if result.returncode == 0:
            console.print("[green]✅ Database migrations applied successfully![/green]")
            return True
        else:
            console.print(f"[red]❌ Migration failed: {result.stderr}[/red]")
            console.print("\n[yellow]Alternative: Apply migration manually via Supabase dashboard[/yellow]")
            console.print("  1. Go to SQL Editor in Supabase dashboard")
            console.print("  2. Run: supabase/migrations/20240101000000_initial_schema.sql")
            return False
    except Exception as e:
        console.print(f"[red]❌ Error running db push: {e}[/red]")
        return False


def setup_supabase():
    """Complete Supabase setup process"""
    console.print(Panel.fit("[bold green]🗄️  Supabase Database Setup[/bold green]", style="green"))

    # Check CLI installation
    if not check_supabase_cli():
        install_cli_instructions()
        if not Confirm.ask("\nHave you installed Supabase CLI? (will check again)"):
            console.print("[yellow]Please install Supabase CLI and run this script again[/yellow]")
            return False

        if not check_supabase_cli():
            console.print("[red]❌ Supabase CLI still not found. Please install it first.[/red]")
            return False

    # Initialize Supabase
    if not run_supabase_init():
        return False

    # Link project
    if not run_supabase_link():
        console.print("\n[yellow]⚠️  Project linking may require manual steps[/yellow]")
        if Confirm.ask("Continue with database push anyway?"):
            pass  # Continue
        else:
            return False

    # Push migrations
    if not run_supabase_db_push():
        return False

    console.print("\n[bold green]✅ Supabase setup complete![/bold green]")
    return True


if __name__ == "__main__":
    success = setup_supabase()
    sys.exit(0 if success else 1)
