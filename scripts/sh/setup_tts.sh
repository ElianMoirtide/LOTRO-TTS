#!/usr/bin/env bash
set -e

# Change directory to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

echo "========================================================"
echo "LOTRO-TTS Audio & AI Environment Setup (Linux)"
echo "========================================================"

LINUX_PY="python/linux64/bin/python3"

# 1. Download portable standalone Python for Linux if not present
if [ ! -f "$LINUX_PY" ]; then
    echo ""
    echo "[INFO] Standalone Python for Linux not found."
    echo "[INFO] Downloading portable Python 3.13 (x86_64) from python-build-standalone..."
    mkdir -p python/linux64

    STANDALONE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.13.0+20241016-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
    TEMP_TAR="python/linux64_python.tar.gz"

    if command -v curl >/dev/null 2>&1; then
        curl -fSL "$STANDALONE_URL" -o "$TEMP_TAR"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --show-progress "$STANDALONE_URL" -O "$TEMP_TAR"
    else
        echo "[ERROR] Neither 'curl' nor 'wget' was found on your system."
        echo "Please install curl or wget (e.g. sudo apt install curl / sudo pacman -S curl)."
        exit 1
    fi

    echo "[INFO] Extracting portable Python to python/linux64..."
    tar -xzf "$TEMP_TAR" -C python/linux64 --strip-components=1
    rm -f "$TEMP_TAR"
    chmod +x "$LINUX_PY"
    echo "[OK] Portable Python successfully installed!"
fi

if [ ! -f "$LINUX_PY" ]; then
    echo "[ERROR] Python executable not found at: $LINUX_PY"
    exit 1
fi

echo "Using Python: $LINUX_PY ($("$LINUX_PY" --version))"
echo ""

echo "Please select the compute mode for AI voices:"
echo "  [1] Auto-Detect (Recommended - NVIDIA CUDA / AMD ROCm / CPU)"
echo "  [2] NVIDIA GPU (GeForce RTX / GTX with CUDA)"
echo "  [3] AMD GPU (ROCm - Radeon RX 7000/9000 & newer RDNA GPUs)"
echo "  [4] CPU (CPU-only / Universal compatibility for all Linux PCs & Steam Deck)"
echo ""

read -rp "Your choice (1, 2, 3 or 4, Default: 1): " CHOICE
case "$CHOICE" in
    2)
        MODE="nvidia"
        ;;
    3)
        MODE="amd"
        ;;
    4)
        MODE="cpu"
        ;;
    *)
        MODE="auto"
        ;;
esac

echo ""
echo "Selected mode: $MODE"
echo "========================================================"
"$LINUX_PY" "scripts/setup_tts.py" --mode "$MODE"

echo ""
echo "========================================================"
echo "Setup completed successfully!"
echo "========================================================"
