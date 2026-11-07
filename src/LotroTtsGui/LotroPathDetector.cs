using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace LotroTtsGui
{
    public static class LotroPathDetector
    {
        public static string GetPythonExecutable(string baseDir)
        {
            if (OperatingSystem.IsWindows())
            {
                return Path.Combine(baseDir, "python", "win64", "python.exe");
            }
            else
            {
                string linPy = Path.Combine(baseDir, "python", "linux64", "bin", "python3");
                if (File.Exists(linPy)) return linPy;
                return "python3";
            }
        }

        public static string GetLotroDocumentsDir()
        {
            if (OperatingSystem.IsWindows())
            {
                return GetWindowsLotroDocumentsDir();
            }
            else
            {
                return GetLinuxLotroDocumentsDir();
            }
        }

        #region Windows Registry Path Resolution
        [SupportedOSPlatform("windows")]
        private static string GetWindowsLotroDocumentsDir()
        {
            try
            {
                using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders");
                if (key != null)
                {
                    object? val = key.GetValue("Personal");
                    if (val != null)
                    {
                        string docs = Environment.ExpandEnvironmentVariables(val.ToString() ?? "");
                        if (!string.IsNullOrEmpty(docs))
                        {
                            return Path.Combine(docs, "The Lord of the Rings Online");
                        }
                    }
                }
            }
            catch { }

            string myDocs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            return Path.Combine(myDocs, "The Lord of the Rings Online");
        }
        #endregion

        #region Linux Proton / Wine / Native Path Resolution
        private static string GetLinuxLotroDocumentsDir()
        {
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            if (string.IsNullOrEmpty(home)) home = Environment.GetEnvironmentVariable("HOME") ?? "/root";

            // 1. Steam Proton (AppID 212500)
            string[] protonRoots = new[]
            {
                Path.Combine(home, ".steam", "steam", "steamapps", "compatdata", "212500", "pfx", "drive_c", "users"),
                Path.Combine(home, ".local", "share", "Steam", "steamapps", "compatdata", "212500", "pfx", "drive_c", "users"),
                Path.Combine(home, ".var", "app", "com.valvesoftware.Steam", ".steam", "steam", "steamapps", "compatdata", "212500", "pfx", "drive_c", "users"),
                Path.Combine(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam", "steamapps", "compatdata", "212500", "pfx", "drive_c", "users")
            };

            foreach (var usersDir in protonRoots)
            {
                if (Directory.Exists(usersDir))
                {
                    try
                    {
                        foreach (var sub in Directory.GetDirectories(usersDir))
                        {
                            string candidate = Path.Combine(sub, "Documents", "The Lord of the Rings Online");
                            if (Directory.Exists(candidate)) return candidate;
                        }
                        // Default steamuser if folder doesn't exist yet
                        return Path.Combine(usersDir, "steamuser", "Documents", "The Lord of the Rings Online");
                    }
                    catch { }
                }
            }

            // 2. Lutris prefixes
            string lutrisPath = Path.Combine(home, "Games", "the-lord-of-the-rings-online", "drive_c", "users", Environment.UserName, "Documents", "The Lord of the Rings Online");
            if (Directory.Exists(lutrisPath)) return lutrisPath;

            // 3. Bottles / default wine prefix
            string wineDefault = Path.Combine(home, ".wine", "drive_c", "users", Environment.UserName, "Documents", "The Lord of the Rings Online");
            if (Directory.Exists(wineDefault)) return wineDefault;

            // 4. Standard Linux Documents
            string linuxDocs = Path.Combine(home, "Documents", "The Lord of the Rings Online");
            return linuxDocs;
        }
        #endregion
    }
}
