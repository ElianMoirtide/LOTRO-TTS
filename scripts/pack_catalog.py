# -*- coding: utf-8 -*-
"""
Expansion & Content Pack Taxonomy for LOTRO-TTS VoicePacks.
Maps all LOTRO QuestCategory IDs, webStoreItemIDs, geographic regions, and quest levels
into clean, modular Expansion Packs and Auxiliary Packs.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

PACK_DEFINITIONS = [
    {
        "pack_id": "01_eriador_soa",
        "sort_order": 1,
        "tier": "story",
        "name_de": "Eriador & Schatten von Angmar (inkl. Vor dem Schatten)",
        "name_en": "Eriador & Shadows of Angmar (incl. Before the Shadow)",
        "level_range": "1-50",
        "description": "Ered Luin, Auenland, Breeland, Schwanenfleet, Cardolan, Nordhöhen, Evendim, Angmar, Forochel, Nebelgebirge, Epos Band I",
    },
    {
        "pack_id": "02_moria_lothlorien",
        "sort_order": 2,
        "tier": "story",
        "name_de": "Die Minen von Moria & Lothlórien (inkl. Eregion)",
        "name_en": "Mines of Moria & Lothlórien (incl. Eregion)",
        "level_range": "50-60",
        "description": "Eregion, Moria, Lothlórien, Epos Band II (Prolog bis Buch 8)",
    },
    {
        "pack_id": "03_mirkwood_enedwaith",
        "sort_order": 3,
        "tier": "story",
        "name_de": "Die Belagerung des Düsterwalds & Enedwaith",
        "name_en": "Siege of Mirkwood & Enedwaith",
        "level_range": "60-65",
        "description": "Südlicher Düsterwald, Dol Guldur, Enedwaith, Epos Band II Buch 9 & Band III Prolog–Buch 3",
    },
    {
        "pack_id": "04_isengard_great_river",
        "sort_order": 4,
        "tier": "story",
        "name_de": "Der Aufstieg Isengarts & Der Große Fluss",
        "name_en": "Rise of Isengard & The Great River",
        "level_range": "65-75",
        "description": "Dunland, Pforte von Rohan, Isengart, Großer Fluss (Thinglad, Braunlande, Limklar), Epos Band III Buch 4–6",
    },
    {
        "pack_id": "05_rohan_helms_deep",
        "sort_order": 5,
        "tier": "story",
        "name_de": "Die Reiter von Rohan & Helms Klamm",
        "name_en": "Riders of Rohan & Helm's Deep",
        "level_range": "75-95",
        "description": "Ost- & West-Emnet, Hytbold, Wildermark, Fangorn, Edoras, Epische Schlachten, Epos Band III Buch 7–14",
    },
    {
        "pack_id": "06_gondor",
        "sort_order": 6,
        "tier": "story",
        "name_de": "Gondor, Pelennor & Das Ödland",
        "name_en": "Gondor, Pelennor & The Wastes",
        "level_range": "95-105",
        "description": "West-/Zentral-/Ost-Gondor, Alt- & Fernes Anórien, Minas Tirith, Nord-Ithilien, Ödland, Epos Band IV",
    },
    {
        "pack_id": "07_mordor_northern_kingdoms",
        "sort_order": 7,
        "tier": "story",
        "name_de": "Mordor, Nördlicher Düsterwald, Ered Mithrin & Täler des Anduin",
        "name_en": "Mordor, Northern Mirkwood, Ered Mithrin & Vales of Anduin",
        "level_range": "105-120",
        "description": "Schwarzes Buch von Mordor, Gorgoroth, Bündnisse, Eryn Lasgalen, Thalland, Erebor, Zwergenfestungen, Täler des Anduin",
    },
    {
        "pack_id": "08_minas_morgul_three_peaks",
        "sort_order": 8,
        "tier": "story",
        "name_de": "Minas Morgul, Langflut & Krieg der Drei Gipfel",
        "name_en": "Minas Morgul, Wells of Langflood & War of Three Peaks",
        "level_range": "120-130",
        "description": "Imlad Morgul, Belagertes Mordor, Quellen des Langflut, Ältestental, Azanulbizar, Epos Band V",
    },
    {
        "pack_id": "09_gundabad_kings_gondor",
        "sort_order": 9,
        "tier": "story",
        "name_de": "Gundabad, Rückkehr nach Carn Dûm & Königreich Gondor",
        "name_en": "Fate of Gundabad, Return to Carn Dûm & Gondor Renewed",
        "level_range": "130-141",
        "description": "Gundabad, Vermächtnis von Durins Volk, Wiedererstarktes Angmar, Königreich Gondor (Lebennin/Lossarnach)",
    },
    {
        "pack_id": "10_umbar_harad_morgoth",
        "sort_order": 10,
        "tier": "story",
        "name_de": "Korsaren von Umbar, Vermächtnis von Morgoth & Harad",
        "name_en": "Corsairs of Umbar, Legacy of Morgoth & Kingdoms of Harad",
        "level_range": "141-160+",
        "description": "Äußeres Gondor, Schildinseln, Umbar, Lied von Wellen und Wind, Ikorbân-Tal, Mûr Ghala, Draugardh",
    },
    {
        "pack_id": "90_tasks_crafting_misc",
        "sort_order": 90,
        "tier": "auxiliary",
        "name_de": "Aufträge (Tasks), Handwerk, Scharmützel, PvMP & Sonstiges",
        "name_en": "Tasks, Crafting, Skirmishes, PvMP & Miscellaneous",
        "level_range": "1-160",
        "description": "Auftragstafeln (540 Quests), Handwerksgilden & -ereignisse, Ettenöden, Scharmützel, Legendäre Server",
    },
    {
        "pack_id": "91_missions",
        "sort_order": 91,
        "tier": "auxiliary",
        "name_de": "Missionen (Alle Regionen)",
        "name_en": "Missions (All Regions)",
        "level_range": "20-160",
        "description": "Sämtliche wiederholbaren Missionen (Vor dem Schatten, Krieg der Drei Gipfel, Gundabad, Umbar, Harad etc.)",
    },
    {
        "pack_id": "92_festivals",
        "sort_order": 92,
        "tier": "auxiliary",
        "name_de": "Feste & Saisonale Events",
        "name_en": "Festivals & Seasonal Events",
        "level_range": "1-160",
        "description": "Frühlingsfest, Bauernfest, Mittsommer, Erntefest, Julfest/Frostfels, Jubiläumsfest",
    },
]

# Explicit QuestCategory ID -> pack_id overrides for total precision
CATEGORY_TO_PACK: dict[int, str] = {}

def _bind(pack_id: str, cat_ids: list[int]):
    for cid in cat_ids:
        CATEGORY_TO_PACK[cid] = pack_id

# 91_missions
_bind("91_missions", [350, 354, 361, 364, 365, 370, 397, 435, 449, 469, 470, 477, 487])

# 92_festivals
_bind("92_festivals", [55, 59, 65, 100, 114, 195, 198, 289, 296, 347, 353, 468])

# 90_tasks_crafting_misc (Tasks, Level Up, Crafting, Ettenmoors PvMP, Skirmish, Delving, Neighbours, Legendary Servers)
_bind("90_tasks_crafting_misc", [
    112, 15, 25, 60, 62, 69, 102, 312, 396,
    2, 9, 10, 20, 23, 26, 27, 42, 412,
    88, 89, 90, 91, 92, 93, 94, 340, 446, 460, 461, 492,
    306, 307, 308, 309, 310, 313, 324, 325,
    490, 491,
])

# 01_eriador_soa
_bind("01_eriador_soa", [
    1, 3, 4, 5, 6, 7, 8, 11, 13, 14, 17, 18, 19, 22, 28, 29, 31, 32, 33, 34, 35, 37, 38,
    39, 40, 41, 43, 44, 45, 46, 47, 48, 49, 50, 51, 53, 54, 56, 57, 58, 61, 63, 64, 70,
    71, 78, 79, 81, 83, 85, 116, 152, 214, 219, 278, 334, 359,
    # Newer Eriador low/mid regions (Before the Shadow, Wildwood, Yondershire, Angle)
    360, 362, 363, 382, 383, 385, 386, 388, 389, 390, 391, 392, 393, 394, 395, 406, 420,
])

# 02_moria_lothlorien
_bind("02_moria_lothlorien", [
    52, 72, 73, 74, 75, 76, 77, 82, 84, 87, 98, 99, 103, 106, 107,
    120, 121, 122, 123, 124, 125, 126, 127, 128, 129,
])

# 03_mirkwood_enedwaith
_bind("03_mirkwood_enedwaith", [101, 104, 105, 108, 109, 110, 111, 115])

# 04_isengard_great_river
_bind("04_isengard_great_river", [
    113, 117, 118, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140,
    141, 142, 143, 144, 145, 146, 147, 148, 150,
])

# 05_rohan_helms_deep
_bind("05_rohan_helms_deep", [
    153, 154, 155, 156, 157, 158, 159, 168, 169, 170, 171, 172, 175, 176, 177, 178,
    179, 180, 181, 182, 183, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 196,
    197, 199, 200, 201, 344, 345,
])

# 06_gondor
_bind("06_gondor", [
    202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 215, 216, 217, 218,
    220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 232, 233, 234, 235, 236, 237,
    241, 242, 243, 245, 246, 247, 248, 251, 252, 254, 257, 258, 259, 264, 265, 266,
    267, 268, 269, 277,
])

# 07_mordor_northern_kingdoms
_bind("07_mordor_northern_kingdoms", [
    149, 260, 261, 262, 263, 270, 271, 272, 274, 275, 276, 279, 280, 281, 282, 283,
    284, 285, 286, 287, 288,
    290, 291, 292, 293, 294, 295, 297, 298, 300, 301, 302, 303, 304, 305, 311,
    315, 316, 317, 318, 319, 320, 321, 322, 323, 348,
])

# 08_minas_morgul_three_peaks
_bind("08_minas_morgul_three_peaks", [
    326, 327, 328, 329, 330, 331, 332, 333, 335, 336, 337, 338, 339,
    341, 342, 343, 349, 351, 352, 355, 356, 357, 358, 366, 367, 368, 369,
])

# 09_gundabad_kings_gondor
_bind("09_gundabad_kings_gondor", [
    346, 371, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 384,
    400, 401, 402, 403, 404, 405,
    408, 410, 411,
])

# 10_umbar_harad_morgoth
_bind("10_umbar_harad_morgoth", [
    407, 413, 414, 415, 416, 417, 418, 419,
    425, 426, 429, 431, 433, 434, 437, 438, 439, 440, 441, 442, 443, 444, 445, 447, 448,
    450, 451, 452, 453, 454, 465, 466, 467,
    471, 472, 474, 475, 476, 478, 479, 480, 481, 482, 483, 484, 485, 488, 489,
])


def _clean_label(text: str | None) -> str:
    return text.replace(r"\q", '"').strip() if text else ""


def load_lotro_metadata(meta_dir: Path) -> dict:
    """
    Loads LotroCompanion metadata XMLs from src/meta/ to resolve category IDs,
    geographic region IDs, and webStoreItemIDs to localized names.
    """
    categories = {}  # cat_id (int) -> {"en": ..., "de": ..., "fr": ..., "es": ...}
    cat_key_map = {}
    qcat_file = meta_dir / "QuestCategory.xml"
    if qcat_file.exists():
        for elem in ET.parse(qcat_file).getroot():
            if elem.tag == "entry":
                code = elem.attrib.get("code", "")
                if code.isdigit():
                    cat_key_map[int(code)] = elem.attrib.get("name", "")

    cat_labels = {}
    for lang in ("en", "de", "fr", "es"):
        lbl_file = meta_dir / f"labels_{lang}_enum-QuestCategory.xml"
        if lbl_file.exists():
            cat_labels[lang] = {
                el.attrib.get("key", ""): _clean_label(el.attrib.get("value"))
                for el in ET.parse(lbl_file).getroot()
                if el.tag == "label"
            }
        else:
            cat_labels[lang] = {}

    for cid, key in cat_key_map.items():
        categories[cid] = {
            lang: cat_labels[lang].get(key) or cat_labels["en"].get(key) or f"Category {cid}"
            for lang in ("en", "de", "fr", "es")
        }

    regions = {}  # region_code (int) -> {"en": ..., "de": ..., "fr": ..., "es": ...}
    geo_file = meta_dir / "geoAreas.xml"
    geo_en_by_id = {}
    reg_id_by_code = {}
    if geo_file.exists():
        for el in ET.parse(geo_file).getroot():
            if el.tag == "region":
                rid = el.attrib.get("id", "")
                code = el.attrib.get("code", "")
                if code.isdigit():
                    c_int = int(code)
                    reg_id_by_code[c_int] = rid
                    geo_en_by_id[rid] = _clean_label(el.attrib.get("name"))

    geo_labels = {}
    for lang in ("en", "de", "fr", "es"):
        lbl_file = meta_dir / f"labels_{lang}_geoAreas.xml"
        if lbl_file.exists():
            geo_labels[lang] = {
                el.attrib.get("key", ""): _clean_label(el.attrib.get("value"))
                for el in ET.parse(lbl_file).getroot()
                if el.tag == "label"
            }
        else:
            geo_labels[lang] = {}

    for c_int, rid in reg_id_by_code.items():
        regions[c_int] = {
            lang: geo_labels[lang].get(rid) or geo_en_by_id.get(rid) or f"Region {c_int}"
            for lang in ("en", "de", "fr", "es")
        }

    webstore = {}  # ws_id (int) -> str
    ws_file = meta_dir / "webStoreItems.xml"
    if ws_file.exists():
        for el in ET.parse(ws_file).getroot():
            if el.tag == "webStoreItem":
                ws_id = el.attrib.get("id", "")
                if ws_id.isdigit():
                    webstore[int(ws_id)] = _clean_label(el.attrib.get("name"))

    return {
        "categories": categories,
        "regions": regions,
        "webstore": webstore,
    }


def classify_quest_pack(
    category_id: int | None,
    cat_name_en: str = "",
    level: int | None = None,
    region_id: int | None = None,
    web_store_name: str = "",
) -> str:
    """Assigns a quest cleanly to one of the PACK_DEFINITIONS pack_ids."""
    if category_id is not None and category_id in CATEGORY_TO_PACK:
        return CATEGORY_TO_PACK[category_id]

    cname = (cat_name_en or "").lower()
    wname = (web_store_name or "").lower()

    # Keyword heuristics for newly added future LotroCompanion categories
    if cname.startswith("mission"):
        return "91_missions"
    if any(k in cname for k in ("festival", "midsummer", "anniversary", "frostbluff", "farmers faire", "hobnanigans")):
        return "92_festivals"
    if cname.startswith(("task", "craft", "legendary ", "skirmish")) or cname in ("reputation", "neighbour", "neighbours", "delving"):
        return "90_tasks_crafting_misc"

    if any(k in wname for k in ("harad", "morgoth", "umbar", "wolves of mordor", "verses of victory", "hamât", "glorious hunt")):
        return "10_umbar_harad_morgoth"
    if any(k in wname for k in ("gundabad", "carn dûm", "gondor renewed")):
        return "09_gundabad_kings_gondor"
    if any(k in wname for k in ("morgul", "mordor besieged", "three peaks", "elderslade", "azanulbizar", "wilderland")):
        return "08_minas_morgul_three_peaks"
    if any(k in wname for k in ("gorgoroth", "black book", "mirkwood", "dwarf-holds", "vales of anduin")):
        return "07_mordor_northern_kingdoms"
    if any(k in wname for k in ("gondor", "anórien", "wastes", "mountains of shadow")):
        return "06_gondor"

    # Level / Region fallback for completely new landscape categories
    lv = level if (level is not None and level > 0) else 0
    if lv >= 142 or region_id in (5, 6):
        return "10_umbar_harad_morgoth"
    if lv >= 131:
        return "09_gundabad_kings_gondor"
    if lv >= 121:
        return "08_minas_morgul_three_peaks"
    if lv >= 106:
        return "07_mordor_northern_kingdoms"
    if lv >= 96 or region_id in (3, 4):
        return "06_gondor"
    if lv >= 76:
        return "05_rohan_helms_deep"
    if lv >= 66:
        return "04_isengard_great_river"
    if lv >= 61:
        return "03_mirkwood_enedwaith"
    if lv >= 51:
        return "02_moria_lothlorien"
    return "01_eriador_soa"
