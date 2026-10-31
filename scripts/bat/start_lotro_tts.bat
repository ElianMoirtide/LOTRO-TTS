@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\.."

set "PYTHON_EXE=python\win64\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Embedded Python not found at: %PYTHON_EXE%
    pause
    exit /b 1
)

echo ========================================================
echo        LOTRO-TTS Background Service and Screenreader
echo ========================================================
echo Watching The Lord of the Rings Online / Script.log...
echo Trigger speech in-game via Plugin or Middle Mouse Button (Mouse 3)!
echo Tip: Run with --config to change your language settings.
echo ========================================================

"%PYTHON_EXE%" "scripts\lotro_service.py" %*

pause

