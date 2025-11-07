#!/usr/bin/env python3
"""Check breakdown of approved matches by match_method"""
import sys
from pathlib import Path
from collections import Counter

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
load_dotenv()

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Get total count first
count_result = supabase.table('team_alias_map').select('match_method', count='exact').eq('review_status', 'approved').limit(1).execute()
total = count_result.count if hasattr(count_result, 'count') else 0

if total == 0:
    console.print("[yellow]No approved matches found[/yellow]")
    sys.exit(0)

# Get all approved matches (paginated)
methods = Counter()
offset = 0
batch_size = 1000

console.print(f"[cyan]Fetching {total:,} approved matches...[/cyan]")

while offset < total:
    batch = supabase.table('team_alias_map').select('match_method').eq(
        'review_status', 'approved'
    ).range(offset, offset + batch_size - 1).execute()
    
    if not batch.data:
        break
    
    for row in batch.data:
        method = row.get('match_method', 'unknown')
        methods[method] += 1
    
    offset += len(batch.data)
    
    if len(batch.data) < batch_size:
        break

# Display results
console.print(f"\n[bold cyan]Approved Matches Breakdown[/bold cyan]\n")
console.print(f"Total approved matches: {total:,}\n")

table = Table(title="Match Method Distribution", box=box.ROUNDED)
table.add_column("Match Method", style="cyan")
table.add_column("Count", style="green", justify="right")
table.add_column("Percentage", style="yellow", justify="right")
table.add_column("Description", style="magenta")

# Match method descriptions
descriptions = {
    'direct_id': 'Direct ID match (from master team import)',
    'fuzzy_auto': 'Fuzzy match auto-approved (confidence ≥0.9)',
    'fuzzy_review': 'Fuzzy match manually reviewed',
    'provider_id': 'Legacy provider ID match',
    'csv_import': 'From CSV import',
    'manual': 'Manually created',
    'unknown': 'Unknown method'
}

for method, count in methods.most_common():
    percentage = (count / total * 100) if total > 0 else 0
    desc = descriptions.get(method, 'Other')
    table.add_row(
        method,
        f"{count:,}",
        f"{percentage:.1f}%",
        desc
    )

console.print(table)

# Summary
direct_id_count = methods.get('direct_id', 0)
fuzzy_auto_count = methods.get('fuzzy_auto', 0)
fuzzy_review_count = methods.get('fuzzy_review', 0)
other_count = total - direct_id_count - fuzzy_auto_count - fuzzy_review_count

console.print(f"\n[bold]Summary:[/bold]")
console.print(f"  [green]Direct ID matches:[/green] {direct_id_count:,} ({direct_id_count/total*100:.1f}%)")
console.print(f"  [cyan]Fuzzy auto-approved:[/cyan] {fuzzy_auto_count:,} ({fuzzy_auto_count/total*100:.1f}%)")
console.print(f"  [yellow]Fuzzy reviewed:[/yellow] {fuzzy_review_count:,} ({fuzzy_review_count/total*100:.1f}%)")
if other_count > 0:
    console.print(f"  [magenta]Other methods:[/magenta] {other_count:,} ({other_count/total*100:.1f}%)")

