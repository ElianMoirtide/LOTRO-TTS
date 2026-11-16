using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text.RegularExpressions;

namespace LotroTtsGui
{
    public static class ProcessVolumeManager
    {
        private static readonly HashSet<string> LotroProcessNames = new(StringComparer.OrdinalIgnoreCase)
        {
            "lotroclient64",
            "lotroclient",
            "lotroclient_awesomium"
        };

        private static readonly object duckLock = new();
        private static readonly Dictionary<string, float> savedWindowsLotroVolumes = new();
        private static readonly Dictionary<string, int> savedLinuxSinkVolumes = new();
        private static bool isLotroDucked = false;

        public static bool IsLotroDucked
        {
            get { lock (duckLock) return isLotroDucked; }
        }

        public static void SetProcessVolume(int pid, int volumePercent)
        {
            volumePercent = Math.Clamp(volumePercent, 0, 100);

            if (OperatingSystem.IsWindows())
            {
                ApplyWindowsProcessVolume(pid, volumePercent);
            }
            else if (OperatingSystem.IsLinux())
            {
                ApplyLinuxProcessVolume(pid, volumePercent);
            }
        }

        public static void ApplyLotroDuckVolume(int duckPercent)
        {
            duckPercent = Math.Clamp(duckPercent, 0, 100);
            lock (duckLock)
            {
                if (OperatingSystem.IsWindows())
                {
                    ApplyWindowsLotroDuck(duckPercent);
                }
                else if (OperatingSystem.IsLinux())
                {
                    ApplyLinuxLotroDuck(duckPercent);
                }
                isLotroDucked = true;
            }
        }

        public static void RestoreLotroDuckVolume()
        {
            lock (duckLock)
            {
                if (!isLotroDucked && savedWindowsLotroVolumes.Count == 0 && savedLinuxSinkVolumes.Count == 0)
                    return;

                if (OperatingSystem.IsWindows())
                {
                    RestoreWindowsLotroDuck();
                }
                else if (OperatingSystem.IsLinux())
                {
                    RestoreLinuxLotroDuck();
                }

                savedWindowsLotroVolumes.Clear();
                savedLinuxSinkVolumes.Clear();
                isLotroDucked = false;
            }
        }

        private static bool IsLotroProcessName(string? name)
        {
            if (string.IsNullOrWhiteSpace(name)) return false;
            string clean = name.Trim();
            if (clean.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                clean = clean[..^4];
            return LotroProcessNames.Contains(clean);
        }

        #region Linux PipeWire / PulseAudio (pactl) & Real-Time Software Scaling
        private static string? RunPactl(string arguments)
        {
            var psi = new ProcessStartInfo
            {
                FileName = "pactl",
                Arguments = arguments,
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var p = Process.Start(psi);
            if (p == null) return null;
            string output = p.StandardOutput.ReadToEnd();
            p.WaitForExit(500);
            return output;
        }

        private static HashSet<int> GetRunningLotroPids()
        {
            var pids = new HashSet<int>();
            try
            {
                foreach (var proc in Process.GetProcesses())
                {
                    try
                    {
                        if (IsLotroProcessName(proc.ProcessName))
                            pids.Add(proc.Id);
                    }
                    catch { }
                    finally
                    {
                        proc.Dispose();
                    }
                }
            }
            catch { }
            return pids;
        }

        private static void ApplyLinuxProcessVolume(int pid, int volumePercent)
        {
            // On Linux, audio streams are one-shot and transient. System sink-inputs
            // vanish as soon as playback stops.
            // 1. For persistent reliability: scripts/tts_speaker.py reads config.json
            //    and scales all audio buffers before playback.
            // 2. For live mid-sentence volume changes: if a stream is actively playing,
            //    we also adjust its current sink-input in real-time via pactl.
            try
            {
                string? output = RunPactl("list sink-inputs");
                if (string.IsNullOrEmpty(output)) return;

                var blocks = output.Split(new[] { "Sink Input #" }, StringSplitOptions.RemoveEmptyEntries);
                foreach (var block in blocks)
                {
                    var idMatch = Regex.Match(block, @"^(\d+)");
                    if (!idMatch.Success) continue;
                    string sinkId = idMatch.Groups[1].Value;

                    bool match = false;
                    var pidMatch = Regex.Match(block, @"application\.process\.id\s*=\s*""?(\d+)""?");
                    if (pidMatch.Success && pid > 0 && pidMatch.Groups[1].Value == pid.ToString())
                    {
                        match = true;
                    }
                    else if (block.Contains("python", StringComparison.OrdinalIgnoreCase) ||
                             block.Contains("LOTRO-TTS", StringComparison.OrdinalIgnoreCase) ||
                             block.Contains("pw-cat", StringComparison.OrdinalIgnoreCase) ||
                             block.Contains("paplay", StringComparison.OrdinalIgnoreCase))
                    {
                        match = true;
                    }

                    if (match)
                    {
                        RunPactl($"set-sink-input-volume {sinkId} {volumePercent}%");
                    }
                }
            }
            catch
            {
                // Ignore if pactl is not installed or daemon is unavailable
            }
        }

        private static void ApplyLinuxLotroDuck(int duckPercent)
        {
            try
            {
                string? output = RunPactl("list sink-inputs");
                if (string.IsNullOrEmpty(output)) return;

                var lotroPids = GetRunningLotroPids();
                var blocks = output.Split(new[] { "Sink Input #" }, StringSplitOptions.RemoveEmptyEntries);
                foreach (var block in blocks)
                {
                    var idMatch = Regex.Match(block, @"^(\d+)");
                    if (!idMatch.Success) continue;
                    string sinkId = idMatch.Groups[1].Value;

                    bool isLotro = block.Contains("lotroclient", StringComparison.OrdinalIgnoreCase);
                    if (!isLotro)
                    {
                        var pidMatch = Regex.Match(block, @"application\.process\.id\s*=\s*""?(\d+)""?");
                        if (pidMatch.Success && int.TryParse(pidMatch.Groups[1].Value, out int blockPid) && lotroPids.Contains(blockPid))
                            isLotro = true;
                    }
                    if (!isLotro) continue;

                    if (!savedLinuxSinkVolumes.TryGetValue(sinkId, out int origPct))
                    {
                        var volMatch = Regex.Match(block, @"Volume:.*?(\d+)%");
                        origPct = volMatch.Success && int.TryParse(volMatch.Groups[1].Value, out int parsed)
                            ? Math.Clamp(parsed, 0, 150)
                            : 100;
                        savedLinuxSinkVolumes[sinkId] = origPct;
                    }

                    int targetPct = Math.Clamp((int)Math.Round(origPct * (duckPercent / 100.0)), 0, 150);
                    RunPactl($"set-sink-input-volume {sinkId} {targetPct}%");
                }
            }
            catch { }
        }

        private static void RestoreLinuxLotroDuck()
        {
            try
            {
                foreach (var kv in savedLinuxSinkVolumes)
                {
                    RunPactl($"set-sink-input-volume {kv.Key} {kv.Value}%");
                }
            }
            catch { }
        }
        #endregion

        #region Windows WASAPI Audio COM
        [SupportedOSPlatform("windows")]
        private static void ForEachWindowsAudioSession(Action<string, uint, ISimpleAudioVolume> visitor)
        {
            try
            {
                var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                Guid iidMgr2 = typeof(IAudioSessionManager2).GUID;

                var devices = new List<IMMDevice>();
                if (enumerator.GetDefaultAudioEndpoint(0, 0, out IMMDevice defaultEndpoint) == 0 && defaultEndpoint != null)
                {
                    devices.Add(defaultEndpoint);
                }

                if (enumerator.EnumAudioEndpoints(0, 1, out IMMDeviceCollection collection) == 0 && collection != null)
                {
                    collection.GetCount(out int devCount);
                    for (int d = 0; d < devCount; d++)
                    {
                        if (collection.Item(d, out IMMDevice dev) == 0 && dev != null)
                        {
                            devices.Add(dev);
                        }
                    }
                }

                var seenKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var dev in devices)
                {
                    try
                    {
                        string devId = dev.GetId(out string rawId) == 0 && !string.IsNullOrEmpty(rawId)
                            ? rawId
                            : "default";
                        if (dev.Activate(ref iidMgr2, 1, IntPtr.Zero, out IntPtr ptr) != 0 || ptr == IntPtr.Zero)
                            continue;

                        try
                        {
                            var mgr = (IAudioSessionManager2)Marshal.GetObjectForIUnknown(ptr);
                            if (mgr.GetSessionEnumerator(out IAudioSessionEnumerator sessionEnum) != 0 || sessionEnum == null)
                                continue;

                            sessionEnum.GetCount(out int count);
                            for (int i = 0; i < count; i++)
                            {
                                if (sessionEnum.GetSession(i, out IAudioSessionControl ctl) == 0 && ctl != null)
                                {
                                    if (ctl is IAudioSessionControl2 ctl2 && ctl is ISimpleAudioVolume vol)
                                    {
                                        ctl2.GetProcessId(out uint pid);
                                        if (pid == 0) continue;

                                        string sessionKey = $"{pid}|{devId}";
                                        if (seenKeys.Add(sessionKey))
                                        {
                                            visitor(sessionKey, pid, vol);
                                        }
                                    }
                                }
                            }
                        }
                        finally
                        {
                            Marshal.Release(ptr);
                        }
                    }
                    catch
                    {
                        // Ignore individual endpoint failure
                    }
                }
            }
            catch
            {
                // Audio endpoint or COM error
            }
        }

        private static string? TryGetProcessName(uint pid)
        {
            try
            {
                using var p = Process.GetProcessById((int)pid);
                return p.ProcessName;
            }
            catch
            {
                return null;
            }
        }

        [SupportedOSPlatform("windows")]
        private static void ApplyWindowsProcessVolume(int targetPid, int volumePercent)
        {
            float normVol = Math.Clamp(volumePercent / 100.0f, 0.0f, 1.0f);
            Guid emptyGuid = Guid.Empty;
            var nameCache = new Dictionary<uint, bool>();

            ForEachWindowsAudioSession((sessionKey, pid, vol) =>
            {
                bool match = false;
                if (targetPid > 0 && pid == (uint)targetPid)
                {
                    match = true;
                }
                else
                {
                    if (!nameCache.TryGetValue(pid, out match))
                    {
                        string? pName = TryGetProcessName(pid);
                        match = string.Equals(pName, "python", StringComparison.OrdinalIgnoreCase) ||
                                string.Equals(pName, "pythonw", StringComparison.OrdinalIgnoreCase);
                        nameCache[pid] = match;
                    }
                }

                if (match && vol.GetMasterVolume(out float curVol) == 0 && Math.Abs(curVol - normVol) > 0.005f)
                {
                    vol.SetMasterVolume(normVol, ref emptyGuid);
                }
            });
        }

        [SupportedOSPlatform("windows")]
        private static void ApplyWindowsLotroDuck(int duckPercent)
        {
            float scale = Math.Clamp(duckPercent / 100.0f, 0.0f, 1.0f);
            Guid emptyGuid = Guid.Empty;
            var nameCache = new Dictionary<uint, bool>();

            ForEachWindowsAudioSession((sessionKey, pid, vol) =>
            {
                if (!nameCache.TryGetValue(pid, out bool isLotro))
                {
                    isLotro = IsLotroProcessName(TryGetProcessName(pid));
                    nameCache[pid] = isLotro;
                }
                if (!isLotro) return;

                if (vol.GetMasterVolume(out float curVol) != 0) return;
                if (!savedWindowsLotroVolumes.TryGetValue(sessionKey, out float origVol))
                {
                    origVol = curVol;
                    savedWindowsLotroVolumes[sessionKey] = origVol;
                }

                float targetVol = Math.Clamp(origVol * scale, 0.0f, 1.0f);
                if (Math.Abs(curVol - targetVol) > 0.005f)
                {
                    vol.SetMasterVolume(targetVol, ref emptyGuid);
                }
            });
        }

        [SupportedOSPlatform("windows")]
        private static void RestoreWindowsLotroDuck()
        {
            if (savedWindowsLotroVolumes.Count == 0) return;
            Guid emptyGuid = Guid.Empty;

            ForEachWindowsAudioSession((sessionKey, pid, vol) =>
            {
                if (savedWindowsLotroVolumes.TryGetValue(sessionKey, out float origVol))
                {
                    if (vol.GetMasterVolume(out float curVol) == 0 && Math.Abs(curVol - origVol) > 0.005f)
                    {
                        vol.SetMasterVolume(origVol, ref emptyGuid);
                    }
                }
            });
        }

        [ComImport]
        [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
        private class MMDeviceEnumeratorComObject { }

        [ComImport]
        [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IMMDeviceEnumerator
        {
            [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
            [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
            [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice endpoint);
            [PreserveSig] int RegisterEndpointNotificationCallback(IntPtr client);
            [PreserveSig] int UnregisterEndpointNotificationCallback(IntPtr client);
        }

        [ComImport]
        [Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IMMDeviceCollection
        {
            [PreserveSig] int GetCount(out int count);
            [PreserveSig] int Item(int index, out IMMDevice device);
        }

        [ComImport]
        [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IMMDevice
        {
            [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, out IntPtr interfacePointer);
            [PreserveSig] int OpenPropertyStore(int stgmAccess, out IntPtr properties);
            [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
            [PreserveSig] int GetState(out int state);
        }

        [ComImport]
        [Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioSessionManager2
        {
            [PreserveSig] int GetAudioSessionControl(ref Guid audioSessionGuid, int streamFlags, out IntPtr sessionControl);
            [PreserveSig] int GetSimpleAudioVolume(ref Guid audioSessionGuid, int streamFlags, out IntPtr audioVolume);
            [PreserveSig] int GetSessionEnumerator(out IAudioSessionEnumerator sessionEnum);
            [PreserveSig] int RegisterSessionNotification(IntPtr newSessionNotification);
            [PreserveSig] int UnregisterSessionNotification(IntPtr newSessionNotification);
            [PreserveSig] int RegisterDuckNotification(IntPtr sessionId, IntPtr duckNotification);
            [PreserveSig] int UnregisterDuckNotification(IntPtr duckNotification);
        }

        [ComImport]
        [Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioSessionEnumerator
        {
            [PreserveSig] int GetCount(out int count);
            [PreserveSig] int GetSession(int index, out IAudioSessionControl session);
        }

        [ComImport]
        [Guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioSessionControl
        {
            [PreserveSig] int GetState(out int state);
            [PreserveSig] int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string displayName);
            [PreserveSig] int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string displayName, ref Guid eventContext);
            [PreserveSig] int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string iconPath);
            [PreserveSig] int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string iconPath, ref Guid eventContext);
            [PreserveSig] int GetGroupingParam(out Guid groupingParam);
            [PreserveSig] int SetGroupingParam(ref Guid groupingParam, ref Guid eventContext);
            [PreserveSig] int RegisterAudioSessionNotification(IntPtr newNotifications);
            [PreserveSig] int UnregisterAudioSessionNotification(IntPtr newNotifications);
        }

        [ComImport]
        [Guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioSessionControl2 : IAudioSessionControl
        {
            [PreserveSig] new int GetState(out int state);
            [PreserveSig] new int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string displayName);
            [PreserveSig] new int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string displayName, ref Guid eventContext);
            [PreserveSig] new int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string iconPath);
            [PreserveSig] new int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string iconPath, ref Guid eventContext);
            [PreserveSig] new int GetGroupingParam(out Guid groupingParam);
            [PreserveSig] new int SetGroupingParam(ref Guid groupingParam, ref Guid eventContext);
            [PreserveSig] new int RegisterAudioSessionNotification(IntPtr newNotifications);
            [PreserveSig] new int UnregisterAudioSessionNotification(IntPtr newNotifications);
            [PreserveSig] int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
            [PreserveSig] int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
            [PreserveSig] int GetProcessId(out uint processId);
            [PreserveSig] int IsSystemSoundsSession();
            [PreserveSig] int SetDuckingPreference(bool optOut);
        }

        [ComImport]
        [Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface ISimpleAudioVolume
        {
            [PreserveSig] int SetMasterVolume(float level, ref Guid eventContext);
            [PreserveSig] int GetMasterVolume(out float level);
            [PreserveSig] int SetMute(bool mute, ref Guid eventContext);
            [PreserveSig] int GetMute(out bool mute);
        }
        #endregion
    }
}
