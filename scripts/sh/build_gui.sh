#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

echo "========================================================"
echo "LOTRO-TTS Avalonia GUI Builder (Linux x64)"
echo "========================================================"
echo ""

if ! command -v dotnet >/dev/null 2>&1; then
    echo "[ERROR] .NET SDK (dotnet) not found in PATH!"
    echo "Please install .NET SDK 10 or newer: https://dotnet.microsoft.com/download"
    exit 1
fi

echo "Publishing self-contained single-file LOTRO-TTS (Linux)..."
dotnet publish src/LotroTtsGui/LotroTtsGui.csproj -c Release -r linux-x64 --self-contained -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o src/LotroTtsGui/bin/Release/net10.0/linux-x64/publish

if [ -f "src/LotroTtsGui/bin/Release/net10.0/linux-x64/publish/LOTRO-TTS" ]; then
    cp -f "src/LotroTtsGui/bin/Release/net10.0/linux-x64/publish/LOTRO-TTS" "LOTRO-TTS"
    chmod +x "LOTRO-TTS"
    echo ""
    echo "========================================================"
    echo "[OK] Successfully built and updated LOTRO-TTS for Linux!"
    echo "========================================================"
fi
