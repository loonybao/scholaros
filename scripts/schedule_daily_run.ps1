<#
.SYNOPSIS
  Register (or update) a daily Windows Scheduled Task that runs the ScholarOS
  pipeline: collect enabled sources, analyze new/changed, refresh derived +
  index + vault.

.DESCRIPTION
  Run this ONCE to schedule daily updates so data never goes stale and deadlines
  do not slip by unnoticed. It only schedules; it does not run the pipeline now.

  Until a cheap OpenAI-compatible API is configured (config/models.yaml model +
  COMPASS_API_KEY / COMPASS_API_BASE_URL in .env), keep the default so the daily
  run only refreshes collected data with no token spend. Once the API is set,
  re-run with -Full for automatic analysis (the daily cost + item caps still
  apply).

.PARAMETER Time
  Daily start time, 24h "HH:mm". Default 07:00.

.PARAMETER Full
  Include the LLM analyze step (requires the API configured). Default skips LLM.

.PARAMETER Remove
  Unregister the task and exit.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\schedule_daily_run.ps1
  powershell -ExecutionPolicy Bypass -File scripts\schedule_daily_run.ps1 -Time 08:30 -Full
  powershell -ExecutionPolicy Bypass -File scripts\schedule_daily_run.ps1 -Remove
#>
param(
  [string]$Time = "07:00",
  [switch]$Full,
  [switch]$Remove
)

$ErrorActionPreference = "Stop"
$TaskName = "ScholarOS Daily Run"

if ($Remove) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed scheduled task '$TaskName'."
  return
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "venv python not found at $python. Create the virtualenv first."
}

if ($Full) { $taskArgs = "-m compass run" } else { $taskArgs = "-m compass run --skip-llm" }

$action = New-ScheduledTaskAction -Execute $python -Argument $taskArgs -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily ScholarOS collect + analyze + refresh" | Out-Null

if ($Full) { $mode = "FULL (collect + LLM analyze + refresh)" } else { $mode = "collect + refresh only (--skip-llm; no API spend)" }
Write-Host "Scheduled '$TaskName' daily at $Time."
Write-Host "  mode  : $mode"
Write-Host "  status: check the Data Health page or data/status/collector_health.json after a run"
Write-Host "  test  : $python $taskArgs"
Write-Host "  remove: powershell -File scripts\schedule_daily_run.ps1 -Remove"
