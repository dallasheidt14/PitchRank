# PowerShell script to set up Windows Task Scheduler for Processing Missing Games Requests
# Run this script as Administrator: Right-click PowerShell -> Run as Administrator

param(
    [string]$ProjectPath = "C:\PitchRank",
    [int]$IntervalMinutes = 5
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PitchRank Missing Games Processor Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Verify project path exists
if (-not (Test-Path $ProjectPath)) {
    Write-Host "ERROR: Project path not found: $ProjectPath" -ForegroundColor Red
    Write-Host "Please update the ProjectPath parameter or create the directory." -ForegroundColor Yellow
    exit 1
}

# Find Python executable
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    Write-Host "ERROR: Python not found in PATH!" -ForegroundColor Red
    Write-Host "Please ensure Python is installed and added to PATH." -ForegroundColor Yellow
    exit 1
}

# Verify the script exists
$scriptPath = Join-Path $ProjectPath "scripts\process_missing_games.py"
if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: Script not found: $scriptPath" -ForegroundColor Red
    Write-Host "Please ensure the process_missing_games.py script exists." -ForegroundColor Yellow
    exit 1
}

Write-Host "Configuration:" -ForegroundColor Green
Write-Host "  Project Path: $ProjectPath" -ForegroundColor White
Write-Host "  Python Path: $pythonPath" -ForegroundColor White
Write-Host "  Script: $scriptPath" -ForegroundColor White
Write-Host "  Interval: Every $IntervalMinutes minutes" -ForegroundColor White
Write-Host ""

# Task name
$taskName = "PitchRank Process Missing Games"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Task '$taskName' already exists!" -ForegroundColor Yellow
    $response = Read-Host "Do you want to delete and recreate it? (Y/N)"
    if ($response -eq "Y" -or $response -eq "y") {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Deleted existing task." -ForegroundColor Green
    } else {
        Write-Host "Cancelled. Exiting." -ForegroundColor Yellow
        exit 0
    }
}

Write-Host "Creating scheduled task..." -ForegroundColor Cyan

# Create action
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$scriptPath`" --limit 10" `
    -WorkingDirectory $ProjectPath

# Create trigger (repeating every X minutes)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 365)

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Create principal (run as current user)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType ServiceAccount -RunLevel Highest

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Automatically process pending missing game requests from scrape_requests table. Runs every $IntervalMinutes minutes." `
        -Force | Out-Null
    
    Write-Host "✅ Task created successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Details:" -ForegroundColor Cyan
    Write-Host "  Name: $taskName" -ForegroundColor White
    Write-Host "  Schedule: Every $IntervalMinutes minutes" -ForegroundColor White
    Write-Host "  Script: $scriptPath" -ForegroundColor White
    Write-Host ""
    Write-Host "The task will:" -ForegroundColor Yellow
    Write-Host "  - Check for pending scrape requests every $IntervalMinutes minutes" -ForegroundColor White
    Write-Host "  - Process up to 10 requests per run (to avoid overload)" -ForegroundColor White
    Write-Host "  - Scrape and import missing games automatically" -ForegroundColor White
    Write-Host ""
    Write-Host "To view the task:" -ForegroundColor Yellow
    Write-Host "  Open Task Scheduler (taskschd.msc)" -ForegroundColor White
    Write-Host "  Look for: '$taskName'" -ForegroundColor White
    Write-Host ""
    Write-Host "To test the task:" -ForegroundColor Yellow
    Write-Host "  Right-click the task -> Run" -ForegroundColor White
    Write-Host ""
    Write-Host "To delete the task:" -ForegroundColor Yellow
    Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false" -ForegroundColor White
    Write-Host ""
    Write-Host "To check pending requests:" -ForegroundColor Yellow
    Write-Host "  Run this SQL in Supabase:" -ForegroundColor White
    Write-Host "  SELECT * FROM scrape_requests WHERE status = 'pending';" -ForegroundColor Gray
    
} catch {
    Write-Host "ERROR: Failed to create task: $_" -ForegroundColor Red
    exit 1
}

