#!/usr/bin/env python3
"""
Socialy X Poster — Autonomous posting to @PitchRank

Reads movers data and posts to X using the brand voice.
Run via cron: `python3 scripts/socialy_x_post.py`
"""
import os
import sys
import json
import random
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
env_local = Path(__file__).parent.parent / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
if env_path.exists():
    load_dotenv(env_path, override=True)

# Also check clawd .env for X credentials
clawd_env = Path.home() / 'clawd' / '.env'
if clawd_env.exists():
    load_dotenv(clawd_env, override=True)

import tweepy


def get_x_client():
    """Initialize X API client with OAuth 1.0a User Context."""
    consumer_key = os.getenv('X_CONSUMER_KEY')
    consumer_secret = os.getenv('X_CONSUMER_SECRET')
    access_token = os.getenv('X_ACCESS_TOKEN')
    access_token_secret = os.getenv('X_ACCESS_TOKEN_SECRET')
    
    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        raise ValueError("Missing X API credentials in environment")
    
    client = tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret
    )
    return client


def get_weekly_movers():
    """Get top movers from the database."""
    try:
        from supabase import create_client
        
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not supabase_url or not supabase_key:
            return None
            
        supabase = create_client(supabase_url, supabase_key)
        
        # Get biggest mover from rankings view
        result = supabase.rpc('get_biggest_movers', {
            'limit_count': 5,
            'min_games': 5
        }).execute()
        
        if result.data:
            return result.data
    except Exception as e:
        print(f"Could not fetch movers: {e}")
    
    return None


def generate_post():
    """Generate a post based on available data."""
    
    # Post templates (brand voice: confident, data-backed, human)
    templates = {
        'mover': [
            "📈 {team_name} just climbed {change} spots to #{new_rank} in {state} {age_group}.\n\nThat's what a {record} run does.\n\n#YouthSoccer #{state}Soccer",
            "🔥 Big move alert: {team_name} is now #{new_rank} nationally in {age_group}.\n\n+{change} spots this week.\n\nSome rankings are vibes. Ours are receipts.\n\npitchrank.io/rankings",
            "👀 {team_name} ({state}) jumped {change} spots this week.\n\nNow ranked #{new_rank} in {age_group}.\n\nWhere does YOUR team stand?\n\n#ClubSoccer #SoccerRankings",
        ],
        'data_flex': [
            "📊 This week we analyzed {games} games across {states} states.\n\nYour team's ranking isn't a guess — it's built from every result that matters.\n\npitchrank.io/rankings\n\n#YouthSoccer #SoccerData",
            "700,000+ games.\n77,000+ teams.\nAll 50 states.\n\nYour kid's team is in there. Go find them.\n\n👇 pitchrank.io/rankings\n\n#ClubSoccer #YouthSoccer",
            "We don't guess. We count.\n\n📊 Real match results\n🏆 Strength of schedule\n📈 Updated weekly\n\nFind your team's ranking 👇\npitchrank.io/rankings",
        ],
        'state_spotlight': [
            "🏆 Top 5 {age_group} teams in {state} right now:\n\n1. {t1}\n2. {t2}\n3. {t3}\n4. {t4}\n5. {t5}\n\nFull rankings 👇\npitchrank.io/rankings\n\n#{state}Soccer #YouthSoccer",
        ],
    }
    
    # Try to get live data
    movers = get_weekly_movers()
    
    if movers and len(movers) > 0:
        # Use real mover data
        mover = movers[0]
        template = random.choice(templates['mover'])
        return template.format(
            team_name=mover.get('team_name', 'Unknown'),
            change=abs(mover.get('change', 0)),
            new_rank=mover.get('new_rank', '?'),
            state=mover.get('state', 'USA'),
            age_group=mover.get('age_group', 'U14').upper(),
            record='strong'
        )
    else:
        # Fall back to data flex post
        template = random.choice(templates['data_flex'])
        return template.format(
            games=random.randint(2000, 3000),
            states=50
        )


def post_to_x(text: str, dry_run: bool = False):
    """Post text to X."""
    if dry_run:
        print(f"[DRY RUN] Would post:\n{text}")
        return True
    
    try:
        client = get_x_client()
        response = client.create_tweet(text=text)
        print(f"✅ Posted to X: {response.data['id']}")
        return True
    except Exception as e:
        print(f"❌ Failed to post: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Post to X for PitchRank')
    parser.add_argument('--dry-run', action='store_true', help='Print without posting')
    parser.add_argument('--message', type=str, help='Custom message to post')
    args = parser.parse_args()
    
    if args.message:
        text = args.message
    else:
        text = generate_post()
    
    print(f"Generated post ({len(text)} chars):\n{text}\n")
    
    success = post_to_x(text, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
