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
import argparse
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

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

from screen_reader import LotroScreenReader
from tts_speaker import LotroSpeaker
from translator import LotroTranslator

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LOTRO-TTS-Service")


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
    ):
        self.lotro_docs_dir = Path(lotro_docs_dir)
        self.script_log_path = self.lotro_docs_dir / "Script.log"
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "lotro.db"
        self.voices_dir = Path(voices_dir)
        self.enable_mouse = enable_mouse
        self.game_lang = game_lang.lower().strip()
        self.tts_lang = tts_lang.lower().strip()

        # Auto-detect CUDA GPU for maximum performance (e.g. RTX 4090)
        import torch
        if mode == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = mode

        logger.info(f"Connecting to Database & Pre-warming OCR: {self.db_path}")
        self.screen_reader = LotroScreenReader(str(self.db_path), eager_init=True)

        logger.info(f"Initializing TTS Speaker on device [{device.upper()}] (Voices: {self.voices_dir})")
        self.speaker = LotroSpeaker(str(self.voices_dir), str(self.db_path), device=device)
        self.translator = LotroTranslator(device=device)
        if self.tts_lang == "it":
            self.translator.preload("it")

        self.last_log_pos = 0
        if self.script_log_path.exists():
            self.last_log_pos = self.script_log_path.stat().st_size

        self.last_detected_client_lang = self.game_lang.upper()
        self.last_detected_target = ""
        self._is_processing = False
        self._lock = threading.Lock()

    def get_lotro_window(self) -> Optional[Dict[str, Any]]:
        """
        Locates the Lord of the Rings Online client window (64-bit or 32-bit).
        Returns {'hwnd': hwnd, 'title': title, 'left': x, 'top': y, 'width': w, 'height': h}
        or None if not found or minimized.
        """
        if not sys.platform.startswith("win"):
            return None

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

        LOTRO_BINARIES = ("lotroclient64.exe", "lotroclient.exe", "lotroclient_awesomium.exe")
        lotro_pids = set()
        for p in psutil.process_iter(["name", "pid"]):
            try:
                if p.info["name"] and p.info["name"].lower() in LOTRO_BINARIES:
                    lotro_pids.add(p.info["pid"])
            except Exception:
                pass

        if not lotro_pids:
            return None

        found_windows = []

        def enum_desk_cb(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in lotro_pids and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
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
                        found_windows.append((hwnd, title, int(left), int(top), int(w), int(h)))
            return True

        DESKENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        cb = DESKENUMPROC(enum_desk_cb)

        if desk:
            user32.EnumDesktopWindows(desk, cb, 0)
        else:
            user32.EnumWindows(cb, 0)

        if found_windows:
            best = max(found_windows, key=lambda it: it[4] * it[5])
            hwnd, title, left, top, w, h = best
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

    def capture_screen(self):
        """
        Captures the LOTRO client frame cleanly:
        1. On Windows, directly captures the LOTRO process DWM surface (ignoring overlapping windows).
        2. Falls back to mss desktop capture (Linux/Proton or exclusive fullscreen).
        """
        import mss
        import numpy as np

        win_info = self.get_lotro_window()

        # 1. Direct process DWM surface snapshot (works even when other windows cover LOTRO)
        if win_info and win_info["width"] > 400 and win_info["height"] > 400:
            try:
                direct_img = self._capture_window_surface_win32(
                    win_info["hwnd"], win_info["width"], win_info["height"]
                )
                if direct_img is not None:
                    return direct_img
            except Exception as e:
                logger.debug(f"Direct window surface capture fallback to mss: {e}")

        # 2. Fallback: mss monitor / window rect capture
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

    def handle_trigger(self, plugin_client_lang: str = "", target_name: str = ""):
        """Executes full workflow upon plugin button click or hotkey."""
        with self._lock:
            if self._is_processing:
                logger.info("Speech/OCR process already running, skipping trigger...")
                return
            self._is_processing = True

        try:
            # Note: Script.log emits TTS|<CLIENT_LANG>|<TARGET> from Turbine.Engine.GetLanguage().
            # Always keep self.tts_lang as the desired spoken output language (en, de, fr, es, it)!
            active_client_lang = (
                plugin_client_lang.lower().strip()
                if plugin_client_lang and plugin_client_lang.lower().strip() in ("en", "de", "fr")
                else self.game_lang
            )
            active_tts_lang = self.tts_lang
            if not target_name:
                target_name = self.last_detected_target or ""

            logger.info(
                f"Trigger activated -> Client Lang: {active_client_lang.upper()} | "
                f"TTS Lang: {active_tts_lang.upper()} | Target: '{target_name}'"
            )

            # 1. Capture LOTRO window surface
            try:
                logger.info("Capturing screen...")
                screen_img = self.capture_screen()
            except Exception as e:
                logger.error(f"Screen capture failed: {e}")
                return

            # 2. Run OCR & window analysis with cached geometry using client language
            ocr_lang = active_client_lang.upper()
            logger.info(f"Scanning screen for quest / instance dialog (OCR lang: {ocr_lang})...")
            scan_result = self.screen_reader.scan_screen_with_cache(
                screen_img, target_npc=target_name, lang=ocr_lang
            )

            window_type = scan_result.get("window_type", "unknown")
            title = scan_result.get("title", "")
            final_text = scan_result.get("final_text", "").strip()

            if not final_text:
                logger.warning("No dialog or quest text detected in window!")
                return

            logger.info(f"Window: [{window_type.upper()}] '{title}'")
            if scan_result.get("db_text"):
                logger.info(f"Full un-truncated quest text matched from lotro.db ({ocr_lang})!")
            else:
                logger.info("Using OCR-extracted text from window.")

            # 3. Cross-language native DB lookup (e.g. EN client -> ES/DE/FR native text by quest_id)
            matched_qid = scan_result.get("quest_id")
            if matched_qid and active_tts_lang in ("de", "en", "fr", "es") and active_tts_lang != active_client_lang:
                direct_text = self.screen_reader.get_quest_text_by_id(
                    matched_qid, target_npc=target_name, lang=active_tts_lang
                )
                if direct_text:
                    logger.info(f"Using native '{active_tts_lang.upper()}' quest text directly from lotro.db!")
                    final_text = direct_text

            # 4. On-demand MarianMT Translation (e.g. for Italian 'it')
            if active_tts_lang == "it":
                final_text = self.translator.translate(final_text, src_lang=active_client_lang, target_lang="it")

            # 5. Speak through TTS
            logger.info(
                f"Speaking text ({len(final_text)} chars) for NPC '{target_name}' in '{active_tts_lang}'..."
            )
            self.speaker.speak(final_text, target_name, lang=active_tts_lang)
        finally:
            with self._lock:
                self._is_processing = False

    def start_mouse_listener(self):
        """Starts background listener for Middle Mouse Button (Button 3)."""
        try:
            from pynput import mouse

            def on_click(x, y, button, pressed):
                if pressed and button == mouse.Button.middle:
                    logger.info("Middle mouse button (Mouse 3) clicked!")
                    threading.Thread(target=self.handle_trigger, daemon=True).start()

            listener = mouse.Listener(on_click=on_click)
            listener.daemon = True
            listener.start()
            logger.info("Global mouse listener activated: Middle Mouse Button (Mouse 3) -> Trigger TTS")
        except Exception as e:
            logger.warning(f"Could not start global mouse listener: {e}")

    def watch_script_log(self, poll_interval: float = 0.25):
        """Watches Script.log for new lines formatted as: TTS|<CLIENT_LANG>|<TARGET>."""
        logger.info(f"Watching '{self.script_log_path}' for plugin triggers...")

        if self.enable_mouse:
            self.start_mouse_listener()

        while True:
            try:
                if self.script_log_path.exists():
                    current_size = self.script_log_path.stat().st_size
                    if current_size < self.last_log_pos:
                        # Log file was truncated / rotated
                        self.last_log_pos = 0

                    if current_size > self.last_log_pos:
                        with open(self.script_log_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(self.last_log_pos)
                            new_lines = f.readlines()
                            self.last_log_pos = f.tell()

                        for line in new_lines:
                            line = line.strip()
                            if not line:
                                continue
                            if line.startswith("TTS|"):
                                parts = line.split("|")
                                if len(parts) >= 3:
                                    lang_code = parts[1].strip()
                                    target_name = parts[2].strip()
                                    self.last_detected_client_lang = lang_code
                                    self.last_detected_target = target_name
                                    threading.Thread(
                                        target=self.handle_trigger, args=(lang_code, target_name), daemon=True
                                    ).start()
                                elif len(parts) == 2:
                                    lang_code = parts[1].strip()
                                    self.last_detected_client_lang = lang_code
                                    threading.Thread(
                                        target=self.handle_trigger, args=(lang_code, ""), daemon=True
                                    ).start()
                time.sleep(poll_interval)
            except KeyboardInterrupt:
                logger.info("Stopping LOTRO-TTS Service...")
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
    if home_docs.exists():
        return home_docs

    home_docs_de = Path.home() / "Dokumente" / "The Lord of the Rings Online"
    if home_docs_de.exists():
        return home_docs_de

    if sys.platform.startswith("linux"):
        steam_lotro_paths = list(
            Path.home().glob(
                ".steam/steam/steamapps/compatdata/212500/pfx/drive_c/users/*/Documents/The Lord of the Rings Online"
            )
        )
        if steam_lotro_paths:
            return steam_lotro_paths[0]

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
                if game_lang in ("en", "de", "fr") and tts_lang in ("en", "de", "fr", "es", "it"):
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
    print("   [5] Italian (it) - AI Translated Quest Text via Voice Cloning")
    choice_tts = input("Select (1-5) [Default 1]: ").strip().lower()

    tts_map = {
        "1": "en",
        "2": "de",
        "3": "fr",
        "4": "es",
        "5": "it",
        "en": "en",
        "de": "de",
        "fr": "fr",
        "es": "es",
        "it": "it",
    }
    tts_lang = tts_map.get(choice_tts, "en")

    # Save atomically to config.json so an empty 0 KB file can never be left behind
    try:
        payload = json.dumps({"game_lang": game_lang, "tts_lang": tts_lang}, indent=2) + "\n"
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
        "--mode", choices=["auto", "cuda", "cpu"], default="auto", help="Compute mode (auto detects CUDA/RTX)"
    )
    parser.add_argument("--no-mouse", action="store_true", help="Disable middle mouse button trigger")
    parser.add_argument("--client-lang", type=str, default=None, help="Force LOTRO game client language (en, de, fr)")
    parser.add_argument("--tts-lang", type=str, default=None, help="Force TTS speech language (en, de, fr, es, it)")
    parser.add_argument("--config", action="store_true", help="Prompt for language configuration")
    args = parser.parse_args()

    # Determine languages
    if args.client_lang and args.tts_lang:
        game_lang = args.client_lang.lower().strip()
        tts_lang = args.tts_lang.lower().strip()
    else:
        game_lang, tts_lang = load_or_prompt_config(base_dir, force_prompt=args.config)
        if args.client_lang:
            game_lang = args.client_lang.lower().strip()
        if args.tts_lang:
            tts_lang = args.tts_lang.lower().strip()

    logger.info(
        f"Active Settings: Game Client Language = [{game_lang.upper()}] | TTS Speech Language = [{tts_lang.upper()}]"
    )

    service = LotroPipelineService(
        lotro_docs_dir=Path(args.docs_dir),
        data_dir=base_dir / "data",
        voices_dir=base_dir / "data" / "voices",
        mode=args.mode,
        enable_mouse=not args.no_mouse,
        game_lang=game_lang,
        tts_lang=tts_lang,
    )
    service.watch_script_log()


if __name__ == "__main__":
    main()
