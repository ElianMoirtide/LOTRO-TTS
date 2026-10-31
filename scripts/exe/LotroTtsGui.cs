using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("LOTRO-TTS")]
[assembly: AssemblyDescription("Local AI Text-to-Speech & Voice Cloning for The Lord of the Rings Online")]
[assembly: AssemblyCompany("LOTRO-TTS")]
[assembly: AssemblyProduct("LOTRO-TTS")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace LotroTtsLauncher
{
    public class MainForm : Form
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        private readonly string baseDir;
        private readonly string pythonExe;
        private readonly string configPath;

        // Status labels
        private Label lblEnvStatus;
        private Label lblDbStatus;
        private Label lblPluginStatus;

        // Controls
        private ComboBox cmbClientLang;
        private ComboBox cmbTtsLang;
        private ComboBox cmbComputeMode;
        private CheckBox chkMiddleMouse;
        private Button btnStartStop;
        private Button btnSetupAi;
        private Button btnRebuildDb;
        private Button btnUpdateSources;
        private Button btnInstallPlugin;
        private Button btnTestSpeech;
        private RichTextBox txtLog;

        private Process activeProcess = null;
        private bool isServiceRunning = false;
        private bool isTaskRunning = false;

        // Theme colors
        private readonly Color bgDark = Color.FromArgb(20, 22, 28);
        private readonly Color bgCard = Color.FromArgb(30, 34, 43);
        private readonly Color bgLog = Color.FromArgb(14, 16, 20);
        private readonly Color goldAccent = Color.FromArgb(212, 175, 55);
        private readonly Color textLight = Color.FromArgb(232, 234, 237);
        private readonly Color textMuted = Color.FromArgb(154, 160, 166);
        private readonly Color greenOk = Color.FromArgb(46, 160, 67);
        private readonly Color redStop = Color.FromArgb(196, 43, 28);
        private readonly Color amberWarn = Color.FromArgb(210, 153, 34);

        public MainForm()
        {
            baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
            pythonExe = Path.Combine(baseDir, "python", "win64", "python.exe");
            configPath = Path.Combine(baseDir, "config.json");

            InitializeUi();
            LoadConfig();
            RefreshSystemStatus();

            AppendLog("======================================================================", goldAccent);
            AppendLog("  LOTRO-TTS v1.0 — Local AI Voiceover System for Middle-earth", goldAccent);
            AppendLog("======================================================================", goldAccent);
            AppendLog("Ready. Click 'START LOTRO-TTS SERVICE' to launch.", textLight);
        }

        private Icon CreateRingIcon()
        {
            Bitmap bmp = new Bitmap(64, 64);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                using (SolidBrush bgBrush = new SolidBrush(Color.FromArgb(24, 26, 32)))
                {
                    g.FillEllipse(bgBrush, 2, 2, 60, 60);
                }
                using (Pen ringOuter = new Pen(Color.FromArgb(235, 190, 60), 7f))
                {
                    g.DrawEllipse(ringOuter, 12, 12, 40, 40);
                }
                using (Pen ringHighlight = new Pen(Color.FromArgb(255, 235, 140), 2f))
                {
                    g.DrawEllipse(ringHighlight, 14, 14, 36, 36);
                }
            }
            return Icon.FromHandle(bmp.GetHicon());
        }

        private void InitializeUi()
        {
            float dpi = 1.0f;
            using (Graphics g = this.CreateGraphics())
            {
                dpi = g.DpiX / 96.0f;
            }
            if (dpi < 1.0f) dpi = 1.0f;

            this.Text = "LOTRO-TTS";
            this.Size = new Size((int)(920 * dpi), (int)(680 * dpi));
            this.MinimumSize = new Size((int)(840 * dpi), (int)(580 * dpi));
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = bgDark;
            this.ForeColor = textLight;
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);
            try { this.Icon = CreateRingIcon(); } catch { }

            int pad = (int)(16 * dpi);
            TableLayoutPanel root = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                Padding = new Padding(pad, (int)(12 * dpi), pad, pad),
                ColumnCount = 1,
                RowCount = 5
            };
            root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, (int)(44 * dpi))); // 0: Header
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, (int)(74 * dpi))); // 1: Status Bar
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, (int)(118 * dpi))); // 2: Settings + Start
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, (int)(48 * dpi))); // 3: Tools Bar
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));             // 4: Live Log

            // 1. Header Panel (Logo + flush bottom-aligned v1.0)
            Panel headerPanel = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = bgDark,
                Margin = new Padding(0)
            };
            Label lblTitle = new Label
            {
                Text = "LOTRO-TTS",
                Font = new Font("Segoe UI", 18f, FontStyle.Bold),
                ForeColor = goldAccent,
                AutoSize = true,
                UseMnemonic = false,
                Location = new Point(0, 0)
            };
            Label lblVersion = new Label
            {
                Text = "v1.0",
                Font = new Font("Segoe UI", 8.5f, FontStyle.Regular),
                ForeColor = textMuted,
                AutoSize = true,
                UseMnemonic = false
            };
            headerPanel.Controls.Add(lblTitle);
            headerPanel.Controls.Add(lblVersion);

            // Position v1.0 flush with the bottom baseline of LOTRO-TTS
            EventHandler layoutHeader = (s, e) =>
            {
                lblVersion.Location = new Point(
                    lblTitle.Right - (int)(2 * dpi),
                    lblTitle.Bottom - lblVersion.Height - (int)(3 * dpi)
                );
            };
            headerPanel.Layout += new LayoutEventHandler((s, e) => layoutHeader(s, e));
            this.Shown += layoutHeader;
            root.Controls.Add(headerPanel, 0, 0);

            // 2. Status Cards Row
            TableLayoutPanel statusGrid = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 3,
                RowCount = 1,
                Margin = new Padding(0, 0, 0, (int)(8 * dpi))
            };
            statusGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33f));
            statusGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33f));
            statusGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.34f));
            statusGrid.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            lblEnvStatus = CreateStatusCard(statusGrid, 0, "AI Environment (python/win64)", dpi);
            lblDbStatus = CreateStatusCard(statusGrid, 1, "Quest Database (data/lotro.db)", dpi);
            lblPluginStatus = CreateStatusCard(statusGrid, 2, "LOTRO Lua Plugin (Plugins/TTS)", dpi);
            root.Controls.Add(statusGrid, 0, 1);

            // 3. Settings & Start Button Panel
            Panel configCard = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = bgCard,
                Padding = new Padding((int)(12 * dpi), (int)(8 * dpi), (int)(12 * dpi), (int)(8 * dpi)),
                Margin = new Padding(0, 0, 0, (int)(8 * dpi))
            };

            TableLayoutPanel configLayout = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 4,
                RowCount = 2
            };
            configLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 25f));
            configLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 28f));
            configLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 21f));
            configLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 26f));
            configLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 62f));
            configLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 38f));

            // Dropdown 1: Client Lang
            cmbClientLang = CreateLabeledDropdown(
                configLayout, 0,
                "Game Client Language (OCR):",
                new object[] {
                    "de — Deutsch (German)",
                    "en — English",
                    "fr — Français (French)"
                },
                dpi
            );
            cmbClientLang.SelectedIndexChanged += (s, e) => SaveConfig();

            // Dropdown 2: TTS Lang
            cmbTtsLang = CreateLabeledDropdown(
                configLayout, 1,
                "Spoken TTS Voice Language:",
                new object[] {
                    "de — Deutsch (Native Voices)",
                    "en — English (Native Voices)",
                    "fr — Français (Native Voices)",
                    "es — Español (Voice Cloning)",
                    "it — Italiano (AI Translation)"
                },
                dpi
            );
            cmbTtsLang.SelectedIndexChanged += (s, e) => SaveConfig();

            // Dropdown 3: Compute Mode
            cmbComputeMode = CreateLabeledDropdown(
                configLayout, 2,
                "Compute Mode:",
                new object[] {
                    "auto — Auto (GPU / CPU)",
                    "cuda — NVIDIA GPU",
                    "cpu — CPU Only"
                },
                dpi
            );

            // Main Start/Stop Button spanning 2 rows in col 3
            btnStartStop = new Button
            {
                Text = "▶  START LOTRO-TTS",
                Dock = DockStyle.Fill,
                BackColor = greenOk,
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
                Cursor = Cursors.Hand,
                UseMnemonic = false,
                Margin = new Padding((int)(6 * dpi), (int)(2 * dpi), 0, (int)(2 * dpi))
            };
            btnStartStop.FlatAppearance.BorderSize = 0;
            btnStartStop.Click += OnStartStopClicked;
            configLayout.Controls.Add(btnStartStop, 3, 0);
            configLayout.SetRowSpan(btnStartStop, 2);

            // Row 1: Middle Mouse Checkbox
            chkMiddleMouse = new CheckBox
            {
                Text = "Enable Middle Mouse Button (Mouse 3) as In-Game Trigger (in addition to the LOTRO Plugin button)",
                Checked = true,
                ForeColor = textLight,
                AutoSize = true,
                UseMnemonic = false,
                Dock = DockStyle.Fill,
                Margin = new Padding((int)(2 * dpi), (int)(4 * dpi), 0, 0)
            };
            configLayout.Controls.Add(chkMiddleMouse, 0, 1);
            configLayout.SetColumnSpan(chkMiddleMouse, 3);

            configCard.Controls.Add(configLayout);
            root.Controls.Add(configCard, 0, 2);

            // 4. Maintenance & Tools Bar
            TableLayoutPanel toolsBar = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 5,
                RowCount = 1,
                Margin = new Padding(0, 0, 0, (int)(8 * dpi))
            };
            for (int i = 0; i < 5; i++)
                toolsBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 20f));
            toolsBar.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

            btnSetupAi = CreateToolButton("⚙ Setup AI (GPU/CPU)", OnSetupAiClicked, 0, dpi);
            btnRebuildDb = CreateToolButton("🗄 Build Quest DB", OnRebuildDbClicked, 1, dpi);
            btnUpdateSources = CreateToolButton("🌐 Update XMLs & DB", OnUpdateSourcesClicked, 2, dpi);
            btnInstallPlugin = CreateToolButton("🧩 Install LOTRO Plugin", OnInstallPluginClicked, 3, dpi);
            btnTestSpeech = CreateToolButton("🔊 Test Voice Output", OnTestSpeechClicked, 4, dpi);

            toolsBar.Controls.Add(btnSetupAi, 0, 0);
            toolsBar.Controls.Add(btnRebuildDb, 1, 0);
            toolsBar.Controls.Add(btnUpdateSources, 2, 0);
            toolsBar.Controls.Add(btnInstallPlugin, 3, 0);
            toolsBar.Controls.Add(btnTestSpeech, 4, 0);
            root.Controls.Add(toolsBar, 0, 3);

            // 5. Live Output Console
            Panel logContainer = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = bgLog,
                Padding = new Padding((int)(8 * dpi))
            };
            txtLog = new RichTextBox
            {
                Dock = DockStyle.Fill,
                BackColor = bgLog,
                ForeColor = textLight,
                BorderStyle = BorderStyle.None,
                ReadOnly = true,
                Font = new Font("Consolas", 9.5f, FontStyle.Regular),
                ScrollBars = RichTextBoxScrollBars.Vertical
            };
            logContainer.Controls.Add(txtLog);
            root.Controls.Add(logContainer, 0, 4);

            this.Controls.Add(root);
            this.FormClosing += OnMainFormClosing;
        }

        private ComboBox CreateLabeledDropdown(TableLayoutPanel parent, int col, string labelText, object[] items, float dpi)
        {
            Panel cell = new Panel
            {
                Dock = DockStyle.Fill,
                Margin = new Padding(0, 0, (int)(10 * dpi), 0)
            };
            Label lbl = new Label
            {
                Text = labelText,
                ForeColor = textMuted,
                Font = new Font("Segoe UI", 8.75f, FontStyle.Regular),
                AutoSize = true,
                UseMnemonic = false,
                Location = new Point(0, 0)
            };
            ComboBox cmb = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                BackColor = bgDark,
                ForeColor = textLight,
                FlatStyle = FlatStyle.Flat,
                Location = new Point(0, (int)(22 * dpi)),
                Width = Math.Max(80, cell.ClientSize.Width),
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
            };
            cmb.Items.AddRange(items);
            cmb.SelectedIndex = 0;
            cell.Controls.Add(lbl);
            cell.Controls.Add(cmb);
            cell.Layout += (s, e) =>
            {
                cmb.Top = lbl.Bottom + (int)(3 * dpi);
                cmb.Width = Math.Max(60, cell.ClientSize.Width - 2);
            };
            parent.Controls.Add(cell, col, 0);
            return cmb;
        }

        private Label CreateStatusCard(TableLayoutPanel parent, int col, string title, float dpi)
        {
            int gap = (int)(4 * dpi);
            Panel card = new Panel
            {
                Dock = DockStyle.Fill,
                BackColor = bgCard,
                Margin = new Padding(col == 0 ? 0 : gap, 0, col == 2 ? 0 : gap, 0)
            };
            Label lblHeader = new Label
            {
                Text = title,
                ForeColor = textMuted,
                Font = new Font("Segoe UI", 8.5f, FontStyle.Regular),
                AutoSize = true,
                UseMnemonic = false,
                Location = new Point((int)(10 * dpi), (int)(7 * dpi))
            };
            Label lblValue = new Label
            {
                Text = "Checking...",
                ForeColor = textLight,
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                AutoSize = true,
                UseMnemonic = false,
                Location = new Point((int)(10 * dpi), (int)(29 * dpi))
            };
            card.Controls.Add(lblHeader);
            card.Controls.Add(lblValue);
            card.Layout += (s, e) =>
            {
                lblValue.Top = lblHeader.Bottom + (int)(3 * dpi);
            };
            parent.Controls.Add(card, col, 0);
            return lblValue;
        }

        private Button CreateToolButton(string text, EventHandler onClick, int col, float dpi)
        {
            int gap = (int)(3 * dpi);
            Button btn = new Button
            {
                Text = text,
                Dock = DockStyle.Fill,
                BackColor = bgCard,
                ForeColor = textLight,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Segoe UI", 8.75f, FontStyle.Regular),
                Cursor = Cursors.Hand,
                UseMnemonic = false,
                Margin = new Padding(col == 0 ? 0 : gap, 0, col == 4 ? 0 : gap, 0)
            };
            btn.FlatAppearance.BorderColor = Color.FromArgb(55, 60, 72);
            btn.FlatAppearance.BorderSize = 1;
            btn.Click += onClick;
            return btn;
        }

        private string GetSelectedCode(ComboBox cmb, string fallback)
        {
            if (cmb.SelectedItem == null) return fallback;
            string s = cmb.SelectedItem.ToString();
            int idx = s.IndexOf(' ');
            return idx > 0 ? s.Substring(0, idx).Trim() : fallback;
        }

        private void SelectByPrefix(ComboBox cmb, string code)
        {
            if (string.IsNullOrEmpty(code)) return;
            for (int i = 0; i < cmb.Items.Count; i++)
            {
                if (cmb.Items[i].ToString().StartsWith(code + " ", StringComparison.OrdinalIgnoreCase))
                {
                    cmb.SelectedIndex = i;
                    return;
                }
            }
        }

        private void LoadConfig()
        {
            try
            {
                if (File.Exists(configPath))
                {
                    string json = File.ReadAllText(configPath, Encoding.UTF8);
                    Match mGame = Regex.Match(json, "\"game_lang\"\\s*:\\s*\"([a-zA-Z]+)\"");
                    Match mTts = Regex.Match(json, "\"tts_lang\"\\s*:\\s*\"([a-zA-Z]+)\"");
                    if (mGame.Success) SelectByPrefix(cmbClientLang, mGame.Groups[1].Value.ToLowerInvariant());
                    if (mTts.Success) SelectByPrefix(cmbTtsLang, mTts.Groups[1].Value.ToLowerInvariant());
                }
            }
            catch { }
        }

        private void SaveConfig()
        {
            try
            {
                string gameLang = GetSelectedCode(cmbClientLang, "de");
                string ttsLang = GetSelectedCode(cmbTtsLang, "de");
                string json = "{\n  \"game_lang\": \"" + gameLang + "\",\n  \"tts_lang\": \"" + ttsLang + "\"\n}\n";
                File.WriteAllText(configPath, json, new UTF8Encoding(false));
            }
            catch { }
        }

        private string GetLotroDocumentsDir()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"))
                {
                    if (key != null)
                    {
                        object val = key.GetValue("Personal");
                        if (val != null)
                        {
                            string docs = Environment.ExpandEnvironmentVariables(val.ToString());
                            return Path.Combine(docs, "The Lord of the Rings Online");
                        }
                    }
                }
            }
            catch { }
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "The Lord of the Rings Online");
        }

        private bool IsAiEnvironmentReady()
        {
            string sitePackages = Path.Combine(baseDir, "python", "win64", "Lib", "site-packages");
            return File.Exists(pythonExe)
                && Directory.Exists(Path.Combine(sitePackages, "torch"))
                && Directory.Exists(Path.Combine(sitePackages, "omnivoice"));
        }

        private bool IsDatabaseReady()
        {
            string dbFile = Path.Combine(baseDir, "data", "lotro.db");
            if (!File.Exists(dbFile)) return false;
            FileInfo fi = new FileInfo(dbFile);
            return fi.Length > 5 * 1024 * 1024;
        }

        private bool IsPluginInstalled()
        {
            string lotroDocs = GetLotroDocumentsDir();
            string mainLua = Path.Combine(lotroDocs, "Plugins", "TTS", "Main.lua");
            return File.Exists(mainLua);
        }

        private void RefreshSystemStatus()
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action(RefreshSystemStatus));
                return;
            }

            if (IsAiEnvironmentReady())
            {
                string cudaDll = Path.Combine(baseDir, "python", "win64", "Lib", "site-packages", "torch", "lib", "torch_cuda.dll");
                lblEnvStatus.Text = File.Exists(cudaDll) ? "✓ Ready (CUDA GPU)" : "✓ Ready (CPU)";
                lblEnvStatus.ForeColor = greenOk;
            }
            else
            {
                lblEnvStatus.Text = "! Not Installed (Click Setup AI)";
                lblEnvStatus.ForeColor = amberWarn;
            }

            string dbFile = Path.Combine(baseDir, "data", "lotro.db");
            if (IsDatabaseReady())
            {
                long mb = new FileInfo(dbFile).Length / (1024 * 1024);
                lblDbStatus.Text = "✓ Ready (" + mb + " MB / 190 Voices)";
                lblDbStatus.ForeColor = greenOk;
            }
            else
            {
                lblDbStatus.Text = "! Missing (Auto-builds on Start)";
                lblDbStatus.ForeColor = amberWarn;
            }

            if (IsPluginInstalled())
            {
                lblPluginStatus.Text = "✓ Installed in LOTRO";
                lblPluginStatus.ForeColor = greenOk;
            }
            else
            {
                lblPluginStatus.Text = "! Not Installed (Click Install)";
                lblPluginStatus.ForeColor = amberWarn;
            }
        }

        private void AppendLog(string line, Color? color = null)
        {
            if (string.IsNullOrEmpty(line)) return;
            if (txtLog.InvokeRequired)
            {
                txtLog.BeginInvoke(new Action(() => AppendLog(line, color)));
                return;
            }
            txtLog.SelectionStart = txtLog.TextLength;
            txtLog.SelectionLength = 0;
            txtLog.SelectionColor = color ?? textLight;
            txtLog.AppendText(line + Environment.NewLine);
            txtLog.ScrollToCaret();
        }

        private void SetButtonsEnabled(bool enabled)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action(() => SetButtonsEnabled(enabled)));
                return;
            }
            btnSetupAi.Enabled = enabled;
            btnRebuildDb.Enabled = enabled;
            btnUpdateSources.Enabled = enabled;
            btnInstallPlugin.Enabled = enabled;
            btnTestSpeech.Enabled = enabled;
            cmbClientLang.Enabled = enabled;
            cmbTtsLang.Enabled = enabled;
            cmbComputeMode.Enabled = enabled;
            chkMiddleMouse.Enabled = enabled;
        }

        private void InstallLuaPluginSilent()
        {
            try
            {
                string srcDir = Path.Combine(baseDir, "src", "plugins", "TTS");
                if (!Directory.Exists(srcDir))
                {
                    AppendLog("[ERROR] Plugin source folder not found: " + srcDir, redStop);
                    return;
                }
                string lotroDocs = GetLotroDocumentsDir();
                string pluginsRoot = Path.Combine(lotroDocs, "Plugins");
                string targetTtsDir = Path.Combine(pluginsRoot, "TTS");
                Directory.CreateDirectory(targetTtsDir);

                foreach (string file in Directory.GetFiles(srcDir))
                {
                    string dest = Path.Combine(targetTtsDir, Path.GetFileName(file));
                    File.Copy(file, dest, true);
                }

                string pluginDescriptor = Path.Combine(srcDir, "TTS.plugin");
                if (File.Exists(pluginDescriptor))
                {
                    File.Copy(pluginDescriptor, Path.Combine(pluginsRoot, "TTS.plugin"), true);
                }

                AppendLog("[OK] LOTRO Lua Plugin installed to: " + targetTtsDir, greenOk);
                RefreshSystemStatus();
            }
            catch (Exception ex)
            {
                AppendLog("[ERROR] Could not install LOTRO Lua Plugin: " + ex.Message, redStop);
            }
        }

        private void OnStartStopClicked(object sender, EventArgs e)
        {
            if (isServiceRunning)
            {
                StopActiveProcess();
                return;
            }

            if (isTaskRunning)
            {
                MessageBox.Show("A maintenance task is currently running. Please wait for it to finish.", "LOTRO-TTS", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            if (!File.Exists(pythonExe))
            {
                MessageBox.Show("Embedded Python was not found at:\n" + pythonExe, "LOTRO-TTS Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            SaveConfig();

            // 1. Auto-install LOTRO Lua plugin if not yet installed
            if (!IsPluginInstalled())
            {
                InstallLuaPluginSilent();
            }

            // 2. Check if AI environment needs setup first
            if (!IsAiEnvironmentReady())
            {
                DialogResult dr = MessageBox.Show(
                    "The AI Voice Cloning environment (PyTorch & OmniVoice) is not installed yet.\n\n" +
                    "Click [Yes] to install for NVIDIA GPU (CUDA) — Recommended\n" +
                    "Click [No] to install for CPU Only\n" +
                    "Click [Cancel] to abort",
                    "LOTRO-TTS First-Time Setup",
                    MessageBoxButtons.YesNoCancel,
                    MessageBoxIcon.Question
                );
                if (dr == DialogResult.Cancel) return;
                string setupMode = (dr == DialogResult.Yes) ? "gpu" : "cpu";

                RunSequentialTasksAndStartService(setupMode, !IsDatabaseReady());
                return;
            }

            // 3. Check if lotro.db needs to be generated first
            if (!IsDatabaseReady())
            {
                RunSequentialTasksAndStartService(null, true);
                return;
            }

            StartTtsServiceProcess();
        }

        private void RunSequentialTasksAndStartService(string setupMode, bool buildDb)
        {
            isTaskRunning = true;
            SetButtonsEnabled(false);
            btnStartStop.Enabled = false;

            System.Threading.ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    if (!string.IsNullOrEmpty(setupMode))
                    {
                        AppendLog("\n>>> Running First-Time AI Environment Setup (" + setupMode.ToUpperInvariant() + ")...", goldAccent);
                        int code = RunPythonBlocking("-u \"scripts\\setup_tts.py\" --mode " + setupMode);
                        RefreshSystemStatus();
                        if (code != 0)
                        {
                            AppendLog("[ERROR] AI Environment Setup exited with code " + code, redStop);
                            return;
                        }
                    }

                    if (buildDb || !IsDatabaseReady())
                    {
                        AppendLog("\n>>> Building SQLite Quest Database (data/lotro.db)...", goldAccent);
                        int code = RunPythonBlocking("-u \"scripts\\generate_db.py\"");
                        RefreshSystemStatus();
                        if (code != 0)
                        {
                            AppendLog("[ERROR] Database generation exited with code " + code, redStop);
                            return;
                        }
                    }

                    this.BeginInvoke(new Action(() =>
                    {
                        isTaskRunning = false;
                        btnStartStop.Enabled = true;
                        StartTtsServiceProcess();
                    }));
                }
                finally
                {
                    this.BeginInvoke(new Action(() =>
                    {
                        isTaskRunning = false;
                        btnStartStop.Enabled = true;
                        if (!isServiceRunning) SetButtonsEnabled(true);
                    }));
                }
            });
        }

        private int RunPythonBlocking(string arguments)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
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

                using (Process p = new Process { StartInfo = psi })
                {
                    p.OutputDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                    p.ErrorDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                    p.Start();
                    p.BeginOutputReadLine();
                    p.BeginErrorReadLine();
                    p.WaitForExit();
                    return p.ExitCode;
                }
            }
            catch (Exception ex)
            {
                AppendLog("[ERROR] " + ex.Message, redStop);
                return -1;
            }
        }

        private void StartTtsServiceProcess()
        {
            string clientLang = GetSelectedCode(cmbClientLang, "de");
            string ttsLang = GetSelectedCode(cmbTtsLang, "de");
            string mode = GetSelectedCode(cmbComputeMode, "auto");
            bool useMouse = chkMiddleMouse.Checked;

            string args = string.Format(
                "-u \"scripts\\lotro_service.py\" --client-lang {0} --tts-lang {1} --mode {2}{3}",
                clientLang,
                ttsLang,
                mode,
                useMouse ? "" : " --no-mouse"
            );

            AppendLog("\n======================================================================", goldAccent);
            AppendLog(string.Format("Starting LOTRO-TTS Service [Client: {0} | TTS: {1} | Mode: {2}]...",
                clientLang.ToUpperInvariant(), ttsLang.ToUpperInvariant(), mode.ToUpperInvariant()), goldAccent);
            AppendLog("======================================================================", goldAccent);

            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
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

                activeProcess = new Process { StartInfo = psi, EnableRaisingEvents = true };
                activeProcess.OutputDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                activeProcess.ErrorDataReceived += (s, ev) => { if (ev.Data != null) AppendLog(ev.Data); };
                activeProcess.Exited += (s, ev) =>
                {
                    this.BeginInvoke(new Action(() =>
                    {
                        isServiceRunning = false;
                        btnStartStop.Text = "▶  START LOTRO-TTS";
                        btnStartStop.BackColor = greenOk;
                        SetButtonsEnabled(true);
                        AppendLog("[Service Stopped]", amberWarn);
                    }));
                };

                activeProcess.Start();
                activeProcess.BeginOutputReadLine();
                activeProcess.BeginErrorReadLine();

                isServiceRunning = true;
                btnStartStop.Text = "⏹  STOP LOTRO-TTS";
                btnStartStop.BackColor = redStop;
                SetButtonsEnabled(false);
            }
            catch (Exception ex)
            {
                AppendLog("[ERROR] Failed to start service: " + ex.Message, redStop);
            }
        }

        private void StopActiveProcess()
        {
            try
            {
                if (activeProcess != null && !activeProcess.HasExited)
                {
                    AppendLog("Stopping LOTRO-TTS Service...", amberWarn);
                    try
                    {
                        ProcessStartInfo killPsi = new ProcessStartInfo
                        {
                            FileName = "taskkill",
                            Arguments = "/PID " + activeProcess.Id + " /T /F",
                            CreateNoWindow = true,
                            UseShellExecute = false
                        };
                        using (Process kp = Process.Start(killPsi))
                        {
                            kp.WaitForExit(3000);
                        }
                    }
                    catch
                    {
                        activeProcess.Kill();
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
            btnStartStop.Enabled = false;

            AppendLog("\n>>> " + title + "...", goldAccent);
            System.Threading.ThreadPool.QueueUserWorkItem(_ =>
            {
                int code = RunPythonBlocking(pythonArgs);
                this.BeginInvoke(new Action(() =>
                {
                    if (code == 0)
                        AppendLog("[OK] " + title + " completed successfully!", greenOk);
                    else
                        AppendLog("[ERROR] " + title + " exited with code " + code, redStop);

                    RefreshSystemStatus();
                    isTaskRunning = false;
                    SetButtonsEnabled(true);
                    btnStartStop.Enabled = true;
                }));
            });
        }

        private void OnSetupAiClicked(object sender, EventArgs e)
        {
            if (isServiceRunning || isTaskRunning) return;
            DialogResult dr = MessageBox.Show(
                "Select compute mode for AI Voice Cloning setup:\n\n" +
                "[Yes] = GPU Mode (NVIDIA RTX / CUDA 12.6) — Recommended\n" +
                "[No] = CPU Mode (Fallback without NVIDIA GPU)\n" +
                "[Cancel] = Cancel",
                "Setup AI Environment",
                MessageBoxButtons.YesNoCancel,
                MessageBoxIcon.Question
            );
            if (dr == DialogResult.Cancel) return;
            string mode = (dr == DialogResult.Yes) ? "gpu" : "cpu";

            if (!IsPluginInstalled())
            {
                InstallLuaPluginSilent();
            }

            isTaskRunning = true;
            SetButtonsEnabled(false);
            btnStartStop.Enabled = false;

            AppendLog("\n>>> AI Environment Setup (" + mode.ToUpperInvariant() + ")...", goldAccent);
            System.Threading.ThreadPool.QueueUserWorkItem(_ =>
            {
                int code = RunPythonBlocking("-u \"scripts\\setup_tts.py\" --mode " + mode);
                if (code == 0 && !IsDatabaseReady())
                {
                    AppendLog("\n>>> Building SQLite Quest Database (data/lotro.db)...", goldAccent);
                    code = RunPythonBlocking("-u \"scripts\\generate_db.py\"");
                }
                this.BeginInvoke(new Action(() =>
                {
                    if (code == 0)
                        AppendLog("[OK] AI Environment & Database Setup completed successfully!", greenOk);
                    else
                        AppendLog("[ERROR] Setup exited with code " + code, redStop);

                    RefreshSystemStatus();
                    isTaskRunning = false;
                    SetButtonsEnabled(true);
                    btnStartStop.Enabled = true;
                }));
            });
        }

        private void OnRebuildDbClicked(object sender, EventArgs e)
        {
            RunBackgroundToolTask("Generating SQLite Quest Database (data/lotro.db)", "-u \"scripts\\generate_db.py\"");
        }

        private void OnUpdateSourcesClicked(object sender, EventArgs e)
        {
            RunBackgroundToolTask("Updating Quest & NPC XML Sources + Rebuilding DB", "-u \"scripts\\update_sources.py\" --generate-db");
        }

        private void OnInstallPluginClicked(object sender, EventArgs e)
        {
            InstallLuaPluginSilent();
        }

        private void OnTestSpeechClicked(object sender, EventArgs e)
        {
            string ttsLang = GetSelectedCode(cmbTtsLang, "de");
            string sampleText = "Die Welt ist im Wandel. Ich spüre es im Wasser, ich spüre es in der Erde.";
            if (ttsLang == "en") sampleText = "The world is changed. I feel it in the water, I feel it in the earth.";
            else if (ttsLang == "fr") sampleText = "Le monde a changé. Je le sens dans l'eau, je le sens dans la terre.";
            else if (ttsLang == "es") sampleText = "El mundo ha cambiado. Lo siento en el agua, lo siento en la tierra.";
            else if (ttsLang == "it") sampleText = "Il mondo è cambiato. Lo sento nell'acqua, lo sento nella terra.";

            string args = string.Format("-u \"scripts\\tts_speaker.py\" --npc \"Galadriel\" --lang {0} --text \"{1}\"", ttsLang, sampleText);
            RunBackgroundToolTask("Testing TTS Voice Output (Galadriel / " + ttsLang.ToUpperInvariant() + ")", args);
        }

        private void OnMainFormClosing(object sender, FormClosingEventArgs e)
        {
            StopActiveProcess();
        }

        [STAThread]
        public static void Main()
        {
            try { SetProcessDPIAware(); } catch { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }
}

