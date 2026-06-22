@echo off
cd /d "C:\Users\ariim\OneDrive\Documents\Claude\Projects\Automated Podcasts"

echo Removing ALL stale lock files...
del /f ".git\index.lock" 2>nul
del /f ".git\HEAD.lock" 2>nul
del /f ".git\packed-refs.lock" 2>nul
del /f ".git\refs\heads\main.lock" 2>nul

echo Staging all changes...
git add -A

echo Committing RSS fix...
git commit -m "Fix RSS feed: add itunes:image and itunes:owner email for Spotify submission"
if %errorlevel% neq 0 (
    echo Nothing new to commit or error occurred.
) else (
    echo Commit successful!
)

echo Pushing to GitHub...
git push origin main

echo.
echo Done! Check output above for errors.
pause
