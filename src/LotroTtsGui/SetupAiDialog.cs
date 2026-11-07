using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;

namespace LotroTtsGui
{
    public class SetupAiDialog : Window
    {
        public string? SelectedMode { get; private set; }

        private readonly IBrush bgDark = new SolidColorBrush(Color.FromRgb(20, 22, 28));
        private readonly IBrush bgCard = new SolidColorBrush(Color.FromRgb(30, 34, 43));
        private readonly IBrush bgCardHover = new SolidColorBrush(Color.FromRgb(38, 43, 54));
        private readonly IBrush borderBrush = new SolidColorBrush(Color.FromRgb(55, 60, 72));
        private readonly IBrush goldAccent = new SolidColorBrush(Color.FromRgb(212, 175, 55));
        private readonly IBrush textLight = new SolidColorBrush(Color.FromRgb(232, 234, 237));
        private readonly IBrush textMuted = new SolidColorBrush(Color.FromRgb(154, 160, 166));
        private readonly IBrush amberWarn = new SolidColorBrush(Color.FromRgb(225, 165, 40));
        private readonly IBrush greenOk = new SolidColorBrush(Color.FromRgb(60, 180, 80));
        private readonly IBrush redAmd = new SolidColorBrush(Color.FromRgb(220, 75, 65));

        public SetupAiDialog()
        {
            Title = "LOTRO-TTS — Select AI Compute Hardware";
            Width = 680;
            Height = 540;
            MinWidth = 620;
            MinHeight = 500;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            Background = bgDark;
            CanResize = false;

            InitializeUi();
        }

        private void InitializeUi()
        {
            var gpu = DetectGpuHardware();

            var mainGrid = new Grid
            {
                Margin = new Thickness(20),
                RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto,*")
            };

            // 0. Header
            var headerStack = new StackPanel
            {
                Margin = new Thickness(0, 0, 0, 16)
            };
            var lblTitle = new TextBlock
            {
                Text = "Choose AI Acceleration Hardware",
                FontSize = 18,
                FontWeight = FontWeight.Bold,
                Foreground = goldAccent
            };
            var lblSubtitle = new TextBlock
            {
                Text = "Select the hardware backend matching your system's graphics card:",
                FontSize = 13,
                Foreground = textLight,
                Margin = new Thickness(0, 4, 0, 0)
            };
            headerStack.Children.Add(lblTitle);
            headerStack.Children.Add(lblSubtitle);
            Grid.SetRow(headerStack, 0);
            mainGrid.Children.Add(headerStack);

            // 1. NVIDIA Option
            string nvidiaTitle;
            string nvidiaDesc;
            string selectedNvidiaMode = "nvidia";

            if (gpu.isNvidia)
            {
                if (gpu.isBlackwell)
                {
                    nvidiaTitle = $"NVIDIA GPU (CUDA 13.0) — Detected: {gpu.name}";
                    nvidiaDesc = $"Blackwell architecture (sm_120) detected.\nAutomatically selects PyTorch CUDA 13.0 (cu130) build for native sm_120 hardware acceleration.";
                    selectedNvidiaMode = "cu130";
                }
                else
                {
                    nvidiaTitle = $"NVIDIA GPU (CUDA 12.6) — Detected: {gpu.name}";
                    nvidiaDesc = $"For GeForce RTX (2000 / 3000 / 4000) and GTX 1600 Series.\nFastest synthesis speed with dedicated Tensor Cores and FP16 acceleration.";
                    selectedNvidiaMode = "cu126";
                }
            }
            else
            {
                nvidiaTitle = "NVIDIA GPU (CUDA 12.6 / 13.0) — Auto-Detects Architecture";
                nvidiaDesc = "For GeForce RTX (2000 / 3000 / 4000 / 5000) and GTX 1600 Series.\nAutomatically detects Blackwell sm_120 (RTX 50xx) or earlier generation.";
            }

            var cardNvidia = CreateOptionCard(
                nvidiaTitle,
                greenOk,
                nvidiaDesc,
                null,
                () => SelectAndClose(selectedNvidiaMode)
            );
            Grid.SetRow(cardNvidia, 1);
            mainGrid.Children.Add(cardNvidia);

            // 2. AMD Option
            string amdTitle = gpu.isAmd
                ? $"AMD GPU (ROCm 6.x / 10.x) — Detected: {gpu.name}"
                : "AMD GPU (ROCm 6.x / 10.x)";

            var cardAmd = CreateOptionCard(
                amdTitle,
                redAmd,
                "For modern Radeon RX 7000 / 9000 Series (RDNA 3/4) & Ryzen 700M / 800M APUs (780M, 890M).",
                "Important: Older AMD GPUs (Radeon RX 5000 / 6000 Series) are not supported by Windows ROCm.\nPlease select 'CPU Mode' instead!",
                () => SelectAndClose("amd")
            );
            Grid.SetRow(cardAmd, 2);
            mainGrid.Children.Add(cardAmd);

            // 3. CPU Option
            var cardCpu = CreateOptionCard(
                "CPU Mode (Universal Compatibility)",
                Brushes.White,
                "Runs on any system (Intel Core, AMD Ryzen, older GPUs without ROCm).\nHighly optimized with multi-threading and AVX2/AVX-512 instructions.",
                null,
                () => SelectAndClose("cpu")
            );
            Grid.SetRow(cardCpu, 3);
            mainGrid.Children.Add(cardCpu);

            // 4. Cancel Button
            var btnCancel = new Button
            {
                Content = "Cancel",
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Bottom,
                Width = 110,
                Height = 34,
                Background = bgCard,
                Foreground = textMuted,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Cursor = new Cursor(StandardCursorType.Hand),
                Margin = new Thickness(0, 16, 0, 0)
            };
            btnCancel.Click += (s, e) => { SelectedMode = null; Close(); };
            Grid.SetRow(btnCancel, 4);
            mainGrid.Children.Add(btnCancel);

            Content = mainGrid;
        }

        private static (string name, double computeCap, bool isBlackwell, bool isNvidia, bool isAmd) DetectGpuHardware()
        {
            string gpuName = "";
            double computeCap = 0.0;
            bool isBlackwell = false;
            bool isNvidia = false;
            bool isAmd = false;

            // 1. Check nvidia-smi
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "nvidia-smi",
                    Arguments = "--query-gpu=name,compute_cap --format=csv,noheader",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                using var p = System.Diagnostics.Process.Start(psi);
                if (p != null)
                {
                    string output = p.StandardOutput.ReadToEnd().Trim();
                    p.WaitForExit(1000);
                    if (!string.IsNullOrEmpty(output))
                    {
                        var lines = output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                        if (lines.Length > 0)
                        {
                            var parts = lines[0].Split(',');
                            gpuName = parts[0].Trim();
                            isNvidia = true;
                            if (parts.Length > 1 && double.TryParse(parts[1].Trim(), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out double cap))
                            {
                                computeCap = cap;
                                isBlackwell = cap >= 12.0;
                            }
                            if (!isBlackwell && System.Text.RegularExpressions.Regex.IsMatch(gpuName, @"RTX\s*50\d\d", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                            {
                                isBlackwell = true;
                            }
                        }
                    }
                }
            }
            catch { }

            // 2. Fallback on Windows: PowerShell Get-CimInstance
            if (string.IsNullOrEmpty(gpuName) && OperatingSystem.IsWindows())
            {
                try
                {
                    var psi = new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = "powershell",
                        Arguments = "-NoProfile -Command \"Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }\"",
                        RedirectStandardOutput = true,
                        UseShellExecute = false,
                        CreateNoWindow = true
                    };
                    using var p = System.Diagnostics.Process.Start(psi);
                    if (p != null)
                    {
                        string output = p.StandardOutput.ReadToEnd();
                        p.WaitForExit(1500);
                        foreach (var raw in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                        {
                            string line = raw.Trim();
                            if (System.Text.RegularExpressions.Regex.IsMatch(line, @"NVIDIA|GeForce|RTX|GTX", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                            {
                                gpuName = line;
                                isNvidia = true;
                                if (System.Text.RegularExpressions.Regex.IsMatch(line, @"RTX\s*50\d\d", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                                {
                                    isBlackwell = true;
                                }
                                break;
                            }
                            else if (System.Text.RegularExpressions.Regex.IsMatch(line, @"Radeon|AMD", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                            {
                                gpuName = line;
                                isAmd = true;
                                break;
                            }
                        }
                    }
                }
                catch { }
            }

            return (gpuName, computeCap, isBlackwell, isNvidia, isAmd);
        }

        private Border CreateOptionCard(string title, IBrush titleColor, string description, string? warningNote, Action onClick)
        {
            var border = new Border
            {
                Background = bgCard,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(14, 10, 14, 10),
                Margin = new Thickness(0, 4, 0, 6),
                Cursor = new Cursor(StandardCursorType.Hand)
            };

            var stack = new StackPanel();

            var lblTitle = new TextBlock
            {
                Text = title,
                FontSize = 14,
                FontWeight = FontWeight.Bold,
                Foreground = titleColor
            };
            stack.Children.Add(lblTitle);

            var lblDesc = new TextBlock
            {
                Text = description,
                FontSize = 12,
                Foreground = textLight,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 4, 0, 0)
            };
            stack.Children.Add(lblDesc);

            if (!string.IsNullOrEmpty(warningNote))
            {
                var lblWarn = new TextBlock
                {
                    Text = warningNote,
                    FontSize = 11.5,
                    FontStyle = FontStyle.Italic,
                    Foreground = amberWarn,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 4, 0, 0)
                };
                stack.Children.Add(lblWarn);
            }

            border.Child = stack;

            border.PointerEntered += (s, e) => border.Background = bgCardHover;
            border.PointerExited += (s, e) => border.Background = bgCard;
            border.PointerPressed += (s, e) => onClick();

            return border;
        }

        private void SelectAndClose(string mode)
        {
            SelectedMode = mode;
            Close();
        }
    }
}
