#!/usr/bin/env python3
"""
Explainy Commentary - Explain why teams moved in rankings

Run: python3 scripts/explainy_commentary.py [--team <name>] [--top-movers] [--limit 5]
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

DATABASE_URL = os.getenv('DATABASE_URL')


def get_connection():
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    # Set statement timeout to 30 seconds to prevent hanging
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '30s'")
    conn.commit()
    return conn


def get_team_movement_analysis(cur, team_id, days=7):
    """Analyze why a team moved in rankings."""
    analysis = {'team_id': team_id}
    
    # Get rank history
    cur.execute('''
        SELECT snapshot_date, rank_in_cohort, power_score_final, rank_in_state
        FROM ranking_history
        WHERE team_id = %s
        ORDER BY snapshot_date DESC
        LIMIT 10
    ''', (team_id,))
    history = cur.fetchall()
    
    if len(history) < 2:
        return None
    
    current = history[0]
    previous = None
    for h in history[1:]:
        if (current[0] - h[0]).days >= days - 2:  # Allow some flexibility
            previous = h
            break
    
    if not previous:
        previous = history[1] if len(history) > 1 else history[0]
    
    # Handle null ranks
    if current[1] is None or previous[1] is None:
        return None
    
    analysis['current_date'] = current[0]
    analysis['previous_date'] = previous[0]
    analysis['current_rank'] = current[1]
    analysis['previous_rank'] = previous[1]
    analysis['rank_change'] = previous[1] - current[1]
    analysis['current_power'] = float(current[2]) if current[2] else 0
    analysis['previous_power'] = float(previous[2]) if previous[2] else 0
    analysis['power_change'] = analysis['current_power'] - analysis['previous_power']
    
    # Get recent games (within the period) - optimized query
    # Note: Ensure index on games(home_team_master_id, game_date) and games(away_team_master_id, game_date)
    start_date = previous[0] - timedelta(days=14)
    cur.execute('''
        SELECT 
            g.game_date,
            g.home_score,
            g.away_score,
            CASE WHEN g.home_team_master_id = %s THEN 'HOME' ELSE 'AWAY' END as side,
            CASE WHEN g.home_team_master_id = %s THEN t_away.team_name ELSE t_home.team_name END as opponent,
            CASE WHEN g.home_team_master_id = %s THEN t_away.club_name ELSE t_home.club_name END as opp_club,
            cr_opp.national_rank as opponent_rank
        FROM games g
        JOIN teams t_home ON g.home_team_master_id = t_home.team_id_master
        JOIN teams t_away ON g.away_team_master_id = t_away.team_id_master
        LEFT JOIN current_rankings cr_opp ON 
            CASE WHEN g.home_team_master_id = %s THEN g.away_team_master_id ELSE g.home_team_master_id END = cr_opp.team_id
        WHERE (g.home_team_master_id = %s OR g.away_team_master_id = %s)
        AND g.game_date >= %s
        ORDER BY g.game_date DESC
        LIMIT 10
    ''', (team_id, team_id, team_id, team_id, team_id, team_id, start_date))
    
    games = []
    for row in cur.fetchall():
        game_date, home_score, away_score, side, opponent, opp_club, opp_rank = row
        if side == 'HOME':
            team_score, opp_score = home_score, away_score
        else:
            team_score, opp_score = away_score, home_score
        
        if team_score is not None and opp_score is not None:
            if team_score > opp_score:
                result = 'W'
            elif team_score < opp_score:
                result = 'L'
            else:
                result = 'D'
        else:
            result = '?'
        
        games.append({
            'date': game_date,
            'opponent': opponent,
            'opp_club': opp_club,
            'opp_rank': opp_rank,
            'score': f"{team_score}-{opp_score}",
            'result': result
        })
    
    analysis['games'] = games
    
    return analysis


def generate_commentary(analysis, team_name, club_name):
    """Generate human-readable commentary for a team's movement."""
    
    if not analysis:
        return "Not enough data to analyze this team's movement."
    
    lines = []
    
    # Header
    rank_change = analysis['rank_change']
    if rank_change > 0:
        direction = "📈 CLIMBED"
        emoji = "🚀"
    elif rank_change < 0:
        direction = "📉 DROPPED"
        emoji = "📉"
    else:
        direction = "➡️ STAYED"
        emoji = "➡️"
    
    lines.append(f"**{team_name}** ({club_name})")
    lines.append(f"{direction} {abs(rank_change)} spots: #{analysis['previous_rank']} → #{analysis['current_rank']}")
    lines.append("")
    
    # Power score context
    power_pct = (analysis['power_change'] / analysis['previous_power'] * 100) if analysis['previous_power'] else 0
    if abs(power_pct) > 10:
        lines.append(f"PowerScore: {analysis['previous_power']:.3f} → {analysis['current_power']:.3f} ({power_pct:+.1f}%)")
        lines.append("")
    
    # Game analysis
    games = analysis.get('games', [])
    if games:
        wins = [g for g in games if g['result'] == 'W']
        losses = [g for g in games if g['result'] == 'L']
        draws = [g for g in games if g['result'] == 'D']
        
        lines.append(f"**Recent Results:** {len(wins)}W-{len(losses)}L-{len(draws)}D")
        
        # Quality wins
        quality_wins = [g for g in wins if g['opp_rank'] and g['opp_rank'] < 500]
        if quality_wins:
            lines.append("")
            lines.append("🏆 **Quality Wins:**")
            for g in quality_wins[:3]:
                lines.append(f"  • Beat #{g['opp_rank']} {g['opponent']} ({g['score']})")
        
        # Bad losses
        bad_losses = [g for g in losses if g['opp_rank'] and g['opp_rank'] > analysis['previous_rank']]
        if bad_losses:
            lines.append("")
            lines.append("💔 **Tough Losses:**")
            for g in bad_losses[:3]:
                lines.append(f"  • Lost to #{g['opp_rank']} {g['opponent']} ({g['score']})")
        
        # Generate explanation
        lines.append("")
        lines.append("**Why they moved:**")
        
        explanations = []
        
        if rank_change > 100:
            if quality_wins:
                explanations.append(f"Big wins against ranked opponents boosted their strength of schedule")
            if len(wins) > len(losses):
                explanations.append(f"Strong {len(wins)}-{len(losses)} record in recent games")
            if not games:
                explanations.append("Likely benefited from SOS recalculation or opponents' results")
        elif rank_change > 0:
            if wins:
                explanations.append(f"Solid results with {len(wins)} wins lifted their PowerScore")
            else:
                explanations.append("Opponents they beat earlier may have improved, boosting SOS")
        elif rank_change < -100:
            if bad_losses:
                explanations.append(f"Losses to lower-ranked teams hurt their ranking")
            if len(losses) > len(wins):
                explanations.append(f"Rough stretch with {len(losses)} losses dragged them down")
            if not games:
                explanations.append("Other teams' results may have pushed them down relatively")
        elif rank_change < 0:
            if losses:
                explanations.append(f"{len(losses)} losses impacted their standing")
            else:
                explanations.append("Other teams climbed past them with better results")
        else:
            explanations.append("Steady performance maintained their position")
        
        for exp in explanations:
            lines.append(f"  → {exp}")
    else:
        lines.append("No recent games found — movement likely due to SOS recalculation or other teams' results")
    
    return "\n".join(lines)


def get_top_movers_with_analysis(cur, days=7, limit=5, direction='up'):
    """Get top movers with full analysis."""
    
    if direction == 'up':
        order = "DESC"
        change_filter = "> 50"
    else:
        order = "ASC"
        change_filter = "< -50"
    
    # Optimized: Get max date once, use it directly to avoid subquery repetition
    cur.execute("SELECT MAX(snapshot_date) FROM ranking_history")
    max_date = cur.fetchone()[0]
    
    if not max_date:
        return []
    
    cur.execute(f'''
        WITH current_rank AS (
            SELECT team_id, rank_in_cohort, age_group, gender, state_code
            FROM ranking_history
            WHERE snapshot_date = %s
            AND rank_in_cohort IS NOT NULL
        ),
        past_rank AS (
            SELECT DISTINCT ON (team_id) team_id, rank_in_cohort
            FROM ranking_history
            WHERE snapshot_date >= %s - INTERVAL '{days + 3} days'
              AND snapshot_date <= %s - INTERVAL '{days - 2} days'
              AND rank_in_cohort IS NOT NULL
            ORDER BY team_id, snapshot_date DESC
        )
        SELECT 
            t.team_id_master,
            t.team_name, 
            t.club_name,
            cr.age_group,
            cr.gender,
            cr.state_code,
            (pr.rank_in_cohort - cr.rank_in_cohort) as rank_change
        FROM current_rank cr
        JOIN past_rank pr ON cr.team_id = pr.team_id
        JOIN teams t ON cr.team_id = t.team_id_master
        WHERE (pr.rank_in_cohort - cr.rank_in_cohort) {change_filter}
        ORDER BY rank_change {order}
        LIMIT {limit}
    ''', (max_date, max_date, max_date))
    
    results = []
    for row in cur.fetchall():
        team_id, team_name, club_name, age_group, gender, state, rank_change = row
        analysis = get_team_movement_analysis(cur, team_id, days)
        commentary = generate_commentary(analysis, team_name, club_name)
        results.append({
            'team_id': team_id,
            'team_name': team_name,
            'club_name': club_name,
            'age_group': age_group,
            'gender': gender,
            'state': state,
            'rank_change': rank_change,
            'analysis': analysis,
            'commentary': commentary
        })
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Explainy Commentary')
    parser.add_argument('--team', type=str, help='Search for a specific team')
    parser.add_argument('--top-movers', action='store_true', help='Analyze top movers')
    parser.add_argument('--days', type=int, default=7, help='Days to analyze (default: 7)')
    parser.add_argument('--limit', type=int, default=3, help='Number of teams (default: 3)')
    args = parser.parse_args()
    
    conn = get_connection()
    cur = conn.cursor()
    
    if args.team:
        # Search for specific team
        cur.execute('''
            SELECT team_id_master, team_name, club_name 
            FROM teams 
            WHERE team_name ILIKE %s OR club_name ILIKE %s
            LIMIT 5
        ''', (f'%{args.team}%', f'%{args.team}%'))
        
        teams = cur.fetchall()
        if not teams:
            print(f"No teams found matching '{args.team}'")
            return
        
        for team_id, team_name, club_name in teams:
            analysis = get_team_movement_analysis(cur, team_id, args.days)
            commentary = generate_commentary(analysis, team_name, club_name)
            print(commentary)
            print()
            print("=" * 50)
            print()
    
    else:
        # Top movers mode (default)
        print("🎙️ **Explainy's Weekly Commentary**")
        print(f"_Analyzing the biggest moves from the past {args.days} days_")
        print()
        print("=" * 50)
        
        # Climbers
        print()
        print("## 🚀 BIGGEST CLIMBERS")
        print()
        climbers = get_top_movers_with_analysis(cur, args.days, args.limit, 'up')
        for i, mover in enumerate(climbers, 1):
            print(f"### {i}. {mover['age_group'].upper()} {mover['gender'].title()} - {mover['state']}")
            print()
            print(mover['commentary'])
            print()
        
        # Fallers
        print("=" * 50)
        print()
        print("## 📉 BIGGEST FALLERS")
        print()
        fallers = get_top_movers_with_analysis(cur, args.days, args.limit, 'down')
        for i, mover in enumerate(fallers, 1):
            print(f"### {i}. {mover['age_group'].upper()} {mover['gender'].title()} - {mover['state']}")
            print()
            print(mover['commentary'])
            print()
    
    conn.close()


if __name__ == '__main__':
    main()
