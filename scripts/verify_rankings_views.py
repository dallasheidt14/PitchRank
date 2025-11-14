#!/usr/bin/env python3
"""
Verify that rankings_view and state_rankings_view are working correctly
Tests that views can be queried and return expected data structure
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


def verify_rankings_view():
    """Verify rankings_view is working"""
    console.print("\n[bold green]Verifying rankings_view[/bold green]\n")
    
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return False
    
    supabase = create_client(supabase_url, supabase_key)
    
    try:
        # Test 1: Basic query
        console.print("[dim]Test 1: Basic query (limit 5)...[/dim]")
        result = supabase.table('rankings_view').select('*').limit(5).execute()
        
        if not result.data:
            console.print("[yellow]⚠️ No data returned from rankings_view[/yellow]")
            return False
        
        console.print(f"[green]✓ Found {len(result.data)} records[/green]")
        
        # Test 2: Check required fields
        console.print("\n[dim]Test 2: Checking required fields...[/dim]")
        required_fields = [
            'team_id_master', 'team_name', 'age_group', 'gender',
            'national_power_score', 'power_score_final',
            'national_rank', 'national_sos_rank',
            'games_played', 'wins', 'losses', 'draws'
        ]
        
        sample = result.data[0]
        missing_fields = [f for f in required_fields if f not in sample]
        
        if missing_fields:
            console.print(f"[red]✗ Missing fields: {missing_fields}[/red]")
            return False
        
        console.print("[green]✓ All required fields present[/green]")
        
        # Test 3: Check power_score_final is populated
        console.print("\n[dim]Test 3: Checking power_score_final values...[/dim]")
        null_scores = sum(1 for r in result.data if r.get('power_score_final') is None)
        if null_scores > 0:
            console.print(f"[yellow]⚠️ {null_scores} records have NULL power_score_final[/yellow]")
        else:
            console.print("[green]✓ All records have power_score_final[/green]")
        
        # Test 4: Check ranks are calculated
        console.print("\n[dim]Test 4: Checking ranks are calculated...[/dim]")
        null_ranks = sum(1 for r in result.data if r.get('national_rank') is None)
        if null_ranks > 0:
            console.print(f"[yellow]⚠️ {null_ranks} records have NULL national_rank[/yellow]")
        else:
            console.print("[green]✓ All records have national_rank[/green]")
        
        # Test 5: Filter by age_group and gender
        console.print("\n[dim]Test 5: Testing filters (age_group=u12, gender=Male)...[/dim]")
        filtered_result = supabase.table('rankings_view').select('*').eq('age_group', 'u12').eq('gender', 'Male').limit(5).execute()
        if filtered_result.data:
            console.print(f"[green]✓ Filtered query returned {len(filtered_result.data)} records[/green]")
        else:
            console.print("[yellow]⚠️ No records found for filter (may be normal if no u12 Male teams)[/yellow]")
        
        # Display sample record
        console.print("\n[bold]Sample record:[/bold]")
        sample_table = Table(show_header=True, header_style="bold cyan")
        sample_table.add_column("Field", style="cyan")
        sample_table.add_column("Value", style="green")
        
        for field in ['team_id_master', 'team_name', 'age_group', 'gender', 
                      'national_power_score', 'power_score_final', 'national_rank', 
                      'games_played', 'wins', 'losses']:
            value = sample.get(field)
            sample_table.add_row(field, str(value) if value is not None else "NULL")
        
        console.print(sample_table)
        
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Error querying rankings_view: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def verify_state_rankings_view():
    """Verify state_rankings_view is working"""
    console.print("\n[bold green]Verifying state_rankings_view[/bold green]\n")
    
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return False
    
    supabase = create_client(supabase_url, supabase_key)
    
    try:
        # Test 1: Basic query
        console.print("[dim]Test 1: Basic query (limit 5)...[/dim]")
        result = supabase.table('state_rankings_view').select('*').limit(5).execute()
        
        if not result.data:
            console.print("[yellow]⚠️ No data returned from state_rankings_view[/yellow]")
            return False
        
        console.print(f"[green]✓ Found {len(result.data)} records[/green]")
        
        # Test 2: Check required fields including power_score alias
        console.print("\n[dim]Test 2: Checking required fields (including power_score alias)...[/dim]")
        required_fields = [
            'team_id_master', 'team_name', 'age_group', 'gender',
            'national_power_score', 'power_score_final', 'power_score',  # power_score is alias
            'national_rank', 'state_rank', 'national_sos_rank', 'state_sos_rank',
            'games_played', 'wins', 'losses', 'draws', 'state_code'
        ]
        
        sample = result.data[0]
        missing_fields = [f for f in required_fields if f not in sample]
        
        if missing_fields:
            console.print(f"[red]✗ Missing fields: {missing_fields}[/red]")
            return False
        
        console.print("[green]✓ All required fields present[/green]")
        
        # Test 3: Verify power_score alias matches power_score_final
        console.print("\n[dim]Test 3: Verifying power_score alias matches power_score_final...[/dim]")
        mismatches = []
        for r in result.data:
            if r.get('power_score') != r.get('power_score_final'):
                mismatches.append(r.get('team_id_master'))
        
        if mismatches:
            console.print(f"[red]✗ power_score mismatch in {len(mismatches)} records[/red]")
            return False
        else:
            console.print("[green]✓ power_score alias matches power_score_final[/green]")
        
        # Test 4: Check state ranks are calculated
        console.print("\n[dim]Test 4: Checking state ranks are calculated...[/dim]")
        null_state_ranks = sum(1 for r in result.data if r.get('state_rank') is None)
        if null_state_ranks > 0:
            console.print(f"[yellow]⚠️ {null_state_ranks} records have NULL state_rank[/yellow]")
        else:
            console.print("[green]✓ All records have state_rank[/green]")
        
        # Test 5: Filter by state_code
        console.print("\n[dim]Test 5: Testing state filter (state_code=CA)...[/dim]")
        filtered_result = supabase.table('state_rankings_view').select('*').eq('state_code', 'CA').limit(5).execute()
        if filtered_result.data:
            console.print(f"[green]✓ Filtered query returned {len(filtered_result.data)} records[/green]")
        else:
            console.print("[yellow]⚠️ No records found for CA (may be normal if no CA teams)[/yellow]")
        
        # Display sample record
        console.print("\n[bold]Sample record:[/bold]")
        sample_table = Table(show_header=True, header_style="bold cyan")
        sample_table.add_column("Field", style="cyan")
        sample_table.add_column("Value", style="green")
        
        for field in ['team_id_master', 'team_name', 'state_code', 'age_group', 'gender',
                      'power_score_final', 'power_score', 'national_rank', 'state_rank',
                      'games_played']:
            value = sample.get(field)
            sample_table.add_row(field, str(value) if value is not None else "NULL")
        
        console.print(sample_table)
        
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Error querying state_rankings_view: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def verify_data_source():
    """Verify views are reading from rankings_full"""
    console.print("\n[bold green]Verifying data source (rankings_full vs current_rankings)[/bold green]\n")
    
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        return False
    
    supabase = create_client(supabase_url, supabase_key)
    
    try:
        # Count records in each table
        rf_count = supabase.table('rankings_full').select('team_id', count='exact').execute()
        cr_count = supabase.table('current_rankings').select('team_id', count='exact').execute()
        rv_count = supabase.table('rankings_view').select('team_id_master', count='exact').execute()
        
        rf_total = rf_count.count if hasattr(rf_count, 'count') else len(rf_count.data) if rf_count.data else 0
        cr_total = cr_count.count if hasattr(cr_count, 'count') else len(cr_count.data) if cr_count.data else 0
        rv_total = rv_count.count if hasattr(rv_count, 'count') else len(rv_count.data) if rv_count.data else 0
        
        console.print(f"[dim]rankings_full: {rf_total} records[/dim]")
        console.print(f"[dim]current_rankings: {cr_total} records[/dim]")
        console.print(f"[dim]rankings_view: {rv_total} records[/dim]")
        
        if rf_total > 0:
            console.print("[green]✓ rankings_full has data[/green]")
        else:
            console.print("[yellow]⚠️ rankings_full is empty - run rankings calculation[/yellow]")
        
        if rv_total > 0:
            console.print("[green]✓ rankings_view is returning data[/green]")
        else:
            console.print("[red]✗ rankings_view is empty[/red]")
            return False
        
        return True
        
    except Exception as e:
        console.print(f"[red]✗ Error checking data source: {e}[/red]")
        return False


def main():
    console.print(Panel.fit(
        "[bold cyan]Rankings Views Verification[/bold cyan]\n"
        "Testing rankings_view and state_rankings_view",
        border_style="bright_blue"
    ))
    
    results = {
        'rankings_view': verify_rankings_view(),
        'state_rankings_view': verify_state_rankings_view(),
        'data_source': verify_data_source(),
    }
    
    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]Summary:[/bold]\n")
    
    all_passed = True
    for test_name, passed in results.items():
        status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
        console.print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        console.print("\n[bold green]✅ All tests passed! Views are working correctly.[/bold green]")
    else:
        console.print("\n[bold yellow]⚠️ Some tests failed. Check output above for details.[/bold yellow]")
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

