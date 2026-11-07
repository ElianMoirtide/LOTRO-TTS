using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text.RegularExpressions;

namespace LotroTtsGui
{
    public static class ProcessVolumeManager
    {
        public static void SetProcessVolume(int pid, int volumePercent)
        {
            if (volumePercent < 0) volumePercent = 0;
            if (volumePercent > 100) volumePercent = 100;

            if (OperatingSystem.IsWindows())
            {
                ApplyWindowsProcessVolume(pid, volumePercent);
            }
            else if (OperatingSystem.IsLinux())
            {
                ApplyLinuxProcessVolume(pid, volumePercent);
            }
        }

        #region Linux PipeWire / PulseAudio (pactl)
        private static void ApplyLinuxProcessVolume(int pid, int volumePercent)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "pactl",
                    Arguments = "list sink-inputs",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                using var p = Process.Start(psi);
                if (p == null) return;
                string output = p.StandardOutput.ReadToEnd();
                p.WaitForExit(1000);

                var blocks = output.Split(new[] { "Sink Input #" }, StringSplitOptions.RemoveEmptyEntries);
                foreach (var block in blocks)
                {
                    var idMatch = Regex.Match(block, @"^(\d+)");
                    if (!idMatch.Success) continue;
                    string sinkId = idMatch.Groups[1].Value;

                    bool match = false;
                    var pidMatch = Regex.Match(block, @"application\.process\.id\s*=\s*""?(\d+)""?");
                    if (pidMatch.Success && pidMatch.Groups[1].Value == pid.ToString())
                    {
                        match = true;
                    }
                    else if (block.Contains("python", StringComparison.OrdinalIgnoreCase))
                    {
                        match = true;
                    }

                    if (match)
                    {
                        var setPsi = new ProcessStartInfo
                        {
                            FileName = "pactl",
                            Arguments = $"set-sink-input-volume {sinkId} {volumePercent}%",
                            UseShellExecute = false,
                            CreateNoWindow = true
                        };
                        using var setP = Process.Start(setPsi);
                        setP?.WaitForExit(1000);
                    }
                }
            }
            catch
            {
                // Ignore if pactl is not installed or daemon is unavailable
            }
        }
        #endregion

        #region Windows WASAPI Audio COM
        [SupportedOSPlatform("windows")]
        private static void ApplyWindowsProcessVolume(int targetPid, int volumePercent)
        {
            try
            {
                var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                if (enumerator.GetDefaultAudioEndpoint(0, 0, out IMMDevice speakers) != 0 || speakers == null)
                    return;

                Guid iidMgr2 = typeof(IAudioSessionManager2).GUID;
                if (speakers.Activate(ref iidMgr2, 1, IntPtr.Zero, out IntPtr ptr) != 0 || ptr == IntPtr.Zero)
                    return;

                var mgr = (IAudioSessionManager2)Marshal.GetObjectForIUnknown(ptr);
                if (mgr.GetSessionEnumerator(out IAudioSessionEnumerator sessionEnum) != 0 || sessionEnum == null)
                    return;

                sessionEnum.GetCount(out int count);
                float normVol = Math.Clamp(volumePercent / 100.0f, 0.0f, 1.0f);
                Guid emptyGuid = Guid.Empty;

                for (int i = 0; i < count; i++)
                {
                    if (sessionEnum.GetSession(i, out IAudioSessionControl ctl) == 0 && ctl != null)
                    {
                        if (ctl is IAudioSessionControl2 ctl2 && ctl is ISimpleAudioVolume vol)
                        {
                            ctl2.GetProcessId(out uint pid);
                            bool match = false;
                            if (targetPid > 0 && pid == (uint)targetPid)
                            {
                                match = true;
                            }
                            else if (pid > 0)
                            {
                                try
                                {
                                    string pName = Process.GetProcessById((int)pid).ProcessName.ToLowerInvariant();
                                    if (pName == "python" || pName == "pythonw")
                                        match = true;
                                }
                                catch { }
                            }

                            if (match)
                            {
                                vol.SetMasterVolume(normVol, ref emptyGuid);
                            }
                        }
                    }
                }
            }
            catch
            {
                // Audio endpoint or COM error
            }
        }

        [ComImport]
        [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
        private class MMDeviceEnumeratorComObject { }

        [ComImport]
        [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IMMDeviceEnumerator
        {
            [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
            [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
            [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice endpoint);
            [PreserveSig] int RegisterEndpointNotificationCallback(IntPtr client);
            [PreserveSig] int UnregisterEndpointNotificationCallback(IntPtr client);
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
        [Guid("E2F5EE11-2079-4C45-B17E-E4232D9C74E4")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IAudioSessionEnumerator
        {
            [PreserveSig] int GetCount(out int count);
            [PreserveSig] int GetSession(int index, out IAudioSessionControl session);
        }

        [ComImport]
        [Guid("F4B49C88-E98D-4585-8A26-3BEEC569EC52")]
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
        private interface IAudioSessionControl2
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
            [PreserveSig] int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
            [PreserveSig] int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
            [PreserveSig] int GetProcessId(out uint processId);
            [PreserveSig] int IsSystemSoundsSession();
            [PreserveSig] int SetDuckingPreference(bool optOut);
        }

        [ComImport]
        [Guid("87CE5498-68D6-44E5-AC21-AB2761805B31")]
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
