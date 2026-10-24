#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS NPC Race Scraper
Scrapes NPC race and wiki URLs from lotro-wiki.com.
Features:
- Solves bot-sentry Proof-of-Work anti-bot challenge automatically.
- Strips leading/trailing quotes (e.g. 'Frodo Baggins' -> Frodo Baggins).
- Robust HTML parsing for race tags (including linked headers like Ashrokil).
- Category-based race extraction when table has no explicit Race row (e.g. Achardis -> Umbarrim -> Man).
- OpenSearch candidate resolution for multi-location NPCs (e.g. Sindri, Reykur),
  distinguishing friendly Quest NPCs from hostile creatures.
- Epithet and title stripping for lookup (e.g. Angbor the Fearless -> Angbor).
- Automatically exports all remaining unresolved NPCs to src/npc/unresolved_npcs.txt
  with a pre-formatted prompt ready to copy & paste into any AI (ChatGPT, Claude, Gemini, etc.).
- Import function (--import-file) to easily import AI responses back into cache and database.
- Persistent JSON cache in src/npc/npc_races.json, only re-querying entries with NULL race or URL.
"""

import argparse
import hashlib
import http.cookiejar
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LOTRO-Race-Scraper")

VALID_RACES = {
    "Hobbit", "Man", "Dwarf", "Elf", "High Elf", "Beorning", "Stout-axe",
    "River-folk", "Dúnadan", "Dúnedain", "Orc", "Uruk-hai", "Half-orc",
    "Goblin", "Troll", "Spider", "Dragon-kind", "Dead", "Ancient Evil",
    "Gaunt Man", "Giant", "Eagle", "Ent", "Huorn"
}

# Mapping of LOTRO Wiki categories to canonical races
CATEGORY_TO_RACE = {
    # Hobbits
    "hobbits": "Hobbit",
    "hobbit_npcs": "Hobbit",
    "fallohides": "Hobbit",
    "harfoots": "Hobbit",
    "stoors": "Hobbit",
    "river-folk": "River-folk",

    # Dwarves
    "dwarves": "Dwarf",
    "dwarf_npcs": "Dwarf",
    "longbeards": "Dwarf",
    "zhélruka": "Dwarf",
    "zhelruka": "Dwarf",
    "stout-axes": "Stout-axe",
    "firebeards": "Dwarf",
    "broadbeams": "Dwarf",
    "ironfold_dwarves": "Dwarf",
    "temámir": "Dwarf",
    "temamir": "Dwarf",
    "abnúshu": "Dwarf",
    "kambrúshu": "Dwarf",

    # Elves
    "elves": "Elf",
    "elf_npcs": "Elf",
    "high_elves": "High Elf",
    "silvan_elves": "Elf",
    "noldor": "High Elf",
    "sindar": "Elf",
    "avari": "Elf",
    "galadhrim": "Elf",
    "rivendell_elves": "Elf",
    "lothlórien_elves": "Elf",
    "mirkwood_elves": "Elf",

    # Men
    "men": "Man",
    "man_npcs": "Man",
    "dúnedain": "Man",
    "dunedain": "Man",
    "rangers_of_the_north": "Man",
    "rangers_of_ithilien": "Man",
    "rohirrim": "Man",
    "gondorians": "Man",
    "men_of_bree": "Man",
    "bree-landers": "Man",
    "men_of_dale": "Man",
    "dale-men": "Man",
    "beornings": "Beorning",
    "lossoth": "Man",
    "hill-men": "Man",
    "angmarim": "Man",
    "dunlendings": "Man",
    "haradrim": "Man",
    "umbarrim": "Man",
    "easterlings": "Man",
    "woodmen": "Man",
    "corsairs": "Man",
    "black_númenóreans": "Man",
    "black_numenoreans": "Man",
    "kintai": "Man",
    "phetekâri": "Man",
    "jangovar": "Man",
    "khundolar": "Man",
    "variags": "Man",

    # Orcs, Goblins, etc.
    "orcs": "Orc",
    "orc_npcs": "Orc",
    "goblins": "Goblin",
    "goblin_npcs": "Goblin",
    "uruk-hai": "Uruk-hai",
    "half-orcs": "Half-orc",
    "trolls": "Troll",

    # Other creatures
    "eagles": "Eagle",
    "ents": "Ent",
    "huorns": "Huorn",
    "giants": "Giant"
}


def clean_npc_name(name: str | None) -> str:
    """Strips leading and trailing quotes, backticks, and whitespace."""
    if not name:
        return ""
    return name.strip("'\"` \t\r\n")


def is_dummy_name(name: str) -> bool:
    """Checks if a name is an internal LOTRO dummy, task level range, or non-character identifier."""
    # E.g. "0-10", "101-110", "???", "---", pure numbers
    if re.match(r"^[\d\s\-\+\.\,\?\!/]+$", name):
        return True
    return False


class LotroWikiScraper:
    def __init__(self, user_agent: str | None = None):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        self.base_url = "https://lotro-wiki.com"
        self._verified = False

    def warm_up(self):
        """Warms up the session by visiting Main_Page and solving challenge if needed."""
        logger.info("Connecting to lotro-wiki.com...")
        self.get_html(f"{self.base_url}/wiki/Main_Page")
        if self._verified:
            logger.info("Session verified and ready.")

    def _solve_challenge(self, html: str, current_url: str) -> bool:
        """Solves the bot-sentry Proof-of-Work challenge."""
        m = re.search(r"var C\s*=\s*(\{.*?\});", html)
        if not m:
            logger.warning("Bot challenge detected, but configuration 'C' not found.")
            return False

        try:
            C = json.loads(m.group(1))
            ch = C["ch"].encode("utf-8")
            d = C.get("d", 5)
            target = "0" * d

            logger.info(f"Solving bot-sentry challenge (difficulty {d})...")
            t0 = time.time()
            nonce = 0
            while True:
                digest = hashlib.sha256(ch + str(nonce).encode("ascii")).hexdigest()
                if digest.startswith(target):
                    break
                nonce += 1

            elapsed_ms = int((time.time() - t0) * 1000)
            logger.info(f"Solved challenge (nonce={nonce}) in {elapsed_ms}ms")

            verify_url = f"{self.base_url}/_/verify"
            post_data = urllib.parse.urlencode({
                "id": C["id"],
                "nonce": str(nonce),
                "elapsed_ms": str(elapsed_ms)
            }).encode("utf-8")

            req = urllib.request.Request(
                verify_url,
                data=post_data,
                headers={
                    "User-Agent": self.user_agent,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": current_url,
                    "Origin": self.base_url
                }
            )

            try:
                with self.opener.open(req, timeout=15) as resp:
                    resp.read()
            except urllib.error.HTTPError as e:
                # Redirect 404 is fine as long as cookie was set
                if e.code == 404:
                    pass
                else:
                    raise

            self._verified = True
            return True
        except Exception as e:
            logger.error(f"Error solving challenge: {e}")
            return False

    def get_html(self, url: str) -> str | None:
        """Fetches page HTML, automatically solving anti-bot challenge when encountered."""
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with self.opener.open(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

                # Check if challenge is presented
                if "Checking your browser" in html or "var C =" in html:
                    if self._solve_challenge(html, url):
                        with self.opener.open(req, timeout=15) as resp2:
                            return resp2.read().decode("utf-8", errors="ignore")
                    else:
                        return None
                return html
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            logger.warning(f"HTTP {e.code} for {url}")
            return None
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            return None

    def opensearch(self, name: str) -> list[tuple[str, str]]:
        """Queries lotro-wiki's MediaWiki OpenSearch API for candidate titles and URLs."""
        url = f"{self.base_url}/w/api.php?action=opensearch&search={urllib.parse.quote(name)}&format=json"
        html = self.get_html(url)
        if not html:
            return []
        try:
            data = json.loads(html)
            titles = data[1]
            urls = data[3]
            return list(zip(titles, urls))
        except Exception:
            return []

    def scrape_npc(self, raw_name: str) -> tuple[str | None, str | None]:
        """
        Scrapes race and wiki URL for an NPC name.
        Returns: (race, canonical_wiki_url)
        """
        name = clean_npc_name(raw_name)
        if not name or is_dummy_name(name):
            return None, None

        # 1. Direct page lookup
        encoded_name = urllib.parse.quote(name.replace(" ", "_"))
        wiki_url = f"{self.base_url}/wiki/{encoded_name}"
        html = self.get_html(wiki_url)

        if html and "There is currently no text in this page" not in html and "noarticletext" not in html:
            if "Disambiguation_Pages" not in html and "may refer to:" not in html:
                race = self._extract_race(html)
                if race:
                    return race, wiki_url

        # 2. Try base name without epithets/titles (e.g. "Angbor the Fearless" -> "Angbor")
        base_name = re.sub(r"\s+the\s+.*$", "", name, flags=re.IGNORECASE).strip()
        if base_name != name and len(base_name) > 2:
            base_url = f"{self.base_url}/wiki/{urllib.parse.quote(base_name.replace(' ', '_'))}"
            base_html = self.get_html(base_url)
            if base_html and "There is currently no text in this page" not in base_html and "noarticletext" not in base_html:
                if "Disambiguation_Pages" not in base_html and "may refer to:" not in base_html:
                    race = self._extract_race(base_html)
                    if race:
                        return race, base_url

        # 3. Try OpenSearch candidates
        candidates = self.opensearch(name)
        if not candidates and base_name != name:
            candidates = self.opensearch(base_name)

        for title, sub_url in candidates:
            # Candidate should match "Name (Location)" or exact title
            if title.startswith(name + " (") or title.lower() == name.lower() or (base_name != name and title.startswith(base_name + " (")):
                sub_html = self.get_html(sub_url)
                if sub_html and self._is_npc_page(sub_html):
                    race = self._extract_race(sub_html)
                    if race:
                        return race, sub_url

        return None, None

    def _extract_race(self, html: str) -> str | None:
        """Extracts race from infobox table first, then falls back to page categories."""
        # 1. Table row check
        race = self._parse_race_from_html(html)
        if race:
            return race

        # 2. Categories check (e.g. Achardis has category Umbarrim -> Man)
        cats = re.findall(r'/wiki/Category:([^"#]+)', html)
        cat_race = self._extract_race_from_categories(cats)
        if cat_race:
            return cat_race

        return None

    @staticmethod
    def _extract_race_from_categories(cats: list[str]) -> str | None:
        for cat in cats:
            cat_clean = cat.lower().replace("+", "_").replace(" ", "_")
            for key, race in CATEGORY_TO_RACE.items():
                if key == cat_clean or f"_{key}" in cat_clean or f"{key}_" in cat_clean:
                    return race
        return None

    @staticmethod
    def _is_npc_page(html: str) -> bool:
        """Determines if a page represents a friendly Quest NPC vs a hostile Creature/Monster."""
        cats = re.findall(r'/wiki/Category:([^"#]+)', html)
        cats_str = ' '.join(cats).lower()

        # Definite NPC signals
        if any(k in cats_str for k in ['npc', 'quest_giver', 'trainer', 'vendor', 'service', 'task']):
            return True

        # Pure hostile monster signals
        if any(k in cats_str for k in ['creatures_by_', 'creatures', 'gaunt_men', 'drakes', 'brigands', 'orcs_of_']):
            if not any(k in cats_str for k in ['npc', 'quest_']):
                return False

        return True

    @staticmethod
    def _parse_race_from_html(html: str) -> str | None:
        """
        Parses Race from infobox tables in wiki HTML.
        Handles both plain text and hyperlinked labels:
        - <td>Race</td><td>Hobbit</td>
        - <td><a ...>Race</a></td><td>Orc</td>
        - <th>Race</th><td>...</td>
        """
        patterns = [
            r'<t[dh][^>]*>\s*(?:<a[^>]*>)?Race(?:</a>)?\s*</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>',
            r'>Race\s*[:]?\s*(?:</[^>]+>)?\s*<t[dh][^>]*>(.*?)</t[dh]>',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if m:
                raw_td = m.group(1)
                clean = re.sub(r'<[^>]+>', '', raw_td).strip()
                clean = re.sub(r'\[\d+\]', '', clean).strip()
                first_line = clean.split("\n")[0].strip()
                if first_line:
                    cap = first_line.capitalize()
                    for vr in VALID_RACES:
                        if cap.lower() == vr.lower():
                            return vr
                    return cap
        return None


def query_ai_race(name: str) -> str | None:
    """
    Fallback to AI API to query the race of an NPC when Wiki search yields no result.
    Checks GEMINI_API_KEY if present, otherwise uses free Open AI API.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    prompt = (
        f'In the MMORPG Lord of the Rings Online (LOTRO), what is the race of the character/NPC named "{name}"? '
        f'Answer with ONLY the race name (e.g. Hobbit, Man, Dwarf, Elf, Orc, Beorning, etc.) or "Unknown" if not known.'
    )

    # 1. Try Gemini REST API if key is available
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            req_data = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}]
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                race = _validate_race_response(text)
                if race:
                    return race
        except Exception as e:
            logger.debug(f"Gemini API query failed for {name}: {e}")

    # 2. Try Pollinations Free AI API (with 5s timeout to not stall)
    try:
        url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode("utf-8").strip()
            race = _validate_race_response(text)
            if race:
                return race
    except Exception as e:
        logger.debug(f"Free AI query failed for {name}: {e}")

    # 3. Rule-based name fallback (e.g. "Evil Dwarf" -> Dwarf)
    for vr in ["Dwarf", "Hobbit", "Elf", "Orc", "Goblin", "Troll", "Spider"]:
        if vr.lower() in name.lower().split():
            return vr

    return None


def _validate_race_response(text: str) -> str | None:
    """Validates and formats an AI response string to a valid race."""
    if not text:
        return None
    clean = re.sub(r'[^a-zA-Z\- ]', '', text).strip()
    if "unknown" in clean.lower():
        return None
    for vr in VALID_RACES:
        if clean.lower() == vr.lower():
            return vr
    words = clean.split()
    if len(words) == 1 and len(clean) < 20:
        return clean.capitalize()
    return None


def load_cache(json_path: Path) -> dict[str, dict]:
    """Loads existing cache from JSON."""
    cache = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    cache[k] = {
                        "race": v.get("race"),
                        "url": v.get("url")
                    }
            logger.info(f"Loaded {len(cache)} cached entries from {json_path.name}")
        except Exception as e:
            logger.warning(f"Could not load JSON cache {json_path}: {e}")
    return cache


def save_cache(json_path: Path, cache: dict[str, dict]):
    """Saves cache to JSON file atomically."""
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        temp_json = json_path.with_suffix(".tmp")
        with open(temp_json, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        if json_path.exists():
            json_path.unlink()
        temp_json.replace(json_path)
    except Exception as e:
        logger.error(f"Error saving JSON cache to {json_path}: {e}")


def get_npc_data_from_db(db_path: Path) -> list[tuple[str, str | None]]:
    """Gets distinct English NPC names along with their gender from the database."""
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT name_en, MAX(gender) 
        FROM NPCs 
        WHERE name_en IS NOT NULL AND name_en != '' 
        GROUP BY name_en 
        ORDER BY name_en;
    """)
    rows = cur.fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows if r[0]]


def update_database(db_path: Path, cache: dict[str, dict]):
    """Updates the SQLite database with scraped races and URLs."""
    if not db_path.exists():
        logger.error(f"Cannot update database: {db_path} not found.")
        return

    logger.info("Applying scraped races to SQLite database...")
    t0 = time.time()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA journal_mode = MEMORY;")
    cur = conn.cursor()

    updates = []
    for name, info in cache.items():
        race = info.get("race")
        url = info.get("url")
        if race:
            clean = clean_npc_name(name)
            updates.append((race, url, name))
            if clean != name:
                updates.append((race, url, clean))

    cur.executemany("UPDATE NPCs SET race = ?, url = ? WHERE name_en = ?;", updates)
    conn.commit()
    conn.close()

    logger.info(f"Database update complete in {time.time() - t0:.2f}s.")


def export_unresolved(export_path: Path, unresolved_names: list[str]):
    """
    Exports remaining unresolved names into an AI-ready prompt text file.
    The user can simply copy the contents into ChatGPT, Claude, Gemini, etc.
    """
    try:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            f.write("# LOTRO-TTS Unresolved NPCs\n")
            f.write("# Copy the prompt below into ChatGPT, Claude, or Gemini to resolve the races.\n")
            f.write("# Save the answer into a text file and import via:\n")
            f.write("#   run_scrape_races.bat --import-file <filename>\n\n")
            f.write("--- PROMPT START ---\n")
            f.write("You are an expert on Lord of the Rings Online (LOTRO) lore and NPCs.\n")
            f.write("For each NPC name below, identify their Race in LOTRO.\n")
            f.write("Valid Races: Hobbit, Man, Dwarf, Elf, High Elf, Beorning, Stout-axe, River-folk, Orc, Goblin, Uruk-hai, Half-orc, Troll, Giant, Eagle, Ent, Huorn, or Inanimate/None (if it is an object/letter/board).\n\n")
            f.write("Format your output strictly line by line as:\n")
            f.write("NPC Name = Race\n\n")
            f.write("NPC Names:\n")
            for name in unresolved_names:
                f.write(f"{name}\n")
            f.write("--- PROMPT END ---\n")
        logger.info(f"Exported {len(unresolved_names)} unresolved NPCs to prompt file: {export_path}")
    except Exception as e:
        logger.error(f"Error exporting unresolved NPCs: {e}")


def import_ai_file(import_path: Path, cache_path: Path, db_path: Path):
    """
    Imports AI-generated responses (format 'Name = Race' or 'Name: Race')
    into cache and updates SQLite database.
    """
    if not import_path.exists():
        logger.error(f"Import file not found: {import_path}")
        return

    logger.info(f"Importing AI resolutions from {import_path}...")
    cache = load_cache(cache_path)
    count = 0

    with open(import_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("---"):
                continue

            # Split on '=' or ':'
            sep = "=" if "=" in line else (":" if ":" in line else None)
            if not sep:
                continue

            parts = line.split(sep, 1)
            raw_name = clean_npc_name(parts[0].strip())
            raw_race = parts[1].strip()

            validated_race = _validate_race_response(raw_race)
            if validated_race and raw_name:
                cache[raw_name] = {
                    "race": validated_race,
                    "url": "API"
                }
                count += 1

    save_cache(cache_path, cache)
    logger.info(f"Successfully imported {count} NPC races from {import_path.name}")
    update_database(db_path, cache)


def main():
    script_dir = Path(__file__).resolve().parent
    default_root = script_dir.parent

    parser = argparse.ArgumentParser(description="Scrape NPC races from lotro-wiki.com.")
    parser.add_argument(
        "--db",
        type=Path,
        default=default_root / "data" / "lotro.db",
        help="Path to SQLite database (default: data/lotro.db)."
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=default_root / "src" / "npc" / "npc_races.json",
        help="Path to JSON cache file (default: src/npc/npc_races.json)."
    )
    parser.add_argument(
        "--export-file",
        type=Path,
        default=default_root / "src" / "npc" / "unresolved_npcs.txt",
        help="Path to export unresolved names prompt file (default: src/npc/unresolved_npcs.txt)."
    )
    parser.add_argument(
        "--import-file",
        type=Path,
        default=None,
        help="Import AI-generated responses from a text file ('Name = Race')."
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Maximum number of new/unscraped NPCs to query in this run."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay between requests in seconds (default: 0.2)."
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-scrape even if already present in cache."
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Disable AI API fallback."
    )
    parser.add_argument(
        "--update-db",
        "-u",
        action="store_true",
        default=True,
        help="Update the SQLite database with the scraped races (default: True)."
    )

    args = parser.parse_args()

    # Handle import if requested
    if args.import_file:
        import_ai_file(args.import_file, args.cache, args.db)
        return

    logger.info("Starting LOTRO-TTS NPC Race Scraper...")
    logger.info(f"Database: {args.db}")
    logger.info(f"Cache file: {args.cache}")

    cache = load_cache(args.cache)

    npc_records = get_npc_data_from_db(args.db)
    if not npc_records:
        logger.error("No NPC names found to scrape.")
        return

    # Filter names: only query names that are NOT yet cached OR have NULL race or NULL url
    to_scrape = []
    unresolved_for_export = []

    for raw_name, gender in npc_records:
        clean = clean_npc_name(raw_name)
        if is_dummy_name(clean):
            continue

        entry = cache.get(clean) or cache.get(raw_name)
        is_resolved = entry and entry.get("race") and entry.get("url")

        if args.force or not is_resolved:
            to_scrape.append(raw_name)
            # Only export characters (having a gender or likely person) to avoid polluting AI with inanimate objects
            if gender in ("MALE", "FEMALE"):
                unresolved_for_export.append(clean)

    total_unresolved = len(to_scrape)
    logger.info(f"Total distinct names: {len(npc_records)} | Unresolved (NULL race/url): {total_unresolved}")
    logger.info(f"Characters without race (with gender): {len(unresolved_for_export)}")

    # Always generate/update the unresolved prompt export file so the user can easily copy it
    export_unresolved(args.export_file, unresolved_for_export)

    if args.limit and args.limit > 0:
        to_scrape = to_scrape[:args.limit]
        logger.info(f"Processing next {len(to_scrape)} NPCs for this run.")

    if not to_scrape:
        logger.info("All NPC names are already resolved! Nothing to scrape.")
        if args.update_db:
            update_database(args.db, cache)
        return

    scraper = LotroWikiScraper()
    scraper.warm_up()

    count_scraped = 0
    count_found = 0
    save_interval = 15

    start_time = time.time()
    try:
        for idx, raw_name in enumerate(to_scrape, start=1):
            clean = clean_npc_name(raw_name)

            # 1. Wiki scrape (includes categories & epithet resolution)
            race, wiki_url = scraper.scrape_npc(clean)

            # 2. AI Fallback if not found on Wiki
            if not race and not args.no_ai:
                ai_race = query_ai_race(clean)
                if ai_race:
                    race = ai_race
                    wiki_url = "API"

            # Store in cache
            cache_entry = {"race": race, "url": wiki_url}
            cache[clean] = cache_entry
            if raw_name != clean:
                cache[raw_name] = cache_entry

            count_scraped += 1
            if race:
                count_found += 1

            race_disp = race if race else "-"
            url_disp = wiki_url if wiki_url else "-"
            pct = (idx / len(to_scrape)) * 100
            print(f"[{idx:4d}/{len(to_scrape):4d}] ({pct:5.1f}%) {raw_name[:32]:32s} -> {race_disp:12s} ({url_disp})")

            # Periodic checkpoint save
            if count_scraped % save_interval == 0:
                save_cache(args.cache, cache)

            if args.delay > 0:
                time.sleep(args.delay)

    except KeyboardInterrupt:
        logger.info("\nScraping interrupted by user. Saving current progress...")
    finally:
        save_cache(args.cache, cache)
        logger.info(f"Saved {len(cache)} entries to {args.cache}")

    elapsed = time.time() - start_time
    logger.info(f"Completed {count_scraped} queries in {elapsed:.1f}s. Resolved race for {count_found} NPCs.")

    # Re-export remaining unresolved list after the run
    remaining_unresolved = [
        name for name in unresolved_for_export 
        if not (cache.get(name) and cache[name].get("race"))
    ]
    export_unresolved(args.export_file, remaining_unresolved)

    if args.update_db:
        update_database(args.db, cache)


if __name__ == "__main__":
    main()
