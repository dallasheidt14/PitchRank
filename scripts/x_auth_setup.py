#!/usr/bin/env python3
"""
X API Re-authentication Tool
Generates new access tokens for @PitchRank

Run this, follow the URL, enter the PIN, get new tokens.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import tweepy

load_dotenv(Path.home() / 'clawd' / '.env', override=True)

consumer_key = os.getenv('X_CONSUMER_KEY')
consumer_secret = os.getenv('X_CONSUMER_SECRET')

if not consumer_key or not consumer_secret:
    print("❌ Missing X_CONSUMER_KEY or X_CONSUMER_SECRET in .env")
    exit(1)

# OAuth 1.0a PIN-based flow
auth = tweepy.OAuth1UserHandler(consumer_key, consumer_secret, callback='oob')

try:
    auth_url = auth.get_authorization_url()
    print("=" * 60)
    print("STEP 1: Open this URL in your browser:")
    print(f"\n{auth_url}\n")
    print("STEP 2: Authorize the app, then copy the PIN")
    print("=" * 60)
    
    pin = input("\nEnter the PIN: ").strip()
    
    access_token, access_token_secret = auth.get_access_token(pin)
    
    print("\n" + "=" * 60)
    print("✅ SUCCESS! New tokens generated.")
    print("=" * 60)
    print(f"\nX_ACCESS_TOKEN={access_token}")
    print(f"X_ACCESS_TOKEN_SECRET={access_token_secret}")
    print("\nUpdate these in ~/clawd/.env and /Projects/PitchRank/.env")
    print("=" * 60)
    
    # Verify they work
    client = tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret
    )
    me = client.get_me()
    print(f"\n✅ Verified: Connected as @{me.data.username}")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
