@echo off
setlocal
cd /d "%~dp0"
title Meeting Copilot
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\bootstrap.ps1" %*
)
if errorlevel 1 (
  echo.
  echo Something failed above. Fix it and double-click again.
  pause
)
