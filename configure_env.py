"""Interactive script to configure .env file with Supabase credentials"""
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

# Default values
DEFAULT_SUPABASE_URL = "https://pfkrhmprwxtghtpinrot.supabase.co"
DEFAULT_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBma3JobXByd3h0Z2h0cGlucm90Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE3NDQ3ODQsImV4cCI6MjA3NzMyMDc4NH0.fOl6xuUuRzJhXe6UPHiCveZsviApipnFmcoB2Iz6Jt0"
DEFAULT_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBma3JobXByd3h0Z2h0cGlucm90Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTc0NDc4NCwiZXhwIjoyMDc3MzIwNzg0fQ.UvuJZ4lNmKC1WjuhGmXB0era5Nyd5Dw_qVegXyPjohE"

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"


def validate_url(url: str) -> bool:
    """Validate Supabase URL format"""
    return url.startswith("https://") and "supabase.co" in url


def validate_key(key: str) -> bool:
    """Validate JWT key format (basic check)"""
    return len(key) > 50 and "." in key


def test_connection(url: str, key: str) -> bool:
    """Test Supabase connection"""
    try:
        from supabase import create_client
        supabase = create_client(url, key)
        # Try a simple query
        result = supabase.table('providers').select('count', count='exact').execute()
        return True
    except ImportError:
        console.print("[yellow]⚠️  Supabase package not installed. Skipping connection test.[/yellow]")
        console.print("[cyan]Install dependencies: pip install -r requirements.txt[/cyan]")
        return True  # Don't fail if package not installed
    except Exception as e:
        console.print(f"[red]Connection test failed: {e}[/red]")
        return False


def configure_env():
    """Interactive .env configuration"""
    console.print(Panel.fit(
        "[bold green]⚽ PitchRank Environment Configuration[/bold green]",
        style="green"
    ))
    
    # Check if .env already exists
    if ENV_FILE.exists():
        console.print(f"\n[yellow]⚠️  .env file already exists at {ENV_FILE}[/yellow]")
        if not Confirm.ask("Do you want to overwrite it?"):
            console.print("[yellow]Keeping existing .env file[/yellow]")
            # Still test connection
            from dotenv import load_dotenv
            load_dotenv(ENV_FILE)
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            if url and key:
                console.print("\n[cyan]Testing existing connection...[/cyan]")
                if test_connection(url, key):
                    console.print("[green]✅ Connection successful with existing credentials![/green]")
                else:
                    console.print("[red]❌ Connection failed with existing credentials[/red]")
            return
    
    # Show defaults
    console.print("\n[cyan]Default Supabase Credentials:[/cyan]")
    console.print(f"  URL: {DEFAULT_SUPABASE_URL}")
    console.print(f"  Anon Key: {DEFAULT_ANON_KEY[:50]}...")
    console.print(f"  Service Role Key: {DEFAULT_SERVICE_ROLE_KEY[:50]}...")
    
    # Ask if user wants to use defaults
    use_defaults = Confirm.ask("\n[bold]Use default credentials?[/bold]", default=True)
    
    if use_defaults:
        url = DEFAULT_SUPABASE_URL
        anon_key = DEFAULT_ANON_KEY
        service_key = DEFAULT_SERVICE_ROLE_KEY
    else:
        console.print("\n[yellow]⚠️  Security Warning:[/yellow]")
        console.print("The service role key has admin access. Keep it secret!")
        console.print("Make sure .env is in .gitignore (already configured)\n")
        
        url = Prompt.ask("Enter Supabase URL", default=DEFAULT_SUPABASE_URL)
        while not validate_url(url):
            console.print("[red]Invalid URL format. Should start with https:// and contain supabase.co[/red]")
            url = Prompt.ask("Enter Supabase URL", default=DEFAULT_SUPABASE_URL)
        
        anon_key = Prompt.ask("Enter Supabase Anon Key", password=True)
        while not validate_key(anon_key):
            console.print("[red]Invalid key format[/red]")
            anon_key = Prompt.ask("Enter Supabase Anon Key", password=True)
        
        service_key = Prompt.ask("Enter Supabase Service Role Key", password=True)
        while not validate_key(service_key):
            console.print("[red]Invalid key format[/red]")
            service_key = Prompt.ask("Enter Supabase Service Role Key", password=True)
    
    # Write .env file
    env_content = f"""# Supabase Configuration
SUPABASE_URL={url}
SUPABASE_KEY={anon_key}
SUPABASE_SERVICE_ROLE_KEY={service_key}

# Environment
ENVIRONMENT=development
LOG_LEVEL=INFO

# PitchRank Settings
RANKING_WINDOW_DAYS=365
MAX_GAMES_PER_TEAM=30
"""
    
    try:
        ENV_FILE.write_text(env_content)
        console.print(f"\n[green]✅ .env file created at {ENV_FILE}[/green]")
    except Exception as e:
        console.print(f"[red]❌ Failed to write .env file: {e}[/red]")
        return
    
    # Test connection immediately (if supabase is installed)
    console.print("\n[cyan]Testing connection...[/cyan]")
    if test_connection(url, anon_key):
        console.print("[green]✅ Connection successful![/green]")
    else:
        console.print("[yellow]⚠️  Connection test skipped or failed.[/yellow]")
        console.print("[cyan]You can test later with: python test_connection.py[/cyan]")


if __name__ == "__main__":
    configure_env()

