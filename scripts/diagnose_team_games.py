#!/usr/bin/env python3
"""
Diagnose why a team has fewer games in rankings than expected.

This script investigates all filtering stages in the ranking pipeline:
1. Games in the database (raw count)
2. Games with valid scores
3. Games not excluded (is_excluded = false)
4. Games within the 365-day window
5. Games where BOTH teams have valid age_group and gender metadata
6. Games after merge resolution
7. Games after deprecated team filtering
8. Final game count in rankings (capped at 30)

Usage:
    python scripts/diagnose_team_games.py <team_id_master>
    python scripts/diagnose_team_games.py 691eb36d-95b2-4a08-bd59-13c1b0e830bb
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client
import pandas as pd
from src.rankings.data_adapter import age_group_to_age

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)


def diagnose_team(team_id: str):
    """Run comprehensive diagnosis for a team's game count."""
    print(f"\n{'='*70}")
    print(f"  GAME COUNT DIAGNOSIS FOR TEAM: {team_id}")
    print(f"{'='*70}\n")

    # 1. Get team info
    print("1. TEAM INFO")
    print("-" * 40)
    team_result = supabase.table('teams').select(
        'team_id_master, team_name, club_name, age_group, gender, state_code, is_deprecated'
    ).eq('team_id_master', team_id).execute()

    if not team_result.data:
        print(f"  ERROR: Team {team_id} not found in teams table!")
        return
    team = team_result.data[0]
    print(f"  Name: {team['team_name']}")
    print(f"  Club: {team['club_name']}")
    print(f"  Age Group: {team['age_group']}")
    print(f"  Gender: {team['gender']}")
    print(f"  State: {team['state_code']}")
    print(f"  Deprecated: {team['is_deprecated']}")
    age = age_group_to_age(team['age_group'])
    print(f"  Normalized Age: {age}")
    print()

    if team['is_deprecated']:
        print("  WARNING: This team is deprecated! It should not appear in rankings.")
        # Check if it's merged
        merge_result = supabase.table('team_merge_map').select(
            'canonical_team_id'
        ).eq('deprecated_team_id', team_id).execute()
        if merge_result.data:
            canonical = merge_result.data[0]['canonical_team_id']
            print(f"  Merged into: {canonical}")
            print(f"  Run this script with the canonical team ID instead.")
        print()

    # 2. Count ALL games (no filters)
    print("2. RAW GAME COUNTS (all games in database)")
    print("-" * 40)
    home_all = supabase.table('games').select(
        'id', count='exact'
    ).eq('home_team_master_id', team_id).execute()
    away_all = supabase.table('games').select(
        'id', count='exact'
    ).eq('away_team_master_id', team_id).execute()
    total_all = (home_all.count or 0) + (away_all.count or 0)
    print(f"  Home games: {home_all.count}")
    print(f"  Away games: {away_all.count}")
    print(f"  Total: {total_all}")
    print()

    # 3. Count games with scores
    print("3. GAMES WITH SCORES (non-null home_score AND away_score)")
    print("-" * 40)
    home_scored = supabase.table('games').select(
        'id', count='exact'
    ).eq('home_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').execute()
    away_scored = supabase.table('games').select(
        'id', count='exact'
    ).eq('away_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').execute()
    total_scored = (home_scored.count or 0) + (away_scored.count or 0)
    print(f"  Home games with scores: {home_scored.count}")
    print(f"  Away games with scores: {away_scored.count}")
    print(f"  Total with scores: {total_scored}")
    dropped_no_score = total_all - total_scored
    if dropped_no_score > 0:
        print(f"  DROPPED (no scores): {dropped_no_score}")
    print()

    # 4. Count non-excluded games with scores
    print("4. NON-EXCLUDED GAMES WITH SCORES")
    print("-" * 40)
    home_valid = supabase.table('games').select(
        'id', count='exact'
    ).eq('home_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').eq('is_excluded', False).execute()
    away_valid = supabase.table('games').select(
        'id', count='exact'
    ).eq('away_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').eq('is_excluded', False).execute()
    total_valid = (home_valid.count or 0) + (away_valid.count or 0)
    print(f"  Home valid: {home_valid.count}")
    print(f"  Away valid: {away_valid.count}")
    print(f"  Total valid: {total_valid}")
    dropped_excluded = total_scored - total_valid
    if dropped_excluded > 0:
        print(f"  DROPPED (is_excluded=true): {dropped_excluded}")
    print()

    # 5. Count games in 365-day window
    print("5. GAMES IN 365-DAY WINDOW")
    print("-" * 40)
    today = datetime.utcnow().date()
    cutoff_365 = (today - timedelta(days=365)).isoformat()
    today_str = today.isoformat()
    home_window = supabase.table('games').select(
        'id', count='exact'
    ).eq('home_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').eq(
        'is_excluded', False
    ).gte('game_date', cutoff_365).lte('game_date', today_str).execute()
    away_window = supabase.table('games').select(
        'id', count='exact'
    ).eq('away_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').eq(
        'is_excluded', False
    ).gte('game_date', cutoff_365).lte('game_date', today_str).execute()
    total_window = (home_window.count or 0) + (away_window.count or 0)
    print(f"  Window: {cutoff_365} to {today_str}")
    print(f"  Home in window: {home_window.count}")
    print(f"  Away in window: {away_window.count}")
    print(f"  Total in window: {total_window}")
    dropped_window = total_valid - total_window
    if dropped_window > 0:
        print(f"  DROPPED (outside 365-day window): {dropped_window}")
    print()

    # 6. Fetch actual games to check opponent metadata
    print("6. OPPONENT METADATA CHECK (key filter!)")
    print("-" * 40)
    # Fetch all games in window for this team
    home_games = supabase.table('games').select(
        'id, game_date, home_score, away_score, home_team_master_id, away_team_master_id'
    ).eq('home_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').eq(
        'is_excluded', False
    ).gte('game_date', cutoff_365).lte('game_date', today_str).execute()

    away_games = supabase.table('games').select(
        'id, game_date, home_score, away_score, home_team_master_id, away_team_master_id'
    ).eq('away_team_master_id', team_id).not_.is_(
        'home_score', 'null'
    ).not_.is_('away_score', 'null').eq(
        'is_excluded', False
    ).gte('game_date', cutoff_365).lte('game_date', today_str).execute()

    all_games = home_games.data + away_games.data

    # Collect all opponent IDs
    opponent_ids = set()
    for g in all_games:
        if g['home_team_master_id'] == team_id:
            opponent_ids.add(g['away_team_master_id'])
        else:
            opponent_ids.add(g['home_team_master_id'])

    # Fetch opponent metadata
    opp_metadata = {}
    opp_ids_list = list(opponent_ids)
    for i in range(0, len(opp_ids_list), 100):
        batch = opp_ids_list[i:i+100]
        result = supabase.table('teams').select(
            'team_id_master, team_name, age_group, gender, is_deprecated'
        ).in_('team_id_master', batch).execute()
        for t in result.data:
            opp_metadata[t['team_id_master']] = t

    # Check each game
    games_with_metadata = 0
    games_without_metadata = 0
    dropped_games_detail = []

    for g in all_games:
        if g['home_team_master_id'] == team_id:
            opp_id = g['away_team_master_id']
        else:
            opp_id = g['home_team_master_id']

        opp = opp_metadata.get(opp_id)
        team_has_age = bool(age)
        team_has_gender = bool(team['gender'])

        if opp is None:
            games_without_metadata += 1
            dropped_games_detail.append({
                'date': g['game_date'],
                'score': f"{g['home_score']}-{g['away_score']}",
                'opponent_id': opp_id,
                'reason': 'Opponent not in teams table',
            })
            continue

        opp_age = age_group_to_age(opp.get('age_group', ''))
        opp_gender = opp.get('gender', '')

        # Normalize gender same as data_adapter
        if opp_gender:
            opp_gender = opp_gender.lower().strip()
            opp_gender = {'boys': 'male', 'boy': 'male', 'girls': 'female', 'girl': 'female'}.get(opp_gender, opp_gender)

        if not opp_age or not opp_gender:
            games_without_metadata += 1
            dropped_games_detail.append({
                'date': g['game_date'],
                'score': f"{g['home_score']}-{g['away_score']}",
                'opponent_id': opp_id,
                'opponent_name': opp.get('team_name', 'Unknown'),
                'opp_age_group': opp.get('age_group'),
                'opp_gender': opp.get('gender'),
                'reason': f"Missing metadata: age_group={opp.get('age_group')!r}, gender={opp.get('gender')!r}",
            })
            continue

        if not team_has_age or not team_has_gender:
            games_without_metadata += 1
            dropped_games_detail.append({
                'date': g['game_date'],
                'score': f"{g['home_score']}-{g['away_score']}",
                'opponent_id': opp_id,
                'reason': f"This team missing metadata: age_group={team['age_group']!r}, gender={team['gender']!r}",
            })
            continue

        games_with_metadata += 1

    print(f"  Games where BOTH teams have valid metadata: {games_with_metadata}")
    print(f"  Games DROPPED due to missing metadata: {games_without_metadata}")

    if dropped_games_detail:
        print(f"\n  DROPPED GAMES DETAIL:")
        for d in dropped_games_detail:
            print(f"    {d['date']} | Score: {d['score']} | Opp: {d.get('opponent_name', d['opponent_id'][:12]+'...')} | {d['reason']}")
    print()

    # 7. Check for merged games
    print("7. MERGE RESOLUTION CHECK")
    print("-" * 40)
    # Check if any teams have been merged INTO this team
    merge_into = supabase.table('team_merge_map').select(
        'deprecated_team_id'
    ).eq('canonical_team_id', team_id).execute()
    if merge_into.data:
        print(f"  Teams merged into this one: {len(merge_into.data)}")
        for m in merge_into.data:
            dep_id = m['deprecated_team_id']
            # Count games for deprecated team
            dep_home = supabase.table('games').select('id', count='exact').eq('home_team_master_id', dep_id).not_.is_('home_score', 'null').not_.is_('away_score', 'null').eq('is_excluded', False).gte('game_date', cutoff_365).execute()
            dep_away = supabase.table('games').select('id', count='exact').eq('away_team_master_id', dep_id).not_.is_('home_score', 'null').not_.is_('away_score', 'null').eq('is_excluded', False).gte('game_date', cutoff_365).execute()
            dep_total = (dep_home.count or 0) + (dep_away.count or 0)
            print(f"    {dep_id}: {dep_total} games still referencing deprecated ID")
    else:
        print(f"  No teams have been merged into this one")

    # Check if this team was merged FROM another
    merge_from = supabase.table('team_merge_map').select(
        'canonical_team_id'
    ).eq('deprecated_team_id', team_id).execute()
    if merge_from.data:
        print(f"  WARNING: This team is DEPRECATED (merged into {merge_from.data[0]['canonical_team_id']})")
    print()

    # 8. Check rankings_full
    print("8. CURRENT RANKINGS DATA")
    print("-" * 40)
    rankings = supabase.table('rankings_full').select(
        'team_id, games_played, games_last_180_days, status, wins, losses, draws, power_score_final, sos_norm, rank_in_cohort, age_group, gender, last_game, last_calculated'
    ).eq('team_id', team_id).execute()
    if rankings.data:
        r = rankings.data[0]
        print(f"  games_played (v53e gp): {r.get('games_played')}")
        print(f"  games_last_180_days: {r.get('games_last_180_days')}")
        print(f"  status: {r.get('status')}")
        print(f"  W/L/D: {r.get('wins')}/{r.get('losses')}/{r.get('draws')}")
        print(f"  power_score_final: {r.get('power_score_final')}")
        print(f"  sos_norm: {r.get('sos_norm')}")
        print(f"  rank_in_cohort: {r.get('rank_in_cohort')}")
        print(f"  age_group: {r.get('age_group')}")
        print(f"  gender: {r.get('gender')}")
        print(f"  last_game: {r.get('last_game')}")
        print(f"  last_calculated: {r.get('last_calculated')}")
    else:
        print(f"  No ranking record found for this team!")
    print()

    # 9. Check rankings_view (what frontend sees)
    print("9. RANKINGS VIEW (frontend display)")
    print("-" * 40)
    view = supabase.table('rankings_view').select(
        'games_played, total_games_played, total_wins, total_losses, total_draws, win_percentage, rank_in_cohort_final, status'
    ).eq('team_id_master', team_id).execute()
    if view.data:
        v = view.data[0]
        print(f"  games_played (capped): {v.get('games_played')}")
        print(f"  total_games_played (SQL view): {v.get('total_games_played')}")
        print(f"  W/L/D: {v.get('total_wins')}/{v.get('total_losses')}/{v.get('total_draws')}")
        print(f"  win_percentage: {v.get('win_percentage')}")
        print(f"  rank: {v.get('rank_in_cohort_final')}")
        print(f"  status: {v.get('status')}")

        gp = v.get('games_played', 0) or 0
        tgp = v.get('total_games_played', 0) or 0
        if tgp > gp:
            print(f"\n  DISCREPANCY: total_games_played ({tgp}) > games_played ({gp})")
            print(f"  This means {tgp - gp} games were filtered by the ranking engine.")
            print(f"  Most likely cause: opponent missing age_group or gender metadata.")
    else:
        print(f"  No rankings_view record found!")
    print()

    # 10. Summary
    print("10. SUMMARY")
    print("=" * 70)
    print(f"  Total games in DB:                {total_all}")
    print(f"  -> With scores:                   {total_scored}")
    print(f"  -> Not excluded:                  {total_valid}")
    print(f"  -> In 365-day window:             {total_window}")
    print(f"  -> With valid opponent metadata:  {games_with_metadata}")
    print(f"  -> In rankings (max 30):          {games_with_metadata} (capped)")
    print()
    if games_without_metadata > 0:
        print(f"  ROOT CAUSE: {games_without_metadata} game(s) dropped due to missing")
        print(f"  opponent metadata (age_group or gender).")
        print(f"  Fix: Add age_group and gender to the opponent teams in the teams table.")
    elif total_window < total_valid:
        print(f"  ROOT CAUSE: {total_valid - total_window} game(s) outside 365-day window.")
    elif dropped_excluded > 0:
        print(f"  ROOT CAUSE: {dropped_excluded} game(s) are excluded (is_excluded=true).")
    elif dropped_no_score > 0:
        print(f"  ROOT CAUSE: {dropped_no_score} game(s) have no scores.")
    else:
        print(f"  The team genuinely has {total_all} games in the database.")
        print(f"  All filters passed - game count is accurate.")
    print()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_team_games.py <team_id_master>")
        print("Example: python scripts/diagnose_team_games.py 691eb36d-95b2-4a08-bd59-13c1b0e830bb")
        sys.exit(1)

    team_id = sys.argv[1]
    diagnose_team(team_id)
