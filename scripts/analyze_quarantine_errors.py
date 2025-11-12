#!/usr/bin/env python3
"""
Analyze validation errors in quarantined games to understand what issues exist

This script:
1. Queries quarantine_games table
2. Analyzes error_details to categorize error types
3. Provides statistics on most common validation failures
"""
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List
import re

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)


def categorize_error(error_details: str) -> str:
    """Categorize error into common types"""
    if not error_details:
        return "Unknown"
    
    error_lower = error_details.lower()
    
    # Date-related errors
    if any(keyword in error_lower for keyword in ['date format', 'invalid date', 'unrecognized date', 'date']):
        return "Date Format"
    
    # Missing field errors
    if any(keyword in error_lower for keyword in ['missing required field', 'missing field', 'required field']):
        if 'team' in error_lower:
            return "Missing Team Field"
        elif 'opponent' in error_lower:
            return "Missing Opponent Field"
        elif 'date' in error_lower:
            return "Missing Date Field"
        elif 'score' in error_lower or 'goal' in error_lower:
            return "Missing Score Field"
        else:
            return "Missing Required Field"
    
    # Empty/null field errors
    if any(keyword in error_lower for keyword in ['empty', 'null', 'cannot be empty']):
        return "Empty/Null Field"
    
    # Score validation errors
    if any(keyword in error_lower for keyword in ['score', 'goal', 'invalid score', 'score format']):
        return "Score Validation"
    
    # Team ID errors
    if any(keyword in error_lower for keyword in ['team_id', 'team id', 'opponent_id', 'opponent id']):
        if 'empty' in error_lower or 'null' in error_lower:
            return "Empty Team ID"
        else:
            return "Team ID Validation"
    
    # Format validation errors
    if any(keyword in error_lower for keyword in ['format', 'invalid format', 'invalid']):
        return "Format Validation"
    
    # Duplicate errors
    if any(keyword in error_lower for keyword in ['duplicate', 'already exist']):
        return "Duplicate"
    
    # Age group errors
    if 'age_group' in error_lower or 'age group' in error_lower:
        return "Age Group Validation"
    
    # Gender errors
    if 'gender' in error_lower:
        return "Gender Validation"
    
    # State code errors
    if 'state' in error_lower and ('code' in error_lower or 'invalid' in error_lower):
        return "State Code Validation"
    
    # Game UID errors
    if 'game_uid' in error_lower:
        return "Game UID Validation"
    
    return "Other"


def analyze_quarantine_errors(limit: int = None, reason_code: str = None):
    """Analyze errors in quarantined games"""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Get total count
    count_query = supabase.table('quarantine_games').select('id', count='exact')
    if reason_code:
        count_query = count_query.eq('reason_code', reason_code)
    count_result = count_query.limit(1).execute()
    total_count = count_result.count if hasattr(count_result, 'count') else 0
    
    console.print(f"[cyan]Found {total_count:,} quarantined games[/cyan]\n")
    
    # Fetch games with error details
    query = supabase.table('quarantine_games').select('reason_code, error_details')
    if reason_code:
        query = query.eq('reason_code', reason_code)
    
    if limit:
        query = query.limit(limit)
    else:
        # Sample up to 10k for analysis if no limit specified
        query = query.limit(10000)
    
    result = query.execute()
    
    if not result.data:
        console.print("[yellow]No quarantined games found[/yellow]")
        return
    
    # Analyze errors
    error_categories = Counter()
    reason_codes = Counter()
    sample_errors = defaultdict(list)  # category -> list of sample error messages
    
    for game in result.data:
        reason = game.get('reason_code', 'unknown')
        error_details = game.get('error_details', '')
        
        reason_codes[reason] += 1
        
        # Categorize error
        category = categorize_error(error_details)
        error_categories[category] += 1
        
        # Store sample errors (up to 3 per category)
        if len(sample_errors[category]) < 3:
            sample_errors[category].append(error_details[:200])
    
    # Display results
    console.print(Panel.fit(
        f"[bold cyan]Quarantine Error Analysis[/bold cyan]\n\n"
        f"Total Games Analyzed: {len(result.data):,}\n"
        f"{'Sample Size' if limit else 'Sampled 10,000'} of {total_count:,} total",
        title="Summary"
    ))
    
    # Reason codes table
    console.print("\n[bold]Reason Codes:[/bold]")
    reason_table = Table(title="Reason Code Distribution", box=box.ROUNDED)
    reason_table.add_column("Reason Code", style="cyan")
    reason_table.add_column("Count", style="magenta", justify="right")
    reason_table.add_column("Percentage", style="yellow", justify="right")
    
    for reason, count in reason_codes.most_common():
        percentage = (count / len(result.data) * 100) if len(result.data) > 0 else 0
        reason_table.add_row(reason, f"{count:,}", f"{percentage:.1f}%")
    
    console.print(reason_table)
    
    # Error categories table
    console.print("\n[bold]Error Categories:[/bold]")
    error_table = Table(title="Error Category Distribution", box=box.ROUNDED)
    error_table.add_column("Category", style="cyan")
    error_table.add_column("Count", style="magenta", justify="right")
    error_table.add_column("Percentage", style="yellow", justify="right")
    error_table.add_column("Sample Error", style="dim")
    
    for category, count in error_categories.most_common():
        percentage = (count / len(result.data) * 100) if len(result.data) > 0 else 0
        sample = sample_errors[category][0] if sample_errors[category] else "N/A"
        error_table.add_row(
            category,
            f"{count:,}",
            f"{percentage:.1f}%",
            sample[:80] + "..." if len(sample) > 80 else sample
        )
    
    console.print(error_table)
    
    # Detailed samples for top categories
    console.print("\n[bold]Sample Errors by Category:[/bold]")
    for category, count in error_categories.most_common(5):
        if sample_errors[category]:
            console.print(f"\n[cyan]{category}[/cyan] ({count:,} occurrences):")
            for i, sample in enumerate(sample_errors[category][:3], 1):
                console.print(f"  {i}. {sample[:150]}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Analyze validation errors in quarantined games'
    )
    parser.add_argument(
        '--reason-code',
        type=str,
        default=None,
        help='Filter by reason code (default: all)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of games to analyze (default: 10,000 sample)'
    )
    
    args = parser.parse_args()
    
    analyze_quarantine_errors(limit=args.limit, reason_code=args.reason_code)


if __name__ == '__main__':
    main()

