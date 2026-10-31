@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo LOTRO-TTS Offline Local Voice Cloning (OmniVoice)
echo ========================================================

set "PY_EXE=python\win64\python.exe"

if not exist "%PY_EXE%" (
    echo [ERROR] Embedded Python not found at: %PY_EXE%
    echo Bitte fuehren Sie zuerst setup_tts.bat aus!
    pause
    exit /b 1
)

echo.
echo [1/3] Spreche Zwergen-NPC 'Glóin' auf Deutsch (Zero-Shot Kloning)...
"%PY_EXE%" "scripts\tts_speaker.py" --npc "Gloin" --lang de --text "Bei Durins Bart! Was treibt Euch in mein Lager, Reisender?" --output "audio_samples\gloin_de.wav"

echo.
echo [2/3] Spreche Elben-NPC 'Galadriel' auf Deutsch (Zero-Shot Kloning)...
"%PY_EXE%" "scripts\tts_speaker.py" --npc "Galadriel" --lang de --text "Die Welt ist im Wandel. Ich spüre es im Wasser. Ich spüre es in der Erde." --output "audio_samples\galadriel_de.wav"

echo.
echo [3/3] Spreche neutralen Erzaehler auf Englisch (Zero-Shot Kloning)...
"%PY_EXE%" "scripts\tts_speaker.py" --npc "narrator" --lang en --text "The shadow lengthens across the northern lands, yet hope remains in the hearts of the free peoples." --output "audio_samples\narrator_en.wav"

echo.
echo ========================================================
echo Test abgeschlossen! Die generierten WAV-Dateien liegen in: audio_samples\
echo ========================================================
pause
