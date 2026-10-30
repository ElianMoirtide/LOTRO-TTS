# -*- coding: utf-8 -*-
"""
Production LOTRO-TTS Speaker Engine
Uses local OmniVoice Zero-Shot Voice Cloning on NVIDIA RTX GPU.
Clones speech dynamically from authentic LOTRO reference audio files in voices/{lang}/{category}/.
"""
import os
import sys
import json
import sqlite3
import argparse
import random
from pathlib import Path
import soundfile as sf
import torch

try:
    from omnivoice import OmniVoice
except ImportError:
    print("Error: omnivoice is not installed. Please install it in the python environment.")
    sys.exit(1)

class LotroSpeaker:
    def __init__(self, voices_dir="data/voices", db_path="data/lotro.db", device=None):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.voices_dir = self.base_dir / voices_dir
        self.db_path = self.base_dir / db_path
        
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Initializing LOTRO-TTS Speaker Engine on [{self.device}]...")
        
        # Load OmniVoice model once
        self.model = OmniVoice.from_pretrained("k2-fsa/OmniVoice")
        self.model = self.model.to(self.device)
        print("OmniVoice model loaded successfully!")
        
        # Load voice indexes for all supported native voice libraries (de, en, fr)
        self.indices = {}
        for lang in ["de", "en", "fr"]:
            idx_file = self.voices_dir / lang / "voice_index.json"
            if idx_file.exists():
                with open(idx_file, "r", encoding="utf-8") as f:
                    self.indices[lang] = json.load(f)
            else:
                self.indices[lang] = []

        # Warm up OmniVoice with a silent 1-word generation to initialize CUDA kernels & VRAM allocations
        self._warmup_engine()

    def _warmup_engine(self):
        """Performs a silent mini-generation to pre-warm CUDA kernels and avoid first-sentence latency."""
        try:
            # Pick any available reference audio from the loaded index
            ref_item = None
            for l in ["en", "de", "fr"]:
                if self.indices.get(l):
                    ref_item = self.indices[l][0]
                    break

            if ref_item:
                ref_audio_path = self.voices_dir / ref_item["audio_file"]
                if ref_audio_path.exists():
                    print(f"Pre-warming TTS engine kernels on [{self.device}]...")
                    # Generate a short neutral word silently (no audio playback)
                    _ = self.model.generate(
                        text="Greetings.",
                        ref_audio=str(ref_audio_path),
                        ref_text=ref_item.get("text", "Greetings."),
                        language="en"
                    )
                    print("TTS engine pre-warmed and ready for instant playback!")
        except Exception as e:
            # Warm-up is non-critical, service will continue normally if it fails
            print(f"TTS warm-up notice: {e}")
                
    def get_npc_info(self, npc_name_or_id):
        """Looks up NPC race and gender from data/lotro.db"""
        if not self.db_path.exists():
            return "narrator", "narrator", "male"
            
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        
        row = None
        if isinstance(npc_name_or_id, int) or (isinstance(npc_name_or_id, str) and npc_name_or_id.isdigit()):
            c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE id = ?", (int(npc_name_or_id),))
            row = c.fetchone()
        else:
            name_query = str(npc_name_or_id).strip()
            # Try exact match first across all supported language names
            c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE name_en = ? OR name_de = ? OR name_fr = ? OR name_es = ? LIMIT 1", (name_query, name_query, name_query, name_query))
            row = c.fetchone()
            # If not found, try fuzzy LIKE match
            if not row:
                c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE name_en LIKE ? OR name_de LIKE ? OR name_fr LIKE ? OR name_es LIKE ? LIMIT 1", (f"%{name_query}%", f"%{name_query}%", f"%{name_query}%", f"%{name_query}%"))
                row = c.fetchone()
            
        conn.close()
        
        if row:
            name, race, gender, voice_id = row
            race_str = (race or "man").lower()
            gender_str = (gender or "male").lower()
            
            # Map race to category
            if "elf" in race_str:
                r = "elf"
            elif "hobbit" in race_str or "river" in race_str:
                r = "hobbit"
            elif "dwarf" in race_str or "stout" in race_str:
                r = "dwarf"
            elif "orc" in race_str or "uruk" in race_str or "goblin" in race_str:
                return name, "orc", "male"
            elif "troll" in race_str:
                return name, "troll", "male"
            elif "ent" in race_str or "huorn" in race_str:
                return name, "ent", "neutral"
            elif "dead" in race_str or "shade" in race_str:
                return name, "dead", "neutral"
            else:
                r = "man"
                
            g = "female" if gender_str == "female" else "male"
            return name, f"{r}_{g}", g
            
        return str(npc_name_or_id), "narrator", "male"

    def select_voice_template(self, category, lang="de", seed_key=None):
        """Selects reference audio and sidecar transcript for cloning"""
        # For languages without authentic LOTRO audio samples (e.g. Italian 'it'),
        # use the authentic English reference audio pool for cross-lingual zero-shot cloning.
        ref_lang = lang if lang in self.indices and self.indices[lang] else "en"
        lang_items = self.indices.get(ref_lang, [])
        cat_matches = [it for it in lang_items if it["category"] == category]
        
        if not cat_matches:
            # Fallback to narrator or man_male
            cat_matches = [it for it in lang_items if it["category"] == "narrator"] or lang_items
            
        if not cat_matches:
            raise FileNotFoundError(f"No voice templates found for category '{category}' and language '{lang}'")
            
        # Deterministic selection if seed_key given
        if seed_key:
            idx = abs(hash(str(seed_key))) % len(cat_matches)
            selected = cat_matches[idx]
        else:
            selected = random.choice(cat_matches)
            
        ref_audio_path = self.voices_dir / selected["audio_file"]
        ref_text = selected["text"]
        
        return selected["voice_id"], ref_audio_path, ref_text

    def speak(self, text, npc_name_or_category="narrator", lang="de", output_path=None, cache_key=None):
        """
        Synthesizes authentic speech for given NPC / category and text.
        Includes persistent disk cache and sentence-level streaming for instant playback.
        """
        import hashlib
        import re

        text = text.strip()
        if not text:
            return None

        # Determine category & NPC info
        if npc_name_or_category in [
            "elf_female", "elf_male", "man_female", "man_male",
            "hobbit_female", "hobbit_male", "dwarf_female", "dwarf_male",
            "orc", "troll", "ent", "dead", "narrator"
        ]:
            category = npc_name_or_category
            npc_name = category
        else:
            npc_name, category, _ = self.get_npc_info(npc_name_or_category)
            
        voice_id, ref_audio, ref_text = self.select_voice_template(category, lang=lang, seed_key=npc_name)
        
        # 1. AUDIO CACHE CHECK
        cache_dir = self.base_dir / "cache" / "audio"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        text_hash = hashlib.md5(f"{voice_id}_{lang}_{text}".encode("utf-8")).hexdigest()
        cached_wav = cache_dir / f"{text_hash}.wav"
        
        if cached_wav.exists() and cached_wav.stat().st_size > 44:
            print(f"[{lang.upper()}] [AUDIO CACHE HIT] Playing cached audio instantly for '{npc_name}'...")
            self.play_audio(cached_wav)
            return cached_wav

        print(f"[{lang.upper()}] Speaking for '{npc_name}' as {category} using template {voice_id}...")
        print(f"  Reference audio: {ref_audio.name}")
        
        # 2. STREAMING OR DIRECT SYNTHESIS
        # Split into sentences for fast Time-To-First-Audio if text is long
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        
        # If short text (1-2 sentences), generate directly
        if len(sentences) <= 2 or len(text) < 180:
            result = self.model.generate(
                text=text,
                ref_audio=str(ref_audio),
                ref_text=ref_text,
                language=lang
            )
            audio_data = result[0].squeeze()
            sample_rate = 24000
            sf.write(str(cached_wav), audio_data, sample_rate)
            self.play_audio(cached_wav)
            return cached_wav

        # For longer texts, stream chunk by chunk
        self._stream_speech(sentences, ref_audio, ref_text, lang, cached_wav)
        return cached_wav

    def _stream_speech(self, sentences, ref_audio, ref_text, lang, final_cached_wav):
        """Generates and plays sentences sequentially with zero wait-time between chunks."""
        import queue
        import threading

        audio_queue = queue.Queue()
        stop_event = threading.Event()
        all_chunks = []

        def player_thread():
            import winsound
            import tempfile
            import time

            while not stop_event.is_set() or not audio_queue.empty():
                try:
                    chunk = audio_queue.get(timeout=0.2)
                    chunk_duration = len(chunk) / 24000.0
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = Path(tmp.name)
                    sf.write(str(tmp_path), chunk, 24000)
                    # Play synchronous so next sentence waits until current is finished
                    try:
                        winsound.PlaySound(str(tmp_path), winsound.SND_FILENAME)
                    except Exception:
                        pass
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                    audio_queue.task_done()
                except queue.Empty:
                    continue

        play_t = threading.Thread(target=player_thread, daemon=True)
        play_t.start()

        try:
            for i, sent in enumerate(sentences):
                res = self.model.generate(
                    text=sent,
                    ref_audio=str(ref_audio),
                    ref_text=ref_text,
                    language=lang
                )
                chunk = res[0].squeeze()
                all_chunks.append(chunk)
                audio_queue.put(chunk)
                if i == 0:
                    print(f"  First sentence ready! Playback started instantly.")
        finally:
            stop_event.set()
            play_t.join()

        # Save concatenated full WAV to persistent cache for future instant re-use
        if all_chunks:
            import numpy as np
            full_audio = np.concatenate(all_chunks)
            sf.write(str(final_cached_wav), full_audio, 24000)

    def play_audio(self, audio_file):
        """Plays a WAV file asynchronously or via standard system sound."""
        try:
            import winsound
            winsound.PlaySound(str(audio_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception:
            pass

        try:
            # Fallback for Linux / macOS
            import subprocess
            if sys.platform.startswith("linux"):
                subprocess.Popen(["aplay", "-q", str(audio_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "darwin":
                subprocess.Popen(["afplay", str(audio_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Could not play audio automatically: {e}", file=sys.stderr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LOTRO-TTS Production Speaker")
    parser.add_argument("--text", type=str, required=True, help="Text to speak")
    parser.add_argument("--npc", type=str, default="narrator", help="NPC name (e.g. Galadriel, Lobelia) or category (elf_female, etc.)")
    parser.add_argument("--lang", type=str, choices=["de", "en", "fr", "es", "it"], default="de", help="Language code")
    parser.add_argument("--output", type=str, default=None, help="Output wav file path")
    
    parser.add_argument("--device", type=str, choices=["cuda", "cpu"], default=None, help="Compute device (default: auto-detect cuda/cpu)")
    
    args = parser.parse_args()
    speaker = LotroSpeaker(device=args.device)
    speaker.speak(args.text, npc_name_or_category=args.npc, lang=args.lang, output_path=args.output)
