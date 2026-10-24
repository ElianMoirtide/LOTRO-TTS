"""
Deterministic Voice Assignment Module for LOTRO-TTS
Assigns voice_id to all NPCs based on race, gender, and hash(npc_id).
Dynamically reads from voices/de/voice_index.json.
"""

import json
from pathlib import Path


def load_voice_pools(voices_dir: Path | None = None) -> tuple[dict, str]:
    """Loads race pools and default narrator directly from voices/de/voice_index.json."""
    if voices_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
        voices_dir = base_dir / "data" / "voices"

    index_path = voices_dir / "de" / "voice_index.json"
    if not index_path.exists():
        index_path = voices_dir / "en" / "voice_index.json"

    if not index_path.exists():
        return {}, "narrator_1"

    with open(index_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    # Group voice_ids into category pools
    pools_by_category = {}
    for it in items:
        cat = it["category"]
        vid = it["voice_id"]
        if cat not in pools_by_category:
            pools_by_category[cat] = []
        pools_by_category[cat].append(vid)

    # Build canonical race pools mapping: Race -> { "MALE": [...], "FEMALE": [...] }
    race_pools = {
        "Dwarf": {
            "MALE": pools_by_category.get("dwarf_male", ["dwarf_male_1"]),
            "FEMALE": pools_by_category.get("dwarf_female", ["dwarf_female_1"])
        },
        "Stout-axe": {
            "MALE": pools_by_category.get("dwarf_male", ["dwarf_male_1"]),
            "FEMALE": pools_by_category.get("dwarf_female", ["dwarf_female_1"])
        },
        "Zhélruka": {
            "MALE": pools_by_category.get("dwarf_male", ["dwarf_male_1"]),
            "FEMALE": pools_by_category.get("dwarf_female", ["dwarf_female_1"])
        },
        "Elf": {
            "MALE": pools_by_category.get("elf_male", ["elf_male_1"]),
            "FEMALE": pools_by_category.get("elf_female", ["elf_female_1"])
        },
        "High Elf": {
            "MALE": pools_by_category.get("elf_male", ["elf_male_1"]),
            "FEMALE": pools_by_category.get("elf_female", ["elf_female_1"])
        },
        "Hobbit": {
            "MALE": pools_by_category.get("hobbit_male", ["hobbit_male_1"]),
            "FEMALE": pools_by_category.get("hobbit_female", ["hobbit_female_1"])
        },
        "River-folk": {
            "MALE": pools_by_category.get("hobbit_male", ["hobbit_male_1"]),
            "FEMALE": pools_by_category.get("hobbit_female", ["hobbit_female_1"])
        },
        "Man": {
            "MALE": pools_by_category.get("man_male", ["man_male_1"]),
            "FEMALE": pools_by_category.get("man_female", ["man_female_1"])
        },
        "Beorning": {
            "MALE": pools_by_category.get("man_male", ["man_male_1"]),
            "FEMALE": pools_by_category.get("man_female", ["man_female_1"])
        },
        "Orc": {
            "MALE": pools_by_category.get("orc", ["orc_1"]),
            "FEMALE": pools_by_category.get("orc", ["orc_1"])
        },
        "Uruk-hai": {
            "MALE": pools_by_category.get("orc", ["orc_1"]),
            "FEMALE": pools_by_category.get("orc", ["orc_1"])
        },
        "Goblin": {
            "MALE": pools_by_category.get("orc", ["orc_1"]),
            "FEMALE": pools_by_category.get("orc", ["orc_1"])
        },
        "Ent": {
            "MALE": pools_by_category.get("ent", ["ent_1"]),
            "FEMALE": pools_by_category.get("ent", ["ent_1"])
        },
        "Huorn": {
            "MALE": pools_by_category.get("ent", ["ent_1"]),
            "FEMALE": pools_by_category.get("ent", ["ent_1"])
        },
        "Dead": {
            "MALE": pools_by_category.get("dead", ["dead_1"]),
            "FEMALE": pools_by_category.get("dead", ["dead_1"])
        },
        "Giant": {
            "MALE": pools_by_category.get("troll", ["troll_1"]),
            "FEMALE": pools_by_category.get("troll", ["troll_1"])
        }
    }

    default_narrator = pools_by_category.get("narrator", ["narrator_1"])[0]
    return race_pools, default_narrator


# Canonical race name mapping from varied wiki / scraper strings
CANONICAL_RACE_MAP = {
    # Dwarves
    "dwarf": "Dwarf",
    "dwarves": "Dwarf",
    "stout-axe": "Stout-axe",
    "stout-axe dwarves": "Stout-axe",
    "zhélruka": "Zhélruka",
    "zhelruka": "Zhélruka",
    "longbeard": "Dwarf",
    "dourhand": "Dwarf",

    # Elves
    "elf": "Elf",
    "elves": "Elf",
    "high elf": "High Elf",
    "high elves": "High Elf",
    "wood-elf": "Elf",
    "galadhrim": "Elf",
    "half-elven": "Elf",

    # Hobbits
    "hobbit": "Hobbit",
    "hobbits": "Hobbit",
    "river-folk": "River-folk",
    "river hobbit": "River-folk",
    "halfling": "Hobbit",
    "stoor": "Hobbit",

    # Men
    "man": "Man",
    "race of man": "Man",
    "race of men": "Man",
    "men": "Man",
    "woman": "Man",
    "rohirrim": "Man",
    "gondor": "Man",
    "gondorian": "Man",
    "lossoth": "Man",
    "kinta": "Man",
    "kintai": "Man",
    "dunlending": "Man",
    "easterling": "Man",
    "haradrim": "Man",
    "umbarrim": "Man",
    "northmen": "Man",
    "beorning": "Beorning",

    # Orcs / Goblins / Uruks
    "orc": "Orc",
    "orcs": "Orc",
    "orc-kind": "Orc",
    "goblin": "Goblin",
    "goblins": "Goblin",
    "uruk": "Uruk-hai",
    "uruk-hai": "Uruk-hai",
    "half-orc": "Orc",
    "half-orcs": "Orc",

    # Ents / Giants / Dead
    "ent": "Ent",
    "huorn": "Huorn",
    "dead": "Dead",
    "the dead": "Dead",
    "shade": "Dead",
    "wraith": "Dead",
    "nazgûl": "Dead",
    "giant": "Giant",
    "giant-kind": "Giant",
    "half-troll": "Giant",
    "troll": "Giant",
    "earth-kin": "Giant"
}


def get_deterministic_voice_id(npc_id: int, gender: str | None, race: str | None, race_pools: dict, default_narrator: str) -> str:
    """
    Determines voice_id for an NPC deterministically.
    If race and gender are known, selects a voice from the race pool using hash(npc_id).
    If inanimate / no gender, assigns the narrator voice.
    """
    g = (gender or "").upper().strip()
    if g not in ("MALE", "FEMALE"):
        return default_narrator

    canonical_race = "Man"
    if race:
        canonical_race = CANONICAL_RACE_MAP.get(race.lower().strip(), "Man")

    pool_for_race = race_pools.get(canonical_race) or race_pools.get("Man", {})
    gender_pool = pool_for_race.get(g)

    if not gender_pool:
        gender_pool = race_pools.get("Man", {}).get(g, [default_narrator])

    idx = abs(npc_id) % len(gender_pool)
    return gender_pool[idx]
