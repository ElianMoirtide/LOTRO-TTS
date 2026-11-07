using System;
using System.Collections.Generic;
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
        public bool IsPrerelease { get; set; }
    }

    public class ParsedSemVer : IComparable<ParsedSemVer>
    {
        public int Major { get; set; }
        public int Minor { get; set; }
        public int Patch { get; set; }
        public string PreType { get; set; } = ""; // "alpha", "beta", "rc", or "" for stable
        public int PreNum { get; set; } = 0;

        public static ParsedSemVer Parse(string raw)
        {
            var res = new ParsedSemVer();
            if (string.IsNullOrWhiteSpace(raw)) return res;

            string clean = raw.Trim().TrimStart('v', 'V');
            string mainPart = clean;
            string prePart = "";
            int dashIdx = clean.IndexOf('-');
            if (dashIdx >= 0)
            {
                mainPart = clean.Substring(0, dashIdx);
                prePart = clean.Substring(dashIdx + 1).ToLowerInvariant();
            }

            var numbers = Regex.Matches(mainPart, @"\d+");
            if (numbers.Count > 0 && int.TryParse(numbers[0].Value, out int maj)) res.Major = maj;
            if (numbers.Count > 1 && int.TryParse(numbers[1].Value, out int min)) res.Minor = min;
            if (numbers.Count > 2 && int.TryParse(numbers[2].Value, out int pat)) res.Patch = pat;

            if (!string.IsNullOrEmpty(prePart))
            {
                if (prePart.Contains("alpha")) res.PreType = "alpha";
                else if (prePart.Contains("beta")) res.PreType = "beta";
                else if (prePart.Contains("rc")) res.PreType = "rc";
                else res.PreType = "pre";

                var preNums = Regex.Matches(prePart, @"\d+");
                if (preNums.Count > 0 && int.TryParse(preNums[0].Value, out int pNum))
                {
                    res.PreNum = pNum;
                }
            }

            return res;
        }

        public int CompareTo(ParsedSemVer? other)
        {
            if (other == null) return 1;
            if (Major != other.Major) return Major.CompareTo(other.Major);
            if (Minor != other.Minor) return Minor.CompareTo(other.Minor);
            if (Patch != other.Patch) return Patch.CompareTo(other.Patch);

            bool thisHasPre = !string.IsNullOrEmpty(PreType);
            bool otherHasPre = !string.IsNullOrEmpty(other.PreType);

            if (!thisHasPre && otherHasPre) return 1;  // Stable > Pre-release
            if (thisHasPre && !otherHasPre) return -1; // Pre-release < Stable
            if (!thisHasPre && !otherHasPre) return 0; // Both Stable

            int Rank(string type) => type switch
            {
                "alpha" => 1,
                "beta" => 2,
                "rc" => 3,
                _ => 0
            };

            int rankA = Rank(PreType);
            int rankB = Rank(other.PreType);
            if (rankA != rankB) return rankA.CompareTo(rankB);

            return PreNum.CompareTo(other.PreNum);
        }
    }

    public static class UpdateChecker
    {
        public static async Task<UpdateInfo?> CheckForUpdateAsync(string currentVersion, bool includePrereleases = false)
        {
            try
            {
                using var client = new HttpClient();
                client.DefaultRequestHeaders.Add("User-Agent", "LOTRO-TTS-Avalonia");
                client.Timeout = TimeSpan.FromSeconds(8);

                // Fetch recent releases list (up to 15) to check for stable or pre-releases
                string url = "https://api.github.com/repos/ElianMoirtide/LOTRO-TTS/releases?per_page=15";
                string json = await client.GetStringAsync(url);

                using var doc = JsonDocument.Parse(json);
                if (doc.RootElement.ValueKind != JsonValueKind.Array)
                {
                    return null;
                }

                JsonElement? bestElement = null;
                ParsedSemVer? bestVersion = null;

                foreach (var el in doc.RootElement.EnumerateArray())
                {
                    bool isDraft = el.TryGetProperty("draft", out var d) && d.GetBoolean();
                    if (isDraft) continue;

                    bool isPre = el.TryGetProperty("prerelease", out var p) && p.GetBoolean();
                    if (isPre && !includePrereleases) continue;

                    string tag = el.TryGetProperty("tag_name", out var t) ? t.GetString() ?? "" : "";
                    if (string.IsNullOrWhiteSpace(tag)) continue;

                    var parsed = ParsedSemVer.Parse(tag);
                    if (bestVersion == null || parsed.CompareTo(bestVersion) > 0)
                    {
                        bestVersion = parsed;
                        bestElement = el;
                    }
                }

                if (!bestElement.HasValue)
                {
                    return null;
                }

                var root = bestElement.Value;
                string tagName = root.TryGetProperty("tag_name", out var tagElem) ? tagElem.GetString() ?? "" : "";
                string releaseName = root.TryGetProperty("name", out var nameElem) ? nameElem.GetString() ?? "" : "";
                string body = root.TryGetProperty("body", out var bodyElem) ? bodyElem.GetString() ?? "" : "";
                string publishedAt = root.TryGetProperty("published_at", out var pubElem) ? pubElem.GetString() ?? "" : "";
                string htmlUrl = root.TryGetProperty("html_url", out var htmlElem) ? htmlElem.GetString() ?? "" : "";
                string zipUrl = root.TryGetProperty("zipball_url", out var zipElem) ? zipElem.GetString() ?? "" : "";
                bool isPrerelease = root.TryGetProperty("prerelease", out var preElem) && preElem.GetBoolean();

                string downloadUrl = "";
                string downloadFileName = $"{tagName}.zip";
                bool isDirectExe = false;

                // Check for attached release assets first (.zip or .exe) with OS-specific matching
                if (root.TryGetProperty("assets", out var assetsElem) && assetsElem.ValueKind == JsonValueKind.Array)
                {
                    string fallbackUrl = "";
                    string fallbackFileName = "";
                    bool fallbackDirectExe = false;
                    bool isWin = OperatingSystem.IsWindows();

                    foreach (var asset in assetsElem.EnumerateArray())
                    {
                        string aName = asset.TryGetProperty("name", out var an) ? an.GetString() ?? "" : "";
                        string aUrl = asset.TryGetProperty("browser_download_url", out var au) ? au.GetString() ?? "" : "";
                        if (string.IsNullOrEmpty(aUrl)) continue;

                        bool isZip = aName.EndsWith(".zip", StringComparison.OrdinalIgnoreCase);
                        bool isExe = aName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase);
                        if (!isZip && !isExe) continue;

                        string lower = aName.ToLowerInvariant();
                        bool isWinAsset = lower.Contains("win") || isExe;
                        bool isLinuxAsset = lower.Contains("linux") || lower.Contains("lin64");

                        // 1. Prioritize exact matching OS asset
                        if (isWin && isWinAsset)
                        {
                            downloadUrl = aUrl;
                            downloadFileName = aName;
                            isDirectExe = isExe;
                            break;
                        }
                        else if (!isWin && isLinuxAsset)
                        {
                            downloadUrl = aUrl;
                            downloadFileName = aName;
                            isDirectExe = false;
                            break;
                        }

                        // 2. Generic fallback if asset does not specify OS
                        if (string.IsNullOrEmpty(fallbackUrl) && !isWinAsset && !isLinuxAsset)
                        {
                            fallbackUrl = aUrl;
                            fallbackFileName = aName;
                            fallbackDirectExe = isExe;
                        }
                    }

                    if (string.IsNullOrEmpty(downloadUrl) && !string.IsNullOrEmpty(fallbackUrl))
                    {
                        downloadUrl = fallbackUrl;
                        downloadFileName = fallbackFileName;
                        isDirectExe = fallbackDirectExe;
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
                    IsNewer = isNewer,
                    IsPrerelease = isPrerelease
                };
            }
            catch
            {
                return null;
            }
        }

        public static int CompareVersions(string vA, string vB)
        {
            var semA = ParsedSemVer.Parse(vA);
            var semB = ParsedSemVer.Parse(vB);
            return semA.CompareTo(semB);
        }
    }
}
