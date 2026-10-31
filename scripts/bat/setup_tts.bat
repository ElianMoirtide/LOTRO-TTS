@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo LOTRO-TTS Audio ^& AI Environment Setup
echo ========================================================

set "PY_EXE=python\win64\python.exe"

if not exist "%PY_EXE%" (
    echo [ERROR] Embedded Python not found at: %PY_EXE%
    pause
    exit /b 1
)

echo Using Python: %PY_EXE%
echo.
echo Bitte waehlen Sie den Rechenmodus fuer die KI-Stimmen:
echo   [1] GPU (Empfohlen - NVIDIA RTX / CUDA)
echo   [2] CPU (Reiner CPU-Betrieb)
echo.

set /p "CHOICE=Ihre Wahl (1 oder 2, Standard: 1): "
if "%CHOICE%"=="2" (
    set "MODE=cpu"
) else (
    set "MODE=gpu"
)

echo.
echo Ausgewaehlter Modus: %MODE%
echo ========================================================
"%PY_EXE%" "scripts\setup_tts.py" --mode %MODE%

echo.
echo ========================================================
echo Setup abgeschlossen!
echo ========================================================
pause
