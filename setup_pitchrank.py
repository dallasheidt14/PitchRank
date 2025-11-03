"""Master setup script for PitchRank - orchestrates complete setup"""
import sys
import subprocess
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

BASE_DIR = Path(__file__).parent
VENV_DIR = BASE_DIR / "venv"
ENV_FILE = BASE_DIR / ".env"
REQUIREMENTS_FILE = BASE_DIR / "requirements.txt"
PROJECT_REF = "pfkrhmprwxtghtpinrot"
SUPABASE_URL = "https://pfkrhmprwxtghtpinrot.supabase.co"


def check_python_version():
    """Check Python version is 3.8+"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        return True
    return False


def create_venv():
    """Create virtual environment"""
    if VENV_DIR.exists():
        console.print("[green]✅ Virtual environment already exists[/green]")
        return True
    
    console.print("[cyan]Creating virtual environment...[/cyan]")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
            capture_output=True
        )
        console.print("[green]✅ Virtual environment created[/green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Failed to create virtual environment: {e}[/red]")
        return False


def get_python_exe():
    """Get Python executable from venv"""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    else:
        return VENV_DIR / "bin" / "python"


def install_requirements():
    """Install requirements with progress"""
    python_exe = get_python_exe()
    
    if not python_exe.exists():
        console.print("[red]❌ Virtual environment Python not found[/red]")
        return False
    
    console.print("[cyan]Installing dependencies...[/cyan]")
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Installing packages...", total=None)
            
            result = subprocess.run(
                [str(python_exe), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
                capture_output=True,
                text=True
            )
            
            progress.update(task, completed=True)
        
        if result.returncode == 0:
            console.print("[green]✅ Dependencies installed[/green]")
            return True
        else:
            console.print(f"[red]❌ Failed to install dependencies: {result.stderr}[/red]")
            return False
    except Exception as e:
        console.print(f"[red]❌ Error installing dependencies: {e}[/red]")
        return False


def check_env_and_connection():
    """Check if .env exists and connection works"""
    if not ENV_FILE.exists():
        return False, "No .env file"
    
    try:
        from dotenv import load_dotenv
        from supabase import create_client
        
        load_dotenv(ENV_FILE)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            return False, "Missing credentials in .env"
        
        supabase = create_client(url, key)
        result = supabase.table('providers').select('count', count='exact').execute()
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)


def run_configure_env():
    """Run configure_env.py script"""
    console.print("\n[bold cyan]Step 2: Configuring Environment[/bold cyan]")
    
    python_exe = get_python_exe()
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    
    try:
        result = subprocess.run(
            [str(python_exe), str(BASE_DIR / "configure_env.py")],
            check=False
        )
        return result.returncode == 0
    except Exception as e:
        console.print(f"[red]❌ Error running configure_env: {e}[/red]")
        return False


def run_supabase_setup():
    """Run Supabase setup"""
    console.print("\n[bold cyan]Step 3: Setting up Supabase Database[/bold cyan]")
    
    python_exe = get_python_exe()
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    
    try:
        result = subprocess.run(
            [str(python_exe), str(BASE_DIR / "scripts" / "setup_supabase.py")],
            check=False
        )
        return result.returncode == 0
    except Exception as e:
        console.print(f"[red]❌ Error running Supabase setup: {e}[/red]")
        return False


def test_connection():
    """Test database connection"""
    console.print("\n[bold cyan]Step 4: Testing Connection[/bold cyan]")
    
    python_exe = get_python_exe()
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    
    try:
        result = subprocess.run(
            [str(python_exe), str(BASE_DIR / "test_connection.py")],
            check=False
        )
        return result.returncode == 0
    except Exception as e:
        console.print(f"[red]❌ Error testing connection: {e}[/red]")
        return False




def create_sample_data():
    """Create sample data"""
    console.print("\n[bold cyan]Step 5: Creating Sample Data[/bold cyan]")
    
    python_exe = get_python_exe()
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    
    try:
        result = subprocess.run(
            [str(python_exe), str(BASE_DIR / "scripts" / "create_sample_data.py"), "10", "5"],
            check=False
        )
        return result.returncode == 0
    except Exception as e:
        console.print(f"[yellow]⚠️  Could not create sample data: {e}[/yellow]")
        return False


def import_sample_team():
    """Import a sample team (placeholder - would need sample CSV)"""
    console.print("\n[cyan]Importing sample team...[/cyan]")
    console.print("[yellow]⚠️  Sample team import skipped (no sample CSV provided)[/yellow]")
    console.print("[cyan]To import teams later, use: python scripts/import_master_teams.py --path <csv> --provider <code>[/cyan]")
    return True


def show_summary():
    """Show setup summary"""
    console.print("\n" + "="*60)
    console.print(Panel.fit(
        "[bold green]✅ PitchRank Setup Complete![/bold green]",
        style="green"
    ))
    
    table = Table(title="Setup Summary")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    
    # Check components
    components = [
        ("Virtual Environment", VENV_DIR.exists()),
        ("Dependencies", (VENV_DIR / "lib" / "site-packages").exists() if VENV_DIR.exists() else False),
        ("Environment File", ENV_FILE.exists()),
        ("Database Connection", check_env_and_connection()[0]),
    ]
    
    for name, status in components:
        status_text = "[green]✅ Ready[/green]" if status else "[red]❌ Not Ready[/red]"
        table.add_row(name, status_text)
    
    console.print(table)
    
    console.print(f"\n[bold cyan]Supabase Dashboard:[/bold cyan]")
    console.print(f"  {SUPABASE_URL}/project/{PROJECT_REF}")
    
    console.print(f"\n[bold cyan]Next Steps:[/bold cyan]")
    console.print("  1. Run: python test_connection.py")
    console.print("  2. Create more teams: python scripts/create_sample_data.py")
    console.print("  3. Import teams: python scripts/import_master_teams.py --path <csv> --provider <code>")
    console.print("  4. Review setup: python setup_guide.py")


def main(reset: bool = False):
    """Main setup orchestrator"""
    console.print(Panel.fit(
        "[bold green]⚽ PitchRank Complete Setup[/bold green]",
        style="green"
    ))
    
    # Check Python version
    if not check_python_version():
        console.print("[red]❌ Python 3.8+ required. Current version: {}.{}[/red]".format(
            sys.version_info.major, sys.version_info.minor
        ))
        return False
    
    console.print(f"[green]✅ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}[/green]")
    
    # Step 1: Virtual Environment
    console.print("\n[bold cyan]Step 1: Setting up Virtual Environment[/bold cyan]")
    if reset and VENV_DIR.exists():
        console.print("[yellow]Removing existing virtual environment...[/yellow]")
        import shutil
        shutil.rmtree(VENV_DIR)
    
    if not create_venv():
        return False
    
    if not install_requirements():
        return False
    
    # Step 2: Environment Configuration
    env_ok, env_msg = check_env_and_connection()
    if env_ok and not reset:
        console.print(f"\n[green]✅ Environment configured: {env_msg}[/green]")
    else:
        if reset or not ENV_FILE.exists():
            if not run_configure_env():
                console.print("[yellow]⚠️  Environment configuration failed or skipped[/yellow]")
        else:
            console.print(f"[yellow]⚠️  Environment check: {env_msg}[/yellow]")
            if Confirm.ask("Reconfigure environment?"):
                run_configure_env()
    
    # Step 3: Supabase Setup
    if not Confirm.ask("\n[bold]Setup Supabase database?[/bold]", default=True):
        console.print("[yellow]Skipping Supabase setup[/yellow]")
    else:
        if not run_supabase_setup():
            console.print("[yellow]⚠️  Supabase setup may require manual steps[/yellow]")
    
    # Step 4: Test Connection
    if not test_connection():
        console.print("[yellow]⚠️  Connection test failed. Check your configuration.[/yellow]")
        return False
    
    # Step 5: Create sample data
    if Confirm.ask("\n[bold]Create sample data for testing?[/bold]", default=True):
        create_sample_data()
        import_sample_team()
    
    # Show summary
    show_summary()
    
    return True


if __name__ == "__main__":
    reset = "--reset" in sys.argv or "-r" in sys.argv
    
    if reset:
        console.print("[yellow]⚠️  Reset mode: Will reconfigure environment[/yellow]")
        if not Confirm.ask("Continue with reset?"):
            sys.exit(0)
    
    success = main(reset=reset)
    sys.exit(0 if success else 1)

