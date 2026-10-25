# LOTRO-TTS (Lord of the Rings Online - Text-to-Speech)

Ein modernes, lokales und offline-fähiges Text-to-Speech (TTS) System für **Der Herr der Ringe Online** (*The Lord of the Rings Online*). 

Das Projekt vertont automatisch Quest- und Instanz-Dialoge im Spiel mit passenden, authentischen Charakterstimmen (Elben, Zwerge, Hobbits, Menschen, Orks etc.) unter Berücksichtigung von Rasse, Volk und Geschlecht – wahlweise auf **Deutsch** oder **Englisch**.

---

## 🌟 Hauptfunktionen

- **Vollständig lokal & offline**: Keine Cloud-Anbindung oder externen API-Schlüssel erforderlich. Läuft direkt auf deiner Hardware.
- **Zweisprachig (DE / EN)**: Erkennt automatisch die Client-Sprache (Deutsch oder Englisch) und wählt die passende deutsche oder englische Stimmbibliothek.
- **Intelligente Quest- & Instanz-Erkennung**:
  - **Standard-Quests**: Erkennt den Questtitel und lädt den **vollständigen, ungekürzten Text** aus der integrierten SQLite-Datenbank (auch wenn Textteile im Spiel hinter Scrollbalken liegen).
  - **Instanzen & dynamische Dialoge**: Liest den Text direkt per GPU-beschleunigtem OCR (`RapidOCR`) aus dem Spielfenster.
- **Authentische Zero-Shot Stimmenzuordnung**:
  - Ermittelt anhand des NPC-Namens automatisch Rasse, Volk und Geschlecht (z. B. Mensch männlich, Zwerg weiblich, Hobbit, Elb, Ork, Erzähler).
  - Deterministische Stimmvergabe: Ein NPC behält bei wiederholtem Treffen stets denselben Sprecher.
- **Maximale Performance & Echtzeit-Reaktion**:
  - **Fast-Path Window-Caching**: Merkt sich die Position des Spielfensters für blitzschnelle Erkennung in Millisekunden.
  - **Satzweises Audio-Streaming**: Lange Texte beginnen bereits nach dem ersten Satz zu sprechen – kein langes Warten auf die Gesamtberechnung.
  - **Audio-Caching**: Einmal berechnete Quests werden im Cache gespeichert und beim nächsten Mal mit **0 ms Latenz** sofort abgespielt.
- **Plattformunabhängig**: Lauffähig unter **Windows** und **Linux** (inklusive **Steam Deck** via Proton).

---

## 🛠️ Voraussetzungen

- **Grafikkarte (Empfohlen)**: NVIDIA-Grafikkarte mit CUDA-Unterstützung (z. B. RTX-Serie) für Sprachgenerierung in Sekundenschnelle. *(CPU-Modus ist als Fallback ebenfalls möglich).*
- **Der Herr der Ringe Online**: Standard-Installation.

---

## 🚀 Vor der ersten Benutzung (Einrichtung)

### 1. In-Game Plugin installieren
Kopiere den Ordner `src/plugins/TTS` in dein LOTRO-Pluginverzeichnis:
- **Windows**: `Documents\The Lord of the Rings Online\Plugins\TTS`
- **Linux / Steam Deck**: `[Steam-Pfad]/compatdata/212500/pfx/drive_c/users/steamuser/Documents/The Lord of the Rings Online/Plugins/TTS`

*Tipp: Aktiviere das Plugin im Spiel über den LOTRO-Zusatzmodul-Manager oder mit dem Chat-Befehl `/plugins load tts`.*

### 2. KI- & Audio-Umgebung installieren (Einmalig)
Führe im Hauptordner einfach die Batch-Datei aus:
```cmd
setup_tts.bat
```
Das Skript fragt dich nach dem gewünschten Modus:
- **1) GPU (NVIDIA / CUDA)** *(Empfohlen)*: Installiert PyTorch mit CUDA-Unterstützung und GPU-beschleunigter OCR.
- **2) CPU**: Installiert die reine Prozessor-Variante (langsamer, aber ohne NVIDIA-Grafikkarte lauffähig).

---

## 🎮 Bedienung & Programmstart

### Starten des Dienstes
Starte vor oder während des Spielens einfach:
```cmd
start_lotro_tts.bat
```
Der Hintergrunddienst überwacht nun das Spiel und wartet auf deinen Auslöser.

### Wie wird das Vorlesen im Spiel ausgelöst?
Du hast **zwei Möglichkeiten**, das Vorlesen eines Dialogs zu starten:

1. **In-Game-Button „Vorlesen“**:
   - Wenn du einen NPC im Spiel im Ziel hast, erscheint der LOTRO-Button **„Vorlesen“** (bzw. **„Read aloud“** im englischen Client).
   - Mit gedrückter `Strg`-Taste kannst du den Button per Drag & Drop an eine beliebige Position ziehen.
2. **Mittlere Maustaste (Maus 3)**:
   - Alternativ drückst du einfach die **mittlere Maustaste**, sobald ein Quest- oder Instanzfenster geöffnet ist. Der Cursor muss dafür nicht auf den Button bewegt werden.

---

## ⚙️ Funktionsweise im Detail

```
[In-Game Klick / Maus 3]
         │
         ├──> Plugin schreibt Signal in 'Script.log' (Sprache + NPC-Name)
         │
         ▼
[LOTRO-TTS Service]
         │
         ├── 1. Fenster-Erkennung & Screenreader (RapidOCR)
         │      - Scannt das Quest-/Instanzfenster (unterstützt alle UI-Skins).
         │      - Bei bekannter Fensterposition via Fast-Path in Millisekunden.
         │
         ├── 2. Text- & Sprecher-Auflösung (SQLite Datenbank: lotro.db)
         │      - Quests: Vollständiger Originaltext aus der Datenbank.
         │      - Instanzen: Direkter OCR-Text mit Rechtschreib- und Umlaut-Korrektur.
         │      - NPC: Ermittelt Kategorie (z. B. dwarf_female, elf_male) & Stimmprofil.
         │
         ├── 3. Audio-Cache Check
         │      - Wurde der Text bereits gesprochen? -> Sofortige Wiedergabe (0 ms)!
         │
         └── 4. Sprachsynthese (OmniVoice Zero-Shot Voice Cloning)
                - Satzweises Streaming: Satz 1 startet sofort über die Lautsprecher.
                - Nahtlose Hintergrund-Berechnung der Folgesätze.
                - Abspeichern in den Cache für zukünftige Durchläufe.
```

---

## 🔧 Erweiterte Optionen & CLI

`lotro_service.py` kann auch mit individuellen Parametern gestartet werden:

```cmd
python\win64\python.exe scripts\lotro_service.py [OPTIONEN]
```

| Parameter | Standard | Beschreibung |
| :--- | :--- | :--- |
| `--mode` | `auto` | Berechnungsmodus: `auto` (erkennt RTX/CUDA automatisch), `cuda` oder `cpu`. |
| `--docs-dir` | *Auto* | Pfad zum LOTRO-Dokumentenverzeichnis (Standard: `D:\Dokumente\The Lord of the Rings Online`). |
| `--no-mouse` | *deaktiviert* | Deaktiviert den globalen Mittlere-Maustaste-Trigger (nur noch In-Game-Button aktiv). |

---

## 📁 Projektstruktur

```
LOTRO-TTS/
├── data/
│   ├── lotro.db              # SQLite-Datenbank (17.700+ NPCs, 15.000+ Quests & Texte)
│   └── voices/               # Kuratierte Sprachprofile (de / en)
│       ├── de/               # Deutsche Stimmprofile nach Völkern/Geschlecht
│       └── en/               # Englische Stimmprofile nach Völkern/Geschlecht
├── scripts/
│   ├── lotro_service.py      # Hauptdienst (Log-Tailer, Trigger & Workflow-Steuerung)
│   ├── screen_reader.py      # Screenreader, RapidOCR & Fenster-Geometrie-Caching
│   ├── tts_speaker.py        # OmniVoice Zero-Shot Engine, Streaming & Audio-Cache
│   └── setup_tts.py          # Installations- und Umgebungs-Setup
├── src/plugins/TTS/          # Lua-Plugin für den LOTRO-Client (In-Game UI)
├── setup_tts.bat             # 1-Klick Installer
└── start_lotro_tts.bat       # 1-Klick Starter für den Hintergrunddienst
```
