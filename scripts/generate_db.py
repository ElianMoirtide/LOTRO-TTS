#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS Database Generator
Generates a portable SQLite database (NPCs, Quests, Quest_Texts)
from the game's extracted XML data files.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LOTRO-TTS-DB")


def clean_text(text: str | None) -> str | None:
    """Cleans LOTRO text markup (e.g. \\q for quotes) and normalizes whitespace."""
    if text is None:
        return None
    # \q is the LOTRO XML escape sequence for double quotes
    return text.replace(r"\q", '"').strip()


def strip_key_prefix(key_str: str | None) -> str | None:
    """Strips the 'key:' prefix if present."""
    if key_str and key_str.startswith("key:"):
        return key_str[4:]
    return key_str


def find_dir_case_insensitive(parent: Path, name: str) -> Path:
    """Finds a child directory case-insensitively, falling back to direct path."""
    target = parent / name
    if target.exists():
        return target
    if parent.exists():
        for child in parent.iterdir():
            if child.is_dir() and child.name.lower() == name.lower():
                return child
    return target


def find_file_case_insensitive(parent: Path, filename: str) -> Path:
    """Finds a child file case-insensitively, falling back to direct path."""
    target = parent / filename
    if target.exists():
        return target
    if parent.exists():
        for child in parent.iterdir():
            if child.is_file() and child.name.lower() == filename.lower():
                return child
    return target


def create_schema(conn: sqlite3.Connection):
    """Creates the SQLite tables and foreign keys."""
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF;")

    cur.execute("DROP TABLE IF EXISTS Quest_Texts;")
    cur.execute("DROP TABLE IF EXISTS Quests;")
    cur.execute("DROP TABLE IF EXISTS NPCs;")

    cur.execute("""
    CREATE TABLE NPCs (
        id INTEGER PRIMARY KEY,
        name_en TEXT,
        name_de TEXT,
        name_fr TEXT,
        gender TEXT,
        race TEXT,
        url TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE Quests (
        id INTEGER PRIMARY KEY,
        title_en TEXT,
        title_de TEXT,
        title_fr TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE Quest_Texts (
        id TEXT PRIMARY KEY,
        quest_id INTEGER,
        text_type TEXT,
        npc_id INTEGER,
        text_en TEXT,
        text_de TEXT,
        text_fr TEXT,
        order_index INTEGER,
        objective_index INTEGER,
        FOREIGN KEY (quest_id) REFERENCES Quests(id),
        FOREIGN KEY (npc_id) REFERENCES NPCs(id)
    );
    """)

    conn.commit()


def create_indexes(conn: sqlite3.Connection):
    """Creates indexes for fast lookup during TTS queries."""
    cur = conn.cursor()
    cur.execute("CREATE INDEX IF NOT EXISTS idx_npcs_name_de ON NPCs(name_de);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_npcs_name_en ON NPCs(name_en);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_npcs_name_fr ON NPCs(name_fr);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_quest_texts_npc_id ON Quest_Texts(npc_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_quest_texts_quest_id ON Quest_Texts(quest_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_quest_texts_type ON Quest_Texts(text_type);")
    conn.commit()


def generate_database(src_dir: Path, output_db: Path):
    """Main generation logic."""
    start_time = time.time()
    logger.info("Starting LOTRO-TTS SQLite database generation...")
    logger.info(f"Source directory: {src_dir}")
    logger.info(f"Target database:  {output_db}")

    output_db.parent.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        try:
            output_db.unlink()
        except OSError as e:
            logger.warning(f"Could not remove existing database file {output_db}: {e}")

    conn = sqlite3.connect(output_db)
    # Performance tuning for fast bulk insert
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA journal_mode = MEMORY;")

    create_schema(conn)

    npc_dir = find_dir_case_insensitive(src_dir, "npc")
    quests_dir = find_dir_case_insensitive(src_dir, "quests")

    if not npc_dir.exists():
        logger.error(f"NPC directory not found at: {npc_dir}")
        sys.exit(1)
    if not quests_dir.exists():
        logger.error(f"Quests directory not found at: {quests_dir}")
        sys.exit(1)

    # -------------------------------------------------------------
    # 1. Parse localized NPC XML files (npc_de.xml, npc_en.xml, npc_fr.xml)
    # -------------------------------------------------------------
    logger.info("Parsing localized NPC files (en, de, fr)...")
    t0 = time.time()
    npc_localized_names: dict[str, dict[int, str]] = {"en": {}, "de": {}, "fr": {}}

    for lang in ["en", "de", "fr"]:
        lang_file = find_file_case_insensitive(npc_dir, f"npc_{lang}.xml")
        if not lang_file.exists():
            logger.warning(f"Localized NPC file not found: {lang_file}")
            continue

        count = 0
        for _, elem in ET.iterparse(lang_file, events=("end",)):
            if elem.tag == "label":
                key = elem.attrib.get("key", "")
                # Only purely numeric keys are NPC IDs; keys with colons are titles
                if key.isdigit():
                    npc_localized_names[lang][int(key)] = clean_text(elem.attrib.get("value"))
                    count += 1
            elem.clear()
        logger.info(f"  Loaded {count} NPC names for '{lang}' from {lang_file.name}")

    logger.info(f"Localized NPC names loaded in {time.time() - t0:.2f}s")

    # -------------------------------------------------------------
    # 2. Parse NPC.xml and prepare NPCs table rows
    # -------------------------------------------------------------
    logger.info("Parsing NPC.xml...")
    t0 = time.time()
    npc_file = find_file_case_insensitive(npc_dir, "npc.xml")
    if not npc_file.exists():
        logger.error(f"NPC.xml not found at: {npc_file}")
        sys.exit(1)

    # Load scraped races cache if available
    json_cache = npc_dir / "npc_races.json"
    cached_races: dict[str, dict] = {}
    if json_cache.exists():
        try:
            with open(json_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if v.get("race"):
                        cached_races[k] = v
            logger.info(f"Loaded {len(cached_races)} cached races from {json_cache.name}")
        except Exception as e:
            logger.warning(f"Could not load races cache from {json_cache}: {e}")

    npcs_dict: dict[int, tuple] = {}
    for _, elem in ET.iterparse(npc_file, events=("end",)):
        if elem.tag == "NPC":
            nid_str = elem.attrib.get("id")
            if nid_str and nid_str.isdigit():
                nid = int(nid_str)
                name_en = npc_localized_names["en"].get(nid) or clean_text(elem.attrib.get("name"))
                name_de = npc_localized_names["de"].get(nid)
                name_fr = npc_localized_names["fr"].get(nid)
                gender = elem.attrib.get("gender")
                clean_name = name_en.strip("'\"` \t\r\n") if name_en else ""
                race_info = (cached_races.get(clean_name) or cached_races.get(name_en) or {}) if name_en else {}
                race = elem.attrib.get("race") or race_info.get("race")
                url = elem.attrib.get("url") or race_info.get("url")
                npcs_dict[nid] = (nid, name_en, name_de, name_fr, gender, race, url)
        elem.clear()

    logger.info(f"Loaded {len(npcs_dict)} NPCs from NPC.xml in {time.time() - t0:.2f}s")

    # -------------------------------------------------------------
    # 3. Parse localized Quests XML files (quests_de.xml, quests_en.xml, quests_fr.xml)
    # -------------------------------------------------------------
    logger.info("Parsing localized Quest files (en, de, fr)...")
    t0 = time.time()
    quest_labels: dict[str, dict[str, str]] = {"en": {}, "de": {}, "fr": {}}

    for lang in ["en", "de", "fr"]:
        lang_file = find_file_case_insensitive(quests_dir, f"quests_{lang}.xml")
        if not lang_file.exists():
            logger.warning(f"Localized Quest file not found: {lang_file}")
            continue

        count = 0
        for _, elem in ET.iterparse(lang_file, events=("end",)):
            if elem.tag == "label":
                k = elem.attrib.get("key", "")
                v = clean_text(elem.attrib.get("value"))
                stripped_k = strip_key_prefix(k)
                if stripped_k:
                    quest_labels[lang][stripped_k] = v
                    count += 1
            elem.clear()
        logger.info(f"  Loaded {count} labels for '{lang}' from {lang_file.name}")

    logger.info(f"Localized Quest labels loaded in {time.time() - t0:.2f}s")

    # -------------------------------------------------------------
    # 4. Parse quests.xml and build Quests and Quest_Texts tables
    # -------------------------------------------------------------
    logger.info("Parsing quests.xml...")
    t0 = time.time()
    quests_file = find_file_case_insensitive(quests_dir, "quests.xml")
    if not quests_file.exists():
        logger.error(f"quests.xml not found at: {quests_file}")
        sys.exit(1)

    quests_rows: list[tuple] = []
    quest_texts_dict: dict[str, tuple] = {}
    extra_referenced_npcs: dict[int, str] = {}

    for _, quest_elem in ET.iterparse(quests_file, events=("end",)):
        if quest_elem.tag == "quest":
            qid_str = quest_elem.attrib.get("id")
            if not qid_str or not qid_str.isdigit():
                quest_elem.clear()
                continue

            qid = int(qid_str)
            qname = clean_text(quest_elem.attrib.get("name"))
            title_en = quest_labels["en"].get(str(qid)) or qname
            title_de = quest_labels["de"].get(str(qid))
            title_fr = quest_labels["fr"].get(str(qid))
            quests_rows.append((qid, title_en, title_de, title_fr))

            order_idx = 1

            # 4a. Description
            desc_key = quest_elem.attrib.get("description")
            if desc_key:
                tid = strip_key_prefix(desc_key)
                quest_texts_dict[tid] = (
                    tid,
                    qid,
                    "description",
                    None,
                    quest_labels["en"].get(tid),
                    quest_labels["de"].get(tid),
                    quest_labels["fr"].get(tid),
                    order_idx,
                    None
                )
                order_idx += 1

            # 4b. Bestower
            bestower = quest_elem.find("bestower")
            if bestower is not None:
                b_text = bestower.attrib.get("text")
                b_npc_str = bestower.attrib.get("npcId")
                b_npc_id = int(b_npc_str) if b_npc_str and b_npc_str.isdigit() else None
                if b_npc_id and b_npc_id not in npcs_dict:
                    extra_referenced_npcs[b_npc_id] = clean_text(bestower.attrib.get("npcName"))
                if b_text:
                    tid = strip_key_prefix(b_text)
                    quest_texts_dict[tid] = (
                        tid,
                        qid,
                        "bestower",
                        b_npc_id,
                        quest_labels["en"].get(tid),
                        quest_labels["de"].get(tid),
                        quest_labels["fr"].get(tid),
                        order_idx,
                        None
                    )
                    order_idx += 1

            # 4c. Objectives and Objective Dialogs
            objectives = quest_elem.find("objectives")
            if objectives is not None:
                for obj in objectives.findall("objective"):
                    obj_idx_str = obj.attrib.get("index")
                    obj_idx = int(obj_idx_str) if obj_idx_str and obj_idx_str.isdigit() else None

                    # Objective text
                    obj_text = obj.attrib.get("text")
                    if obj_text:
                        tid = strip_key_prefix(obj_text)
                        quest_texts_dict[tid] = (
                            tid,
                            qid,
                            "objective",
                            None,
                            quest_labels["en"].get(tid),
                            quest_labels["de"].get(tid),
                            quest_labels["fr"].get(tid),
                            order_idx,
                            obj_idx
                        )
                        order_idx += 1

                    # Dialogs inside objective
                    for dlg in obj.findall("dialog"):
                        dlg_text = dlg.attrib.get("text")
                        dlg_npc_str = dlg.attrib.get("npcId")
                        dlg_npc_id = int(dlg_npc_str) if dlg_npc_str and dlg_npc_str.isdigit() else None
                        if dlg_npc_id and dlg_npc_id not in npcs_dict:
                            extra_referenced_npcs[dlg_npc_id] = clean_text(dlg.attrib.get("npcName"))
                        if dlg_text:
                            tid = strip_key_prefix(dlg_text)
                            quest_texts_dict[tid] = (
                                tid,
                                qid,
                                "dialog",
                                dlg_npc_id,
                                quest_labels["en"].get(tid),
                                quest_labels["de"].get(tid),
                                quest_labels["fr"].get(tid),
                                order_idx,
                                obj_idx
                            )
                            order_idx += 1

            # 4d. EndDialog
            end_dlg = quest_elem.find("endDialog")
            if end_dlg is not None:
                ed_text = end_dlg.attrib.get("text")
                ed_npc_str = end_dlg.attrib.get("npcId")
                ed_npc_id = int(ed_npc_str) if ed_npc_str and ed_npc_str.isdigit() else None
                if ed_npc_id and ed_npc_id not in npcs_dict:
                    extra_referenced_npcs[ed_npc_id] = clean_text(end_dlg.attrib.get("npcName"))
                if ed_text:
                    tid = strip_key_prefix(ed_text)
                    quest_texts_dict[tid] = (
                        tid,
                        qid,
                        "dialog",
                        ed_npc_id,
                        quest_labels["en"].get(tid),
                        quest_labels["de"].get(tid),
                        quest_labels["fr"].get(tid),
                        order_idx,
                        None
                    )
                    order_idx += 1

            # 4e. CompletionComment
            comp_comment = quest_elem.find("completionComment")
            if comp_comment is not None:
                cc_npc = comp_comment.find("npc")
                cc_npc_id = None
                if cc_npc is not None:
                    cc_npc_str = cc_npc.attrib.get("npcId")
                    cc_npc_id = int(cc_npc_str) if cc_npc_str and cc_npc_str.isdigit() else None
                    if cc_npc_id and cc_npc_id not in npcs_dict:
                        extra_referenced_npcs[cc_npc_id] = clean_text(cc_npc.attrib.get("npcName"))
                for cc_text in comp_comment.findall("text"):
                    t_val = cc_text.attrib.get("text")
                    if t_val:
                        tid = strip_key_prefix(t_val)
                        quest_texts_dict[tid] = (
                            tid,
                            qid,
                            "dialog",
                            cc_npc_id,
                            quest_labels["en"].get(tid),
                            quest_labels["de"].get(tid),
                            quest_labels["fr"].get(tid),
                            order_idx,
                            None
                        )
                        order_idx += 1

            quest_elem.clear()

    logger.info(f"Parsed {len(quests_rows)} quests and {len(quest_texts_dict)} texts in {time.time() - t0:.2f}s")

    # Add any referenced quest-giving entities/objects to NPCs to preserve foreign key integrity
    for nid, name_en in extra_referenced_npcs.items():
        if nid not in npcs_dict:
            clean_name = name_en.strip("'\"` \t\r\n") if name_en else ""
            race_info = (cached_races.get(clean_name) or cached_races.get(name_en) or {}) if name_en else {}
            npcs_dict[nid] = (
                nid,
                name_en,
                npc_localized_names["de"].get(nid),
                npc_localized_names["fr"].get(nid),
                None,
                race_info.get("race"),
                race_info.get("url")
            )
    logger.info(f"Total NPCs (including quest interactables): {len(npcs_dict)}")

    # -------------------------------------------------------------
    # 5. Insert rows into SQLite
    # -------------------------------------------------------------
    logger.info("Writing data to SQLite database...")
    t0 = time.time()
    cur = conn.cursor()
    cur.executemany("INSERT INTO NPCs VALUES (?, ?, ?, ?, ?, ?, ?)", npcs_dict.values())
    cur.executemany("INSERT INTO Quests VALUES (?, ?, ?, ?)", quests_rows)
    cur.executemany("INSERT INTO Quest_Texts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", quest_texts_dict.values())
    conn.commit()
    logger.info(f"Database insertion completed in {time.time() - t0:.2f}s")

    # -------------------------------------------------------------
    # 6. Verify Foreign Key constraints
    # -------------------------------------------------------------
    logger.info("Validating Foreign Key constraints...")
    cur.execute("PRAGMA foreign_key_check;")
    fk_violations = cur.fetchall()
    if fk_violations:
        logger.warning(f"Found {len(fk_violations)} foreign key violations: {fk_violations[:5]}")
    else:
        logger.info("Foreign key check passed: 0 violations.")

    # -------------------------------------------------------------
    # 7. Create indexes & finalize SQLite settings
    # -------------------------------------------------------------
    logger.info("Creating database indexes...")
    t0 = time.time()
    create_indexes(conn)
    logger.info(f"Indexes created in {time.time() - t0:.2f}s")

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.commit()
    conn.close()

    db_size_mb = output_db.stat().st_size / (1024 * 1024)
    total_time = time.time() - start_time
    logger.info(f"Database generated successfully: {output_db} ({db_size_mb:.2f} MB)")
    logger.info(f"Completed in {total_time:.2f} seconds.")


def main():
    # Automatically locate project root based on scripts folder location
    script_dir = Path(__file__).resolve().parent
    default_root = script_dir.parent

    parser = argparse.ArgumentParser(description="Generate LOTRO-TTS SQLite database from XML sources.")
    parser.add_argument(
        "--src",
        type=Path,
        default=default_root / "src",
        help="Path to the 'src' directory containing 'npc' and 'quests' subfolders."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=default_root / "data" / "lotro.db",
        help="Path to the target SQLite database file (default: data/lotro.db)."
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Run silently, showing only warnings and errors."
    )

    args = parser.parse_args()

    if args.quiet:
        logger.setLevel(logging.WARNING)

    generate_database(args.src, args.output)


if __name__ == "__main__":
    main()
