# LOTRO-TTS (The Lord of the Rings Online - Text-to-Speech)

A modern, local, and fully offline Text-to-Speech (TTS) system for **The Lord of the Rings Online** (*LOTRO*).

LOTRO-TTS breathes life into quest dialogues and instance scenarios using authentic voice models tailored to each NPC's race, lineage, and gender (Elves, Dwarves, Hobbits, Men, Orcs, Ents, etc.) — supporting both **English** and **German** game clients.

---

## 🌟 Key Features

- **100% Local & Offline**: No cloud subscriptions, no external APIs, and no telemetry. All inference runs directly on your local hardware.
- **Bilingual (English & German)**: Automatically detects game client language (`EN` / `DE`) and switches to the corresponding curated voice library and transcripts.
- **Intelligent Quest & Instance Window Detection**:
  - **Standard Quests**: Reads the quest title and retrieves the **complete, un-truncated original text** from the embedded SQLite database (even if parts are hidden behind in-game scrollbars).
  - **Instances & Dynamic Scenarios**: Reads the dialogue text directly from the screen using GPU-accelerated OCR (`RapidOCR`).
- **Authentic Zero-Shot Voice Allocation**:
  - Automatically identifies NPC race, lineage, and gender (e.g. Man Male, Dwarf Female, Hobbit, Elf, Orc, Narrator) from the database.
  - Deterministic voice assignment: An NPC consistently retains the exact same voice actor profile across playthroughs.
- **Engineered for Speed & Low Latency**:
  - **Fast-Path Window Caching**: Caches the in-game dialogue window coordinates for near-instant OCR recognition.
  - **Sentence-Level Audio Streaming**: Begins speaking on the very first sentence (~0.3s) while calculating subsequent sentences smoothly in the background.
  - **Persistent Audio Caching**: Repeated dialogues and quests play instantly with **0 ms latency**.
- **Cross-Platform**: Runs natively on **Windows** and **Linux** (including **Steam Deck** via Proton).

---

## 🛠️ Requirements

- **Graphics Card (Recommended)**: NVIDIA GPU with CUDA support (e.g. RTX series) for instant speech generation. *(CPU mode is supported as a fallback).*
- **The Lord of the Rings Online**: Standard game installation.

---

## 🚀 Getting Started (First-Time Setup)

### 1. Install the In-Game Lua Plugin
Copy the `src/plugins/TTS` folder into your LOTRO Plugins directory:
- **Windows**: `Documents\The Lord of the Rings Online\Plugins\TTS`
- **Linux / Steam Deck**: `[Steam-Path]/compatdata/212500/pfx/drive_c/users/steamuser/Documents/The Lord of the Rings Online/Plugins/TTS`

*Tip: Enable the plugin in-game via the LOTRO Plugin Manager or by typing `/plugins load tts` in chat.*

### 2. Set Up the AI & Audio Environment (One-Time)
Run the automated setup batch file in the root folder:
```cmd
setup_tts.bat
```
Select your desired compute mode:
- **1) GPU (NVIDIA / CUDA)** *(Recommended)*: Installs PyTorch with CUDA acceleration and GPU-accelerated OCR.
- **2) CPU**: Installs the CPU-only version (runs without an NVIDIA GPU, but with higher latency).

---

## 🎮 How to Use & Start the Program

### Starting the Service
Before or while playing LOTRO, run:
```cmd
start_lotro_tts.bat
```
The background service monitors the game client and waits for your trigger.

### Triggering Dialogue in Game
You have **two convenient ways** to trigger text-to-speech in-game:

1. **In-Game Button ("Read aloud" / "Vorlesen")**:
   - Targeting an NPC reveals the LOTRO button **"Read aloud"** (or **"Vorlesen"** in German).
   - Clicking the button logs `TTS|<LANG>|<NPC_NAME>` to `Script.log`, which immediately triggers the service with the target NPC's identity.
   - Hold `Ctrl` to drag and reposition the button anywhere on your screen.
2. **Middle Mouse Button (Mouse 3)**:
   - Alternatively, press your **Middle Mouse Button (Mouse 3)** whenever a quest or instance window is open.
   - This directly triggers the screen reader pipeline using the most recently detected language and target NPC from the log, without needing to click the button.

---

## ⚙️ How It Works Under the Hood

```
[In-Game Button Click] ──────────────────────────┐
  (Writes 'TTS|<LANG>|<NPC>' to Script.log)      │
                                                 ▼
[Middle Mouse Click (Mouse 3)] ────────> [LOTRO-TTS Pipeline Service]
  (Uses last known log context)                  │
                                                 ├── 1. Window Detection & OCR (RapidOCR)
                                                 │      - Scans the quest / instance dialogue box (skin-independent).
                                                 │      - Uses fast-path title scanning when window position is cached.
                                                 │
                                                 ├── 2. Text & Speaker Resolution (SQLite Database: lotro.db)
                                                 │      - Quests: Full un-truncated original text from database.
                                                 │      - Instances: Direct OCR text with diacritics and character normalization.
                                                 │      - NPC: Resolves race/gender profile (e.g. dwarf_female, elf_male).
                                                 │
                                                 ├── 3. Audio Cache Check
                                                 │      - Has this dialogue been generated before? -> Instant playback (0 ms)!
                                                 │
                                                 └── 4. Zero-Shot Speech Synthesis (OmniVoice)
                                                        - Sentence streaming: Sentence 1 plays through speakers immediately.
                                                        - Next sentences synthesized concurrently in the background.
                                                        - Saves complete audio to cache for future instant re-use.
```

---

## 🔧 Advanced Options & Command Line Arguments

You can run `lotro_service.py` with custom arguments:

```cmd
python\win64\python.exe scripts\lotro_service.py [OPTIONS]
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `--mode` | `auto` | Compute mode: `auto` (auto-detects CUDA/RTX GPU), `cuda`, or `cpu`. |
| `--docs-dir` | *Auto* | Path to LOTRO user documents directory (default: `%USERPROFILE%\Documents\The Lord of the Rings Online`). |
| `--no-mouse` | *disabled* | Disables the global middle mouse button trigger (in-game button only). |

---

## 📁 Repository Structure

```
LOTRO-TTS/
├── data/
│   ├── lotro.db              # SQLite Database (17,700+ NPCs, 15,000+ Quests & Texts)
│   └── voices/               # Curated Voice Profiles (de / en)
│       ├── de/               # German reference audio profiles by race & gender
│       └── en/               # English reference audio profiles by race & gender
├── scripts/
│   ├── lotro_service.py      # Core service (log watcher, trigger dispatcher, pipeline)
│   ├── screen_reader.py      # Screen reader, RapidOCR, and window geometry cache
│   ├── tts_speaker.py        # OmniVoice Zero-Shot engine, streaming & audio cache
│   └── setup_tts.py          # Setup & environment installation script
├── src/plugins/TTS/          # Lua Plugin for the LOTRO client (in-game UI)
├── setup_tts.bat             # 1-click environment installer
└── start_lotro_tts.bat       # 1-click background service launcher
```
