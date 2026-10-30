@echo off
setlocal
chcp 65001 >nul

set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python\win64\python.exe"

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

cd /d "%BASE_DIR%"
"%PYTHON_EXE%" "%BASE_DIR%scripts\lotro_service.py" %*

pause

