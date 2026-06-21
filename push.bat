@echo off
cd /d "C:\Users\ariim\OneDrive\Documents\Claude\Projects\Automated Podcasts"
git config user.email "ariimoanapons@gmail.com"
git config user.name "Aurelien"

echo Removing stale lock files...
del /f ".git\index.lock" 2>nul
del /f ".git\refs\heads\main.lock" 2>nul
rmdir /s /q ".git\rebase-merge" 2>nul
rmdir /s /q ".git\rebase-apply" 2>nul

echo Checking out main...
git checkout main 2>nul || git checkout -b main

echo Staging changes...
git add -A

echo Committing...
git commit -m "Switch to OpenAI TTS dual-voice (onyx/nova), drop ElevenLabs"
if %errorlevel% neq 0 echo Nothing new to commit.

echo Fetching remote...
git fetch origin

echo Merging remote changes...
git merge origin/main --no-edit

echo Pushing...
git push origin main

echo.
echo Done! Press any key to close.
pause
