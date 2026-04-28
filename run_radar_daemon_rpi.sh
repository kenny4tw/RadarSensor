#!/usr/bin/env bash
# Launcher script for radar sensor daemon on Raspberry Pi
# This script activates the virtual environment and starts the daemon

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find Python
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif [[ -x ".venv/bin/python3" ]]; then
  PYTHON=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "ERROR: Python not found. Install Python 3.10+ first." >&2
  exit 1
fi

# Start the daemon
exec "$PYTHON" "$SCRIPT_DIR/pi_radar_daemon.py" --config "$SCRIPT_DIR/sensors_rpi.json" "$@"
