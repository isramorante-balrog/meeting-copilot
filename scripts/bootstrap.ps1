<#
.SYNOPSIS
  Self-contained launcher for Meeting Copilot (Windows). Runs on Windows PowerShell 5.1 or pwsh 7.
.DESCRIPTION
  Checks every dependency and installs whatever is missing (Node.js LTS, Python 3.12 via winget,
  Python packages in backend\.venv, npm packages), then launches the HUD.
  Idempotent: a second run only re-verifies and starts the app in a few seconds.
.PARAMETER NoAudio
  Start the HUD in text-only mode (no mic/loopback capture).
.PARAMETER Reinstall
  Force reinstall of Python and npm packages.
.PARAMETER NoLaunch
  Install/verify only; do not start the app.
#>
[CmdletBinding()]
param(
  [switch]$NoAudio,
  [switch]$Reinstall,
  [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$StateDir = Join-Path $Root ".copilot"
if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir | Out-Null }

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    !!  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "    XX  $m" -ForegroundColor Red }

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user    = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user;$env:Path"
}

function Has-Cmd($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Winget-Install($id, $label) {
  if (-not (Has-Cmd winget)) {
    Fail "$label is missing and winget is not available. Install $label manually, then re-run."
    throw "missing $label"
  }
  Warn "$label not found - installing with winget ($id). This can take a few minutes."
  & winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements | Out-Host
  Refresh-Path
}

# ----------------------------------------------------------------- 1. Node.js
Step "Node.js"
if (-not (Has-Cmd node)) { Winget-Install "OpenJS.NodeJS.LTS" "Node.js LTS" }
if (-not (Has-Cmd node)) { Fail "Node.js still not on PATH. Open a new terminal or reboot, then re-run."; throw "node" }
$nodeMajor = [int]((& node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 18) { Warn "Node $nodeMajor is old; Electron 33 needs >= 18. Consider: winget upgrade OpenJS.NodeJS.LTS" }
Ok "node $(& node --version)"

# ----------------------------------------------------------------- 2. Python
Step "Python"
$py = $null
foreach ($cand in @("python3.12", "python3.11", "python3.10", "python", "py")) {
  if (Has-Cmd $cand) {
    try {
      $v = & $cand -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
      if ($v -and ([version]$v -ge [version]"3.10") -and ([version]$v -le [version]"3.13")) { $py = $cand; break }
    } catch {}
  }
}
if (-not $py) {
  Winget-Install "Python.Python.3.12" "Python 3.12"
  # "python" may still be the Microsoft Store alias stub (prints nothing): only accept a candidate that really runs
  foreach ($cand in @("py", "python", "python3")) {
    if (Has-Cmd $cand) {
      try { $v = & $cand -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { $v = $null }
      if ($v -and ([version]$v -ge [version]"3.10")) { $py = $cand; break }
    }
  }
}
if (-not $py) { Fail "Python 3.10-3.13 not found after install. Re-open the terminal and re-run."; throw "python" }
Ok "$py $(& $py -c 'import sys; print(sys.version.split()[0])')"

# ----------------------------------------------------------------- 3. AI providers
# Nothing is asked in this console any more. API keys (ChatGPT / Grok / DeepSeek / Gemini), the Deepgram
# key and the primary provider are entered in the app's first-run window (Setup -> "Proveedores de IA").
# Claude Code is optional: if it is already installed and signed in, the app can use it with no key.
Step "AI providers"
if (Has-Cmd claude) { Ok "Claude Code CLI found (optional): $(& claude --version 2>&1 | Select-Object -First 1)" }
else { Ok "Claude Code CLI not installed (optional). Keys for other providers are entered inside the app." }

# ----------------------------------------------------------------- 5. Python venv + packages
Step "Python packages (backend\.venv)"
$venv = Join-Path $Root "backend\.venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Warn "creating virtual environment"
  & $py -m venv $venv | Out-Host
  if (($LASTEXITCODE -ne 0) -or -not (Test-Path $venvPy)) {
    Fail "Could not create the Python virtual environment with '$py'. Install Python 3.12 from python.org (tick 'Add to PATH'), then run again."
    throw "venv"
  }
}
$req = Join-Path $Root "backend\requirements.txt"
$reqHash = (Get-FileHash $req -Algorithm SHA256).Hash
$reqMarker = Join-Path $StateDir "requirements.sha256"
$installed = (Test-Path $reqMarker) -and ((Get-Content $reqMarker) -eq $reqHash)
if ($Reinstall -or -not $installed) {
  Warn "installing Python requirements (first time: ~2-4 min, downloads faster-whisper/ctranslate2)"
  & $venvPy -m pip install --upgrade pip wheel --quiet | Out-Host
  & $venvPy -m pip install -r $req | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "pip install failed"; throw "pip" }
  Set-Content -Path $reqMarker -Value $reqHash
}
& $venvPy -c "import faster_whisper, websockets, sounddevice, webrtcvad, numpy" 2>$null
if ($LASTEXITCODE -ne 0) { Fail "Python packages import check failed. Re-run with -Reinstall."; throw "pyimport" }
Ok "python packages present"

# ----------------------------------------------------------------- 6. npm packages
Step "npm packages (electron, ws)"
$pkgHash = (Get-FileHash (Join-Path $Root "package.json") -Algorithm SHA256).Hash
$pkgMarker = Join-Path $StateDir "package.sha256"
$electronBin = Join-Path $Root "node_modules\.bin\electron.cmd"
$npmOk = (Test-Path $electronBin) -and (Test-Path $pkgMarker) -and ((Get-Content $pkgMarker) -eq $pkgHash)
if ($Reinstall -or -not $npmOk) {
  Warn "installing npm packages (downloads Electron ~100 MB the first time)"
  & npm install --no-audit --no-fund | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "npm install failed"; throw "npm" }
  Set-Content -Path $pkgMarker -Value $pkgHash
}
Ok "electron present"

# ----------------------------------------------------------------- 7. Whisper model pre-download
Step "Whisper model"
$model = "small"
$cfgPath = Join-Path $Root "config.json"
if (Test-Path $cfgPath) {   # absent on a fresh clone: the app creates it on first save
  try { $m = (Get-Content $cfgPath -Raw | ConvertFrom-Json).stt.model_size; if ($m) { $model = $m } } catch {}
}
$modelMarker = Join-Path $StateDir "whisper_$model"
if (-not (Test-Path $modelMarker)) {
  Warn "downloading faster-whisper '$model' (one time)"
  & $venvPy -c "from faster_whisper import WhisperModel; WhisperModel('$model', device='cpu', compute_type='int8'); print('model ready')" | Out-Host
  if ($LASTEXITCODE -eq 0) { Set-Content -Path $modelMarker -Value "ok" } else { Warn "model download failed - the app will retry at startup" }
}
Ok "whisper '$model' cached"

# ----------------------------------------------------------------- 8. context folder
if (-not (Test-Path (Join-Path $Root "context"))) { New-Item -ItemType Directory -Path (Join-Path $Root "context") | Out-Null }

# ----------------------------------------------------------------- 9. launch
if ($NoLaunch) { Ok "verification complete (-NoLaunch)"; exit 0 }
Step "Launching Meeting Copilot"
Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue
Remove-Item Env:CLAUDE_CODE_ENTRYPOINT -ErrorAction SilentlyContinue
$electronArgs = @(".")
if ($NoAudio) { $electronArgs += "--no-audio" }
Start-Process -FilePath $electronBin -ArgumentList $electronArgs -WorkingDirectory $Root -WindowStyle Hidden
Ok "HUD started. Logs: $Root\logs\copilot.log  |  Tray icon: right-click for Settings / Quit"
Start-Sleep -Seconds 2
