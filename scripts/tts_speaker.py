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
        
        # Load voice indexes for de and en
        self.indices = {}
        for lang in ["de", "en"]:
            idx_file = self.voices_dir / lang / "voice_index.json"
            if idx_file.exists():
                with open(idx_file, "r", encoding="utf-8") as f:
                    self.indices[lang] = json.load(f)
            else:
                self.indices[lang] = []
                
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
            # Try exact match first
            c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE name_en = ? OR name_de = ? LIMIT 1", (name_query, name_query))
            row = c.fetchone()
            # If not found, try fuzzy LIKE match
            if not row:
                c.execute("SELECT name_en, race, gender, voice_id FROM NPCs WHERE name_en LIKE ? OR name_de LIKE ? LIMIT 1", (f"%{name_query}%", f"%{name_query}%"))
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
        lang_items = self.indices.get(lang, [])
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

    def speak(self, text, npc_name_or_category="narrator", lang="de", output_path=None):
        """
        Synthesizes authentic speech for given NPC / category and text.
        """
        # Determine category
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
        
        print(f"[{lang.upper()}] Speaking for '{npc_name}' as {category} using template {voice_id}...")
        print(f"  Reference audio: {ref_audio.name}")
        print(f"  Reference prompt: {ref_text}")
        
        # OmniVoice Zero-Shot Generation
        result = self.model.generate(
            text=text,
            ref_audio=str(ref_audio),
            ref_text=ref_text,
            language=lang
        )
        
        audio_data = result[0].squeeze()
        sample_rate = 24000
        
        if not output_path:
            out_dir = self.base_dir / "audio_samples"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"{category}_{lang}.wav"
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
        sf.write(str(output_path), audio_data, sample_rate)
        print(f"  Generated speech saved to: {output_path}")
        return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LOTRO-TTS Production Speaker")
    parser.add_argument("--text", type=str, required=True, help="Text to speak")
    parser.add_argument("--npc", type=str, default="narrator", help="NPC name (e.g. Galadriel, Lobelia) or category (elf_female, etc.)")
    parser.add_argument("--lang", type=str, choices=["de", "en"], default="de", help="Language code")
    parser.add_argument("--output", type=str, default=None, help="Output wav file path")
    
    parser.add_argument("--device", type=str, choices=["cuda", "cpu"], default=None, help="Compute device (default: auto-detect cuda/cpu)")
    
    args = parser.parse_args()
    speaker = LotroSpeaker(device=args.device)
    speaker.speak(args.text, npc_name_or_category=args.npc, lang=args.lang, output_path=args.output)
