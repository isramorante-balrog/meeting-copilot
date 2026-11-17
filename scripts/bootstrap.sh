#!/usr/bin/env bash
# Self-contained launcher for macOS / Linux. Idempotent.
#   ./scripts/bootstrap.sh [--no-audio] [--reinstall] [--no-launch]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
STATE="$ROOT/.copilot"; mkdir -p "$STATE" context logs
NO_AUDIO=0; REINSTALL=0; NO_LAUNCH=0
for a in "$@"; do case "$a" in --no-audio) NO_AUDIO=1;; --reinstall) REINSTALL=1;; --no-launch) NO_LAUNCH=1;; esac; done
step(){ printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok(){ printf '    \033[32mOK  %s\033[0m\n' "$1"; }
warn(){ printf '    \033[33m!!  %s\033[0m\n' "$1"; }
have(){ command -v "$1" >/dev/null 2>&1; }
OS="$(uname -s)"

brew_install(){ # $1 formula/cask  $2 label
  if ! have brew; then
    if [ "$OS" = "Darwin" ]; then
      warn "Homebrew missing - installing (needed to install $2)"
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
    else
      echo "Install $2 with your package manager (apt/dnf/pacman) and re-run."; exit 1
    fi
  fi
  warn "$2 missing - brew install $1"; brew install "$1"
}

step "Node.js"
have node || brew_install node "Node.js"
ok "node $(node --version)"

step "Python"
PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if have "$c" && "$c" -c 'import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then brew_install python@3.12 "Python 3.12"; PY=python3.12; fi
ok "$PY $($PY -c 'import sys;print(sys.version.split()[0])')"
if [ "$OS" = "Darwin" ] && ! have portaudio-config && ! ls /opt/homebrew/lib/libportaudio* /usr/local/lib/libportaudio* >/dev/null 2>&1; then
  brew_install portaudio "PortAudio (for sounddevice)"
fi

step "AI providers"
# API keys and the primary AI provider are entered in the app (first-run window), not here.
if have claude; then ok "Claude Code CLI found (optional)"; else ok "Claude Code CLI not installed (optional)"; fi

step "Python packages (backend/.venv)"
VENV="$ROOT/backend/.venv"; VPY="$VENV/bin/python"
[ -x "$VPY" ] || { warn "creating venv"; "$PY" -m venv "$VENV"; }
REQ="$ROOT/backend/requirements.txt"
HASH="$(shasum -a 256 "$REQ" | cut -d' ' -f1)"
if [ "$REINSTALL" = 1 ] || [ "$(cat "$STATE/requirements.sha256" 2>/dev/null || true)" != "$HASH" ]; then
  warn "installing Python requirements (first time: a few minutes)"
  "$VPY" -m pip install --upgrade pip wheel --quiet
  "$VPY" -m pip install -r "$REQ"
  echo "$HASH" > "$STATE/requirements.sha256"
fi
"$VPY" -c "import faster_whisper, websockets, sounddevice, webrtcvad, numpy" && ok "python packages present"

step "npm packages (electron, ws)"
PHASH="$(shasum -a 256 package.json | cut -d' ' -f1)"
if [ "$REINSTALL" = 1 ] || [ ! -x node_modules/.bin/electron ] || [ "$(cat "$STATE/package.sha256" 2>/dev/null || true)" != "$PHASH" ]; then
  warn "npm install (downloads Electron the first time)"; npm install --no-audit --no-fund
  echo "$PHASH" > "$STATE/package.sha256"
fi
ok "electron present"

step "Whisper model"
MODEL="$("$VPY" -c "import json,os;print((json.load(open('config.json')).get('stt') or {}).get('model_size','small') if os.path.exists('config.json') else 'small')" 2>/dev/null || echo small)"
if [ ! -f "$STATE/whisper_$MODEL" ]; then
  warn "downloading faster-whisper '$MODEL' (one time)"
  "$VPY" -c "from faster_whisper import WhisperModel; WhisperModel('$MODEL', device='cpu', compute_type='int8')" && touch "$STATE/whisper_$MODEL" || warn "download failed; app retries at startup"
fi
ok "whisper '$MODEL' cached"

if [ "$OS" = "Darwin" ] && ! "$VPY" -c "import sounddevice as sd; import sys; sys.exit(0 if any('blackhole' in d['name'].lower() for d in sd.query_devices()) else 1)" 2>/dev/null; then
  warn "BlackHole virtual audio device not found: system-audio (THEM) capture needs it. Install: brew install blackhole-2ch, then route Zoom/Teams output to a Multi-Output Device."
fi

[ "$NO_LAUNCH" = 1 ] && { ok "verification complete"; exit 0; }
step "Launching Meeting Copilot"
unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT
ARGS=(.); [ "$NO_AUDIO" = 1 ] && ARGS+=(--no-audio)
nohup node_modules/.bin/electron "${ARGS[@]}" >> logs/launcher.log 2>&1 &
ok "HUD started. Logs: $ROOT/logs/copilot.log"
sleep 2
