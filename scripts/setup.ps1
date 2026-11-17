#requires -Version 7.0
<#
.SYNOPSIS
  One-time setup for Meeting Copilot (Windows / macOS / Linux, PowerShell 7).
.DESCRIPTION
  Verifies Node, Python and the Claude Code CLI, creates backend/.venv,
  installs Python requirements and npm dependencies, and creates /context.
.PARAMETER Python
  Python interpreter to build the venv with (default: python on Windows, python3 elsewhere).
.PARAMETER SkipNode
  Skip npm install (if you already ran it).
.PARAMETER Cuda
  Also install CUDA 12 runtime libs for faster-whisper (NVIDIA GPU only).
#>
[CmdletBinding()]
param(
  [string]$Python = $(if ($IsWindows) { "python" } else { "python3" }),
  [switch]$SkipNode,
  [switch]$Cuda
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

Step "Checking prerequisites"
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js not found. Install Node 20+ from https://nodejs.org" }
Ok "node $(node --version)"

$py = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python '$Python' not found. Install Python 3.10-3.12." }
$pyVer = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Ok "python $pyVer ($($py.Source))"

$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
  Ok "claude CLI: $(claude --version 2>&1 | Select-Object -First 1)"
} else {
  Warn "claude CLI not on PATH. Install with: npm install -g @anthropic-ai/claude-code  then run: claude  (log in with your Max account)"
}

if ($env:GEMINI_API_KEY) { Ok "GEMINI_API_KEY is set (fallback brain enabled)" }
else { Warn "GEMINI_API_KEY not set — Gemini fallback/summaries disabled until you set it." }

Step "Creating Python virtual environment (backend/.venv)"
$venv = Join-Path $Root "backend/.venv"
if (-not (Test-Path $venv)) { & $Python -m venv $venv }
$venvPy = if ($IsWindows) { Join-Path $venv "Scripts/python.exe" } else { Join-Path $venv "bin/python" }
Ok "venv python: $venvPy"

Step "Installing Python requirements"
& $venvPy -m pip install --upgrade pip wheel | Out-Null
& $venvPy -m pip install -r (Join-Path $Root "backend/requirements.txt")
if ($Cuda) {
  & $venvPy -m pip install "nvidia-cublas-cu12" "nvidia-cudnn-cu12"
  Ok "CUDA runtime libs installed — set stt.device to 'cuda' in config.json"
}
Ok "python deps installed"

if (-not $SkipNode) {
  Step "Installing npm dependencies (electron, ws)"
  npm install
  Ok "npm deps installed"
}

Step "Preparing /context"
$ctx = Join-Path $Root "context"
if (-not (Test-Path $ctx)) { New-Item -ItemType Directory -Path $ctx | Out-Null }
Ok "drop your .md/.txt knowledge files in: $ctx"

Step "Done"
Write-Host @"

Next (see README.md runbook):
  1. $venvPy backend/server.py --list-devices      # pick mic / loopback devices
  2. $venvPy backend/server.py --no-audio          # dry-run backend in one terminal
  3. $venvPy backend/tools/ws_probe.py "test question"   # verify Claude streaming
  4. npm start                                      # launch the HUD
"@
