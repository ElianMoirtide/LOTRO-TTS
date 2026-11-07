@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo LOTRO-TTS Offline Local Voice Cloning (OmniVoice)
echo ========================================================

set "PY_EXE=python\win64\python.exe"

if not exist "%PY_EXE%" (
    echo [ERROR] Embedded Python not found at: %PY_EXE%
    echo Please run setup_tts.bat first!
    pause
    exit /b 1
)

echo.
echo [1/3] Speaking Dwarf NPC 'Glóin' in German (Zero-Shot Cloning)...
"%PY_EXE%" "scripts\tts_speaker.py" --npc "Gloin" --lang de --text "Bei Durins Bart! Was treibt Euch in mein Lager, Reisender?" --output "audio_samples\gloin_de.wav"

echo.
echo [2/3] Speaking Elf NPC 'Galadriel' in German (Zero-Shot Cloning)...
"%PY_EXE%" "scripts\tts_speaker.py" --npc "Galadriel" --lang de --text "Die Welt ist im Wandel. Ich spüre es im Wasser. Ich spüre es in der Erde." --output "audio_samples\galadriel_de.wav"

echo.
echo [3/3] Speaking neutral Narrator in English (Zero-Shot Cloning)...
"%PY_EXE%" "scripts\tts_speaker.py" --npc "narrator" --lang en --text "The shadow lengthens across the northern lands, yet hope remains in the hearts of the free peoples." --output "audio_samples\narrator_en.wav"

echo.
echo ========================================================
echo Test completed! Generated WAV files are saved in: audio_samples\
echo ========================================================
pause
