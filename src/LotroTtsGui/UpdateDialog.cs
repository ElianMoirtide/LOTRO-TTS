using System;
using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;

namespace LotroTtsGui
{
    public class UpdateDialog : Window
    {
        private readonly UpdateInfo updateInfo;
        private readonly IBrush bgDark = new SolidColorBrush(Color.FromRgb(20, 22, 28));
        private readonly IBrush bgCard = new SolidColorBrush(Color.FromRgb(30, 34, 43));
        private readonly IBrush bgLog = new SolidColorBrush(Color.FromRgb(14, 16, 20));
        private readonly IBrush borderBrush = new SolidColorBrush(Color.FromRgb(55, 60, 72));
        private readonly IBrush goldAccent = new SolidColorBrush(Color.FromRgb(212, 175, 55));
        private readonly IBrush textLight = new SolidColorBrush(Color.FromRgb(232, 234, 237));
        private readonly IBrush textMuted = new SolidColorBrush(Color.FromRgb(154, 160, 166));
        private readonly IBrush greenOk = new SolidColorBrush(Color.FromRgb(46, 160, 67));

        public UpdateDialog(UpdateInfo info)
        {
            this.updateInfo = info;

            Title = $"LOTRO-TTS Update — {info.TagName}";
            Width = 620;
            Height = 480;
            MinWidth = 500;
            MinHeight = 380;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            Background = bgDark;

            InitializeUi();
        }

        private void InitializeUi()
        {
            var mainGrid = new Grid
            {
                Margin = new Thickness(20),
                RowDefinitions = new RowDefinitions("Auto,Auto,*,Auto")
            };

            // 0. Title & Release Name
            var headerStack = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
            var lblTitle = new TextBlock
            {
                Text = "New Update Available!",
                FontSize = 18,
                FontWeight = FontWeight.Bold,
                Foreground = goldAccent
            };
            var lblRelease = new TextBlock
            {
                Text = $"{updateInfo.TagName}: {updateInfo.ReleaseName}",
                FontSize = 14,
                FontWeight = FontWeight.SemiBold,
                Foreground = textLight,
                Margin = new Thickness(0, 4, 0, 0)
            };
            headerStack.Children.Add(lblTitle);
            headerStack.Children.Add(lblRelease);
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

            // 3. Actions Row
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                Spacing = 10,
                Margin = new Thickness(0, 16, 0, 0)
            };

            var btnOpenBrowser = new Button
            {
                Content = "Open in Browser",
                Background = greenOk,
                Foreground = Brushes.White,
                FontWeight = FontWeight.SemiBold,
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

            var btnClose = new Button
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

            buttonPanel.Children.Add(btnOpenBrowser);
            buttonPanel.Children.Add(btnClose);
            Grid.SetRow(buttonPanel, 3);
            mainGrid.Children.Add(buttonPanel);

            Content = mainGrid;
        }
    }
}
