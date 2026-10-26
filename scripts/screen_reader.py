#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Screen Reader & OCR Pipeline (OS-Independent)
Extracts quest titles and dialogue texts from LOTRO windows.
Supports both Standard Quest windows and Instance / Dialogue windows.
"""

import os
import re
import sys
import sqlite3
import unicodedata
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

def normalize_text_for_matching(text: str) -> str:
    """Normalizes umlauts, ligatures and accents to simplified ASCII lowercase for robust fuzzy matching."""
    if not text:
        return ""
    text = text.lower()
    # Map umlauts directly to base vowels (ü -> u, ä -> a, ö -> o) because OCR often drops dots on capital letters
    text = text.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "s")
    text = text.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    # Decompose unicode characters (remove diacritics)
    text = unicodedata.normalize("NFKD", text)
    text = "".join([c for c in text if not unicodedata.combining(c)])
    # Remove all non-alphanumeric characters
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

class LotroScreenReader:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.db_path = base_dir / "data" / "lotro.db"
        else:
            self.db_path = Path(db_path)
            
        self.ocr_engine = None
        self.cached_window_box = None  # (x1, y1, x2, y2) relative to full screen

    def _init_ocr(self):
        """Pre-warms and initializes RapidOCR engine."""
        if self.ocr_engine is None:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine = RapidOCR()
            # Warm-up run so first in-game query doesn't suffer CUDA initialization penalty
            try:
                dummy = np.zeros((100, 300, 3), dtype=np.uint8)
                self.ocr_engine(dummy)
            except Exception:
                pass
        return self.ocr_engine

    def scan_screen_with_cache(self, full_screen_img, target_npc: str = "", lang: str = "de") -> Dict[str, Any]:
        """
        Scans using cached window coordinates first for near-instant OCR.
        Falls back to scanning the full screen if the cached crop does not contain a valid dialog.
        """
        import numpy as np
        from PIL import Image

        if isinstance(full_screen_img, Image.Image):
            full_screen_img = np.array(full_screen_img)

        h, w = full_screen_img.shape[:2]

        # 1. Try Cached Window Box if available
        if self.cached_window_box:
            cx1, cy1, cx2, cy2 = self.cached_window_box
            pad = 25
            x1 = max(0, cx1 - pad)
            y1 = max(0, cy1 - pad)
            x2 = min(w, cx2 + pad)
            y2 = min(h, cy2 + pad)

            # Fast path: First scan ONLY the top 15% (Title bar) of the cached window
            title_crop_h = max(35, int((y2 - y1) * 0.16))
            title_crop = full_screen_img[y1:y1 + title_crop_h, x1:x2]
            title_ocr, _ = self._init_ocr()(title_crop)
            
            if title_ocr:
                fast_title = " ".join([b[1].strip() for b in title_ocr if not re.search(r'(AUFGABENSTUFE|QUEST LEVEL|^X$)', b[1], re.IGNORECASE)])
                fast_title = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', fast_title).strip()
                if fast_title and self.db_path.exists():
                    q_id, db_text = self._lookup_quest_in_db(fast_title, target_npc=target_npc, lang=lang)
                    if db_text:
                        print(f"[LotroScreenReader] Fast-path DB hit on cached title: '{fast_title}' ({lang.upper()})")
                        is_instance = bool(re.search(r'^(INSTANZ|INSTANCE)', fast_title, re.IGNORECASE))
                        return {
                            "window_type": "instance" if is_instance else "quest",
                            "title": fast_title,
                            "dialog_text": db_text,
                            "db_text": db_text,
                            "final_text": db_text,
                            "quest_id": q_id,
                            "window_box": self.cached_window_box
                        }

            # If fast title check didn't match DB, scan the full cached box (e.g. dynamic dialog)
            cropped_box = full_screen_img[y1:y2, x1:x2]
            res = self.scan_image(cropped_box, target_npc=target_npc, lang=lang)
            if res.get("final_text") and res.get("title"):
                return res

        # 2. Fallback to Full Screen scan and update cached location
        res = self.scan_image(full_screen_img, target_npc=target_npc, lang=lang)
        if res.get("window_box"):
            self.cached_window_box = res["window_box"]
            print(f"[LotroScreenReader] Cached dialog window geometry: {self.cached_window_box}")
        return res

    def scan_image(self, image_input, target_npc: str = "", lang: str = "de") -> Dict[str, Any]:
        """
        Scans a window image or file path using RapidOCR.
        Supports PIL.Image, numpy.ndarray, file path str/Path, or bytes.
        """
        import numpy as np
        from PIL import Image

        if isinstance(image_input, Image.Image):
            image_input = np.array(image_input)

        ocr = self._init_ocr()
        result, elapse_list = ocr(image_input)
        
        if not result:
            return {
                "window_type": "unknown",
                "title": "",
                "dialog_text": "",
                "db_text": None,
                "final_text": "",
                "quest_id": None,
                "window_box": None
            }

        boxes = []
        for item in result:
            coords, text, conf = item
            y_min = min(pt[1] for pt in coords)
            y_max = max(pt[1] for pt in coords)
            x_min = min(pt[0] for pt in coords)
            x_max = max(pt[0] for pt in coords)
            boxes.append({
                "text": text.strip(),
                "conf": conf,
                "x_min": x_min,
                "x_max": x_max,
                "y_min": y_min,
                "y_max": y_max,
                "center_x": (x_min + x_max) / 2.0,
                "center_y": (y_min + y_max) / 2.0
            })

        # Calculate overall bounding frame
        img_w = max(b["x_max"] for b in boxes)
        img_h = max(b["y_max"] for b in boxes)

        # 1. Identify Title:
        boxes.sort(key=lambda b: b["y_min"])
        
        title_box = None
        for b in boxes:
            t = b["text"]
            if re.search(r'(AUFGABENSTUFE|QUEST LEVEL|TYP:|TYPE:|^X$)', t, re.IGNORECASE):
                continue
            if 0.15 * img_w < b["center_x"] < 0.85 * img_w and b["y_min"] < img_h * 0.18:
                title_box = b
                break

        title = title_box["text"] if title_box else ""
        title = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', title).strip()

        is_instance = bool(re.search(r'^(INSTANZ|INSTANCE)', title, re.IGNORECASE))
        window_type = "instance" if is_instance else "quest"

        # 2. Extract Left-Column Dialog Text:
        left_dialog_boxes = []
        for b in boxes:
            if b == title_box:
                continue
            if b["y_min"] < img_h * 0.12:
                continue
            if b["y_max"] > img_h * 0.85:
                continue
            if re.search(r'^(ANNEHMEN|ABLEHNEN|FORTSETZEN|WEITER|BEENDEN|ACCEPT|DECLINE|CONTINUE|FINISH|Aa)$', b["text"], re.IGNORECASE):
                continue
            if b["center_x"] < img_w * 0.58:
                left_dialog_boxes.append(b)

        left_dialog_boxes.sort(key=lambda b: b["y_min"])
        
        # Clean OCR text: replace OCR anomalies like leading 'Tch' or 'Ieh' with 'Ich'
        cleaned_dialog_lines = []
        for b in left_dialog_boxes:
            t = b["text"]
            if lang.lower() == "de":
                t = re.sub(r"^['\"]?[TtIil][ce]h\b", "'Ich", t)
                t = re.sub(r"\bStraBe\b", "Straße", t)
                t = re.sub(r"\bZahesten\b", "Zähesten", t)
            cleaned_dialog_lines.append(t)

        dialog_text = "\n\n".join(cleaned_dialog_lines)

        # Calculate window boundary for caching
        window_box = None
        if title_box and left_dialog_boxes:
            all_rel_boxes = [title_box] + left_dialog_boxes
            window_box = (
                int(min(b["x_min"] for b in all_rel_boxes)),
                int(min(b["y_min"] for b in all_rel_boxes)),
                int(max(b["x_max"] for b in boxes)),
                int(max(b["y_max"] for b in boxes))
            )

        # 3. DB Lookup:
        db_text = None
        quest_id = None
        if title and self.db_path.exists():
            quest_id, db_text = self._lookup_quest_in_db(title, target_npc=target_npc, lang=lang)

        # Final text selection: prefer DB text if matched, otherwise clean OCR text
        final_text = db_text if db_text else dialog_text

        return {
            "window_type": window_type,
            "title": title,
            "dialog_text": dialog_text,
            "db_text": db_text,
            "final_text": final_text,
            "quest_id": quest_id,
            "window_box": window_box
        }

    def _lookup_quest_in_db(self, title: str, target_npc: str = "", lang: str = "de") -> Tuple[Optional[int], Optional[str]]:
        """Queries lotro.db for best matching quest title and fetches bestower text in requested language."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            
            norm_query = normalize_text_for_matching(title)
            if not norm_query:
                conn.close()
                return None, None

            # Get candidate quests from DB
            cur.execute("SELECT id, title_de, title_en FROM Quests")
            all_quests = cur.fetchall()

            matched_id = None
            best_match_len = 0

            for q_id, t_de, t_en in all_quests:
                norm_de = normalize_text_for_matching(t_de)
                norm_en = normalize_text_for_matching(t_en)

                if norm_query == norm_de or norm_query == norm_en:
                    matched_id = q_id
                    break
                elif (norm_query in norm_de or norm_de in norm_query) and len(norm_de) > best_match_len:
                    matched_id = q_id
                    best_match_len = len(norm_de)
                elif (norm_query in norm_en or norm_en in norm_query) and len(norm_en) > best_match_len:
                    matched_id = q_id
                    best_match_len = len(norm_en)

            if not matched_id:
                conn.close()
                return None, None

            is_en = (lang.lower() == "en")

            # If target NPC name was passed from plugin, match NPC-specific dialog first
            if target_npc:
                cur.execute("""
                    SELECT qt.text_en, qt.text_de 
                    FROM Quest_Texts qt
                    JOIN NPCs n ON qt.npc_id = n.id
                    WHERE qt.quest_id = ? AND (LOWER(n.name_de) = LOWER(?) OR LOWER(n.name_en) = LOWER(?))
                    LIMIT 1
                """, (matched_id, target_npc, target_npc))
                npc_row = cur.fetchone()
                if npc_row:
                    text_candidate = (npc_row[0] if is_en else npc_row[1]) or (npc_row[1] if is_en else npc_row[0])
                    if text_candidate:
                        conn.close()
                        text = re.sub(r'\$\{PLAYERNAME:([^\[\|]+)[^}]*\}', r'\1', text_candidate)
                        text = re.sub(r'\$\{PLAYER[^}]*\}', 'friend' if is_en else 'Freund', text)
                        return matched_id, text.strip()

            # Otherwise fetch standard bestower / dialog text
            cur.execute("""
                SELECT text_en, text_de FROM Quest_Texts 
                WHERE quest_id = ? AND text_type IN ('bestower', 'dialog', 'description')
                ORDER BY CASE text_type 
                    WHEN 'bestower' THEN 1 
                    WHEN 'dialog' THEN 2
                    ELSE 3 END
                LIMIT 1
            """, (matched_id,))
            text_row = cur.fetchone()
            conn.close()

            if text_row:
                text_candidate = (text_row[0] if is_en else text_row[1]) or (text_row[1] if is_en else text_row[0])
                if text_candidate:
                    text = re.sub(r'\$\{PLAYERNAME:([^\[\|]+)[^}]*\}', r'\1', text_candidate)
                    text = re.sub(r'\$\{PLAYER[^}]*\}', 'friend' if is_en else 'Freund', text)
                    return matched_id, text.strip()

        except Exception as e:
            print(f"[LotroScreenReader] DB lookup error: {e}", file=sys.stderr)

        return None, None
