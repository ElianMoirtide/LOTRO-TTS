using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;

namespace LotroTtsGui
{
    public class UpdateDialog : Window
    {
        private readonly UpdateInfo updateInfo;
        private readonly string baseDir;
        private readonly IBrush bgDark = new SolidColorBrush(Color.FromRgb(20, 22, 28));
        private readonly IBrush bgCard = new SolidColorBrush(Color.FromRgb(30, 34, 43));
        private readonly IBrush bgLog = new SolidColorBrush(Color.FromRgb(14, 16, 20));
        private readonly IBrush borderBrush = new SolidColorBrush(Color.FromRgb(55, 60, 72));
        private readonly IBrush goldAccent = new SolidColorBrush(Color.FromRgb(212, 175, 55));
        private readonly IBrush textLight = new SolidColorBrush(Color.FromRgb(232, 234, 237));
        private readonly IBrush textMuted = new SolidColorBrush(Color.FromRgb(154, 160, 166));
        private readonly IBrush greenOk = new SolidColorBrush(Color.FromRgb(46, 160, 67));
        private readonly IBrush amberWarn = new SolidColorBrush(Color.FromRgb(210, 153, 34));
        private readonly IBrush redStop = new SolidColorBrush(Color.FromRgb(196, 43, 28));

        private Button btnAutoUpdate = null!;
        private Button btnOpenBrowser = null!;
        private Button btnClose = null!;
        private StackPanel pnlProgress = null!;
        private ProgressBar progressBar = null!;
        private TextBlock lblProgressStatus = null!;

        public UpdateDialog(UpdateInfo info, string baseDir)
        {
            this.updateInfo = info;
            this.baseDir = baseDir;

            Title = $"LOTRO-TTS Update — {info.TagName}";
            Width = 640;
            Height = 520;
            MinWidth = 520;
            MinHeight = 400;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            Background = bgDark;

            try
            {
                using var iconStream = Avalonia.Platform.AssetLoader.Open(new Uri("avares://LOTRO-TTS/lotro_tts.ico"));
                Icon = new WindowIcon(iconStream);
            }
            catch { }

            InitializeUi();
        }

        private void InitializeUi()
        {
            var mainGrid = new Grid
            {
                Margin = new Thickness(20),
                RowDefinitions = new RowDefinitions("Auto,Auto,*,Auto,Auto")
            };

            // 0. Title & Release Name
            var headerStack = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
            var lblTitle = new TextBlock
            {
                Text = updateInfo.IsPrerelease ? "New Pre-Release Available! (Beta)" : "New Update Available!",
                FontSize = 18,
                FontWeight = FontWeight.Bold,
                Foreground = updateInfo.IsPrerelease ? amberWarn : goldAccent
            };
            var releaseStack = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 8,
                Margin = new Thickness(0, 4, 0, 0)
            };
            var lblRelease = new TextBlock
            {
                Text = $"{updateInfo.TagName}: {updateInfo.ReleaseName}",
                FontSize = 14,
                FontWeight = FontWeight.SemiBold,
                Foreground = textLight,
                VerticalAlignment = VerticalAlignment.Center
            };
            releaseStack.Children.Add(lblRelease);

            if (updateInfo.IsPrerelease)
            {
                var badge = new Border
                {
                    Background = amberWarn,
                    CornerRadius = new CornerRadius(3),
                    Padding = new Thickness(6, 2),
                    VerticalAlignment = VerticalAlignment.Center
                };
                var lblBadge = new TextBlock
                {
                    Text = "PRE-RELEASE / BETA",
                    FontSize = 10,
                    FontWeight = FontWeight.Bold,
                    Foreground = Brushes.Black
                };
                badge.Child = lblBadge;
                releaseStack.Children.Add(badge);
            }

            headerStack.Children.Add(lblTitle);
            headerStack.Children.Add(releaseStack);
            Grid.SetRow(headerStack, 0);
            mainGrid.Children.Add(headerStack);

            // 1. Release Info
            var lblSub = new TextBlock
            {
                Text = "Changelog and Release Notes:",
                FontSize = 12,
                Foreground = textMuted,
                Margin = new Thickness(0, 0, 0, 6)
            };
            Grid.SetRow(lblSub, 1);
            mainGrid.Children.Add(lblSub);

            // 2. Scrollable Body
            var notesBorder = new Border
            {
                Background = bgLog,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(4),
                Padding = new Thickness(10)
            };
            var scroll = new ScrollViewer();
            var txtBody = new TextBlock
            {
                Text = string.IsNullOrWhiteSpace(updateInfo.Body) ? "No changelog provided." : updateInfo.Body,
                Foreground = textLight,
                FontSize = 12,
                FontFamily = FontFamily.Parse("Consolas, monospace"),
                TextWrapping = TextWrapping.Wrap
            };
            scroll.Content = txtBody;
            notesBorder.Child = scroll;
            Grid.SetRow(notesBorder, 2);
            mainGrid.Children.Add(notesBorder);

            // 3. Progress Row (hidden by default)
            pnlProgress = new StackPanel
            {
                Margin = new Thickness(0, 10, 0, 0),
                IsVisible = false
            };
            lblProgressStatus = new TextBlock
            {
                Text = "Downloading update...",
                FontSize = 12,
                Foreground = textLight,
                Margin = new Thickness(0, 0, 0, 4)
            };
            progressBar = new ProgressBar
            {
                Height = 12,
                Minimum = 0,
                Maximum = 100,
                Value = 0,
                Foreground = goldAccent,
                Background = bgCard
            };
            pnlProgress.Children.Add(lblProgressStatus);
            pnlProgress.Children.Add(progressBar);
            Grid.SetRow(pnlProgress, 3);
            mainGrid.Children.Add(pnlProgress);

            // 4. Actions Row
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                Spacing = 10,
                Margin = new Thickness(0, 16, 0, 0)
            };

            btnAutoUpdate = new Button
            {
                Content = "Download & Install Update",
                Background = goldAccent,
                Foreground = new SolidColorBrush(Color.FromRgb(20, 22, 28)),
                FontWeight = FontWeight.Bold,
                Padding = new Thickness(16, 6),
                Cursor = new Cursor(StandardCursorType.Hand)
            };
            btnAutoUpdate.Click += async (s, e) => await StartAutoUpdateAsync();

            btnOpenBrowser = new Button
            {
                Content = "Open in Browser",
                Background = bgCard,
                Foreground = textLight,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(14, 6),
                Cursor = new Cursor(StandardCursorType.Hand)
            };
            btnOpenBrowser.Click += (s, e) =>
            {
                try
                {
                    string target = !string.IsNullOrEmpty(updateInfo.HtmlUrl)
                        ? updateInfo.HtmlUrl
                        : "https://github.com/ElianMoirtide/LOTRO-TTS/releases";
                    Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
                }
                catch { }
            };

            btnClose = new Button
            {
                Content = "Close",
                Background = bgCard,
                Foreground = textLight,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(14, 6),
                Cursor = new Cursor(StandardCursorType.Hand)
            };
            btnClose.Click += (s, e) => Close();

            buttonPanel.Children.Add(btnAutoUpdate);
            buttonPanel.Children.Add(btnOpenBrowser);
            buttonPanel.Children.Add(btnClose);
            Grid.SetRow(buttonPanel, 4);
            mainGrid.Children.Add(buttonPanel);

            Content = mainGrid;
        }

        private async Task StartAutoUpdateAsync()
        {
            if (string.IsNullOrEmpty(updateInfo.DownloadUrl))
            {
                lblProgressStatus.Text = "No download URL available. Please use 'Open in Browser'.";
                lblProgressStatus.Foreground = amberWarn;
                pnlProgress.IsVisible = true;
                return;
            }

            btnAutoUpdate.IsEnabled = false;
            btnOpenBrowser.IsEnabled = false;
            btnClose.IsEnabled = false;
            pnlProgress.IsVisible = true;
            lblProgressStatus.Text = "Initiating download...";
            progressBar.Value = 0;

            string tempDir = Path.Combine(baseDir, "_update_temp");
            string downloadFile = Path.Combine(tempDir, updateInfo.DownloadFileName);
            string extractDir = Path.Combine(tempDir, "extracted");

            try
            {
                if (Directory.Exists(tempDir))
                {
                    try { Directory.Delete(tempDir, true); } catch { }
                }
                Directory.CreateDirectory(tempDir);

                // Download with progress
                using var client = new HttpClient();
                client.DefaultRequestHeaders.Add("User-Agent", "LOTRO-TTS-AutoUpdater");
                client.Timeout = TimeSpan.FromMinutes(5);

                using var response = await client.GetAsync(updateInfo.DownloadUrl, HttpCompletionOption.ResponseHeadersRead);
                response.EnsureSuccessStatusCode();

                long? totalBytes = response.Content.Headers.ContentLength;
                using var contentStream = await response.Content.ReadAsStreamAsync();
                using var fileStream = new FileStream(downloadFile, FileMode.Create, FileAccess.Write, FileShare.None, 8192, true);

                byte[] buffer = new byte[16384];
                long totalRead = 0;
                int read;

                while ((read = await contentStream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                {
                    await fileStream.WriteAsync(buffer, 0, read);
                    totalRead += read;

                    if (totalBytes.HasValue && totalBytes.Value > 0)
                    {
                        double percent = (double)totalRead / totalBytes.Value * 100.0;
                        progressBar.Value = percent;
                        long mbRead = totalRead / (1024 * 1024);
                        long mbTotal = totalBytes.Value / (1024 * 1024);
                        lblProgressStatus.Text = $"Downloading update: {mbRead} MB / {mbTotal} MB ({percent:F0}%)";
                    }
                    else
                    {
                        long mbRead = totalRead / (1024 * 1024);
                        lblProgressStatus.Text = $"Downloading update: {mbRead} MB...";
                    }
                }
                fileStream.Close();

                lblProgressStatus.Text = "Unpacking update...";
                progressBar.Value = 95;

                string payloadDir = extractDir;
                if (updateInfo.IsDirectExe)
                {
                    Directory.CreateDirectory(extractDir);
                    string targetExeName = OperatingSystem.IsWindows() ? "LOTRO-TTS.exe" : "LOTRO-TTS";
                    string targetExe = Path.Combine(extractDir, targetExeName);
                    File.Copy(downloadFile, targetExe, true);
                }
                else
                {
                    if (Directory.Exists(extractDir))
                    {
                        try { Directory.Delete(extractDir, true); } catch { }
                    }
                    ZipFile.ExtractToDirectory(downloadFile, extractDir);

                    // Check for single top-level directory (standard GitHub release zipballs)
                    string[] subDirs = Directory.GetDirectories(extractDir);
                    string[] directFiles = Directory.GetFiles(extractDir);
                    if (directFiles.Length == 0 && subDirs.Length == 1)
                    {
                        payloadDir = subDirs[0];
                    }
                }

                lblProgressStatus.Text = "Launching updater & restarting application...";
                progressBar.Value = 100;
                await Task.Delay(500);

                LaunchHandoffScript(payloadDir, downloadFile);
            }
            catch (Exception ex)
            {
                lblProgressStatus.Text = $"Update failed: {ex.Message}";
                lblProgressStatus.Foreground = redStop;
                btnAutoUpdate.IsEnabled = true;
                btnOpenBrowser.IsEnabled = true;
                btnClose.IsEnabled = true;
            }
        }

        private void LaunchHandoffScript(string payloadDir, string downloadFile)
        {
            int currentPid = Process.GetCurrentProcess().Id;

            if (OperatingSystem.IsWindows())
            {
                string cmdPath = Path.Combine(baseDir, "apply_update.cmd");
                string script = $@"@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title LOTRO-TTS Auto-Updater
echo ============================================================
echo                  LOTRO-TTS Auto-Updater
echo ============================================================
echo.
echo Waiting for LOTRO-TTS (PID %1) to close...
powershell -NoProfile -Command ""try {{ Wait-Process -Id %1 -Timeout 15 }} catch {{}}"" 2>nul
timeout /t 1 /nobreak >nul

echo.
echo Applying update to: %2
echo Source payload:     %3
echo.

:: 1. If Python runtime update is included in the release payload, update binaries & stdlib
:: while strictly preserving site-packages (TTS wheels: PyTorch, OmniVoice, CUDA, etc.)
if exist ""%~3\python\win64"" (
    echo Updating Python runtime environment (preserving installed TTS packages)...
    robocopy ""%~3\python\win64"" ""%~2\python\win64"" /E /XD site-packages Scripts share /R:5 /W:1 >nul
    powershell -NoProfile -Command ""Get-ChildItem '%~2\python\win64\*._pth' -ErrorAction SilentlyContinue | ForEach-Object {{ (Get-Content $_.FullName) -replace '#import site', 'import site' | Set-Content $_.FullName }}"" 2>nul
)

:: 2. Robocopy files into base directory (excluding runtime, user cache, user db, custom npc overrides, logs)
if exist ""%~2\src\npc\npc_races_custom.json"" copy /y ""%~2\src\npc\npc_races_custom.json"" ""%~2\_custom_npc.tmp"" >nul
robocopy ""%~3"" ""%~2"" /E /XD python cache logs .git scratch _update_temp /XF config.json lotro.db npc_races_custom.json *.log /R:5 /W:1 >nul
if exist ""%~2\_custom_npc.tmp"" move /y ""%~2\_custom_npc.tmp"" ""%~2\src\npc\npc_races_custom.json"" >nul

:: If config.json did not exist in target, copy default
if not exist ""%~2\config.json"" if exist ""%~3\config.json"" copy ""%~3\config.json"" ""%~2\config.json"" >nul

echo.
echo Cleaning up temporary update files...
rmdir /s /q ""%~2\_update_temp"" 2>nul
if exist ""%~4"" del /f /q ""%~4"" 2>nul

echo.
echo ============================================================
echo           Update applied successfully! Restarting...
echo ============================================================
timeout /t 2 /nobreak >nul
start """" ""%~2\LOTRO-TTS.exe""
del ""%~f0"" & exit
";
                File.WriteAllText(cmdPath, script, Encoding.UTF8);

                var psi = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = $"/c \"\"{cmdPath}\" {currentPid} \"{baseDir}\" \"{payloadDir}\" \"{downloadFile}\"\"",
                    UseShellExecute = true,
                    WindowStyle = ProcessWindowStyle.Normal
                };
                Process.Start(psi);
                Environment.Exit(0);
            }
            else
            {
                string shPath = Path.Combine(baseDir, "apply_update.sh");
                string script = $@"#!/usr/bin/env bash
PID={currentPid}
BASE_DIR=""{baseDir}""
PAYLOAD_DIR=""{payloadDir}""
TEMP_FILE=""{downloadFile}""

echo ""Waiting for LOTRO-TTS (PID $PID) to close...""
tail --pid=$PID -f /dev/null 2>/dev/null || sleep 2

echo ""Applying update to $BASE_DIR...""

# 1. If Python runtime update is included, update binaries & stdlib preserving site-packages
if [ -d ""$PAYLOAD_DIR/python/linux64"" ]; then
    echo ""Updating Python runtime environment (preserving installed TTS packages)...""
    mkdir -p ""$BASE_DIR/python/linux64""
    [ -d ""$PAYLOAD_DIR/python/linux64/bin"" ] && cp -rf ""$PAYLOAD_DIR/python/linux64/bin"" ""$BASE_DIR/python/linux64/""
    [ -d ""$PAYLOAD_DIR/python/linux64/include"" ] && cp -rf ""$PAYLOAD_DIR/python/linux64/include"" ""$BASE_DIR/python/linux64/""
    if [ -d ""$PAYLOAD_DIR/python/linux64/lib"" ]; then
        mkdir -p ""$BASE_DIR/python/linux64/lib""
        find ""$PAYLOAD_DIR/python/linux64/lib"" -mindepth 1 -maxdepth 1 ! -name 'site-packages' -exec cp -rf {{}} ""$BASE_DIR/python/linux64/lib/"" \;
    fi
fi

# 2. Copy application files excluding python, cache, config.json, lotro.db, .git, logs, npc_races_custom.json
if [ -f ""$BASE_DIR/src/npc/npc_races_custom.json"" ]; then
    cp -f ""$BASE_DIR/src/npc/npc_races_custom.json"" ""$BASE_DIR/_custom_npc.tmp""
fi
find ""$PAYLOAD_DIR"" -mindepth 1 -maxdepth 1 ! -name 'python' ! -name 'cache' ! -name 'config.json' ! -name 'lotro.db' ! -name '.git' ! -name 'logs' -exec cp -rf {{}} ""$BASE_DIR""/ \;
if [ -f ""$BASE_DIR/_custom_npc.tmp"" ]; then
    mv -f ""$BASE_DIR/_custom_npc.tmp"" ""$BASE_DIR/src/npc/npc_races_custom.json""
fi

chmod +x ""$BASE_DIR/LOTRO-TTS"" 2>/dev/null
rm -rf ""$BASE_DIR/_update_temp""
[ -f ""$TEMP_FILE"" ] && rm -f ""$TEMP_FILE""

echo ""Restarting LOTRO-TTS...""
sleep 1
nohup ""$BASE_DIR/LOTRO-TTS"" >/dev/null 2>&1 &
rm -- ""$0""
";
                File.WriteAllText(shPath, script, new UTF8Encoding(false));

                try
                {
                    Process.Start("chmod", $"+x \"{shPath}\"");
                }
                catch { }

                var psi = new ProcessStartInfo
                {
                    FileName = "/bin/bash",
                    Arguments = $"\"{shPath}\"",
                    UseShellExecute = false
                };
                Process.Start(psi);
                Environment.Exit(0);
            }
        }
    }
}
