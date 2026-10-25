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
echo Click "Vorlesen" in-game or press Middle Mouse Button (Maus 3)!
echo ========================================================

cd /d "%BASE_DIR%"
"%PYTHON_EXE%" "%BASE_DIR%scripts\lotro_service.py" %*

pause

