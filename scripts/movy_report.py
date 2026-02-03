#!/usr/bin/env python3
"""
Movy Report - Generate weekly movers and content suggestions

Run: python3 scripts/movy_report.py [--cohort <age_group> <gender>] [--state <state>]
"""

import os
import sys
import argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

DATABASE_URL = os.getenv('DATABASE_URL')


def get_connection():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def get_biggest_climbers(cur, days=7, limit=10, age_group=None, gender=None, state=None):
    """Get teams that climbed the most in national rankings."""
    
    filters = []
    params = [days, limit]
    
    if age_group:
        filters.append("cr.age_group = %s")
        params.insert(-1, age_group)
    if gender:
        filters.append("cr.gender = %s")
        params.insert(-1, gender)
    if state:
        filters.append("cr.state_code = %s")
        params.insert(-1, state)
    
    filter_sql = f"AND {' AND '.join(filters)}" if filters else ""
    
    query = f'''
    WITH current_rank AS (
        SELECT team_id, rank_in_cohort, age_group, gender, state_code, power_score_final
        FROM ranking_history
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ranking_history)
    ),
    past_rank AS (
        SELECT DISTINCT ON (team_id, age_group, gender) team_id, rank_in_cohort, age_group, gender, snapshot_date
        FROM ranking_history
        WHERE snapshot_date <= (SELECT MAX(snapshot_date) FROM ranking_history) - INTERVAL '%s days'
        ORDER BY team_id, age_group, gender, snapshot_date DESC
    )
    SELECT 
        t.team_name, 
        t.club_name,
        cr.age_group,
        cr.gender,
        cr.state_code,
        pr.rank_in_cohort as old_rank,
        cr.rank_in_cohort as new_rank,
        (pr.rank_in_cohort - cr.rank_in_cohort) as rank_change,
        cr.power_score_final
    FROM current_rank cr
    JOIN past_rank pr ON cr.team_id = pr.team_id
        AND cr.age_group = pr.age_group
        AND cr.gender = pr.gender
    JOIN teams t ON cr.team_id = t.team_id_master
    WHERE pr.rank_in_cohort - cr.rank_in_cohort > 0
    {filter_sql}
    ORDER BY rank_change DESC
    LIMIT %s
    '''
    
    cur.execute(query, params)
    return cur.fetchall()


def get_biggest_fallers(cur, days=7, limit=10, age_group=None, gender=None, state=None):
    """Get teams that dropped the most in national rankings."""
    
    filters = []
    params = [days, limit]
    
    if age_group:
        filters.append("cr.age_group = %s")
        params.insert(-1, age_group)
    if gender:
        filters.append("cr.gender = %s")
        params.insert(-1, gender)
    if state:
        filters.append("cr.state_code = %s")
        params.insert(-1, state)
    
    filter_sql = f"AND {' AND '.join(filters)}" if filters else ""
    
    query = f'''
    WITH current_rank AS (
        SELECT team_id, rank_in_cohort, age_group, gender, state_code, power_score_final
        FROM ranking_history
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ranking_history)
    ),
    past_rank AS (
        SELECT DISTINCT ON (team_id, age_group, gender) team_id, rank_in_cohort, age_group, gender, snapshot_date
        FROM ranking_history
        WHERE snapshot_date <= (SELECT MAX(snapshot_date) FROM ranking_history) - INTERVAL '%s days'
        ORDER BY team_id, age_group, gender, snapshot_date DESC
    )
    SELECT 
        t.team_name, 
        t.club_name,
        cr.age_group,
        cr.gender,
        cr.state_code,
        pr.rank_in_cohort as old_rank,
        cr.rank_in_cohort as new_rank,
        (cr.rank_in_cohort - pr.rank_in_cohort) as rank_drop,
        cr.power_score_final
    FROM current_rank cr
    JOIN past_rank pr ON cr.team_id = pr.team_id
        AND cr.age_group = pr.age_group
        AND cr.gender = pr.gender
    JOIN teams t ON cr.team_id = t.team_id_master
    WHERE cr.rank_in_cohort - pr.rank_in_cohort > 0
    {filter_sql}
    ORDER BY rank_drop DESC
    LIMIT %s
    '''
    
    cur.execute(query, params)
    return cur.fetchall()


def get_snapshot_dates(cur):
    """Get available snapshot dates."""
    cur.execute("""
        SELECT DISTINCT snapshot_date 
        FROM ranking_history 
        ORDER BY snapshot_date DESC 
        LIMIT 10
    """)
    return [row[0] for row in cur.fetchall()]


def format_team(row):
    """Format a team row for display."""
    team_name, club_name, age_group, gender, state, old_rank, new_rank, change, power_score = row
    gender_label = "Boys" if gender == "male" else "Girls"
    return f"{team_name} ({club_name}) - {age_group.upper()} {gender_label} {state}"


def generate_social_caption(climbers, period="week"):
    """Generate a social media caption for biggest movers."""
    lines = [f"📈 BIGGEST CLIMBERS THIS {period.upper()}!", ""]
    
    for i, row in enumerate(climbers[:5], 1):
        team_name, club_name, age_group, gender, state, old_rank, new_rank, change, _ = row
        gender_emoji = "👦" if gender == "male" else "👧"
        lines.append(f"{i}. {team_name} {gender_emoji}")
        lines.append(f"   #{old_rank} → #{new_rank} (+{change} spots)")
        lines.append("")
    
    lines.append("#YouthSoccer #Rankings #PitchRank")
    
    if climbers:
        age = climbers[0][2].upper()
        gender = "Boys" if climbers[0][3] == "male" else "Girls"
        lines.append(f"#{age} #{gender}Soccer")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Movy Report - Weekly Movers')
    parser.add_argument('--days', type=int, default=7, help='Days to look back (default: 7)')
    parser.add_argument('--age-group', type=str, help='Filter by age group (e.g., u14)')
    parser.add_argument('--gender', type=str, help='Filter by gender (male/female)')
    parser.add_argument('--state', type=str, help='Filter by state code (e.g., TX)')
    parser.add_argument('--limit', type=int, default=10, help='Number of results (default: 10)')
    parser.add_argument('--caption', action='store_true', help='Generate social media caption')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Get snapshot info
    dates = get_snapshot_dates(cur)
    
    # Get movers
    climbers = get_biggest_climbers(
        cur, 
        days=args.days, 
        limit=args.limit,
        age_group=args.age_group,
        gender=args.gender,
        state=args.state
    )
    
    fallers = get_biggest_fallers(
        cur, 
        days=args.days, 
        limit=args.limit,
        age_group=args.age_group,
        gender=args.gender,
        state=args.state
    )
    
    conn.close()
    
    if args.json:
        import json
        print(json.dumps({
            'snapshot_dates': [str(d) for d in dates],
            'period_days': args.days,
            'climbers': [{'team': r[0], 'club': r[1], 'age': r[2], 'gender': r[3], 
                         'state': r[4], 'old_rank': r[5], 'new_rank': r[6], 
                         'change': r[7], 'power_score': float(r[8]) if r[8] else None} 
                        for r in climbers],
            'fallers': [{'team': r[0], 'club': r[1], 'age': r[2], 'gender': r[3], 
                        'state': r[4], 'old_rank': r[5], 'new_rank': r[6], 
                        'drop': r[7], 'power_score': float(r[8]) if r[8] else None} 
                       for r in fallers],
        }, indent=2, default=str))
        return
    
    # Header
    period = f"{args.days}-day"
    filters = []
    if args.age_group:
        filters.append(args.age_group.upper())
    if args.gender:
        filters.append("Boys" if args.gender == "male" else "Girls")
    if args.state:
        filters.append(args.state.upper())
    filter_str = f" ({', '.join(filters)})" if filters else ""
    
    print(f"📈 **Movy {period.title()} Movers Report{filter_str}**")
    print(f"Latest snapshot: {dates[0] if dates else 'N/A'}")
    print()
    
    # Climbers
    print(f"**🚀 Top {len(climbers)} Climbers:**")
    for i, row in enumerate(climbers, 1):
        team_info = format_team(row)
        old_rank, new_rank, change = row[5], row[6], row[7]
        print(f"  {i}. {team_info}")
        print(f"     #{old_rank} → #{new_rank} (+{change})")
    
    print()
    
    # Fallers
    print(f"**📉 Top {len(fallers)} Fallers:**")
    for i, row in enumerate(fallers, 1):
        team_info = format_team(row)
        old_rank, new_rank, drop = row[5], row[6], row[7]
        print(f"  {i}. {team_info}")
        print(f"     #{old_rank} → #{new_rank} (-{drop})")
    
    # Social caption
    if args.caption and climbers:
        print()
        print("=" * 50)
        print("📱 **Suggested Social Caption:**")
        print("=" * 50)
        print(generate_social_caption(climbers, "week" if args.days <= 7 else "month"))


if __name__ == '__main__':
    main()
