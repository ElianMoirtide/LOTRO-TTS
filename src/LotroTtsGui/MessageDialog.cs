using System;
using System.Diagnostics;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;

namespace LotroTtsGui
{
    public enum MessageDialogType
    {
        Information,
        Success,
        Warning,
        Error
    }

    public class MessageDialog : Window
    {
        private readonly IBrush bgDark = new SolidColorBrush(Color.FromRgb(20, 22, 28));
        private readonly IBrush bgCard = new SolidColorBrush(Color.FromRgb(30, 34, 43));
        private readonly IBrush borderBrush = new SolidColorBrush(Color.FromRgb(55, 60, 72));
        private readonly IBrush goldAccent = new SolidColorBrush(Color.FromRgb(212, 175, 55));
        private readonly IBrush textLight = new SolidColorBrush(Color.FromRgb(232, 234, 237));
        private readonly IBrush textMuted = new SolidColorBrush(Color.FromRgb(154, 160, 166));
        private readonly IBrush greenOk = new SolidColorBrush(Color.FromRgb(46, 160, 67));
        private readonly IBrush amberWarn = new SolidColorBrush(Color.FromRgb(210, 153, 34));
        private readonly IBrush redStop = new SolidColorBrush(Color.FromRgb(196, 43, 28));

        public MessageDialog(string title, string heading, string message, MessageDialogType type, string? linkUrl = null, string? linkButtonText = null)
        {
            Title = title;
            Width = 480;
            MinWidth = 420;
            MaxWidth = 560;
            SizeToContent = SizeToContent.Height;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            Background = bgDark;
            CanResize = false;

            try
            {
                using var iconStream = Avalonia.Platform.AssetLoader.Open(new Uri("avares://LOTRO-TTS/lotro_tts.ico"));
                Icon = new WindowIcon(iconStream);
            }
            catch { }

            InitializeUi(heading, message, type, linkUrl, linkButtonText);
        }

        private void InitializeUi(string heading, string message, MessageDialogType type, string? linkUrl, string? linkButtonText)
        {
            var root = new Grid
            {
                Margin = new Thickness(24, 20, 24, 20),
                RowDefinitions = new RowDefinitions("Auto,Auto,Auto")
            };

            IBrush accentColor = type switch
            {
                MessageDialogType.Success => greenOk,
                MessageDialogType.Warning => amberWarn,
                MessageDialogType.Error => redStop,
                _ => goldAccent
            };

            string iconSymbol = type switch
            {
                MessageDialogType.Success => "✓",
                MessageDialogType.Warning => "⚠",
                MessageDialogType.Error => "✕",
                _ => "ℹ"
            };

            // 0. Header (Icon + Heading)
            var headerStack = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 10,
                Margin = new Thickness(0, 0, 0, 12)
            };

            var lblIcon = new TextBlock
            {
                Text = iconSymbol,
                FontSize = 22,
                FontWeight = FontWeight.Bold,
                Foreground = accentColor,
                VerticalAlignment = VerticalAlignment.Center
            };
            var lblHeading = new TextBlock
            {
                Text = heading,
                FontSize = 17,
                FontWeight = FontWeight.Bold,
                Foreground = accentColor,
                VerticalAlignment = VerticalAlignment.Center
            };
            headerStack.Children.Add(lblIcon);
            headerStack.Children.Add(lblHeading);
            Grid.SetRow(headerStack, 0);
            root.Children.Add(headerStack);

            // 1. Message Body
            var lblMessage = new TextBlock
            {
                Text = message,
                FontSize = 13,
                Foreground = textLight,
                TextWrapping = TextWrapping.Wrap,
                LineHeight = 20,
                Margin = new Thickness(0, 0, 0, 20)
            };
            Grid.SetRow(lblMessage, 1);
            root.Children.Add(lblMessage);

            // 2. Buttons Row
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                Spacing = 10
            };

            if (!string.IsNullOrEmpty(linkUrl) && !string.IsNullOrEmpty(linkButtonText))
            {
                var btnLink = new Button
                {
                    Content = linkButtonText,
                    Background = bgCard,
                    Foreground = textLight,
                    BorderBrush = borderBrush,
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(14, 6),
                    Cursor = new Cursor(StandardCursorType.Hand)
                };
                btnLink.Click += (s, e) =>
                {
                    try
                    {
                        Process.Start(new ProcessStartInfo(linkUrl) { UseShellExecute = true });
                    }
                    catch { }
                };
                buttonPanel.Children.Add(btnLink);
            }

            var btnOk = new Button
            {
                Content = "OK",
                Background = accentColor,
                Foreground = Brushes.White,
                FontWeight = FontWeight.SemiBold,
                Padding = new Thickness(22, 6),
                Cursor = new Cursor(StandardCursorType.Hand)
            };
            btnOk.Click += (s, e) => Close();
            buttonPanel.Children.Add(btnOk);

            Grid.SetRow(buttonPanel, 2);
            root.Children.Add(buttonPanel);

            Content = root;
        }

        public static Task ShowAsync(Window owner, string title, string heading, string message, MessageDialogType type, string? linkUrl = null, string? linkButtonText = null)
        {
            var dlg = new MessageDialog(title, heading, message, type, linkUrl, linkButtonText);
            return dlg.ShowDialog(owner);
        }
    }
}
