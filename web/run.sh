#!/usr/bin/env bash
# ApplyPilot Dynamic Frontend Launcher
set -e

PORT="${1:-8080}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting ApplyPilot Dynamic Frontend Dashboard on port ${PORT}..."

if command -v uv >/dev/null 2>&1; then
  uv run python3 "${DIR}/server.py"
elif command -v python3 >/dev/null 2>&1; then
  python3 "${DIR}/server.py"
else
  echo "Error: python3 or uv required to run the dashboard server."
  exit 1
fi
