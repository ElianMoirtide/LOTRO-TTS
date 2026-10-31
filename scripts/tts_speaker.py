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
import unicodedata
from pathlib import Path
import numpy as np
import soundfile as sf
import torch

try:
    from omnivoice import OmniVoice
except ImportError:
    print("Error: omnivoice is not installed. Please install it in the python environment.")
    sys.exit(1)

# Version tag included in audio cache keys so outdated cached clips are invalidated
SPEAKER_ENGINE_VERSION = "v4"


def _norm_npc_key(name: str | None) -> str:
    if not name:
        return ""
    s = str(name).strip().strip("'\"` \t\r\n").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


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

        # Cache of pre-encoded VoiceClonePrompt objects & reference audio durations
        self._prompt_cache = {}
        self._ref_duration_cache = {}

        # Load voice indexes for all supported native voice libraries (de, en, fr)
        self.indices = {}
        self.by_voice_id = {}
        self.by_npc_name = {}
        for lang in ["de", "en", "fr"]:
            idx_file = self.voices_dir / lang / "voice_index.json"
            if idx_file.exists():
                with open(idx_file, "r", encoding="utf-8") as f:
                    items = json.load(f)
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

        # Warm up OmniVoice with a silent 1-word generation to initialize CUDA kernels & VRAM allocations
        self._warmup_engine()

    def _warmup_engine(self):
        """Performs a silent mini-generation to pre-warm CUDA kernels and avoid first-sentence latency."""
        try:
            ref_item = None
            for l in ["en", "de", "fr"]:
                items = self.indices.get(l, [])
                if items:
                    ref_item = next((it for it in items if not it.get("voice_id", "").startswith("npc_")), items[0])
                    break

            if ref_item:
                ref_audio_path = self.voices_dir / ref_item["audio_file"]
                if ref_audio_path.exists():
                    print(f"Pre-warming TTS engine kernels on [{self.device}]...")
                    _ = self.model.generate(
                        text="Greetings.",
                        ref_audio=str(ref_audio_path),
                        ref_text=ref_item.get("text", "Greetings."),
                        language="en",
                        postprocess_output=False
                    )
                    print("TTS engine pre-warmed and ready for instant playback!")
        except Exception as e:
            print(f"TTS warm-up notice: {e}")

    def get_npc_info(self, npc_name_or_id):
        """Looks up NPC race, gender, and assigned voice_id from data/lotro.db."""
        if not self.db_path.exists():
            return "narrator", "narrator", "male", None

        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()

        row = None
        if isinstance(npc_name_or_id, int) or (isinstance(npc_name_or_id, str) and npc_name_or_id.isdigit()):
            c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE id = ?", (int(npc_name_or_id),))
            row = c.fetchone()
        else:
            name_query = str(npc_name_or_id).strip()
            c.execute(
                "SELECT name_en, race, gender, voice_id FROM NPCs "
                "WHERE name_en = ? OR name_de = ? OR name_fr = ? OR name_es = ? "
                "ORDER BY CASE WHEN race IS NOT NULL AND length(race) > 0 THEN 0 ELSE 1 END, id ASC LIMIT 1",
                (name_query, name_query, name_query, name_query)
            )
            row = c.fetchone()
            if not row:
                c.execute(
                    "SELECT name_en, race, gender, voice_id FROM NPCs "
                    "WHERE name_en LIKE ? OR name_de LIKE ? OR name_fr LIKE ? OR name_es LIKE ? "
                    "ORDER BY CASE WHEN race IS NOT NULL AND length(race) > 0 THEN 0 ELSE 1 END, id ASC LIMIT 1",
                    (f"%{name_query}%", f"%{name_query}%", f"%{name_query}%", f"%{name_query}%")
                )
                row = c.fetchone()

        conn.close()

        if row:
            name, race, gender, voice_id = row
            race_str = (race or "man").lower()
            gender_str = (gender or "male").lower()

            # Map race to category
            if "river-maid" in race_str:
                return name, "elf_female", "female", voice_id
            elif "elf" in race_str or "kinta" in race_str:
                r = "elf"
            elif "hobbit" in race_str or "halfling" in race_str or "stoor" in race_str or "river" in race_str:
                r = "hobbit"
            elif "dwarf" in race_str or "stout" in race_str or "zhélruka" in race_str or "zhelruka" in race_str or "temámir" in race_str or "temamir" in race_str:
                r = "dwarf"
            elif "orc" in race_str or "uruk" in race_str or "goblin" in race_str or "ordâkhai" in race_str or "ordakhai" in race_str:
                return name, "orc", "male", voice_id
            elif "troll" in race_str or "giant" in race_str or "rogmul" in race_str:
                return name, "troll", "male", voice_id
            elif "ent" in race_str or "huorn" in race_str:
                return name, "ent", "neutral", voice_id
            elif "dead" in race_str or "shade" in race_str or "wraith" in race_str or "nazgûl" in race_str or "nazgul" in race_str:
                return name, "dead", "neutral", voice_id
            else:
                r = "man"

            g = "female" if gender_str == "female" else "male"
            return name, f"{r}_{g}", g, voice_id

        # Diacritic-insensitive fallback via pre-indexed verified NPC names (e.g. 'Gloin' -> 'Glóin', 'Eowyn' -> 'Éowyn')
        norm_q = _norm_npc_key(npc_name_or_id)
        for l in ("en", "de", "fr"):
            if norm_q in self.by_npc_name.get(l, {}):
                it = self.by_npc_name[l][norm_q]
                return str(npc_name_or_id), it.get("category", "man_male"), it.get("gender", "male"), it["voice_id"]

        return str(npc_name_or_id), "narrator", "male", None

    def select_voice_template(self, category, lang="de", seed_key=None, preferred_voice_id=None):
        """Selects reference audio and sidecar transcript for cloning (prioritizing 1:1 NPC voice when available)."""
        # For languages without authentic LOTRO audio samples (e.g. Spanish 'es', Italian 'it'),
        # use the authentic English reference audio pool for cross-lingual zero-shot cloning.
        ref_lang = lang if lang in self.indices and self.indices[lang] else "en"
        lang_items = self.indices.get(ref_lang, [])
        voice_map = self.by_voice_id.get(ref_lang, {})
        npc_map = self.by_npc_name.get(ref_lang, {})

        # 1. Direct voice_id match from lotro.db (verified voice actor or deterministic category voice)
        if preferred_voice_id and preferred_voice_id in voice_map:
            cand = voice_map[preferred_voice_id]
            cand_path = self.voices_dir / cand["audio_file"]
            if cand_path.exists():
                return cand["voice_id"], cand_path, cand["text"], ref_lang

        # 2. Direct verified NPC name match (covers diacritic variants like Gloin -> Glóin)
        if seed_key:
            norm_seed = _norm_npc_key(seed_key)
            if norm_seed in npc_map:
                cand = npc_map[norm_seed]
                cand_path = self.voices_dir / cand["audio_file"]
                if cand_path.exists():
                    return cand["voice_id"], cand_path, cand["text"], ref_lang

        # 3. Category pool lookup
        cat_matches = [it for it in lang_items if it["category"] == category]

        if not cat_matches:
            cat_matches = (
                [it for it in lang_items if it["category"] == "narrator"]
                or [it for it in lang_items if it["category"] == "man_male"]
                or lang_items
            )

        if not cat_matches:
            raise FileNotFoundError(f"No voice templates found for category '{category}' and language '{lang}'")

        if seed_key:
            idx = abs(hash(str(seed_key))) % len(cat_matches)
            selected = cat_matches[idx]
        else:
            selected = random.choice(cat_matches)

        ref_audio_path = self.voices_dir / selected["audio_file"]
        ref_text = selected["text"]

        return selected["voice_id"], ref_audio_path, ref_text, ref_lang

    def _get_voice_prompt_and_duration(self, voice_id, ref_lang, ref_audio_path, ref_text):
        """
        Builds and caches the VoiceClonePrompt with preprocess_prompt=False so
        OmniVoice's aggressive silence stripper does not shrink reference duration
        or clip reference phonemes.
        """
        cache_key = (ref_lang, voice_id, str(ref_audio_path), ref_text)
        if cache_key not in self._prompt_cache:
            info = sf.info(str(ref_audio_path))
            self._ref_duration_cache[cache_key] = float(info.duration)
            prompt = self.model.create_voice_clone_prompt(
                ref_audio=str(ref_audio_path),
                ref_text=ref_text,
                preprocess_prompt=False
            )
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

        # Add generous trailing breath headroom (+0.32s) so final syllables (-en, -er, -t)
        # have full room to decay naturally before the diffusion token window ends.
        est_duration = (target_w / effective_rate) + 0.32
        return max(est_duration, 0.85)

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

    def _synthesize_chunk(self, text_chunk, voice_id, ref_lang, ref_audio, ref_text, lang, category):
        """Synthesizes a single sentence/chunk with calibrated duration and intact word endings."""
        prompt, ref_dur = self._get_voice_prompt_and_duration(voice_id, ref_lang, ref_audio, ref_text)
        target_dur = self._estimate_natural_duration(text_chunk, ref_text, ref_dur, category=category)

        res = self.model.generate(
            text=text_chunk,
            voice_clone_prompt=prompt,
            language=lang,
            duration=target_dur,
            postprocess_output=False
        )
        return self._clean_generated_chunk(res[0], sample_rate=24000)

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
        preferred_voice_id = None
        if npc_name_or_category in [
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

        text_hash = hashlib.md5(
            f"{SPEAKER_ENGINE_VERSION}_{voice_id}_{ref_audio.name}_{lang}_{text}".encode("utf-8")
        ).hexdigest()
        cached_wav = Path(output_path) if output_path else (cache_dir / f"{text_hash}.wav")

        if not output_path and cached_wav.exists() and cached_wav.stat().st_size > 44:
            print(f"[{lang.upper()}] [AUDIO CACHE HIT] Playing cached audio instantly for '{npc_name}'...")
            self.play_audio(cached_wav)
            return cached_wav

        print(f"[{lang.upper()}] Speaking for '{npc_name}' as {category} using template {voice_id}...")
        print(f"  Reference audio: {ref_audio.name}")

        # 2. STREAMING OR DIRECT SYNTHESIS
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

        # If short text (1 sentence and < 140 chars), generate directly
        if len(sentences) <= 1 and len(text) < 140:
            audio_data = self._synthesize_chunk(
                text, voice_id, ref_lang, ref_audio, ref_text, lang, category
            )
            sf.write(str(cached_wav), audio_data, 24000)
            self.play_audio(cached_wav)
            return cached_wav

        # For multi-sentence texts, generate and stream sentence by sentence
        # (Generating sentence-by-sentence also prevents diffusion attention drift on long paragraphs!)
        self._stream_speech(sentences, voice_id, ref_lang, ref_audio, ref_text, lang, category, cached_wav)
        return cached_wav

    def _stream_speech(self, sentences, voice_id, ref_lang, ref_audio, ref_text, lang, category, final_cached_wav):
        """Generates and plays sentences sequentially with zero wait-time between chunks."""
        import queue
        import threading

        audio_queue = queue.Queue()
        stop_event = threading.Event()
        all_chunks = []

        def player_thread():
            import winsound
            import tempfile

            while not stop_event.is_set() or not audio_queue.empty():
                try:
                    chunk = audio_queue.get(timeout=0.2)
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = Path(tmp.name)
                    sf.write(str(tmp_path), chunk, 24000)
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
                chunk = self._synthesize_chunk(
                    sent, voice_id, ref_lang, ref_audio, ref_text, lang, category
                )
                all_chunks.append(chunk)
                audio_queue.put(chunk)
                if i == 0:
                    print("  First sentence ready! Playback started instantly.")
        finally:
            stop_event.set()
            play_t.join()

        if all_chunks:
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
