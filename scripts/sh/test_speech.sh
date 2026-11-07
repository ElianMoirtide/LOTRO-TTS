#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

echo "========================================================"
echo "LOTRO-TTS Offline Local Voice Cloning (OmniVoice)"
echo "========================================================"

PYTHON_EXE="python/linux64/bin/python3"

if [ ! -f "$PYTHON_EXE" ]; then
    echo "[ERROR] Standalone Python not found at: $PYTHON_EXE"
    echo "Please run scripts/sh/setup_tts.sh first!"
    exit 1
fi

mkdir -p audio_samples

echo ""
echo "[1/3] Speaking Dwarf NPC 'Glóin' in German (Zero-Shot Cloning)..."
"$PYTHON_EXE" scripts/tts_speaker.py --npc "Gloin" --lang de --text "Bei Durins Bart! Was treibt Euch in mein Lager, Reisender?" --output "audio_samples/gloin_de.wav"

echo ""
echo "[2/3] Speaking Elf NPC 'Galadriel' in German (Zero-Shot Cloning)..."
"$PYTHON_EXE" scripts/tts_speaker.py --npc "Galadriel" --lang de --text "Die Welt ist im Wandel. Ich spüre es im Wasser. Ich spüre es in der Erde." --output "audio_samples/galadriel_de.wav"

echo ""
echo "[3/3] Speaking neutral Narrator in English (Zero-Shot Cloning)..."
"$PYTHON_EXE" scripts/tts_speaker.py --npc "narrator" --lang en --text "The shadow lengthens across the northern lands, yet hope remains in the hearts of the free peoples." --output "audio_samples/narrator_en.wav"

echo ""
echo "========================================================"
echo "Test completed! Generated WAV files are saved in: audio_samples/"
echo "========================================================"
