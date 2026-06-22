Set-Location "C:\Users\ariim\OneDrive\Documents\Claude\Projects\Automated Podcasts"

Write-Host "=== Setup: Auto Cookie Refresh ===" -ForegroundColor Cyan
Write-Host ""

$pat = Read-Host "Paste your GitHub PAT (repo scope)"
if ([string]::IsNullOrWhiteSpace($pat)) {
    Write-Host "No PAT entered. Exiting." -ForegroundColor Red
    exit 1
}

# Save PAT
$pat | Out-File -FilePath ".github_pat" -NoNewline -Encoding utf8
Write-Host "PAT saved." -ForegroundColor Green

# Find python path
$pythonCmd = (Get-Command python -ErrorAction SilentlyContinue)
if ($pythonCmd) {
    $python = $pythonCmd.Source
} else {
    $python = "python"
}

# Create scheduled task
$scriptPath = (Resolve-Path "auto_refresh_cookies.py").Path
$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$scriptPath`"" -WorkingDirectory (Get-Location).Path
$trigger  = New-ScheduledTaskTrigger -Daily -DaysInterval 10 -At "09:00AM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable

Register-ScheduledTask -TaskName "PodcastCookieRefresh" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "Scheduled task created: runs every 10 days at 9 AM." -ForegroundColor Green

# Test immediately
Write-Host ""
Write-Host "Testing now..." -ForegroundColor Cyan
python auto_refresh_cookies.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "All good! Fully automatic from now on." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Something went wrong - check output above." -ForegroundColor Red
}

Read-Host "Press Enter to close"
