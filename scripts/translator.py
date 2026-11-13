# -*- coding: utf-8 -*-
"""
LOTRO-TTS Translation Module
Translates English quest and dialogue text into target languages (e.g. Italian 'it')
using HuggingFace MarianMT (Helsinki-NLP/opus-mt-en-*).
"""

import hashlib
import logging
import os
import sqlite3
import warnings
from pathlib import Path

# Suppress noisy HuggingFace Hub unauthenticated warnings and verbose HTTP logs
os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*")
warnings.filterwarnings("ignore", message=".*sacremoses.*")
warnings.filterwarnings("ignore", module="huggingface_hub.*")

logger = logging.getLogger("LOTRO-Translator")

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

# Supported explicit language pairs and corresponding HuggingFace model IDs
SUPPORTED_TRANSLATION_MODELS = {
    "en_it": "Helsinki-NLP/opus-mt-en-it",
    "en_es": "Helsinki-NLP/opus-mt-en-es",
    "en_nl": "Helsinki-NLP/opus-mt-en-nl",
    "de_nl": "Helsinki-NLP/opus-mt-de-nl",
    "de_it": "Helsinki-NLP/opus-mt-de-it",
    "de_es": "Helsinki-NLP/opus-mt-de-es",
    "fr_it": "Helsinki-NLP/opus-tatoeba-fr-it",
    "fr_es": "Helsinki-NLP/opus-mt-fr-es",
    "de_en": "Helsinki-NLP/opus-mt-de-en",
    "fr_en": "Helsinki-NLP/opus-mt-fr-en",
}


def _resolve_device(device: str | None) -> str:
    if device and device != "auto" and device != "cuda":
        return device
    try:
        from tts_speaker import resolve_compute_device
        return resolve_compute_device(device)
    except Exception:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"


class LotroTranslator:
    def __init__(self, cache_db_path: Path | str | None = None, device: str | None = None):
        self.base_dir = Path(__file__).resolve().parent.parent
        if cache_db_path is None:
            self.cache_db_path = self.base_dir / "data" / "translation_cache.db"
        else:
            self.cache_db_path = Path(cache_db_path)

        self.device = _resolve_device(device)

        self._pipelines = {}
        self._init_cache_db()

    def _init_cache_db(self):
        """Initializes the dedicated translation cache database if not exists."""
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.cache_db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS Translations (
                    source_hash TEXT NOT NULL,
                    src_lang TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source_hash, src_lang, target_lang)
                );
            """)
            conn.commit()
        finally:
            conn.close()

    def _resolve_translation_chain(self, src_lang: str, target_lang: str) -> list[str]:
        """Returns direct pair key or a 2-step English pivot chain (e.g. fr_en -> en_nl)."""
        direct_key = f"{src_lang}_{target_lang}"
        if direct_key in SUPPORTED_TRANSLATION_MODELS:
            return [direct_key]
        if src_lang != "en" and target_lang != "en":
            leg1 = f"{src_lang}_en"
            leg2 = f"en_{target_lang}"
            if leg1 in SUPPORTED_TRANSLATION_MODELS and leg2 in SUPPORTED_TRANSLATION_MODELS:
                return [leg1, leg2]
        return []

    def preload(self, target_lang: str, src_lang: str = "en"):
        """Pre-downloads, loads, and warms up the translation model at service startup."""
        target_lang = target_lang.lower().strip()
        src_lang = src_lang.lower().strip()
        chain = self._resolve_translation_chain(src_lang, target_lang)
        if not chain:
            return

        # When client is German or French, lotro.db quest matching prefers clean English text
        # for translation; preload en_<target> too if not already in chain!
        en_key = f"en_{target_lang}"
        if src_lang != "en" and target_lang in ("nl", "it", "es") and en_key in SUPPORTED_TRANSLATION_MODELS and en_key not in chain:
            try:
                self._get_model_and_tokenizer(en_key)
            except Exception:
                pass

        for pair_key in chain:
            model, tokenizer = self._get_model_and_tokenizer(pair_key)
            try:
                import torch
                device = "cuda" if self.device == "cuda" and torch.cuda.is_available() else "cpu"
                inputs = tokenizer("Greetings.", return_tensors="pt", padding=True, truncation=True)
                if device == "cuda":
                    inputs = {k: v.to("cuda") for k, v in inputs.items()}
                with torch.inference_mode():
                    _ = model.generate(**inputs, max_length=16)
            except Exception:
                pass

    def _get_model_and_tokenizer(self, pair_key: str):
        """Loads MarianMT model and tokenizer (uses local disk cache first without HTTP roundtrips)."""
        lookup_key = pair_key.lower().strip()
        if lookup_key in self._pipelines:
            return self._pipelines[lookup_key]

        model_id = SUPPORTED_TRANSLATION_MODELS.get(lookup_key)
        if not model_id:
            raise ValueError(f"No translation model configured for '{lookup_key}'.")

        logger.info(f"Loading translation model '{model_id}' on device [{self.device.upper()}]...")
        import warnings
        from transformers import MarianMTModel, MarianTokenizer
        import torch

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

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*sacremoses.*")
            warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
            warnings.filterwarnings("ignore", message=".*HF_TOKEN.*")
            warnings.filterwarnings("ignore", module="huggingface_hub.*")
            try:
                # Fast offline load if already downloaded (use_safetensors=False avoids PR conversion lookup)
                tokenizer = MarianTokenizer.from_pretrained(model_id, local_files_only=True)
                model = MarianMTModel.from_pretrained(model_id, local_files_only=True, use_safetensors=False)
            except Exception:
                logger.info(f"Downloading translation model '{model_id}' (one-time download)...")
                tokenizer = MarianTokenizer.from_pretrained(model_id)
                model = MarianMTModel.from_pretrained(model_id, use_safetensors=False)

        if self.device == "cuda" and torch.cuda.is_available():
            model = model.to("cuda")

        self._pipelines[lookup_key] = (model, tokenizer)
        logger.info(f"Translation model '{model_id}' ready.")
        return model, tokenizer

    def translate(self, text: str, src_lang: str = "en", target_lang: str = "it") -> str:
        """
        Translates text from src_lang to target_lang.
        Checks translation_cache.db first to avoid re-translating existing texts.
        Supports direct models as well as automatic English pivot chains (e.g. fr -> en -> nl).
        """
        text = text.strip()
        if not text:
            return ""

        src_lang = src_lang.lower().strip()
        target_lang = target_lang.lower().strip()

        # Same language, no translation needed
        if src_lang == target_lang:
            return text

        chain = self._resolve_translation_chain(src_lang, target_lang)
        if not chain:
            raise ValueError(f"No translation model configured for '{src_lang}' -> '{target_lang}'.")

        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # 1. Check SQLite Cache
        conn = sqlite3.connect(str(self.cache_db_path))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT translated_text FROM Translations WHERE source_hash = ? AND src_lang = ? AND target_lang = ?",
                (source_hash, src_lang, target_lang)
            )
            row = cur.fetchone()
            if row and row[0]:
                logger.info(f"[TRANSLATION CACHE HIT] Retrieved '{target_lang}' translation instantly.")
                return row[0]

            # 2. Run MarianMT Translation (direct or 2-step English pivot)
            import torch
            device = "cuda" if self.device == "cuda" and torch.cuda.is_available() else "cpu"
            current_text = text
            for idx, pair_key in enumerate(chain):
                if len(chain) == 1:
                    logger.info(f"Translating text ({len(current_text)} chars) from '{src_lang}' to '{target_lang}' via MarianMT...")
                else:
                    logger.info(f"Translating text step {idx + 1}/{len(chain)} ({pair_key}) via MarianMT...")

                model, tokenizer = self._get_model_and_tokenizer(pair_key)
                inputs = tokenizer(current_text, return_tensors="pt", padding=True, truncation=True)
                if device == "cuda":
                    inputs = {k: v.to("cuda") for k, v in inputs.items()}

                with torch.inference_mode():
                    translated_tokens = model.generate(**inputs, max_length=1024)
                current_text = tokenizer.decode(translated_tokens[0], skip_special_tokens=True).strip()

            translated_text = current_text

            # 3. Save to Cache
            cur.execute(
                """
                INSERT OR REPLACE INTO Translations (source_hash, src_lang, target_lang, source_text, translated_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_hash, src_lang, target_lang, text, translated_text)
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(f"Translation complete: '{translated_text[:60]}...'")
        return translated_text

