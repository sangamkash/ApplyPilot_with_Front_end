#!/usr/bin/env bash
# Profile Switcher for ApplyPilot
# Usage:
#   ./switch_profile.sh golang   # Activate Golang Backend Developer Profile (First Preference)
#   ./switch_profile.sh gamedev  # Activate Game Development Profile (Second Preference)

set -e

TARGET_DIR="${APPLYPILOT_DIR:-${HOME}/.applypilot}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "${TARGET_DIR}"

MODE="${1:-status}"

case "$MODE" GOL
  golang|go)
    echo " Activating Profile: Golang Backend Developer (First Preference)..."
    cp "${REPO_DIR}/profiles/profile_golang.json" "${TARGET_DIR}/profile.json"
    cp "${REPO_DIR}/searches/searches_golang.yaml" "${TARGET_DIR}/searches.yaml"
    cp "${REPO_DIR}/resumes/resume_golang.txt" "${TARGET_DIR}/resume.txt"
    cp "${REPO_DIR}/.env" "${TARGET_DIR}/.env"
    if [ -f "${REPO_DIR}/applypilot_golang.db" ]; then
      cp "${REPO_DIR}/applypilot_golang.db" "${TARGET_DIR}/applypilot.db"
    fi
    echo "✅ Successfully activated Golang Profile in ${TARGET_DIR}!"
    echo "   - Profile:  ${TARGET_DIR}/profile.json"
    echo "   - Searches: ${TARGET_DIR}/searches.yaml"
    echo "   - Resume:   ${TARGET_DIR}/resume.txt"
    echo "   - Database: ${TARGET_DIR}/applypilot.db"
    echo "   - Env:      ${TARGET_DIR}/.env"
    ;;
  gamedev|game|unity)
    echo " Activating Profile: Game Development (Unity & Leadership)..."
    cp "${REPO_DIR}/profiles/profile_gamedev.json" "${TARGET_DIR}/profile.json"
    cp "${REPO_DIR}/searches/searches_gamedev.yaml" "${TARGET_DIR}/searches.yaml"
    cp "${REPO_DIR}/resumes/resume_gamedev.txt" "${TARGET_DIR}/resume.txt"
    cp "${REPO_DIR}/.env" "${TARGET_DIR}/.env"
    if [ -f "${REPO_DIR}/applypilot_gamedev.db" ]; then
      cp "${REPO_DIR}/applypilot_gamedev.db" "${TARGET_DIR}/applypilot.db"
    fi
    echo "✅ Successfully activated Game Dev Profile in ${TARGET_DIR}!"
    echo "   - Profile:  ${TARGET_DIR}/profile.json"
    echo "   - Searches: ${TARGET_DIR}/searches.yaml"
    echo "   - Resume:   ${TARGET_DIR}/resume.txt"
    echo "   - Database: ${TARGET_DIR}/applypilot.db"
    echo "   - Env:      ${TARGET_DIR}/.env"
    ;;
  status)
    if [ -f "${TARGET_DIR}/profile.json" ]; then
      TARGET_ROLE=$(grep -o '"target_role": *"[^"]*"' "${TARGET_DIR}/profile.json" | cut -d'"' -f4)
      echo "Current Active Profile in ${TARGET_DIR}: ${TARGET_ROLE}"
    else
      echo "No active profile found in ${TARGET_DIR}."
      echo "Run './switch_profile.sh golang' or './switch_profile.sh gamedev' to activate one."
    fi
    ;;
  *)
    echo "Usage: ./switch_profile.sh [golang|gamedev|status]"
    exit 1
    ;;
esac
