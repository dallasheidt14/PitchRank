#!/usr/bin/env python3
"""
Reassign HD/AD Games Between Teams

This script moves games from one team to another based on the competition field
(which indicates HD or AD division). Handles immutable game flags automatically.

Usage:
    # Dry run - see what would change
    python scripts/reassign_division_games.py \
        --from-team <HD_TEAM_UUID> \
        --to-team <AD_TEAM_UUID> \
        --division AD \
        --dry-run

    # Actually move the games
    python scripts/reassign_division_games.py \
        --from-team <HD_TEAM_UUID> \
        --to-team <AD_TEAM_UUID> \
        --division AD

Examples:
    # Move AD games from HD team to AD team
    python scripts/reassign_division_games.py \
        --from-team 433ad64d-9a1a-4e7a-afd0-79c4bb5e600b \
        --to-team 7927135b-4f74-41fa-9d0d-a3c1c1fe4fa6 \
        --division AD

    # Move HD games from AD team to HD team (reverse cleanup)
    python scripts/reassign_division_games.py \
        --from-team 7927135b-4f74-41fa-9d0d-a3c1c1fe4fa6 \
        --to-team 433ad64d-9a1a-4e7a-afd0-79c4bb5e600b \
        --division HD
"""
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment
env_local = Path(__file__).parent.parent / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv(Path(__file__).parent.parent / '.env')

from supabase import create_client

def get_db():
    """Get Supabase client"""
    url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def get_team_info(db, team_id: str) -> dict:
    """Get team name and info"""
    result = db.table('teams').select('team_name, age_group, gender').eq(
        'team_id_master', team_id
    ).single().execute()
    return result.data if result.data else {}


def find_games_to_move(db, from_team_id: str, division: str) -> list:
    """
    Find games that match the division pattern and are assigned to from_team.

    Args:
        db: Supabase client
        from_team_id: Team UUID to move games FROM
        division: 'AD' or 'HD' - matches competition field containing this

    Returns:
        List of game dicts with id, position (home/away), and game info
    """
    games_to_move = []

    # Find home games with matching division
    home_games = db.table('games').select(
        'id, game_date, competition, home_score, away_score, is_immutable'
    ).eq('home_team_master_id', from_team_id).ilike(
        'competition', f'%{division}%'
    ).execute()

    for game in (home_games.data or []):
        games_to_move.append({
            'id': game['id'],
            'position': 'home',
            'game_date': game['game_date'],
            'competition': game['competition'],
            'score': f"{game['home_score']}-{game['away_score']}",
            'is_immutable': game['is_immutable']
        })

    # Find away games with matching division
    away_games = db.table('games').select(
        'id, game_date, competition, home_score, away_score, is_immutable'
    ).eq('away_team_master_id', from_team_id).ilike(
        'competition', f'%{division}%'
    ).execute()

    for game in (away_games.data or []):
        games_to_move.append({
            'id': game['id'],
            'position': 'away',
            'game_date': game['game_date'],
            'competition': game['competition'],
            'score': f"{game['home_score']}-{game['away_score']}",
            'is_immutable': game['is_immutable']
        })

    # Sort by date
    games_to_move.sort(key=lambda x: x['game_date'] or '')

    return games_to_move


def move_games(db, games: list, to_team_id: str, dry_run: bool = True) -> dict:
    """
    Move games to a new team, handling immutability.

    Returns:
        Dict with counts of success, errors, etc.
    """
    results = {
        'total': len(games),
        'moved': 0,
        'errors': 0,
        'unlocked': 0,
        'relocked': 0,
        'error_details': []
    }

    if dry_run:
        print(f"\n🔍 DRY RUN - Would move {len(games)} games to {to_team_id}")
        return results

    print(f"\n🔄 Moving {len(games)} games to {to_team_id}...")

    for game in games:
        game_id = game['id']
        position = game['position']
        was_immutable = game['is_immutable']

        try:
            # Step 1: Unlock if immutable
            if was_immutable:
                db.table('games').update({'is_immutable': False}).eq('id', game_id).execute()
                results['unlocked'] += 1

            # Step 2: Move the game
            if position == 'home':
                db.table('games').update({'home_team_master_id': to_team_id}).eq('id', game_id).execute()
            else:
                db.table('games').update({'away_team_master_id': to_team_id}).eq('id', game_id).execute()

            results['moved'] += 1

            # Step 3: Re-lock if it was immutable
            if was_immutable:
                db.table('games').update({'is_immutable': True}).eq('id', game_id).execute()
                results['relocked'] += 1

        except Exception as e:
            results['errors'] += 1
            results['error_details'].append({
                'game_id': game_id,
                'error': str(e)
            })
            print(f"  ❌ Error moving game {game_id}: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Reassign HD/AD games between teams',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--from-team', required=True, help='Team UUID to move games FROM')
    parser.add_argument('--to-team', required=True, help='Team UUID to move games TO')
    parser.add_argument('--division', required=True, choices=['AD', 'HD'],
                        help='Division to match in competition field')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen without making changes')

    args = parser.parse_args()

    db = get_db()

    # Get team info
    from_team = get_team_info(db, args.from_team)
    to_team = get_team_info(db, args.to_team)

    if not from_team:
        print(f"❌ Source team not found: {args.from_team}")
        sys.exit(1)
    if not to_team:
        print(f"❌ Target team not found: {args.to_team}")
        sys.exit(1)

    print("=" * 60)
    print("REASSIGN DIVISION GAMES")
    print("=" * 60)
    print(f"\n📤 FROM: {from_team['team_name']} ({args.from_team[:8]}...)")
    print(f"📥 TO:   {to_team['team_name']} ({args.to_team[:8]}...)")
    print(f"🏷️  Division: {args.division}")
    print(f"🔍 Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    # Find games to move
    games = find_games_to_move(db, args.from_team, args.division)

    if not games:
        print(f"\n✅ No {args.division} games found on source team. Nothing to do!")
        return

    # Show games
    print(f"\n📋 Found {len(games)} {args.division} games to move:")
    print("-" * 60)

    immutable_count = sum(1 for g in games if g['is_immutable'])

    for game in games:
        lock_icon = "🔒" if game['is_immutable'] else "🔓"
        print(f"  {lock_icon} {game['game_date']} | {game['position']:4} | "
              f"{game['score']:5} | {game['competition']}")

    print("-" * 60)
    print(f"  Total: {len(games)} games ({immutable_count} immutable)")

    # Move games
    results = move_games(db, games, args.to_team, dry_run=args.dry_run)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if args.dry_run:
        print(f"  Would move: {results['total']} games")
        print(f"  Would unlock/relock: {immutable_count} immutable games")
        print(f"\n💡 Run without --dry-run to execute")
    else:
        print(f"  ✅ Moved: {results['moved']} games")
        print(f"  🔓 Unlocked: {results['unlocked']} games")
        print(f"  🔒 Re-locked: {results['relocked']} games")
        if results['errors']:
            print(f"  ❌ Errors: {results['errors']}")
            for err in results['error_details']:
                print(f"      {err['game_id']}: {err['error']}")

    # Verification query
    if not args.dry_run and results['moved'] > 0:
        print(f"\n📊 Verification - run this SQL to confirm:")
        print(f"""
SELECT t.team_name, COUNT(*) as games
FROM games g
JOIN teams t ON t.team_id_master = g.home_team_master_id
             OR t.team_id_master = g.away_team_master_id
WHERE t.team_id_master IN ('{args.from_team}', '{args.to_team}')
GROUP BY t.team_name;
""")


if __name__ == '__main__':
    main()
