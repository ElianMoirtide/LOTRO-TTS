@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo LOTRO-TTS NPC Race Scraper (lotro-wiki.com)
echo ========================================================
echo.

set "PYTHON_EXE="
if exist "python\win64\python.exe" (
    set "PYTHON_EXE=python\win64\python.exe"
)
if not defined PYTHON_EXE (
    where python >nul 2>nul
    if %errorlevel% equ 0 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo [ERROR] No Python runtime found in python\win64 or system PATH.
    pause
    exit /b 1
)

echo Python: "%PYTHON_EXE%"
echo.
echo Starting scrape_npc_races.py...
echo [NOTE] You can cancel at any time with Ctrl+C.
echo.

"%PYTHON_EXE%" "scripts\scrape_npc_races.py" %*

echo.
pause
