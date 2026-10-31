@echo off
setlocal
cd /d "%~dp0..\.."
echo Compiling LOTRO-TTS.exe...
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe /optimize+ /win32icon:scripts\exe\lotro_tts.ico /out:LOTRO-TTS.exe scripts\exe\LotroTtsGui.cs
if %errorlevel% equ 0 (
    echo [OK] Successfully built LOTRO-TTS.exe!
) else (
    echo [ERROR] Build failed!
)
pause

