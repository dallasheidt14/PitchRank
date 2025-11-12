# PowerShell script to set up Windows Task Scheduler for PitchRank Weekly Scrape & Import
# Run this script as Administrator: Right-click PowerShell -> Run as Administrator

param(
    [string]$ProjectPath = "C:\PitchRank",
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "02:00",
    [switch]$SkipRankings = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PitchRank Task Scheduler Setup" -ForegroundColor Cyan
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

Write-Host "Configuration:" -ForegroundColor Green
Write-Host "  Project Path: $ProjectPath" -ForegroundColor White
Write-Host "  Python Path: $pythonPath" -ForegroundColor White
Write-Host "  Day: $DayOfWeek" -ForegroundColor White
Write-Host "  Time: $Time" -ForegroundColor White
Write-Host ""

# Task name
$taskName = "PitchRank Weekly Scrape & Import"

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

# Determine script and arguments
if ($SkipRankings) {
    # Just scrape and import (no rankings)
    $scriptPath = Join-Path $ProjectPath "scripts\scrape_games.py"
    $arguments = "--auto-import"
    $description = "Weekly automation: Scrape games from GotSport and auto-import to database"
} else {
    # Full weekly update (scrape, import, rankings)
    $scriptPath = Join-Path $ProjectPath "scripts\weekly\update.py"
    $arguments = ""
    $description = "Weekly automation: Scrape games, import to database, and recalculate rankings"
}

Write-Host "Creating scheduled task..." -ForegroundColor Cyan
Write-Host "  Script: $scriptPath" -ForegroundColor White
Write-Host "  Arguments: $arguments" -ForegroundColor White
Write-Host ""

# Create action
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$scriptPath`" $arguments" `
    -WorkingDirectory $ProjectPath

# Create trigger (weekly)
$daysOfWeekMap = @{
    "Sunday" = [DayOfWeek]::Sunday
    "Monday" = [DayOfWeek]::Monday
    "Tuesday" = [DayOfWeek]::Tuesday
    "Wednesday" = [DayOfWeek]::Wednesday
    "Thursday" = [DayOfWeek]::Thursday
    "Friday" = [DayOfWeek]::Friday
    "Saturday" = [DayOfWeek]::Saturday
}

if (-not $daysOfWeekMap.ContainsKey($DayOfWeek)) {
    Write-Host "ERROR: Invalid day of week: $DayOfWeek" -ForegroundColor Red
    Write-Host "Valid options: Sunday, Monday, Tuesday, Wednesday, Thursday, Friday, Saturday" -ForegroundColor Yellow
    exit 1
}

$dayOfWeekEnum = $daysOfWeekMap[$DayOfWeek]
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dayOfWeekEnum -At $Time

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -WakeToRun

# Create principal (run as current user)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $description `
        -Force | Out-Null
    
    Write-Host "✅ Task created successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Details:" -ForegroundColor Cyan
    Write-Host "  Name: $taskName" -ForegroundColor White
    Write-Host "  Schedule: Every $DayOfWeek at $Time" -ForegroundColor White
    Write-Host "  Script: $scriptPath" -ForegroundColor White
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
    
} catch {
    Write-Host "ERROR: Failed to create task: $_" -ForegroundColor Red
    exit 1
}

