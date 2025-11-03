"""Interactive setup guide for PitchRank"""
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

console = Console()

BASE_DIR = Path(__file__).parent


def check_python_version():
    """Check if Python version is 3.8+"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        console.print(f"[green]✅ Python {version.major}.{version.minor}.{version.micro}[/green]")
        return True
    else:
        console.print(f"[red]❌ Python {version.major}.{version.minor} is too old. Need 3.8+[/red]")
        return False


def check_venv():
    """Check if virtual environment exists"""
    venv_paths = [
        BASE_DIR / "venv",
        BASE_DIR / ".venv",
        BASE_DIR / "env"
    ]
    
    for venv_path in venv_paths:
        if venv_path.exists():
            console.print(f"[green]✅ Virtual environment found at {venv_path}[/green]")
            return True
    
    console.print("[yellow]⚠️  Virtual environment not found[/yellow]")
    return False


def check_env_file():
    """Check if .env file exists"""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        console.print(f"[green]✅ .env file found[/green]")
        return True
    else:
        console.print("[yellow]⚠️  .env file not found[/yellow]")
        return False


def check_requirements():
    """Check if requirements are installed"""
    try:
        import pandas
        import supabase
        import rich
        console.print("[green]✅ Key dependencies installed[/green]")
        return True
    except ImportError:
        console.print("[yellow]⚠️  Dependencies not installed[/yellow]")
        return False


def check_database_connection():
    """Check if database connection works"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return False
    
    try:
        from dotenv import load_dotenv
        import os
        from supabase import create_client
        
        load_dotenv(env_file)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            return False
        
        supabase = create_client(url, key)
        result = supabase.table('providers').select('count', count='exact').execute()
        console.print("[green]✅ Database connection successful[/green]")
        return True
    except Exception:
        console.print("[yellow]⚠️  Database connection failed[/yellow]")
        return False


def show_setup_guide():
    """Interactive setup guide"""
    console.print(Panel.fit(
        "[bold green]⚽ PitchRank Setup Guide[/bold green]",
        style="green"
    ))
    
    console.print("\n[bold]Checking setup status...[/bold]\n")
    
    steps = [
        ("Python Version", check_python_version),
        ("Virtual Environment", check_venv),
        ("Environment File", check_env_file),
        ("Dependencies", check_requirements),
        ("Database Connection", check_database_connection),
    ]
    
    completed = []
    pending = []
    
    for name, check_func in steps:
        console.print(f"\n[cyan]{name}:[/cyan] ", end="")
        if check_func():
            completed.append(name)
        else:
            pending.append(name)
    
    # Summary
    console.print("\n" + "="*50)
    console.print(f"\n[green]✅ Completed: {len(completed)}/{len(steps)}[/green]")
    if pending:
        console.print(f"\n[yellow]⚠️  Pending: {len(pending)}[/yellow]")
        console.print("\n[bold]Next steps:[/bold]")
        for step in pending:
            console.print(f"  - {step}")
    
    # Provide guidance
    if len(pending) > 0:
        console.print("\n[cyan]Run setup_pitchrank.py to complete setup automatically[/cyan]")
        console.print("Or follow the instructions in SETUP_CHECKLIST.md")
    else:
        console.print("\n[bold green]✅ Setup complete! You're ready to go![/bold green]")
    
    return len(pending) == 0


if __name__ == "__main__":
    show_setup_guide()

