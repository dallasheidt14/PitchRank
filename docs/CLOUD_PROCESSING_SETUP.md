# Cloud-Based Processing Setup for Missing Games

Since Windows Task Scheduler requires your laptop to be on, here are cloud-based alternatives:

## Option 1: Vercel Cron Jobs + External Service (Recommended)

### Setup Steps:

1. **Create a simple API endpoint** (already created at `/api/process-missing-games`)
   - This endpoint checks for pending requests
   - Can be called by Vercel Cron Jobs

2. **Set up Vercel Cron Job:**
   
   Create `vercel.json` in the `frontend` directory:
   ```json
   {
     "crons": [{
       "path": "/api/process-missing-games",
       "schedule": "*/5 * * * *"
     }]
   }
   ```
   
   This runs every 5 minutes.

3. **Set up processing service:**
   
   The API endpoint currently just checks for requests. You need to set up actual processing:
   
   **Option A: GitHub Actions** (Free, runs on GitHub's servers)
   - Create `.github/workflows/process-missing-games.yml`
   - Runs every 5 minutes
   - Executes the Python script
   - See example below
   
   **Option B: Supabase Edge Functions** (Runs in Supabase cloud)
   - Create Edge Function that processes requests
   - Can be triggered by database webhooks
   - See Supabase docs for Edge Functions
   
   **Option C: AWS Lambda / Google Cloud Functions** (Pay-as-you-go)
   - Deploy Python script as serverless function
   - Trigger via API call from Vercel Cron

## Option 2: GitHub Actions (Free & Easy)

Create `.github/workflows/process-missing-games.yml`:

```yaml
name: Process Missing Games

on:
  schedule:
    # Run every 5 minutes
    - cron: '*/5 * * * *'
  workflow_dispatch: # Allow manual trigger

jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Process missing games
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: |
          python scripts/process_missing_games.py --limit 10
```

**Setup:**
1. Go to GitHub repo → Settings → Secrets and variables → Actions
2. Add secrets:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
3. Commit the workflow file
4. GitHub will run it automatically every 5 minutes

## Option 3: Supabase Edge Functions

Create `supabase/functions/process-missing-games/index.ts`:

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

serve(async (req) => {
  try {
    const supabaseUrl = Deno.env.get('SUPABASE_URL')!
    const supabaseKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    
    const supabase = createClient(supabaseUrl, supabaseKey)
    
    // Get pending requests
    const { data: requests } = await supabase
      .from('scrape_requests')
      .select('*')
      .eq('status', 'pending')
      .limit(10)
    
    // Process requests (you'd need to implement the scraping logic here)
    // Or call an external API that runs your Python script
    
    return new Response(
      JSON.stringify({ processed: requests?.length || 0 }),
      { headers: { "Content-Type": "application/json" } }
    )
  } catch (error) {
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    )
  }
})
```

Then set up pg_cron to call it:
```sql
SELECT cron.schedule(
  'process-missing-games',
  '*/5 * * * *',
  $$
  SELECT net.http_post(
    url := 'https://your-project.supabase.co/functions/v1/process-missing-games',
    headers := '{"Authorization": "Bearer YOUR_ANON_KEY"}'::jsonb
  );
  $$
);
```

## Option 4: Always-On VPS (Simple but costs money)

- DigitalOcean Droplet ($6/month)
- AWS EC2 t2.micro (Free tier available)
- Azure VM (Free tier available)

Install Python, clone repo, set up cron job. Runs 24/7.

## Recommendation

**For your use case, GitHub Actions (Option 2) is the best choice:**
- ✅ Free
- ✅ Runs in the cloud (no laptop needed)
- ✅ Easy to set up
- ✅ Can use your existing Python script
- ✅ Automatic scheduling
- ✅ Logs available in GitHub Actions tab

The workflow will run every 5 minutes, check for pending requests, and process them automatically - all without your laptop being on!

