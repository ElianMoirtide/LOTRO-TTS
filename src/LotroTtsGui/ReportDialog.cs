using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;

namespace LotroTtsGui
{
    public sealed class VoiceReportContext
    {
        public string VoiceId { get; set; } = "";
        public string RefAudio { get; set; } = "";
        public string Category { get; set; } = "";
        public string TtsLang { get; set; } = "";
        public string RefLang { get; set; } = "";
        public bool NarratorMode { get; set; }
        public string NpcName { get; set; } = "";
        public string NpcId { get; set; } = "";
        public string DbRace { get; set; } = "";
        public string DbGender { get; set; } = "";
        public string QuestTitle { get; set; } = "";
        public string QuestId { get; set; } = "";
        public string ClientLang { get; set; } = "";
        public string WindowType { get; set; } = "";
        public DateTime CapturedAtUtc { get; set; } = DateTime.UtcNow;

        public bool HasVoiceData => !string.IsNullOrWhiteSpace(VoiceId) || !string.IsNullOrWhiteSpace(NpcName);

        public static bool TryParseJson(string json, out VoiceReportContext? ctx)
        {
            ctx = null;
            if (string.IsNullOrWhiteSpace(json)) return false;
            try
            {
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;
                if (root.ValueKind != JsonValueKind.Object) return false;

                var res = new VoiceReportContext
                {
                    VoiceId = ReadString(root, "voice_id"),
                    RefAudio = ReadString(root, "ref_audio"),
                    Category = ReadString(root, "category"),
                    TtsLang = ReadString(root, "tts_lang"),
                    RefLang = ReadString(root, "ref_lang"),
                    NarratorMode = root.TryGetProperty("narrator_mode", out var nm) && nm.ValueKind == JsonValueKind.True,
                    NpcName = ReadString(root, "npc_name"),
                    NpcId = ReadFlexibleId(root, "npc_id"),
                    DbRace = ReadString(root, "db_race"),
                    DbGender = ReadString(root, "db_gender"),
                    QuestTitle = ReadString(root, "quest_title"),
                    QuestId = ReadFlexibleId(root, "quest_id"),
                    ClientLang = ReadString(root, "client_lang"),
                    WindowType = ReadString(root, "window_type"),
                    CapturedAtUtc = DateTime.UtcNow,
                };
                ctx = res;
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static string ReadString(JsonElement obj, string prop)
        {
            if (obj.TryGetProperty(prop, out var el) && el.ValueKind == JsonValueKind.String)
                return el.GetString() ?? "";
            return "";
        }

        private static string ReadFlexibleId(JsonElement obj, string prop)
        {
            if (!obj.TryGetProperty(prop, out var el)) return "";
            return el.ValueKind switch
            {
                JsonValueKind.Number => el.GetRawText(),
                JsonValueKind.String => el.GetString() ?? "",
                _ => ""
            };
        }
    }

    public sealed class ReportHostMetadata
    {
        public string AppVersion { get; set; } = "";
        public string DbVersion { get; set; } = "unknown";
        public string OsInfo { get; set; } = "";
        public string ComputeMode { get; set; } = "auto";
        public string ClientLang { get; set; } = "de";
        public string TtsLang { get; set; } = "de";
        public bool NarratorMode { get; set; }
        public string ReportEndpointOverride { get; set; } = "";
        public string RecentLogExcerpt { get; set; } = "";

        public static string DetectOsSummary()
        {
            string plat = OperatingSystem.IsWindows() ? "Windows" : (OperatingSystem.IsLinux() ? "Linux" : RuntimeInformation.OSDescription);
            return $"{plat} ({RuntimeInformation.OSArchitecture})";
        }
    }

    public static class ReportRelayConfig
    {
        public const string GitHubRepo = "ElianMoirtide/LOTRO-TTS";

        /// <summary>
        /// Deploy tools/report-worker/ to Cloudflare Workers and paste its /report URL here
        /// (e.g. "https://lotro-tts-report-worker.&lt;subdomain&gt;.workers.dev/report").
        /// </summary>
        public const string DefaultReportEndpoint = "https://lotro-tts-report-worker.elian-moirtide.workers.dev/report";

        public static string ResolveEndpoint(string? configOverride)
        {
            string? envUrl = Environment.GetEnvironmentVariable("LOTRO_TTS_REPORT_URL");
            if (!string.IsNullOrWhiteSpace(envUrl)) return envUrl.Trim();
            if (!string.IsNullOrWhiteSpace(configOverride)) return configOverride.Trim();
            return DefaultReportEndpoint.Trim();
        }
    }

    public class ReportDialog : Window
    {
        private readonly VoiceReportContext voiceCtx;
        private readonly ReportHostMetadata hostMeta;
        private readonly string resolvedEndpoint;

        public string? SubmittedIssueUrl { get; private set; }
        public int? SubmittedIssueNumber { get; private set; }
        public bool SubmittedDeduplicated { get; private set; }

        private readonly IBrush bgDark = new SolidColorBrush(Color.FromRgb(20, 22, 28));
        private readonly IBrush bgCard = new SolidColorBrush(Color.FromRgb(30, 34, 43));
        private readonly IBrush bgInput = new SolidColorBrush(Color.FromRgb(16, 18, 23));
        private readonly IBrush borderBrush = new SolidColorBrush(Color.FromRgb(55, 60, 72));
        private readonly IBrush goldAccent = new SolidColorBrush(Color.FromRgb(212, 175, 55));
        private readonly IBrush textLight = new SolidColorBrush(Color.FromRgb(232, 234, 237));
        private readonly IBrush textMuted = new SolidColorBrush(Color.FromRgb(154, 160, 166));
        private readonly IBrush greenOk = new SolidColorBrush(Color.FromRgb(46, 160, 67));
        private readonly IBrush amberWarn = new SolidColorBrush(Color.FromRgb(210, 153, 34));
        private readonly IBrush redStop = new SolidColorBrush(Color.FromRgb(196, 43, 28));

        private ComboBox cmbCategory = null!;
        private StackPanel pnlVoiceFields = null!;
        private StackPanel pnlNpcCorrection = null!;
        private StackPanel pnlPronFields = null!;
        private StackPanel pnlBugFields = null!;

        private TextBox txtVoiceId = null!;
        private TextBox txtRefAudio = null!;
        private TextBox txtNpcName = null!;
        private TextBox txtNpcId = null!;
        private TextBlock lblCurrentDbMeta = null!;

        private ComboBox cmbExpectedRace = null!;
        private ComboBox cmbExpectedGender = null!;
        private TextBox txtPronWord = null!;
        private TextBox txtPronSuggestion = null!;
        private TextBox txtSummary = null!;
        private CheckBox chkIncludeLog = null!;
        private TextBox txtNotes = null!;

        private Border statusBanner = null!;
        private TextBlock lblStatus = null!;
        private Button btnOpenIssue = null!;
        private Button btnSubmit = null!;
        private Button btnOpenGitHub = null!;
        private Button btnCopy = null!;
        private Button btnClose = null!;

        public ReportDialog(VoiceReportContext? voiceContext, ReportHostMetadata hostMetadata)
        {
            this.voiceCtx = voiceContext ?? new VoiceReportContext();
            this.hostMeta = hostMetadata;
            this.resolvedEndpoint = ReportRelayConfig.ResolveEndpoint(hostMetadata.ReportEndpointOverride);

            Title = "LOTRO-TTS — Report Voice / Issue";
            Width = 620;
            MinWidth = 540;
            Height = 680;
            MinHeight = 560;
            MaxHeight = 820;
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

        private string SelectedReportType => cmbCategory.SelectedIndex switch
        {
            0 => "voice_quality",
            1 => "npc_metadata",
            2 => "pronunciation",
            _ => "general_bug"
        };

        private void InitializeUi()
        {
            var outerGrid = new Grid
            {
                Margin = new Thickness(20, 18, 20, 18),
                RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto")
            };

            // 0. Header
            var headerStack = new StackPanel { Margin = new Thickness(0, 0, 0, 10) };
            headerStack.Children.Add(new TextBlock
            {
                Text = "Report Voice, NPC Metadata, or Bug",
                FontSize = 18,
                FontWeight = FontWeight.Bold,
                Foreground = goldAccent
            });
            headerStack.Children.Add(new TextBlock
            {
                Text = "No GitHub account required when submitted directly via the report relay. Private player names and dialogue texts are never sent automatically.",
                FontSize = 12,
                Foreground = textMuted,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 4, 0, 0)
            });
            Grid.SetRow(headerStack, 0);
            outerGrid.Children.Add(headerStack);

            // 1. Scrollable Form Content
            var scroll = new ScrollViewer
            {
                VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled
            };
            var formStack = new StackPanel { Spacing = 10, Margin = new Thickness(0, 0, 4, 0) };

            // Report Category
            var catStack = new StackPanel { Spacing = 4 };
            catStack.Children.Add(CreateFieldLabel("Report Category"));
            cmbCategory = new ComboBox
            {
                ItemsSource = new[]
                {
                    "Poor Voice Quality (robotic, noise, cut-off, mismatch)",
                    "Wrong NPC Metadata (incorrect Race, Gender, or assigned Voice)",
                    "Pronunciation / Text Issue",
                    "General Bug / Other Problem"
                },
                SelectedIndex = voiceCtx.HasVoiceData ? 0 : 3,
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            cmbCategory.SelectionChanged += (s, e) => UpdateSectionVisibility();
            catStack.Children.Add(cmbCategory);
            formStack.Children.Add(catStack);

            // Captured Environment Summary Card
            string clientLangDisplay = !string.IsNullOrWhiteSpace(voiceCtx.ClientLang) ? voiceCtx.ClientLang.ToUpperInvariant() : hostMeta.ClientLang.ToUpperInvariant();
            string ttsLangDisplay = !string.IsNullOrWhiteSpace(voiceCtx.TtsLang) ? voiceCtx.TtsLang.ToUpperInvariant() : hostMeta.TtsLang.ToUpperInvariant();
            var envCard = new Border
            {
                Background = bgCard,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(5),
                Padding = new Thickness(12, 8)
            };
            var envStack = new StackPanel { Spacing = 3 };
            envStack.Children.Add(new TextBlock
            {
                Text = $"System Context: App {hostMeta.AppVersion} | DB: {hostMeta.DbVersion} | OS: {hostMeta.OsInfo}",
                FontSize = 11.5,
                Foreground = textLight,
                TextWrapping = TextWrapping.Wrap
            });
            envStack.Children.Add(new TextBlock
            {
                Text = $"Languages: Client {clientLangDisplay} -> TTS {ttsLangDisplay} | Compute: {hostMeta.ComputeMode.ToUpperInvariant()} | Narrator: {(voiceCtx.NarratorMode || hostMeta.NarratorMode ? "ON" : "OFF")}",
                FontSize = 11.5,
                Foreground = textMuted,
                TextWrapping = TextWrapping.Wrap
            });
            if (!string.IsNullOrWhiteSpace(voiceCtx.QuestTitle) || !string.IsNullOrWhiteSpace(voiceCtx.QuestId))
            {
                string qDisplay = string.IsNullOrWhiteSpace(voiceCtx.QuestId)
                    ? voiceCtx.QuestTitle
                    : $"{voiceCtx.QuestTitle} (ID: {voiceCtx.QuestId})";
                envStack.Children.Add(new TextBlock
                {
                    Text = $"Captured Quest: {qDisplay}",
                    FontSize = 11.5,
                    Foreground = goldAccent,
                    TextWrapping = TextWrapping.Wrap
                });
            }
            envCard.Child = envStack;
            formStack.Children.Add(envCard);

            // Voice & NPC Metadata Fields
            pnlVoiceFields = new StackPanel { Spacing = 8 };
            var voiceRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
            txtVoiceId = CreateInputBox(voiceCtx.VoiceId);
            txtRefAudio = CreateInputBox(voiceCtx.RefAudio);
            AddLabeledControl(voiceRow, 0, "Voice ID (auto-captured if spoken)", txtVoiceId);
            AddLabeledControl(voiceRow, 2, "Reference Audio File", txtRefAudio);
            pnlVoiceFields.Children.Add(voiceRow);

            var npcRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
            txtNpcName = CreateInputBox(voiceCtx.NpcName);
            txtNpcId = CreateInputBox(voiceCtx.NpcId);
            AddLabeledControl(npcRow, 0, "NPC Name", txtNpcName);
            AddLabeledControl(npcRow, 2, "NPC ID (optional)", txtNpcId);
            pnlVoiceFields.Children.Add(npcRow);

            string dbMetaDisplay = (!string.IsNullOrWhiteSpace(voiceCtx.DbRace) || !string.IsNullOrWhiteSpace(voiceCtx.DbGender) || !string.IsNullOrWhiteSpace(voiceCtx.Category))
                ? $"Assigned Category: {(string.IsNullOrWhiteSpace(voiceCtx.Category) ? "-" : voiceCtx.Category)} | DB Race / Gender: {(string.IsNullOrWhiteSpace(voiceCtx.DbRace) ? "-" : voiceCtx.DbRace)} / {(string.IsNullOrWhiteSpace(voiceCtx.DbGender) ? "-" : voiceCtx.DbGender)}"
                : "Assigned Category / DB Race: not captured in this session (speak a quest first or fill in manually).";
            lblCurrentDbMeta = new TextBlock
            {
                Text = dbMetaDisplay,
                FontSize = 11.5,
                Foreground = textMuted,
                TextWrapping = TextWrapping.Wrap
            };
            pnlVoiceFields.Children.Add(lblCurrentDbMeta);
            formStack.Children.Add(pnlVoiceFields);

            // NPC Correction Dropdowns
            pnlNpcCorrection = new StackPanel { Spacing = 6 };
            var fixRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
            cmbExpectedRace = new ComboBox
            {
                ItemsSource = new[] { "(Unspecified)", "Man", "Elf", "Dwarf", "Hobbit", "Orc", "Ent", "Dead", "Troll", "Narrator / Other" },
                SelectedIndex = 0,
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            cmbExpectedGender = new ComboBox
            {
                ItemsSource = new[] { "(Unspecified)", "Male", "Female", "Neutral" },
                SelectedIndex = 0,
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            AddLabeledControl(fixRow, 0, "Expected Race", cmbExpectedRace);
            AddLabeledControl(fixRow, 2, "Expected Gender", cmbExpectedGender);
            pnlNpcCorrection.Children.Add(fixRow);
            formStack.Children.Add(pnlNpcCorrection);

            // Pronunciation Fields
            pnlPronFields = new StackPanel { Spacing = 6 };
            var pronRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
            txtPronWord = CreateInputBox("");
            txtPronSuggestion = CreateInputBox("");
            AddLabeledControl(pronRow, 0, "Original Word / Name (e.g. Cirith Ungol)", txtPronWord);
            AddLabeledControl(pronRow, 2, "Spoken Spelling Suggestion", txtPronSuggestion);
            pnlPronFields.Children.Add(pronRow);
            formStack.Children.Add(pnlPronFields);

            // General Bug Fields
            pnlBugFields = new StackPanel { Spacing = 6 };
            txtSummary = CreateInputBox("");
            var summaryWrap = new StackPanel { Spacing = 4 };
            summaryWrap.Children.Add(CreateFieldLabel("Short Summary / Issue Title"));
            summaryWrap.Children.Add(txtSummary);
            pnlBugFields.Children.Add(summaryWrap);

            chkIncludeLog = new CheckBox
            {
                Content = "Attach recent console log (last 40 lines; home paths are replaced with <USER_HOME>)",
                IsChecked = !voiceCtx.HasVoiceData,
                Foreground = textLight,
                FontSize = 11.5
            };
            pnlBugFields.Children.Add(chkIncludeLog);
            formStack.Children.Add(pnlBugFields);

            // Free-text Description / Notes
            var notesStack = new StackPanel { Spacing = 4 };
            notesStack.Children.Add(CreateFieldLabel("Description / Details"));
            txtNotes = new TextBox
            {
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 105,
                Background = bgInput,
                Foreground = textLight,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                FontSize = 12,
                Padding = new Thickness(8, 6)
            };
            notesStack.Children.Add(txtNotes);
            formStack.Children.Add(notesStack);

            scroll.Content = formStack;
            Grid.SetRow(scroll, 1);
            outerGrid.Children.Add(scroll);

            // 2. Status Banner (feedback after submission / config notice)
            statusBanner = new Border
            {
                Background = bgCard,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(4),
                Padding = new Thickness(10, 8),
                Margin = new Thickness(0, 10, 0, 0),
                IsVisible = false
            };
            var statusRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            lblStatus = new TextBlock
            {
                FontSize = 12,
                Foreground = textLight,
                TextWrapping = TextWrapping.Wrap,
                VerticalAlignment = VerticalAlignment.Center
            };
            btnOpenIssue = new Button
            {
                Content = "Open Issue",
                Background = bgDark,
                Foreground = goldAccent,
                BorderBrush = goldAccent,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(10, 4),
                FontSize = 11.5,
                IsVisible = false,
                Cursor = new Cursor(StandardCursorType.Hand),
                Margin = new Thickness(10, 0, 0, 0)
            };
            btnOpenIssue.Click += (s, e) =>
            {
                if (!string.IsNullOrWhiteSpace(SubmittedIssueUrl))
                    OpenUrlInBrowser(SubmittedIssueUrl);
            };
            Grid.SetColumn(lblStatus, 0);
            Grid.SetColumn(btnOpenIssue, 1);
            statusRow.Children.Add(lblStatus);
            statusRow.Children.Add(btnOpenIssue);
            statusBanner.Child = statusRow;
            Grid.SetRow(statusBanner, 2);
            outerGrid.Children.Add(statusBanner);

            // 3. Action Buttons Row
            var footerGrid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"),
                Margin = new Thickness(0, 14, 0, 0)
            };

            var leftBtns = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            btnCopy = CreateSecondaryButton("Copy Markdown", async (s, e) => await CopyMarkdownAsync());
            btnOpenGitHub = CreateSecondaryButton("Open on GitHub", (s, e) => OpenGitHubPreFilledIssue());
            leftBtns.Children.Add(btnCopy);
            leftBtns.Children.Add(btnOpenGitHub);

            var rightBtns = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            btnSubmit = new Button
            {
                Content = "Submit Report",
                Background = goldAccent,
                Foreground = new SolidColorBrush(Color.FromRgb(20, 22, 28)),
                FontWeight = FontWeight.Bold,
                Padding = new Thickness(16, 6),
                Cursor = new Cursor(StandardCursorType.Hand),
                CornerRadius = new CornerRadius(4)
            };
            btnSubmit.Click += async (s, e) => await SubmitDirectReportAsync();
            btnClose = CreateSecondaryButton("Close", (s, e) => Close());
            rightBtns.Children.Add(btnSubmit);
            rightBtns.Children.Add(btnClose);

            Grid.SetColumn(leftBtns, 0);
            Grid.SetColumn(rightBtns, 2);
            footerGrid.Children.Add(leftBtns);
            footerGrid.Children.Add(rightBtns);
            Grid.SetRow(footerGrid, 3);
            outerGrid.Children.Add(footerGrid);

            Content = outerGrid;

            UpdateSectionVisibility();
            if (string.IsNullOrWhiteSpace(resolvedEndpoint))
            {
                ShowStatus(
                    "Direct relay URL is not configured in this build yet — click 'Open on GitHub' (with GitHub account) or 'Copy Markdown'. Developers can set LOTRO_TTS_REPORT_URL or DefaultReportEndpoint.",
                    amberWarn,
                    showIssueBtn: false
                );
            }
        }

        private TextBlock CreateFieldLabel(string text) => new TextBlock
        {
            Text = text,
            FontSize = 11.5,
            Foreground = textMuted
        };

        private TextBox CreateInputBox(string initialText) => new TextBox
        {
            Text = initialText,
            Background = bgInput,
            Foreground = textLight,
            BorderBrush = borderBrush,
            BorderThickness = new Thickness(1),
            FontSize = 12,
            Padding = new Thickness(8, 5)
        };

        private static void AddLabeledControl(Grid row, int col, string labelText, Control control)
        {
            var stack = new StackPanel { Spacing = 4 };
            stack.Children.Add(new TextBlock
            {
                Text = labelText,
                FontSize = 11.5,
                Foreground = new SolidColorBrush(Color.FromRgb(154, 160, 166))
            });
            stack.Children.Add(control);
            Grid.SetColumn(stack, col);
            row.Children.Add(stack);
        }

        private Button CreateSecondaryButton(string text, EventHandler<Avalonia.Interactivity.RoutedEventArgs> onClick)
        {
            var btn = new Button
            {
                Content = text,
                Background = bgCard,
                Foreground = textLight,
                BorderBrush = borderBrush,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(12, 6),
                Cursor = new Cursor(StandardCursorType.Hand),
                CornerRadius = new CornerRadius(4)
            };
            btn.Click += onClick;
            return btn;
        }

        private void UpdateSectionVisibility()
        {
            string rType = SelectedReportType;
            pnlVoiceFields.IsVisible = rType is "voice_quality" or "npc_metadata";
            pnlNpcCorrection.IsVisible = rType == "npc_metadata";
            pnlPronFields.IsVisible = rType == "pronunciation";
            pnlBugFields.IsVisible = rType is "general_bug" or "pronunciation";
            if (rType == "general_bug")
            {
                chkIncludeLog.IsVisible = true;
            }
            else
            {
                chkIncludeLog.IsVisible = false;
            }
        }

        private void ShowStatus(string message, IBrush color, bool showIssueBtn)
        {
            lblStatus.Text = message;
            lblStatus.Foreground = color;
            btnOpenIssue.IsVisible = showIssueBtn && !string.IsNullOrWhiteSpace(SubmittedIssueUrl);
            statusBanner.IsVisible = true;
        }

        private bool ValidateInput(out string errorMessage)
        {
            string rType = SelectedReportType;
            string notes = (txtNotes.Text ?? "").Trim();
            string summary = (txtSummary.Text ?? "").Trim();

            if (rType == "voice_quality" && string.IsNullOrWhiteSpace(txtVoiceId.Text) && string.IsNullOrWhiteSpace(notes))
            {
                errorMessage = "Please enter a Voice ID or describe the voice quality issue.";
                return false;
            }
            if (rType == "npc_metadata" && string.IsNullOrWhiteSpace(txtNpcName.Text) && string.IsNullOrWhiteSpace(txtNpcId.Text))
            {
                errorMessage = "Please enter the affected NPC Name or NPC ID.";
                return false;
            }
            if (rType == "general_bug" && string.IsNullOrWhiteSpace(summary) && string.IsNullOrWhiteSpace(notes))
            {
                errorMessage = "Please enter a short summary or description of the problem.";
                return false;
            }
            if (rType == "pronunciation" && string.IsNullOrWhiteSpace(txtPronWord.Text) && string.IsNullOrWhiteSpace(notes))
            {
                errorMessage = "Please enter the mispronounced word/name or describe the issue.";
                return false;
            }

            errorMessage = "";
            return true;
        }

        private string GetSanitizedLogExcerpt()
        {
            if (SelectedReportType != "general_bug" || chkIncludeLog.IsChecked != true)
                return "";
            if (string.IsNullOrWhiteSpace(hostMeta.RecentLogExcerpt))
                return "";

            string text = hostMeta.RecentLogExcerpt;
            try
            {
                string userHome = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                if (!string.IsNullOrWhiteSpace(userHome) && userHome.Length > 3)
                {
                    text = text.Replace(userHome, "<USER_HOME>", StringComparison.OrdinalIgnoreCase);
                }
                if (!string.IsNullOrWhiteSpace(Environment.UserName) && Environment.UserName.Length >= 3)
                {
                    text = text.Replace($"\\{Environment.UserName}\\", "\\<USER>\\", StringComparison.OrdinalIgnoreCase);
                    text = text.Replace($"/{Environment.UserName}/", "/<USER>/", StringComparison.Ordinal);
                }
            }
            catch { }

            if (text.Length > 3800)
                text = text.Substring(text.Length - 3800);
            return text;
        }

        private string SelectedExpectedRace =>
            cmbExpectedRace.SelectedIndex > 0 && cmbExpectedRace.SelectedItem is string s ? s : "";

        private string SelectedExpectedGender =>
            cmbExpectedGender.SelectedIndex > 0 && cmbExpectedGender.SelectedItem is string s ? s : "";

        private string BuildMarkdownPreview(out string title, out string labelsCsv)
        {
            string rType = SelectedReportType;
            string clientLang = !string.IsNullOrWhiteSpace(voiceCtx.ClientLang) ? voiceCtx.ClientLang : hostMeta.ClientLang;
            string ttsLang = !string.IsNullOrWhiteSpace(voiceCtx.TtsLang) ? voiceCtx.TtsLang : hostMeta.TtsLang;
            string vid = (txtVoiceId.Text ?? "").Trim();
            string refAudio = (txtRefAudio.Text ?? "").Trim();
            string npcName = (txtNpcName.Text ?? "").Trim();
            string npcId = (txtNpcId.Text ?? "").Trim();
            string summary = (txtSummary.Text ?? "").Trim();
            string notes = (txtNotes.Text ?? "").Trim();

            if (rType == "voice_quality")
            {
                title = $"[Voice Report] {ttsLang.ToLowerInvariant()}/{(string.IsNullOrWhiteSpace(vid) ? "unknown_voice" : vid)}";
                labelsCsv = "voice-report,user-report";
            }
            else if (rType == "npc_metadata")
            {
                string npcKey = !string.IsNullOrWhiteSpace(npcId) ? $"{(string.IsNullOrWhiteSpace(npcName) ? "NPC" : npcName)} [{npcId}]" : npcName;
                title = $"[NPC Report] {npcKey}";
                labelsCsv = "npc-metadata,user-report";
            }
            else if (rType == "pronunciation")
            {
                string w = (txtPronWord.Text ?? "").Trim();
                title = $"[Pronunciation] {ttsLang.ToLowerInvariant()}: {(string.IsNullOrWhiteSpace(w) ? (string.IsNullOrWhiteSpace(summary) ? "Dialogue Text" : summary) : w)}";
                labelsCsv = "pronunciation,user-report";
            }
            else
            {
                title = $"[Bug Report] {(string.IsNullOrWhiteSpace(summary) ? "User Issue" : summary)}";
                labelsCsv = "bug,user-report";
            }

            var sb = new StringBuilder();
            sb.AppendLine("### LOTRO-TTS Report");
            sb.AppendLine();
            sb.AppendLine("| Field | Value |");
            sb.AppendLine("| :--- | :--- |");
            sb.AppendLine($"| **Type** | `{rType}` |");
            sb.AppendLine($"| **App / DB** | `{hostMeta.AppVersion}` / `{hostMeta.DbVersion}` |");
            sb.AppendLine($"| **OS / Mode** | `{hostMeta.OsInfo}` / `{hostMeta.ComputeMode}` |");
            sb.AppendLine($"| **Languages** | Client: `{clientLang}` \\| TTS: `{ttsLang}` |");

            if (!string.IsNullOrWhiteSpace(vid) || !string.IsNullOrWhiteSpace(refAudio))
            {
                sb.AppendLine($"| **Voice ID** | `{vid}` (`{voiceCtx.Category}`) |");
                sb.AppendLine($"| **Reference Audio** | `{refAudio}` |");
            }
            if (!string.IsNullOrWhiteSpace(npcName) || !string.IsNullOrWhiteSpace(npcId))
            {
                sb.AppendLine($"| **NPC** | `{npcName}` (ID: `{npcId}`) |");
                sb.AppendLine($"| **DB Race / Gender** | `{voiceCtx.DbRace}` / `{voiceCtx.DbGender}` |");
            }
            if (rType == "npc_metadata" && (!string.IsNullOrWhiteSpace(SelectedExpectedRace) || !string.IsNullOrWhiteSpace(SelectedExpectedGender)))
            {
                sb.AppendLine($"| **Suggested Fix** | Race: `{SelectedExpectedRace}` \\| Gender: `{SelectedExpectedGender}` |");
            }
            if (rType == "pronunciation")
            {
                sb.AppendLine($"| **Word / Replacement** | `{(txtPronWord.Text ?? "").Trim()}` -> `{(txtPronSuggestion.Text ?? "").Trim()}` |");
            }
            if (!string.IsNullOrWhiteSpace(voiceCtx.QuestTitle) || !string.IsNullOrWhiteSpace(voiceCtx.QuestId))
            {
                sb.AppendLine($"| **Quest** | `{voiceCtx.QuestTitle}` (ID: `{voiceCtx.QuestId}`) |");
            }

            sb.AppendLine();
            sb.AppendLine("### Description");
            sb.AppendLine(string.IsNullOrWhiteSpace(notes) ? "_No additional notes._" : notes);

            string logExcerpt = GetSanitizedLogExcerpt();
            if (!string.IsNullOrWhiteSpace(logExcerpt))
            {
                sb.AppendLine();
                sb.AppendLine("```text");
                sb.AppendLine(logExcerpt);
                sb.AppendLine("```");
            }

            return sb.ToString();
        }

        private async Task SubmitDirectReportAsync()
        {
            if (string.IsNullOrWhiteSpace(resolvedEndpoint))
            {
                ShowStatus(
                    "Direct relay URL is not configured yet. Use 'Open on GitHub' or 'Copy Markdown' below.",
                    amberWarn,
                    showIssueBtn: false
                );
                return;
            }

            if (!ValidateInput(out string validationError))
            {
                ShowStatus(validationError, amberWarn, showIssueBtn: false);
                return;
            }

            btnSubmit.IsEnabled = false;
            btnOpenGitHub.IsEnabled = false;
            btnCopy.IsEnabled = false;
            btnClose.IsEnabled = false;
            ShowStatus("Sending report...", goldAccent, showIssueBtn: false);

            try
            {
                string clientLang = !string.IsNullOrWhiteSpace(voiceCtx.ClientLang) ? voiceCtx.ClientLang : hostMeta.ClientLang;
                string ttsLang = !string.IsNullOrWhiteSpace(voiceCtx.TtsLang) ? voiceCtx.TtsLang : hostMeta.TtsLang;

                var payload = new Dictionary<string, object?>
                {
                    ["report_type"] = SelectedReportType,
                    ["app_version"] = hostMeta.AppVersion,
                    ["db_version"] = hostMeta.DbVersion,
                    ["os_info"] = hostMeta.OsInfo,
                    ["compute_mode"] = hostMeta.ComputeMode,
                    ["client_lang"] = clientLang,
                    ["tts_lang"] = ttsLang,
                    ["narrator_mode"] = voiceCtx.NarratorMode || hostMeta.NarratorMode,
                    ["voice_id"] = (txtVoiceId.Text ?? "").Trim(),
                    ["ref_audio"] = (txtRefAudio.Text ?? "").Trim(),
                    ["category"] = voiceCtx.Category,
                    ["npc_name"] = (txtNpcName.Text ?? "").Trim(),
                    ["npc_id"] = (txtNpcId.Text ?? "").Trim(),
                    ["db_race"] = voiceCtx.DbRace,
                    ["db_gender"] = voiceCtx.DbGender,
                    ["quest_title"] = voiceCtx.QuestTitle,
                    ["quest_id"] = voiceCtx.QuestId,
                    ["expected_race"] = SelectedExpectedRace,
                    ["expected_gender"] = SelectedExpectedGender,
                    ["pron_word"] = (txtPronWord.Text ?? "").Trim(),
                    ["pron_suggestion"] = (txtPronSuggestion.Text ?? "").Trim(),
                    ["summary"] = (txtSummary.Text ?? "").Trim(),
                    ["notes"] = (txtNotes.Text ?? "").Trim(),
                    ["log_excerpt"] = GetSanitizedLogExcerpt(),
                };

                string json = JsonSerializer.Serialize(payload);
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
                client.DefaultRequestHeaders.Add("User-Agent", $"LOTRO-TTS-Reporter/{hostMeta.AppVersion}");

                using var content = new StringContent(json, Encoding.UTF8, "application/json");
                using var response = await client.PostAsync(resolvedEndpoint, content);
                string respText = await response.Content.ReadAsStringAsync();

                if (!response.IsSuccessStatusCode)
                {
                    string errDetail = respText;
                    try
                    {
                        using var edoc = JsonDocument.Parse(respText);
                        if (edoc.RootElement.TryGetProperty("error", out var ee) && ee.ValueKind == JsonValueKind.String)
                            errDetail = ee.GetString() ?? respText;
                    }
                    catch { }
                    ShowStatus($"Report relay error ({(int)response.StatusCode}): {errDetail}", redStop, showIssueBtn: false);
                    return;
                }

                using var doc = JsonDocument.Parse(respText);
                var root = doc.RootElement;
                SubmittedIssueNumber = root.TryGetProperty("issue_number", out var numEl) && numEl.TryGetInt32(out int num) ? num : null;
                SubmittedIssueUrl = root.TryGetProperty("issue_url", out var urlEl) && urlEl.ValueKind == JsonValueKind.String ? urlEl.GetString() : null;
                SubmittedDeduplicated = root.TryGetProperty("deduplicated", out var dedEl) && dedEl.ValueKind == JsonValueKind.True;

                string actionText = SubmittedDeduplicated
                    ? $"Added your report to existing GitHub Issue #{SubmittedIssueNumber}. Thank you!"
                    : $"Created GitHub Issue #{SubmittedIssueNumber}. Thank you for reporting!";
                ShowStatus(actionText, greenOk, showIssueBtn: true);
            }
            catch (Exception ex)
            {
                ShowStatus($"Could not reach report relay ({ex.Message}). You can use 'Open on GitHub' or 'Copy Markdown' instead.", redStop, showIssueBtn: false);
            }
            finally
            {
                btnSubmit.IsEnabled = true;
                btnOpenGitHub.IsEnabled = true;
                btnCopy.IsEnabled = true;
                btnClose.IsEnabled = true;
            }
        }

        private async Task CopyMarkdownAsync()
        {
            string body = BuildMarkdownPreview(out string title, out _);
            if (Clipboard != null)
            {
                var dt = new DataTransfer();
                dt.Add(DataTransferItem.CreateText($"# {title}\n\n{body}"));
                await Clipboard.SetDataAsync(dt);
                ShowStatus("Formatted report copied to clipboard.", greenOk, showIssueBtn: false);
            }
        }

        private void OpenGitHubPreFilledIssue()
        {
            if (!ValidateInput(out string validationError))
            {
                ShowStatus(validationError, amberWarn, showIssueBtn: false);
                return;
            }

            string body = BuildMarkdownPreview(out string title, out string labelsCsv);
            if (body.Length > 4500)
                body = body.Substring(0, 4500) + "\n\n...(truncated for URL limit)";

            string url = $"https://github.com/{ReportRelayConfig.GitHubRepo}/issues/new" +
                         $"?title={Uri.EscapeDataString(title)}" +
                         $"&labels={Uri.EscapeDataString(labelsCsv)}" +
                         $"&body={Uri.EscapeDataString(body)}";
            OpenUrlInBrowser(url);
            ShowStatus("Opened pre-filled GitHub issue page in your browser.", greenOk, showIssueBtn: false);
        }

        private static void OpenUrlInBrowser(string url)
        {
            try
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch { }
        }
    }
}
