#!/usr/bin/env python3
"""
Team SOS Audit Script
====================
Interactive script to audit a team's Strength of Schedule (SOS) calculation.

Shows:
- Team's game history
- For each game: opponent, score, opponent strength, game weight
- Manual SOS calculation vs actual SOS from database
- Helps verify SOS is being calculated correctly

Usage:
    # Interactive mode
    python scripts/team_audit_sos.py

    # Non-interactive mode (for GitHub Actions)
    python scripts/team_audit_sos.py --team-name "Dallas Tigers"
    python scripts/team_audit_sos.py --team-id "abc-123-def"
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from supabase import create_client
import os
import argparse
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from src.etl.v53e import V53EConfig

console = Console()

# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


async def search_teams(supabase, search_term: str):
    """Search for teams by name"""
    try:
        # Search in teams table
        result = supabase.table('teams').select(
            'team_id_master, team_name'
        ).ilike('team_name', f'%{search_term}%').limit(20).execute()

        if result.data:
            # Normalize the response to use 'name' key for consistency
            return [{'team_id_master': t['team_id_master'], 'name': t['team_name']} for t in result.data]
        return []
    except Exception as e:
        console.print(f"[red]Error searching teams: {e}[/red]")
        return []


async def get_team_info(supabase, team_id: str):
    """Get team information including name and metadata"""
    try:
        # Get team info from teams table (single query)
        team_result = supabase.table('teams').select(
            'team_name, age_group, gender'
        ).eq('team_id_master', team_id).limit(1).execute()

        if team_result.data:
            return {
                'team_id': team_id,
                'name': team_result.data[0].get('team_name', 'Unknown'),
                'age_group': team_result.data[0].get('age_group', 'Unknown'),
                'gender': team_result.data[0].get('gender', 'Unknown')
            }
        return None
    except Exception as e:
        console.print(f"[yellow]Warning: Could not fetch team info: {e}[/yellow]")
        return None


async def get_team_games(supabase, team_id: str, lookback_days: int = 365):
    """Get all games for a specific team"""
    try:
        cutoff = datetime.now() - timedelta(days=lookback_days)
        cutoff_str = cutoff.strftime('%Y-%m-%d')

        # Get games where team is home
        home_games = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
            'home_score, away_score'
        ).eq('home_team_master_id', team_id).gte('game_date', cutoff_str).execute()

        # Get games where team is away
        away_games = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
            'home_score, away_score'
        ).eq('away_team_master_id', team_id).gte('game_date', cutoff_str).execute()

        games = []

        # Process home games
        for game in home_games.data:
            games.append({
                'game_id': game.get('game_uid') or game.get('id'),
                'date': game['game_date'],
                'team_id': team_id,
                'opp_id': game['away_team_master_id'],
                'gf': game.get('home_score'),
                'ga': game.get('away_score'),
                'location': 'Home'
            })

        # Process away games
        for game in away_games.data:
            games.append({
                'game_id': game.get('game_uid') or game.get('id'),
                'date': game['game_date'],
                'team_id': team_id,
                'opp_id': game['home_team_master_id'],
                'gf': game.get('away_score'),
                'ga': game.get('home_score'),
                'location': 'Away'
            })

        return pd.DataFrame(games).sort_values('date', ascending=False) if games else pd.DataFrame()
    except Exception as e:
        console.print(f"[red]Error fetching games: {e}[/red]")
        return pd.DataFrame()


async def get_opponent_names(supabase, opp_ids: list):
    """Get names for opponent IDs"""
    if not opp_ids:
        return {}

    try:
        # Batch fetch in chunks to avoid URI too long
        names = {}
        batch_size = 100

        for i in range(0, len(opp_ids), batch_size):
            batch = list(opp_ids)[i:i + batch_size]
            result = supabase.table('teams').select(
                'team_id_master, team_name'
            ).in_('team_id_master', batch).execute()

            if result.data:
                for row in result.data:
                    names[row['team_id_master']] = row['team_name']

        return names
    except Exception as e:
        console.print(f"[yellow]Warning: Could not fetch opponent names: {e}[/yellow]")
        return {}


def calculate_sos_manually(games_df: pd.DataFrame, strength_map: dict, cfg: V53EConfig, today: pd.Timestamp):
    """
    Manually calculate SOS using simplified v53e logic

    This approximates the SOS calculation from v53e.py for verification.
    Uses simplified recency weighting instead of full v53e complexity.
    """
    if games_df.empty:
        return None, None

    g = games_df.copy()

    # Calculate recency rank (1 = most recent)
    g = g.sort_values('date', ascending=False).reset_index(drop=True)
    g['rank_recency'] = range(1, len(g) + 1)

    # Simplified recency weighting: most recent games get higher weight
    # Approximates v53e Layer 3 logic
    n = len(g)
    k = min(cfg.RECENT_K, n)

    # Recent games (first k) get higher weight, older games get dampened
    weights = []
    for i in range(n):
        pos = i + 1
        if pos <= k:
            # Recent games: full weight
            w = 1.0
        elif cfg.DAMPEN_TAIL_START <= pos <= cfg.DAMPEN_TAIL_END:
            # Tail dampening
            t = (pos - cfg.DAMPEN_TAIL_START) / max(1, cfg.DAMPEN_TAIL_END - cfg.DAMPEN_TAIL_START)
            w = cfg.DAMPEN_TAIL_START_WEIGHT + (cfg.DAMPEN_TAIL_END_WEIGHT - cfg.DAMPEN_TAIL_START_WEIGHT) * t
        elif pos > cfg.DAMPEN_TAIL_END:
            # Very old games: minimum weight
            w = cfg.DAMPEN_TAIL_END_WEIGHT
        else:
            # Between recent and tail: full weight
            w = 1.0
        weights.append(w)

    g['w_game'] = weights

    # Calculate k_adapt (strength gap adjustment)
    # Approximates v53e Layer 5 logic
    g['gd'] = g['gf'] - g['ga']

    # Simplified adaptive K based on goal difference (proxy for strength gap)
    # In real v53e, this uses actual strength difference, but we approximate here
    g['k_adapt'] = cfg.ADAPTIVE_K_ALPHA * (1.0 + cfg.ADAPTIVE_K_BETA * (g['gd'].abs() / 10.0))

    # Calculate w_sos (SOS weight)
    g['w_sos'] = g['w_game'] * g['k_adapt']

    # Apply repeat cap: for each opponent, keep only top SOS_REPEAT_CAP games by weight
    g = g.sort_values(['opp_id', 'w_sos'], ascending=[True, False])
    g['repeat_rank'] = g.groupby('opp_id')['w_sos'].rank(ascending=False, method='first')
    g_sos = g[g['repeat_rank'] <= cfg.SOS_REPEAT_CAP].copy()

    # Map opponent strengths
    g_sos['opp_strength'] = g_sos['opp_id'].map(
        lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE)
    )

    # Calculate weighted average (Pass 1: Direct)
    total_weight = g_sos['w_sos'].sum()
    if total_weight <= 0:
        return None, g_sos

    sos_direct = (g_sos['opp_strength'] * g_sos['w_sos']).sum() / total_weight

    # For simplicity, we'll just return Pass 1 (direct) SOS
    # Full v53e does 3 passes with transitivity, but this is good enough for verification
    return sos_direct, g_sos


async def audit_team(supabase, team_id: str, team_name: str = None):
    """
    Run SOS audit for a specific team

    Args:
        supabase: Supabase client
        team_id: Team ID to audit
        team_name: Optional team name (will be fetched if not provided)
    """
    if not team_name:
        team_info = await get_team_info(supabase, team_id)
        team_name = team_info['name'] if team_info else 'Unknown'

    console.print(f"\n[bold green]Analyzing: {team_name}[/bold green]")
    console.print(f"[dim]Team ID: {team_id}[/dim]\n")

    # Get team info
    team_info = await get_team_info(supabase, team_id)
    if team_info:
        console.print(f"[cyan]Age Group:[/cyan] {team_info['age_group']}")
        console.print(f"[cyan]Gender:[/cyan] {team_info['gender']}\n")
    else:
        console.print("[yellow]Could not fetch team metadata[/yellow]\n")

    # Fetch current rankings from database (don't recompute!)
    console.print("[yellow]Loading rankings data from database...[/yellow]")

    try:
        # Fetch all rankings from rankings_full table
        rankings_result = supabase.table('rankings_full').select(
            'team_id, abs_strength, sos, sos_norm'
        ).execute()

        if not rankings_result.data:
            console.print("[red]No rankings found in database. Please run the rankings calculation first.[/red]")
            return

        teams_df = pd.DataFrame(rankings_result.data)

        # Create strength map (team_id -> abs_strength)
        strength_map = dict(zip(teams_df['team_id'], teams_df['abs_strength']))

        # Get this team's actual SOS from rankings
        team_ranking = teams_df[teams_df['team_id'] == team_id]
        actual_sos = team_ranking['sos'].values[0] if not team_ranking.empty and 'sos' in team_ranking.columns else None
        actual_sos_norm = team_ranking['sos_norm'].values[0] if not team_ranking.empty and 'sos_norm' in team_ranking.columns else None

        console.print(f"[green]✓ Loaded {len(teams_df):,} teams with strength values[/green]\n")

    except Exception as e:
        console.print(f"[red]Error loading rankings: {e}[/red]")
        import traceback
        traceback.print_exc()
        return

    # Get team's games
    console.print("[yellow]Fetching game history...[/yellow]")
    games_df = await get_team_games(supabase, team_id, lookback_days=365)

    if games_df.empty:
        console.print(f"[red]No games found for {team_name} in the last 365 days[/red]")
        return

    console.print(f"[green]✓ Found {len(games_df)} games[/green]\n")

    # Get opponent names
    opp_ids = games_df['opp_id'].unique().tolist()
    opp_names = await get_opponent_names(supabase, opp_ids)

    # Manual SOS calculation
    cfg = V53EConfig()
    today = pd.Timestamp.now()

    console.print("[yellow]Calculating SOS manually...[/yellow]")
    manual_sos, games_with_weights = calculate_sos_manually(games_df, strength_map, cfg, today)

    # Display SOS comparison
    sos_panel = Table.grid(padding=(0, 2))
    sos_panel.add_column(style="cyan", justify="right")
    sos_panel.add_column(style="white")

    sos_panel.add_row("Manual SOS (Pass 1):", f"{manual_sos:.6f}" if manual_sos else "N/A")
    sos_panel.add_row("Actual SOS (from DB):", f"{actual_sos:.6f}" if actual_sos is not None else "N/A")

    if manual_sos is not None and actual_sos is not None:
        diff = abs(manual_sos - actual_sos)
        color = "green" if diff < 0.01 else "yellow" if diff < 0.05 else "red"
        sos_panel.add_row("Difference:", f"[{color}]{diff:.6f}[/{color}]")

        if actual_sos_norm is not None:
            sos_panel.add_row("SOS Normalized:", f"{actual_sos_norm:.4f}")

    console.print(Panel(sos_panel, title="SOS Comparison", border_style="cyan"))
    console.print()

    # Display game details
    if games_with_weights is not None:
        console.print(Panel.fit(
            "[bold]Game History with SOS Contributions[/bold]\n"
            "[dim]Shows opponent strength, game weight, and whether included in SOS calc[/dim]",
            border_style="cyan"
        ))

        games_table = Table(show_header=True, header_style="bold cyan")
        games_table.add_column("Date", style="white", width=10)
        games_table.add_column("Opponent", style="white", width=30)
        games_table.add_column("Score", justify="center", width=10)
        games_table.add_column("Opp Str", justify="right", width=8)
        games_table.add_column("Weight", justify="right", width=8)
        games_table.add_column("Contrib", justify="right", width=8)
        games_table.add_column("In SOS?", justify="center", width=8)
        games_table.add_column("Loc", justify="center", width=6)

        # Sort by date (most recent first)
        games_display = games_with_weights.sort_values('date', ascending=False)

        total_weight = games_display['w_sos'].sum()

        for _, game in games_display.iterrows():
            opp_name = opp_names.get(game['opp_id'], 'Unknown')[:30]
            opp_strength = game['opp_strength']
            weight = game['w_sos']
            included = game['repeat_rank'] <= cfg.SOS_REPEAT_CAP

            # Calculate contribution to SOS
            contrib = (opp_strength * weight) / total_weight if total_weight > 0 else 0

            # Color code based on opponent strength
            if opp_strength >= 0.65:
                strength_color = "green"
            elif opp_strength >= 0.45:
                strength_color = "yellow"
            else:
                strength_color = "red"

            games_table.add_row(
                game['date'][:10],
                opp_name,
                f"{int(game['gf']) if pd.notna(game['gf']) else '?'}-{int(game['ga']) if pd.notna(game['ga']) else '?'}",
                f"[{strength_color}]{opp_strength:.4f}[/{strength_color}]",
                f"{weight:.4f}",
                f"{contrib:.6f}",
                "[green]✓[/green]" if included else "[red]✗[/red]",
                game.get('location', '?')
            )

        console.print(games_table)

        # Summary statistics
        console.print("\n[bold cyan]Summary Statistics:[/bold cyan]")
        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="cyan", justify="right")
        summary.add_column(style="white")

        summary.add_row("Total Games:", f"{len(games_df)}")
        summary.add_row("Games in SOS Calc:", f"{len(games_display[games_display['repeat_rank'] <= cfg.SOS_REPEAT_CAP])}")
        summary.add_row("Unique Opponents:", f"{games_display['opp_id'].nunique()}")
        summary.add_row("Avg Opponent Strength:", f"{games_display['opp_strength'].mean():.4f}")
        summary.add_row("Strongest Opponent:", f"{games_display['opp_strength'].max():.4f}")
        summary.add_row("Weakest Opponent:", f"{games_display['opp_strength'].min():.4f}")

        console.print(summary)

        # Config info
        console.print("\n[dim]SOS Configuration:[/dim]")
        config_info = Table.grid(padding=(0, 2))
        config_info.add_column(style="dim", justify="right")
        config_info.add_column(style="dim")

        config_info.add_row("Repeat Cap:", f"{cfg.SOS_REPEAT_CAP} games per opponent")
        config_info.add_row("Unranked Base:", f"{cfg.UNRANKED_SOS_BASE}")
        config_info.add_row("Iterations:", f"{cfg.SOS_ITERATIONS} passes")
        config_info.add_row("Transitivity Lambda:", f"{cfg.SOS_TRANSITIVITY_LAMBDA}")

        console.print(config_info)

        # Note about Pass 1 vs full calculation
        console.print("\n[yellow]Note:[/yellow] Manual SOS shows Pass 1 (Direct) only.")
        console.print("[dim]Actual SOS includes {0} total passes with transitivity.[/dim]".format(cfg.SOS_ITERATIONS))

        if manual_sos is not None and actual_sos is not None:
            diff = abs(manual_sos - actual_sos)
            if diff < 0.01:
                console.print("\n[green]✓ SOS calculation appears correct (difference < 0.01)[/green]")
            elif diff < 0.05:
                console.print("\n[yellow]⚠ Small difference detected. This is expected due to transitivity passes.[/yellow]")
            else:
                console.print("\n[red]✗ Large difference detected! SOS calculation may have issues.[/red]")


async def main():
    """Main entry point - handles both interactive and CLI modes"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Audit SOS calculations for a specific team',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python scripts/team_audit_sos.py

  # Non-interactive mode
  python scripts/team_audit_sos.py --team-name "Dallas Tigers"
  python scripts/team_audit_sos.py --team-id "abc-123-def-456"
        """
    )
    parser.add_argument('--team-name', type=str, help='Team name to search for')
    parser.add_argument('--team-id', type=str, help='Exact team ID to audit')
    parser.add_argument('--auto-select', action='store_true',
                        help='Auto-select first match (for non-interactive use)')

    args = parser.parse_args()

    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env[/red]")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)

    # Non-interactive mode: team ID provided
    if args.team_id:
        console.print(Panel.fit(
            "[bold cyan]Team SOS Audit Script[/bold cyan]\n"
            "[dim]Running in non-interactive mode[/dim]",
            border_style="cyan"
        ))
        await audit_team(supabase, args.team_id)
        return

    # Non-interactive mode: team name provided
    if args.team_name:
        console.print(Panel.fit(
            "[bold cyan]Team SOS Audit Script[/bold cyan]\n"
            "[dim]Running in non-interactive mode[/dim]",
            border_style="cyan"
        ))

        console.print(f"\n[yellow]Searching for teams matching '{args.team_name}'...[/yellow]")
        teams = await search_teams(supabase, args.team_name)

        if not teams:
            console.print(f"[red]No teams found matching '{args.team_name}'[/red]")
            sys.exit(1)

        # Auto-select if requested or only one match
        if args.auto_select or len(teams) == 1:
            selected_team = teams[0]
            console.print(f"[green]Selected: {selected_team['name']}[/green]")
        else:
            # Display options and take first match
            console.print(f"\n[green]Found {len(teams)} team(s), using first match:[/green]")
            selected_team = teams[0]
            console.print(f"[green]→ {selected_team['name']}[/green]")

        await audit_team(supabase, selected_team['team_id_master'], selected_team['name'])
        return

    # Interactive mode
    console.print(Panel.fit(
        "[bold cyan]Team SOS Audit Script[/bold cyan]\n\n"
        "This script helps you verify SOS calculations by showing:\n"
        "• Team's complete game history\n"
        "• Opponent strength for each game\n"
        "• Game weights and SOS contributions\n"
        "• Manual SOS calculation vs database value",
        border_style="cyan"
    ))

    # Get team search term
    search_term = Prompt.ask("\n[cyan]Enter team name to search[/cyan]")

    console.print(f"\n[yellow]Searching for teams matching '{search_term}'...[/yellow]")
    teams = await search_teams(supabase, search_term)

    if not teams:
        console.print(f"[red]No teams found matching '{search_term}'[/red]")
        return

    # Display search results
    console.print(f"\n[green]Found {len(teams)} team(s):[/green]")
    search_table = Table(show_header=True)
    search_table.add_column("#", style="cyan", width=4)
    search_table.add_column("Team Name", style="white")
    search_table.add_column("Team ID", style="dim")

    for i, team in enumerate(teams, 1):
        search_table.add_row(
            str(i),
            team['name'],
            str(team['team_id_master'])[:8] + "..."
        )

    console.print(search_table)

    # Select team
    if len(teams) == 1:
        selected_idx = 0
        console.print(f"\n[green]Auto-selecting only match: {teams[0]['name']}[/green]")
    else:
        selection = Prompt.ask(
            f"\n[cyan]Select team number (1-{len(teams)})[/cyan]",
            default="1"
        )
        try:
            selected_idx = int(selection) - 1
            if selected_idx < 0 or selected_idx >= len(teams):
                console.print("[red]Invalid selection[/red]")
                return
        except ValueError:
            console.print("[red]Invalid selection[/red]")
            return

    team_id = teams[selected_idx]['team_id_master']
    team_name = teams[selected_idx]['name']

    await audit_team(supabase, team_id, team_name)


if __name__ == '__main__':
    asyncio.run(main())
