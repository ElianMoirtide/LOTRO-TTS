#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Main Pipeline Service
1. Tails 'The Lord of the Rings Online/Script.log' for triggers: TTS|<LANG>|<TARGET>
2. Listens for global middle mouse button click (Mouse 3) as alternative trigger
3. Captures LOTRO screen area / dialog window via mss
4. Extracts dialogue via RapidOCR & queries lotro.db for full un-truncated text
5. Resolves voice profile from lotro.db for the target NPC
6. Speaks the dialogue text using LotroSpeaker
"""

import os
import sys
import time
import re
import argparse
import logging
import threading
from pathlib import Path

# Add scripts directory to path
base_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(base_dir / "scripts"))

from screen_reader import LotroScreenReader
from tts_speaker import LotroSpeaker

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LOTRO-TTS-Service")

class LotroPipelineService:
    def __init__(self, lotro_docs_dir: Path, data_dir: Path, voices_dir: Path, mode: str = "auto", enable_mouse: bool = True):
        self.lotro_docs_dir = Path(lotro_docs_dir)
        self.script_log_path = self.lotro_docs_dir / "Script.log"
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "lotro.db"
        self.voices_dir = Path(voices_dir)
        self.enable_mouse = enable_mouse
        
        # Auto-detect CUDA GPU for maximum performance (e.g. RTX 4090)
        import torch
        if mode == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = mode

        logger.info(f"Connecting to Database: {self.db_path}")
        self.screen_reader = LotroScreenReader(str(self.db_path))
        
        logger.info(f"Initializing TTS Speaker on device [{device.upper()}] (Voices: {self.voices_dir})")
        self.speaker = LotroSpeaker(str(self.voices_dir), str(self.db_path), device=device)
        
        self.last_log_pos = 0
        if self.script_log_path.exists():
            self.last_log_pos = self.script_log_path.stat().st_size

        self.last_detected_lang = "DE"
        self.last_detected_target = ""
        self._is_processing = False
        self._lock = threading.Lock()

    def capture_screen(self):
        """
        Captures the primary monitor or focused area.
        In LOTRO, quest and instance dialogue windows appear in the center-to-left region.
        Cropping the center 75% horizontally and vertically dramatically accelerates OCR
        while fully capturing any quest or instance dialogue window.
        """
        import mss
        import numpy as np

        with mss.MSS() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            screenshot = sct.grab(monitor)
            img = np.array(screenshot)[:, :, :3]  # Drop alpha channel
            
            # Crop away outer peripheral margins (skill bars at bottom, radar at top-right)
            h, w = img.shape[:2]
            # LOTRO quest dialogs are typically centered or slightly left of center
            crop_y1 = int(h * 0.05)
            crop_y2 = int(h * 0.90)
            crop_x1 = int(w * 0.05)
            crop_x2 = int(w * 0.85)
            cropped_img = img[crop_y1:crop_y2, crop_x1:crop_x2]
            return cropped_img

    def handle_trigger(self, lang_code: str = "", target_name: str = ""):
        """Executes full workflow upon plugin button click or hotkey."""
        with self._lock:
            if self._is_processing:
                logger.info("Speech/OCR process already running, skipping trigger...")
                return
            self._is_processing = True

        try:
            if not lang_code:
                lang_code = self.last_detected_lang or "DE"
            if not target_name:
                target_name = self.last_detected_target or ""

            logger.info(f"Trigger activated -> Language: {lang_code} | Target: '{target_name}'")
            
            # 1. Capture screen
            try:
                logger.info("Capturing screen...")
                screen_img = self.capture_screen()
            except Exception as e:
                logger.error(f"Screen capture failed: {e}")
                return

            # 2. Run OCR & window analysis with cached geometry
            logger.info("Scanning screen for quest / instance dialog...")
            scan_result = self.screen_reader.scan_screen_with_cache(screen_img, target_npc=target_name)
            
            window_type = scan_result.get("window_type", "unknown")
            title = scan_result.get("title", "")
            final_text = scan_result.get("final_text", "").strip()

            if not final_text:
                logger.warning("No dialog or quest text detected in window!")
                return

            logger.info(f"Window: [{window_type.upper()}] '{title}'")
            if scan_result.get("db_text"):
                logger.info("Full un-truncated quest text matched from lotro.db!")
            else:
                logger.info("Using OCR-extracted text from window.")

            # 3. Speak through TTS
            lang = lang_code.lower() if lang_code in ("DE", "EN") else "de"
            logger.info(f"Speaking text ({len(final_text)} chars) for NPC '{target_name}' in '{lang}'...")
            self.speaker.speak(final_text, target_name, lang=lang)
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
        """Watches Script.log for new lines formatted as: TTS|<LANG>|<TARGET>."""
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
                                    self.last_detected_lang = lang_code
                                    self.last_detected_target = target_name
                                    threading.Thread(target=self.handle_trigger, args=(lang_code, target_name), daemon=True).start()
                                elif len(parts) == 2:
                                    lang_code = parts[1].strip()
                                    self.last_detected_lang = lang_code
                                    threading.Thread(target=self.handle_trigger, args=(lang_code, ""), daemon=True).start()
                time.sleep(poll_interval)
            except KeyboardInterrupt:
                logger.info("Stopping LOTRO-TTS Service...")
                break
            except Exception as e:
                logger.error(f"Error watching log: {e}")
                time.sleep(1.0)

def main():
    parser = argparse.ArgumentParser(description="LOTRO-TTS Service")
    parser.add_argument("--docs-dir", type=str, default=r"D:\Dokumente\The Lord of the Rings Online", help="Path to LOTRO Documents folder")
    parser.add_argument("--mode", choices=["auto", "cuda", "cpu"], default="auto", help="Compute mode (auto detects CUDA/RTX)")
    parser.add_argument("--no-mouse", action="store_true", help="Disable middle mouse button trigger")
    args = parser.parse_args()

    service = LotroPipelineService(
        lotro_docs_dir=Path(args.docs_dir),
        data_dir=base_dir / "data",
        voices_dir=base_dir / "data" / "voices",
        mode=args.mode,
        enable_mouse=not args.no_mouse
    )
    service.watch_script_log()

if __name__ == "__main__":
    main()
