#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Source XML Updater
Downloads and updates source XML files from the LotroCompanion GitHub repository.
Supports ETags for conditional downloads to save bandwidth and time.
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LOTRO-TTS-Updater")

# GitHub source URLs mapped to local relative file paths
SOURCES = [
    # NPC data
    {
        "name": "npc.xml",
        "rel_path": Path("npc") / "npc.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/NPCs.xml"
    },
    {
        "name": "npc_de.xml",
        "rel_path": Path("npc") / "npc_de.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/de/npc.xml"
    },
    {
        "name": "npc_en.xml",
        "rel_path": Path("npc") / "npc_en.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/en/npc.xml"
    },
    {
        "name": "npc_fr.xml",
        "rel_path": Path("npc") / "npc_fr.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/fr/npc.xml"
    },
    {
        "name": "npc_es.xml",
        "rel_path": Path("npc") / "npc_es.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/es/npc.xml"
    },
    # Quest data
    {
        "name": "quests.xml",
        "rel_path": Path("quests") / "quests.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/quests.xml"
    },
    {
        "name": "quests_de.xml",
        "rel_path": Path("quests") / "quests_de.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/de/quests.xml"
    },
    {
        "name": "quests_en.xml",
        "rel_path": Path("quests") / "quests_en.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/en/quests.xml"
    },
    {
        "name": "quests_fr.xml",
        "rel_path": Path("quests") / "quests_fr.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/fr/quests.xml"
    },
    {
        "name": "quests_es.xml",
        "rel_path": Path("quests") / "quests_es.xml",
        "url": "https://github.com/LotroCompanion/lotro-data/raw/refs/heads/master/lore/labels/es/quests.xml"
    },
]


def load_etags(cache_file: Path) -> dict:
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_etags(cache_file: Path, etags: dict):
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(etags, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save ETag cache: {e}")


def format_bytes(num_bytes: int) -> str:
    """Formats bytes to human-readable string (KB, MB)."""
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def download_file(url: str, target_path: Path, cached_etag: str | None, force: bool = False) -> tuple[bool, str | None]:
    """
    Downloads a single file with progress reporting and atomic temporary file.
    Returns: (was_updated: bool, new_etag: str | None)
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")

    headers = {
        "User-Agent": "LOTRO-TTS-Updater"
    }

    # Only use conditional request if the local target file actually exists
    if not force and cached_etag and target_path.exists():
        headers["If-None-Match"] = cached_etag

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            # 200 OK -> New file to download
            etag = resp.headers.get("ETag")
            total_size = resp.headers.get("Content-Length")
            total_bytes = int(total_size) if total_size and total_size.isdigit() else 0

            downloaded_bytes = 0
            chunk_size = 128 * 1024  # 128 KB
            start_time = time.time()
            last_print = start_time

            print(f"  Downloading {target_path.name} ({format_bytes(total_bytes) if total_bytes else 'unknown size'})...")

            with open(temp_path, "wb") as f_out:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    downloaded_bytes += len(chunk)

                    now = time.time()
                    if total_bytes and (now - last_print >= 0.5 or downloaded_bytes == total_bytes):
                        last_print = now
                        pct = (downloaded_bytes / total_bytes) * 100
                        speed = downloaded_bytes / max(0.001, (now - start_time))
                        speed_str = f"{format_bytes(int(speed))}/s"
                        print(f"\r    [{pct:5.1f}%] {format_bytes(downloaded_bytes)} / {format_bytes(total_bytes)} ({speed_str})", end="", flush=True)

            print()  # Newline after progress bar
            # Atomic replace
            if target_path.exists():
                target_path.unlink()
            temp_path.replace(target_path)

            elapsed = max(0.01, time.time() - start_time)
            avg_speed = format_bytes(int(downloaded_bytes / elapsed))
            logger.info(f"  Saved {target_path.name} ({format_bytes(downloaded_bytes)}) in {elapsed:.1f}s ({avg_speed}/s)")
            return True, etag

    except urllib.error.HTTPError as e:
        if e.code == 304:
            logger.info(f"  {target_path.name} is already up to date (HTTP 304 Not Modified).")
            return False, cached_etag
        else:
            logger.error(f"  HTTP error downloading {target_path.name}: {e.code} {e.reason}")
            if temp_path.exists():
                temp_path.unlink()
            return False, None
    except Exception as e:
        logger.error(f"  Error downloading {target_path.name}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False, None


def update_all(src_dir: Path, force: bool = False, generate_db: bool = False):
    """Updates all source XML files."""
    start_time = time.time()
    logger.info("Starting LOTRO source XML update...")
    logger.info(f"Target directory: {src_dir}")

    cache_file = src_dir / ".etags.json"
    etags = load_etags(cache_file)

    updated_count = 0
    total_files = len(SOURCES)

    for idx, item in enumerate(SOURCES, start=1):
        name = item["name"]
        target = src_dir / item["rel_path"]
        url = item["url"]
        cached_etag = etags.get(str(item["rel_path"]))

        logger.info(f"[{idx}/{total_files}] Checking {name}...")
        was_updated, new_etag = download_file(url, target, cached_etag, force=force)

        if new_etag:
            etags[str(item["rel_path"])] = new_etag

        if was_updated:
            updated_count += 1

    save_etags(cache_file, etags)

    elapsed = time.time() - start_time
    logger.info(f"Update completed in {elapsed:.1f}s. {updated_count}/{total_files} file(s) updated.")

    if generate_db or updated_count > 0:
        if generate_db:
            logger.info("Automatically regenerating SQLite database...")
            # Import and call generate_db directly if present
            try:
                scripts_dir = Path(__file__).resolve().parent
                sys.path.insert(0, str(scripts_dir))
                import generate_db as gen_module
                gen_module.generate_database(src_dir, src_dir.parent / "data" / "lotro.db")
            except Exception as e:
                logger.error(f"Failed to automatically regenerate database: {e}")


def main():
    script_dir = Path(__file__).resolve().parent
    default_root = script_dir.parent

    parser = argparse.ArgumentParser(description="Update LOTRO-TTS source XML files from GitHub.")
    parser.add_argument(
        "--src",
        type=Path,
        default=default_root / "src",
        help="Path to the 'src' directory containing XML sources (default: src)."
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force download of all files even if unchanged."
    )
    parser.add_argument(
        "--generate-db",
        "-g",
        action="store_true",
        help="Automatically regenerate SQLite database after update."
    )

    args = parser.parse_args()
    update_all(args.src, force=args.force, generate_db=args.generate_db)


if __name__ == "__main__":
    main()

