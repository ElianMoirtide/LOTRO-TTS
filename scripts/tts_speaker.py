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
SPEAKER_ENGINE_VERSION = "v6"


def _norm_npc_key(name: str | None) -> str:
    if not name:
        return ""
    s = str(name).strip().strip("'\"` \t\r\n").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


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
        preprocess_prompt=False so OmniVoice's silence stripper does not shrink reference
        duration or clip reference phonemes.
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
                    preprocess_prompt=False
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

    def _clean_generated_chunk(self, audio_tensor, sample_rate=24000):
        """
        Gentle audio post-processor that replaces OmniVoice's aggressive remove_silence().
        Preserves quiet word-final syllables ('-en' in 'sprechen') by only trimming
        near-zero digital silence (< 0.0015) and keeping a 220ms trailing tail.
        """
        if hasattr(audio_tensor, "detach"):
            wav = audio_tensor.squeeze().detach().cpu().numpy().astype(np.float32)
        else:
            wav = np.asarray(audio_tensor, dtype=np.float32).squeeze()
        if wav.size == 0:
            return wav

        # Find first and last sample above a very low noise floor (0.0015)
        active = np.where(np.abs(wav) > 0.0015)[0]
        if active.size > 0:
            lead_keep = int(0.08 * sample_rate)   # 80ms lead room
            trail_keep = int(0.24 * sample_rate)  # 240ms trail room so word endings never clip
            start_idx = max(0, int(active[0]) - lead_keep)
            end_idx = min(wav.size, int(active[-1]) + trail_keep)
            wav = wav[start_idx:end_idx]

        # Apply gentle 15ms cosine fade-in / fade-out to prevent clicks
        fade_len = min(int(0.015 * sample_rate), wav.size // 4)
        if fade_len > 1:
            fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
            fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            wav[:fade_len] *= fade_in
            wav[-fade_len:] *= fade_out

        # Add 80ms inter-sentence pause at the end
        pad = np.zeros(int(0.08 * sample_rate), dtype=np.float32)
        return np.concatenate([wav, pad])

    @torch.inference_mode()
    def _synthesize_chunk(self, text_chunk, voice_id, ref_lang, ref_audio, ref_text, lang, category, num_step=24):
        """Synthesizes a single sentence/chunk with calibrated duration, intact word endings, and tuned diffusion steps."""
        prompt, ref_dur = self._get_voice_prompt_and_duration(voice_id, ref_lang, ref_audio, ref_text)
        target_dur = self._estimate_natural_duration(text_chunk, ref_text, ref_dur, category=category)

        res = self.model.generate(
            text=text_chunk,
            voice_clone_prompt=prompt,
            language=lang,
            duration=target_dur,
            num_step=num_step,
            postprocess_output=False
        )
        return self._clean_generated_chunk(res[0], sample_rate=24000)

    def _split_dialogue_chunks(self, text: str, lang: str = "de") -> list[str]:
        """
        Intelligently splits dialogue purely on complete, grammatical sentence boundaries:
        1. Never splits inside sentences at commas or subclauses (preserves natural intonation & prosody).
        2. Never breaks on ellipses ('...' or '…') which represent internal dramatic pauses/hesitations.
        3. Protects honorifics & abbreviations (M., Mme., Dr., etc., z.B., etc.).
        4. Preserves speech tags ("« Regardez ! » dit-il") with their preceding quote.
        5. Merges tiny fragments (< 4 words or < 18 chars) so isolated words do not create audio buffer stalls.
        """
        import re

        text = text.strip()
        if not text:
            return []

        # Normalize French non-breaking spaces and typography
        text = text.replace("\u00a0", " ").replace("\u202f", " ")

        # Protect ellipses so they are never split as sentence boundaries
        protected = text.replace("...", "___ELLIPSIS___").replace("…", "___ELLIPSIS___")

        # Protect common abbreviations across DE, EN, FR, ES, IT, NL
        abbrs = [
            "M.", "Mme.", "Mlle.", "Dr.", "Prof.", "etc.", "cf.", "env.", "p.ex.",
            "z.B.", "d.h.", "u.a.", "bzw.", "ca.", "usw.",
            "Mr.", "Mrs.", "Ms.", "e.g.", "i.e.", "vs.",
            "Sr.", "Sra.", "bijv.", "d.w.z.", "t.a.v."
        ]
        for ab in abbrs:
            protected = protected.replace(ab, ab.replace(".", "___DOT___"))

        # Normalize spaces before closing quotes in French typography (e.g. "Oui ! »" -> "Oui !»")
        protected = re.sub(r'([.!?])\s+([»”"\x27])', r'\1\2', protected)

        # Split on sentence boundaries (. ! ?) followed by whitespace and an uppercase letter / quote / end.
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

        # Restore protected placeholders
        restored = []
        for p in parts:
            p = p.replace("___ELLIPSIS___", "...").replace("___DOT___", ".").strip()
            if p:
                restored.append(p)

        # Merge very short chunks into neighbors so isolated words don't create audio buffer underruns
        merged = []
        for p in restored:
            w_count = len(p.split())
            if merged and (w_count < 4 or len(p) < 18):
                merged[-1] = merged[-1] + " " + p
            else:
                merged.append(p)

        # If the very first sentence is tiny (< 4 words or < 18 chars) and more sentences follow,
        # merge it with the second sentence for natural opening prosody and buffer safety
        if len(merged) > 1 and (len(merged[0].split()) < 4 or len(merged[0]) < 18):
            merged[1] = merged[0] + " " + merged[1]
            merged.pop(0)

        # Gently split extraordinarily long sentences (> 220 chars) at clause delimiters
        # (; — – or balanced commas) so time-to-first-sound remains responsive without hurting prosody
        final_chunks = []
        for chunk in merged:
            if len(chunk) <= 220:
                final_chunks.append(chunk)
                continue
            clauses = re.split(r'(?<=[;—–])\s+', chunk)
            if len(clauses) == 1 and len(chunk) > 260:
                clauses = re.split(r'(?<=,)\s+', chunk)
            buf = ""
            for cl in clauses:
                cl = cl.strip()
                if not cl:
                    continue
                if buf and len(buf) >= 75 and (len(buf) + 1 + len(cl)) > 200:
                    final_chunks.append(buf)
                    buf = cl
                else:
                    buf = f"{buf} {cl}".strip() if buf else cl
            if buf:
                if final_chunks and len(buf) < 55:
                    final_chunks[-1] = f"{final_chunks[-1]} {buf}"
                else:
                    final_chunks.append(buf)

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

        text = self.apply_pronunciation(raw_text, lang=lang).strip() or raw_text

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
                    audio_data = self._synthesize_chunk(
                        text, voice_id, ref_lang, ref_audio, ref_text, lang, category, num_step=18
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

                # First sentence uses num_step=18 for ultra-fast time-to-first-sound; subsequent use 24
                step_count = 18 if i == 0 else 24
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
