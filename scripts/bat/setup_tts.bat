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
echo Please select the compute mode for AI voices:
echo   [1] Auto-Detect (Recommended - NVIDIA CUDA / AMD ROCm / CPU)
echo   [2] NVIDIA GPU (GeForce RTX / GTX with CUDA)
echo   [3] AMD GPU (ROCm 10.x - Radeon RX 7000/9000 ^& 780M/890M APUs)
echo       * NOTE: Older AMD GPUs (RX 5000/6000) not supported by Windows ROCm. Please select CPU (4)!
echo   [4] CPU (CPU-only / Universal compatibility for all PCs)
echo.

set /p "CHOICE=Your choice (1, 2, 3 or 4, Default: 1): "
if "%CHOICE%"=="2" (
    set "MODE=nvidia"
) else if "%CHOICE%"=="3" (
    set "MODE=amd"
) else if "%CHOICE%"=="4" (
    set "MODE=cpu"
) else (
    set "MODE=auto"
)

echo.
echo Selected mode: %MODE%
echo ========================================================
"%PY_EXE%" "scripts\setup_tts.py" --mode %MODE%

echo.
echo ========================================================
echo Setup completed successfully!
echo ========================================================
pause
