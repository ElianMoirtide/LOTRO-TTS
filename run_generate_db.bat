@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo LOTRO-TTS SQLite Database Generator
echo ========================================================
echo.

set "PYTHON_EXE="
if exist "%~dp0python\win64\python.exe" (
    set "PYTHON_EXE=%~dp0python\win64\python.exe"
)
if not defined PYTHON_EXE if exist "%~dp0python\win32\python.exe" (
    set "PYTHON_EXE=%~dp0python\win32\python.exe"
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
echo Starte generate_db.py...
echo.

"%PYTHON_EXE%" "%~dp0scripts\generate_db.py" %*

echo.
pause
