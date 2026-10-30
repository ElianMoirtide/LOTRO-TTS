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
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List, Set


def normalize_text_for_matching(text: str) -> str:
    """Normalizes umlauts, ligatures and accents to simplified ASCII lowercase for robust fuzzy matching."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("ß", "ss").replace("æ", "ae").replace("œ", "oe")
    # Decompose unicode characters (ä->a, ö->o, ü->u, ê->e, é->e, ñ->n, etc.)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Remove all non-alphanumeric characters
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


# Normalized prefixes for HUD notifications that must never be mistaken for an open dialog window
HUD_ALERT_PREFIXES = (
    "questavailable",
    "aufgabeverfugbar",
    "quetedisponible",
    "questcompleted",
    "aufgabeabgeschlossen",
    "queteterminee",
    "deedcompleted",
    "tatabgeschlossen",
    "newtitle",
)

# Normalized prefixes/tokens for Quest metadata lines right below the dialog title bar
LEVEL_META_PREFIXES = (
    "questlevel",
    "aufgabenstufe",
    "niveaudequete",
    "typesolo",
    "typsolo",
    "typefellowship",
    "typgefahrten",
    "typesmallfellowship",
    "typeraid",
    "repeatable",
    "wiederholbar",
)

# Normalized headers for the right-hand Objectives / Rewards column inside LOTRO Quest & Instance dialogs
OBJECTIVE_HEADERS = (
    "nextobjective",
    "currentobjective",
    "objectives",
    "nachstesziel",
    "aktuellesziel",
    "ziele",
    "objectifsuivant",
    "objectifactuel",
    "objectifs",
    "rewards",
    "belohnungen",
    "recompenses",
)

# Normalized action buttons at the bottom of LOTRO Quest & Instance dialogs
DIALOG_BUTTON_TOKENS = {
    "accept",
    "decline",
    "continue",
    "finish",
    "complete",
    "cancel",
    "later",
    "close",
    "travelnow",
    "enter",
    "launch",
    "annehmen",
    "ablehnen",
    "fortsetzen",
    "weiter",
    "beenden",
    "abbrechen",
    "schliessen",
    "jetztreisen",
    "accepter",
    "refuser",
    "continuer",
    "terminer",
    "annuler",
    "fermer",
}

CHAT_LINE_RE = re.compile(
    r"^(\[(World|LFF|Trade|Kinship|General|Regional|OOC|Fellowship|Raid|Officer|Advice|Glff|"
    r"Welt|SNG|Handel|Sippe|Allgemein|Gefahrten|Gefährten|Schlachtzug|Beratung|"
    r"Monde|Confrerie|Confrérie|Commerce|Conseil)\]|"
    r"(To\s+\w+\s*:|Say\s*:|Screenshot\s*\[)|\d+\s*FPS\b)",
    re.IGNORECASE,
)


class LotroScreenReader:
    def __init__(self, db_path: Optional[str] = None, eager_init: bool = True):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.db_path = base_dir / "data" / "lotro.db"
        else:
            self.db_path = Path(db_path)

        self.ocr_engine = None
        self._ocr_on_cuda = False
        self.cached_window_box: Optional[Tuple[int, int, int, int]] = None
        self.cached_title_strip: Optional[Tuple[int, int, int, int]] = None

        # Pre-indexed quest titles in RAM for O(1) sub-millisecond matching
        self._quest_index_loaded = False
        self._exact_titles: Dict[str, Dict[str, List[Tuple[int, str]]]] = {
            "de": defaultdict(list),
            "en": defaultdict(list),
            "fr": defaultdict(list),
            "es": defaultdict(list),
        }
        self._all_titles: Dict[str, List[Tuple[str, int, Set[str], int, str]]] = {
            "de": [],
            "en": [],
            "fr": [],
            "es": [],
        }

        if self.db_path.exists():
            self._init_quest_index()
        if eager_init:
            self._init_ocr()

    @staticmethod
    def _trigrams(s: str) -> Set[str]:
        if len(s) < 3:
            return {s} if s else set()
        return {s[i : i + 3] for i in range(len(s) - 2)}

    def _init_quest_index(self):
        """Loads and normalizes all quest titles from lotro.db into memory once (~35ms)."""
        if self._quest_index_loaded or not self.db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            rows = conn.execute("SELECT id, title_de, title_en, title_fr, title_es FROM Quests").fetchall()
            conn.close()

            col_langs = ((1, "de"), (2, "en"), (3, "fr"), (4, "es"))
            for row in rows:
                qid = row[0]
                for col_idx, lang_key in col_langs:
                    raw_t = row[col_idx]
                    if raw_t:
                        norm_t = normalize_text_for_matching(raw_t)
                        if norm_t:
                            self._exact_titles[lang_key][norm_t].append((qid, raw_t))
                            self._all_titles[lang_key].append(
                                (norm_t, len(norm_t), self._trigrams(norm_t), qid, raw_t)
                            )

            self._quest_index_loaded = True
        except Exception as e:
            print(f"[LotroScreenReader] Quest index preload notice: {e}", file=sys.stderr)

    def _init_ocr(self):
        """Pre-warms and initializes RapidOCR engine with true CUDA HEURISTIC execution when available."""
        if self.ocr_engine is None:
            import numpy as np
            import onnxruntime as ort
            from rapidocr_onnxruntime import RapidOCR

            try:
                import torch
                if torch.cuda.is_available():
                    torch_lib = Path(torch.__file__).parent / "lib"
                    if torch_lib.exists():
                        os.environ["PATH"] = str(torch_lib) + ";" + os.environ.get("PATH", "")
                        try:
                            os.add_dll_directory(str(torch_lib))
                        except Exception:
                            pass
            except Exception:
                pass

            # Disable 180-degree angle classifier and width/height ratio det-bypass bug
            self.ocr_engine = RapidOCR(
                use_angle_cls=False,
                width_height_ratio=-1,
                det_limit_type="max",
                det_limit_side_len=1920,
                det_model_path=None,
            )

            # RapidOCR 1.2.x UpdateParameters ignores rec_use_cuda and uses EXHAUSTIVE cuDNN search;
            # attach CUDAExecutionProvider with HEURISTIC search directly for instant GPU inference.
            if "CUDAExecutionProvider" in ort.get_available_providers():
                try:
                    ep = [
                        (
                            "CUDAExecutionProvider",
                            {
                                "device_id": 0,
                                "cudnn_conv_algo_search": "HEURISTIC",
                            },
                        ),
                        "CPUExecutionProvider",
                    ]
                    so = ort.SessionOptions()
                    so.log_severity_level = 4
                    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

                    det_infer = self.ocr_engine.text_detector.infer
                    det_infer.session = ort.InferenceSession(
                        det_infer.session._model_path, sess_options=so, providers=ep
                    )

                    rec_obj = self.ocr_engine.text_recognizer
                    for attr_val in rec_obj.__dict__.values():
                        if hasattr(attr_val, "session") and hasattr(attr_val.session, "_model_path"):
                            attr_val.session = ort.InferenceSession(
                                attr_val.session._model_path, sess_options=so, providers=ep
                            )
                            break

                    self._ocr_on_cuda = "CUDAExecutionProvider" in det_infer.session.get_providers()
                except Exception as e:
                    print(f"[LotroScreenReader] CUDA OCR provider fallback to CPU: {e}", file=sys.stderr)
                    self._ocr_on_cuda = False

            # Pre-warm detector and recognizer (including full batch=6 shape)
            try:
                dummy_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
                self.ocr_engine.text_detector(dummy_screen)
                self.ocr_engine.text_recognizer([np.zeros((48, 320, 3), dtype=np.uint8) for _ in range(6)])
            except Exception:
                pass

        return self.ocr_engine

    @staticmethod
    def _is_hud_alert(b: Dict[str, Any]) -> bool:
        n = b["norm"]
        if any(n.startswith(p) for p in HUD_ALERT_PREFIXES):
            return True
        if 10 <= len(n) <= 26:
            return any(SequenceMatcher(None, n[: len(p)], p).ratio() >= 0.85 for p in HUD_ALERT_PREFIXES)
        return False

    @staticmethod
    def _is_level_meta(b: Dict[str, Any]) -> bool:
        n = b["norm"]
        if any(n.startswith(p) for p in LEVEL_META_PREFIXES):
            return True
        if re.search(r"^(qu[ei]stlevel|aufgabenstufe|niveaudequ|ty[pf]esolo|ty[pf]efellowship)", n):
            return True
        return bool(
            re.search(
                r"\b(QU[EI]ST\s*LEVEL|AUFGABENSTUFE|NIVEAU\s*DE\s*QU|TY[PF]E?\s*[:;])\b",
                b["text"],
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_objective_hdr(b: Dict[str, Any]) -> bool:
        n = b["norm"]
        if n in OBJECTIVE_HEADERS or any(n.startswith(p) for p in OBJECTIVE_HEADERS):
            return True
        if 5 <= len(n) <= 24:
            return any(SequenceMatcher(None, n, p).ratio() >= 0.82 for p in OBJECTIVE_HEADERS)
        return False

    @staticmethod
    def _is_dialog_btn(b: Dict[str, Any]) -> bool:
        t = b["text"].strip()
        if t == "Aa":
            return True
        n = b["norm"]
        if len(n) <= 16 and n in DIALOG_BUTTON_TOKENS:
            return True
        if 5 <= len(n) <= 14:
            return any(SequenceMatcher(None, n, tok).ratio() >= 0.82 for tok in DIALOG_BUTTON_TOKENS if len(tok) >= 5)
        return False

    @staticmethod
    def _is_chat_or_hud_noise(b: Dict[str, Any]) -> bool:
        t = b["text"].strip()
        if CHAT_LINE_RE.search(t):
            return True
        n = b["norm"]
        if n in ("general", "combat", "ims", "say", "readaloud", "x", "freepeoples", "freievolker", "peupleslibres"):
            return True
        return False

    @classmethod
    def _merge_same_line_fragments(cls, boxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merges horizontally split word fragments on the same text line (e.g. wide small-caps titles)."""
        if len(boxes) < 2:
            return boxes

        boxes_by_y = sorted(boxes, key=lambda b: (b["center_y"], b["x_min"]))
        used = [False] * len(boxes_by_y)
        merged: List[Dict[str, Any]] = []

        for i, cur in enumerate(boxes_by_y):
            if used[i]:
                continue
            cur = dict(cur)
            used[i] = True

            # Do not merge standalone UI controls/anchors with neighbors
            cur_is_ctrl = (
                cls._is_dialog_btn(cur)
                or cls._is_level_meta(cur)
                or cls._is_objective_hdr(cur)
                or cls._is_hud_alert(cur)
            )
            if not cur_is_ctrl:
                changed = True
                while changed:
                    changed = False
                    for j in range(len(boxes_by_y)):
                        if used[j]:
                            continue
                        nxt = boxes_by_y[j]
                        if (
                            cls._is_dialog_btn(nxt)
                            or cls._is_level_meta(nxt)
                            or cls._is_objective_hdr(nxt)
                            or cls._is_hud_alert(nxt)
                        ):
                            continue
                        min_h = min(cur["h"], nxt["h"])
                        max_h = max(cur["h"], nxt["h"])
                        if (min_h / float(max_h)) >= 0.70 and abs(cur["center_y"] - nxt["center_y"]) <= min_h * 0.42:
                            # Merge only tight word gaps on the exact same baseline (never jump across columns)
                            if -min_h * 0.25 <= (nxt["x_min"] - cur["x_max"]) <= min_h * 1.35:
                                combined_text = f"{cur['text']} {nxt['text']}".strip()
                            elif -min_h * 0.25 <= (cur["x_min"] - nxt["x_max"]) <= min_h * 1.35:
                                combined_text = f"{nxt['text']} {cur['text']}".strip()
                            else:
                                continue

                            x1 = min(cur["x_min"], nxt["x_min"])
                            y1 = min(cur["y_min"], nxt["y_min"])
                            x2 = max(cur["x_max"], nxt["x_max"])
                            y2 = max(cur["y_max"], nxt["y_max"])
                            cur = {
                                "text": combined_text,
                                "norm": normalize_text_for_matching(combined_text),
                                "conf": min(cur["conf"], nxt["conf"]),
                                "x_min": x1,
                                "y_min": y1,
                                "x_max": x2,
                                "y_max": y2,
                                "w": x2 - x1,
                                "h": y2 - y1,
                                "center_x": (x1 + x2) / 2.0,
                                "center_y": (y1 + y2) / 2.0,
                            }
                            used[j] = True
                            changed = True
            merged.append(cur)

        merged.sort(key=lambda b: (b["y_min"], b["x_min"]))
        return merged

    def _detect_and_recognize(
        self,
        img,
        max_det_width: int = 1920,
        filter_cpu_hud: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Runs fast downscaled text detection + zero-copy native-resolution axis-aligned box cropping
        + batch text recognition. Avoids RapidOCR's slow per-box full-4K cv2.warpPerspective overhead.
        """
        import cv2
        import numpy as np

        img = np.ascontiguousarray(img)
        h, w = img.shape[:2]
        if h < 12 or w < 20:
            return []

        ocr = self._init_ocr()

        if w > max_det_width:
            scale = max_det_width / float(w)
            det_w = max_det_width
            det_h = max(16, int(round(h * scale)))
            det_img = cv2.resize(img, (det_w, det_h), interpolation=cv2.INTER_LINEAR)
            sx = w / float(det_w)
            sy = h / float(det_h)
        else:
            det_img = img
            sx = 1.0
            sy = 1.0

        dt_boxes, _ = ocr.text_detector(det_img)
        if dt_boxes is None or len(dt_boxes) == 0:
            return []

        raw_coords = []
        crops = []
        pad = 2
        for pts in dt_boxes:
            x1 = max(0, int(min(p[0] for p in pts) * sx) - pad)
            y1 = max(0, int(min(p[1] for p in pts) * sy) - pad)
            x2 = min(w, int(max(p[0] for p in pts) * sx) + pad)
            y2 = min(h, int(max(p[1] for p in pts) * sy) + pad)
            bw = x2 - x1
            bh = y2 - y1
            if bh < 8 or bw < 10:
                continue
            # On CPU-only systems, skip obvious bottom-left chat lines during full-screen scan
            if filter_cpu_hud and not self._ocr_on_cuda and len(dt_boxes) > 25:
                if x2 < w * 0.27 and y1 > h * 0.65:
                    continue
            raw_coords.append((x1, y1, x2, y2))
            crops.append(np.ascontiguousarray(img[y1:y2, x1:x2]))

        if not crops:
            return []

        rec_res, _ = ocr.text_recognizer(crops)
        boxes: List[Dict[str, Any]] = []
        for (x1, y1, x2, y2), (text, score) in zip(raw_coords, rec_res):
            conf = float(score)
            t = text.strip()
            if conf < 0.50 or not t:
                continue
            boxes.append(
                {
                    "text": t,
                    "norm": normalize_text_for_matching(t),
                    "conf": conf,
                    "x_min": x1,
                    "y_min": y1,
                    "x_max": x2,
                    "y_max": y2,
                    "w": x2 - x1,
                    "h": y2 - y1,
                    "center_x": (x1 + x2) / 2.0,
                    "center_y": (y1 + y2) / 2.0,
                }
            )

        return self._merge_same_line_fragments(boxes)

    def scan_screen_with_cache(self, full_screen_img, target_npc: str = "", lang: str = "de") -> Dict[str, Any]:
        """
        Scans using cached title-strip geometry first (~0.03s) when the dialog stays at the same position.
        Automatically detects moved/closed windows and falls back to full-screen anchor scan (~0.20s).
        """
        import numpy as np
        from PIL import Image

        if isinstance(full_screen_img, Image.Image):
            full_screen_img = np.array(full_screen_img)

        h, w = full_screen_img.shape[:2]

        # 1. Fast-Path: Check cached Title Bar + Quest Level strip (~30ms)
        if self.cached_title_strip and self.cached_window_box:
            sx1, sy1, sx2, sy2 = self.cached_title_strip
            sx1, sy1 = max(0, sx1), max(0, sy1)
            sx2, sy2 = min(w, sx2), min(h, sy2)

            if sx2 - sx1 > 80 and sy2 - sy1 > 25:
                strip_crop = full_screen_img[sy1:sy2, sx1:sx2]
                strip_boxes = self._detect_and_recognize(strip_crop, max_det_width=1920)

                if strip_boxes and not any(self._is_hud_alert(b) for b in strip_boxes):
                    has_level_meta = any(self._is_level_meta(b) for b in strip_boxes)
                    # Check dark dialog header background so floating world text over bright terrain doesn't spoof cache
                    dark_header_bg = float(strip_crop.mean()) < 95.0

                    for b in strip_boxes:
                        if self._is_level_meta(b) or self._is_objective_hdr(b) or self._is_dialog_btn(b) or self._is_chat_or_hud_noise(b):
                            continue
                        clean_t = re.sub(r"^[^\w\s]+|[^\w\s]+$", "", b["text"]).strip()
                        if len(b["norm"]) < 3:
                            continue

                        is_inst = bool(re.search(r"^(INSTANZ|INSTANCE)\b", clean_t, re.IGNORECASE))
                        if self.db_path.exists() and (has_level_meta or is_inst or dark_header_bg):
                            q_id, db_title, db_text = self._match_title_in_db(clean_t, target_npc=target_npc, lang=lang)
                            if db_text:
                                final_title = db_title or clean_t
                                print(f"[LotroScreenReader] Fast-path DB hit on cached title: '{final_title}' ({lang.upper()})")
                                return {
                                    "window_type": "instance" if is_inst else "quest",
                                    "title": final_title,
                                    "dialog_text": db_text,
                                    "db_text": db_text,
                                    "final_text": db_text,
                                    "quest_id": q_id,
                                    "window_box": self.cached_window_box,
                                }

                    # If dialog header anchors are still at the cached position (e.g. non-DB dynamic/instance dialog),
                    # scan only the cached dialog panel instead of the entire 4K screen
                    if has_level_meta or any(re.search(r"^(INSTANZ|INSTANCE)\b", b["text"], re.IGNORECASE) for b in strip_boxes):
                        wx1, wy1, wx2, wy2 = self.cached_window_box
                        pad = 25
                        cx1, cy1 = max(0, wx1 - pad), max(0, wy1 - pad)
                        cx2, cy2 = min(w, wx2 + pad), min(h, wy2 + pad)
                        res = self._scan_array(
                            full_screen_img[cy1:cy2, cx1:cx2],
                            target_npc=target_npc,
                            lang=lang,
                            require_anchors=False,
                            offset=(cx1, cy1),
                        )
                        if res.get("final_text") and res.get("title"):
                            return res

            # Dialog was moved or closed -> invalidate stale cache before full-screen scan
            self.cached_window_box = None
            self.cached_title_strip = None

        # 2. Full-Screen Anchor-Verified Scan (~0.18s - 0.30s on GPU)
        res = self._scan_array(
            full_screen_img,
            target_npc=target_npc,
            lang=lang,
            require_anchors=True,
            offset=(0, 0),
        )
        if res.get("final_text") and res.get("window_box") and res.get("_title_strip"):
            self.cached_window_box = res["window_box"]
            self.cached_title_strip = res.pop("_title_strip")
            print(f"[LotroScreenReader] Cached dialog window geometry: {self.cached_window_box}")
        else:
            res.pop("_title_strip", None)
        return res

    def scan_image(self, image_input, target_npc: str = "", lang: str = "de") -> Dict[str, Any]:
        """
        Scans a window image or file path using RapidOCR.
        Supports PIL.Image, numpy.ndarray, file path str/Path, or bytes.
        """
        import numpy as np
        from PIL import Image

        if isinstance(image_input, (str, Path)):
            img = np.array(Image.open(image_input).convert("RGB"))[:, :, ::-1]
        elif isinstance(image_input, bytes):
            import io
            img = np.array(Image.open(io.BytesIO(image_input)).convert("RGB"))[:, :, ::-1]
        elif isinstance(image_input, Image.Image):
            img = np.array(image_input.convert("RGB"))[:, :, ::-1]
        else:
            img = image_input

        h, w = img.shape[:2]
        # Full 16:9 / ultrawide screens (or >=1800px desktop captures) use anchor verification;
        # standalone pre-cropped dialog panels (~1.44 aspect ratio, <1700px wide) allow relaxed matching.
        is_full_desktop = (w >= 1800 and h >= 950) or (w >= 960 and (w / float(max(1, h))) >= 1.68)
        res = self._scan_array(
            img,
            target_npc=target_npc,
            lang=lang,
            require_anchors=is_full_desktop,
            offset=(0, 0),
        )
        res.pop("_title_strip", None)
        return res

    def _scan_array(
        self,
        img,
        target_npc: str = "",
        lang: str = "de",
        require_anchors: bool = True,
        offset: Tuple[int, int] = (0, 0),
    ) -> Dict[str, Any]:
        empty_res = {
            "window_type": "unknown",
            "title": "",
            "dialog_text": "",
            "db_text": None,
            "final_text": "",
            "quest_id": None,
            "window_box": None,
        }

        h, w = img.shape[:2]
        boxes = self._detect_and_recognize(img, max_det_width=1920, filter_cpu_hud=require_anchors)
        if not boxes:
            return empty_res

        # Identify Chat Window bounding region (if 2+ chat lines exist) to prevent wrapped chat continuation lines
        chat_boxes = [b for b in boxes if CHAT_LINE_RE.search(b["text"]) and not re.search(r"\b\d+\s*FPS\b", b["text"], re.IGNORECASE)]
        chat_rect = None
        if require_anchors and len(chat_boxes) >= 2:
            chat_rect = (
                min(cb["x_min"] for cb in chat_boxes) - 15,
                min(cb["y_min"] for cb in chat_boxes) - 35,
                max(cb["x_max"] for cb in chat_boxes) + 40,
                max(cb["y_max"] for cb in chat_boxes) + 35,
            )

        def is_inside_chat(bx: Dict[str, Any]) -> bool:
            if not chat_rect:
                return False
            return chat_rect[0] <= bx["center_x"] <= chat_rect[2] and chat_rect[1] <= bx["center_y"] <= chat_rect[3]

        hud_alerts = [b for b in boxes if self._is_hud_alert(b)]
        level_boxes = [b for b in boxes if self._is_level_meta(b) and not is_inside_chat(b)]
        obj_boxes = [b for b in boxes if self._is_objective_hdr(b) and not is_inside_chat(b)]
        btn_boxes = [b for b in boxes if self._is_dialog_btn(b) and not is_inside_chat(b)]

        best_candidate = None
        best_score = -1e9

        for b in boxes:
            if (
                self._is_hud_alert(b)
                or self._is_level_meta(b)
                or self._is_objective_hdr(b)
                or self._is_dialog_btn(b)
                or self._is_chat_or_hud_noise(b)
                or is_inside_chat(b)
            ):
                continue
            if len(b["norm"]) < 3:
                continue

            # Hard-reject ONLY the badge subtitle directly touching a 'QUEST AVAILABLE' HUD ring alert
            is_under_alert = False
            for al in hud_alerts:
                gap_y = b["y_min"] - al["y_max"]
                if -al["h"] * 0.5 <= gap_y <= max(28.0, al["h"] * 1.25) and abs(
                    b["center_x"] - al["center_x"]
                ) <= max(90.0, al["w"] * 0.55):
                    is_under_alert = True
                    break
            if is_under_alert:
                continue

            tx = b["center_x"]
            half_w = max(b["w"] * 1.4, min(w * 0.25, 800.0)) if require_anchors else w * 0.55
            max_win_h = max(b["h"] * 30.0, h * 0.65) if require_anchors else float(h)

            win_left_est = max(0.0, tx - half_w)
            win_right_est = min(float(w), tx + half_w)

            # A dialog title bar is ALWAYS at the top of its dialog: reject if a QUEST LEVEL or NEXT OBJECTIVE
            # header sits right above candidate b inside the same horizontal window
            has_header_above = any(
                win_left_est <= hdr["center_x"] <= win_right_est
                and 0 < (b["y_min"] - hdr["y_min"]) <= max_win_h * 0.85
                for hdr in (level_boxes + obj_boxes)
            )
            if has_header_above:
                continue

            # Also reject floating HUD/tracker text far above a dialog whose actual headers sit much lower
            has_distant_dialog_below = any(
                win_left_est <= hdr["center_x"] <= win_right_est
                and max(240.0, b["h"] * 8.5) < (hdr["y_min"] - b["y_min"]) <= max_win_h
                for hdr in (level_boxes + obj_boxes)
            )
            if require_anchors and has_distant_dialog_below:
                continue

            local_levels = [
                a for a in level_boxes
                if win_left_est <= a["center_x"] <= win_right_est
                and 0 <= a["y_min"] - b["y_min"] <= max(130.0, b["h"] * 4.5)
            ]
            local_objs = [
                a for a in obj_boxes
                if tx - b["w"] * 0.35 <= a["center_x"] <= win_right_est
                and 0 < a["y_min"] - b["y_min"] <= max(240.0, b["h"] * 8.5)
            ]
            local_btns = [
                a for a in btn_boxes
                if win_left_est <= a["center_x"] <= win_right_est
                and b["h"] * 4.0 < a["y_min"] - b["y_min"] <= max_win_h
            ]

            # Determine vertical and horizontal bounds of left-column dialogue text for this candidate
            body_top = max([b["y_max"]] + [a["y_max"] for a in local_levels])
            body_bottom = min([a["y_min"] for a in local_btns]) if local_btns else min(float(h), b["y_min"] + max_win_h * 0.88)
            right_split_x = min([a["x_min"] for a in local_objs]) - 10.0 if local_objs else (tx + half_w * 0.18 if require_anchors else w * 0.58)

            body_lines = [
                ln for ln in boxes
                if ln is not b
                and not self._is_hud_alert(ln)
                and not self._is_level_meta(ln)
                and not self._is_objective_hdr(ln)
                and not self._is_dialog_btn(ln)
                and not self._is_chat_or_hud_noise(ln)
                and not is_inside_chat(ln)
                and ln["y_min"] >= body_top - 4
                and ln["y_max"] <= body_bottom + 4
                and ln["x_min"] >= win_left_est - 20
                and ln["center_x"] < right_split_x
            ]

            is_inst_prefix = bool(re.search(r"^(INSTANZ|INSTANCE)\b", b["text"], re.IGNORECASE))

            # Check coherent left-aligned paragraph structure (3+ lines aligned on left margin)
            has_aligned_paragraph = False
            if len(body_lines) >= 4:
                x_mins = sorted(ln["x_min"] for ln in body_lines[:6])
                if (x_mins[-1] - x_mins[0]) <= 35:
                    has_aligned_paragraph = True

            # On full-screen scans, strictly require at least one genuine LOTRO Dialog UI control/header anchor
            has_dialog_anchor = bool(local_levels or local_objs or local_btns or is_inst_prefix)
            if require_anchors and not has_dialog_anchor:
                continue

            # Score candidate
            score = 0.0
            if local_levels:
                min_dy = min(a["y_min"] - b["y_max"] for a in local_levels)
                score += 140.0 - max(0.0, min_dy) * 0.5
            if local_objs:
                min_obj_dy = min(a["y_min"] - b["y_max"] for a in local_objs)
                score += 120.0 - max(0.0, min_obj_dy) * 0.25
            if local_btns:
                score += 90.0
            if is_inst_prefix:
                score += 110.0
            if has_aligned_paragraph:
                score += 45.0
            elif len(body_lines) >= 1:
                score += min(30.0, len(body_lines) * 8.0)

            # Penalize if another non-noise box sits between candidate b and the dialog's level/objective header
            anchor_top_y = min(
                [a["y_min"] for a in local_levels] + [a["y_min"] for a in local_objs] + [body_top + 1000.0]
            )
            intervening = sum(
                1 for other in boxes
                if other is not b
                and b["y_max"] < other["y_min"]
                and other["y_max"] < anchor_top_y
                and win_left_est <= other["center_x"] <= win_right_est
            )
            score -= intervening * 60.0

            clean_t = re.sub(r"^[^\w\s]+|[^\w\s]+$", "", b["text"]).strip()
            q_id, db_title, db_text = (None, None, None)
            if self.db_path.exists():
                q_id, db_title, db_text = self._match_title_in_db(clean_t, target_npc=target_npc, lang=lang)
                if db_text:
                    score += 160.0

            # Never select a window candidate that yields zero readable text (neither DB match nor body lines)
            if not db_text and not body_lines:
                continue

            # In pre-cropped standalone dialog mode, favor top-center box
            if not require_anchors and b["y_min"] < h * 0.20 and 0.15 * w < tx < 0.85 * w:
                score += 80.0

            if score > best_score:
                best_score = score
                best_candidate = (b, clean_t, local_levels, local_objs, local_btns, body_lines, q_id, db_title, db_text)

        if best_candidate is None:
            return empty_res

        title_box, clean_title, local_levels, local_objs, local_btns, body_lines, q_id, db_title, db_text = best_candidate
        final_title = db_title or clean_title
        is_instance = bool(re.search(r"^(INSTANZ|INSTANCE)\b", final_title, re.IGNORECASE))
        window_type = "instance" if is_instance else "quest"

        # Sort and clean left-column OCR dialogue lines
        body_lines.sort(key=lambda ln: ln["y_min"])
        cleaned_dialog_lines = []
        for ln in body_lines:
            t = ln["text"]
            if lang.lower() == "de":
                t = re.sub(r"^['\"]?[TtIil][ce]h\b", "'Ich", t)
                t = re.sub(r"\bStraBe\b", "Straße", t)
                t = re.sub(r"\bZahesten\b", "Zähesten", t)
            cleaned_dialog_lines.append(t)

        dialog_text = "\n\n".join(cleaned_dialog_lines)
        final_text = db_text if db_text else dialog_text

        # Compute tight dialog window bounding box strictly from THIS dialog's constituent boxes
        dialog_constituents = [title_box] + local_levels + local_objs + local_btns + body_lines
        ox, oy = offset
        win_x1 = int(min(c["x_min"] for c in dialog_constituents)) + ox
        win_y1 = int(min(c["y_min"] for c in dialog_constituents)) + oy
        win_x2 = int(max(c["x_max"] for c in dialog_constituents)) + ox
        win_y2 = int(max(c["y_max"] for c in dialog_constituents)) + oy
        # Ensure horizontal width covers full two-column dialog around centered title
        est_half = int(max((win_x2 - win_x1) * 0.52, title_box["w"] * 1.15, 320))
        t_cx = int(title_box["center_x"]) + ox
        win_x1 = max(0, min(win_x1, t_cx - est_half))
        win_x2 = max(win_x2, t_cx + est_half)

        window_box = (win_x1, win_y1, win_x2, win_y2)
        title_strip = (
            max(0, win_x1 - 20),
            max(0, int(title_box["y_min"]) + oy - 25),
            win_x2 + 20,
            int(title_box["y_max"] + title_box["h"] * 3.4) + oy + 20,
        )

        return {
            "window_type": window_type,
            "title": final_title,
            "dialog_text": dialog_text,
            "db_text": db_text,
            "final_text": final_text,
            "quest_id": q_id,
            "window_box": window_box,
            "_title_strip": title_strip,
        }

    def _match_title_in_db(
        self, title: str, target_npc: str = "", lang: str = "de"
    ) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        """
        Matches a candidate title against the in-memory quest index (~0.1ms)
        and fetches full quest dialogue text from lotro.db (~1ms).
        Returns (quest_id, matched_db_title, quest_text).
        """
        if not self.db_path.exists():
            return None, None, None

        self._init_quest_index()
        norm_query = normalize_text_for_matching(title)
        if not norm_query or len(norm_query) < 3:
            return None, None, None

        lang_clean = lang.lower().strip()
        if lang_clean not in ("en", "de", "fr", "es"):
            lang_clean = "en"

        lang_order = [lang_clean] + [l for l in ("en", "de", "fr", "es") if l != lang_clean]
        candidate_matches: List[Tuple[int, str]] = []

        # 1. O(1) Exact normalized match on preferred language, then fallback languages
        for l_key in lang_order:
            exact = self._exact_titles.get(l_key, {}).get(norm_query)
            if exact:
                candidate_matches = list(exact)
                break

        # 2. Length-guarded substring match (handles slight OCR edge clipping without false-matching short words)
        if not candidate_matches and len(norm_query) >= 6:
            qlen = len(norm_query)
            best_len = 0
            for l_key in lang_order:
                for norm_t, tlen, _, qid, raw_t in self._all_titles.get(l_key, ()):
                    if tlen < 6:
                        continue
                    ratio = (qlen / float(tlen)) if qlen <= tlen else (tlen / float(qlen))
                    if ratio >= 0.75 and (norm_query in norm_t or norm_t in norm_query):
                        if tlen > best_len:
                            best_len = tlen
                            candidate_matches = [(qid, raw_t)]
                        elif tlen == best_len:
                            candidate_matches.append((qid, raw_t))
                if candidate_matches:
                    break

        # 3. Trigram-filtered fuzzy match (~1.5ms) for small-caps OCR substitutions (e.g. 'YOURSFLF' -> 'YOURSELF')
        if not candidate_matches and len(norm_query) >= 6:
            qlen = len(norm_query)
            q_tri = self._trigrams(norm_query)
            min_shared = max(1, int(len(q_tri) * 0.42))
            max_len_diff = max(3, int(qlen * 0.25))
            best_sim = 0.835
            for l_key in lang_order:
                for norm_t, tlen, t_tri, qid, raw_t in self._all_titles.get(l_key, ()):
                    if abs(tlen - qlen) > max_len_diff:
                        continue
                    if len(q_tri & t_tri) < min_shared:
                        continue
                    sim = SequenceMatcher(None, norm_query, norm_t).ratio()
                    if sim > best_sim + 1e-6:
                        best_sim = sim
                        candidate_matches = [(qid, raw_t)]
                    elif abs(sim - best_sim) <= 1e-6:
                        candidate_matches.append((qid, raw_t))
                if candidate_matches:
                    break

        if not candidate_matches:
            return None, None, None

        # Resolve quest text (preferring the quest ID associated with target_npc when duplicate titles exist)
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            text_col = f"text_{lang_clean}"

            if target_npc:
                for qid, raw_t in candidate_matches:
                    cur.execute(
                        f"""
                        SELECT qt.{text_col}, qt.text_en
                        FROM Quest_Texts qt
                        JOIN NPCs n ON qt.npc_id = n.id
                        WHERE qt.quest_id = ? AND (
                            LOWER(COALESCE(n.name_de, '')) = LOWER(?) OR
                            LOWER(COALESCE(n.name_en, '')) = LOWER(?) OR
                            LOWER(COALESCE(n.name_fr, '')) = LOWER(?) OR
                            LOWER(COALESCE(n.name_es, '')) = LOWER(?)
                        )
                        LIMIT 1
                        """,
                        (qid, target_npc, target_npc, target_npc, target_npc),
                    )
                    npc_row = cur.fetchone()
                    if npc_row and (npc_row[0] or npc_row[1]):
                        conn.close()
                        return qid, raw_t, self._format_player_placeholders(npc_row[0] or npc_row[1], lang_clean)

            for qid, raw_t in candidate_matches:
                cur.execute(
                    f"""
                    SELECT {text_col}, text_en FROM Quest_Texts
                    WHERE quest_id = ? AND text_type IN ('bestower', 'dialog', 'description')
                    ORDER BY CASE text_type
                        WHEN 'bestower' THEN 1
                        WHEN 'dialog' THEN 2
                        ELSE 3 END
                    LIMIT 1
                    """,
                    (qid,),
                )
                text_row = cur.fetchone()
                if text_row and (text_row[0] or text_row[1]):
                    conn.close()
                    return qid, raw_t, self._format_player_placeholders(text_row[0] or text_row[1], lang_clean)

            conn.close()
        except Exception as e:
            print(f"[LotroScreenReader] DB lookup error: {e}", file=sys.stderr)

        return None, None, None

    def get_quest_text_by_id(self, quest_id: int, target_npc: str = "", lang: str = "en") -> Optional[str]:
        """Fetches quest dialogue directly by quest_id for cross-language native DB lookups."""
        if not self.db_path.exists() or not quest_id:
            return None
        lang_clean = lang.lower().strip()
        if lang_clean not in ("en", "de", "fr", "es"):
            lang_clean = "en"
        text_col = f"text_{lang_clean}"
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            if target_npc:
                cur.execute(
                    f"""
                    SELECT qt.{text_col}, qt.text_en
                    FROM Quest_Texts qt
                    JOIN NPCs n ON qt.npc_id = n.id
                    WHERE qt.quest_id = ? AND (
                        LOWER(COALESCE(n.name_de, '')) = LOWER(?) OR
                        LOWER(COALESCE(n.name_en, '')) = LOWER(?) OR
                        LOWER(COALESCE(n.name_fr, '')) = LOWER(?) OR
                        LOWER(COALESCE(n.name_es, '')) = LOWER(?)
                    )
                    LIMIT 1
                    """,
                    (quest_id, target_npc, target_npc, target_npc, target_npc),
                )
                row = cur.fetchone()
                if row and (row[0] or row[1]):
                    conn.close()
                    return self._format_player_placeholders(row[0] or row[1], lang_clean)

            cur.execute(
                f"""
                SELECT {text_col}, text_en FROM Quest_Texts
                WHERE quest_id = ? AND text_type IN ('bestower', 'dialog', 'description')
                ORDER BY CASE text_type
                    WHEN 'bestower' THEN 1
                    WHEN 'dialog' THEN 2
                    ELSE 3 END
                LIMIT 1
                """,
                (quest_id,),
            )
            row = cur.fetchone()
            conn.close()
            if row and (row[0] or row[1]):
                return self._format_player_placeholders(row[0] or row[1], lang_clean)
        except Exception as e:
            print(f"[LotroScreenReader] DB ID lookup error: {e}", file=sys.stderr)
        return None

    def _lookup_quest_in_db(
        self, title: str, target_npc: str = "", lang: str = "de"
    ) -> Tuple[Optional[int], Optional[str]]:
        """Queries lotro.db for best matching quest title and fetches bestower text in requested language."""
        q_id, _, db_text = self._match_title_in_db(title, target_npc=target_npc, lang=lang)
        return q_id, db_text

    @staticmethod
    def _format_player_placeholders(text_candidate: str, lang_clean: str) -> str:
        text = re.sub(r"\$\{PLAYERNAME:([^\[\|]+)[^}]*\}", r"\1", text_candidate)
        default_friend = (
            "friend"
            if lang_clean in ("en", "it")
            else ("ami" if lang_clean == "fr" else ("amigo" if lang_clean == "es" else "Freund"))
        )
        text = re.sub(r"\$\{PLAYER[^}]*\}", default_friend, text)
        return text.strip()
