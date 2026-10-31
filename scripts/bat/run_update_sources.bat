@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo LOTRO-TTS Source XML Updater
echo ========================================================
echo.

set "PYTHON_EXE="
if exist "python\win64\python.exe" (
    set "PYTHON_EXE=python\win64\python.exe"
)
if not defined PYTHON_EXE if exist "python\win32\python.exe" (
    set "PYTHON_EXE=python\win32\python.exe"
)
if not defined PYTHON_EXE (
    where python >nul 2>nul
    if %errorlevel% equ 0 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo [FEHLER] Kein Python in python\win64 oder python\win32 gefunden.
    pause
    exit /b 1
)

echo Python: "%PYTHON_EXE%"
echo.
echo Aktualisiere Quell-Dateien von GitHub...
echo.

"%PYTHON_EXE%" "scripts\update_sources.py" --generate-db %*

echo.
pause
