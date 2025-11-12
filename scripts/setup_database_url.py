#!/usr/bin/env python3
"""
Helper script to add DATABASE_URL to .env.local
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load existing .env.local if it exists
env_local = Path('.env.local')
env_vars = {}

if env_local.exists():
    load_dotenv(env_local)
    # Read existing vars
    with open(env_local, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key] = value

print("=" * 60)
print("DATABASE_URL Setup Helper")
print("=" * 60)
print()
print("You need to get your DATABASE_URL from Supabase Dashboard:")
print("  1. Go to: https://app.supabase.com")
print("  2. Select your project")
print("  3. Settings > Database > Connection String")
print("  4. Click 'Direct Connection' tab")
print("  5. Copy the connection string")
print()
print("The connection string should look like:")
print("  postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres")
print()
print("OR (direct connection):")
print("  postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres")
print()

# Get DATABASE_URL from user
current_url = env_vars.get('DATABASE_URL', '')
if current_url:
    print(f"Current DATABASE_URL: {current_url[:50]}...")
    print()
    response = input("Do you want to update it? (y/n): ").strip().lower()
    if response != 'y':
        print("Keeping existing DATABASE_URL.")
        exit(0)

print()
print("Paste your DATABASE_URL here (or press Enter to skip):")
db_url = input("DATABASE_URL: ").strip()

if not db_url:
    print("No DATABASE_URL provided. Skipping.")
    exit(0)

# URL-encode special characters in password if needed
# The user should provide the full URL, but we can help with encoding
if '!' in db_url and '%21' not in db_url:
    print()
    print("⚠️  Warning: Password contains '!' character.")
    print("   Make sure it's URL-encoded as '%21' in the connection string.")
    print("   Example: postgresql://postgres:password%21@host:5432/db")
    print()
    response = input("Do you want to auto-encode special characters? (y/n): ").strip().lower()
    if response == 'y':
        # Simple encoding - replace ! with %21
        import urllib.parse
        # Parse the URL
        if '://' in db_url:
            parts = db_url.split('://', 1)
            scheme = parts[0]
            rest = parts[1]
            if '@' in rest:
                auth_part, host_part = rest.split('@', 1)
                if ':' in auth_part:
                    user, password = auth_part.split(':', 1)
                    # URL encode the password
                    password_encoded = urllib.parse.quote(password, safe='')
                    db_url = f"{scheme}://{user}:{password_encoded}@{host_part}"
                    print(f"✅ Encoded URL: {db_url[:80]}...")

# Update env_vars
env_vars['DATABASE_URL'] = db_url

# Write back to .env.local
print()
print(f"Writing DATABASE_URL to {env_local}...")
with open(env_local, 'w') as f:
    # Write other vars first
    for key, value in env_vars.items():
        if key != 'DATABASE_URL':
            f.write(f"{key}={value}\n")
    # Write DATABASE_URL last
    f.write(f"DATABASE_URL={db_url}\n")

print("✅ DATABASE_URL added to .env.local")
print()
print("Next steps:")
print("  1. Test connection: python scripts/test_db_connection.py")
print("  2. Run import: python scripts/import_games_enhanced.py --help")


