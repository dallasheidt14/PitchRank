# Supabase Pooler Setup for GitHub Actions

## Problem
GitHub Actions runners don't support IPv6, but Supabase's direct database connection (`db.xxx.supabase.co:5432`) only supports IPv6. This causes connection failures in CI/CD.

## Solution
Use Supabase's **Session Mode Pooler** which provides IPv4 connectivity.

## Required GitHub Actions Secret Update

You need to update the `DATABASE_URL` secret in GitHub Actions to use the pooler URL:

### Current (Direct Connection - IPv6 only):
```
postgresql://postgres:PASSWORD@db.pfkrhmprwxtghtpinrot.supabase.co:5432/postgres
```

### New (Session Pooler - IPv4 supported):
```
postgresql://postgres.pfkrhmprwxtghtpinrot:POOLER_PASSWORD@aws-1-us-west-1.pooler.supabase.com:5432/postgres
```

### How to Get the Pooler URL:
1. Go to your Supabase Dashboard
2. Click **Connect** in the top navigation
3. Select **Session Mode** (not Transaction Mode)
4. Copy the connection string
5. Update the `DATABASE_URL` secret in GitHub Actions Settings > Secrets

**Note:** The pooler connection uses a different password than the direct connection. Make sure to get the correct pooler password from the Supabase dashboard.

## Alternative Approach (Recommended)

Instead of replacing `DATABASE_URL`, you can add a separate secret:
- Create a new GitHub Actions secret called `SUPABASE_POOLER_URL`
- Set it to the session pooler connection string
- The script will automatically use it if present

This keeps your local development using the direct connection (which works fine with IPv6) while GitHub Actions uses the pooler.

## Verification

After updating the secret, trigger the **Auto Merge Queue** workflow manually to verify the connection works.

## Technical Details

- **Session Mode Pooler**: `aws-1-us-west-1.pooler.supabase.com:5432`
- **Username Format**: `postgres.PROJECT_REF` (not just `postgres`)
- **IPv4 Support**: ✅ Yes
- **IPv6 Support**: ✅ Yes (both supported)
- **Connection Pooling**: Yes (good for serverless)

The script in `scripts/find_queue_matches.py` now automatically handles both scenarios:
- Local dev: Direct connection (IPv6)
- GitHub Actions: Pooler connection (IPv4)
