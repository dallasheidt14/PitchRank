#!/usr/bin/env python3
"""
Post to Buffer - Queue social media posts via Buffer API

Setup:
1. Create Buffer account at buffer.com
2. Connect your Instagram account
3. Get access token from buffer.com/developers/apps
4. Add BUFFER_ACCESS_TOKEN to .env

Run: python3 scripts/post_to_buffer.py --platform instagram --caption "Your caption"
"""

import os
import sys
import argparse
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

BUFFER_ACCESS_TOKEN = os.getenv('BUFFER_ACCESS_TOKEN')
PITCHRANK_URL = os.getenv('PITCHRANK_URL', 'https://pitchrank.io')

BUFFER_API_URL = 'https://api.bufferapp.com/1'


def get_profiles():
    """Get connected Buffer profiles (social accounts)."""
    if not BUFFER_ACCESS_TOKEN:
        print("❌ BUFFER_ACCESS_TOKEN not set in .env")
        return []
    
    response = requests.get(
        f'{BUFFER_API_URL}/profiles.json',
        params={'access_token': BUFFER_ACCESS_TOKEN}
    )
    
    if response.status_code != 200:
        print(f"❌ Error getting profiles: {response.text}")
        return []
    
    return response.json()


def create_post(profile_id: str, text: str, media_url: str = None, scheduled_at: datetime = None):
    """Create a Buffer post."""
    if not BUFFER_ACCESS_TOKEN:
        print("❌ BUFFER_ACCESS_TOKEN not set in .env")
        return None
    
    data = {
        'access_token': BUFFER_ACCESS_TOKEN,
        'profile_ids[]': profile_id,
        'text': text,
    }
    
    if media_url:
        data['media[photo]'] = media_url
    
    if scheduled_at:
        data['scheduled_at'] = scheduled_at.isoformat()
    else:
        data['now'] = 'true'  # Add to queue
    
    response = requests.post(
        f'{BUFFER_API_URL}/updates/create.json',
        data=data
    )
    
    if response.status_code != 200:
        print(f"❌ Error creating post: {response.text}")
        return None
    
    return response.json()


def generate_movers_caption(climbers: list = None, fallers: list = None):
    """Generate a caption for the movers infographic."""
    caption_lines = [
        "📈 BIGGEST MOVERS THIS WEEK!",
        "",
    ]
    
    if climbers:
        caption_lines.append("🚀 Top Climbers:")
        for i, team in enumerate(climbers[:3], 1):
            caption_lines.append(f"{i}. {team['team_name']} (+{team['change']})")
        caption_lines.append("")
    
    if fallers:
        caption_lines.append("📉 Biggest Drops:")
        for i, team in enumerate(fallers[:3], 1):
            caption_lines.append(f"{i}. {team['team_name']} ({team['change']})")
        caption_lines.append("")
    
    caption_lines.extend([
        "Full rankings at pitchrank.io 🔗",
        "",
        "#YouthSoccer #SoccerRankings #PitchRank",
        "#ClubSoccer #YouthSports #SoccerStats"
    ])
    
    return "\n".join(caption_lines)


def post_movers_infographic(platform: str = 'instagram', age_group: str = None, gender: str = None):
    """Post the weekly movers infographic to Buffer."""
    
    # Get profiles
    profiles = get_profiles()
    if not profiles:
        return False
    
    # Find the right profile
    target_profile = None
    for profile in profiles:
        if platform.lower() in profile.get('service', '').lower():
            target_profile = profile
            break
    
    if not target_profile:
        print(f"❌ No {platform} profile found in Buffer. Available profiles:")
        for p in profiles:
            print(f"  - {p.get('service')}: {p.get('formatted_username')}")
        return False
    
    # Generate infographic URL
    infographic_url = f"{PITCHRANK_URL}/api/infographic/movers?platform={platform}"
    if age_group:
        infographic_url += f"&age_group={age_group}"
    if gender:
        infographic_url += f"&gender={gender}"
    
    # Generate caption
    caption = generate_movers_caption()
    
    # Create the post
    print(f"📤 Posting to {target_profile.get('formatted_username')} ({platform})...")
    print(f"   Image: {infographic_url}")
    print(f"   Caption preview: {caption[:100]}...")
    
    result = create_post(
        profile_id=target_profile['id'],
        text=caption,
        media_url=infographic_url
    )
    
    if result:
        print(f"✅ Post queued successfully!")
        print(f"   Buffer ID: {result.get('updates', [{}])[0].get('id')}")
        return True
    
    return False


def main():
    parser = argparse.ArgumentParser(description='Post to Buffer')
    parser.add_argument('--platform', type=str, default='instagram', 
                       help='Platform (instagram, twitter, facebook)')
    parser.add_argument('--age-group', type=str, help='Filter by age group')
    parser.add_argument('--gender', type=str, help='Filter by gender')
    parser.add_argument('--list-profiles', action='store_true', 
                       help='List connected Buffer profiles')
    parser.add_argument('--caption', type=str, help='Custom caption')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be posted without posting')
    args = parser.parse_args()
    
    if args.list_profiles:
        profiles = get_profiles()
        if profiles:
            print("📱 Connected Buffer profiles:")
            for p in profiles:
                print(f"  - {p.get('service')}: {p.get('formatted_username')} (ID: {p.get('id')})")
        else:
            print("No profiles found. Set BUFFER_ACCESS_TOKEN in .env")
        return
    
    if args.dry_run:
        print("🔍 DRY RUN - Would post:")
        print(f"   Platform: {args.platform}")
        print(f"   Image URL: {PITCHRANK_URL}/api/infographic/movers?platform={args.platform}")
        print(f"   Caption: {generate_movers_caption()[:200]}...")
        return
    
    success = post_movers_infographic(
        platform=args.platform,
        age_group=args.age_group,
        gender=args.gender
    )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
