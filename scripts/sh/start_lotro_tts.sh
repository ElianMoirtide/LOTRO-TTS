#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

PYTHON_EXE="python/linux64/bin/python3"

if [ ! -f "$PYTHON_EXE" ]; then
    echo "[ERROR] Standalone Python not found at: $PYTHON_EXE"
    echo "Please run scripts/sh/setup_tts.sh first!"
    exit 1
fi

echo "========================================================"
echo "       LOTRO-TTS Background Service and Screenreader"
echo "========================================================"
echo "Watching The Lord of the Rings Online / Script.log..."
echo "Trigger speech in-game via Plugin or Middle Mouse Button (Mouse 3)!"
echo "Tip: Run with --config to change your language settings."
echo "========================================================"

"$PYTHON_EXE" scripts/lotro_service.py "$@"
