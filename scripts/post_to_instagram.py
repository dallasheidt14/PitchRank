#!/usr/bin/env python3
"""
Post to Instagram via Graph API

Setup:
1. Create Facebook Business Page
2. Connect Instagram Business/Creator account to the FB Page
3. Create Facebook App at developers.facebook.com
4. Add Instagram Graph API product
5. Generate access token with permissions:
   - instagram_basic
   - instagram_content_publish
   - pages_read_engagement
6. Add to .env:
   - INSTAGRAM_ACCESS_TOKEN
   - INSTAGRAM_BUSINESS_ACCOUNT_ID

Run: python3 scripts/post_to_instagram.py --caption "Your caption" --image-url "https://..."
"""

import os
import sys
import argparse
import requests
import time
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

INSTAGRAM_ACCESS_TOKEN = os.getenv('INSTAGRAM_ACCESS_TOKEN')
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv('INSTAGRAM_BUSINESS_ACCOUNT_ID')
PITCHRANK_URL = os.getenv('PITCHRANK_URL', 'https://pitchrank.io')

GRAPH_API_URL = 'https://graph.facebook.com/v18.0'


def get_account_info():
    """Get Instagram account info to verify connection."""
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ACCOUNT_ID:
        print("❌ Missing INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_BUSINESS_ACCOUNT_ID in .env")
        return None
    
    response = requests.get(
        f'{GRAPH_API_URL}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}',
        params={
            'fields': 'id,username,profile_picture_url,followers_count',
            'access_token': INSTAGRAM_ACCESS_TOKEN
        }
    )
    
    if response.status_code != 200:
        print(f"❌ Error getting account info: {response.json()}")
        return None
    
    return response.json()


def create_media_container(image_url: str, caption: str):
    """Create a media container for the post."""
    response = requests.post(
        f'{GRAPH_API_URL}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media',
        params={
            'image_url': image_url,
            'caption': caption,
            'access_token': INSTAGRAM_ACCESS_TOKEN
        }
    )
    
    if response.status_code != 200:
        print(f"❌ Error creating media container: {response.json()}")
        return None
    
    return response.json().get('id')


def check_media_status(container_id: str):
    """Check if media container is ready for publishing."""
    response = requests.get(
        f'{GRAPH_API_URL}/{container_id}',
        params={
            'fields': 'status_code',
            'access_token': INSTAGRAM_ACCESS_TOKEN
        }
    )
    
    if response.status_code != 200:
        return None
    
    return response.json().get('status_code')


def publish_media(container_id: str):
    """Publish the media container."""
    response = requests.post(
        f'{GRAPH_API_URL}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish',
        params={
            'creation_id': container_id,
            'access_token': INSTAGRAM_ACCESS_TOKEN
        }
    )
    
    if response.status_code != 200:
        print(f"❌ Error publishing: {response.json()}")
        return None
    
    return response.json().get('id')


def post_to_instagram(image_url: str, caption: str, wait_for_processing: bool = True):
    """Full flow to post an image to Instagram."""
    
    print(f"📤 Posting to Instagram...")
    print(f"   Image: {image_url}")
    print(f"   Caption: {caption[:100]}...")
    
    # Step 1: Create media container
    print("   Creating media container...")
    container_id = create_media_container(image_url, caption)
    if not container_id:
        return None
    
    print(f"   Container ID: {container_id}")
    
    # Step 2: Wait for processing
    if wait_for_processing:
        print("   Waiting for processing...")
        for i in range(30):  # Max 30 seconds
            status = check_media_status(container_id)
            if status == 'FINISHED':
                break
            elif status == 'ERROR':
                print("❌ Media processing failed")
                return None
            time.sleep(1)
    
    # Step 3: Publish
    print("   Publishing...")
    post_id = publish_media(container_id)
    
    if post_id:
        print(f"✅ Posted successfully!")
        print(f"   Post ID: {post_id}")
        return post_id
    
    return None


def generate_movers_caption():
    """Generate a caption for the movers infographic."""
    return """📈 BIGGEST MOVERS THIS WEEK!

🚀 Teams on the rise and 📉 those taking a hit.

Who's climbing your state rankings? Check the full breakdown at pitchrank.io

#YouthSoccer #SoccerRankings #PitchRank #ClubSoccer #YouthSports #SoccerStats #SoccerLife #USYouthSoccer"""


def main():
    parser = argparse.ArgumentParser(description='Post to Instagram')
    parser.add_argument('--image-url', type=str, help='URL of image to post')
    parser.add_argument('--caption', type=str, help='Caption for the post')
    parser.add_argument('--movers', action='store_true', 
                       help='Post the weekly movers infographic')
    parser.add_argument('--platform', type=str, default='instagram',
                       help='Infographic platform size (instagram, story)')
    parser.add_argument('--check-account', action='store_true',
                       help='Verify Instagram account connection')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be posted without posting')
    args = parser.parse_args()
    
    if args.check_account:
        info = get_account_info()
        if info:
            print(f"✅ Connected to Instagram!")
            print(f"   Username: @{info.get('username')}")
            print(f"   Followers: {info.get('followers_count', 'N/A')}")
        return
    
    # Determine image URL and caption
    if args.movers:
        image_url = f"{PITCHRANK_URL}/api/infographic/movers?platform={args.platform}"
        caption = generate_movers_caption()
    elif args.image_url:
        image_url = args.image_url
        caption = args.caption or "Check out pitchrank.io for youth soccer rankings!"
    else:
        print("❌ Specify --movers or --image-url")
        sys.exit(1)
    
    if args.dry_run:
        print("🔍 DRY RUN - Would post:")
        print(f"   Image: {image_url}")
        print(f"   Caption:\n{caption}")
        return
    
    # Check credentials
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ACCOUNT_ID:
        print("❌ Missing credentials. Add to .env:")
        print("   INSTAGRAM_ACCESS_TOKEN=your_token")
        print("   INSTAGRAM_BUSINESS_ACCOUNT_ID=your_account_id")
        print("\nTo get these:")
        print("1. Create FB Business Page & connect Instagram")
        print("2. Create app at developers.facebook.com")
        print("3. Add Instagram Graph API")
        print("4. Generate token with instagram_content_publish permission")
        sys.exit(1)
    
    post_id = post_to_instagram(image_url, caption)
    sys.exit(0 if post_id else 1)


if __name__ == '__main__':
    main()
