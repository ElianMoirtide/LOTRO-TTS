#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOTRO-TTS NPC Race Scraper
Scrapes NPC race and wiki URLs from lotro-wiki.com.
Automatically solves the bot-sentry Proof-of-Work challenge and maintains
a persistent JSON cache in src/npc/npc_races.json to avoid redundant requests.
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
        logger.info("Initializing connection to lotro-wiki.com...")
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
                # When verifying, the server redirects to the original page.
                # If that original page returns 404, the verification cookie
                # was still received and saved into cookie_jar.
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
                        # Retry with the new verification cookie
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

    def scrape_npc(self, raw_name: str) -> tuple[str | None, str | None]:
        """
        Scrapes race and wiki URL for an NPC name.
        Returns: (race, canonical_wiki_url)
        """
        name = clean_npc_name(raw_name)
        if not name or is_dummy_name(name):
            return None, None

        encoded_name = urllib.parse.quote(name.replace(" ", "_"))
        wiki_url = f"{self.base_url}/wiki/{encoded_name}"

        html = self.get_html(wiki_url)
        if not html:
            return None, None

        # Check for missing page
        if "There is currently no text in this page" in html or "noarticletext" in html:
            return None, None

        # Check for disambiguation page
        if "Disambiguation_Pages" in html or "may refer to:" in html:
            links = re.findall(r'<a href="(/wiki/[^"#:]+)"[^>]*>([^<]+)</a>', html)
            for href, text in links:
                if text.startswith(name + " (") or href.startswith(f"/wiki/{encoded_name}_("):
                    sub_url = f"{self.base_url}{href}"
                    sub_html = self.get_html(sub_url)
                    if sub_html:
                        race = self._parse_race_from_html(sub_html)
                        if race:
                            return race, sub_url
            return None, wiki_url

        race = self._parse_race_from_html(html)
        return race, wiki_url

    @staticmethod
    def _parse_race_from_html(html: str) -> str | None:
        """Parses Race from infobox tables in wiki HTML."""
        patterns = [
            r'>Race\s*</td>\s*<td[^>]*>(.*?)</td>',
            r'>Race\s*</th>\s*<td[^>]*>(.*?)</td>',
            r'>Race\s*</th>\s*<th[^>]*>(.*?)</th>',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if m:
                raw_td = m.group(1)
                clean = re.sub(r'<[^>]+>', '', raw_td).strip()
                clean = re.sub(r'\[\d+\]', '', clean).strip()
                clean = clean.split("\n")[0].strip()
                if clean:
                    # Clean title casing, e.g. "dwarf" -> "Dwarf"
                    return clean.capitalize()
        return None


def clean_npc_name(name: str) -> str:
    """Strips leading/trailing quotes and normalizes whitespace."""
    if not name:
        return ""
    # Strip single and double quotes, backticks
    cleaned = name.strip("'\"` \t\r\n")
    return cleaned


def is_dummy_name(name: str) -> bool:
    """Checks if a name is an internal LOTRO dummy or non-character identifier."""
    # E.g. "0-10", "101-110", "???", "---", pure numbers
    if re.match(r"^[\d\s\-\+\.\,\?\!/]+$", name):
        return True
    return False


def load_cache(cache_path: Path) -> dict[str, dict]:
    """Loads existing scraped races JSON cache."""
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load cache file {cache_path}: {e}")
    return {}


def save_cache(cache_path: Path, cache: dict[str, dict]):
    """Saves cache atomically to JSON."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        if cache_path.exists():
            cache_path.unlink()
        temp_path.replace(cache_path)
    except Exception as e:
        logger.error(f"Error saving cache to {cache_path}: {e}")


def get_npc_names(db_path: Path) -> list[str]:
    """Gets distinct English NPC names from the database."""
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT name_en FROM NPCs WHERE name_en IS NOT NULL AND name_en != '' ORDER BY name_en;")
    rows = cur.fetchall()
    conn.close()
    return [r[0].strip() for r in rows if r[0].strip()]


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
    for name_en, info in cache.items():
        race = info.get("race")
        url = info.get("url")
        if race or url:
            updates.append((race, url, name_en))

    cur.executemany("UPDATE NPCs SET race = ?, url = ? WHERE name_en = ?;", updates)
    conn.commit()
    conn.close()

    logger.info(f"Updated {len(updates)} distinct NPC names in database in {time.time() - t0:.2f}s")


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
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Maximum number of new/unscraped NPCs to query in this run."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Polite delay between requests in seconds (default: 0.25)."
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-scrape even if already present in cache."
    )
    parser.add_argument(
        "--update-db",
        "-u",
        action="store_true",
        default=True,
        help="Update the SQLite database with the scraped races (default: True)."
    )

    args = parser.parse_args()

    logger.info("Starting LOTRO-TTS NPC Race Scraper...")
    logger.info(f"Database: {args.db}")
    logger.info(f"Cache file: {args.cache}")

    cache = load_cache(args.cache)
    logger.info(f"Loaded {len(cache)} existing cached entries.")

    names = get_npc_names(args.db)
    if not names:
        logger.error("No NPC names found to scrape.")
        return

    # Filter names that need scraping
    if args.force:
        to_scrape = names
    else:
        to_scrape = [n for n in names if n not in cache]

    total_needed = len(to_scrape)
    logger.info(f"Total distinct NPC names: {len(names)} | Needing scrape: {total_needed}")

    if args.limit and args.limit > 0:
        to_scrape = to_scrape[:args.limit]
        logger.info(f"Limiting to first {len(to_scrape)} NPCs for this run.")

    if not to_scrape:
        logger.info("All NPC names are already in the cache! Nothing to scrape.")
        if args.update_db:
            update_database(args.db, cache)
        return

    scraper = LotroWikiScraper()
    scraper.warm_up()

    count_scraped = 0
    count_found_race = 0
    save_interval = 20

    start_time = time.time()
    try:
        for idx, name in enumerate(to_scrape, start=1):
            race, wiki_url = scraper.scrape_npc(name)
            cache[name] = {
                "race": race,
                "url": wiki_url
            }
            count_scraped += 1
            if race:
                count_found_race += 1

            race_disp = race if race else "-"
            pct = (idx / len(to_scrape)) * 100
            print(f"[{idx:4d}/{len(to_scrape):4d}] ({pct:5.1f}%) {name[:35]:35s} -> {race_disp:12s} ({wiki_url or '-'})")

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
    logger.info(f"Scraped {count_scraped} NPCs in {elapsed:.1f}s. Found race for {count_found_race} NPCs.")

    if args.update_db:
        update_database(args.db, cache)


if __name__ == "__main__":
    main()

