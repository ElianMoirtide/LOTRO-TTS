# -*- coding: utf-8 -*-
"""
LOTRO-TTS Translation Module
Translates English quest and dialogue text into target languages (e.g. Italian 'it')
using HuggingFace MarianMT (Helsinki-NLP/opus-mt-en-*).

Features:
- Completely offline once downloaded.
- GPU accelerated if CUDA is available, otherwise runs on CPU (AMD / Intel).
- Persistent SQLite cache in data/translation_cache.db (never touches lotro.db).
- Lazy loading: The translation model is only loaded into memory when requested.
"""

import hashlib
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("LOTRO-Translator")

# Supported language pairs and corresponding HuggingFace model IDs
SUPPORTED_TRANSLATION_MODELS = {
    "it": "Helsinki-NLP/opus-mt-en-it",
    "es": "Helsinki-NLP/opus-mt-en-es",
}


class LotroTranslator:
    def __init__(self, cache_db_path: Path | str | None = None, device: str | None = None):
        self.base_dir = Path(__file__).resolve().parent.parent
        if cache_db_path is None:
            self.cache_db_path = self.base_dir / "data" / "translation_cache.db"
        else:
            self.cache_db_path = Path(cache_db_path)

        if device is None:
            import torch
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self._pipelines = {}
        self._init_cache_db()

    def _init_cache_db(self):
        """Initializes the dedicated translation cache database if not exists."""
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.cache_db_path))
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
        conn.close()

    def preload(self, target_lang: str):
        """Pre-downloads, loads, and warms up the translation model at service startup."""
        target_lang = target_lang.lower().strip()
        if target_lang not in SUPPORTED_TRANSLATION_MODELS:
            return
        model, tokenizer = self._get_model_and_tokenizer(target_lang)
        try:
            import torch
            device = "cuda" if self.device == "cuda" and torch.cuda.is_available() else "cpu"
            inputs = tokenizer("Greetings.", return_tensors="pt", padding=True, truncation=True)
            if device == "cuda":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}
            _ = model.generate(**inputs, max_length=16)
        except Exception:
            pass

    def _get_model_and_tokenizer(self, target_lang: str):
        """Loads MarianMT model and tokenizer (uses local disk cache first without HTTP roundtrips)."""
        target_lang = target_lang.lower().strip()
        if target_lang in self._pipelines:
            return self._pipelines[target_lang]

        model_id = SUPPORTED_TRANSLATION_MODELS.get(target_lang)
        if not model_id:
            raise ValueError(f"No translation model configured for target language '{target_lang}'.")

        logger.info(f"Loading translation model '{model_id}' on device [{self.device.upper()}]...")
        import warnings
        from transformers import MarianMTModel, MarianTokenizer
        import torch

        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*sacremoses.*")
            try:
                # Fast offline load if already downloaded
                tokenizer = MarianTokenizer.from_pretrained(model_id, local_files_only=True)
                model = MarianMTModel.from_pretrained(model_id, local_files_only=True)
            except Exception:
                logger.info(f"Downloading translation model '{model_id}' (one-time download)...")
                tokenizer = MarianTokenizer.from_pretrained(model_id)
                model = MarianMTModel.from_pretrained(model_id)

        if self.device == "cuda" and torch.cuda.is_available():
            model = model.to("cuda")

        self._pipelines[target_lang] = (model, tokenizer)
        logger.info(f"Translation model '{model_id}' ready.")
        return model, tokenizer

    def translate(self, text: str, src_lang: str = "en", target_lang: str = "it") -> str:
        """
        Translates text from src_lang to target_lang.
        Checks translation_cache.db first to avoid re-translating existing texts.
        """
        text = text.strip()
        if not text:
            return ""

        src_lang = src_lang.lower().strip()
        target_lang = target_lang.lower().strip()

        # Same language, no translation needed
        if src_lang == target_lang:
            return text

        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # 1. Check SQLite Cache
        conn = sqlite3.connect(str(self.cache_db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT translated_text FROM Translations WHERE source_hash = ? AND src_lang = ? AND target_lang = ?",
            (source_hash, src_lang, target_lang)
        )
        row = cur.fetchone()
        if row and row[0]:
            conn.close()
            logger.info(f"[TRANSLATION CACHE HIT] Retrieved '{target_lang}' translation instantly.")
            return row[0]

        # 2. Run MarianMT Translation
        logger.info(f"Translating text ({len(text)} chars) from '{src_lang}' to '{target_lang}' via MarianMT...")
        model, tokenizer = self._get_model_and_tokenizer(target_lang)

        import torch
        device = "cuda" if self.device == "cuda" and torch.cuda.is_available() else "cpu"
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        if device == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        translated_tokens = model.generate(**inputs, max_length=1024)
        translated_text = tokenizer.decode(translated_tokens[0], skip_special_tokens=True).strip()

        # 3. Save to Cache
        cur.execute(
            """
            INSERT OR REPLACE INTO Translations (source_hash, src_lang, target_lang, source_text, translated_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_hash, src_lang, target_lang, text, translated_text)
        )
        conn.commit()
        conn.close()

        logger.info(f"Translation complete: '{translated_text[:60]}...'")
        return translated_text

