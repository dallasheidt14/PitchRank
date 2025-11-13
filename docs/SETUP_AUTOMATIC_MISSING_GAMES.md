# Setting Up Automatic Processing for Missing Games Requests

This guide explains how to automatically process user-submitted missing game requests.

## Option 1: Scheduled Task (Recommended for Most Users)

Run the Python script periodically to check for and process pending requests.

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task:
   - Name: "Process Missing Games Requests"
   - Trigger: Every 5 minutes (or your preferred interval)
   - Action: Start a program
   - Program: `python` (or full path to Python executable)
   - Arguments: `C:\PitchRank\scripts\process_missing_games.py`
   - Start in: `C:\PitchRank`

### Linux/Mac Cron

Add to crontab (`crontab -e`):

```bash
# Process missing games every 5 minutes
*/5 * * * * cd /path/to/PitchRank && python3 scripts/process_missing_games.py >> logs/missing_games.log 2>&1
```

### Using the Existing Scheduled Task Setup

You can modify `scripts/setup_scheduled_task.ps1` to include processing missing games:

```powershell
# Add to your existing scheduled task
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\PitchRank\scripts\process_missing_games.py" -WorkingDirectory "C:\PitchRank"
```

## Option 2: Supabase Database Webhook (Advanced)

Set up a webhook that triggers when a new scrape_request is created.

### Prerequisites

- A webhook endpoint that can receive POST requests
- The endpoint should trigger the Python script processing

### Setup Steps

1. **Create a Webhook Endpoint**

   You'll need to create an API endpoint (could be a simple Flask/FastAPI server) that:
   - Receives webhook POST requests from Supabase
   - Triggers processing of pending requests
   - Returns success response

2. **Configure Supabase Webhook**

   - Go to Supabase Dashboard → Database → Webhooks
   - Create new webhook:
     - Name: "Process Missing Games"
     - Table: `scrape_requests`
     - Events: INSERT
     - HTTP Request:
       - URL: Your webhook endpoint URL
       - Method: POST
       - Headers: `Authorization: Bearer YOUR_SECRET`

3. **Webhook Payload**

   Supabase will send:
   ```json
   {
     "type": "INSERT",
     "table": "scrape_requests",
     "record": {
       "id": "...",
       "team_id_master": "...",
       "game_date": "2024-01-15",
       "status": "pending",
       ...
     }
   }
   ```

## Option 3: Supabase pg_cron (If Available)

If your Supabase instance has pg_cron extension enabled:

```sql
-- Schedule processing every 5 minutes
SELECT cron.schedule(
  'process-missing-games',
  '*/5 * * * *',  -- Every 5 minutes
  $$
  -- This would need to call an external function or webhook
  -- since pg_cron can't directly run Python scripts
  SELECT net.http_post(
    url := 'https://your-webhook-endpoint.com/process',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body := '{}'::jsonb
  );
  $$
);
```

## Recommended Approach

**For most users, Option 1 (Scheduled Task) is recommended** because:
- Simple to set up
- No additional infrastructure needed
- Works with existing Python scripts
- Easy to monitor and debug

The scheduled task will check for pending requests every few minutes and process them automatically.

## Monitoring

Check processing status:

```sql
-- View pending requests
SELECT * FROM scrape_requests WHERE status = 'pending';

-- View recent processing activity
SELECT 
  status,
  COUNT(*) as count,
  MAX(requested_at) as latest_request
FROM scrape_requests
GROUP BY status;

-- View failed requests
SELECT * FROM scrape_requests 
WHERE status = 'failed' 
ORDER BY requested_at DESC 
LIMIT 10;
```

## Troubleshooting

1. **Script not running**: Check scheduled task is enabled and Python path is correct
2. **No requests processed**: Verify there are pending requests in the database
3. **Processing fails**: Check error_message column in scrape_requests table
4. **Rate limiting**: Adjust the scheduled task interval if hitting API limits

