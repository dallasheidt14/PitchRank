#!/usr/bin/env python3
"""
Helper script to switch between local and production Supabase environments
"""
import os
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()

def show_current_env():
    """Show current environment configuration"""
    env_file = Path(".env")
    local_env_file = Path(".env.local")
    
    use_local = os.getenv("USE_LOCAL_SUPABASE", "false").lower() == "true"
    supabase_url = os.getenv("SUPABASE_URL", "Not set")
    
    console.print("\n[bold]Current Environment Configuration[/bold]")
    console.print(f"  USE_LOCAL_SUPABASE: {use_local}")
    console.print(f"  SUPABASE_URL: {supabase_url}")
    
    if env_file.exists():
        console.print(f"\n[green]✓[/green] Production .env file exists")
    else:
        console.print(f"\n[yellow]⚠[/yellow] Production .env file not found")
    
    if local_env_file.exists():
        console.print(f"[green]✓[/green] Local .env.local file exists")
    else:
        console.print(f"[yellow]⚠[/yellow] Local .env.local file not found")
    
    if use_local:
        console.print("\n[cyan]Currently using: LOCAL Supabase[/cyan]")
    else:
        console.print("\n[cyan]Currently using: PRODUCTION Supabase[/cyan]")

def switch_to_local():
    """Switch to local Supabase"""
    local_env_file = Path(".env.local")
    
    if not local_env_file.exists():
        console.print("[red]Error: .env.local file not found![/red]")
        console.print("\nTo create it:")
        console.print("1. Run: supabase start")
        console.print("2. Copy the credentials from the output")
        console.print("3. Create .env.local with:")
        console.print("   USE_LOCAL_SUPABASE=true")
        console.print("   SUPABASE_URL=http://localhost:54321")
        console.print("   SUPABASE_KEY=<from_output>")
        console.print("   SUPABASE_SERVICE_ROLE_KEY=<from_output>")
        return False
    
    console.print("[green]Switching to LOCAL Supabase...[/green]")
    console.print("\nTo use local Supabase, set environment variable:")
    console.print("[bold]Windows PowerShell:[/bold]")
    console.print("  $env:USE_LOCAL_SUPABASE='true'")
    console.print("[bold]Windows CMD:[/bold]")
    console.print("  set USE_LOCAL_SUPABASE=true")
    console.print("[bold]Linux/Mac:[/bold]")
    console.print("  export USE_LOCAL_SUPABASE=true")
    console.print("\nOr load from .env.local:")
    console.print("  python -c \"from dotenv import load_dotenv; load_dotenv('.env.local')\"")
    return True

def switch_to_production():
    """Switch to production Supabase"""
    env_file = Path(".env")
    
    if not env_file.exists():
        console.print("[red]Error: .env file not found![/red]")
        console.print("\nRun: python configure_env.py")
        return False
    
    console.print("[green]Switching to PRODUCTION Supabase...[/green]")
    console.print("\nTo use production Supabase:")
    console.print("  Unset USE_LOCAL_SUPABASE or set it to 'false'")
    console.print("[bold]Windows PowerShell:[/bold]")
    console.print("  $env:USE_LOCAL_SUPABASE='false'")
    console.print("[bold]Windows CMD:[/bold]")
    console.print("  set USE_LOCAL_SUPABASE=false")
    console.print("[bold]Linux/Mac:[/bold]")
    console.print("  unset USE_LOCAL_SUPABASE")
    return True

def main():
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "local":
            switch_to_local()
        elif command == "production":
            switch_to_production()
        elif command == "status":
            show_current_env()
        else:
            console.print("[red]Unknown command. Use: local, production, or status[/red]")
    else:
        show_current_env()
        console.print("\n[bold]Usage:[/bold]")
        console.print("  python scripts/switch_env.py local       # Switch to local")
        console.print("  python scripts/switch_env.py production   # Switch to production")
        console.print("  python scripts/switch_env.py status      # Show current config")

if __name__ == "__main__":
    main()













