# Setting Up Windows Task Scheduler for PitchRank

## Quick Setup (Automated)

### Option 1: PowerShell Script (Recommended)

1. **Open PowerShell as Administrator**
   - Press `Win + X`
   - Select "Windows PowerShell (Admin)" or "Terminal (Admin)"

2. **Navigate to project directory**
   ```powershell
   cd C:\PitchRank
   ```

3. **Run the setup script**
   ```powershell
   .\scripts\setup_scheduled_task.ps1
   ```

4. **Customize (optional)**
   ```powershell
   # Change day and time
   .\scripts\setup_scheduled_task.ps1 -DayOfWeek "Monday" -Time "03:00"
   
   # Scrape & import only (skip rankings)
   .\scripts\setup_scheduled_task.ps1 -SkipRankings
   
   # Custom project path
   .\scripts\setup_scheduled_task.ps1 -ProjectPath "D:\MyProjects\PitchRank"
   ```

### Option 2: Manual Setup via GUI

1. **Open Task Scheduler**
   - Press `Win + R`
   - Type `taskschd.msc` and press Enter

2. **Create Basic Task**
   - Click "Create Basic Task" in the right panel
   - Name: `PitchRank Weekly Scrape & Import`
   - Description: `Weekly automation: Scrape games from GotSport and auto-import to database`

3. **Set Trigger**
   - Trigger: **Weekly**
   - Start date: Choose a date
   - Time: `02:00` (or your preferred time)
   - Recur every: `1` week
   - Day: **Sunday** (or your preferred day)

4. **Set Action**
   - Action: **Start a program**
   - Program/script: `python` (or full path: `C:\Python313\python.exe`)
   - Add arguments: `scripts\scrape_games.py --auto-import`
   - Start in: `C:\PitchRank` (your project path)

5. **Set Conditions**
   - ✅ Check "Start the task only if the computer is on AC power" (optional)
   - ✅ Check "Wake the computer to run this task" (optional)
   - ✅ Check "Start only if the following network connection is available" → Any connection

6. **Set Settings**
   - ✅ Check "Allow task to be run on demand"
   - ✅ Check "Run task as soon as possible after a scheduled start is missed"
   - ✅ Check "If the task fails, restart every: 1 hour" (optional)
   - ✅ Check "If the running task does not end when requested, force it to stop"

7. **Click Finish**

## What Gets Scheduled

### Default (Full Weekly Update)
- **Script**: `scripts/weekly/update.py`
- **Actions**:
  1. Scrape games (incremental, teams not updated in last 7 days)
  2. Auto-import scraped games
  3. Recalculate rankings

### Scrape & Import Only (Skip Rankings)
- **Script**: `scripts/scrape_games.py --auto-import`
- **Actions**:
  1. Scrape games (incremental)
  2. Auto-import scraped games

## Testing the Task

1. **Open Task Scheduler**
2. **Find your task**: `PitchRank Weekly Scrape & Import`
3. **Right-click** → **Run**
4. **Check logs**: `logs/weekly_update_YYYYMMDD.log` (for full update) or console output

## Viewing Task History

1. Open Task Scheduler
2. Select your task
3. Click "History" tab at the bottom
4. Look for execution results

## Troubleshooting

### Task Not Running
- Check if Python is in PATH (or use full path to python.exe)
- Verify project path is correct
- Check "History" tab in Task Scheduler for errors
- Ensure `.env.local` file exists with proper credentials

### Permission Issues
- Run PowerShell as Administrator when creating the task
- Task runs as your user account (should have necessary permissions)

### Python Not Found
- Use full path: `C:\Python313\python.exe` instead of `python`
- Or add Python to system PATH

### Logs Location
- Full update logs: `logs/weekly_update_YYYYMMDD.log`
- Scraper logs: Console output (can be redirected to file)

## Removing the Task

### Via PowerShell
```powershell
Unregister-ScheduledTask -TaskName "PitchRank Weekly Scrape & Import" -Confirm:$false
```

### Via GUI
1. Open Task Scheduler
2. Find the task
3. Right-click → Delete

## Advanced: Multiple Tasks

You can create separate tasks for different schedules:

```powershell
# Daily scrape (lightweight)
.\scripts\setup_scheduled_task.ps1 -DayOfWeek "Monday" -Time "02:00" -SkipRankings -ProjectPath "C:\PitchRank"

# Weekly full update
.\scripts\setup_scheduled_task.ps1 -DayOfWeek "Sunday" -Time "03:00" -ProjectPath "C:\PitchRank"
```

