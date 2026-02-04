# ✅ ACTION REQUIRED: Update GitHub Actions Secret

## What Was Fixed
✅ Updated `scripts/find_queue_matches.py` to use proper Supabase pooler hostname  
✅ Code now supports IPv4 connections (GitHub Actions compatible)  
✅ Local development still works with direct connection  
✅ Pushed commits to main branch  

## ⚠️ Required Manual Step

**You must update the GitHub Actions secret to complete the fix:**

1. Go to: https://github.com/dallasheidt14/PitchRank/settings/secrets/actions
2. Click **Edit** on `DATABASE_URL`
3. Get the **Session Mode** pooler URL from your Supabase Dashboard:
   - Dashboard → Connect → Session Mode
   - Should look like: `postgresql://postgres.pfkrhmprwxtghtpinrot:PASSWORD@aws-1-us-west-1.pooler.supabase.com:5432/postgres`
4. Replace the current value with the pooler URL
5. Save

**OR** (Alternative):
1. Create a new secret called `SUPABASE_POOLER_URL`
2. Set it to the session pooler connection string from above
3. The script will automatically prefer this over DATABASE_URL

## Test the Fix
After updating the secret, trigger the **Auto Merge Queue** workflow to verify:
- Actions → Auto Merge Queue → Run workflow

## Why This Is Necessary
- GitHub Actions runners don't support IPv6
- The old `db.xxx.supabase.co` hostname is IPv6-only
- The pooler (`aws-1-us-west-1.pooler.supabase.com`) supports both IPv4 and IPv6
- **Different passwords**: The pooler uses a different password than direct connection

See `POOLER_SETUP.md` for detailed technical documentation.
