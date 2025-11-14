# Weekly Update GitHub Action Setup

## Overview
The `weekly-update.yml` workflow automatically runs the PitchRank weekly update every Monday at 12:01 AM Pacific Time.

## Schedule
- **Cron**: `1 8 * * 1` (Every Monday at 8:01 AM UTC)
- **Pacific Time**: 
  - During PST (UTC-8): Runs at 12:01 AM PST ✅
  - During PDT (UTC-7): Runs at 1:01 AM PDT (1 hour later)

## Required GitHub Secrets
Make sure these secrets are configured in your GitHub repository settings:

1. **SUPABASE_URL** - Your Supabase project URL
2. **SUPABASE_SERVICE_KEY** - Your Supabase service role key (used for both SUPABASE_SERVICE_KEY and SUPABASE_SERVICE_ROLE_KEY)

### How to Add Secrets
1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each secret with the exact names above

## What the Workflow Does
1. **Scrape Games**: Fetches new games from GotSport
2. **Import Games**: Imports scraped games into Supabase database
3. **Recalculate Rankings**: Recalculates team rankings with ML-enhanced algorithm

## Manual Trigger
You can also trigger this workflow manually:
1. Go to **Actions** tab in GitHub
2. Select **Weekly Update** workflow
3. Click **Run workflow** button

## Logs
- Logs are automatically uploaded as artifacts after each run
- Logs are retained for 30 days
- Check the **Actions** tab to view run history and logs

## Timeout
The workflow has a 2-hour timeout to accommodate the full update process.

## Troubleshooting
- If the workflow fails, check the logs in the Actions tab
- Verify all secrets are correctly configured
- Ensure Supabase credentials have proper permissions
- Check that all Python dependencies are installed correctly

