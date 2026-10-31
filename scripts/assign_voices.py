"""
Deterministic Voice Assignment Module for LOTRO-TTS
Assigns voice_id to all NPCs:
1. Prioritizes authentic 1:1 NPC voices (npc_<id>) verified via Quest DB transcripts.
2. Otherwise assigns deterministically from the 190 deduplicated category voices based on race, gender, and hash(npc_id).
Dynamically reads from data/voices/de/voice_index.json.
"""

import json
import unicodedata
from pathlib import Path


def _norm_name(name: str | None) -> str:
    if not name:
        return ""
    s = name.strip().strip("'\"` \t\r\n").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def load_voice_pools(voices_dir: Path | None = None) -> tuple[dict, str]:
    """Loads race pools, 1:1 NPC voice mappings, and default narrator directly from voice_index.json."""
    if voices_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
        voices_dir = base_dir / "data" / "voices"

    index_path = voices_dir / "de" / "voice_index.json"
    if not index_path.exists():
        index_path = voices_dir / "en" / "voice_index.json"

    if not index_path.exists():
        return {}, "man_male_1"

    with open(index_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    # Group voice_ids into category pools and verified 1:1 NPC lookup tables
    pools_by_category = {}
    verified_npc_id_map = {}    # int(npc_id) -> voice_id
    verified_npc_name_map = {}  # norm_name -> voice_id

    for it in items:
        cat = it["category"]
        vid = it["voice_id"]
        if cat not in pools_by_category:
            pools_by_category[cat] = []
        pools_by_category[cat].append(vid)

        # Primary NPC of this category voice
        if it.get("npc_id"):
            verified_npc_id_map[int(it["npc_id"])] = vid
        if it.get("npc_name"):
            norm = _norm_name(it["npc_name"])
            if norm:
                verified_npc_name_map[norm] = vid

        # All other verified 1:1 Quest-DB NPCs sharing this voice actor
        for nid in it.get("verified_npc_ids", []):
            if int(nid) not in verified_npc_id_map:
                verified_npc_id_map[int(nid)] = vid
        for nname in it.get("verified_npc_names", []):
            norm = _norm_name(nname)
            if norm and norm not in verified_npc_name_map:
                verified_npc_name_map[norm] = vid

    # Build canonical race pools mapping: Race -> { "MALE": [...], "FEMALE": [...] }
    race_pools = {
        "_verified_npc_ids": verified_npc_id_map,
        "_verified_npc_names": verified_npc_name_map,
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

    narrator_pool = pools_by_category.get("narrator") or pools_by_category.get("man_male") or ["man_male_1"]
    default_narrator = narrator_pool[0]
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
    "temámir": "Dwarf",
    "temamir": "Dwarf",
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
    "kinta": "Elf",
    "kintai": "Elf",
    "river-maid": "Elf",

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
    "ordâkhai": "Orc",
    "ordakhai": "Orc",
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
    "nazgul": "Dead",
    "giant": "Giant",
    "giant-kind": "Giant",
    "half-troll": "Giant",
    "troll": "Giant",
    "rogmul": "Giant",
    "earth-kin": "Giant"
}


def get_deterministic_voice_id(
    npc_id: int,
    gender: str | None,
    race: str | None,
    race_pools: dict,
    default_narrator: str,
    name_en: str | None = None,
) -> str:
    """
    Determines voice_id for an NPC deterministically:
    1. Exact verified Quest-DB NPC match by npc_id -> authentic voice actor (<category>_<idx>).
    2. Verified Quest-DB NPC match by name_en -> authentic voice actor (<category>_<idx>).
    3. Category voice from the race/gender pool using hash(npc_id).
    """
    verified_ids = race_pools.get("_verified_npc_ids", {})
    if int(npc_id) in verified_ids:
        return verified_ids[int(npc_id)]

    if name_en:
        norm = _norm_name(name_en)
        verified_names = race_pools.get("_verified_npc_names", {})
        if norm in verified_names:
            return verified_names[norm]

    canonical_race = None
    if race:
        canonical_race = CANONICAL_RACE_MAP.get(race.lower().strip())
        if not canonical_race and "river-maid" in race.lower():
            canonical_race = "Elf"
            gender = gender or "FEMALE"

    g = (gender or "").upper().strip()
    if g not in ("MALE", "FEMALE"):
        if canonical_race in ("Ent", "Huorn", "Dead", "Orc", "Uruk-hai", "Goblin", "Giant"):
            g = "MALE"
        else:
            return default_narrator

    if not canonical_race:
        canonical_race = "Man"

    pool_for_race = race_pools.get(canonical_race) or race_pools.get("Man", {})
    gender_pool = pool_for_race.get(g)

    if not gender_pool:
        gender_pool = race_pools.get("Man", {}).get(g, [default_narrator])

    idx = abs(npc_id) % len(gender_pool)
    return gender_pool[idx]
