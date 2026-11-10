@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo LOTRO-TTS Avalonia GUI Builder (Cross-Platform)
echo ========================================================
echo.

where dotnet >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] .NET SDK (dotnet) not found in PATH!
    echo Please install .NET SDK 10 or newer: https://dotnet.microsoft.com/download
    pause
    exit /b 1
)

echo [1/2] Publishing Windows x64 binary (LOTRO-TTS.exe)...
dotnet publish src\LotroTtsGui\LotroTtsGui.csproj -c Release -r win-x64 --self-contained -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o src\LotroTtsGui\bin\Release\net10.0\win-x64\publish

if %errorlevel% equ 0 (
    copy /y "src\LotroTtsGui\bin\Release\net10.0\win-x64\publish\LOTRO-TTS.exe" "LOTRO-TTS.exe" >nul
    echo [OK] Updated LOTRO-TTS.exe in root directory.
) else (
    echo [ERROR] Windows build failed!
)

echo.
echo [2/2] Publishing Linux x64 binary (LOTRO-TTS)...
dotnet publish src\LotroTtsGui\LotroTtsGui.csproj -c Release -r linux-x64 --self-contained -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o src\LotroTtsGui\bin\Release\net10.0\linux-x64\publish

if %errorlevel% equ 0 (
    copy /y "src\LotroTtsGui\bin\Release\net10.0\linux-x64\publish\LOTRO-TTS" "LOTRO-TTS" >nul
    echo [OK] Updated LOTRO-TTS (Linux) in root directory.
) else (
    echo [ERROR] Linux build failed!
)

echo.
echo ========================================================
echo Build process finished!
echo ========================================================
pause
