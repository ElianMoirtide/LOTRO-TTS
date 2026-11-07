using System;
using System.Net.Http;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

namespace LotroTtsGui
{
    public class UpdateInfo
    {
        public string TagName { get; set; } = "";
        public string ReleaseName { get; set; } = "";
        public string Body { get; set; } = "";
        public string PublishedAt { get; set; } = "";
        public string HtmlUrl { get; set; } = "";
        public string DownloadUrl { get; set; } = "";
        public string DownloadFileName { get; set; } = "";
        public bool IsDirectExe { get; set; }
        public bool IsNewer { get; set; }
    }

    public static class UpdateChecker
    {
        public static async Task<UpdateInfo?> CheckForUpdateAsync(string currentVersion)
        {
            try
            {
                using var client = new HttpClient();
                client.DefaultRequestHeaders.Add("User-Agent", "LOTRO-TTS-Avalonia");
                client.Timeout = TimeSpan.FromSeconds(8);

                string url = "https://api.github.com/repos/ElianMoirtide/LOTRO-TTS/releases/latest";
                string json = await client.GetStringAsync(url);

                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;

                string tagName = root.TryGetProperty("tag_name", out var tagElem) ? tagElem.GetString() ?? "" : "";
                string releaseName = root.TryGetProperty("name", out var nameElem) ? nameElem.GetString() ?? "" : "";
                string body = root.TryGetProperty("body", out var bodyElem) ? bodyElem.GetString() ?? "" : "";
                string publishedAt = root.TryGetProperty("published_at", out var pubElem) ? pubElem.GetString() ?? "" : "";
                string htmlUrl = root.TryGetProperty("html_url", out var htmlElem) ? htmlElem.GetString() ?? "" : "";
                string zipUrl = root.TryGetProperty("zipball_url", out var zipElem) ? zipElem.GetString() ?? "" : "";

                string downloadUrl = "";
                string downloadFileName = $"{tagName}.zip";
                bool isDirectExe = false;

                // Check for attached release assets first (.zip or .exe)
                if (root.TryGetProperty("assets", out var assetsElem) && assetsElem.ValueKind == JsonValueKind.Array)
                {
                    foreach (var asset in assetsElem.EnumerateArray())
                    {
                        string aName = asset.TryGetProperty("name", out var an) ? an.GetString() ?? "" : "";
                        string aUrl = asset.TryGetProperty("browser_download_url", out var au) ? au.GetString() ?? "" : "";
                        if (aName.EndsWith(".zip", StringComparison.OrdinalIgnoreCase) || aName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                        {
                            downloadUrl = aUrl;
                            downloadFileName = aName;
                            isDirectExe = aName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase);
                            break;
                        }
                    }
                }

                if (string.IsNullOrEmpty(downloadUrl))
                {
                    downloadUrl = zipUrl;
                }

                bool isNewer = CompareVersions(tagName, currentVersion) > 0;

                return new UpdateInfo
                {
                    TagName = tagName,
                    ReleaseName = string.IsNullOrEmpty(releaseName) ? tagName : releaseName,
                    Body = body,
                    PublishedAt = publishedAt,
                    HtmlUrl = htmlUrl,
                    DownloadUrl = downloadUrl,
                    DownloadFileName = downloadFileName,
                    IsDirectExe = isDirectExe,
                    IsNewer = isNewer
                };
            }
            catch
            {
                return null;
            }
        }

        public static int CompareVersions(string vA, string vB)
        {
            var pA = ParseVersion(vA);
            var pB = ParseVersion(vB);

            for (int i = 0; i < Math.Max(pA.Length, pB.Length); i++)
            {
                int a = i < pA.Length ? pA[i] : 0;
                int b = i < pB.Length ? pB[i] : 0;
                if (a != b) return a.CompareTo(b);
            }
            return 0;
        }

        private static int[] ParseVersion(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return new[] { 0 };
            var matches = Regex.Matches(raw, @"\d+");
            if (matches.Count == 0) return new[] { 0 };
            int[] result = new int[matches.Count];
            for (int i = 0; i < matches.Count; i++)
            {
                int.TryParse(matches[i].Value, out result[i]);
            }
            return result;
        }
    }
}
