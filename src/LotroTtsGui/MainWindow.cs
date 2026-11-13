using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Formats.Tar;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;

namespace LotroTtsGui
{
    public class LogMessage
    {
        public string Text { get; set; } = "";
        public IBrush Brush { get; set; } = Brushes.White;
    }

    public class MainWindow : Window
    {
        public const string AppVersion = "v2.0-rc3";

        private readonly string baseDir;
        private string pythonExe;
        private readonly string configPath;
        private string stopHotkey = "pause";
        private double savedNormalWidth = 960;
        private double savedNormalHeight = 720;
        private bool savedIsMaximized = false;
        private bool isLoadingConfig = false;

        // Status controls
        private TextBlock lblEnvStatus = null!;
        private TextBlock lblDbStatus = null!;
        private TextBlock lblPluginStatus = null!;

        // Config controls
        private ComboBox cmbClientLang = null!;
        private ComboBox cmbTtsLang = null!;
        private ComboBox cmbComputeMode = null!;
        private Slider sliderVolume = null!;
        private TextBlock lblVolumeTitle = null!;
        private volatile int currentVolume = 80;
        private CancellationTokenSource? serviceVolumeWatcherCts;
        private CheckBox chkMiddleMouse = null!;
        private CheckBox chkNarratorMode = null!;
        private ComboBox cmbNarratorVoice = null!;
        private string savedNarratorVoice = "man_male_1";
        private Button btnStartStop = null!;

        // Tool buttons
        private Button btnSetupAi = null!;
        private Button btnRebuildDb = null!;
        private Button btnUpdateSources = null!;
        private Button btnInstallPlugin = null!;
        private Button btnTestSpeech = null!;

        // Update Checker
        private Button btnUpdateBadge = null!;
        private CheckBox chkIncludePrereleases = null!;
        private bool includePrereleases = false;
        private UpdateInfo? latestUpdateInfo = null;
        private bool isCheckingUpdates = false;

        // Log Console
        private readonly ObservableCollection<LogMessage> logMessages = new();
        private ScrollViewer logScrollViewer = null!;
        private SelectableTextBlock logTextBlock = null!;

        // Process state
        private Process? activeProcess = null;
        private bool isServiceRunning = false;
        private bool isTaskRunning = false;

        // Theme brushes
        private readonly IBrush bgDark = new SolidColorBrush(Color.FromRgb(20, 22, 28));
        private readonly IBrush bgCard = new SolidColorBrush(Color.FromRgb(30, 34, 43));
        private readonly IBrush bgLog = new SolidColorBrush(Color.FromRgb(14, 16, 20));
        private readonly IBrush borderBrush = new SolidColorBrush(Color.FromRgb(55, 60, 72));
        private readonly IBrush goldAccent = new SolidColorBrush(Color.FromRgb(212, 175, 55));
        private readonly IBrush textLight = new SolidColorBrush(Color.FromRgb(232, 234, 237));
        private readonly IBrush textMuted = new SolidColorBrush(Color.FromRgb(154, 160, 166));
        private readonly IBrush greenOk = new SolidColorBrush(Color.FromRgb(46, 160, 67));
        private readonly IBrush redStop = new SolidColorBrush(Color.FromRgb(196, 43, 28));
        private readonly IBrush amberWarn = new SolidColorBrush(Color.FromRgb(210, 153, 34));

        public MainWindow()
        {
            baseDir = AppContext.BaseDirectory.TrimEnd('\\', '/');
            pythonExe = LotroPathDetector.GetPythonExecutable(baseDir);
            configPath = Path.Combine(baseDir, "config.json");

            Title = "LOTRO-TTS";
            Width = 960;
            Height = 720;
            MinWidth = 880;
            MinHeight = 620;
            Background = bgDark;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            try
            {
                using var iconStream = Avalonia.Platform.AssetLoader.Open(new Uri("avares://LOTRO-TTS/lotro_tts.ico"));
                Icon = new WindowIcon(iconStream);
            }
            catch { }

            LoadSavedWindowSize();
            Width = savedNormalWidth;
            Height = savedNormalHeight;
            if (savedIsMaximized)
            {
                WindowState = WindowState.Maximized;
            }

            isLoadingConfig = true;
            try
            {
                InitializeUi();
                PopulateNarratorVoices();
                LoadConfig();
                RefreshSystemStatus();
            }
            finally
            {
                isLoadingConfig = false;
            }

            this.PropertyChanged += (s, e) =>
            {
                if (isLoadingConfig) return;
                if (e.Property.Name == nameof(WindowState))
                {
                    savedIsMaximized = (WindowState == WindowState.Maximized);
                }
                else if (e.Property.Name == nameof(Bounds) || e.Property.Name == nameof(ClientSize))
                {
                    if (WindowState == WindowState.Normal)
                    {
                        if (Bounds.Width >= MinWidth) savedNormalWidth = Bounds.Width;
                        if (Bounds.Height >= MinHeight) savedNormalHeight = Bounds.Height;
                    }
                }
            };

            this.Closing += (s, e) =>
            {
                SaveConfig();
                StopActiveProcess();
            };

            AppendLog("======================================================================", goldAccent);
            AppendLog($"  LOTRO-TTS {AppVersion} — Local Voiceover System for Middle-earth", goldAccent);
            AppendLog("======================================================================", goldAccent);
            AppendLog("Ready. Click 'START LOTRO-TTS' to launch.", textLight);

            string dbFile = Path.Combine(baseDir, "data", "lotro.db");
            if (File.Exists(dbFile) && AreDatabaseSourcesNewer(dbFile))
            {
                AppendLog("[NOTICE] Updated quest/NPC source files detected. Click 'Build Quest DB' to update your quest database.", amberWarn);
            }
            if (IsPluginUpdateAvailable())
            {
                AppendLog("[NOTICE] Updated LOTRO Lua Plugin detected. Click 'Install LOTRO Plugin' to update your in-game plugin.", amberWarn);
            }

            // Background update check after UI is loaded
            this.Loaded += async (s, e) =>
            {
                await Task.Delay(1000);
                await RunUpdateCheckAsync(silent: true);
            };
        }

        private void InitializeUi()
        {
            var rootGrid = new Grid
            {
                Margin = new Thickness(16, 12, 16, 16),
                RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,*,Auto")
            };

            // 0. Header (Title, Version, Update Badge)
            var headerGrid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto"),
                Margin = new Thickness(0, 0, 0, 10)
            };

            var lblTitle = new TextBlock
            {
                Text = "LOTRO-TTS",
                FontSize = 20,
                FontWeight = FontWeight.Bold,
                Foreground = goldAccent,
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(lblTitle, 0);
            headerGrid.Children.Add(lblTitle);

            var lblVersion = new TextBlock
            {
                Text = AppVersion,
                FontSize = 11,
                Foreground = textMuted,
                VerticalAlignment = VerticalAlignment.Bottom,
                Margin = new Thickness(6, 0, 0, 3)
            };
            Grid.SetColumn(lblVersion, 1);
            headerGrid.Children.Add(lblVersion);

            var updateControls = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                Spacing = 10
            };

            chkIncludePrereleases = new CheckBox
            {
                Content = "Include Pre-Releases (Beta)",
                IsChecked = includePrereleases,
                Foreground = textMuted,
                FontSize = 11.5,
                VerticalAlignment = VerticalAlignment.Center
            };
            chkIncludePrereleases.IsCheckedChanged += (s, e) =>
            {
                includePrereleases = chkIncludePrereleases.IsChecked ?? false;
                SaveConfig();
                _ = RunUpdateCheckAsync(silent: true);
            };

            btnUpdateBadge = new Button
            {
                Content = "Check for Updates",
                FontSize = 12,
                Foreground = textMuted,
                Background = bgCard,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(10, 4),
                Cursor = new Cursor(StandardCursorType.Hand),
                VerticalAlignment = VerticalAlignment.Center
            };
            btnUpdateBadge.Click += OnUpdateBadgeClicked;

            updateControls.Children.Add(chkIncludePrereleases);
            updateControls.Children.Add(btnUpdateBadge);
            Grid.SetColumn(updateControls, 3);
            headerGrid.Children.Add(updateControls);

            Grid.SetRow(headerGrid, 0);
            rootGrid.Children.Add(headerGrid);

            // 1. Status Cards Row
            var statusGrid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("*,10,*,10,*"),
                Margin = new Thickness(0, 0, 0, 10)
            };

            string pythonFolder = OperatingSystem.IsWindows() ? "python/win64" : "python/linux64";
            lblEnvStatus = CreateStatusCard(statusGrid, 0, $"TTS Environment ({pythonFolder})");
            lblDbStatus = CreateStatusCard(statusGrid, 2, "Quest Database (data/lotro.db)");
            lblPluginStatus = CreateStatusCard(statusGrid, 4, "LOTRO Lua Plugin (Plugins/TTS)");

            Grid.SetRow(statusGrid, 1);
            rootGrid.Children.Add(statusGrid);

            // 2. Settings & Start Panel
            var configBorder = new Border
            {
                Background = bgCard,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(14, 10, 14, 10),
                Margin = new Thickness(0, 0, 0, 10)
            };

            // Outer grid: Left is all settings (*), Right is the Start/Stop button (180px)
            var configOuterGrid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("*,14,180")
            };

            var settingsPanel = new Grid
            {
                RowDefinitions = new RowDefinitions("Auto,Auto,Auto")
            };

            // Row 0: 4 dropdowns & volume slider
            var row0Grid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("1.1*,8,1.2*,8,0.9*,8,0.9*")
            };

            // Dropdown 1: Game Client Lang
            cmbClientLang = CreateDropdown(row0Grid, 0, 0, "Game Client Language (OCR):", new[]
            {
                "de — Deutsch (German)",
                "en — English",
                "fr — Français (French)"
            });
            cmbClientLang.SelectionChanged += (s, e) => SaveConfig();

            // Dropdown 2: TTS Voice Lang
            cmbTtsLang = CreateDropdown(row0Grid, 0, 2, "Spoken TTS Voice Language:", new[]
            {
                "de — Deutsch (Native Voices)",
                "en — English (Native Voices)",
                "fr — Français (Native Voices)",
                "es — Español (Voice Cloning)",
                "it — Italiano (Translated)",
                "nl — Nederlands (Translated)"
            });
            cmbTtsLang.SelectionChanged += (s, e) =>
            {
                PopulateNarratorVoices();
                SaveConfig();
            };

            // Dropdown 3: Compute Mode
            cmbComputeMode = CreateDropdown(row0Grid, 0, 4, "Compute Mode:", new[]
            {
                "auto — Auto (GPU / CPU)",
                "cuda — GPU (NVIDIA / AMD)",
                "cpu — CPU Only"
            });

            // Slider: Volume
            var volPanel = new StackPanel();
            lblVolumeTitle = new TextBlock
            {
                Text = "TTS Volume: 80%",
                FontSize = 11.5,
                Foreground = textMuted,
                Margin = new Thickness(0, 0, 0, 4)
            };
            sliderVolume = new Slider
            {
                Minimum = 0,
                Maximum = 100,
                Value = 80,
                VerticalAlignment = VerticalAlignment.Center
            };
            sliderVolume.PropertyChanged += (s, e) =>
            {
                if (e.Property.Name == nameof(Slider.Value))
                {
                    int v = (int)sliderVolume.Value;
                    currentVolume = v;
                    lblVolumeTitle.Text = $"TTS Volume: {v}%";
                    SaveConfig();
                    int targetPid = (activeProcess != null && !activeProcess.HasExited) ? activeProcess.Id : -1;
                    ThreadPool.QueueUserWorkItem(_ =>
                    {
                        ProcessVolumeManager.SetProcessVolume(targetPid, v);
                    });
                }
            };
            volPanel.Children.Add(lblVolumeTitle);
            volPanel.Children.Add(sliderVolume);
            Grid.SetRow(volPanel, 0);
            Grid.SetColumn(volPanel, 6);
            row0Grid.Children.Add(volPanel);

            Grid.SetRow(row0Grid, 0);
            settingsPanel.Children.Add(row0Grid);

            // Row 1: Middle Mouse trigger checkbox
            chkMiddleMouse = new CheckBox
            {
                Content = new TextBlock
                {
                    Text = "Enable Middle Mouse Button (Mouse 3) as In-Game Trigger / Stop Toggle (in addition to the LOTRO Plugin button)",
                    TextWrapping = TextWrapping.Wrap,
                    Foreground = textLight,
                    FontSize = 12
                },
                IsChecked = true,
                Margin = new Thickness(0, 6, 0, 0)
            };
            Grid.SetRow(chkMiddleMouse, 1);
            settingsPanel.Children.Add(chkMiddleMouse);

            // Row 2: Narrator Mode Controls in a WrapPanel
            var narratorPanel = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 6, 0, 0)
            };

            chkNarratorMode = new CheckBox
            {
                Content = "Narrator Mode (Audiobook — single voice):",
                IsChecked = false,
                Foreground = textLight,
                FontSize = 12,
                Margin = new Thickness(0, 0, 8, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            chkNarratorMode.IsCheckedChanged += (s, e) =>
            {
                cmbNarratorVoice.IsEnabled = chkNarratorMode.IsChecked ?? false;
                SaveConfig();
            };

            cmbNarratorVoice = new ComboBox
            {
                Width = 240,
                IsEnabled = false,
                FontSize = 12,
                VerticalAlignment = VerticalAlignment.Center
            };
            cmbNarratorVoice.SelectionChanged += (s, e) => SaveConfig();

            narratorPanel.Children.Add(chkNarratorMode);
            narratorPanel.Children.Add(cmbNarratorVoice);

            Grid.SetRow(narratorPanel, 2);
            settingsPanel.Children.Add(narratorPanel);

            Grid.SetColumn(settingsPanel, 0);
            configOuterGrid.Children.Add(settingsPanel);

            // Start/Stop Button in dedicated right column
            btnStartStop = new Button
            {
                Content = "START LOTRO-TTS",
                Background = greenOk,
                Foreground = Brushes.White,
                FontWeight = FontWeight.Bold,
                FontSize = 13,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                VerticalAlignment = VerticalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Center,
                VerticalContentAlignment = VerticalAlignment.Center,
                Cursor = new Cursor(StandardCursorType.Hand),
                CornerRadius = new CornerRadius(4)
            };
            btnStartStop.Click += OnStartStopClicked;
            Grid.SetColumn(btnStartStop, 2);
            configOuterGrid.Children.Add(btnStartStop);

            configBorder.Child = configOuterGrid;
            Grid.SetRow(configBorder, 2);
            rootGrid.Children.Add(configBorder);

            // 3. Maintenance & Tools Bar
            var toolsGrid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("*,6,*,6,*,6,*,6,*"),
                Margin = new Thickness(0, 0, 0, 10)
            };

            btnSetupAi = CreateToolButton(toolsGrid, 0, "Setup TTS (GPU/CPU)", OnSetupAiClicked);
            btnRebuildDb = CreateToolButton(toolsGrid, 2, "Build Quest DB", OnRebuildDbClicked);
            btnUpdateSources = CreateToolButton(toolsGrid, 4, "Update XMLs & DB", OnUpdateSourcesClicked);
            btnInstallPlugin = CreateToolButton(toolsGrid, 6, "Install LOTRO Plugin", OnInstallPluginClicked);
            btnTestSpeech = CreateToolButton(toolsGrid, 8, "Test Voice Output", OnTestSpeechClicked);

            Grid.SetRow(toolsGrid, 3);
            rootGrid.Children.Add(toolsGrid);

            // 4. Live Output Console
            var logBorder = new Border
            {
                Background = bgLog,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(4),
                Padding = new Thickness(8)
            };

            logScrollViewer = new ScrollViewer
            {
                HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
                VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto
            };

            logTextBlock = new SelectableTextBlock
            {
                FontFamily = FontFamily.Parse("Consolas, monospace"),
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Foreground = textLight,
                SelectionBrush = new SolidColorBrush(Color.Parse("#3B6E8C"))
            };

            logScrollViewer.Content = logTextBlock;
            logBorder.Child = logScrollViewer;
            Grid.SetRow(logBorder, 4);
            rootGrid.Children.Add(logBorder);

            // 5. Console Bottom Actions (Copy Log / Clear)
            var logActions = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                Spacing = 8,
                Margin = new Thickness(0, 6, 0, 0)
            };
            var btnCopyLog = new Button
            {
                Content = "Copy Log",
                FontSize = 11,
                Background = bgCard,
                Foreground = textMuted,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(8, 2),
                Cursor = new Cursor(StandardCursorType.Hand)
            };
            btnCopyLog.Click += async (s, e) =>
            {
                var sb = new StringBuilder();
                foreach (var m in logMessages) sb.AppendLine(m.Text);
                if (Clipboard != null)
                {
                    var dt = new DataTransfer();
                    dt.Add(DataTransferItem.CreateText(sb.ToString()));
                    await Clipboard.SetDataAsync(dt);
                }
            };
            var btnClearLog = new Button
            {
                Content = "Clear Log",
                FontSize = 11,
                Background = bgCard,
                Foreground = textMuted,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(8, 2),
                Cursor = new Cursor(StandardCursorType.Hand)
            };
            btnClearLog.Click += (s, e) =>
            {
                logMessages.Clear();
                logTextBlock.Inlines?.Clear();
            };

            logActions.Children.Add(btnCopyLog);
            logActions.Children.Add(btnClearLog);
            Grid.SetRow(logActions, 5);
            rootGrid.Children.Add(logActions);

            Content = rootGrid;
        }

        private TextBlock CreateStatusCard(Grid parent, int col, string title)
        {
            var border = new Border
            {
                Background = bgCard,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(12, 8)
            };
            var stack = new StackPanel();
            var lblTitle = new TextBlock
            {
                Text = title,
                FontSize = 11.5,
                Foreground = textMuted,
                Margin = new Thickness(0, 0, 0, 4)
            };
            var lblValue = new TextBlock
            {
                Text = "Checking...",
                FontSize = 13,
                FontWeight = FontWeight.Bold,
                Foreground = textLight
            };
            stack.Children.Add(lblTitle);
            stack.Children.Add(lblValue);
            border.Child = stack;

            Grid.SetColumn(border, col);
            parent.Children.Add(border);
            return lblValue;
        }

        private ComboBox CreateDropdown(Grid parent, int row, int col, string label, string[] items)
        {
            var stack = new StackPanel();
            var lbl = new TextBlock
            {
                Text = label,
                FontSize = 11.5,
                Foreground = textMuted,
                Margin = new Thickness(0, 0, 0, 4)
            };
            var cmb = new ComboBox
            {
                ItemsSource = items,
                SelectedIndex = 0,
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            stack.Children.Add(lbl);
            stack.Children.Add(cmb);

            Grid.SetRow(stack, row);
            Grid.SetColumn(stack, col);
            parent.Children.Add(stack);
            return cmb;
        }

        private Button CreateToolButton(Grid parent, int col, string text, EventHandler<Avalonia.Interactivity.RoutedEventArgs> onClick)
        {
            var btn = new Button
            {
                Content = text,
                Background = bgCard,
                Foreground = textLight,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                FontSize = 12,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Center,
                Padding = new Thickness(8, 6),
                Cursor = new Cursor(StandardCursorType.Hand),
                CornerRadius = new CornerRadius(4)
            };
            btn.Click += onClick;
            Grid.SetColumn(btn, col);
            parent.Children.Add(btn);
            return btn;
        }

        private void AppendLog(string line, IBrush? color = null)
        {
            if (string.IsNullOrEmpty(line)) return;
            Dispatcher.UIThread.Post(() =>
            {
                var brush = color ?? textLight;
                logMessages.Add(new LogMessage { Text = line, Brush = brush });
                if (logMessages.Count > 3000)
                {
                    for (int i = 0; i < 200; i++) logMessages.RemoveAt(0);
                }
                if (logTextBlock.Inlines != null)
                {
                    logTextBlock.Inlines.Add(new Run { Text = line + "\n", Foreground = brush });
                    if (logTextBlock.Inlines.Count > 3000)
                    {
                        for (int i = 0; i < 200; i++) logTextBlock.Inlines.RemoveAt(0);
                    }
                }
                logScrollViewer.ScrollToEnd();
            });
        }

        private string GetSelectedCode(ComboBox cmb, string fallback)
        {
            if (cmb.SelectedItem is string s)
            {
                int idx = s.IndexOf(' ');
                return idx > 0 ? s.Substring(0, idx).Trim() : fallback;
            }
            return fallback;
        }

        private void SelectByPrefix(ComboBox cmb, string code)
        {
            if (string.IsNullOrEmpty(code) || cmb.ItemsSource == null) return;
            int idx = 0;
            foreach (var item in cmb.ItemsSource)
            {
                if (item is string s && s.StartsWith(code + " ", StringComparison.OrdinalIgnoreCase))
                {
                    cmb.SelectedIndex = idx;
                    return;
                }
                idx++;
            }
        }

        private void LoadSavedWindowSize()
        {
            try
            {
                if (File.Exists(configPath))
                {
                    string json = File.ReadAllText(configPath, Encoding.UTF8);
                    using var doc = JsonDocument.Parse(json);
                    var root = doc.RootElement;

                    if (root.TryGetProperty("window_width", out var ww) && ww.TryGetDouble(out double w) && w >= MinWidth)
                    {
                        savedNormalWidth = w;
                    }
                    if (root.TryGetProperty("window_height", out var wh) && wh.TryGetDouble(out double h) && h >= MinHeight)
                    {
                        savedNormalHeight = h;
                    }
                    if (root.TryGetProperty("window_maximized", out var wm) && wm.ValueKind == JsonValueKind.True)
                    {
                        savedIsMaximized = true;
                    }
                }
            }
            catch { }
        }

        private void LoadConfig()
        {
            try
            {
                if (File.Exists(configPath))
                {
                    string json = File.ReadAllText(configPath, Encoding.UTF8);
                    using var doc = JsonDocument.Parse(json);
                    var root = doc.RootElement;

                    if (root.TryGetProperty("game_lang", out var g) || root.TryGetProperty("client_lang", out g))
                        SelectByPrefix(cmbClientLang, g.GetString()?.ToLowerInvariant() ?? "de");

                    if (root.TryGetProperty("tts_lang", out var t))
                        SelectByPrefix(cmbTtsLang, t.GetString()?.ToLowerInvariant() ?? "de");

                    if (root.TryGetProperty("volume", out var v) && v.TryGetInt32(out int vol))
                    {
                        currentVolume = Math.Clamp(vol, 0, 100);
                        sliderVolume.Value = currentVolume;
                        lblVolumeTitle.Text = $"TTS Volume: {currentVolume}%";
                    }

                    if (root.TryGetProperty("stop_hotkey", out var sh) && !string.IsNullOrWhiteSpace(sh.GetString()))
                    {
                        stopHotkey = sh.GetString()!.ToLowerInvariant().Trim();
                    }

                    if (root.TryGetProperty("narrator_mode", out var nm) && (nm.ValueKind == JsonValueKind.True || nm.ValueKind == JsonValueKind.False))
                    {
                        bool isNarrator = nm.GetBoolean();
                        chkNarratorMode.IsChecked = isNarrator;
                        cmbNarratorVoice.IsEnabled = isNarrator;
                    }

                    if (root.TryGetProperty("narrator_voice", out var nv) && !string.IsNullOrWhiteSpace(nv.GetString()))
                    {
                        savedNarratorVoice = nv.GetString()!.Trim();
                        SelectNarratorVoice(savedNarratorVoice);
                    }

                    if (root.TryGetProperty("middle_mouse", out var mm) && (mm.ValueKind == JsonValueKind.True || mm.ValueKind == JsonValueKind.False))
                    {
                        if (chkMiddleMouse != null) chkMiddleMouse.IsChecked = mm.GetBoolean();
                    }

                    if (root.TryGetProperty("include_prereleases", out var ip) && (ip.ValueKind == JsonValueKind.True || ip.ValueKind == JsonValueKind.False))
                    {
                        includePrereleases = ip.GetBoolean();
                        if (chkIncludePrereleases != null) chkIncludePrereleases.IsChecked = includePrereleases;
                    }
                }
                else
                {
                    SaveConfig();
                }
            }
            catch { }
        }

        private void PopulateNarratorVoices()
        {
            if (cmbNarratorVoice == null || cmbTtsLang == null) return;
            string ttsLang = GetSelectedCode(cmbTtsLang, "en");
            string voicesDir = Path.Combine(baseDir, "data", "voices");
            string langFolder = (ttsLang == "de" || ttsLang == "fr") ? ttsLang : "en";
            string indexFile = Path.Combine(voicesDir, langFolder, "voice_index.json");

            var items = new List<string>();
            string currentSelectedId = GetSelectedVoiceId(cmbNarratorVoice, savedNarratorVoice);

            if (File.Exists(indexFile))
            {
                try
                {
                    using var doc = JsonDocument.Parse(File.ReadAllText(indexFile, Encoding.UTF8));
                    var root = doc.RootElement;
                    if (root.ValueKind == JsonValueKind.Array)
                    {
                        var seen = new HashSet<string>();
                        foreach (var el in root.EnumerateArray())
                        {
                            if (el.TryGetProperty("voice_id", out var vidElem))
                            {
                                string vid = vidElem.GetString() ?? "";
                                if (!string.IsNullOrEmpty(vid) && seen.Add(vid))
                                {
                                    string npc = el.TryGetProperty("npc_name", out var n) ? n.GetString() ?? "" : "";
                                    string cat = el.TryGetProperty("category", out var c) ? c.GetString() ?? "" : "";
                                    string label = string.IsNullOrEmpty(npc) ? $"{vid} ({cat})" : $"{vid} — {npc} ({cat})";
                                    items.Add(label);
                                }
                            }
                        }
                    }
                }
                catch { }
            }

            if (items.Count == 0)
            {
                items.Add("man_male_1 — Horn / Narrator (man_male)");
                items.Add("man_male_15 — Athelward (man_male)");
                items.Add("elf_female_1 — Fimloth (elf_female)");
                items.Add("hobbit_male_1 — Pippin (hobbit_male)");
            }

            cmbNarratorVoice.ItemsSource = items;
            SelectNarratorVoice(currentSelectedId);
        }

        private void SelectNarratorVoice(string voiceId)
        {
            if (cmbNarratorVoice?.ItemsSource is IList<string> items)
            {
                for (int i = 0; i < items.Count; i++)
                {
                    if (items[i].StartsWith(voiceId + " ", StringComparison.OrdinalIgnoreCase)
                        || items[i].StartsWith(voiceId + "—", StringComparison.OrdinalIgnoreCase)
                        || items[i].Equals(voiceId, StringComparison.OrdinalIgnoreCase))
                    {
                        cmbNarratorVoice.SelectedIndex = i;
                        return;
                    }
                }
                if (items.Count > 0) cmbNarratorVoice.SelectedIndex = 0;
            }
        }

        private static string GetSelectedVoiceId(ComboBox cmb, string defaultVoice = "man_male_1")
        {
            if (cmb?.SelectedItem is string s)
            {
                int sep = s.IndexOf('—');
                if (sep > 0) return s.Substring(0, sep).Trim();
                int space = s.IndexOf(' ');
                if (space > 0) return s.Substring(0, space).Trim();
                return s.Trim();
            }
            return defaultVoice;
        }

        private void SaveConfig()
        {
            if (isLoadingConfig) return;
            try
            {
                string gameLang = GetSelectedCode(cmbClientLang, "de");
                string ttsLang = GetSelectedCode(cmbTtsLang, "de");
                int volume = (int)sliderVolume.Value;
                bool middleMouse = chkMiddleMouse?.IsChecked ?? true;
                bool narratorMode = chkNarratorMode?.IsChecked ?? false;
                string narratorVoice = GetSelectedVoiceId(cmbNarratorVoice, savedNarratorVoice);
                savedNarratorVoice = narratorVoice;

                if (WindowState == WindowState.Maximized)
                {
                    savedIsMaximized = true;
                }
                else
                {
                    savedIsMaximized = false;
                    if (Bounds.Width >= MinWidth) savedNormalWidth = Bounds.Width;
                    else if (Width >= MinWidth) savedNormalWidth = Width;

                    if (Bounds.Height >= MinHeight) savedNormalHeight = Bounds.Height;
                    else if (Height >= MinHeight) savedNormalHeight = Height;
                }

                var data = new
                {
                    version = AppVersion,
                    game_lang = gameLang,
                    tts_lang = ttsLang,
                    volume = volume,
                    stop_hotkey = stopHotkey,
                    middle_mouse = middleMouse,
                    narrator_mode = narratorMode,
                    narrator_voice = narratorVoice,
                    include_prereleases = includePrereleases,
                    window_width = (int)Math.Round(savedNormalWidth),
                    window_height = (int)Math.Round(savedNormalHeight),
                    window_maximized = savedIsMaximized
                };
                string json = JsonSerializer.Serialize(data, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(configPath, json, new UTF8Encoding(false));
            }
            catch { }
        }

        private bool IsAiEnvironmentReady()
        {
            string incompleteMarker = Path.Combine(baseDir, "python", ".setup_incomplete");
            if (File.Exists(incompleteMarker))
                return false;

            if (OperatingSystem.IsWindows())
            {
                string sitePackages = Path.Combine(baseDir, "python", "win64", "Lib", "site-packages");
                return File.Exists(pythonExe)
                    && Directory.Exists(Path.Combine(sitePackages, "torch"))
                    && Directory.Exists(Path.Combine(sitePackages, "omnivoice"));
            }
            else
            {
                string linPy = Path.Combine(baseDir, "python", "linux64", "bin", "python3");
                if (!File.Exists(linPy)) return false;
                string libDir = Path.Combine(baseDir, "python", "linux64", "lib");
                if (!Directory.Exists(libDir)) return false;
                foreach (var d in Directory.GetDirectories(libDir, "python3*"))
                {
                    string sp = Path.Combine(d, "site-packages");
                    if (Directory.Exists(Path.Combine(sp, "torch")) && Directory.Exists(Path.Combine(sp, "omnivoice")))
                        return true;
                }
                return false;
            }
        }

        private bool IsDatabaseReady()
        {
            string dbFile = Path.Combine(baseDir, "data", "lotro.db");
            if (!File.Exists(dbFile)) return false;
            return new FileInfo(dbFile).Length > 5 * 1024 * 1024;
        }

        private bool IsPluginInstalled()
        {
            try
            {
                string lotroDocs = LotroPathDetector.GetLotroDocumentsDir();
                string ttsDir = Path.Combine(lotroDocs, "Plugins", "TTS");
                return File.Exists(Path.Combine(ttsDir, "Main.lua"))
                    && (File.Exists(Path.Combine(ttsDir, "TTS.plugin")) || File.Exists(Path.Combine(lotroDocs, "Plugins", "TTS.plugin")));
            }
            catch
            {
                return false;
            }
        }

        private bool AreDatabaseSourcesNewer(string dbFile)
        {
            try
            {
                if (!File.Exists(dbFile)) return false;
                DateTime dbTime = File.GetLastWriteTimeUtc(dbFile);

                string srcDir = Path.Combine(baseDir, "src");
                if (Directory.Exists(srcDir))
                {
                    foreach (string f in Directory.GetFiles(srcDir, "*.xml", SearchOption.AllDirectories))
                    {
                        if (File.GetLastWriteTimeUtc(f) > dbTime) return true;
                    }
                }

                string voicesDir = Path.Combine(baseDir, "data", "voices");
                if (Directory.Exists(voicesDir))
                {
                    foreach (string f in Directory.GetFiles(voicesDir, "voice_index.json", SearchOption.AllDirectories))
                    {
                        if (File.GetLastWriteTimeUtc(f) > dbTime) return true;
                    }
                }
            }
            catch { }
            return false;
        }

        private static bool FilesDiffer(string file1, string file2)
        {
            try
            {
                var fi1 = new FileInfo(file1);
                var fi2 = new FileInfo(file2);
                if (fi1.Length != fi2.Length) return true;
                byte[] b1 = File.ReadAllBytes(file1);
                byte[] b2 = File.ReadAllBytes(file2);
                return !b1.AsSpan().SequenceEqual(b2);
            }
            catch
            {
                return true;
            }
        }

        private bool IsPluginUpdateAvailable()
        {
            try
            {
                if (!IsPluginInstalled()) return false;

                string lotroDocs = LotroPathDetector.GetLotroDocumentsDir();
                string installedDir = Path.Combine(lotroDocs, "Plugins", "TTS");
                string repoDir = Path.Combine(baseDir, "src", "plugins", "TTS");

                if (!Directory.Exists(repoDir) || !Directory.Exists(installedDir))
                    return false;

                foreach (string repoFile in Directory.GetFiles(repoDir))
                {
                    string fileName = Path.GetFileName(repoFile);
                    string installedFile = Path.Combine(installedDir, fileName);
                    if (!File.Exists(installedFile) || FilesDiffer(repoFile, installedFile))
                    {
                        return true;
                    }
                }
            }
            catch { }
            return false;
        }

        private void RefreshSystemStatus()
        {
            Dispatcher.UIThread.Post(() =>
            {
                if (IsAiEnvironmentReady())
                {
                    string hw = "CPU";
                    if (OperatingSystem.IsWindows())
                    {
                        string torchLib = Path.Combine(baseDir, "python", "win64", "Lib", "site-packages", "torch", "lib");
                        if (File.Exists(Path.Combine(torchLib, "amdhip64.dll")) || File.Exists(Path.Combine(torchLib, "torch_hip.dll")))
                            hw = "AMD ROCm";
                        else if (File.Exists(Path.Combine(torchLib, "torch_cuda.dll")))
                            hw = "NVIDIA CUDA";
                    }
                    else
                    {
                        string linLib = Path.Combine(baseDir, "python", "linux64", "lib");
                        if (Directory.Exists(linLib))
                        {
                            foreach (var pydir in Directory.GetDirectories(linLib, "python3*"))
                            {
                                string tLib = Path.Combine(pydir, "site-packages", "torch", "lib");
                                if (Directory.Exists(tLib))
                                {
                                    if (File.Exists(Path.Combine(tLib, "libtorch_hip.so"))) hw = "AMD ROCm";
                                    else if (File.Exists(Path.Combine(tLib, "libtorch_cuda.so"))) hw = "NVIDIA CUDA";
                                }
                            }
                        }
                    }

                    lblEnvStatus.Text = $"Ready ({hw})";
                    lblEnvStatus.Foreground = greenOk;
                }
                else
                {
                    string incompleteMarker = Path.Combine(baseDir, "python", ".setup_incomplete");
                    if (File.Exists(incompleteMarker))
                    {
                        lblEnvStatus.Text = "Incomplete / Failed (Click Setup TTS)";
                        lblEnvStatus.Foreground = redStop;
                    }
                    else
                    {
                        lblEnvStatus.Text = "Not Installed (Click Setup TTS)";
                        lblEnvStatus.Foreground = amberWarn;
                    }
                }

                string dbFile = Path.Combine(baseDir, "data", "lotro.db");
                if (IsDatabaseReady())
                {
                    long mb = new FileInfo(dbFile).Length / (1024 * 1024);
                    if (AreDatabaseSourcesNewer(dbFile))
                    {
                        lblDbStatus.Text = "Update Available (Click Build DB)";
                        lblDbStatus.Foreground = amberWarn;
                    }
                    else
                    {
                        lblDbStatus.Text = $"Ready ({mb} MB / 190 Voices)";
                        lblDbStatus.Foreground = greenOk;
                    }
                }
                else
                {
                    lblDbStatus.Text = "Missing (Auto-builds on Start)";
                    lblDbStatus.Foreground = amberWarn;
                }

                if (IsPluginInstalled())
                {
                    if (IsPluginUpdateAvailable())
                    {
                        lblPluginStatus.Text = "Update Available (Click Install)";
                        lblPluginStatus.Foreground = amberWarn;
                    }
                    else
                    {
                        lblPluginStatus.Text = "Installed in LOTRO";
                        lblPluginStatus.Foreground = greenOk;
                    }
                }
                else
                {
                    lblPluginStatus.Text = "Not Installed (Click Install)";
                    lblPluginStatus.Foreground = amberWarn;
                }
            });
        }

        private void SetButtonsEnabled(bool enabled)
        {
            Dispatcher.UIThread.Post(() =>
            {
                btnSetupAi.IsEnabled = enabled;
                btnRebuildDb.IsEnabled = enabled;
                btnUpdateSources.IsEnabled = enabled;
                btnInstallPlugin.IsEnabled = enabled;
                btnTestSpeech.IsEnabled = enabled;
                cmbClientLang.IsEnabled = enabled;
                cmbTtsLang.IsEnabled = enabled;
                cmbComputeMode.IsEnabled = enabled;
                chkMiddleMouse.IsEnabled = enabled;
            });
        }

        private void InstallLuaPluginSilent()
        {
            try
            {
                string srcDir = Path.Combine(baseDir, "src", "plugins", "TTS");
                if (!Directory.Exists(srcDir))
                {
                    AppendLog($"[ERROR] Plugin source folder not found: {srcDir}", redStop);
                    return;
                }
                string lotroDocs = LotroPathDetector.GetLotroDocumentsDir();
                string pluginsRoot = Path.Combine(lotroDocs, "Plugins");
                string targetTtsDir = Path.Combine(pluginsRoot, "TTS");
                Directory.CreateDirectory(targetTtsDir);

                foreach (string file in Directory.GetFiles(srcDir))
                {
                    string dest = Path.Combine(targetTtsDir, Path.GetFileName(file));
                    File.Copy(file, dest, true);
                }

                // Clean up any legacy duplicate TTS.plugin directly under Plugins/
                string legacyPluginDescriptor = Path.Combine(pluginsRoot, "TTS.plugin");
                if (File.Exists(legacyPluginDescriptor))
                {
                    try { File.Delete(legacyPluginDescriptor); } catch { }
                }

                AppendLog($"[OK] LOTRO Lua Plugin installed to: {targetTtsDir}", greenOk);
                RefreshSystemStatus();
            }
            catch (Exception ex)
            {
                AppendLog($"[ERROR] Could not install LOTRO Lua Plugin: {ex.Message}", redStop);
            }
        }

        private async void OnStartStopClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            if (isServiceRunning)
            {
                StopActiveProcess();
                return;
            }

            if (isTaskRunning)
            {
                AppendLog("[NOTICE] A task is currently running. Please wait for it to finish.", amberWarn);
                return;
            }

            SaveConfig();

            if (!IsPluginInstalled() || IsPluginUpdateAvailable())
            {
                InstallLuaPluginSilent();
            }

            if (!IsAiEnvironmentReady())
            {
                var dlg = new SetupAiDialog();
                await dlg.ShowDialog(this);
                if (string.IsNullOrEmpty(dlg.SelectedMode)) return;

                RunSequentialTasksAndStartService(dlg.SelectedMode, !IsDatabaseReady());
                return;
            }

            if (!File.Exists(pythonExe))
            {
                AppendLog($"[ERROR] Python was not found at: {pythonExe}", redStop);
                return;
            }

            if (!IsDatabaseReady())
            {
                RunSequentialTasksAndStartService(null, true);
                return;
            }

            StartTtsServiceProcess();
        }

        private void RunSequentialTasksAndStartService(string? setupMode, bool buildDb)
        {
            isTaskRunning = true;
            SetButtonsEnabled(false);
            btnStartStop.IsEnabled = false;

            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    if (OperatingSystem.IsLinux() && !File.Exists(pythonExe))
                    {
                        bool ok = EnsureLinuxPythonAvailable();
                        if (!ok)
                        {
                            Dispatcher.UIThread.Post(() =>
                            {
                                isTaskRunning = false;
                                SetButtonsEnabled(true);
                                btnStartStop.IsEnabled = true;
                            });
                            return;
                        }
                    }

                    if (!string.IsNullOrEmpty(setupMode))
                    {
                        AppendLog($"\n>>> Running First-Time TTS Environment Setup ({setupMode.ToUpperInvariant()})...", goldAccent);
                        int code = RunPythonBlocking($"-u \"scripts/setup_tts.py\" --mode {setupMode}");
                        RefreshSystemStatus();
                        if (code != 0)
                        {
                            AppendLog($"[ERROR] TTS Environment Setup exited with code {code}", redStop);
                            return;
                        }
                    }

                    if (buildDb || !IsDatabaseReady())
                    {
                        AppendLog("\n>>> Building SQLite Quest Database (data/lotro.db)...", goldAccent);
                        int code = RunPythonBlocking("-u \"scripts/generate_db.py\"");
                        RefreshSystemStatus();
                        if (code != 0)
                        {
                            AppendLog($"[ERROR] Database generation exited with code {code}", redStop);
                            return;
                        }
                    }

                    Dispatcher.UIThread.Post(() =>
                    {
                        isTaskRunning = false;
                        btnStartStop.IsEnabled = true;
                        StartTtsServiceProcess();
                    });
                }
                finally
                {
                    Dispatcher.UIThread.Post(() =>
                    {
                        isTaskRunning = false;
                        btnStartStop.IsEnabled = true;
                        if (!isServiceRunning) SetButtonsEnabled(true);
                    });
                }
            });
        }

        private int RunPythonBlocking(string arguments)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = pythonExe,
                    Arguments = arguments,
                    WorkingDirectory = baseDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                psi.EnvironmentVariables["PYTHONUTF8"] = "1";
                psi.EnvironmentVariables["HF_HUB_VERBOSITY"] = "error";
                psi.EnvironmentVariables["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1";

                using var p = new Process { StartInfo = psi };
                p.OutputDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                p.ErrorDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                p.Start();
                p.BeginOutputReadLine();
                p.BeginErrorReadLine();
                using var watcherCts = new CancellationTokenSource();
                var token = watcherCts.Token;
                int pid = p.Id;

                if (OperatingSystem.IsWindows())
                {
                    ThreadPool.QueueUserWorkItem(_ =>
                    {
                        while (!token.IsCancellationRequested)
                        {
                            try
                            {
                                ProcessVolumeManager.SetProcessVolume(pid, currentVolume);
                            }
                            catch { }
                            try { Task.Delay(200, token).Wait(); } catch { break; }
                        }
                    });
                }
                p.WaitForExit();
                watcherCts.Cancel();
                return p.ExitCode;
            }
            catch (Exception ex)
            {
                AppendLog($"[ERROR] {ex.Message}", redStop);
                return -1;
            }
        }

        private bool EnsureLinuxPythonAvailable()
        {
            if (!OperatingSystem.IsLinux()) return true;

            string linuxPyDir = Path.Combine(baseDir, "python", "linux64");
            string linuxPyExe = Path.Combine(linuxPyDir, "bin", "python3");

            if (File.Exists(linuxPyExe))
            {
                pythonExe = linuxPyExe;
                return true;
            }

            AppendLog("\n========================================================", goldAccent);
            AppendLog(">>> Standalone Python for Linux not found.", goldAccent);
            AppendLog(">>> Downloading portable Python 3.13 from python-build-standalone...", goldAccent);
            AppendLog("========================================================", goldAccent);

            string downloadUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.13.0+20241016-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz";
            string tempTar = Path.Combine(baseDir, "python", "linux64_python.tar.gz");

            try
            {
                Directory.CreateDirectory(Path.Combine(baseDir, "python"));
                if (Directory.Exists(linuxPyDir))
                {
                    try { Directory.Delete(linuxPyDir, true); } catch { }
                }
                Directory.CreateDirectory(linuxPyDir);

                using (var client = new HttpClient())
                {
                    client.DefaultRequestHeaders.Add("User-Agent", "LOTRO-TTS-Installer");
                    using var response = client.GetAsync(downloadUrl, HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult();
                    response.EnsureSuccessStatusCode();

                    long? totalBytes = response.Content.Headers.ContentLength;
                    using var inStream = response.Content.ReadAsStream();
                    using var outStream = new FileStream(tempTar, FileMode.Create, FileAccess.Write, FileShare.None);

                    byte[] buffer = new byte[128 * 1024];
                    long downloaded = 0;
                    long lastReport = 0;
                    int bytesRead;

                    while ((bytesRead = inStream.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        outStream.Write(buffer, 0, bytesRead);
                        downloaded += bytesRead;
                        if (downloaded - lastReport >= 5 * 1024 * 1024 || (totalBytes.HasValue && downloaded == totalBytes.Value))
                        {
                            lastReport = downloaded;
                            double mb = downloaded / (1024.0 * 1024.0);
                            if (totalBytes.HasValue)
                            {
                                double totalMb = totalBytes.Value / (1024.0 * 1024.0);
                                AppendLog($"  Downloading: {mb:F1} MB / {totalMb:F1} MB ({(int)(downloaded * 100 / totalBytes.Value)}%)...");
                            }
                            else
                            {
                                AppendLog($"  Downloading: {mb:F1} MB...");
                            }
                        }
                    }
                }

                AppendLog(">>> Extracting portable Python to python/linux64...", goldAccent);

                bool tarSuccess = false;
                try
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = "tar",
                        Arguments = $"-xzf \"{tempTar}\" -C \"{linuxPyDir}\" --strip-components=1",
                        UseShellExecute = false,
                        CreateNoWindow = true
                    };
                    using var p = Process.Start(psi);
                    p?.WaitForExit();
                    tarSuccess = (p?.ExitCode == 0);
                }
                catch { }

                if (!tarSuccess || !File.Exists(linuxPyExe))
                {
                    using var fs = File.OpenRead(tempTar);
                    using var gz = new GZipStream(fs, CompressionMode.Decompress);
                    using var reader = new TarReader(gz);

                    while (reader.GetNextEntry() is { } entry)
                    {
                        string rel = entry.Name;
                        int slash = rel.IndexOf('/');
                        if (slash >= 0) rel = rel.Substring(slash + 1);
                        if (string.IsNullOrEmpty(rel)) continue;

                        string dest = Path.Combine(linuxPyDir, rel);
                        if (entry.EntryType == TarEntryType.Directory)
                        {
                            Directory.CreateDirectory(dest);
                        }
                        else if (entry.EntryType is TarEntryType.RegularFile or TarEntryType.V7RegularFile)
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                            entry.ExtractToFile(dest, overwrite: true);
                        }
                        else if (entry.EntryType == TarEntryType.SymbolicLink)
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                            if (File.Exists(dest) || Directory.Exists(dest)) File.Delete(dest);
                            File.CreateSymbolicLink(dest, entry.LinkName);
                        }
                    }
                }

                try { File.Delete(tempTar); } catch { }

                try
                {
                    File.SetUnixFileMode(linuxPyExe, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
                                                     UnixFileMode.GroupRead | UnixFileMode.GroupExecute |
                                                     UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
                }
                catch
                {
                    try
                    {
                        using var cp = Process.Start(new ProcessStartInfo("chmod", $"+x \"{linuxPyExe}\"") { UseShellExecute = false, CreateNoWindow = true });
                        cp?.WaitForExit(2000);
                    }
                    catch { }
                }

                if (File.Exists(linuxPyExe))
                {
                    pythonExe = linuxPyExe;
                    AppendLog("[OK] Portable Python successfully installed to python/linux64!", greenOk);
                    Dispatcher.UIThread.Post(RefreshSystemStatus);
                    return true;
                }
                else
                {
                    AppendLog($"[ERROR] Failed to extract Python to {linuxPyExe}", redStop);
                    return false;
                }
            }
            catch (Exception ex)
            {
                AppendLog($"[ERROR] Failed to download portable Python: {ex.Message}", redStop);
                try { if (File.Exists(tempTar)) File.Delete(tempTar); } catch { }
                return false;
            }
        }

        private void StartTtsServiceProcess()
        {
            string clientLang = GetSelectedCode(cmbClientLang, "de");
            string ttsLang = GetSelectedCode(cmbTtsLang, "de");
            string mode = GetSelectedCode(cmbComputeMode, "auto");
            int volume = (int)sliderVolume.Value;
            bool useMouse = chkMiddleMouse.IsChecked ?? true;

            bool narratorMode = chkNarratorMode.IsChecked ?? false;
            string narratorVoice = GetSelectedVoiceId(cmbNarratorVoice, savedNarratorVoice);

            string args = $"-u \"scripts/lotro_service.py\" --client-lang {clientLang} --tts-lang {ttsLang} --mode {mode} --volume {volume} --stop-hotkey {stopHotkey}" +
                          (narratorMode ? $" --narrator-mode --narrator-voice {narratorVoice}" : "") +
                          (useMouse ? "" : " --no-mouse");

            AppendLog("\n======================================================================", goldAccent);
            AppendLog($"Starting LOTRO-TTS Service [Client: {clientLang.ToUpperInvariant()} | TTS: {ttsLang.ToUpperInvariant()} | Mode: {mode.ToUpperInvariant()} | Vol: {volume}%]...", goldAccent);
            AppendLog($"[HOTKEY] Press [{stopHotkey.ToUpperInvariant()}], [ESC], or [MOUSE 3] anytime in-game to instantly force-stop dialogue.", goldAccent);
            if (narratorMode)
            {
                AppendLog($"[NARRATOR MODE] Active — all dialogue will be read using single narrator voice: '{narratorVoice}'", goldAccent);
            }
            AppendLog("======================================================================", goldAccent);

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = pythonExe,
                    Arguments = args,
                    WorkingDirectory = baseDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                psi.EnvironmentVariables["PYTHONUTF8"] = "1";
                psi.EnvironmentVariables["HF_HUB_VERBOSITY"] = "error";
                psi.EnvironmentVariables["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1";

                activeProcess = new Process { StartInfo = psi, EnableRaisingEvents = true };
                activeProcess.OutputDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                activeProcess.ErrorDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                activeProcess.Exited += (s, ev) =>
                {
                    serviceVolumeWatcherCts?.Cancel();
                    serviceVolumeWatcherCts = null;
                    Dispatcher.UIThread.Post(() =>
                    {
                        isServiceRunning = false;
                        btnStartStop.Content = "START LOTRO-TTS";
                        btnStartStop.Background = greenOk;
                        SetButtonsEnabled(true);
                        AppendLog("[Service Stopped]", amberWarn);
                    });
                };

                activeProcess.Start();
                activeProcess.BeginOutputReadLine();
                activeProcess.BeginErrorReadLine();

                serviceVolumeWatcherCts?.Cancel();
                serviceVolumeWatcherCts = new CancellationTokenSource();
                var token = serviceVolumeWatcherCts.Token;
                int svcPid = activeProcess.Id;
                if (OperatingSystem.IsWindows())
                {
                    ThreadPool.QueueUserWorkItem(_ =>
                    {
                        while (!token.IsCancellationRequested && activeProcess != null && !activeProcess.HasExited)
                        {
                            ProcessVolumeManager.SetProcessVolume(svcPid, currentVolume);
                            try { Task.Delay(250, token).Wait(); } catch { break; }
                        }
                    });
                }

                isServiceRunning = true;
                btnStartStop.Content = "STOP LOTRO-TTS";
                btnStartStop.Background = redStop;
                SetButtonsEnabled(false);
            }
            catch (Exception ex)
            {
                AppendLog($"[ERROR] Failed to start service: {ex.Message}", redStop);
            }
        }

        private void StopActiveProcess()
        {
            try
            {
                serviceVolumeWatcherCts?.Cancel();
                serviceVolumeWatcherCts = null;
                if (activeProcess != null && !activeProcess.HasExited)
                {
                    AppendLog("Stopping LOTRO-TTS Service...", amberWarn);
                    if (OperatingSystem.IsWindows())
                    {
                        try
                        {
                            var killPsi = new ProcessStartInfo
                            {
                                FileName = "taskkill",
                                Arguments = $"/PID {activeProcess.Id} /T /F",
                                CreateNoWindow = true,
                                UseShellExecute = false
                            };
                            using var kp = Process.Start(killPsi);
                            kp?.WaitForExit(3000);
                        }
                        catch { activeProcess.Kill(); }
                    }
                    else
                    {
                        try
                        {
                            activeProcess.Kill(entireProcessTree: true);
                        }
                        catch { activeProcess.Kill(); }
                    }
                }
            }
            catch { }
        }

        private void RunBackgroundToolTask(string title, string pythonArgs)
        {
            if (isServiceRunning || isTaskRunning) return;
            isTaskRunning = true;
            SetButtonsEnabled(false);
            btnStartStop.IsEnabled = false;

            AppendLog($"\n>>> {title}...", goldAccent);
            ThreadPool.QueueUserWorkItem(_ =>
            {
                if (OperatingSystem.IsLinux() && !File.Exists(pythonExe))
                {
                    bool ok = EnsureLinuxPythonAvailable();
                    if (!ok)
                    {
                        Dispatcher.UIThread.Post(() =>
                        {
                            isTaskRunning = false;
                            SetButtonsEnabled(true);
                            btnStartStop.IsEnabled = true;
                        });
                        return;
                    }
                }

                int code = RunPythonBlocking(pythonArgs);
                Dispatcher.UIThread.Post(() =>
                {
                    if (code == 0)
                        AppendLog($"[OK] {title} completed successfully!", greenOk);
                    else
                        AppendLog($"[ERROR] {title} exited with code {code}", redStop);

                    RefreshSystemStatus();
                    isTaskRunning = false;
                    SetButtonsEnabled(true);
                    btnStartStop.IsEnabled = true;
                });
            });
        }

        private async void OnSetupAiClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            if (isServiceRunning || isTaskRunning) return;

            var dlg = new SetupAiDialog();
            await dlg.ShowDialog(this);
            if (string.IsNullOrEmpty(dlg.SelectedMode)) return;
            string mode = dlg.SelectedMode;

            if (!IsPluginInstalled() || IsPluginUpdateAvailable())
            {
                InstallLuaPluginSilent();
            }

            isTaskRunning = true;
            SetButtonsEnabled(false);
            btnStartStop.IsEnabled = false;

            AppendLog($"\n>>> TTS Environment Setup ({mode.ToUpperInvariant()})...", goldAccent);
            ThreadPool.QueueUserWorkItem(_ =>
            {
                if (OperatingSystem.IsLinux() && !File.Exists(pythonExe))
                {
                    bool ok = EnsureLinuxPythonAvailable();
                    if (!ok)
                    {
                        Dispatcher.UIThread.Post(() =>
                        {
                            isTaskRunning = false;
                            SetButtonsEnabled(true);
                            btnStartStop.IsEnabled = true;
                        });
                        return;
                    }
                }

                int code = RunPythonBlocking($"-u \"scripts/setup_tts.py\" --mode {mode}");
                if (code == 0 && !IsDatabaseReady())
                {
                    AppendLog("\n>>> Building SQLite Quest Database (data/lotro.db)...", goldAccent);
                    code = RunPythonBlocking("-u \"scripts/generate_db.py\"");
                }
                Dispatcher.UIThread.Post(() =>
                {
                    if (code == 0)
                        AppendLog("[OK] TTS Engine & Database Setup completed successfully!", greenOk);
                    else
                        AppendLog($"[ERROR] Setup exited with code {code}", redStop);

                    RefreshSystemStatus();
                    isTaskRunning = false;
                    SetButtonsEnabled(true);
                    btnStartStop.IsEnabled = true;
                });
            });
        }

        private void OnRebuildDbClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            RunBackgroundToolTask("Generating SQLite Quest Database (data/lotro.db)", "-u \"scripts/generate_db.py\"");
        }

        private void OnUpdateSourcesClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            RunBackgroundToolTask("Updating Quest & NPC XML Sources + Rebuilding DB", "-u \"scripts/update_sources.py\" --generate-db");
        }

        private void OnInstallPluginClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            InstallLuaPluginSilent();
        }

        private void OnTestSpeechClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            if (!IsAiEnvironmentReady())
            {
                AppendLog("[ERROR] TTS AI Environment is not set up yet. Please click 'Setup TTS (GPU/CPU)' first.", redStop);
                return;
            }

            string ttsLang = GetSelectedCode(cmbTtsLang, "de");
            int volume = (int)sliderVolume.Value;
            string sampleText = "Die Welt ist im Wandel. Ich spüre es im Wasser, ich spüre es in der Erde.";
            if (ttsLang == "en") sampleText = "The world is changed. I feel it in the water, I feel it in the earth.";
            else if (ttsLang == "fr") sampleText = "Le monde a changé. Je le sens dans l'eau, je le sens dans la terre.";
            else if (ttsLang == "es") sampleText = "El mundo ha cambiado. Lo siento en el agua, lo siento en la tierra.";
            else if (ttsLang == "it") sampleText = "Il mondo è cambiato. Lo sento nell'acqua, lo sento nella terra.";

            string args = $"-u \"scripts/tts_speaker.py\" --npc \"Galadriel\" --lang {ttsLang} --volume {volume} --text \"{sampleText}\"";
            RunBackgroundToolTask($"Testing TTS Voice Output (Galadriel / {ttsLang.ToUpperInvariant()} / Vol: {volume}%)", args);
        }

        private async void OnUpdateBadgeClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
        {
            if (latestUpdateInfo != null && latestUpdateInfo.IsNewer)
            {
                var dlg = new UpdateDialog(latestUpdateInfo, baseDir);
                await dlg.ShowDialog(this);
            }
            else
            {
                await RunUpdateCheckAsync(silent: false);
            }
        }

        private async Task RunUpdateCheckAsync(bool silent)
        {
            if (isCheckingUpdates) return;
            isCheckingUpdates = true;

            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                btnUpdateBadge.Content = "Checking...";
                btnUpdateBadge.IsEnabled = false;
            });

            try
            {
                var info = await UpdateChecker.CheckForUpdateAsync(AppVersion, includePrereleases);
                latestUpdateInfo = info;

                await Dispatcher.UIThread.InvokeAsync(async () =>
                {
                    btnUpdateBadge.IsEnabled = true;

                    if (info != null && info.IsNewer)
                    {
                        if (info.IsPrerelease)
                        {
                            btnUpdateBadge.Content = $"Pre-Release: {info.TagName}";
                            btnUpdateBadge.Foreground = Brushes.White;
                            btnUpdateBadge.Background = amberWarn;
                            btnUpdateBadge.FontWeight = FontWeight.Bold;

                            AppendLog($"[UPDATE] A new pre-release (Beta) is available: {info.TagName} ({info.ReleaseName})", amberWarn);
                            AppendLog("  Click 'Pre-Release' in the top right to view details.", textLight);
                        }
                        else
                        {
                            btnUpdateBadge.Content = $"Update: {info.TagName}";
                            btnUpdateBadge.Foreground = Brushes.White;
                            btnUpdateBadge.Background = new SolidColorBrush(Color.FromRgb(170, 120, 15));
                            btnUpdateBadge.FontWeight = FontWeight.Bold;

                            AppendLog($"[UPDATE] A new version of LOTRO-TTS is available: {info.TagName} ({info.ReleaseName})", goldAccent);
                            AppendLog("  Click 'Update' in the top right to view details.", textLight);
                        }

                        if (!silent)
                        {
                            var dlg = new UpdateDialog(info, baseDir);
                            await dlg.ShowDialog(this);
                        }
                    }
                    else if (info != null)
                    {
                        btnUpdateBadge.Content = $"Up to Date ({AppVersion})";
                        btnUpdateBadge.Foreground = new SolidColorBrush(Color.FromRgb(110, 190, 120));
                        btnUpdateBadge.Background = new SolidColorBrush(Color.FromRgb(24, 34, 28));
                        btnUpdateBadge.FontWeight = FontWeight.Normal;

                        if (!silent)
                        {
                            AppendLog($"[OK] You are running the latest version of LOTRO-TTS ({AppVersion}).", greenOk);
                            string releaseDetails = !string.IsNullOrEmpty(info.TagName)
                                ? $"Latest release on GitHub: {info.TagName}"
                                : "";
                            if (!string.IsNullOrEmpty(info.ReleaseName) && info.ReleaseName != info.TagName)
                            {
                                releaseDetails += $" ({info.ReleaseName})";
                            }

                            string message = $"You are running the newest version of LOTRO-TTS ({AppVersion}). No update is required.";
                            if (!string.IsNullOrEmpty(releaseDetails))
                            {
                                message += $"\n\n{releaseDetails}";
                            }

                            await MessageDialog.ShowAsync(
                                this,
                                "LOTRO-TTS Update Check",
                                "You are up to date!",
                                message,
                                MessageDialogType.Success,
                                "https://github.com/ElianMoirtide/LOTRO-TTS/releases",
                                "View Releases"
                            );
                        }
                    }
                    else
                    {
                        btnUpdateBadge.Content = "Check for Updates";
                        btnUpdateBadge.Foreground = textMuted;
                        btnUpdateBadge.Background = bgCard;
                        btnUpdateBadge.FontWeight = FontWeight.Normal;

                        if (!silent)
                        {
                            AppendLog("[NOTICE] Update check failed: Could not connect to GitHub releases.", amberWarn);
                            await MessageDialog.ShowAsync(
                                this,
                                "LOTRO-TTS Update Check",
                                "Unable to Check for Updates",
                                "Could not connect to GitHub to check for updates.\n\nPlease verify your internet connection or check the GitHub releases page manually.",
                                MessageDialogType.Warning,
                                "https://github.com/ElianMoirtide/LOTRO-TTS/releases",
                                "Open GitHub Releases"
                            );
                        }
                    }
                });
            }
            catch (Exception ex)
            {
                await Dispatcher.UIThread.InvokeAsync(async () =>
                {
                    btnUpdateBadge.IsEnabled = true;
                    btnUpdateBadge.Content = "Check for Updates";
                    btnUpdateBadge.Foreground = textMuted;
                    btnUpdateBadge.Background = bgCard;
                    btnUpdateBadge.FontWeight = FontWeight.Normal;

                    if (!silent)
                    {
                        AppendLog($"[NOTICE] Update check failed: {ex.Message}", amberWarn);
                        await MessageDialog.ShowAsync(
                            this,
                            "LOTRO-TTS Update Check",
                            "Unable to Check for Updates",
                            $"An error occurred while checking for updates:\n\n{ex.Message}",
                            MessageDialogType.Warning,
                            "https://github.com/ElianMoirtide/LOTRO-TTS/releases",
                            "Open GitHub Releases"
                        );
                    }
                });
            }
            finally
            {
                isCheckingUpdates = false;
            }
        }
    }
}
