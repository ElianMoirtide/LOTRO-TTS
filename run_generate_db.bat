@echo off
setlocal enabledelayedexpansion

:: Switch to the repository root directory where this batch file is located
cd /d "%~dp0"

echo ========================================================
echo LOTRO-TTS SQLite Database Generator
echo ========================================================
echo.

:: Detect portable embedded Python executable
set "PYTHON_EXE="

if exist "%~dp0python\win64\python.exe" (
    set "PYTHON_EXE=%~dp0python\win64\python.exe"
    echo Using portable Python (win64): !PYTHON_EXE!
) else if exist "%~dp0python\win32\python.exe" (
    set "PYTHON_EXE=%~dp0python\win32\python.exe"
    echo Using portable Python (win32): !PYTHON_EXE!
) else (
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
        echo Using system Python: !PYTHON_EXE!
    ) else (
        echo [ERROR] No Python binary found in python\win64 or python\win32, and system python is not installed.
        pause
        exit /b 1
    )
)

echo.
echo Running generate_db.py...
echo.

"!PYTHON_EXE!" "%~dp0scripts\generate_db.py" %*

set EXIT_CODE=!errorlevel!

echo.
if !EXIT_CODE! equ 0 (
    echo [SUCCESS] Database generation finished successfully.
) else (
    echo [ERROR] Database generation failed with exit code !EXIT_CODE!.
)

echo.
pause
exit /b !EXIT_CODE!
