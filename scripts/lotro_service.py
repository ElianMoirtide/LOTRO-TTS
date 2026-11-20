#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Main Pipeline Service
1. Tails 'The Lord of the Rings Online/Script.log' for triggers: TTS|<CLIENT_LANG>|<TARGET>
2. Listens for global middle mouse button click (Mouse 3) as alternative trigger
3. Captures LOTRO process DWM surface directly via Win32 PrintWindow (PW_RENDERFULLCONTENT) with mss fallback
4. Extracts dialogue via RapidOCR & queries lotro.db for full un-truncated text
5. Resolves voice profile from lotro.db for the target NPC
6. Speaks the dialogue text using LotroSpeaker (with optional cross-language DB lookup or MarianMT translation)
"""

import os
import sys
import json
import time
import queue
import argparse
import logging
import threading
import warnings
from pathlib import Path
from typing import Optional, Dict, Any

# Suppress noisy HuggingFace Hub unauthenticated warnings and verbose HTTP logs
os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*")
warnings.filterwarnings("ignore", module="huggingface_hub.*")

# Enable Per-Monitor v2 DPI Awareness on Windows so GetWindowRect / PrintWindow / mss
# always operate at native physical resolution (e.g. 3840x2160 on 150% scaled 4K displays).
if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# Add scripts directory to path
base_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(base_dir / "scripts"))

from screen_reader import LotroScreenReader, PlayerInfo
from tts_speaker import LotroSpeaker
from translator import LotroTranslator

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LOTRO-TTS-Service")

# Suppress noisy HTTP, connection-pool, and HuggingFace background download logs
for noisy in (
    "httpx",
    "httpcore",
    "httpcore2",
    "httpx2",
    "urllib3",
    "requests",
    "huggingface_hub",
    "transformers",
):
    logging.getLogger(noisy).setLevel(logging.ERROR)


LOTRO_CLIENT_BINARIES = ("lotroclient64.exe", "lotroclient.exe", "lotroclient_awesomium.exe")

_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_TOKEN_QUERY = 0x0008
_WIN_TOKEN_ELEVATION = 20
_WIN_TOKEN_INTEGRITY_LEVEL = 25
_WIN_TOKEN_UIACCESS = 26
_WIN_SECURITY_MANDATORY_HIGH_RID = 0x3000
_WIN_ERROR_ACCESS_DENIED = 5
_WIN32_API_LOCK = threading.Lock()
_WIN32_SECURITY_APIS = None


def _get_win32_security_apis():
    """Lazily initializes Win32 DLL bindings with explicit argtypes/restypes for elevation checks."""
    global _WIN32_SECURITY_APIS
    with _WIN32_API_LOCK:
        if _WIN32_SECURITY_APIS is not None:
            return _WIN32_SECURITY_APIS

        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.OpenProcessToken.restype = wintypes.BOOL
        adv.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        adv.GetTokenInformation.restype = wintypes.BOOL
        adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.GetForegroundWindow.argtypes = []
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD

        _WIN32_SECURITY_APIS = (k32, adv, u32)
        return _WIN32_SECURITY_APIS


def _read_token_privileges_win32(apis, h_token) -> tuple[bool, Optional[int], bool]:
    """Reads (is_elevated, integrity_rid, has_ui_access) from an open Win32 access token."""
    import ctypes
    from ctypes import wintypes

    _, adv, _ = apis
    ret_len = wintypes.DWORD(0)

    elev = wintypes.DWORD(0)
    is_elevated = bool(
        adv.GetTokenInformation(
            h_token, _WIN_TOKEN_ELEVATION, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(ret_len)
        )
        and elev.value != 0
    )

    ui_access = wintypes.DWORD(0)
    has_ui_access = bool(
        adv.GetTokenInformation(
            h_token, _WIN_TOKEN_UIACCESS, ctypes.byref(ui_access), ctypes.sizeof(ui_access), ctypes.byref(ret_len)
        )
        and ui_access.value != 0
    )

    integrity_rid: Optional[int] = None
    ret_len.value = 0
    adv.GetTokenInformation(h_token, _WIN_TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(ret_len))
    if ret_len.value > 0:
        buf = ctypes.create_string_buffer(ret_len.value)
        if adv.GetTokenInformation(h_token, _WIN_TOKEN_INTEGRITY_LEVEL, buf, ret_len.value, ctypes.byref(ret_len)):
            psid = ctypes.c_void_p.from_buffer(buf).value
            if psid:
                count_ptr = adv.GetSidSubAuthorityCount(psid)
                if count_ptr and count_ptr[0] > 0:
                    rid_ptr = adv.GetSidSubAuthority(psid, count_ptr[0] - 1)
                    if rid_ptr:
                        integrity_rid = int(rid_ptr[0])

    return is_elevated, integrity_rid, has_ui_access


def _get_own_token_privileges_win32() -> Optional[tuple[bool, Optional[int], bool]]:
    """Returns (is_elevated, integrity_rid, has_ui_access) for the current process on Windows."""
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    try:
        apis = _get_win32_security_apis()
        k32, adv, _ = apis
        h_tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), _WIN_TOKEN_QUERY, ctypes.byref(h_tok)):
            return None
        try:
            return _read_token_privileges_win32(apis, h_tok)
        finally:
            k32.CloseHandle(h_tok)
    except Exception:
        return None


def _lookup_lotro_proc_name_psutil(pid: int) -> Optional[str]:
    """Finds executable name for pid via process snapshot if it belongs to a LOTRO client."""
    try:
        import psutil

        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info.get("pid") == pid:
                name = (proc.info.get("name") or "").lower()
                return name if name in LOTRO_CLIENT_BINARIES else None
    except Exception:
        pass
    return None


def _inspect_target_pid_elevation_win32(
    pid: int,
    own_privs: tuple[bool, Optional[int], bool],
    known_lotro_name: Optional[str] = None,
) -> tuple[Optional[str], Optional[bool]]:
    """
    Checks whether a target Windows PID is a LOTRO client process running at higher
    integrity / elevation than the current process (which causes Windows UIPI hook blocks).

    Returns (proc_name, is_mismatched) where is_mismatched is True/False, or None if transient.
    """
    own_elevated, own_integrity, own_ui_access = own_privs
    if own_ui_access or (own_elevated and (own_integrity is None or own_integrity >= _WIN_SECURITY_MANDATORY_HIGH_RID)):
        return known_lotro_name, False

    import ctypes
    from ctypes import wintypes

    apis = _get_win32_security_apis()
    k32, adv, _ = apis

    h_proc = k32.OpenProcess(_WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h_proc:
        err = ctypes.get_last_error()
        if err == _WIN_ERROR_ACCESS_DENIED:
            matched_name = known_lotro_name or _lookup_lotro_proc_name_psutil(pid)
            if matched_name:
                return matched_name, True
            return None, False
        return known_lotro_name, None

    try:
        proc_name = known_lotro_name
        if proc_name is None:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not k32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                err = ctypes.get_last_error()
                if err == _WIN_ERROR_ACCESS_DENIED:
                    matched_name = _lookup_lotro_proc_name_psutil(pid)
                    return (matched_name, True) if matched_name else (None, False)
                return None, None
            proc_name = os.path.basename(buf.value).lower()
            if proc_name not in LOTRO_CLIENT_BINARIES:
                return proc_name, False

        h_tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(h_proc, _WIN_TOKEN_QUERY, ctypes.byref(h_tok)):
            err = ctypes.get_last_error()
            if err == _WIN_ERROR_ACCESS_DENIED:
                # Medium-integrity processes receive ERROR_ACCESS_DENIED when opening
                # an elevated (High-integrity) process token with TOKEN_QUERY.
                return proc_name, True
            return proc_name, None

        try:
            target_elevated, target_integrity, _ = _read_token_privileges_win32(apis, h_tok)
        finally:
            k32.CloseHandle(h_tok)

        if target_integrity is not None and own_integrity is not None and target_integrity > own_integrity:
            return proc_name, True
        if target_elevated and not own_elevated:
            return proc_name, True
        return proc_name, False
    finally:
        k32.CloseHandle(h_proc)


_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "alt": "alt",
    "lalt": "alt",
    "ralt": "alt",
    "altgr": "alt",
    "shift": "shift",
    "lshift": "shift",
    "rshift": "shift",
}


def _parse_hotkey_spec(spec: str) -> tuple[frozenset[str], str]:
    """Parses a hotkey string such as 'pause', 'scroll_lock', or 'alt+r' into (modifiers, main_key)."""
    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    if not parts or parts in (["none"], ["off"], ["disabled"]):
        return frozenset(), ""
    mods = set()
    main_key = ""
    for part in parts:
        if part in _MODIFIER_ALIASES and len(parts) > 1:
            mods.add(_MODIFIER_ALIASES[part])
        else:
            main_key = part
    return frozenset(mods), main_key


def _get_modifier_name(key, keyboard_mod) -> Optional[str]:
    for attr in ("ctrl", "ctrl_l", "ctrl_r"):
        if key == getattr(keyboard_mod.Key, attr, None):
            return "ctrl"
    for attr in ("alt", "alt_l", "alt_r", "alt_gr"):
        if key == getattr(keyboard_mod.Key, attr, None):
            return "alt"
    for attr in ("shift", "shift_l", "shift_r"):
        if key == getattr(keyboard_mod.Key, attr, None):
            return "shift"
    k_name = (getattr(key, "name", None) or "").lower()
    if k_name in _MODIFIER_ALIASES:
        return _MODIFIER_ALIASES[k_name]
    return None


def _key_matches_spec(key, pressed_mods: frozenset[str], req_mods: frozenset[str], target_key: str, keyboard_mod) -> bool:
    if not target_key or not req_mods.issubset(pressed_mods):
        return False
    k_name = (getattr(key, "name", None) or "").lower()
    k_char = (getattr(key, "char", None) or "").lower()
    k_vk = getattr(key, "vk", None)

    if target_key in ("pause", "break", "pause_break"):
        return (
            k_name in ("pause", "pause_break", "media_play_pause")
            or key == getattr(keyboard_mod.Key, "pause", None)
            or k_vk in (19, 0x13, 3, 0x03)
        )
    if target_key in ("scroll_lock", "scrolllock", "rollen"):
        return (
            k_name in ("scroll_lock", "scrolllock")
            or key == getattr(keyboard_mod.Key, "scroll_lock", None)
            or k_vk in (145, 0x91)
        )
    if target_key == "end":
        return (
            k_name == "end"
            or key == getattr(keyboard_mod.Key, "end", None)
            or k_vk in (35, 0x23)
        )
    if target_key in ("esc", "escape"):
        return (
            k_name in ("esc", "escape")
            or key == getattr(keyboard_mod.Key, "esc", None)
            or k_vk in (27, 0x1B)
        )
    if k_name and k_name == target_key:
        return True
    if k_char and k_char == target_key:
        return True
    if len(target_key) == 1 and isinstance(k_vk, int) and (48 <= k_vk <= 57 or 65 <= k_vk <= 90):
        return chr(k_vk).lower() == target_key
    return False


class LotroPipelineService:
    def __init__(
        self,
        lotro_docs_dir: Path,
        data_dir: Path,
        voices_dir: Path,
        mode: str = "auto",
        enable_mouse: bool = True,
        game_lang: str = "en",
        tts_lang: str = "en",
        stop_hotkey: str = "pause",
        narrator_mode: bool = False,
        narrator_voice: str = "man_male_1",
        volume: int = 80,
        speed: int = 100,
        queue_mode: bool = False,
        replay_hotkey: str = "scroll_lock",
        skip_hotkey: str = "end",
        emit_duck_events: bool = False,
        gui_ipc: bool = False,
    ):
        self.lotro_docs_dir = Path(lotro_docs_dir)
        self.script_log_path = self.lotro_docs_dir / "Script.log"
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "lotro.db"
        self.voices_dir = Path(voices_dir)
        self.enable_mouse = enable_mouse
        self.game_lang = game_lang.lower().strip()
        self.tts_lang = tts_lang.lower().strip()
        self.stop_hotkey = (stop_hotkey or "pause").lower().strip()
        self.narrator_mode = bool(narrator_mode)
        self.narrator_voice = str(narrator_voice).strip() if narrator_voice else "man_male_1"
        self.volume = max(0, min(100, int(volume)))
        self.speed = max(50, min(200, int(speed)))
        self.queue_mode = bool(queue_mode)
        self.replay_hotkey = (replay_hotkey or "").lower().strip()
        self.skip_hotkey = (skip_hotkey or "").lower().strip()
        self.emit_duck_events = bool(emit_duck_events)
        self.gui_ipc = bool(gui_ipc)

        # Auto-detect CUDA/ROCm GPU (activating Low-End GPU mode <= 6.5 GB VRAM) and verify kernel execution
        from tts_speaker import resolve_compute_profile
        device, low_vram, profile_desc = resolve_compute_profile(mode)
        use_gpu_ocr = (device == "cuda") and (not low_vram)

        logger.info(f"Compute Profile: {profile_desc}")
        try:
            from generate_db import check_database_status
            db_status = check_database_status(self.db_path, base_dir=base_dir)
            db_ver_label = db_status.get("built_app_version") or "unknown"
            if db_status.get("status") == "ready":
                logger.info(
                    f"Quest DB verified: {db_ver_label} (Schema v{db_status.get('schema_version')}, {db_status.get('size_mb')} MB)"
                )
            elif db_status.get("exists"):
                logger.warning(
                    f"Quest DB notice: {db_status.get('reason')} (Built: {db_ver_label}) -> Rebuild via 'Build Quest DB' / generate_db.py."
                )
        except Exception as e:
            logger.debug(f"Database metadata check skipped: {e}")

        logger.info(f"Connecting to Database & Pre-warming OCR ({'CUDA' if use_gpu_ocr else 'CPU'}): {self.db_path}")
        self.screen_reader = LotroScreenReader(str(self.db_path), eager_init=True, use_gpu_ocr=use_gpu_ocr)

        mode_label = f"{device.upper()} / LOW-END GPU" if low_vram else device.upper()
        logger.info(f"Initializing TTS Speaker on device [{mode_label}] (Voices: {self.voices_dir})")
        self.speaker = LotroSpeaker(
            str(self.voices_dir),
            str(self.db_path),
            device=mode,
            narrator_mode=self.narrator_mode,
            narrator_voice=self.narrator_voice,
            volume=self.volume,
            speed=self.speed,
            active_lang=self.tts_lang,
            low_vram=low_vram,
            emit_duck_events=self.emit_duck_events,
            emit_voice_meta=self.gui_ipc,
        )
        self.translator = LotroTranslator(device="cpu" if low_vram else device)
        if self.tts_lang in ("it", "nl"):
            self.translator.preload(self.tts_lang, src_lang=self.game_lang)

        self.last_log_pos = 0
        self.log_identity = None
        self.player_info = PlayerInfo()
        try:
            with self.script_log_path.open("rb") as log:
                stat = os.fstat(log.fileno())
                self.log_identity = (stat.st_dev, stat.st_ino)
                for raw_line in log:
                    if not raw_line.endswith(b"\n"):
                        break
                    self.last_log_pos += len(raw_line)
                    self._consume_player_info(raw_line.decode("utf-8", errors="replace").strip())
        except FileNotFoundError:
            pass

        self.last_detected_client_lang = self.game_lang.upper()
        self.last_detected_target = ""
        self._is_scanning = False
        self._is_speaking = False
        self._trigger_gen = 0
        self._queue_epoch = 0
        self._worker_item_seq = 0
        self._current_worker_item_id: Optional[int] = None
        self._skipped_worker_item_id: Optional[int] = None
        self._lock = threading.Lock()
        self._capture_lock = threading.RLock()
        self._ocr_lock = threading.Lock()
        self._last_trigger_ts = 0.0
        self._dialogue_queue: queue.Queue = queue.Queue(maxsize=10)
        self._last_dialogue: Optional[tuple[str, str, str]] = None
        self._dialogue_meta_by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        cfg_file = base_dir / "config.json"
        try:
            self._live_cfg_mtime = cfg_file.stat().st_mtime if cfg_file.exists() else None
        except OSError:
            self._live_cfg_mtime = None
        self._uipi_lock = threading.Lock()
        self._uipi_checked_pids: Dict[int, bool] = {}
        self._uipi_warned_pids: set[int] = set()
        self._own_token_privileges = _get_own_token_privileges_win32() if sys.platform.startswith("win") else None

        self._queue_worker = threading.Thread(target=self._dialogue_worker_loop, daemon=True)
        self._queue_worker.start()

    def get_lotro_window(self) -> Optional[Dict[str, Any]]:
        """
        Locates the Lord of the Rings Online client window (64-bit or 32-bit).
        Returns {'hwnd': hwnd, 'title': title, 'left': x, 'top': y, 'width': w, 'height': h}
        or None if not found or minimized.
        """
        if not sys.platform.startswith("win"):
            return self._get_lotro_window_linux()

        import ctypes
        from ctypes import wintypes
        import psutil

        user32 = ctypes.windll.user32

        # Attach to active interactive desktop session (WinSta0 / default)
        desk = None
        try:
            winsta0 = user32.OpenWindowStationW("WinSta0", False, 0x037F)
            if winsta0:
                user32.SetProcessWindowStation(winsta0)
            desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if desk:
                user32.SetThreadDesktop(desk)
        except Exception:
            desk = None

        lotro_procs: Dict[int, str] = {}
        for p in psutil.process_iter(["name", "pid"]):
            try:
                if p.info["name"]:
                    pname = p.info["name"].lower()
                    if pname in LOTRO_CLIENT_BINARIES:
                        lotro_procs[p.info["pid"]] = pname
            except Exception:
                pass

        if not lotro_procs:
            return None

        found_windows = []

        def enum_desk_cb(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in lotro_procs and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    rect = (ctypes.c_long * 4)()
                    user32.GetWindowRect(hwnd, rect)
                    left, top, right, bottom = rect
                    w = right - left
                    h = bottom - top
                    if w > 200 and h > 200:
                        found_windows.append((hwnd, title, int(left), int(top), int(w), int(h), int(pid.value)))
            return True

        DESKENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        cb = DESKENUMPROC(enum_desk_cb)

        if desk:
            user32.EnumDesktopWindows(desk, cb, 0)
        else:
            user32.EnumWindows(cb, 0)

        if found_windows:
            best = max(found_windows, key=lambda it: it[4] * it[5])
            hwnd, title, left, top, w, h, best_pid = best
            self._check_pid_uipi_mismatch(best_pid, proc_name=lotro_procs.get(best_pid))
            logger.debug(f"Targeting LOTRO Window: '{title}' (hwnd={hwnd}, {w}x{h} at [{left},{top}])")
            return {
                "hwnd": hwnd,
                "title": title,
                "left": left,
                "top": top,
                "width": w,
                "height": h,
            }

        return None

    def get_lotro_window_rect(self) -> Optional[Dict[str, int]]:
        """Compatibility helper returning mss-compatible rect dict."""
        info = self.get_lotro_window()
        if not info:
            return None
        return {
            "left": info["left"],
            "top": info["top"],
            "width": info["width"],
            "height": info["height"],
        }

    def _get_lotro_window_linux(self) -> Optional[Dict[str, Any]]:
        """
        Locates the LOTRO client window under Linux (X11 / XWayland) via wmctrl or xdotool.
        Returns {'hwnd': id, 'title': title, 'left': x, 'top': y, 'width': w, 'height': h}
        or None.
        """
        import subprocess
        import shutil

        # 1. Try wmctrl -l -G
        if shutil.which("wmctrl"):
            try:
                res = subprocess.run(["wmctrl", "-l", "-G"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        if "lord of the rings online" in line.lower():
                            parts = line.split(None, 7)
                            if len(parts) >= 8:
                                win_id_str, _, x_str, y_str, w_str, h_str, _, title = parts
                                try:
                                    return {
                                        "hwnd": int(win_id_str, 16),
                                        "title": title.strip(),
                                        "left": int(x_str),
                                        "top": int(y_str),
                                        "width": int(w_str),
                                        "height": int(h_str),
                                    }
                                except ValueError:
                                    pass
            except Exception as e:
                logger.debug(f"wmctrl window lookup failed: {e}")

        # 2. Try xdotool
        if shutil.which("xdotool"):
            try:
                res = subprocess.run(
                    ["xdotool", "search", "--onlyvisible", "--name", "Lord of the Rings Online"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0 and res.stdout.strip():
                    win_id = res.stdout.strip().splitlines()[0].strip()
                    geo = subprocess.run(["xdotool", "getwindowgeometry", win_id], capture_output=True, text=True, timeout=2)
                    if geo.returncode == 0:
                        pos_match = re.search(r"Position:\s*(\d+),(\d+)", geo.stdout)
                        size_match = re.search(r"Geometry:\s*(\d+)x(\d+)", geo.stdout)
                        if pos_match and size_match:
                            return {
                                "hwnd": int(win_id),
                                "title": "The Lord of the Rings Online",
                                "left": int(pos_match.group(1)),
                                "top": int(pos_match.group(2)),
                                "width": int(size_match.group(1)),
                                "height": int(size_match.group(2)),
                            }
            except Exception as e:
                logger.debug(f"xdotool window lookup failed: {e}")

        return None

    @staticmethod
    def _capture_window_surface_win32(hwnd: int, w: int, h: int):
        """
        Captures the rendered DWM DirectX surface of the target window on demand via
        PrintWindow(..., PW_RENDERFULLCONTENT=2).
        - Captures ONLY the LOTRO window even when occluded/covered by other windows (like OBS Window Capture).
        - Zero background CPU/GPU resource consumption while idle and no WGC yellow border.
        Returns a BGR uint8 numpy array (h, w, 3) or None if unavailable.
        """
        import ctypes
        from ctypes import wintypes
        import numpy as np

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        hwnd_dc = user32.GetWindowDC(hwnd)
        if not hwnd_dc:
            return None

        mem_dc = None
        bmp = None
        try:
            mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
            if not mem_dc:
                return None
            bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
            if not bmp:
                return None

            gdi32.SelectObject(mem_dc, bmp)
            # PW_RENDERFULLCONTENT (0x00000002) queries DWM for the composed DirectX window surface
            ok = user32.PrintWindow(hwnd, mem_dc, 2)
            if not ok:
                return None

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h  # Top-down DIB
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0  # BI_RGB

            buf = ctypes.create_string_buffer(w * h * 4)
            lines = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
            if lines != h:
                return None

            arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))[:, :, :3].copy()
            # Reject all-black frames (can occur if game runs in legacy exclusive fullscreen without DWM)
            if arr.max() == 0:
                return None
            return arr
        finally:
            if bmp:
                gdi32.DeleteObject(bmp)
            if mem_dc:
                gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, hwnd_dc)

    @staticmethod
    def _is_wayland_session() -> bool:
        """True inside a Wayland desktop session, where X11 screen grabs (mss GetImage) are refused."""
        return (
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )

    @staticmethod
    def _load_capture_png(png_path: Path):
        """Loads a captured PNG as a contiguous BGR numpy array (same layout as the mss path)."""
        import numpy as np
        from PIL import Image

        with Image.open(png_path) as im:
            rgb = np.array(im.convert("RGB"))
        return np.ascontiguousarray(rgb[:, :, ::-1])

    def _capture_wayland_spectacle(self, tmp_dir: Path):
        """KDE Plasma: Spectacle in background mode (active window first, then the current monitor)."""
        import shutil
        import subprocess

        exe = shutil.which("spectacle")
        if not exe:
            return None, "spectacle not installed"

        last_error = "no output file produced"
        for target_flag in ("--activewindow", "--current"):
            out_path = tmp_dir / f"spectacle{target_flag.replace('-', '_')}.png"
            res = subprocess.run(
                [exe, "--background", "--nonotify", target_flag, "--no-decoration", "--output", str(out_path)],
                capture_output=True, text=True, timeout=10,
            )
            # Spectacle may finish writing the file slightly after it returns
            deadline = time.time() + 2.0
            while time.time() < deadline and not (out_path.exists() and out_path.stat().st_size > 0):
                time.sleep(0.02)
            if not (out_path.exists() and out_path.stat().st_size > 0):
                last_error = (res.stderr or res.stdout or "no output file produced").strip()
                continue

            img = self._load_capture_png(out_path)
            h, w = img.shape[:2]
            if w <= 400 or h <= 400:
                # Focus was on a small window, not the game: retry with the whole monitor
                last_error = f"captured area too small ({w}x{h})"
                continue
            return img, f"spectacle {target_flag.lstrip('-')}"
        return None, f"spectacle: {last_error}"

    def _capture_wayland_grim(self, tmp_dir: Path):
        """wlroots compositors (Sway, Hyprland, ...): grim, full desktop. Fails fast on other compositors."""
        import shutil
        import subprocess

        exe = shutil.which("grim")
        if not exe:
            return None, "grim not installed"

        out_path = tmp_dir / "grim.png"
        res = subprocess.run([exe, str(out_path)], capture_output=True, text=True, timeout=10)
        if res.returncode != 0 or not out_path.exists():
            return None, f"grim: {(res.stderr or res.stdout or f'exit code {res.returncode}').strip()}"
        return self._load_capture_png(out_path), "grim"

    def _capture_wayland_portal(self, tmp_dir: Path):
        """
        Any desktop with xdg-desktop-portal (GNOME, KDE, wlroots with xdg-desktop-portal-wlr):
        non-interactive org.freedesktop.portal.Screenshot over D-Bus (via jeepney). Full desktop only;
        some desktops ask once for screenshot permission. The portal saves the image itself
        (usually in ~/Pictures), so that exact file is deleted after loading.
        """
        try:
            from jeepney import DBusAddress, MatchRule, MessageType, message_bus, new_method_call
            from jeepney.io.blocking import Proxy, open_dbus_connection
        except ImportError:
            return None, "jeepney not installed (re-run the TTS setup)"
        from urllib.parse import unquote, urlparse

        conn = open_dbus_connection(bus="SESSION")
        try:
            token = f"lotro_tts_{os.getpid()}_{int(time.time() * 1000)}"
            sender = conn.unique_name.lstrip(":").replace(".", "_")
            request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
            rule = MatchRule(
                type="signal", interface="org.freedesktop.portal.Request", member="Response", path=request_path
            )
            Proxy(message_bus, conn).AddMatch(rule)

            portal = DBusAddress(
                "/org/freedesktop/portal/desktop",
                bus_name="org.freedesktop.portal.Desktop",
                interface="org.freedesktop.portal.Screenshot",
            )
            msg = new_method_call(
                portal, "Screenshot", "sa{sv}",
                ("", {"handle_token": ("s", token), "interactive": ("b", False)}),
            )
            with conn.filter(rule) as responses:
                reply = conn.send_and_get_reply(msg, timeout=5)
                if reply.header.message_type == MessageType.error:
                    return None, f"portal: {reply.body[0] if reply.body else 'D-Bus error'}"
                # Generous timeout: the desktop may show a one-time permission prompt
                signal = conn.recv_until_filtered(responses, timeout=30)
        finally:
            conn.close()

        response_code, results = signal.body
        if response_code != 0:
            return None, f"portal: request denied or cancelled (code {response_code})"
        uri = results.get("uri", ("s", ""))[1]
        shot_path = Path(unquote(urlparse(uri).path)) if uri.startswith("file://") else None
        if not shot_path or not shot_path.exists():
            return None, f"portal: no screenshot file returned ({uri or 'empty uri'})"
        try:
            return self._load_capture_png(shot_path), "xdg-desktop-portal"
        finally:
            try:
                shot_path.unlink()
            except OSError:
                pass

    def _capture_screen_wayland(self):
        """
        Tries Wayland-native capture backends in order (Spectacle, grim, xdg-desktop-portal).
        The last working backend is tried first next time. Returns a BGR numpy array,
        or None when no backend worked (the caller then falls back to mss).
        """
        import tempfile

        backends = {
            "spectacle": self._capture_wayland_spectacle,
            "grim": self._capture_wayland_grim,
            "portal": self._capture_wayland_portal,
        }
        order = list(backends)
        preferred = getattr(self, "_wayland_capture_backend", None)
        if preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)

        errors = []
        with tempfile.TemporaryDirectory(prefix="lotro_tts_capture_") as tmp:
            for name in order:
                try:
                    img, detail = backends[name](Path(tmp))
                except Exception as e:
                    img, detail = None, f"{name}: {e}"
                if img is not None:
                    self._wayland_capture_backend = name
                    logger.info(f"Captured {img.shape[1]}x{img.shape[0]} frame via {detail}")
                    return img
                errors.append(detail)

        if not getattr(self, "_wayland_capture_warned", False):
            self._wayland_capture_warned = True
            logger.warning(
                "Wayland session: no screen capture backend worked (" + "; ".join(errors) + "). "
                "Install 'spectacle' (KDE) or 'grim' (Sway/Hyprland), or make sure xdg-desktop-portal "
                "and its desktop backend are running (GNOME). Falling back to X11 capture."
            )
        return None

    def capture_screen(self):
        """
        Captures the LOTRO client frame cleanly:
        1. On Windows, directly captures the LOTRO process DWM surface (ignoring overlapping windows).
        2. In a Linux Wayland session, uses a Wayland-native capture tool (X11 grabs are refused there).
        3. Falls back to mss desktop capture (Linux/Proton or exclusive fullscreen).
        """
        import mss
        import numpy as np

        win_info = self.get_lotro_window()

        # 1. Direct Windows DWM surface snapshot (works even when other windows cover LOTRO)
        if sys.platform.startswith("win") and win_info and win_info["width"] > 400 and win_info["height"] > 400:
            try:
                direct_img = self._capture_window_surface_win32(
                    win_info["hwnd"], win_info["width"], win_info["height"]
                )
                if direct_img is not None:
                    return direct_img
            except Exception as e:
                logger.debug(f"Direct window surface capture fallback to mss: {e}")

        # 2. Linux Wayland session: Wayland-native capture (mss is only tried if no backend works)
        if sys.platform.startswith("linux") and self._is_wayland_session():
            wayland_img = self._capture_screen_wayland()
            if wayland_img is not None:
                return wayland_img

        # 3. Fallback: mss monitor / window rect capture
        with mss.MSS() as sct:
            if win_info and win_info["width"] > 400 and win_info["height"] > 400:
                capture_box = {
                    "left": win_info["left"],
                    "top": win_info["top"],
                    "width": win_info["width"],
                    "height": win_info["height"],
                }
            else:
                monitors = sct.monitors[1:] if len(sct.monitors) > 1 else sct.monitors
                target_monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

                if win_info:
                    max_overlap = 0
                    for m in monitors:
                        m_r = m["left"] + m["width"]
                        m_b = m["top"] + m["height"]
                        r_r = win_info["left"] + win_info["width"]
                        r_b = win_info["top"] + win_info["height"]

                        inter_w = max(0, min(m_r, r_r) - max(m["left"], win_info["left"]))
                        inter_h = max(0, min(m_b, r_b) - max(m["top"], win_info["top"]))
                        overlap = inter_w * inter_h
                        if overlap > max_overlap:
                            max_overlap = overlap
                            target_monitor = m

                capture_box = target_monitor

            screenshot = sct.grab(capture_box)
            img = np.ascontiguousarray(np.array(screenshot)[:, :, :3])
            return img

    def _refresh_live_config(self):
        """Hot-reloads dynamic service settings (e.g. queue_mode) when config.json changes."""
        config_file = base_dir / "config.json"
        if not config_file.exists():
            return
        try:
            mtime = config_file.stat().st_mtime
            if mtime != self._live_cfg_mtime:
                self._live_cfg_mtime = mtime
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                if "queue_mode" in cfg:
                    self.queue_mode = bool(cfg["queue_mode"])
        except Exception:
            pass

    def _is_canceled(
        self,
        expected_gen: Optional[int] = None,
        expected_epoch: Optional[int] = None,
        expected_item_id: Optional[int] = None,
    ) -> bool:
        with self._lock:
            if expected_gen is not None and expected_gen != self._trigger_gen:
                return True
            if expected_epoch is not None and expected_epoch != self._queue_epoch:
                return True
            if expected_item_id is not None and self._skipped_worker_item_id == expected_item_id:
                return True
        return False

    def _drain_dialogue_queue(self):
        """Removes all pending items from the FIFO dialogue queue."""
        drained = 0
        while True:
            try:
                self._dialogue_queue.get_nowait()
                self._dialogue_queue.task_done()
                drained += 1
            except queue.Empty:
                break
        return drained

    def _resolve_dialogue_from_capture(
        self,
        screen_img,
        active_client_lang: str,
        active_tts_lang: str,
        target_name: str,
        explicit_target: bool,
        player_info: Optional[PlayerInfo],
        expected_gen: Optional[int] = None,
        expected_epoch: Optional[int] = None,
        expected_item_id: Optional[int] = None,
    ) -> Optional[tuple[str, str, str]]:
        """Runs OCR, lotro.db resolution, and optional translation on a captured screenshot."""
        ocr_lang = active_client_lang.upper()
        logger.info(f"Scanning screen for quest / instance dialog (OCR lang: {ocr_lang})...")
        with self._ocr_lock:
            if self._is_canceled(expected_gen, expected_epoch, expected_item_id):
                return None
            scan_result = self.screen_reader.scan_screen_with_cache(
                screen_img, target_npc=target_name, lang=ocr_lang, player_info=player_info
            )

        if self._is_canceled(expected_gen, expected_epoch, expected_item_id):
            return None

        window_type = scan_result.get("window_type", "unknown")
        title = scan_result.get("title", "")
        final_text = scan_result.get("final_text", "").strip()

        if not final_text:
            logger.warning("No dialog or quest text detected in window! (Ensure quest parchment is open and visible on screen)")
            return None

        logger.info(f"Window: [{window_type.upper()}] '{title}'")
        if scan_result.get("db_text"):
            logger.info(f"Full un-truncated quest text matched from lotro.db ({ocr_lang})!")
        else:
            logger.info("Using OCR-extracted text from window.")

        # Resolve speaker target: DB NPC ID > explicit in-game target > fallback narrator
        matched_npc_id = scan_result.get("npc_id")
        if matched_npc_id:
            speaker_target = str(matched_npc_id)
            logger.info(f"Resolved Quest NPC ID [{matched_npc_id}] directly from lotro.db!")
        elif explicit_target and target_name:
            speaker_target = target_name
            logger.info(f"No DB NPC ID found; using in-game target from plugin log: '{target_name}'")
        else:
            speaker_target = target_name or "narrator"

        # Cross-language native DB lookup (e.g. EN client -> ES/DE/FR native text by quest_id)
        matched_qid = scan_result.get("quest_id")
        matched_text_id = scan_result.get("quest_text_id")
        db_target_hint = "" if matched_npc_id else target_name
        direct_text = None
        if matched_qid and active_tts_lang in ("de", "en", "fr", "es") and active_tts_lang != active_client_lang:
            direct_text = self.screen_reader.get_quest_text_by_id(
                matched_qid, target_npc=db_target_hint, lang=active_tts_lang,
                quest_text_id=matched_text_id, player_info=player_info
            )
            if direct_text:
                logger.info(f"Using native '{active_tts_lang.upper()}' quest text directly from lotro.db!")
                final_text = direct_text

        # On-demand MarianMT Translation (for Italian 'it', Dutch 'nl', or DB-missing Spanish/English fallback)
        needs_translation = (
            active_tts_lang in ("it", "nl")
            or (active_tts_lang == "es" and not direct_text and active_client_lang != "es")
            or (active_tts_lang == "en" and not direct_text and active_client_lang in ("de", "fr"))
        )
        if needs_translation:
            if self._is_canceled(expected_gen, expected_epoch, expected_item_id):
                logger.info("Dialogue trigger canceled before translation.")
                return None

            src_lang = active_client_lang
            if matched_qid:
                clean_en_text = self.screen_reader.get_quest_text_by_id(
                    matched_qid, target_npc=db_target_hint, lang="en",
                    quest_text_id=matched_text_id, player_info=player_info
                )
                if clean_en_text:
                    final_text = clean_en_text
                    src_lang = "en"
            try:
                final_text = self.translator.translate(final_text, src_lang=src_lang, target_lang=active_tts_lang)
            except Exception as e:
                logger.warning(f"Translation fallback ({src_lang} -> {active_tts_lang}): {e}. Using original text.")

        if self._is_canceled(expected_gen, expected_epoch, expected_item_id):
            return None

        dialogue_ctx = {
            "window_type": window_type,
            "quest_title": title or None,
            "quest_id": matched_qid,
            "quest_text_id": matched_text_id,
            "client_lang": active_client_lang,
        }
        meta_map = getattr(self, "_dialogue_meta_by_key", None)
        if isinstance(meta_map, dict):
            with self._lock:
                if len(meta_map) >= 32:
                    meta_map.clear()
                meta_map[(final_text, speaker_target, active_tts_lang)] = dialogue_ctx

        return final_text, speaker_target, active_tts_lang

    def _speak_resolved_dialogue(
        self,
        final_text: str,
        speaker_target: str,
        active_tts_lang: str,
        expected_gen: Optional[int] = None,
        expected_epoch: Optional[int] = None,
        expected_item_id: Optional[int] = None,
    ):
        """Speaks resolved dialogue text cleanly unless canceled before start."""
        if self._is_canceled(expected_gen, expected_epoch, expected_item_id):
            logger.info("Dialogue trigger canceled before playback.")
            return
        extra_meta = None
        meta_map = getattr(self, "_dialogue_meta_by_key", None)
        if isinstance(meta_map, dict):
            with self._lock:
                extra_meta = meta_map.get((final_text, speaker_target, active_tts_lang))
        with self._lock:
            self._is_speaking = True
        try:
            if self.narrator_mode:
                logger.info(
                    f"Speaking text ({len(final_text)} chars) for '{speaker_target}' in [NARRATOR MODE] (Voice: {self.narrator_voice}) in '{active_tts_lang}'..."
                )
            else:
                logger.info(
                    f"Speaking text ({len(final_text)} chars) for NPC '{speaker_target}' in '{active_tts_lang}'..."
                )
            speak_kwargs: Dict[str, Any] = {"lang": active_tts_lang, "wait": True}
            if getattr(self, "gui_ipc", False) and extra_meta:
                speak_kwargs["extra_meta"] = extra_meta
            self.speaker.speak(final_text, speaker_target, **speak_kwargs)
        finally:
            with self._lock:
                self._is_speaking = False

    def _dialogue_worker_loop(self):
        """Sequentially processes queued screenshot/replay jobs in FIFO order for Queue Mode."""
        while True:
            try:
                item = self._dialogue_queue.get()
                item_id = None
                try:
                    job_type = item[0]
                    item_epoch = item[1]
                    if self._is_canceled(expected_epoch=item_epoch):
                        continue

                    with self._lock:
                        if item_epoch != self._queue_epoch:
                            continue
                        self._worker_item_seq += 1
                        item_id = self._worker_item_seq
                        self._current_worker_item_id = item_id

                    if job_type == "ocr_job":
                        _, _, screen_img, active_client_lang, active_tts_lang, target_name, explicit_target, p_info = item
                        with self._lock:
                            if item_epoch != self._queue_epoch or self._skipped_worker_item_id == item_id:
                                continue
                            self._is_scanning = True
                        resolved = None
                        try:
                            resolved = self._resolve_dialogue_from_capture(
                                screen_img,
                                active_client_lang,
                                active_tts_lang,
                                target_name,
                                explicit_target,
                                p_info,
                                expected_epoch=item_epoch,
                                expected_item_id=item_id,
                            )
                        finally:
                            del screen_img
                            with self._lock:
                                self._is_scanning = False

                        if resolved and not self._is_canceled(expected_epoch=item_epoch, expected_item_id=item_id):
                            final_text, speaker_target, out_lang = resolved
                            with self._lock:
                                self._last_dialogue = (final_text, speaker_target, out_lang)
                            self._speak_resolved_dialogue(
                                final_text,
                                speaker_target,
                                out_lang,
                                expected_epoch=item_epoch,
                                expected_item_id=item_id,
                            )
                    elif job_type == "replay_job":
                        _, _, final_text, speaker_target, out_lang = item
                        self._speak_resolved_dialogue(
                            final_text,
                            speaker_target,
                            out_lang,
                            expected_epoch=item_epoch,
                            expected_item_id=item_id,
                        )
                finally:
                    with self._lock:
                        if item_id is not None and self._current_worker_item_id == item_id:
                            self._current_worker_item_id = None
                    self._dialogue_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing queued dialogue: {e}")

    def handle_trigger(
        self, plugin_client_lang: str = "", target_name: str = "", player_info: Optional[PlayerInfo] = None
    ):
        """
        Captures the LOTRO screen immediately on trigger (~20-40ms), then either queues
        the capture (Queue Mode) or interrupts and speaks immediately (Interrupt Mode).
        """
        if player_info is None:
            player_info = self.player_info
        self._refresh_live_config()
        is_queue_mode = self.queue_mode

        active_client_lang = (
            plugin_client_lang.lower().strip()
            if plugin_client_lang and plugin_client_lang.lower().strip() in ("en", "de", "fr")
            else self.game_lang
        )
        active_tts_lang = self.tts_lang
        explicit_target = bool(target_name and target_name.strip())
        if not explicit_target:
            target_name = self.last_detected_target or ""

        # Stage 1: Grab raw frame immediately so closing the quest window right after trigger never breaks OCR
        with self._capture_lock:
            now = time.monotonic()
            if now - self._last_trigger_ts < 0.12:
                logger.debug("Trigger arrived within 120ms debounce window; skipping duplicate.")
                return
            self._last_trigger_ts = now

            logger.info(
                f"Trigger activated -> Client Lang: {active_client_lang.upper()} | "
                f"TTS Lang: {active_tts_lang.upper()} | Target: '{target_name}'"
            )
            try:
                logger.info("Capturing screen...")
                screen_img = self.capture_screen()
            except Exception as e:
                logger.error(f"Screen capture failed: {e}")
                return

        if is_queue_mode:
            with self._lock:
                my_epoch = self._queue_epoch
                busy = self._is_scanning or self._is_speaking or (self.speaker and self.speaker.is_speaking()) or not self._dialogue_queue.empty()
            try:
                self._dialogue_queue.put_nowait(
                    ("ocr_job", my_epoch, screen_img, active_client_lang, active_tts_lang, target_name, explicit_target, player_info)
                )
                if busy:
                    logger.info(
                        f"Dialogue screenshot captured and queued ({self._dialogue_queue.qsize()} pending in queue)."
                    )
            except queue.Full:
                del screen_img
                logger.warning("Dialogue queue is full (10 items) — wait for playback or press Pause to clear.")
            return

        # Standard Interrupt Mode: cancel any active/queued items and run immediately
        with self._lock:
            self._trigger_gen += 1
            my_gen = self._trigger_gen
            self._queue_epoch += 1
            self._drain_dialogue_queue()
            self._is_scanning = True

        if self.speaker and (self._is_speaking or self.speaker.is_speaking()):
            logger.info("Interrupting previous speech for new dialogue trigger...")
            self.speaker.stop()

        resolved = None
        try:
            resolved = self._resolve_dialogue_from_capture(
                screen_img,
                active_client_lang,
                active_tts_lang,
                target_name,
                explicit_target,
                player_info,
                expected_gen=my_gen,
            )
        finally:
            del screen_img
            with self._lock:
                if my_gen == self._trigger_gen:
                    self._is_scanning = False

        if not resolved:
            return

        final_text, speaker_target, out_lang = resolved
        with self._lock:
            if my_gen != self._trigger_gen:
                logger.info("Dialogue trigger canceled before playback.")
                return
            self._last_dialogue = (final_text, speaker_target, out_lang)

        self._speak_resolved_dialogue(final_text, speaker_target, out_lang, expected_gen=my_gen)

    def replay_last(self):
        """Replays the last spoken dialogue (from cache if available)."""
        with self._lock:
            last = self._last_dialogue
        if not last:
            logger.info("No previous dialogue available to replay yet.")
            return

        self._refresh_live_config()
        final_text, speaker_target, out_lang = last
        if self.queue_mode:
            with self._lock:
                my_epoch = self._queue_epoch
                busy = self._is_scanning or self._is_speaking or (self.speaker and self.speaker.is_speaking()) or not self._dialogue_queue.empty()
            try:
                self._dialogue_queue.put_nowait(("replay_job", my_epoch, final_text, speaker_target, out_lang))
                msg = f"Replaying last dialogue for '{speaker_target}' (queued)..." if busy else f"Replaying last dialogue for '{speaker_target}'..."
                logger.info(msg)
            except queue.Full:
                logger.warning("Dialogue queue is full (10 items) — cannot queue replay right now.")
            return

        with self._lock:
            self._trigger_gen += 1
            my_gen = self._trigger_gen
            self._queue_epoch += 1
            self._drain_dialogue_queue()
        if self.speaker:
            self.speaker.stop()
        logger.info(f"Replaying last dialogue for '{speaker_target}'...")
        threading.Thread(
            target=self._speak_resolved_dialogue,
            args=(final_text, speaker_target, out_lang),
            kwargs={"expected_gen": my_gen},
            daemon=True,
        ).start()

    def skip_current(self):
        """Skips the currently playing/scanning dialogue in Queue Mode and advances to the next queued item."""
        self._refresh_live_config()
        if not self.queue_mode:
            logger.debug("Skip requested while Queue Mode is disabled.")
            return

        with self._lock:
            active_id = self._current_worker_item_id
            speaking_now = active_id is not None or self._is_scanning or self._is_speaking or (self.speaker and self.speaker.is_speaking())
            if not speaking_now:
                logger.debug("Skip hotkey pressed (no active dialogue in Queue Mode).")
                return
            if active_id is not None:
                self._skipped_worker_item_id = active_id
            remaining = self._dialogue_queue.qsize()

        if self.speaker:
            self.speaker.stop()

        if remaining > 0:
            logger.info(f"[SKIP] Skipping current dialogue -> moving to next queued quest ({remaining} remaining).")
        else:
            logger.info("[SKIP] Current dialogue skipped (queue is now empty).")

    def force_stop(self):
        """Immediately halts any running dialogue playback, active scan, queue, and speech synthesis."""
        was_active = False
        drained = 0
        with self._lock:
            drained = self._drain_dialogue_queue()
            if drained > 0 or self._is_scanning or self._is_speaking or (self.speaker and self.speaker.is_speaking()):
                was_active = True
            self._trigger_gen += 1
            self._queue_epoch += 1
            self._is_speaking = False
            self._is_scanning = False

        if self.speaker:
            self.speaker.stop()

        if was_active:
            if drained > 0:
                logger.info(f"[FORCE STOP] Dialogue playback interrupted and {drained} queued item(s) cleared!")
            else:
                logger.info("[FORCE STOP] Dialogue playback interrupted immediately by hotkey!")
        else:
            logger.debug("Stop hotkey pressed (no dialogue currently playing).")

    def start_keyboard_listener(self):
        """Starts background listener for Stop (default: Pause/Break) and optional Replay hotkeys."""
        try:
            from pynput import keyboard

            stop_req_mods, stop_main_key = _parse_hotkey_spec(self.stop_hotkey)
            replay_req_mods, replay_main_key = _parse_hotkey_spec(self.replay_hotkey)
            skip_req_mods, skip_main_key = _parse_hotkey_spec(self.skip_hotkey)
            pressed_mods: set[str] = set()
            mod_lock = threading.Lock()

            def on_press(key):
                mod = _get_modifier_name(key, keyboard)
                with mod_lock:
                    if mod:
                        pressed_mods.add(mod)
                        return
                    mods_snapshot = frozenset(pressed_mods)

                if _key_matches_spec(key, mods_snapshot, stop_req_mods, stop_main_key, keyboard):
                    threading.Thread(target=self.force_stop, daemon=True).start()
                    return

                if _key_matches_spec(key, mods_snapshot, replay_req_mods, replay_main_key, keyboard):
                    threading.Thread(target=self.replay_last, daemon=True).start()
                    return

                if _key_matches_spec(key, mods_snapshot, skip_req_mods, skip_main_key, keyboard):
                    threading.Thread(target=self.skip_current, daemon=True).start()

            def on_release(key):
                mod = _get_modifier_name(key, keyboard)
                if mod:
                    with mod_lock:
                        pressed_mods.discard(mod)

            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.daemon = True
            listener.start()
            replay_note = (
                f" | Replay Hotkey [{self.replay_hotkey.upper()}] -> Replay last"
                if replay_main_key
                else ""
            )
            skip_note = (
                f" | Skip Hotkey [{self.skip_hotkey.upper()}] -> Skip current (Queue Mode)"
                if skip_main_key
                else ""
            )
            logger.info(
                f"Global keyboard listener activated: Stop Hotkey [{self.stop_hotkey.upper()}] -> Force-stop playback{replay_note}{skip_note}"
            )
        except Exception as e:
            logger.warning(f"Could not start global keyboard listener: {e}")

    def start_mouse_listener(self):
        """Starts background listener for Middle Mouse Button (Button 3)."""
        try:
            from pynput import mouse

            def on_click(x, y, button, pressed):
                if pressed and button == mouse.Button.middle:
                    self._refresh_live_config()
                    # In Interrupt Mode, Mouse 3 acts as smart trigger/stop toggle;
                    # in Queue Mode, Mouse 3 queues new dialogues without interrupting current speech.
                    if not self.queue_mode and (
                        self._is_scanning or self._is_speaking or (self.speaker and self.speaker.is_speaking())
                    ):
                        logger.info("Middle mouse button (Mouse 3) clicked while active -> Stopping dialogue!")
                        self.force_stop()
                        return

                    msg = (
                        "Middle mouse button (Mouse 3) clicked -> Capturing & queuing dialogue!"
                        if self.queue_mode
                        else "Middle mouse button (Mouse 3) clicked -> Triggering dialogue scan!"
                    )
                    logger.info(msg)
                    threading.Thread(target=self.handle_trigger, daemon=True).start()

            listener = mouse.Listener(on_click=on_click)
            listener.daemon = True
            listener.start()
            mode_desc = "Trigger / Queue TTS" if self.queue_mode else "Trigger / Stop TTS"
            logger.info(f"Global mouse listener activated: Middle Mouse Button (Mouse 3) -> {mode_desc}")
        except Exception as e:
            logger.warning(f"Could not start global mouse listener: {e}")

    def _consume_player_info(self, line: str) -> bool:
        if not line.startswith("TTS:INFO|"):
            return False
        fields = [field.strip() for field in line.split("|")]
        if len(fields) == 5:
            _, name, race, gender, player_class = fields
            if name and gender in ("M", "F"):
                self.player_info = PlayerInfo(name, race, gender, player_class)
        return True

    def _check_pid_uipi_mismatch(self, pid: int, proc_name: Optional[str] = None) -> bool:
        """
        Checks once per LOTRO PID whether the target client is elevated while LOTRO-TTS is not.
        Logs an actionable UIPI warning once per mismatched PID and returns True if mismatched.
        """
        if not sys.platform.startswith("win") or not pid or self._own_token_privileges is None:
            return False

        with self._uipi_lock:
            cached_is_lotro = self._uipi_checked_pids.get(pid)
            if cached_is_lotro is not None and (proc_name is None or cached_is_lotro):
                return pid in self._uipi_warned_pids

        try:
            resolved_name, mismatched = _inspect_target_pid_elevation_win32(
                pid, self._own_token_privileges, known_lotro_name=proc_name
            )
        except Exception as e:
            logger.debug(f"UIPI elevation check skipped for pid={pid}: {e}")
            return False

        is_lotro = bool(resolved_name and resolved_name in LOTRO_CLIENT_BINARIES)
        should_warn = False
        with self._uipi_lock:
            if mismatched is not None:
                if len(self._uipi_checked_pids) > 512:
                    self._uipi_checked_pids.clear()
                self._uipi_checked_pids[pid] = is_lotro
            if mismatched is True and pid not in self._uipi_warned_pids:
                self._uipi_warned_pids.add(pid)
                should_warn = True

        if should_warn:
            display_name = resolved_name or "lotroclient64.exe"
            hotkey_label = self.stop_hotkey.upper()
            hotkeys_desc = f"Mouse 3 / {hotkey_label}" if self.enable_mouse else hotkey_label
            logger.warning(
                f"LOTRO ({display_name}) is running with Administrator/elevated privileges while LOTRO-TTS is not! "
                f"Windows UIPI blocks global hotkeys ({hotkeys_desc}) while LOTRO is focused. "
                "Fix: Run LOTRO-TTS.exe as Administrator, or disable 'Run as administrator' on LOTRO / Steam."
            )

        return bool(mismatched)

    def check_lotro_elevation_mismatch(self, check_foreground_only: bool = False) -> None:
        """Detects Windows UIPI privilege mismatches between LOTRO and LOTRO-TTS."""
        if not sys.platform.startswith("win") or self._own_token_privileges is None:
            return

        own_elevated, own_integrity, own_ui_access = self._own_token_privileges
        if own_ui_access or (
            own_elevated and (own_integrity is None or own_integrity >= _WIN_SECURITY_MANDATORY_HIGH_RID)
        ):
            return

        if check_foreground_only:
            import ctypes
            from ctypes import wintypes

            try:
                _, _, u32 = _get_win32_security_apis()
                fg_hwnd = u32.GetForegroundWindow()
                if not fg_hwnd:
                    return
                fg_pid = wintypes.DWORD(0)
                u32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
                if fg_pid.value:
                    self._check_pid_uipi_mismatch(int(fg_pid.value))
            except Exception as e:
                logger.debug(f"Foreground UIPI elevation check failed: {e}")
            return

        try:
            import psutil

            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    pid = proc.info.get("pid")
                    if pid and name in LOTRO_CLIENT_BINARIES:
                        self._check_pid_uipi_mismatch(int(pid), proc_name=name)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Startup UIPI elevation scan failed: {e}")

    def start_gui_ipc_listener(self):
        """Reads control commands (e.g. REPLAY) from redirected stdin when launched by the GUI."""
        if not self.gui_ipc:
            return

        def ipc_loop():
            try:
                for raw in sys.stdin:
                    cmd = (raw or "").strip().upper()
                    if cmd == "REPLAY":
                        threading.Thread(target=self.replay_last, daemon=True).start()
                    elif cmd == "SKIP":
                        threading.Thread(target=self.skip_current, daemon=True).start()
                    elif cmd == "STOP":
                        threading.Thread(target=self.force_stop, daemon=True).start()
            except Exception:
                pass

        threading.Thread(target=ipc_loop, daemon=True).start()

    def watch_script_log(self, poll_interval: float = 0.03):
        """Watches Script.log for read requests and character info."""
        logger.info(f"Watching '{self.script_log_path}' for plugin triggers...")

        self.start_keyboard_listener()
        if self.enable_mouse:
            self.start_mouse_listener()
        self.start_gui_ipc_listener()
        self.check_lotro_elevation_mismatch(check_foreground_only=False)

        last_uipi_check = time.monotonic()

        while True:
            try:
                now = time.monotonic()
                if now - last_uipi_check >= 2.0:
                    last_uipi_check = now
                    self.check_lotro_elevation_mismatch(check_foreground_only=True)

                if self.script_log_path.exists():
                    stat = self.script_log_path.stat()
                    identity = (stat.st_dev, stat.st_ino)
                    if identity != self.log_identity or stat.st_size < self.last_log_pos:
                        self.log_identity = identity
                        self.last_log_pos = 0

                    if stat.st_size > self.last_log_pos:
                        with self.script_log_path.open("rb") as f:
                            f.seek(self.last_log_pos)
                            new_lines = f.read().split(b"\n")[:-1]

                        for raw_line in new_lines:
                            self.last_log_pos += len(raw_line) + 1
                            line = raw_line.decode("utf-8", errors="replace").strip()
                            if self._consume_player_info(line):
                                continue
                            if line.startswith("TTS|"):
                                parts = line.split("|")
                                if len(parts) >= 3:
                                    lang_code = parts[1].strip()
                                    target_name = parts[2].strip()
                                    self.last_detected_client_lang = lang_code
                                    self.last_detected_target = target_name
                                    threading.Thread(
                                        target=self.handle_trigger, args=(lang_code, target_name, self.player_info), daemon=True
                                    ).start()
                                elif len(parts) == 2:
                                    lang_code = parts[1].strip()
                                    self.last_detected_client_lang = lang_code
                                    threading.Thread(
                                        target=self.handle_trigger, args=(lang_code, "", self.player_info), daemon=True
                                    ).start()
                else:
                    self.log_identity = None
                    self.last_log_pos = 0
                time.sleep(poll_interval)
            except KeyboardInterrupt:
                logger.info("Stopping LOTRO-TTS Service...")
                if self.speaker:
                    self.speaker.stop()
                    self.speaker.close()
                if self.screen_reader:
                    self.screen_reader.close()
                break
            except Exception as e:
                logger.error(f"Error watching log: {e}")
                time.sleep(1.0)


def get_default_lotro_documents_dir() -> Path:
    """
    Detects the default 'The Lord of the Rings Online' documents directory.
    On Windows, it queries the Windows Registry ('User Shell Folders' -> 'Personal')
    to properly handle users with custom/relocated Documents folders (e.g. D:\\Dokumente, OneDrive, etc.).
    Falls back to user home directory or Linux/Proton wine prefixes.
    """
    if sys.platform.startswith("win"):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            raw_path, _ = winreg.QueryValueEx(key, "Personal")
            winreg.CloseKey(key)
            expanded_path = os.path.expandvars(raw_path)
            candidate = Path(expanded_path) / "The Lord of the Rings Online"
            return candidate
        except Exception as e:
            logger.debug(f"Registry documents detection failed: {e}")

    home_docs = Path.home() / "Documents" / "The Lord of the Rings Online"
    home_docs_de = Path.home() / "Dokumente" / "The Lord of the Rings Online"

    if sys.platform.startswith("linux"):
        return _detect_linux_lotro_documents_dir(home_docs, home_docs_de)

    if home_docs.exists():
        return home_docs

    if home_docs_de.exists():
        return home_docs_de

    return home_docs


def _detect_linux_lotro_documents_dir(home_docs: Path, home_docs_de: Path) -> Path:
    """
    Linux: searches Wine/Proton prefixes before the native Documents folder, in the same order as the
    GUI's LotroPathDetector, so terminal runs watch the folder the GUI installs the plugin into.
    Among existing candidates, the one that already contains the TTS plugin wins.
    """
    docs_suffix = "drive_c/users/*/Documents/The Lord of the Rings Online"
    patterns = [
        # 1. Steam Proton (AppID 212500): native Steam, ~/.local/share/Steam, Flatpak Steam (both layouts)
        f".steam/steam/steamapps/compatdata/212500/pfx/{docs_suffix}",
        f".local/share/Steam/steamapps/compatdata/212500/pfx/{docs_suffix}",
        f".var/app/com.valvesoftware.Steam/.steam/steam/steamapps/compatdata/212500/pfx/{docs_suffix}",
        f".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/212500/pfx/{docs_suffix}",
        # 2. Lutris prefix
        f"Games/the-lord-of-the-rings-online/{docs_suffix}",
        # 3. Default Wine prefix
        f".wine/{docs_suffix}",
        # 4. Bottles prefixes (Flatpak)
        f".var/app/com.usebottles.bottles/data/bottles/bottles/*/{docs_suffix}",
    ]

    candidates = []
    seen = set()
    for pattern in patterns:
        for match in sorted(Path.home().glob(pattern)):
            if not match.is_dir():
                continue
            key = match.resolve()
            if key not in seen:
                seen.add(key)
                candidates.append(match)
    # 5. Native Documents folders (Linux client or manually linked)
    for native in (home_docs, home_docs_de):
        if native.is_dir() and native.resolve() not in seen:
            seen.add(native.resolve())
            candidates.append(native)

    for cand in candidates:
        if (cand / "Plugins" / "TTS" / "Main.lua").exists():
            return cand
    if candidates:
        return candidates[0]
    return home_docs


def load_or_prompt_config(base_dir: Path, force_prompt: bool = False) -> tuple[str, str]:
    """
    Loads language configuration from config.json or prompts the user interactively in English.
    Returns (game_lang, tts_lang).
    """
    config_file = base_dir / "config.json"

    if config_file.exists() and not force_prompt:
        try:
            if config_file.stat().st_size > 0:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                game_lang = str(cfg.get("game_lang", "")).lower().strip()
                tts_lang = str(cfg.get("tts_lang", "")).lower().strip()
                if game_lang in ("en", "de", "fr") and tts_lang in ("en", "de", "fr", "es", "it", "nl"):
                    return game_lang, tts_lang
        except Exception as e:
            logger.warning(f"Invalid config.json ({e}), re-prompting configuration...")

    print("\n" + "=" * 60)
    print("           LOTRO-TTS Language Configuration")
    print("=" * 60)
    print("1. Which language is your LOTRO game client set to? (for OCR & Dialogs)")
    print("   [1] English (en) - Default")
    print("   [2] German (de)")
    print("   [3] French (fr)")
    choice_client = input("Select (1-3) [Default 1]: ").strip().lower()

    client_map = {"1": "en", "2": "de", "3": "fr", "en": "en", "de": "de", "fr": "fr"}
    game_lang = client_map.get(choice_client, "en")

    print("\n2. In which language do you want dialogue to be read aloud (TTS)?")
    print("   [1] English (en) - Native Voice")
    print("   [2] German (de) - Native Voice")
    print("   [3] French (fr) - Native Voice")
    print("   [4] Spanish (es) - Native Quest Text via Voice Cloning")
    print("   [5] Italian (it) - Translated Quest Text via Voice Cloning")
    print("   [6] Dutch (nl) - Translated Quest Text via Voice Cloning")
    choice_tts = input("Select (1-6) [Default 1]: ").strip().lower()

    tts_map = {
        "1": "en",
        "2": "de",
        "3": "fr",
        "4": "es",
        "5": "it",
        "6": "nl",
        "nl": "nl",
        "en": "en",
        "de": "de",
        "fr": "fr",
        "es": "es",
        "it": "it",
    }
    tts_lang = tts_map.get(choice_tts, "en")

    # Save atomically to config.json so an empty 0 KB file can never be left behind
    try:
        payload = json.dumps({"version": "v2.0-rc5", "game_lang": game_lang, "tts_lang": tts_lang}, indent=2) + "\n"
        tmp_file = config_file.with_suffix(".json.tmp")
        tmp_file.write_text(payload, encoding="utf-8")
        os.replace(str(tmp_file), str(config_file))
        print(f"\nConfiguration saved to {config_file.name}: Client={game_lang.upper()} | TTS={tts_lang.upper()}")
    except Exception as e:
        print(f"Notice: Could not save config.json: {e}")

    print("=" * 60 + "\n")
    return game_lang, tts_lang


def main():
    parser = argparse.ArgumentParser(description="LOTRO-TTS Service")
    default_docs = get_default_lotro_documents_dir()
    parser.add_argument(
        "--docs-dir",
        type=str,
        default=str(default_docs),
        help=f"Path to LOTRO Documents folder (default: {default_docs})",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "cuda", "low-gpu", "low_vram", "cpu"],
        default="auto",
        help="Compute mode (auto detects GPU and enables Low-End GPU mode <= 6.5 GB VRAM)",
    )
    parser.add_argument("--no-mouse", action="store_true", help="Disable middle mouse button trigger")
    parser.add_argument("--client-lang", type=str, default=None, help="Force LOTRO game client language (en, de, fr)")
    parser.add_argument("--tts-lang", type=str, default=None, help="Force TTS speech language (en, de, fr, es, it, nl)")
    parser.add_argument("--config", action="store_true", help="Prompt for language configuration")
    parser.add_argument(
        "--stop-hotkey",
        type=str,
        default=None,
        help="Global hotkey to force-stop dialogue playback (default: 'pause')",
    )
    parser.add_argument(
        "--narrator-mode",
        action="store_true",
        help="Enable optional single narrator voice for all dialogue (audiobook style)",
    )
    parser.add_argument(
        "--narrator-voice",
        type=str,
        default=None,
        help="Voice ID to use for narrator mode (default: 'man_male_1')",
    )
    parser.add_argument(
        "--volume",
        type=int,
        default=None,
        help="TTS speech playback volume percent (0-100)",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=None,
        help="TTS speech speed percentage (75-135, default: 100)",
    )
    parser.add_argument(
        "--queue-mode",
        action="store_true",
        help="Queue triggered dialogues sequentially instead of interrupting current playback",
    )
    parser.add_argument(
        "--replay-hotkey",
        type=str,
        default=None,
        help="Global hotkey to replay the last dialogue (default: 'scroll_lock', 'none' to disable)",
    )
    parser.add_argument(
        "--skip-hotkey",
        type=str,
        default=None,
        help="Global hotkey to skip the active dialogue in Queue Mode (default: 'end', 'none' to disable)",
    )
    parser.add_argument(
        "--emit-duck-events",
        action="store_true",
        help="Emit [AUDIO_DUCK:1/0] stdout markers for GUI audio ducking",
    )
    parser.add_argument(
        "--gui-ipc",
        action="store_true",
        help="Read control commands (e.g. REPLAY, SKIP) from stdin when hosted by LOTRO-TTS GUI",
    )
    args = parser.parse_args()

    # Determine languages, hotkeys, queue mode, narrator mode, volume, and speed
    config_file = base_dir / "config.json"
    configured_stop_hotkey = "pause"
    configured_replay_hotkey = "scroll_lock"
    configured_skip_hotkey = "end"
    configured_queue_mode = False
    configured_narrator_mode = False
    configured_narrator_voice = "man_male_1"
    configured_volume = 80
    configured_speed = 100
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text(encoding="utf-8"))
            if cfg.get("stop_hotkey"):
                configured_stop_hotkey = str(cfg["stop_hotkey"]).lower().strip()
            if "replay_hotkey" in cfg and cfg["replay_hotkey"] is not None:
                configured_replay_hotkey = str(cfg["replay_hotkey"]).lower().strip()
            if "skip_hotkey" in cfg and cfg["skip_hotkey"] is not None:
                configured_skip_hotkey = str(cfg["skip_hotkey"]).lower().strip()
            if "queue_mode" in cfg:
                configured_queue_mode = bool(cfg["queue_mode"])
            if "narrator_mode" in cfg:
                configured_narrator_mode = bool(cfg["narrator_mode"])
            if cfg.get("narrator_voice"):
                configured_narrator_voice = str(cfg["narrator_voice"]).strip()
            if "volume" in cfg:
                configured_volume = int(cfg["volume"])
            if "speech_speed" in cfg:
                configured_speed = int(cfg["speech_speed"])
        except Exception:
            pass

    stop_hotkey = args.stop_hotkey or configured_stop_hotkey
    replay_hotkey = args.replay_hotkey if args.replay_hotkey is not None else configured_replay_hotkey
    skip_hotkey = args.skip_hotkey if args.skip_hotkey is not None else configured_skip_hotkey
    queue_mode = bool(args.queue_mode or configured_queue_mode)
    narrator_mode = args.narrator_mode or configured_narrator_mode
    narrator_voice = args.narrator_voice or configured_narrator_voice
    volume = args.volume if args.volume is not None else configured_volume
    speed = args.speed if args.speed is not None else configured_speed

    if args.client_lang and args.tts_lang:
        game_lang = args.client_lang.lower().strip()
        tts_lang = args.tts_lang.lower().strip()
    else:
        game_lang, tts_lang = load_or_prompt_config(base_dir, force_prompt=args.config)
        if args.client_lang:
            game_lang = args.client_lang.lower().strip()
        if args.tts_lang:
            tts_lang = args.tts_lang.lower().strip()

    narrator_info = f" | Narrator Mode = [ENABLED: {narrator_voice}]" if narrator_mode else " | Narrator Mode = [DISABLED]"
    queue_info = " | Queue Mode = [ENABLED]" if queue_mode else " | Queue Mode = [DISABLED]"
    replay_info = f" | Replay Hotkey = [{replay_hotkey.upper()}]" if replay_hotkey and replay_hotkey not in ("none", "off", "disabled") else ""
    skip_info = f" | Skip Hotkey = [{skip_hotkey.upper()}]" if skip_hotkey and skip_hotkey not in ("none", "off", "disabled") else ""
    logger.info(
        f"Active Settings: Game Client = [{game_lang.upper()}] | TTS Speech = [{tts_lang.upper()}] | Stop Hotkey = [{stop_hotkey.upper()}]{replay_info}{skip_info} | Volume = [{volume}%] | Speed = [{speed}%]{queue_info}{narrator_info}"
    )

    service = LotroPipelineService(
        lotro_docs_dir=Path(args.docs_dir),
        data_dir=base_dir / "data",
        voices_dir=base_dir / "data" / "voices",
        mode=args.mode,
        enable_mouse=not args.no_mouse,
        game_lang=game_lang,
        tts_lang=tts_lang,
        stop_hotkey=stop_hotkey,
        narrator_mode=narrator_mode,
        narrator_voice=narrator_voice,
        volume=volume,
        speed=speed,
        queue_mode=queue_mode,
        replay_hotkey=replay_hotkey,
        skip_hotkey=skip_hotkey,
        emit_duck_events=args.emit_duck_events,
        gui_ipc=args.gui_ipc,
    )
    service.watch_script_log()


if __name__ == "__main__":
    main()
