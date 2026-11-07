# LOTRO-TTS (The Lord of the Rings Online - Text-to-Speech)

A modern, local, and fully offline Text-to-Speech (TTS) system for **The Lord of the Rings Online** (*LOTRO*).

LOTRO-TTS breathes life into quest dialogues and instance scenarios using authentic voice models tailored to each NPC's race, lineage, and gender (Elves, Dwarves, Hobbits, Men, Orcs, Ents, etc.) — supporting both **English** and **German** game clients. (and maybe French if requested lol)

---

## 💡 Motivation & Personal Vision (**not AI written**)

So basically i was bothered by all those quests without voiceover. So i looked up if there is already any tool and ofc i've found LotroToSpeech, Khazad-Voice-TTS and newly Project Questa.
I've looked up their repositories and tested them, it worked, but i wasn't fully satisfied - especially with german language support. Also i wanted to do some technical changes. My first attempt was by forking Khazad-Voice-TTS and tried to modify it to my needs/wishes, but pretty quick i realized that i'd had to change too much. So i started from scratch and took inspiration of the workflows of those projects and adapted them to my project.
In the end i just wanted the program to be completely "portable" (no installation of external Tools, e.g. without Tesseract OCR in Khazad-Voice-TTS, and everything of the tool stays in its Folder, nowhere else) and structured as i wanted it to be with support primarily for german language. Also i used sound files from the game for the voices. Most are already good, but some are need to be changed or added. Thats a WIP. Thanks for reading.

WIP:
- Performance (specifically delay between pressed button and TTS is playing, e.g. OCR on 4k)
- More unique voices

---
**below is written/documented with AI.... ain't no way i'm writing that whole Thing lol**

## 🌟 Key Features

- **100% Local & Portable**: No cloud subscriptions, no external APIs, and no telemetry. All inference runs directly on your local hardware inside the project folder.
- **All-in-One Cross-Platform GUI (`LOTRO-TTS.exe` / `LOTRO-TTS`)**:
  - Native, modern dark-themed GUI built with **Avalonia UI (.NET 8)** — available as a single-file, self-contained executable on both **Windows** and **Linux**.
  - One-click first-time setup (installs PyTorch with CUDA 12.6, ROCm, or CPU, OmniVoice, RapidOCR, and dependencies into the embedded Python environment).
  - Automatically installs the in-game Lua plugin (`Plugins\TTS`) into your `The Lord of the Rings Online` user documents folder (supporting Windows Registry, Steam Proton, Lutris, and custom wine prefixes).
  - Automatically builds the local SQLite database (`data/lotro.db`) and pre-warms OCR and TTS GPU kernels on startup.
  - **Integrated Auto-Updater**: Checks for updates on startup, supports one-click automated updates with rollback backups, and includes an optional toggle for **Pre-Releases / Beta Versions**.
- **Multilingual Support (`DE` / `EN` / `FR` / `ES` / `IT` / `NL`)**:
  - **Game Client Languages (OCR & Quest DB)**: **German (`DE`)**, **English (`EN`)**, and **French (`FR`)**.
  - **Spoken TTS Output Languages**: Native LOTRO voice libraries for **German (`DE`)**, **English (`EN`)**, and **French (`FR`)**, plus cross-lingual zero-shot voice cloning for **Spanish (`ES`)** (native database quest texts) and **Italian (`IT`)** / **Dutch (`NL`)** (local MarianMT translation).
- **190 Quest-Verified Authentic Voice Actors per Language (`570` Audio Profiles)**:
  - Extracted, transcribed, and verified 1:1 against the LOTRO Quest Database using neural speaker verification (`WavLM-SV`).
  - Covers `man_male` (50), `man_female` (39), `dwarf_male` (32), `elf_male` (21), `elf_female` (11), `hobbit_male` (9), `hobbit_female` (9), `dead` (6), `orc` (6), `dwarf_female` (5), `ent` (1), and `troll` (1).
  - Over **2,000 named Quest NPCs** (e.g. *Galadriel*, *Gandalf*, *Aragorn*, *Glóin*, *Treebeard*, *Gothmog*, *The Witch-king of Angmar*) are directly linked to their authentic voice actor, while all remaining **18,000+ NPCs** receive a deterministic voice matching their race and gender.
- **Custom NPC Overrides (`src/npc/npc_races_custom.json`)**:
  - Easily define or override race, gender, and specific voice profiles for any NPC by name or ID.
  - Custom overrides take precedence during database generation and are preserved across updates.
- **Narrator Mode & Audio Controls**:
  - Optional global **Narrator Mode** to read all quest dialogues in a chosen storytelling voice.
  - Configurable in-game stop hotkey (default: `Pause`) and master volume slider.
- **Intelligent Quest & Instance Window Detection**:
  - **Direct DWM Window Surface Capture**: Captures the LOTRO client frame directly on demand (even if other windows overlap the game, with zero idle CPU/GPU overhead).
  - **Standard Quests**: Reads the quest title via GPU-accelerated `RapidOCR` and retrieves the **complete, un-truncated original text** from `data/lotro.db` (even if parts are hidden behind in-game scrollbars).
  - **Instances & Dynamic Scenarios**: Reads the dialogue text directly from the screen when no static quest entry exists.
- **Engineered for Speed & Natural Speech**:
  - **Calibrated Speech Cadence**: Dynamic duration estimation and gentle trailing-syllable preservation prevent rushed speech or clipped word endings.
  - **Sentence-Level Audio Streaming**: Begins speaking on the very first sentence while synthesizing subsequent sentences concurrently in the background.
  - **Persistent Audio Caching**: Repeated dialogues play instantly with **0 ms latency**.

---

## 🛠️ Requirements & System Compatibility

- **Hardware Acceleration (Pick one)**:
  - **NVIDIA GPU (Recommended)**: GeForce RTX (2000 / 3000 / 4000 / 5000 Series, including Blackwell) or GTX 1600 series with CUDA 12.6.
  - **AMD GPU**: Modern Radeon RX 7000 / 9000 Series (RDNA 3/4) & Ryzen 700M / 800M APUs with ROCm.
  - **CPU Mode (Universal Compatibility)**: Highly optimized with multi-threading and AVX2/AVX-512 instructions (runs on any Intel Core, AMD Ryzen, or handhelds like Steam Deck).
- **Operating Systems**:
  - **Windows 10 / 11 (64-bit)**
  - **Linux (64-bit / SteamOS / Steam Deck)**: Compatible with Proton, Lutris, and native wine prefixes. Recommended tools: `pipewire-pulse` / `pulseaudio-utils` (for process volume control) and `wmctrl` or `xdotool` (for window detection).
- **The Lord of the Rings Online**: Standard game installation (English, German, or French game client).

---

## 🚀 Getting Started

Simply launch the single-file GUI executable for your platform:
* **Windows**: Double-click **`LOTRO-TTS.exe`** in the root folder.
* **Linux**: Run **`./LOTRO-TTS`** in terminal or double-click it in your desktop file manager.

### First-Time Setup (Automated via GUI)
1. Launch **`LOTRO-TTS.exe`** (Windows) or **`./LOTRO-TTS`** (Linux).
2. Select your **Game Client Language** (`DE`, `EN`, `FR`) and your desired **Spoken TTS Voice Language** (`DE`, `EN`, `FR`, `ES`, `IT`, `NL`).
3. Click **`▶ START LOTRO-TTS`** (or **`⚙ Setup TTS (GPU/CPU)`**):
   - **Step 1 (LOTRO Lua Plugin)**: If not yet installed, LOTRO-TTS automatically copies the Lua plugin into your LOTRO `Plugins/TTS` folder.
   - **Step 2 (TTS Environment)**: Prompts you to choose your compute backend (**NVIDIA GPU**, **AMD GPU**, or **CPU Mode**), and installs PyTorch, OmniVoice, sounddevice, and RapidOCR into `python/win64` (Windows) or `python/linux64` (Linux).
   - **Step 3 (Quest Database)**: Automatically generates `data/lotro.db` (~140 MB, 18,074 NPCs & 15,489 Quests) in ~4 seconds and starts the background service!

*In-Game Tip: Enable the plugin in LOTRO via the **Plugin Manager** at character selection or by typing `/plugins load tts` in chat.*

---

## 🎮 Triggering Dialogue In-Game

While `LOTRO-TTS.exe` is running in the background, you have **two ways** to trigger voiceover in-game:

1. **In-Game Plugin Button ("Read aloud" / "Vorlesen") — *(Recommended Primary Method)***:
   - Targeting an NPC reveals the in-game button **"Read aloud"** (or **"Vorlesen"** in German).
   - Clicking the button writes `TTS|<LANG>|<NPC_NAME>` to `Script.log`, passing the currently targeted NPC directly to LOTRO-TTS so the **exact matching NPC voice** (1:1 character voice or race/gender profile) is selected.
   - Hold `Ctrl` to drag and reposition the button anywhere on your screen.
2. **Middle Mouse Button (Mouse 3) — *(Alternative Shortcut)***:
   - Alternatively, you can press your **Middle Mouse Button (Mouse 3)** whenever a quest or instance dialogue window is open.
   - For standard quests in `lotro.db`, LOTRO-TTS automatically resolves the quest's associated NPC from the database; for dynamic instance texts or objects without an NPC, it uses the last logged target or the default narrator voice (`man_male_1`).

---

## 🎭 Custom NPC Overrides (Race, Gender & Voice Assignment)

Encountered an NPC whose race or gender in the base lore data is missing or incorrect? Want to assign a specific favorite voice actor to a particular quest giver?

You can easily override or define metadata for any NPC by editing **`src/npc/npc_races_custom.json`**:

```json
{
  "Peony Grubb": {
    "race": "Hobbit",
    "gender": "Female"
  },
  "1879049636": {
    "race": "Hobbit",
    "gender": "Female",
    "voice_id": "hobbit_female_9"
  }
}
```

* **Match by Name or ID**: Use either the NPC's English or localized in-game name (e.g. `"Peony Grubb"`) or their numeric NPC ID (e.g. `"1879049636"`).
* **Supported Fields**:
  * `"race"`: `Man`, `Elf`, `Dwarf`, `Hobbit`, `Orc`, `Ent`, `Troll`, `Dead`, etc.
  * `"gender"`: `Male` or `Female`.
  * `"voice_id"`: (Optional) Directly assign any specific voice profile ID from `data/voices/` (e.g. `hobbit_female_9`, `man_male_1`, `elf_female_3`).
* **Applying Changes**: Click **`Tools` → `Rebuild Database`** in the GUI (or run `scripts/generate_db.py`). The generator immediately applies your custom definitions when compiling `data/lotro.db`.
* **Safe Across Updates**: `src/npc/npc_races_custom.json` is user-managed and will never be overwritten or erased when updating LOTRO-TTS.

---

## ⚙️ How It Works Under the Hood

```
[LOTRO-TTS.exe GUI] ─────────────────────────────┐
  (One-Click Setup, DB Builder & Service Host)   │
                                                 ▼
[In-Game Button / Mouse 3] ───────────> [LOTRO-TTS Pipeline Service]
                                                 │
                                                 ├── 1. Direct Window Capture & CUDA OCR (RapidOCR)
                                                 │      - Captures LOTRO DWM surface (DPI & 4K aware).
                                                 │      - Fast-path title strip scanning with geometry cache.
                                                 │
                                                 ├── 2. Text & Speaker Resolution (SQLite: data/lotro.db)
                                                 │      - Quests: Full un-truncated text in DE / EN / FR / ES.
                                                 │      - Instances: Direct OCR text extraction.
                                                 │      - NPC: Maps 2,001 verified Quest NPCs to their 1:1
                                                 │        voice actor & 16,000+ NPCs by race/gender pool.
                                                 │
                                                 ├── 3. Audio Cache Check
                                                 │      - Previously generated line? -> Instant playback (0 ms)!
                                                 │
                                                 └── 4. Zero-Shot Speech Synthesis (OmniVoice)
                                                        - Calibrated duration & intact word-final syllables.
                                                        - Sentence 1 plays immediately while next sentences
                                                          synthesize concurrently in the background.
```

---

## 🔧 Advanced CLI & Batch Scripts (`scripts/bat/`)

In addition to the GUI launchers (`LOTRO-TTS.exe` on Windows and `LOTRO-TTS` on Linux), standalone scripts and CLI entrypoints are available for Windows (`scripts/bat/`) and Linux (`scripts/sh/`):

### Windows Batch Scripts (`scripts/bat/`)

| Script | Description |
| :--- | :--- |
| `scripts\bat\start_lotro_tts.bat` | Starts `scripts/lotro_service.py` directly in a console window. |
| `scripts\bat\setup_tts.bat` | Runs the interactive Python/CUDA environment installer (`scripts/setup_tts.py`). |
| `scripts\bat\run_generate_db.bat` | Builds `data/lotro.db` from local XML files in `src/` (`scripts/generate_db.py`). |
| `scripts\bat\run_update_sources.bat` | Downloads the latest XML data from LotroCompanion and rebuilds `data/lotro.db`. |
| `scripts\bat\test_speech.bat` | Generates sample `.wav` files in `audio_samples/` to verify voice cloning. |
| `scripts\bat\build_gui.bat` | Compiles the cross-platform Avalonia GUI executable for Windows (`LOTRO-TTS.exe`). |

### Linux Shell Scripts (`scripts/sh/`)

| Script | Description |
| :--- | :--- |
| `scripts/sh/setup_tts.sh` | Auto-downloads standalone portable Python 3.13 into `python/linux64` & installs PyTorch/OmniVoice. |
| `scripts/sh/start_lotro_tts.sh` | Starts `scripts/lotro_service.py` directly in a console window. |
| `scripts/sh/run_generate_db.sh` | Builds `data/lotro.db` on Linux (`scripts/generate_db.py`). |
| `scripts/sh/run_update_sources.sh` | Downloads the latest XML data from LotroCompanion and rebuilds database on Linux. |
| `scripts/sh/run_scrape_races.sh` | Scrapes missing NPC race metadata from lotro-wiki.com on Linux. |
| `scripts/sh/test_speech.sh` | Generates sample `.wav` files in `audio_samples/` to verify voice cloning. |
| `scripts/sh/build_gui.sh` | Compiles the cross-platform Avalonia GUI executable for Linux (`LOTRO-TTS`). |

### CLI Arguments for `scripts/lotro_service.py`

```cmd
python\win64\python.exe scripts\lotro_service.py [OPTIONS]
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `--client-lang` | `config.json` | LOTRO game client language for OCR: `de`, `en`, or `fr`. |
| `--tts-lang` | `config.json` | Spoken TTS voice output language: `de`, `en`, `fr`, `es`, `it`, or `nl`. |
| `--mode` | `auto` | Compute mode: `auto` (auto-detects CUDA/RTX GPU), `cuda`, or `cpu`. |
| `--docs-dir` | *Auto* | Path to LOTRO user documents directory (auto-detected via Windows Registry). |
| `--no-mouse` | *disabled* | Disables the global middle mouse button trigger (in-game button only). |
| `--config` | *disabled* | Forces interactive language configuration in console mode. |

---

## 📁 Repository Structure

```
LOTRO-TTS/
├── LOTRO-TTS.exe             # All-in-One GUI Launcher (Windows standalone binary)
├── LOTRO-TTS                 # All-in-One GUI Launcher (Linux standalone binary)
├── README.md                 # Project documentation
├── data/
│   ├── lotro.db              # Generated SQLite Database (18,074 NPCs, 15,489 Quests)
│   └── voices/               # 190 Quest-Verified Voice Profiles per language (570 .ogg files)
│       ├── de/               # German reference audio profiles & voice_index.json
│       ├── en/               # English reference audio profiles & voice_index.json
│       └── fr/               # French reference audio profiles & voice_index.json
├── python/
│   ├── win64/                # Embedded portable Python 3.13 runtime (Windows)
│   └── linux64/              # Standalone portable Python 3.13 runtime (Linux)
├── scripts/
│   ├── lotro_service.py      # Core service (log watcher, DWM/X11 window capture, pipeline)
│   ├── screen_reader.py      # Screen reader, CUDA RapidOCR & window geometry cache
│   ├── tts_speaker.py        # OmniVoice Zero-Shot engine, sounddevice playback & streaming
│   ├── translator.py         # Local MarianMT neural translator (for Italian 'it' and Dutch 'nl')
│   ├── generate_db.py        # SQLite database generator (auto-downloads missing sources)
│   ├── assign_voices.py      # Deterministic & 1:1 verified NPC voice assignment
│   ├── update_sources.py     # Updater for LotroCompanion NPC/Quest XMLs
│   ├── scrape_npc_races.py   # Race metadata scraper for lotro-wiki.com
│   ├── setup_tts.py          # Automated PyTorch/CUDA & OmniVoice installer (Win & Linux)
│   ├── bat/                  # Windows CLI batch scripts (incl. build_gui.bat)
│   └── sh/                   # Linux CLI shell scripts (incl. build_gui.sh)
└── src/
    ├── LotroTtsGui/          # Cross-Platform Avalonia UI .NET 8 source project
    ├── npc/                  # Extracted LOTRO NPC XMLs, cached races & npc_races_custom.json
    ├── quests/               # Extracted LOTRO Quest XMLs (auto-fetched on first run if missing)
    └── plugins/TTS/          # Lua Plugin for the LOTRO client (in-game UI button)
```

---

## 🙏 Credits & Acknowledgments

- **Idea & Inspiration**: Inspired by the concepts and community efforts of [Khazad-Voice-TTS](https://github.com/Khazad-Voice-TTS), *LOTROToSpeech*, and *Project Questa*.
- **Game Data & Quest Database**: Powered by data and lore extractions from the incredible [LotroCompanion lotro-data](https://github.com/LotroCompanion/lotro-data) repository.
- **Voice Profiles**: Curated and verified using authentic in-game audio assets from *The Lord of the Rings Online* to capture the genuine atmosphere of Middle-earth.
