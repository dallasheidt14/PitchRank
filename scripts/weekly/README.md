# Windows Task Scheduler Configuration for PitchRank Weekly Updates

## Setup Instructions

### Option 1: Windows Task Scheduler (Recommended)

1. **Open Task Scheduler**
   - Press `Win + R`, type `taskschd.msc`, press Enter

2. **Create Basic Task**
   - Click "Create Basic Task" in the right panel
   - Name: "PitchRank Weekly Update"
   - Description: "Weekly automation for scraping, importing, and recalculating rankings"

3. **Set Trigger**
   - Trigger: Weekly
   - Start date: Choose a date
   - Time: Choose a time (e.g., Sunday 2:00 AM)
   - Recur every: 1 week
   - Day: Sunday (or your preferred day)

4. **Set Action**
   - Action: Start a program
   - Program/script: `python`
   - Add arguments: `scripts\weekly\update.py --games-file "data\master\all_games_master.csv"`
   - Start in: `C:\PitchRank` (or your project path)

5. **Set Conditions**
   - Uncheck "Start the task only if the computer is on AC power" (if you want it to run on battery)
   - Check "Wake the computer to run this task" (optional)

6. **Set Settings**
   - Check "Run task as soon as possible after a scheduled start is missed"
   - Check "If the task fails, restart every: 1 hour" (optional)

### Option 2: Manual Execution

Run manually:
```bash
python scripts/weekly/update.py --games-file data/master/all_games_master.csv
```

### Option 3: PowerShell Scheduled Job

Create a PowerShell script:
```powershell
# weekly_update.ps1
$scriptPath = "C:\PitchRank\scripts\weekly\update.py"
$gamesFile = "C:\PitchRank\data\master\all_games_master.csv"

python $scriptPath --games-file $gamesFile
```

Then schedule it:
```powershell
$trigger = New-JobTrigger -Weekly -DaysOfWeek Sunday -At 2am
Register-ScheduledJob -Name "PitchRankWeeklyUpdate" -ScriptBlock {
    python C:\PitchRank\scripts\weekly\update.py --games-file C:\PitchRank\data\master\all_games_master.csv
} -Trigger $trigger
```

## Usage Examples

### Full Update (Scrape → Import → Rankings)
```bash
python scripts/weekly/update.py --games-file data/master/all_games_master.csv
```

### Import Only (Skip Scraping)
```bash
python scripts/weekly/update.py --skip-scrape --games-file data/new_games.csv
```

### Rankings Only (Skip Scrape & Import)
```bash
python scripts/weekly/update.py --skip-scrape --skip-import
```

### v53e Only (No ML Enhancement)
```bash
python scripts/weekly/update.py --no-ml --games-file data/master/all_games_master.csv
```

## Logs

Logs are saved to: `logs/weekly_update_YYYYMMDD.log`

## Future: When Scrapers Are Implemented

Once scrapers are fully implemented, you can remove the `--games-file` argument and the script will automatically scrape from providers:

```bash
python scripts/weekly/update.py --provider gotsport
```

