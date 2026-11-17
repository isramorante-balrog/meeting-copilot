#!/usr/bin/env bash
# Double-click launcher for macOS (and Linux). Installs missing dependencies, then starts the HUD.
set -e
cd "$(dirname "$0")"
exec bash scripts/bootstrap.sh "$@"
