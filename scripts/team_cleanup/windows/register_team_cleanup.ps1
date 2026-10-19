param([switch]$RunNow)
# Registers the weekly team cleanup's autopilot: one tick of scripts\team_cleanup\advance.py every hour,
# as the signed-in user, from C:\pitchrank-weekly. Run it once; -RunNow also starts a tick now.
# Pause the autopilot by creating autopilot.paused in the run store; delete the file to resume.
$ErrorActionPreference = 'Stop'
$name = 'PitchRank Team Cleanup Autopilot'
$store = Join-Path $env:USERPROFILE 'pitchrank-cleanup-runs'
New-Item -ItemType Directory -Force -Path $store | Out-Null
# The task runs a copy kept outside the checkout, which a tick may move to newer code.
$tick = Join-Path $store 'team_cleanup_tick.cmd'
Copy-Item -Force (Join-Path $PSScriptRoot 'team_cleanup_tick.cmd') $tick
$python = (Get-Command python).Source
"Python: $python"
$action = New-ScheduledTaskAction -Execute $tick -Argument "`"$python`"" -WorkingDirectory 'C:\pitchrank-weekly'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(17) -RepetitionInterval (New-TimeSpan -Hours 1)
# A laptop: without the battery switches Windows skips every tick while it is unplugged and stops a running
# one, mid-apply, when it is unplugged. Each step stops itself at four hours, so only a tick of six or more
# such steps meets the 23-hour limit.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 23) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State | Format-Table -AutoSize
(Get-ScheduledTaskInfo -TaskName $name).NextRunTime
if ($RunNow) { Start-ScheduledTask -TaskName $name; "Started $name now." }
