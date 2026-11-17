@echo off
setlocal
cd /d "%~dp0"
title Meeting Copilot
if not exist "%~dp0scripts\bootstrap.ps1" (
  echo.
  echo   The app files are not next to this launcher.
  echo   If you opened it from inside the ZIP, extract the whole ZIP first ^(right-click - Extract All^),
  echo   then run "Meeting Copilot.cmd" from the extracted "meeting-copilot" folder.
  echo.
  echo   Looked in: %~dp0
  pause
  exit /b 1
)
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" %*
)
if errorlevel 1 (
  echo.
  echo Something failed above. Fix it and double-click again.
  pause
)
