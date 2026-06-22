Set-Location "C:\Users\ariim\OneDrive\Documents\Claude\Projects\Automated Podcasts"

Write-Host "Cleaning up any stuck merge or lock files..." -ForegroundColor Cyan
if (Test-Path ".git\MERGE_HEAD")       { Remove-Item ".git\MERGE_HEAD" -Force }
if (Test-Path ".git\index.lock")       { Remove-Item ".git\index.lock" -Force }
if (Test-Path ".git\HEAD.lock")        { Remove-Item ".git\HEAD.lock" -Force }
if (Test-Path ".git\packed-refs.lock") { Remove-Item ".git\packed-refs.lock" -Force }
if (Test-Path ".git\refs\heads\main.lock") { Remove-Item ".git\refs\heads\main.lock" -Force }

Write-Host "Staging all changes..." -ForegroundColor Cyan
git add -A

$status = git diff --staged --quiet 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Nothing new to commit." -ForegroundColor Yellow
} else {
    $msg = Read-Host "Commit message (press Enter for default)"
    if ([string]::IsNullOrWhiteSpace($msg)) { $msg = "Update pipeline" }
    git commit -m $msg
    Write-Host "Committed." -ForegroundColor Green
}

Write-Host "Pulling remote changes..." -ForegroundColor Cyan
git pull origin main --no-rebase -X ours

Write-Host "Pushing to GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nDone! All changes pushed." -ForegroundColor Green
} else {
    Write-Host "Push failed - check output above." -ForegroundColor Red
}

Read-Host "Press Enter to close"
