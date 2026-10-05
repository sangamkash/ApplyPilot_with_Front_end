#!/usr/bin/env bash
# ApplyPilot Dynamic Frontend Launcher
set -euo pipefail

PORT="${1:-${PORT:-8080}}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${DIR}/.." && pwd)"
export PORT

echo "Starting ApplyPilot Dynamic Frontend Dashboard on port ${PORT}..."
echo "Access URL: http://localhost:${PORT}"

if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
  "${REPO_DIR}/.venv/bin/python" "${DIR}/server.py"
elif command -v uv >/dev/null 2>&1; then
  uv run python3 "${DIR}/server.py"
elif command -v python3 >/dev/null 2>&1; then
  python3 "${DIR}/server.py"
else
  echo "Error: python3, uv, or a valid .venv required to run the dashboard server."
  exit 1
fi

