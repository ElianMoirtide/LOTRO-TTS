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
            var cardNvidia = CreateOptionCard(
                "NVIDIA GPU (CUDA 12.6) - Recommended",
                greenOk,
                "For GeForce RTX (2000 / 3000 / 4000 / 5000) and GTX 1600 Series.\nFastest synthesis speed with dedicated Tensor Cores and FP16 acceleration.",
                null,
                () => SelectAndClose("nvidia")
            );
            Grid.SetRow(cardNvidia, 1);
            mainGrid.Children.Add(cardNvidia);

            // 2. AMD Option
            var cardAmd = CreateOptionCard(
                "AMD GPU (ROCm 6.x / 10.x)",
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
