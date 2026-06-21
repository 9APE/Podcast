@echo off
cd /d "C:\Users\ariim\OneDrive\Documents\Claude\Projects\Automated Podcasts"
git config user.email "ariimoanapons@gmail.com"
git config user.name "Aurelien"

echo Removing stale lock files...
del /f ".git\index.lock" 2>nul
rmdir /s /q ".git\rebase-merge" 2>nul
rmdir /s /q ".git\rebase-apply" 2>nul

echo Staging changes...
git add -A

echo Committing...
git commit -m "Multi-topic: top 5 per channel, ranked by trending, episode IDs t1-t5"
if %errorlevel% neq 0 echo Nothing new to commit.

echo Fetching and merging remote...
git fetch origin
git merge origin/main --no-edit

echo Pushing...
git push origin main

echo.
echo Done! Press any key to close.
pause
