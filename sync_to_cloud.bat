@echo off
@chcp 65001 >nul
title 1-Click Cloud Sync (Upstox Token and Watchlist)
cd /d "%~dp0"
python sync_to_cloud.py
echo.
pause
