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
import shutil
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime, timedelta
import json
from collections import deque

sys.path.append(str(Path(__file__).parent.parent))
from src.etl.v53e import V53EConfig

# Make Rich tables render as wide as your terminal allows.
# You can override width by setting env var: RICH_WIDTH (e.g. 300).
_rich_width = int(os.getenv("RICH_WIDTH", "0") or "0")
if _rich_width <= 0:
    _rich_width = shutil.get_terminal_size(fallback=(300, 20)).columns
_rich_width = max(_rich_width, 300)
console = Console(width=_rich_width, force_terminal=True)

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


async def get_merged_team_ids(supabase, canonical_id: str) -> list:
    """Get all deprecated team IDs that were merged into this canonical team."""
    try:
        # team_merge_map stores edges: canonical_team_id -> deprecated_team_id.
        # Merges can be chained, so traverse recursively to collect all reachable IDs.
        visited = set()
        q = deque([canonical_id])
        visited.add(canonical_id)

        while q:
            current = q.popleft()
            result = supabase.table('team_merge_map').select('deprecated_team_id').eq(
                'canonical_team_id', current
            ).execute()
            deprecated_ids = [r['deprecated_team_id'] for r in (result.data or [])]
            for dep in deprecated_ids:
                if dep not in visited:
                    visited.add(dep)
                    q.append(dep)

        # Keep canonical first for readability in output/exports.
        rest = sorted([tid for tid in visited if tid != canonical_id])
        return [canonical_id] + rest
    except Exception as e:
        console.print(f"[yellow]Warning: Could not fetch merge map: {e}[/yellow]")
        return [canonical_id]


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

    reports_dir = Path('reports')
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    games_csv_path = reports_dir / f"audit_two_teams_sos_{run_ts}_games.csv"
    opponents_csv_path = reports_dir / f"audit_two_teams_sos_{run_ts}_opponents.csv"
    summary_json_path = reports_dir / f"audit_two_teams_sos_{run_ts}_summary.json"

    audit_summary: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cutoff_days": 365,
        "cutoff_date": cutoff_str,
        "team_ids": TEAM_IDS,
        "teams": [],
    }
    games_rows: list[dict] = []
    opponents_rows: list[dict] = []

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

        # 3) Fetch games (including games from deprecated/merged team IDs)
        all_team_ids = await get_merged_team_ids(supabase, team_id)
        if len(all_team_ids) > 1:
            console.print(f"[cyan]Found {len(all_team_ids) - 1} merged team ID(s) — including their games[/cyan]")

        games = []
        # Fetch games for all IDs (canonical + deprecated) in batches
        for tid in all_team_ids:
            home_games = supabase.table('games').select(
                'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
                'home_score, away_score'
            ).eq('home_team_master_id', tid).gte('game_date', cutoff_str).not_.is_(
                'home_score', 'null'
            ).not_.is_('away_score', 'null').execute()

            away_games = supabase.table('games').select(
                'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
                'home_score, away_score'
            ).eq('away_team_master_id', tid).gte('game_date', cutoff_str).not_.is_(
                'home_score', 'null'
            ).not_.is_('away_score', 'null').execute()

            for game in (home_games.data or []):
                # Resolve opponent to canonical ID if it's a deprecated team
                opp_id = game['away_team_master_id']
                games.append({
                    'date': game['game_date'],
                    'opp_id': opp_id,
                    'gf': game.get('home_score', 0),
                    'ga': game.get('away_score', 0),
                    'source_team_id': tid,
                })
            for game in (away_games.data or []):
                opp_id = game['home_team_master_id']
                games.append({
                    'date': game['game_date'],
                    'opp_id': opp_id,
                    'gf': game.get('away_score', 0),
                    'ga': game.get('home_score', 0),
                    'source_team_id': tid,
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

        team_audit: dict = {
            "team_id": team_id,
            "team_name": team_name,
            "club_name": team_info.get('club_name', '?'),
            "age_group": team_info.get('age_group', '?'),
            "gender": team_info.get('gender', '?'),
            "state_code": team_info.get('state_code', '?'),
            "merged_team_ids": all_team_ids,
            "games_total": int(len(g)),
            "games_in_sos_calc": int(len(g_sos)),
            "games_repeat_capped_out": int(len(g) - len(g_sos)),
            "unique_opponents": int(g['opp_id'].nunique()) if len(g) else 0,
            "manual_sos": float(manual_sos),
            "database_sos": None,
            "sos_difference": None,
            "opponents": [],
        }

        # Display game table sorted by date (most recent first)
        console.print(f"\n[bold]Game-by-Game SOS Breakdown ({len(g)} games, {g_sos.shape[0]} in SOS calc):[/bold]\n")

        # Compute an opponent column width that uses the terminal space.
        # This avoids rich's default truncation ("…") when names are long.
        other_cols_total = 3 + 10 + 5 + 7 + 6 + 14 + 10 + 14 + 6
        opponent_width = max(120, _rich_width - other_cols_total - 6)

        games_table = Table(
            show_header=True,
            header_style="bold cyan",
            show_lines=False,
            expand=True,
        )
        games_table.add_column("#", width=3)
        games_table.add_column("Date", width=10)
        games_table.add_column("Opponent", width=opponent_width, overflow="fold")
        games_table.add_column("Age", width=5)
        games_table.add_column("Score", justify="center", width=7)
        games_table.add_column("Result", justify="center", width=6)
        games_table.add_column("Opp Strength", justify="right", width=14)
        games_table.add_column("Weight", justify="right", width=10)
        games_table.add_column("SOS Contrib", justify="right", width=14)
        games_table.add_column("In SOS", justify="center", width=6)

        g_display = g.sort_values('date', ascending=False).reset_index(drop=True)

        for idx, row in g_display.iterrows():
            opp_info = opp_names.get(row['opp_id'], {'name': row['opp_id'][:12] + '...', 'age_group': '?'})
            # Do not truncate opponent name here; rely on the wide column + overflow folding.
            opp_name = opp_info['name']
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
            team_audit["database_sos"] = float(actual_sos)
            team_audit["sos_difference"] = float(diff)

        summary.add_row("", "")
        summary.add_row("Total Games:", str(len(g)))
        if 'source_team_id' in g.columns:
            canonical_count = (g['source_team_id'] == team_id).sum()
            merged_count = (g['source_team_id'] != team_id).sum()
            summary.add_row("  → From canonical ID:", str(canonical_count))
            summary.add_row("  → From merged IDs:", str(merged_count))
            team_audit["canonical_games_count"] = int(canonical_count)
            team_audit["merged_games_count"] = int(merged_count)
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

        # Export: per-game rows
        if total_weight > 0 and len(g_sos) > 0:
            # Per-game contribution share that sums to manual_sos across g_sos.
            g_sos = g_sos.assign(_game_contrib=(g_sos["opp_strength"] * g_sos["w_sos"]) / total_weight)
            contrib_by_idx = dict(zip(g_sos.index.tolist(), g_sos["_game_contrib"].tolist()))
        else:
            contrib_by_idx = {}

        for _, row in g.sort_values("date", ascending=False).iterrows():
            gf = int(row["gf"])
            ga = int(row["ga"])
            if gf > ga:
                result_plain = "W"
            elif gf < ga:
                result_plain = "L"
            else:
                result_plain = "D"

            sos_contrib_value = None
            if bool(row.get("in_sos")):
                sos_contrib_value = float(contrib_by_idx.get(row.name)) if row.name in contrib_by_idx else None

            games_rows.append({
                "team_id": team_id,
                "team_name": team_name,
                "team_age_group": team_info.get("age_group", "?"),
                "team_gender": team_info.get("gender", "?"),
                "team_state_code": team_info.get("state_code", "?"),
                "game_date": str(row["date"])[:10],
                "source_team_id": row.get("source_team_id"),
                "opp_id": row["opp_id"],
                "opp_name": opp_names.get(row["opp_id"], {}).get("name"),
                "score_for": gf,
                "score_against": ga,
                "result": result_plain,
                "repeat_rank": int(row["repeat_rank"]) if pd.notna(row.get("repeat_rank")) else None,
                "in_sos": bool(row.get("in_sos")),
                "opp_strength": float(row.get("opp_strength", cfg.UNRANKED_SOS_BASE)),
                "w_sos": float(row.get("w_sos", 0.0)),
                "sos_contrib": sos_contrib_value,
            })

        # Export: per-opponent rollup (only games included in SOS calc)
        if len(g_sos) > 0 and total_weight > 0:
            opp_rollup_df = (
                g_sos.assign(_game_contrib=(g_sos["opp_strength"] * g_sos["w_sos"]) / total_weight)
                .groupby("opp_id")
                .agg(
                    opp_strength=("opp_strength", "first"),
                    games_in_sos=("opp_id", "size"),
                    total_weight=("w_sos", "sum"),
                    sos_contrib_sum=("_game_contrib", "sum"),
                )
                .reset_index()
            )
            opp_rollup_df["opp_name"] = opp_rollup_df["opp_id"].map(
                lambda o: (opp_names.get(o, {}).get("name") or str(o))
            )
            opp_rollup_df["opp_age_group"] = opp_rollup_df["opp_id"].map(
                lambda o: opp_names.get(o, {}).get("age_group", "?")
            )
            opp_rollup_df["sos_contrib_share_of_manual_sos"] = opp_rollup_df["sos_contrib_sum"].apply(
                lambda x: (float(x) / float(manual_sos)) if manual_sos and manual_sos != 0 else None
            )
            opp_rollup_df = opp_rollup_df.sort_values("sos_contrib_sum", ascending=False)

            team_audit["opponents"] = opp_rollup_df.to_dict(orient="records")
            opponents_rows.extend(opp_rollup_df.assign(team_id=team_id).to_dict(orient="records"))

        audit_summary["teams"].append(team_audit)

    # Write export files once after processing both teams
    if games_rows:
        pd.DataFrame(games_rows).to_csv(games_csv_path, index=False, encoding="utf-8")
    if opponents_rows:
        pd.DataFrame(opponents_rows).to_csv(opponents_csv_path, index=False, encoding="utf-8")
    summary_json_path.write_text(json.dumps(audit_summary, indent=2), encoding="utf-8")
    console.print(f"\n[green]Exported audit files:[/green]\n- {games_csv_path}\n- {opponents_csv_path}\n- {summary_json_path}\n")


if __name__ == '__main__':
    asyncio.run(run_audit())
