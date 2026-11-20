# -*- coding: utf-8 -*-
"""
Production LOTRO-TTS Speaker Engine
Uses local OmniVoice Zero-Shot Voice Cloning on NVIDIA RTX GPU.
Clones speech dynamically from authentic LOTRO reference audio files in voices/{lang}/{category}/.
"""
import os
import re
import sys
import json
import time
import hashlib
import shutil
import sqlite3
import argparse
import random
import unicodedata
import threading
from pathlib import Path
import warnings
import numpy as np
import soundfile as sf
import torch

# Suppress noisy HuggingFace Hub unauthenticated warnings and verbose HTTP logs
os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*")
warnings.filterwarnings("ignore", module="huggingface_hub.*")


def _ensure_ffmpeg_in_path():
    """Ensures pydub/torchaudio find a portable ffmpeg binary (suppresses RuntimeWarning)."""
    exe_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    py_dir = Path(sys.executable).resolve().parent
    candidate_dirs = [py_dir / "Scripts", py_dir]
    for cdir in candidate_dirs:
        if (cdir / exe_name).is_file():
            os.environ["PATH"] = str(cdir) + os.pathsep + os.environ.get("PATH", "")
            return
    if shutil.which("ffmpeg") or shutil.which("avconv"):
        return
    try:
        import imageio_ffmpeg
        src_ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if src_ffmpeg.is_file():
            target_dir = py_dir / "Scripts" if sys.platform.startswith("win") else py_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            dst_ffmpeg = target_dir / exe_name
            if not dst_ffmpeg.exists():
                try:
                    shutil.copy2(src_ffmpeg, dst_ffmpeg)
                except Exception:
                    target_dir = src_ffmpeg.parent
            os.environ["PATH"] = str(target_dir) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


_ensure_ffmpeg_in_path()

try:
    from omnivoice import OmniVoice, VoiceClonePrompt
except ImportError:
    print("Error: omnivoice is not installed. Please install it in the python environment.")
    sys.exit(1)

# Version tag included in audio cache keys so outdated cached clips are invalidated
SPEAKER_ENGINE_VERSION = "v7"


def _norm_npc_key(name: str | None) -> str:
    if not name:
        return ""
    s = str(name).strip().strip("'\"` \t\r\n").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _int_to_words(n: int, lang: str) -> str:
    """Converts non-negative integers 0..999999 into spoken words for DE/EN/FR/ES."""
    if n < 0 or n > 999999:
        return str(n)

    l = (lang or "en").lower().strip()
    if l == "de":
        ones = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
                "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
        tens = ["", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig"]

        def _de(num: int) -> str:
            if num < 20:
                return ones[num]
            if num < 100:
                t, u = divmod(num, 10)
                if u == 0:
                    return tens[t]
                u_str = "ein" if u == 1 else ones[u]
                return f"{u_str}und{tens[t]}"
            if num < 1000:
                h, rem = divmod(num, 100)
                prefix = "ein" if h == 1 else ones[h]
                return f"{prefix}hundert" + (_de(rem) if rem else "")
            th, rem = divmod(num, 1000)
            prefix = "ein" if th == 1 else _de(th)
            return f"{prefix}tausend" + (_de(rem) if rem else "")

        return _de(n)

    if l == "en":
        ones = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
        tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

        def _en(num: int) -> str:
            if num < 20:
                return ones[num]
            if num < 100:
                t, u = divmod(num, 10)
                return tens[t] if u == 0 else f"{tens[t]}-{ones[u]}"
            if num < 1000:
                h, rem = divmod(num, 100)
                return f"{ones[h]} hundred" + (f" {_en(rem)}" if rem else "")
            th, rem = divmod(num, 1000)
            return f"{_en(th)} thousand" + (f" {_en(rem)}" if rem else "")

        return _en(n)

    if l == "fr":
        ones = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
                "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
        tens = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante", "soixante", "quatre-vingt", "quatre-vingt"]

        def _fr(num: int, plural_80: bool = True) -> str:
            if num < 20:
                return ones[num]
            if num < 100:
                t, u = divmod(num, 10)
                if t in (7, 9):
                    u += 10
                if t == 8 and u == 0:
                    return "quatre-vingts" if plural_80 else "quatre-vingt"
                if u == 0:
                    return tens[t]
                if u in (1, 11) and t in (2, 3, 4, 5, 6, 7):
                    return f"{tens[t]} et {ones[u]}"
                return f"{tens[t]}-{ones[u]}"
            if num < 1000:
                h, rem = divmod(num, 100)
                if h == 1:
                    base = "cent"
                elif rem == 0 and plural_80:
                    base = f"{ones[h]} cents"
                else:
                    base = f"{ones[h]} cent"
                return base if rem == 0 else f"{base} {_fr(rem, plural_80)}"
            th, rem = divmod(num, 1000)
            base = "mille" if th == 1 else f"{_fr(th, plural_80=False)} mille"
            return base if rem == 0 else f"{base} {_fr(rem, plural_80)}"

        return _fr(n)

    if l == "es":
        ones = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
                "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve"]
        twenties = ["veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro",
                    "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
        tens = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
        hundreds = ["", "ciento", "doscientos", "trescientos", "cuatrocientos",
                    "quinientos", "seiscientos", "setecientos", "ochocientos", "novecientos"]

        def _es(num: int) -> str:
            if num < 20:
                return ones[num]
            if num < 30:
                return twenties[num - 20]
            if num < 100:
                t, u = divmod(num, 10)
                return tens[t] if u == 0 else f"{tens[t]} y {ones[u]}"
            if num == 100:
                return "cien"
            if num < 1000:
                h, rem = divmod(num, 100)
                return hundreds[h] if rem == 0 else f"{hundreds[h]} {_es(rem)}"
            th, rem = divmod(num, 1000)
            base = "mil" if th == 1 else f"{_es(th)} mil"
            return base if rem == 0 else f"{base} {_es(rem)}"

        return _es(n)

    return str(n)


_GREETING_EXCLAIM_RE = re.compile(
    r"(^|\n|[.!?]\s+)(Hallo|Guten Tag|Guten Morgen|Guten Abend|Seid gegrüßt|Grüße|Willkommen|"
    r"Hello|Greetings|Good day|Good morning|Welcome|Well met|Hail|"
    r"Bonjour|Salut|Bienvenue|Hola|Saludos|Bienvenidos)\s*!+(?=\s+\S)",
    re.IGNORECASE,
)


def _strip_lotro_markup(text: str) -> str:
    """Strips LOTRO UI color tags/escapes and normalizes inline typography while preserving paragraph breaks."""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"</?rgb(?:=[^>]*)?>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = s.replace(r"\q", '"').replace("\u00a0", " ").replace("\u202f", " ")
    s = s.replace("…", "...")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _normalize_dialogue_for_tts(text: str, lang: str = "de") -> str:
    """Applies natural cadence normalization (ellipsis pacing, greeting softening, number expansion)."""
    s = _strip_lotro_markup(text)
    if not s:
        return ""
    s = re.sub(r"\s*\.{3,}\s*", "... ", s)
    s = _GREETING_EXCLAIM_RE.sub(r"\1\2,", s)
    l = (lang or "de").lower().strip()
    if l in ("de", "en", "fr", "es"):
        s = re.sub(r"(?<![\d.,])(\d{1,6})(?![\d.,])", lambda m: _int_to_words(int(m.group(1)), l), s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r" *\n *", "\n", s).strip()


class WarmAudioPlayer:
    """
    Persistent real-time audio stream player. Keeps an active WASAPI/ALSA/PulseAudio
    OutputStream streaming continuous silence when idle, eliminating the 15-40ms stream
    negotiation/open latency when speech chunks arrive. Supports instantaneous thread-safe cancellation.
    """
    def __init__(self, sample_rate=24000):
        import queue
        self.sample_rate = sample_rate
        self.queue = queue.Queue()
        self.stream = None
        self._active = False
        self._current_chunk = None
        self._current_offset = 0
        self._lock = threading.Lock()
        try:
            import sounddevice as sd
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback
            )
            self.stream.start()
            self._active = True
        except Exception:
            self._active = False

    def _callback(self, outdata, frames, time_info, status):
        outdata.fill(0)
        written = 0
        with self._lock:
            while written < frames:
                if self._current_chunk is None:
                    try:
                        self._current_chunk = self.queue.get_nowait()
                        self._current_offset = 0
                    except Exception:
                        break

                chunk = self._current_chunk
                offset = self._current_offset
                needed = frames - written
                avail = len(chunk) - offset
                take = min(needed, avail)
                outdata[written:written + take, 0] = chunk[offset:offset + take]
                written += take
                offset += take
                if offset >= len(chunk):
                    self._current_chunk = None
                    self._current_offset = 0
                else:
                    self._current_offset = offset

    def play(self, data, vol_scale=1.0):
        data = np.asarray(data, dtype=np.float32)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if vol_scale < 0.999:
            data = np.clip(data * vol_scale, -1.0, 1.0)
        self.queue.put(data)

    def stop(self):
        with self._lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except Exception:
                    break
            self._current_chunk = None
            self._current_offset = 0

    def is_playing(self):
        with self._lock:
            return not self.queue.empty() or (self._current_chunk is not None)

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass


LOW_VRAM_THRESHOLD_BYTES = int(6.5 * (1024 ** 3))
LOW_GPU_MODES = frozenset({"low-gpu", "low_gpu", "low-vram", "low_vram", "low-end", "low_end"})


def resolve_compute_profile(
    requested_device=None,
    low_vram_threshold_bytes: int = LOW_VRAM_THRESHOLD_BYTES,
) -> tuple[str, bool, str]:
    """Resolves (torch_device, low_vram, description) and verifies GPU kernel execution."""
    mode = (requested_device or "auto").strip().lower()
    if mode == "cpu":
        return ("cpu", False, "CPU Only (manual)")

    if not torch.cuda.is_available():
        return ("cpu", False, "CPU fallback (CUDA not available)")

    try:
        t = torch.randn(4, 4, device="cuda")
        _ = t @ t
        torch.cuda.synchronize()
        del t
    except Exception as e:
        print(f"[WARNING] GPU acceleration test failed ({e}). Falling back to CPU!")
        return ("cpu", False, f"CPU fallback ({e})")

    gpu_name = "GPU"
    total_vram_bytes = 0
    try:
        props = torch.cuda.get_device_properties(0)
        gpu_name = getattr(props, "name", "GPU") or "GPU"
        total_vram_bytes = int(getattr(props, "total_memory", 0) or 0)
    except Exception:
        pass
    vram_gb = total_vram_bytes / (1024 ** 3) if total_vram_bytes > 0 else 0.0

    if mode in LOW_GPU_MODES:
        desc = (
            f"Low-End GPU ({gpu_name}, {vram_gb:.1f} GB VRAM — manual)"
            if total_vram_bytes > 0
            else f"Low-End GPU ({gpu_name} — manual)"
        )
        return ("cuda", True, desc)

    if mode in ("cuda", "gpu"):
        desc = (
            f"CUDA GPU ({gpu_name}, {vram_gb:.1f} GB VRAM — manual)"
            if total_vram_bytes > 0
            else f"CUDA GPU ({gpu_name} — manual)"
        )
        return ("cuda", False, desc)

    if total_vram_bytes > 0 and total_vram_bytes <= low_vram_threshold_bytes:
        return ("cuda", True, f"Auto -> Low-End GPU ({gpu_name}, {vram_gb:.1f} GB VRAM <= 6.5 GB)")

    desc = (
        f"Auto -> CUDA GPU ({gpu_name}, {vram_gb:.1f} GB VRAM)"
        if total_vram_bytes > 0
        else f"Auto -> CUDA GPU ({gpu_name})"
    )
    return ("cuda", False, desc)


def resolve_compute_device(requested_device=None) -> str:
    """Resolves the PyTorch compute device ('cuda' or 'cpu') and verifies GPU kernel execution."""
    device, _, _ = resolve_compute_profile(requested_device)
    return device


class LotroSpeaker:
    def __init__(
        self,
        voices_dir="data/voices",
        db_path="data/lotro.db",
        device=None,
        narrator_mode: bool = False,
        narrator_voice: str = "man_male_1",
        volume: int = 80,
        speed: int = 100,
        active_lang: str | None = None,
        low_vram: bool | None = None,
        emit_duck_events: bool = False,
        background_precache: bool = True,
    ):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.background_precache = bool(background_precache)
        self.voices_dir = self.base_dir / voices_dir
        self.db_path = self.base_dir / db_path
        self.narrator_mode = bool(narrator_mode)
        self.narrator_voice = str(narrator_voice).strip() if narrator_voice else "man_male_1"
        self.volume = max(0, min(100, int(volume)))
        self.speed = max(50, min(200, int(speed)))
        self.active_lang = active_lang.lower().strip() if active_lang else None
        self._cached_vol_scale = max(0.0, min(1.0, float(self.volume) / 100.0))
        self._cached_speed_factor = max(0.5, min(2.0, float(self.speed) / 100.0))
        cfg_file = self.base_dir / "config.json"
        try:
            self._config_vol_mtime = cfg_file.stat().st_mtime if cfg_file.exists() else None
        except OSError:
            self._config_vol_mtime = None
        self._db_local = threading.local()

        resolved_device, detected_low_vram, profile_desc = resolve_compute_profile(device)
        self.device = resolved_device
        self.low_vram = (bool(low_vram) if low_vram is not None else detected_low_vram) and (self.device == "cuda")
        print(f"Initializing LOTRO-TTS Speaker Engine on [{self.device}] ({profile_desc})...")

        # On AMD ROCm, route convolutions through PyTorch's own kernels instead of MIOpen.
        # MIOpen runs a solver search for every new input shape (each new sentence length),
        # which made synthesis many times slower and caused long pauses and GPU load spikes.
        # NVIDIA/CUDA (cuDNN) is not affected.
        if self.device == "cuda" and getattr(torch.version, "hip", None):
            torch.backends.cudnn.enabled = False
            print("ROCm detected: MIOpen convolution backend disabled (avoids per-shape solver searches).")

        # Initialize audio backend and register WASAPI audio session with OS mixer immediately (0.01s silent warmup)
        try:
            import sounddevice as sd
            sd.play(np.zeros(240, dtype=np.float32), 24000)
            sd.wait()
        except Exception:
            pass

        # Initialize persistent warm audio stream (0ms start delay)
        self._warm_player = WarmAudioPlayer(sample_rate=24000)

        # Load OmniVoice model once (FP16 half-precision on CUDA for 2x faster Tensor Core inference)
        model_dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", torch_dtype=model_dtype)
        if self.device == "cuda" and self.low_vram and getattr(self.model, "audio_tokenizer", None) is not None:
            # Keep FP32 audio_tokenizer (~764 MiB + ~1.3 GiB prompt-encode spike) on CPU;
            # OmniVoice routes encode/decode via self.audio_tokenizer.device.
            audio_tok = self.model.audio_tokenizer
            del self.model.audio_tokenizer
            self.model = self.model.to(self.device)
            self.model.audio_tokenizer = audio_tok
        else:
            self.model = self.model.to(self.device)
        tok_note = " | audio_tokenizer: cpu" if (self.device == "cuda" and self.low_vram) else ""
        print(f"OmniVoice model loaded successfully (dtype: {model_dtype}{tok_note})!")

        # Cache of pre-encoded VoiceClonePrompt objects & reference audio durations
        self._prompt_cache = {}
        self._ref_duration_cache = {}

        # Thread synchronization & playback control
        self._synthesis_lock = threading.Lock()
        self._active_stop_event = threading.Event()
        self._is_speaking_event = threading.Event()
        self.emit_duck_events = bool(emit_duck_events)
        self._duck_active = False
        self._duck_lock = threading.Lock()

        # Pronunciation dictionary (hot-reloaded from data/pronunciation*.json via mtime)
        self.pronunciation_path = self.base_dir / "data" / "pronunciation.json"
        self.pronunciation_custom_path = self.base_dir / "data" / "pronunciation_custom.json"
        self._pronunciation_lock = threading.Lock()
        self._pronunciation_mtimes = None
        self._pronunciation_compiled = {}

        # Load voice indexes for all supported native voice libraries (de, en, fr)
        self.indices = {}
        self.by_voice_id = {}
        self.by_npc_name = {}
        for lang in ["de", "en", "fr"]:
            idx_file = self.voices_dir / lang / "voice_index.json"
            if idx_file.exists():
                with open(idx_file, "r", encoding="utf-8") as f:
                    items = json.load(f)
                # Index files store Windows-style relative paths (e.g. 'fr\man_male\x.ogg');
                # use '/' so they resolve on Linux too (Windows accepts both separators)
                for it in items:
                    if isinstance(it.get("audio_file"), str):
                        it["audio_file"] = it["audio_file"].replace("\\", "/")
                self.indices[lang] = items
                self.by_voice_id[lang] = {it["voice_id"]: it for it in items}
                name_map = {}
                for it in items:
                    if it.get("npc_name"):
                        k = _norm_npc_key(it["npc_name"])
                        if k:
                            name_map[k] = it
                    for nname in it.get("verified_npc_names", []):
                        k = _norm_npc_key(nname)
                        if k and k not in name_map:
                            name_map[k] = it
                self.by_npc_name[lang] = name_map
            else:
                self.indices[lang] = []
                self.by_voice_id[lang] = {}
                self.by_npc_name[lang] = {}

        # Custom NPC overrides (src/npc/npc_races_custom.json)
        self.custom_races_path = self.base_dir / "src" / "npc" / "npc_races_custom.json"
        self._custom_races_mtime = 0
        self._custom_races_cache = {}

        # Warm up OmniVoice with a silent mini-generation to initialize CUDA kernels & VRAM allocations,
        # and pre-cache default narrator voice prompts so quest dialogues start with 0ms prompt latency.
        self._warmup_engine()

    def _get_target_voice_libraries(self) -> list[str]:
        """Determines which voice libraries to pre-warm based on active_lang."""
        if self.active_lang in ("de", "en", "fr"):
            return [self.active_lang]
        if self.active_lang in ("es", "it", "nl"):
            return ["en"]
        return ["de", "en", "fr"]

    def _get_db_conn(self) -> sqlite3.Connection | None:
        """Returns a persistent thread-local read-only SQLite connection with mmap enabled."""
        if not self.db_path.exists():
            return None
        try:
            st = self.db_path.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

        conn = getattr(self._db_local, "conn", None)
        conn_sig = getattr(self._db_local, "sig", None)
        if conn is not None and conn_sig == sig:
            return conn

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._db_local.conn = None

        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
            conn.execute("PRAGMA mmap_size=268435456;")
        except Exception:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db_local.conn = conn
        self._db_local.sig = sig
        return conn

    def close(self):
        """Closes warm audio player and cached SQLite connection."""
        if hasattr(self, "_warm_player") and self._warm_player:
            self._warm_player.close()
        conn = getattr(self._db_local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._db_local.conn = None

    def _warmup_engine(self):
        """Performs a silent mini-generation to pre-warm CUDA kernels and pre-caches narrator voice prompts."""
        try:
            print(f"Pre-warming TTS engine kernels on [{self.device}]...")
            _ = self.model.generate(
                text="Greetings.",
                language="en",
                num_step=16,
                postprocess_output=False
            )
            # Pre-cache narrator voice prompts for active language(s) so dialogues start with 0ms prompt delay
            narrator_defaults = [("de", "man_male_1"), ("en", "man_male_1"), ("fr", "man_male_15")]
            active_libs = set(self._get_target_voice_libraries())
            for l, narr_id in narrator_defaults:
                if l in active_libs and l in self.indices and narr_id in self.by_voice_id.get(l, {}):
                    cand = self.by_voice_id[l][narr_id]
                    p_path = self.voices_dir / cand["audio_file"]
                    if p_path.exists():
                        ref_l = "fr" if (l == "fr" and cand.get("is_native_french", True)) else ("en" if l != "de" else "de")
                        self._get_voice_prompt_and_duration(narr_id, ref_l, p_path, cand["text"])
            print("TTS engine pre-warmed and narrator voices ready for instant playback!")
            if self.low_vram and self.device == "cuda":
                torch.cuda.empty_cache()
            # Launch background daemon worker to pre-cache frequent voice prompts (0ms encounter latency).
            # Skipped for one-shot CLI runs: the process would exit while the worker is still inside torch.
            if self.background_precache:
                threading.Thread(target=self._background_precache_worker, daemon=True).start()
        except Exception as e:
            print(f"TTS warm-up notice: {e}")

    def _background_precache_worker(self):
        """
        Background daemon thread that pre-computes (or loads from disk cache) VoiceClonePrompt tensors
        for frequently used voices in the active language library.
        Eliminates the ~375ms prompt extraction delay upon first encountering an NPC.
        Yields immediately if user triggers speech synthesis.
        """
        import time

        time.sleep(1.0)
        priority_prefixes = (
            "man_male_", "man_female_", "dwarf_male_", "dwarf_female_",
            "elf_male_", "elf_female_", "hobbit_male_", "hobbit_female_",
            "orc_", "dead_"
        )

        for lang in self._get_target_voice_libraries():
            items = self.indices.get(lang, [])
            for it in items:
                v_id = it.get("voice_id", "")
                try:
                    num = int(v_id.rsplit("_", 1)[-1])
                except (ValueError, IndexError):
                    num = 99
                # Pre-cache top 10 voices per category (instant on repeat runs via disk cache)
                if num > 10:
                    continue
                if not any(v_id.startswith(p) for p in priority_prefixes):
                    continue

                audio_rel = it.get("audio_file")
                if not audio_rel:
                    continue
                audio_path = self.voices_dir / audio_rel
                if not audio_path.exists():
                    continue

                ref_l = "fr" if (lang == "fr" and it.get("is_native_french", True)) else ("en" if lang != "de" else "de")
                cache_key = (ref_l, v_id, str(audio_path), it.get("text", ""))
                if cache_key in self._prompt_cache:
                    continue

                # Yield immediately to user speech synthesis if active
                while self._is_speaking_event.is_set():
                    time.sleep(0.5)

                try:
                    self._get_voice_prompt_and_duration(v_id, ref_l, audio_path, it.get("text", ""))
                except Exception:
                    pass
                time.sleep(0.02)

    def _get_custom_npc_overrides(self) -> dict:
        """Loads or reloads custom NPC overrides from src/npc/npc_races_custom.json if modified."""
        if not self.custom_races_path.exists():
            return {}
        try:
            mtime = self.custom_races_path.stat().st_mtime
            if mtime != self._custom_races_mtime:
                with open(self.custom_races_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                parsed = {}
                for k, v in cdata.items():
                    if str(k).startswith("_"):
                        continue
                    clean_k = str(k).strip().strip("'\"`")
                    norm_k = _norm_npc_key(clean_k)
                    entry = {"race": v} if isinstance(v, str) else v
                    parsed[clean_k] = entry
                    parsed[clean_k.lower()] = entry
                    if norm_k:
                        parsed[norm_k] = entry
                self._custom_races_cache = parsed
                self._custom_races_mtime = mtime
            return self._custom_races_cache
        except Exception as e:
            print(f"[WARN] Could not parse custom NPC overrides from {self.custom_races_path}: {e}")
            return self._custom_races_cache

    @staticmethod
    def _map_race_gender_to_category(race: str | None, gender: str | None) -> tuple[str, str]:
        """Maps canonical or raw race & gender strings to TTS category and gender."""
        race_str = (race or "man").lower().strip()
        gender_str = (gender or "male").lower().strip()
        if "river-maid" in race_str:
            return "elf_female", "female"
        elif "elf" in race_str or "kinta" in race_str:
            r = "elf"
        elif "hobbit" in race_str or "halfling" in race_str or "stoor" in race_str or "river" in race_str:
            r = "hobbit"
        elif "dwarf" in race_str or "stout" in race_str or "zhélruka" in race_str or "zhelruka" in race_str or "temámir" in race_str or "temamir" in race_str:
            r = "dwarf"
        elif "orc" in race_str or "uruk" in race_str or "goblin" in race_str or "ordâkhai" in race_str or "ordakhai" in race_str:
            return "orc", "male"
        elif "troll" in race_str or "giant" in race_str or "rogmul" in race_str:
            return "troll", "male"
        elif "ent" in race_str or "huorn" in race_str:
            return "ent", "neutral"
        elif "dead" in race_str or "shade" in race_str or "wraith" in race_str or "nazgûl" in race_str or "nazgul" in race_str:
            return "dead", "neutral"
        else:
            r = "man"

        g = "female" if gender_str in ("female", "f", "woman") else "male"
        return f"{r}_{g}", g

    def get_npc_info(self, npc_name_or_id):
        """Looks up NPC race, gender, and assigned voice_id from custom overrides and data/lotro.db."""
        custom_overrides = self._get_custom_npc_overrides()
        raw_key = str(npc_name_or_id).strip().strip("'\"`")
        norm_key = _norm_npc_key(raw_key)

        # 1. Direct custom override lookup before DB query
        custom = (
            custom_overrides.get(raw_key)
            or custom_overrides.get(raw_key.lower())
            or (norm_key and custom_overrides.get(norm_key))
        )

        row = None
        conn = self._get_db_conn()
        if conn is not None:
            c = conn.cursor()
            if isinstance(npc_name_or_id, int) or (isinstance(npc_name_or_id, str) and npc_name_or_id.isdigit()):
                c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE id = ?", (int(npc_name_or_id),))
                row = c.fetchone()
            else:
                name_query = raw_key
                c.execute(
                    "SELECT name_en, race, gender, voice_id FROM NPCs "
                    "WHERE LOWER(name_en) = LOWER(?) OR LOWER(name_de) = LOWER(?) "
                    "OR LOWER(name_fr) = LOWER(?) OR LOWER(name_es) = LOWER(?) "
                    "ORDER BY CASE WHEN race IS NOT NULL AND length(race) > 0 THEN 0 ELSE 1 END, id ASC LIMIT 1",
                    (name_query, name_query, name_query, name_query)
                )
                row = c.fetchone()
                if not row and len(name_query) >= 4:
                    c.execute(
                        "SELECT name_en, race, gender, voice_id FROM NPCs "
                        "WHERE name_en LIKE ? OR name_de LIKE ? OR name_fr LIKE ? OR name_es LIKE ? "
                        "ORDER BY CASE WHEN race IS NOT NULL AND length(race) > 0 THEN 0 ELSE 1 END, id ASC LIMIT 1",
                        (f"%{name_query}%", f"%{name_query}%", f"%{name_query}%", f"%{name_query}%")
                    )
                    row = c.fetchone()

        if row:
            db_name, db_race, db_gender, db_voice_id = row
            # If not matched earlier, check custom overrides by DB English name
            if not custom and db_name:
                custom = (
                    custom_overrides.get(db_name)
                    or custom_overrides.get(db_name.lower())
                    or custom_overrides.get(_norm_npc_key(db_name))
                )

            name = db_name
            race = custom.get("race") if (custom and custom.get("race")) else db_race
            gender = custom.get("gender") if (custom and custom.get("gender")) else db_gender

            # If voice_id explicitly overridden in custom json, use it;
            # If race or gender were overridden in custom json without explicit voice_id, set voice_id to None
            # so select_voice_template picks dynamically from the new race/gender category pool!
            if custom and custom.get("voice_id"):
                voice_id = custom["voice_id"]
            elif custom and (custom.get("race") or custom.get("gender")):
                voice_id = None
            else:
                voice_id = db_voice_id

            category, g = self._map_race_gender_to_category(race, gender)
            if custom:
                print(f"[CUSTOM NPC OVERRIDE] Applied custom settings for '{name}': category={category}, gender={g}, voice_id={voice_id}")
            return name, category, g, voice_id

        if custom:
            name = custom.get("name") or raw_key
            race = custom.get("race")
            gender = custom.get("gender")
            voice_id = custom.get("voice_id")
            category, g = self._map_race_gender_to_category(race, gender)
            print(f"[CUSTOM NPC OVERRIDE] Applied custom settings for '{name}': category={category}, gender={g}, voice_id={voice_id}")
            return name, category, g, voice_id

        # Diacritic-insensitive fallback via pre-indexed verified NPC names (e.g. 'Gloin' -> 'Glóin', 'Eowyn' -> 'Éowyn')
        if norm_key:
            for l in ("en", "de", "fr"):
                if norm_key in self.by_npc_name.get(l, {}):
                    it = self.by_npc_name[l][norm_key]
                    return raw_key, it.get("category", "man_male"), it.get("gender", "male"), it["voice_id"]

        return raw_key, "narrator", "male", None

    def select_voice_template(self, category, lang="de", seed_key=None, preferred_voice_id=None):
        """Selects reference audio and sidecar transcript for cloning (prioritizing 1:1 NPC voice when available)."""
        # For languages without authentic LOTRO audio samples (e.g. Spanish 'es', Italian 'it', Dutch 'nl'),
        # use the authentic English reference audio pool for cross-lingual zero-shot cloning.
        ref_lang = lang if lang in self.indices and self.indices[lang] else "en"
        lang_items = self.indices.get(ref_lang, [])
        voice_map = self.by_voice_id.get(ref_lang, {})
        npc_map = self.by_npc_name.get(ref_lang, {})

        # 1. Fixed narrator voice for inanimate objects & untargeted narrator texts
        # In French, man_male_15 (Athelward: "Bienvenue à Cléving, ami venu de loin.") is used
        # to ensure a calm, welcoming storyteller voice and avoid Horn's distressed delivery.
        if category == "narrator" and not preferred_voice_id:
            if lang == "fr":
                preferred_voice_id = "man_male_15"
            else:
                preferred_voice_id = "man_male_1"

        # 2. Direct voice_id match from lotro.db (verified voice actor or deterministic category voice)
        if preferred_voice_id and preferred_voice_id in voice_map:
            cand = voice_map[preferred_voice_id]
            cand_path = self.voices_dir / cand["audio_file"]
            if cand_path.exists():
                c_lang = "en" if cand.get("is_native_french") is False else ref_lang
                return cand["voice_id"], cand_path, cand["text"], c_lang

        # 3. Direct verified NPC name match (covers diacritic variants like Gloin -> Glóin)
        if seed_key:
            norm_seed = _norm_npc_key(seed_key)
            if norm_seed in npc_map:
                cand = npc_map[norm_seed]
                cand_path = self.voices_dir / cand["audio_file"]
                if cand_path.exists():
                    c_lang = "en" if cand.get("is_native_french") is False else ref_lang
                    return cand["voice_id"], cand_path, cand["text"], c_lang

        # 4. Category pool lookup
        cat_matches = [it for it in lang_items if it["category"] == category]

        if not cat_matches:
            cat_matches = (
                [it for it in lang_items if it["category"] == "narrator"]
                or [it for it in lang_items if it["category"] == "man_male"]
                or lang_items
            )

        if not cat_matches:
            raise FileNotFoundError(f"No voice templates found for category '{category}' and language '{lang}'")

        # For French, prioritize authentic French LOTRO voice recordings when available in the pool
        if lang == "fr":
            native_matches = [it for it in cat_matches if it.get("is_native_french")]
            if native_matches:
                cat_matches = native_matches

        if seed_key:
            import zlib
            idx = zlib.crc32(str(seed_key).encode("utf-8")) % len(cat_matches)
            selected = cat_matches[idx]
        else:
            selected = random.choice(cat_matches)

        ref_audio_path = self.voices_dir / selected["audio_file"]
        ref_text = selected["text"]
        selected_ref_lang = "en" if selected.get("is_native_french") is False else ref_lang

        return selected["voice_id"], ref_audio_path, ref_text, selected_ref_lang

    def _get_voice_prompt_and_duration(self, voice_id, ref_lang, ref_audio_path, ref_text):
        """
        Builds and caches (RAM + persistent disk cache) the VoiceClonePrompt with
        preprocess_prompt=True for clean voice timbre conditioning without clipping or trailing silence.
        """
        cache_key = (ref_lang, voice_id, str(ref_audio_path), ref_text)
        if cache_key not in self._prompt_cache:
            info = sf.info(str(ref_audio_path))
            self._ref_duration_cache[cache_key] = float(info.duration)

            prompt_dir = self.base_dir / "cache" / "prompts"
            ref_mtime = int(ref_audio_path.stat().st_mtime) if ref_audio_path.exists() else 0
            text_sig = hashlib.md5((ref_text or "").encode("utf-8")).hexdigest()[:8]
            prompt_file = prompt_dir / f"{SPEAKER_ENGINE_VERSION}_{ref_lang}_{voice_id}_{ref_mtime}_{text_sig}.pt"

            prompt = None
            if prompt_file.exists():
                try:
                    prompt_map_loc = "cpu" if self.low_vram else self.device
                    prompt = VoiceClonePrompt.load(str(prompt_file), map_location=prompt_map_loc)
                except Exception:
                    prompt = None

            if prompt is None:
                prompt = self.model.create_voice_clone_prompt(
                    ref_audio=str(ref_audio_path),
                    ref_text=ref_text,
                    preprocess_prompt=True
                )
                try:
                    prompt_dir.mkdir(parents=True, exist_ok=True)
                    tmp_file = prompt_file.with_suffix(f".pt.{os.getpid()}.{threading.get_ident()}.tmp")
                    prompt.save(str(tmp_file))
                    os.replace(tmp_file, prompt_file)
                except Exception:
                    pass

            self._prompt_cache[cache_key] = prompt
        return self._prompt_cache[cache_key], self._ref_duration_cache[cache_key]

    def _estimate_natural_duration(self, text_chunk, ref_text, ref_duration, category="narrator"):
        """
        Calculates a calibrated target duration (in seconds) that prevents both:
        1) Rapid-fire speech / skipped words caused by short or fast reference clips.
        2) Clipped word endings (e.g. 'sprechen' -> 'sprech') caused by running out of frames
           at the end of a sentence.
        """
        estimator = getattr(self.model, "duration_estimator", None)
        if estimator is not None and hasattr(estimator, "calculate_total_weight"):
            target_w = max(float(estimator.calculate_total_weight(text_chunk)), 1.0)
            ref_w = max(float(estimator.calculate_total_weight(ref_text)), 1.0)
        else:
            target_w = max(float(len(text_chunk)), 1.0)
            ref_w = max(float(len(ref_text)), 1.0)

        raw_rate = ref_w / max(ref_duration, 0.8)

        # Clamp speaking rate to a natural storytelling cadence (weight units / sec).
        # Reference clips with >14.5 weight/sec are slowed down so words are articulated clearly.
        if category in ("ent", "dead", "narrator"):
            min_rate, max_rate = 10.5, 13.5
        else:
            min_rate, max_rate = 11.5, 14.2

        effective_rate = max(min_rate, min(raw_rate, max_rate))
        speed_factor = self._get_speed_factor()
        effective_rate *= speed_factor

        # Add generous trailing breath headroom (+0.32s) so final syllables (-en, -er, -t)
        # have full room to decay naturally before the diffusion token window ends.
        est_duration = (target_w / effective_rate) + 0.32
        return max(est_duration, 0.85 / max(speed_factor, 0.75))

    def _trim_raw_chunk(self, audio_tensor, sample_rate=24000):
        """
        Trims leading/trailing digital silence above 0.0032 noise floor and strips isolated
        <=90ms pre-speech onset artifacts followed by >=110ms silence before main speech.
        """
        if hasattr(audio_tensor, "detach"):
            wav = audio_tensor.squeeze().detach().cpu().numpy().astype(np.float32)
        else:
            wav = np.asarray(audio_tensor, dtype=np.float32).squeeze()
        if wav.size == 0:
            return wav

        active = np.where(np.abs(wav) > 0.0032)[0]
        if active.size > 0:
            lead_keep = int(0.06 * sample_rate)
            trail_keep = int(0.19 * sample_rate)
            first_act = int(active[0])
            last_act = int(active[-1])

            # Strip isolated micro-pop at utterance start (e.g. stray reference-boundary consonant before a >110ms pause)
            hop = int(0.01 * sample_rate)
            scan_end = min(wav.size, first_act + int(0.85 * sample_rate))
            if (last_act - first_act) > int(0.40 * sample_rate) and scan_end - first_act >= int(0.22 * sample_rate):
                sub = wav[first_act:scan_end]
                n_bins = sub.size // hop
                if n_bins >= 22:
                    bin_rms = np.sqrt(np.mean(sub[: n_bins * hop].reshape(n_bins, hop) ** 2, axis=1))
                    # Look for a quiet valley of >=11 consecutive 10ms bins (110ms) starting within first 90ms
                    start_gap = None
                    run = 0
                    for b_i in range(n_bins):
                        if bin_rms[b_i] < 0.0025:
                            if run == 0:
                                start_gap = b_i
                            run += 1
                            if run >= 11 and start_gap is not None and start_gap <= 9:
                                pre_peak = float(np.max(np.abs(sub[: max(1, start_gap * hop)])))
                                post_act = np.where(bin_rms[b_i:] >= 0.005)[0]
                                if pre_peak < 0.25 and post_act.size > 0:
                                    first_act = first_act + (b_i + int(post_act[0])) * hop
                                break
                        else:
                            run = 0
                            start_gap = None

            start_idx = max(0, first_act - lead_keep)
            end_idx = min(wav.size, last_act + trail_keep)
            if end_idx > start_idx:
                wav = wav[start_idx:end_idx]
        return wav

    @staticmethod
    def _evaluate_chunk_envelope(wav_trimmed: np.ndarray, expected_text: str, sample_rate: int = 24000) -> tuple[bool, float]:
        """
        Sub-millisecond CPU envelope sanity check (0 extra VRAM, ~0.1ms runtime).
        Detects empty/collapsed chunks, clipped tails, extreme speaking-rate rush (swallowed
        openers/words), severe waveform clipping, and unnatural internal silence gaps.
        Returns (passed, quality_score).
        """
        if wav_trimmed.size < int(0.14 * sample_rate):
            return False, -100.0

        act = np.where(np.abs(wav_trimmed) > 0.005)[0]
        if act.size < int(0.10 * sample_rate):
            return False, -100.0

        a, b = int(act[0]), int(act[-1])
        active_dur = max(0.12, float(b - a) / float(sample_rate))
        tail_n = min(wav_trimmed.size, int(0.030 * sample_rate))
        tail_rms = float(np.sqrt(np.mean(wav_trimmed[-tail_n:] ** 2))) if tail_n > 0 else 0.0
        clip_frac = float(np.mean(np.abs(wav_trimmed[a : b + 1]) > 0.99))

        max_gap_s = 0.0
        hop = int(0.02 * sample_rate)
        n_frames = wav_trimmed.size // hop
        if n_frames >= 5:
            rms_frames = np.sqrt(np.mean(wav_trimmed[: n_frames * hop].reshape(n_frames, hop) ** 2, axis=1))
            act_f = np.where(rms_frames > 0.008)[0]
            if act_f.size >= 3:
                inner = rms_frames[int(act_f[0]) : int(act_f[-1]) + 1] < 0.006
                max_run, cur = 0, 0
                for is_sil in inner:
                    cur = cur + 1 if is_sil else 0
                    if cur > max_run:
                        max_run = cur
                max_gap_s = max_run * 0.02

        body_inner = (expected_text or "").strip()[:-1]
        has_pause_punct = ("..." in expected_text) or ("…" in expected_text) or ("?" in body_inner) or ("!" in body_inner)
        max_allowed_gap = 1.15 if has_pause_punct else 0.90
        tlen = len((expected_text or "").strip())
        cps = float(tlen) / active_dur

        ok = (tail_rms <= 0.048) and (clip_frac <= 0.03) and (max_gap_s <= max_allowed_gap)
        if tlen >= 24 and not (3.5 <= cps <= 24.5):
            ok = False

        score = -tail_rms * 40.0 - clip_frac * 50.0 - max(0.0, max_gap_s - 0.6) * 5.0
        if tlen >= 24:
            score -= max(0.0, cps - 19.0) * 0.8 + max(0.0, 7.0 - cps) * 0.8
        return ok, score

    def _clean_generated_chunk(self, audio_tensor, sample_rate=24000, pretrimmed=False):
        """
        Gentle audio post-processor preserving natural word endings with 60ms lead / 190ms trail,
        15ms cosine fade-in/out, and 80ms inter-sentence pause.
        """
        wav = np.asarray(audio_tensor, dtype=np.float32) if pretrimmed else self._trim_raw_chunk(audio_tensor, sample_rate)
        if wav.size == 0:
            return wav

        fade_len = min(int(0.015 * sample_rate), wav.size // 4)
        if fade_len > 1:
            wav = wav.copy()
            wav[:fade_len] *= np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
            wav[-fade_len:] *= np.linspace(1.0, 0.0, fade_len, dtype=np.float32)

        pad = np.zeros(int(0.08 * sample_rate), dtype=np.float32)
        return np.concatenate([wav, pad])

    @torch.inference_mode()
    def _synthesize_chunk(self, text_chunk, voice_id, ref_lang, ref_audio, ref_text, lang, category, num_step=20):
        """
        Synthesizes a single sentence/chunk using OmniVoice natural speed prediction + t_shift=0.20
        + guidance_scale=2.2, guarded by a sub-ms CPU acoustic envelope check with 1 fast fallback retry.
        """
        prompt, _ = self._get_voice_prompt_and_duration(voice_id, ref_lang, ref_audio, ref_text)
        base_speed = 0.85 if category in ("ent", "dead") else 0.90
        eff_speed = max(0.5, min(2.0, base_speed * self._get_speed_factor()))

        best_trimmed = None
        best_score = -1e9
        for attempt, cur_steps in enumerate((num_step, max(num_step + 4, 24))):
            if attempt > 0 and self._active_stop_event.is_set():
                break
            res = self.model.generate(
                text=text_chunk,
                voice_clone_prompt=prompt,
                language=lang,
                duration=None,
                speed=eff_speed,
                num_step=cur_steps,
                t_shift=0.20,
                guidance_scale=2.2,
                fade_duration=0.0,
                pad_duration=0.0,
                postprocess_output=False,
            )
            trimmed = self._trim_raw_chunk(res[0], sample_rate=24000)
            ok, sc = self._evaluate_chunk_envelope(trimmed, text_chunk, sample_rate=24000)
            if sc > best_score:
                best_score = sc
                best_trimmed = trimmed
            if ok:
                break

        return self._clean_generated_chunk(best_trimmed, sample_rate=24000, pretrimmed=True)

    def _split_dialogue_chunks(self, text: str, lang: str = "de", max_chars: int = 155) -> list[str]:
        """
        Paragraph- and sentence-aware dialogue chunker:
        1. Preserves paragraph breaks so distinct thoughts never slur together.
        2. Never splits inside sentences on commas <= max_chars or ellipses ('...', '…').
        3. Protects honorifics & abbreviations across DE, EN, FR, ES, IT, NL.
        4. Merges only tiny micro-utterances (<= 14 chars, e.g. "Durell?", "Ja.") with adjacent sentences.
        5. Breaks ultra-long sentences (> max_chars) at clause delimiters so time-to-first-sound stays low.
        """
        text = (text or "").strip()
        if not text:
            return []

        text = text.replace("\u00a0", " ").replace("\u202f", " ")
        abbrs = [
            "M.", "Mme.", "Mlle.", "Dr.", "Prof.", "etc.", "cf.", "env.", "p.ex.",
            "z.B.", "d.h.", "u.a.", "bzw.", "ca.", "usw.",
            "Mr.", "Mrs.", "Ms.", "e.g.", "i.e.", "vs.",
            "Sr.", "Sra.", "bijv.", "d.w.z.", "t.a.v."
        ]

        final_chunks = []
        for para in [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]:
            protected = para.replace("...", "___ELLIPSIS___").replace("…", "___ELLIPSIS___")
            for ab in abbrs:
                protected = protected.replace(ab, ab.replace(".", "___DOT___"))
            protected = re.sub(r'([.!?])\s+([»”"\x27])', r'\1\2', protected)

            raw_splits = re.split(r'([.!?]+[\x27\x22\u00bb\u201d]*)\s+(?=[A-ZÀ-ÖØ-ß«“"\x27]|$)', protected)
            parts = []
            if len(raw_splits) == 1:
                parts = [raw_splits[0]]
            else:
                for i in range(0, len(raw_splits) - 1, 2):
                    p = (raw_splits[i] + raw_splits[i + 1]).strip()
                    if p:
                        parts.append(p)
                if len(raw_splits) % 2 == 1 and raw_splits[-1].strip():
                    parts.append(raw_splits[-1].strip())

            restored = [p.replace("___ELLIPSIS___", "...").replace("___DOT___", ".").strip() for p in parts if p.strip()]

            expanded = []
            for sent in restored:
                if len(sent) <= max_chars:
                    expanded.append(sent)
                    continue
                clauses = re.split(r'(?<=[;—–])\s+', sent)
                if len(clauses) == 1 and len(sent) > 200:
                    clauses = re.split(r'(?<=,)\s+', sent)
                buf = ""
                for cl in clauses:
                    cl = cl.strip()
                    if not cl:
                        continue
                    if buf and len(buf) >= 65 and (len(buf) + 1 + len(cl)) > (max_chars + 10):
                        expanded.append(buf)
                        buf = cl
                    else:
                        buf = f"{buf} {cl}".strip() if buf else cl
                if buf:
                    expanded.append(buf)

            merged = []
            i = 0
            while i < len(expanded):
                s = expanded[i].strip()
                if not s:
                    i += 1
                    continue
                if len(s) <= 14 and (i + 1) < len(expanded) and (len(s) + 1 + len(expanded[i + 1])) <= (max_chars + 25):
                    merged.append(f"{s} {expanded[i + 1].strip()}")
                    i += 2
                elif merged and len(s) <= 14 and (len(merged[-1]) + 1 + len(s)) <= (max_chars + 25):
                    merged[-1] = f"{merged[-1]} {s}"
                    i += 1
                else:
                    merged.append(s)
                    i += 1

            final_chunks.extend(merged)

        return final_chunks

    def _set_audio_duck(self, active: bool):
        """Notifies GUI host (when enabled) to duck or restore LOTRO game audio."""
        if not getattr(self, "emit_duck_events", False):
            return
        state = bool(active)
        with self._duck_lock:
            if state == self._duck_active:
                return
            self._duck_active = state
        print(f"[AUDIO_DUCK:{1 if state else 0}]", flush=True)

    @staticmethod
    def _extract_dict_entries(section) -> dict[str, str]:
        if not isinstance(section, dict):
            return {}
        return {
            str(k).strip(): str(v).strip()
            for k, v in section.items()
            if isinstance(k, str)
            and isinstance(v, str)
            and k.strip()
            and v.strip()
            and not k.startswith("_")
        }

    def _get_compiled_pronunciation(self, lang: str = "de"):
        """
        Loads & compiles pronunciation rules from data/pronunciation.json + data/pronunciation_custom.json,
        reloading automatically when either file's modification time changes.
        """
        lang_key = (lang or "de").lower().strip()
        p_base = getattr(self, "pronunciation_path", self.base_dir / "data" / "pronunciation.json")
        p_custom = getattr(self, "pronunciation_custom_path", self.base_dir / "data" / "pronunciation_custom.json")

        try:
            m_base = p_base.stat().st_mtime_ns if p_base.exists() else None
        except OSError:
            m_base = None
        try:
            m_custom = p_custom.stat().st_mtime_ns if p_custom.exists() else None
        except OSError:
            m_custom = None

        cur_mtimes = (m_base, m_custom)
        with self._pronunciation_lock:
            if cur_mtimes != self._pronunciation_mtimes:
                self._pronunciation_compiled.clear()
                self._pronunciation_mtimes = cur_mtimes

            if lang_key in self._pronunciation_compiled:
                return self._pronunciation_compiled[lang_key]

            merged: dict[str, str] = {}
            for path in (p_base, p_custom):
                if not path.exists():
                    continue
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        continue
                    merged.update(self._extract_dict_entries(raw.get("common")))
                    merged.update(self._extract_dict_entries(raw.get(lang_key)))
                except Exception as e:
                    print(f"[WARNING] Could not load pronunciation dictionary '{path.name}': {e}", file=sys.stderr)

            if not merged:
                self._pronunciation_compiled[lang_key] = None
                return None

            # Longest keys first so multi-word names match before prefixes; optional trailing 's' keeps German genitives intact
            sorted_keys = sorted(merged.keys(), key=len, reverse=True)
            alternation = "|".join(re.escape(k) for k in sorted_keys)
            pattern = re.compile(rf"(?<!\w)(?:{alternation})(?=s?(?!\w))", re.IGNORECASE)
            lower_map = {k.lower(): v for k, v in merged.items()}
            compiled = (pattern, lower_map)
            self._pronunciation_compiled[lang_key] = compiled
            return compiled

    def apply_pronunciation(self, text: str, lang: str = "de") -> str:
        """Applies whole-word pronunciation dictionary substitutions right before TTS synthesis."""
        if not text:
            return text
        compiled = self._get_compiled_pronunciation(lang)
        if not compiled:
            return text
        pattern, lower_map = compiled
        return pattern.sub(lambda m: lower_map.get(m.group(0).lower(), m.group(0)), text)

    def stop(self):
        """
        Immediately halts any active speech synthesis and stops audio playback.
        Signals threads to exit and cuts ongoing Windows / Linux sound output.
        """
        if hasattr(self, "_active_stop_event") and self._active_stop_event is not None:
            self._active_stop_event.set()
        if hasattr(self, "_is_speaking_event") and self._is_speaking_event is not None:
            self._is_speaking_event.clear()

        # 1. Instantly stop warm audio player (0ms cut)
        if hasattr(self, "_warm_player") and self._warm_player and self._warm_player._active:
            self._warm_player.stop()

        # 2. Stop sounddevice (Cross-platform: Windows, Linux, macOS)
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

        # 3. Stop winsound (Windows fallback)
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except Exception:
            pass

        self._set_audio_duck(False)

    def is_speaking(self) -> bool:
        """Returns True if speech synthesis or playback is currently in progress."""
        if hasattr(self, "_warm_player") and self._warm_player and self._warm_player._active:
            if self._warm_player.is_playing():
                return True
        return hasattr(self, "_is_speaking_event") and self._is_speaking_event.is_set()

    def speak(
        self,
        text,
        npc_name_or_category="narrator",
        lang="de",
        output_path=None,
        cache_key=None,
        narrator_mode=None,
        narrator_voice=None,
        wait: bool = False,
    ):
        """
        Synthesizes authentic speech for given NPC / category and text.
        Includes persistent disk cache, pronunciation dictionary substitution,
        and sentence-level streaming for instant playback.
        Supports thread-safe instant interruption via stop() and optional single-narrator mode.
        """
        raw_text = (text or "").strip()
        if not raw_text:
            return None

        # Stop any previous playback and reset stop event for this new speech turn
        self.stop()
        self._active_stop_event.clear()
        self._is_speaking_event.set()

        text = _strip_lotro_markup(raw_text) or raw_text
        text = self.apply_pronunciation(text, lang=lang).strip() or text
        text = _normalize_dialogue_for_tts(text, lang=lang) or text

        use_narrator_mode = self.narrator_mode if narrator_mode is None else bool(narrator_mode)
        active_narrator_voice = (narrator_voice or self.narrator_voice or "man_male_1").strip()

        with self._synthesis_lock:
            if self._active_stop_event.is_set():
                self._is_speaking_event.clear()
                self._set_audio_duck(False)
                return None
            try:
                # Determine category & NPC info
                preferred_voice_id = None
                if use_narrator_mode:
                    preferred_voice_id = active_narrator_voice
                    if npc_name_or_category in [
                        "elf_female", "elf_male", "man_female", "man_male",
                        "hobbit_female", "hobbit_male", "dwarf_female", "dwarf_male",
                        "orc", "troll", "ent", "dead", "narrator"
                    ]:
                        npc_name = npc_name_or_category
                    else:
                        npc_name, _, _, _ = self.get_npc_info(npc_name_or_category)

                    # Look up category of active_narrator_voice from index if available
                    ref_l = lang if lang in self.indices and self.indices[lang] else "en"
                    v_info = self.by_voice_id.get(ref_l, {}).get(preferred_voice_id)
                    category = v_info.get("category", "narrator") if v_info else "narrator"
                elif npc_name_or_category in [
                    "elf_female", "elf_male", "man_female", "man_male",
                    "hobbit_female", "hobbit_male", "dwarf_female", "dwarf_male",
                    "orc", "troll", "ent", "dead", "narrator"
                ]:
                    category = npc_name_or_category
                    npc_name = category
                else:
                    npc_name, category, _, preferred_voice_id = self.get_npc_info(npc_name_or_category)

                voice_id, ref_audio, ref_text, ref_lang = self.select_voice_template(
                    category, lang=lang, seed_key=npc_name, preferred_voice_id=preferred_voice_id
                )

                # 1. AUDIO CACHE CHECK
                cache_dir = self.base_dir / "cache" / "audio"
                cache_dir.mkdir(parents=True, exist_ok=True)

                # Refresh live config before hashing so speed slider changes immediately affect cache key
                self._get_speed_factor()
                speed_tag = f"_spd{self.speed}" if self.speed != 100 else ""

                # Include reference audio mtime & transcription hash so modified voices automatically invalidate cache
                ref_mtime = int(ref_audio.stat().st_mtime) if ref_audio.exists() else 0
                ref_text_hash = hashlib.md5((ref_text or "").encode("utf-8")).hexdigest()[:8]
                text_hash = hashlib.md5(
                    f"{SPEAKER_ENGINE_VERSION}_{voice_id}_{ref_audio.name}_{ref_mtime}_{ref_text_hash}_{lang}{speed_tag}_{text}".encode("utf-8")
                ).hexdigest()
                cached_wav = Path(output_path) if output_path else (cache_dir / f"{text_hash}.wav")

                if not output_path and cached_wav.exists() and cached_wav.stat().st_size > 44:
                    print(f"[{lang.upper()}] [AUDIO CACHE HIT] Playing cached audio instantly for '{npc_name}'...")
                    self._set_audio_duck(True)
                    self.play_audio(cached_wav, wait=wait)
                    return cached_wav

                if use_narrator_mode:
                    print(f"[{lang.upper()}] [NARRATOR MODE] Speaking for '{npc_name}' using narrator voice '{voice_id}'...")
                else:
                    print(f"[{lang.upper()}] Speaking for '{npc_name}' as {category} using template {voice_id}...")
                print(f"  Reference audio: {ref_audio.name}")

                if self._active_stop_event.is_set():
                    return None

                # 2. STREAMING OR DIRECT SYNTHESIS
                sentences = self._split_dialogue_chunks(text, lang=lang)

                # If short text (1 sentence and < 140 chars), generate directly and play from RAM immediately
                if len(sentences) <= 1 and len(text) < 140:
                    single_text = sentences[0] if sentences else text
                    audio_data = self._synthesize_chunk(
                        single_text, voice_id, ref_lang, ref_audio, ref_text, lang, category, num_step=20
                    )
                    if self._active_stop_event.is_set():
                        return None
                    # Asynchronously write to persistent cache in background daemon thread while playing
                    if not output_path:
                        threading.Thread(
                            target=sf.write,
                            args=(str(cached_wav), audio_data, 24000),
                            daemon=True
                        ).start()
                    else:
                        sf.write(str(cached_wav), audio_data, 24000)
                    # Immediate in-memory playback with 0ms disk delay
                    self._set_audio_duck(True)
                    self.play_memory_audio(audio_data, sample_rate=24000, wait=wait)
                    return cached_wav

                # For multi-sentence texts, generate and stream sentence by sentence
                self._stream_speech(sentences, voice_id, ref_lang, ref_audio, ref_text, lang, category, cached_wav, wait=wait)
                return cached_wav
            finally:
                self._is_speaking_event.clear()
                if wait or self._active_stop_event.is_set():
                    self._set_audio_duck(False)
                if self.low_vram and self.device == "cuda":
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass

    def _stream_speech(self, sentences, voice_id, ref_lang, ref_audio, ref_text, lang, category, final_cached_wav, wait: bool = False):
        """Generates and plays sentences sequentially with zero wait-time between chunks and instant cancellation support."""
        import queue

        audio_queue = queue.Queue()
        synthesis_done = threading.Event()
        all_chunks = []

        def player_thread():
            import time

            while not self._active_stop_event.is_set():
                try:
                    chunk = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    if synthesis_done.is_set():
                        break
                    continue

                if self._active_stop_event.is_set():
                    audio_queue.task_done()
                    break

                vol_scale = self._get_volume_scale()
                scaled_chunk = np.clip(chunk * vol_scale, -1.0, 1.0) if vol_scale < 0.999 else chunk

                # 1. Warm persistent stream fast path (0ms latency, zero gap between sentences)
                if hasattr(self, "_warm_player") and self._warm_player and self._warm_player._active:
                    self._warm_player.play(chunk, vol_scale=vol_scale)
                    chunk_dur = len(chunk) / 24000.0
                    t0 = time.time()
                    while (time.time() - t0) < chunk_dur:
                        if self._active_stop_event.is_set():
                            self._warm_player.stop()
                            break
                        time.sleep(0.015)
                    audio_queue.task_done()
                    continue

                # 2. Try sounddevice fallback (Cross-platform: Windows, Linux, macOS)
                played = False
                try:
                    import sounddevice as sd
                    sd.play(scaled_chunk, 24000)
                    chunk_dur = len(scaled_chunk) / 24000.0
                    t0 = time.time()
                    while (time.time() - t0) < chunk_dur:
                        if self._active_stop_event.is_set():
                            sd.stop()
                            break
                        time.sleep(0.02)
                    played = True
                except Exception:
                    pass

                # 3. Windows fallback via winsound
                if not played and not self._active_stop_event.is_set() and sys.platform.startswith("win"):
                    try:
                        import winsound
                        import io
                        import wave

                        int16_data = (np.clip(scaled_chunk, -1.0, 1.0) * 32767.0).astype(np.int16)
                        mem_wav = io.BytesIO()
                        with wave.open(mem_wav, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(24000)
                            wf.writeframes(int16_data.tobytes())
                        wav_bytes = mem_wav.getvalue()
                        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
                        played = True
                    except Exception:
                        pass

                # 4. Linux / macOS CLI player fallback (e.g. if libportaudio2 is not installed)
                if not played and not self._active_stop_event.is_set() and (sys.platform.startswith("linux") or sys.platform == "darwin"):
                    import tempfile
                    import subprocess
                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                            tmp_path = tmp.name
                        sf.write(tmp_path, scaled_chunk, 24000)
                        candidates = [["pw-cat", "-p"], ["paplay"], ["aplay", "-q"]] if sys.platform.startswith("linux") else [["afplay"]]
                        for player in candidates:
                            try:
                                proc = subprocess.Popen(player + [tmp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                while proc.poll() is None:
                                    if self._active_stop_event.is_set():
                                        proc.terminate()
                                        break
                                    time.sleep(0.02)
                                played = True
                                break
                            except FileNotFoundError:
                                continue
                    except Exception:
                        pass
                    finally:
                        if tmp_path:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass

                audio_queue.task_done()

        play_t = threading.Thread(target=player_thread, daemon=True)
        play_t.start()

        try:
            for i, sent in enumerate(sentences):
                if self._active_stop_event.is_set():
                    print("  [LOTRO-TTS] Synthesis canceled.")
                    break

                # First sentence uses num_step=20 for crisp fast time-to-first-sound; subsequent use 26
                step_count = 20 if i == 0 else 26
                chunk = self._synthesize_chunk(
                    sent, voice_id, ref_lang, ref_audio, ref_text, lang, category, num_step=step_count
                )
                if self._active_stop_event.is_set():
                    print("  [LOTRO-TTS] Synthesis canceled after chunk.")
                    break

                all_chunks.append(chunk)
                if i == 0:
                    self._set_audio_duck(True)
                    print("  First sentence ready! Playback started instantly via warm stream.")
                audio_queue.put(chunk)
        finally:
            synthesis_done.set()
            play_t.join(timeout=0.5 if self._active_stop_event.is_set() else None)
            if wait and hasattr(self, "_warm_player") and self._warm_player and self._warm_player._active:
                while not self._active_stop_event.is_set() and self._warm_player.is_playing():
                    time.sleep(0.025)

        # Write final full dialogue to persistent cache in background thread only if completed without interruption
        if all_chunks and not self._active_stop_event.is_set() and len(all_chunks) == len(sentences):
            full_audio = np.concatenate(all_chunks)
            threading.Thread(
                target=sf.write,
                args=(str(final_cached_wav), full_audio, 24000),
                daemon=True
            ).start()

    def _get_volume_scale(self) -> float:
        """
        Reads volume (0-100) and speech_speed (50-200) from config.json to apply live settings.
        Caches file modification time for instant 0ms lookups.
        """
        config_path = self.base_dir / "config.json"
        if not config_path.exists():
            return self._cached_vol_scale
        try:
            mtime = config_path.stat().st_mtime
            if mtime != self._config_vol_mtime:
                self._config_vol_mtime = mtime
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                vol = cfg.get("volume", self.volume)
                self.volume = max(0, min(100, int(vol)))
                self._cached_vol_scale = max(0.0, min(1.0, float(self.volume) / 100.0))
                if "speech_speed" in cfg:
                    spd = cfg.get("speech_speed", self.speed)
                    self.speed = max(50, min(200, int(spd)))
                    self._cached_speed_factor = max(0.5, min(2.0, float(self.speed) / 100.0))
            return self._cached_vol_scale
        except Exception:
            return self._cached_vol_scale

    def _get_speed_factor(self) -> float:
        """Returns the cached normalized speech speed multiplier (1.0 = 100%)."""
        self._get_volume_scale()
        return self._cached_speed_factor

    def _wait_interruptible(self, duration_sec: float, on_cancel=None, step_sec: float = 0.025):
        """Sleeps up to duration_sec while checking _active_stop_event for immediate cancellation."""
        t0 = time.monotonic()
        while (time.monotonic() - t0) < duration_sec:
            if self._active_stop_event.is_set():
                if on_cancel:
                    try:
                        on_cancel()
                    except Exception:
                        pass
                return
            time.sleep(step_sec)

    def _wait_for_subprocess(self, proc):
        """Waits for an external CLI player process while honoring stop requests."""
        while proc.poll() is None:
            if self._active_stop_event.is_set():
                proc.terminate()
                break
            time.sleep(0.025)

    def play_memory_audio(self, audio_data, sample_rate=24000, wait: bool = False):
        """Plays float32 audio array directly from memory without touching the hard drive."""
        vol_scale = self._get_volume_scale()
        duration_sec = float(len(audio_data)) / float(sample_rate or 24000)

        # 1. Warm persistent stream fast path (0ms start delay)
        if hasattr(self, "_warm_player") and self._warm_player and self._warm_player._active:
            self._warm_player.play(audio_data, vol_scale=vol_scale)
            if wait:
                while not self._active_stop_event.is_set() and self._warm_player.is_playing():
                    time.sleep(0.025)
            return

        # Apply software audio scaling on all platforms so volume is reliably respected
        if vol_scale < 0.999:
            audio_data = np.clip(audio_data * vol_scale, -1.0, 1.0)

        # 2. Try sounddevice fallback (Cross-platform: Windows, Linux, macOS)
        try:
            import sounddevice as sd
            sd.play(audio_data, sample_rate)
            if wait:
                self._wait_interruptible(duration_sec, on_cancel=sd.stop)
            return
        except Exception:
            pass

        # 3. Try winsound on Windows
        try:
            import winsound
            import io
            import wave

            int16_data = (np.clip(audio_data, -1.0, 1.0) * 32767.0).astype(np.int16)
            mem_wav = io.BytesIO()
            with wave.open(mem_wav, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(int16_data.tobytes())
            winsound.PlaySound(mem_wav.getvalue(), winsound.SND_MEMORY | winsound.SND_ASYNC)
            if wait:
                self._wait_interruptible(duration_sec, on_cancel=lambda: winsound.PlaySound(None, 0))
            return
        except Exception:
            pass

        # 4. Fallback for systems without winsound or sounddevice (Linux / macOS CLI players)
        import tempfile
        import subprocess
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            sf.write(tmp_path, audio_data, sample_rate)
            candidates = (
                [["pw-cat", "-p"], ["paplay"], ["aplay", "-q"]]
                if sys.platform.startswith("linux")
                else ([["afplay"]] if sys.platform == "darwin" else [])
            )
            for player in candidates:
                try:
                    proc = subprocess.Popen(player + [tmp_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if wait:
                        self._wait_for_subprocess(proc)
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                    return
                except FileNotFoundError:
                    continue
        except Exception:
            pass

    def play_audio(self, audio_file, wait: bool = False):
        """Plays a WAV file asynchronously (or blocks until finished when wait=True)."""
        try:
            data, fs = sf.read(str(audio_file), dtype="float32")
            self.play_memory_audio(data, fs, wait=wait)
            return
        except Exception:
            pass

        # Native system player fallback if soundfile could not decode directly
        try:
            import subprocess
            candidates = (
                [["pw-cat", "-p"], ["paplay"], ["aplay", "-q"]]
                if sys.platform.startswith("linux")
                else ([["afplay"]] if sys.platform == "darwin" else [])
            )
            for player in candidates:
                try:
                    proc = subprocess.Popen(player + [str(audio_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if wait:
                        self._wait_for_subprocess(proc)
                    return
                except FileNotFoundError:
                    continue
        except Exception as e:
            print(f"Could not play audio automatically: {e}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LOTRO-TTS Production Speaker")
    parser.add_argument("--text", type=str, required=True, help="Text to speak")
    parser.add_argument("--npc", type=str, default="narrator", help="NPC name (e.g. Galadriel, Lobelia) or category (elf_female, etc.)")
    parser.add_argument("--lang", type=str, choices=["de", "en", "fr", "es", "it", "nl"], default="de", help="Language code")
    parser.add_argument("--output", type=str, default=None, help="Output wav file path")
    parser.add_argument("--volume", type=int, default=80, help="Volume percentage (0-100)")
    parser.add_argument("--speed", type=int, default=100, help="Speech speed percentage (75-135, default: 100)")
    parser.add_argument("--device", type=str, choices=["auto", "cuda", "low-gpu", "low_vram", "cpu"], default=None, help="Compute mode (default: auto-detect)")

    args = parser.parse_args()
    # One-shot run: no background voice pre-caching, and wait for playback to finish before exiting
    speaker = LotroSpeaker(
        device=args.device, volume=args.volume, speed=args.speed, active_lang=args.lang,
        background_precache=False,
    )
    speaker.speak(args.text, npc_name_or_category=args.npc, lang=args.lang, output_path=args.output, wait=True)
