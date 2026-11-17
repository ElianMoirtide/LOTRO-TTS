#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

echo "========================================================"
echo "LOTRO-TTS Source XML Updater"
echo "========================================================"
echo ""

PYTHON_EXE=""
if [ -f "python/linux64/bin/python3" ]; then
    PYTHON_EXE="python/linux64/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXE="python"
fi

if [ -z "$PYTHON_EXE" ]; then
    echo "[ERROR] No Python runtime found in python/linux64 or system PATH."
    exit 1
fi

echo "Python: $PYTHON_EXE"
echo ""
echo "Updating source files from GitHub..."
echo ""

"$PYTHON_EXE" scripts/update_sources.py --generate-db "$@"
