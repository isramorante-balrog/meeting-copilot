#requires -Version 7.0
<#
.SYNOPSIS
  Launch the Meeting Copilot HUD (Electron spawns the Python backend itself).
.PARAMETER NoAudio
  Start without microphone/loopback capture (use ws_probe.py to inject text).
.PARAMETER DebugTools
  Open Electron DevTools and verbose logging.
#>
[CmdletBinding()]
param(
  [switch]$NoAudio,
  [switch]$DebugTools
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$electronArgs = @(".")
if ($NoAudio)    { $electronArgs += "--no-audio" }
if ($DebugTools) { $electronArgs += "--debug" }

# Never inherit an outer Claude Code session marker (claude -p refuses to nest).
Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue
Remove-Item Env:CLAUDE_CODE_ENTRYPOINT -ErrorAction SilentlyContinue

Write-Host "Starting Meeting Copilot HUD..." -ForegroundColor Cyan
npx electron @electronArgs
