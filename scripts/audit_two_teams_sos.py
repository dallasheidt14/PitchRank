#!/usr/bin/env python3
"""
SOS Deep Dive — Audit Two Teams
================================
Runs the SOS audit for both teams requested in the rankings engine audit.

Usage:
    python scripts/audit_two_teams_sos.py

Outputs a detailed opponent-by-opponent SOS breakdown for each team:
- Each opponent's name, abs_strength, and contribution to SOS
- Which games were repeat-capped out
- Manual SOS calculation vs database SOS
- Sanity check summary
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))
from src.etl.v53e import V53EConfig

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

TEAM_IDS = [
    "ffa679df-b3e3-43cf-a330-d7dd6dea5be7",
    "691eb36d-95b2-4a08-bd59-13c1b0e830bb",
]


async def run_audit():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)
    cfg = V53EConfig()
    today = pd.Timestamp.now()
    cutoff = today - pd.Timedelta(days=365)
    cutoff_str = cutoff.strftime('%Y-%m-%d')

    # 1) Load strength map from rankings_full (all teams)
    console.print("[yellow]Loading rankings data from database...[/yellow]")
    all_rankings = []
    offset = 0
    page_size = 1000
    while True:
        result = supabase.table('rankings_full').select(
            'team_id, abs_strength, sos, sos_norm, sos_raw, powerscore_adj, powerscore_ml, '
            'power_score_final, off_norm, def_norm, games_played, status, age_group, gender'
        ).range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_rankings.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    rankings_df = pd.DataFrame(all_rankings)
    strength_map = dict(zip(rankings_df['team_id'], rankings_df['abs_strength']))
    console.print(f"[green]Loaded {len(rankings_df):,} teams with strength values[/green]\n")

    for team_id in TEAM_IDS:
        console.print(f"\n{'='*80}")

        # 2) Get team info
        team_result = supabase.table('teams').select(
            'team_name, club_name, age_group, gender, state_code'
        ).eq('team_id_master', team_id).limit(1).execute()

        team_info = team_result.data[0] if team_result.data else {}
        team_name = team_info.get('team_name', 'Unknown')

        console.print(Panel.fit(
            f"[bold cyan]{team_name}[/bold cyan]\n"
            f"ID: {team_id}\n"
            f"Club: {team_info.get('club_name', '?')} | "
            f"Age: {team_info.get('age_group', '?')} | "
            f"Gender: {team_info.get('gender', '?')} | "
            f"State: {team_info.get('state_code', '?')}",
            border_style="cyan"
        ))

        # Get this team's ranking data
        team_ranking = rankings_df[rankings_df['team_id'] == team_id]
        if not team_ranking.empty:
            tr = team_ranking.iloc[0]
            console.print(f"\n[bold]Current Rankings Data:[/bold]")
            stats = Table.grid(padding=(0, 2))
            stats.add_column(style="cyan", justify="right", width=25)
            stats.add_column(style="white")
            stats.add_row("Status:", str(tr.get('status', '?')))
            stats.add_row("Games Played:", str(tr.get('games_played', '?')))
            stats.add_row("OFF Norm:", f"{tr.get('off_norm', 0):.4f}")
            stats.add_row("DEF Norm:", f"{tr.get('def_norm', 0):.4f}")
            stats.add_row("SOS (raw):", f"{tr.get('sos', 0):.6f}")
            stats.add_row("SOS Norm:", f"{tr.get('sos_norm', 0):.4f}")
            stats.add_row("SOS Raw (post-shrinkage):", f"{tr.get('sos_raw', 0):.6f}" if tr.get('sos_raw') else "N/A")
            stats.add_row("PowerScore (adj):", f"{tr.get('powerscore_adj', 0):.4f}")
            stats.add_row("PowerScore (ML):", f"{tr.get('powerscore_ml', 0):.4f}")
            stats.add_row("Power Score Final:", f"{tr.get('power_score_final', 0):.4f}")
            console.print(stats)
        else:
            console.print("[yellow]Team not found in rankings_full table[/yellow]")

        # 3) Fetch games
        home_games = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
            'home_score, away_score'
        ).eq('home_team_master_id', team_id).gte('game_date', cutoff_str).not_.is_(
            'home_score', 'null'
        ).not_.is_('away_score', 'null').execute()

        away_games = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
            'home_score, away_score'
        ).eq('away_team_master_id', team_id).gte('game_date', cutoff_str).not_.is_(
            'home_score', 'null'
        ).not_.is_('away_score', 'null').execute()

        games = []
        for game in (home_games.data or []):
            games.append({
                'date': game['game_date'],
                'opp_id': game['away_team_master_id'],
                'gf': game.get('home_score', 0),
                'ga': game.get('away_score', 0),
            })
        for game in (away_games.data or []):
            games.append({
                'date': game['game_date'],
                'opp_id': game['home_team_master_id'],
                'gf': game.get('away_score', 0),
                'ga': game.get('home_score', 0),
            })

        if not games:
            console.print("[red]No games found in 365-day window[/red]")
            continue

        g = pd.DataFrame(games).sort_values('date', ascending=False).reset_index(drop=True)
        g['rank_recency'] = range(1, len(g) + 1)

        # Recency weights (exponential decay matching v53e)
        n = len(g)
        raw_weights = [np.exp(-cfg.RECENCY_DECAY_RATE * i) for i in range(n)]
        total_w = sum(raw_weights)
        g['w_base'] = [w / total_w for w in raw_weights]

        # Adaptive K (simplified — uses strength gap)
        def adaptive_k(row):
            team_str = strength_map.get(team_id, 0.5)
            opp_str = strength_map.get(row['opp_id'], cfg.UNRANKED_SOS_BASE)
            gap = abs(team_str - opp_str)
            return cfg.ADAPTIVE_K_ALPHA * (1.0 + cfg.ADAPTIVE_K_BETA * gap)

        g['k_adapt'] = g.apply(adaptive_k, axis=1)
        g['w_sos'] = g['w_base'] * g['k_adapt']

        # Repeat cap
        g = g.sort_values(['opp_id', 'w_sos'], ascending=[True, False])
        g['repeat_rank'] = g.groupby('opp_id')['w_sos'].rank(ascending=False, method='first')
        g['in_sos'] = g['repeat_rank'] <= cfg.SOS_REPEAT_CAP

        # Map opponent strengths
        g['opp_strength'] = g['opp_id'].map(
            lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE)
        )

        # Get opponent names
        opp_ids = g['opp_id'].unique().tolist()
        opp_names = {}
        for i in range(0, len(opp_ids), 100):
            batch = opp_ids[i:i+100]
            result = supabase.table('teams').select(
                'team_id_master, team_name, age_group'
            ).in_('team_id_master', batch).execute()
            if result.data:
                for row in result.data:
                    opp_names[row['team_id_master']] = {
                        'name': row['team_name'],
                        'age_group': row.get('age_group', '?'),
                    }

        # Calculate manual SOS
        g_sos = g[g['in_sos']].copy()
        total_weight = g_sos['w_sos'].sum()
        manual_sos = (g_sos['opp_strength'] * g_sos['w_sos']).sum() / total_weight if total_weight > 0 else 0

        # Display game table sorted by date (most recent first)
        console.print(f"\n[bold]Game-by-Game SOS Breakdown ({len(g)} games, {g_sos.shape[0]} in SOS calc):[/bold]\n")

        games_table = Table(show_header=True, header_style="bold cyan", show_lines=False)
        games_table.add_column("#", width=3)
        games_table.add_column("Date", width=10)
        games_table.add_column("Opponent", width=38)
        games_table.add_column("Age", width=5)
        games_table.add_column("Score", justify="center", width=7)
        games_table.add_column("Result", justify="center", width=6)
        games_table.add_column("Opp Strength", justify="right", width=12)
        games_table.add_column("Weight", justify="right", width=8)
        games_table.add_column("SOS Contrib", justify="right", width=11)
        games_table.add_column("In SOS", justify="center", width=6)

        g_display = g.sort_values('date', ascending=False).reset_index(drop=True)

        for idx, row in g_display.iterrows():
            opp_info = opp_names.get(row['opp_id'], {'name': row['opp_id'][:12] + '...', 'age_group': '?'})
            opp_name = opp_info['name'][:38]
            opp_age = opp_info.get('age_group', '?')

            gf, ga = int(row['gf']), int(row['ga'])
            if gf > ga:
                result_str = "[green]W[/green]"
            elif gf < ga:
                result_str = "[red]L[/red]"
            else:
                result_str = "[yellow]D[/yellow]"

            opp_str = row['opp_strength']
            if opp_str >= 0.50:
                str_color = "green"
            elif opp_str >= 0.30:
                str_color = "yellow"
            else:
                str_color = "red"

            # SOS contribution (only for games included in SOS calc)
            if row['in_sos'] and total_weight > 0:
                contrib = (opp_str * row['w_sos']) / total_weight
                contrib_str = f"{contrib:.6f}"
            else:
                contrib_str = "[dim]—[/dim]"

            in_sos_str = "[green]✓[/green]" if row['in_sos'] else "[red]✗ (cap)[/red]"

            games_table.add_row(
                str(idx + 1),
                str(row['date'])[:10],
                opp_name,
                str(opp_age),
                f"{gf}-{ga}",
                result_str,
                f"[{str_color}]{opp_str:.6f}[/{str_color}]",
                f"{row['w_sos']:.5f}",
                contrib_str,
                in_sos_str,
            )

        console.print(games_table)

        # Summary
        console.print(f"\n[bold]SOS Summary:[/bold]")
        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="cyan", justify="right", width=30)
        summary.add_column(style="white")

        summary.add_row("Manual SOS (Pass 1 direct):", f"{manual_sos:.6f}")
        actual_sos = team_ranking.iloc[0].get('sos', None) if not team_ranking.empty else None
        if actual_sos is not None:
            summary.add_row("Database SOS:", f"{float(actual_sos):.6f}")
            diff = abs(manual_sos - float(actual_sos))
            color = "green" if diff < 0.01 else "yellow" if diff < 0.03 else "red"
            summary.add_row("Difference:", f"[{color}]{diff:.6f}[/{color}]")
            summary.add_row("", f"[dim](Diff expected due to Power-SOS co-calc, SCF, PageRank dampening)[/dim]")

        summary.add_row("", "")
        summary.add_row("Total Games:", str(len(g)))
        summary.add_row("Games in SOS Calc:", str(len(g_sos)))
        summary.add_row("Games Repeat-Capped:", str(len(g) - len(g_sos)))
        summary.add_row("Unique Opponents:", str(g['opp_id'].nunique()))

        # Opponent strength distribution
        opp_strengths = g_sos['opp_strength']
        summary.add_row("", "")
        summary.add_row("Avg Opp Strength:", f"{opp_strengths.mean():.6f}")
        summary.add_row("Max Opp Strength:", f"{opp_strengths.max():.6f}")
        summary.add_row("Min Opp Strength:", f"{opp_strengths.min():.6f}")
        summary.add_row("Median Opp Strength:", f"{opp_strengths.median():.6f}")

        # Count strong/weak opponents
        strong = (opp_strengths >= 0.40).sum()
        mid = ((opp_strengths >= 0.20) & (opp_strengths < 0.40)).sum()
        weak = (opp_strengths < 0.20).sum()
        unranked = (g_sos['opp_strength'] == cfg.UNRANKED_SOS_BASE).sum()
        summary.add_row("", "")
        summary.add_row("Strong Opps (≥0.40):", str(strong))
        summary.add_row("Mid Opps (0.20-0.40):", str(mid))
        summary.add_row("Weak Opps (<0.20):", str(weak))
        summary.add_row("Unranked Opps (0.35 default):", str(unranked))

        console.print(summary)
        console.print()


if __name__ == '__main__':
    asyncio.run(run_audit())
