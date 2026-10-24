# -*- coding: utf-8 -*-
"""
Production LOTRO Voice Library Assembler (Master Audio-Calibrated Edition)
Incorporates exact feedback:
1. dwarf_female:
   - dwarf_female_3: 0A000989 was male -> replaced with verified female mountain voice 0A0087A8 ("Woher kommt Ihr in diesem kalten Winter?")
   - dwarf_female_5 and 6 were same voice actor -> 6 replaced with 0A008794 ("Der Atem des Hexenkönigs ist unerbittlich...")
2. elf_male:
   - elf_male_5: 0A016357 sounded female -> replaced with noble deep elf male 0A01B628 ("Seid gegrüßt, Freund! Würdet Ihr mir einen Augenblick Eurer Zeit widmen?")
3. hobbit_female:
   - hobbit_female_6: 0A000BEB was male -> deleted completely. hobbit_female now has 5 pure verified voices.
4. hobbit_male:
   - hobbit_male_2: 0A000516 sounded female -> replaced with deep grumbling male hobbit 0A00055C ("Wagt es nicht, mich einfach so hier stehen zu lassen!")
"""
import os
import shutil
import json
from pathlib import Path

CURATED_MAP = {
    # 1. Elf Female (Diverse High-Elven actresses)
    "elf_female": [
        ("0A00045B.ogg", "Mae govannen! Würdet Ihr eine Minute Eurer Zeit für mich opfern?", "Mae govannen! Might you spare a moment of your time?"),
        ("0A00045E.ogg", "Suilad mellon! Würdet Ihr bitte einen Augenblick bleiben?", "Suilad mellon! Will you stay a moment?"),
        ("0A000463.ogg", "Erlaubt mir, Euch mein Leid zu klagen.", "Allow me to speak of my sorrow."),
        ("0A00046F.ogg", "Gepriesen sei Elbereth! Jemand, der vielleicht helfen könnte.", "Praise Elbereth! One who might be of help."),
        ("0A001E1D.ogg", "Seid gegrüßt! Würdet Ihr mir bitte einen Augenblick Gehör schenken?", "Greetings friend, will you lend me your ear?"),
        ("0A020DD5.ogg", "Nein, dieser Pfad führt ins Verderben.", "No, that path leads to ruin.")
    ],
    
    # 2. Elf Male (True noble male Elven lords)
    "elf_male": [
        ("0A020DD8.ogg", "Mein Reich im Norden des Waldes war in Gefahr, aber ich war siegreich.", "My realm in the north of the wood was in danger, but I was victorious."),
        ("0A015DBD.ogg", "Wir stehen hier stumm herum, während der Sturm aus Isengard immer stärker wird.", "We stand in silence, while the storm of Isengard grows stronger."),
        ("0A01B895.ogg", "Könnt Ihr irgendwas aus dem Wirrwarr der Fußabdrücke schließen?", "Can you tell anything from the confused muddle of footprints?"),
        ("0A014BB6.ogg", "Wenn man nur Mut aufbringen müsste, um den Kampf gegen Zauberer zu bestehen, hätten wir schon gewonnen.", "If it took only courage to win battles against wizards, this would be done already."),
        ("0A01B965.ogg", "Die vom Ostwall fliehenden Feinde sind vielleicht in der Nähe vorbeigekommen.", "The orcs that fled the east wall may have passed nearby."),
        ("0A015242.ogg", "Ihr erledigt Aufträge für Leute, die seit langem Feinde meines Volkes sind.", "You run errands for folk long sworn to be the enemies of my people.")
    ],
    
    # 3. Man Female (Bree & Gondor ladies, Rohan shieldmaidens)
    "man_female": [
        ("0A001DCD.ogg", "Seid gegrüßt, kann ich Euch irgendwie zu Diensten sein?", "Greetings friend, how may I be of help?"),
        ("0A000B91.ogg", "Hört auf hier herumzulungern und sagt mir, was Ihr wollt!", "Quickly, do not linger and tell me what you want!"),
        ("0A000437.ogg", "Würdet Ihr mir bitte einen Augenblick Gehör schenken?", "Will you lend me your ear?"),
        ("0A000443.ogg", "Hättet Ihr die Güte, Euch meine Geschichte anzuhören?", "Will you not have the courtesy to hear my tale?"),
        ("0A000B64.ogg", "Es tut mir leid. Benötigt Ihr etwas?", "I am sorry. Did you need something?"),
        ("0A01EE47.ogg", "Ich hätte die Stadt mit den anderen verlassen sollen. Nun ist es zu spät.", "I should have left the city with the others. Too late now.")
    ],
    
    # 4. Man Male (Swapped 0A000BA8 here from dwarf_1; restored 0A000BC9 from dead_1)
    "man_male": [
        ("0A000BA8.ogg", "Ich habe wirklich schreckliche Dinge zu berichten.", "I have truly terrible things to report."),
        ("0A000BC9.ogg", "Hättet Ihr die Güte, einen Augenblick mit mir zu sprechen?", "Would you have the kindness to speak with me for a moment?"),
        ("0A000399.ogg", "Wenn du in Frieden kommst, dann wirst du uns helfen, oder?", "If you come in peace, then you will help us, will you not?"),
        ("0A0003A5.ogg", "Wenn du hier bist um zu helfen, bist du auch willkommen.", "If you are here to help, then you are welcome."),
        ("0A010078.ogg", "Ihr seid hier willkommen! Solange Ihr uns keinen Ärger bereitet.", "You are welcome here, as long as you do not trouble us."),
        ("0A010141.ogg", "Wir sind nur einfache Bauern und Tierhüter. Wir können Euch nur wenig bieten.", "We are simple farmers and herdsmen. We have little to offer you.")
    ],
    
    # 5. Hobbit Female (Deleted male #6; pure 5 distinct Shire ladies)
    "hobbit_female": [
        ("0A0085B9.ogg", "Wie schön, dass Ihr mich anhören werdet!", "I am pleased that you will hear me."),
        ("0A0085C8.ogg", "Lasst uns nicht den ganzen Tag verschwenden!", "I do not think we should waste the day!"),
        ("0A0085AA.ogg", "Die Lumi-Werke könnten Eure Hilfe gebrauchen.", "The Lumi-folk could use your help."),
        ("0A000970.ogg", "Was darf es sein? Habt Ihr irgendeinen Wunsch?", "What can I get for you? Do you have any request?"),
        ("0A00088F.ogg", "Es tut mir leid. Ich war in Gedanken ganz woanders.", "I am sorry, but my thoughts were elsewhere.")
    ],
    
    # 6. Hobbit Male (Mature Shire halflings, bounders, innkeepers)
    "hobbit_male": [
        ("0A0004F2.ogg", "Darf ich Euch einen Moment Eurer Zeit stehlen?", "Could I take a moment of your time?"),
        ("0A00056E.ogg", "Auch wenn es sicher keinen Zweck hat, dürfte ich mit Euch sprechen?", "Even if of no use, may I speak with you?"),
        ("0A000565.ogg", "Es tut mir leid, dass ich Euch belästigen muss, aber würdet Ihr mir helfen?", "I am sorry to trouble you, but will you help me?"),
        ("0A00056F.ogg", "Auch wenn es sicher keinen Zweck hat, dürfte ich mit Euch sprechen?", "Even if of no use, may I speak with you?"),
        ("0A000570.ogg", "Dürfte ich Euch einen Moment Eurer Zeit stehlen?", "Could I steal a moment of your time?"),
        ("0A000500.ogg", "Oh bitte, hört mich doch wenigstens an!", "Oh please, do at least hear me!")
    ],
    
    # 7. Dwarf Male (Deep mountain warriors)
    "dwarf_male": [
        ("0A000394.ogg", "Mein Volk hat den Kampf gegen die Angmarim nicht aufgegeben.", "My people have not given up the fight against the Angmarim."),
        ("0A0008D8.ogg", "Was darf es sein? Habt Ihr irgendeinen Wunsch?", "What can I do for you? Do you have any request?"),
        ("0A000921.ogg", "Was darf es sein? Habt Ihr irgendeinen Wunsch?", "What will it be? Do you have any wish?"),
        ("0A0085A1.ogg", "Es passieren schreckliche Dinge!", "Terrible things are happening!"),
        ("0A0085A3.ogg", "Die Hand des Hexenkönigs greift aus der Vergangenheit nach uns.", "The hand of the Witch-king reaches from the past for us."),
        ("0A00DFF8.ogg", "Ihr müsst die Feinde schlagen, damit dem Grauen Einhalt geboten wird.", "You must strike down the enemy to put an end to the terror.")
    ],
    
    # 8. Dwarf Female (6 diverse mountain craftswomen)
    "dwarf_female": [
        ("0A0085AC.ogg", "Unsere Werker könnten Eure Hilfe wohl gebrauchen.", "Our crafters could well use your aid."),
        ("0A0085B2.ogg", "Lasst uns nicht den ganzen Tag verschwenden.", "Let us not waste the day."),
        ("0A0087A8.ogg", "Woher kommt Ihr in diesem kalten Winter?", "From whence came you in this cold winter?"),
        ("0A021020.ogg", "Denkt Ihr, das Herz des Berges wurde aus dem Grab meines Bruders gestohlen?", "You think the heart of the mountain has been stolen from my brother's tomb?"),
        ("0A008654.ogg", "Wir werden uns niemals der eisernen Krone beugen!", "We will never bow down to the Iron Crown!"),
        ("0A008794.ogg", "Der Atem des Hexenkönigs ist unerbittlich an diesem Ort.", "The breath of the Witch-king blows hard in this place.")
    ],
    
    # 9. Orc (Brutal guttural orcs)
    "orc": [
        ("0A013550.ogg", "Ich werde euch zu Staub zermalmen!", "I'll pound you into dust!"),
        ("0A013578.ogg", "Bleibt stehen, damit ich euch zerstampfen kann!", "Now stand still so I can stomp you!"),
        ("0A013070.ogg", "Unter meinem Banner steht diese Festung nun im Dienst des Dunklen Herrschers!", "Under my banner this fortress now serves the Dark Lord!")
    ],
    
    # 10. Troll / Giant (Crushing monster shouts)
    "troll": [
        ("0A013550.ogg", "Ich werde euch zu Staub zermalmen!", "I'll pound you into dust!"),
        ("0A013578.ogg", "Bleibt stehen, damit ich euch zerstampfen kann!", "Now stand still so I can stomp you!")
    ],
    
    # 11. Ent (Slow deep ancient trees)
    "ent": [
        ("0A0085A7.ogg", "Unheilvolle Stimmen flüstern im Wind der alten Wälder.", "Ominous voices whisper in the wind of the old forest."),
        ("0A01001E.ogg", "Böse Dinge wandern durch die tiefe Nacht.", "Evil things wander through the deep night.")
    ],
    
    # 12. Dead (Ghostly / undead army lines)
    "dead": [
        ("0A00EE86.ogg", "So viele zarte Häppchen, wo soll man nur anfangen?", "So many tasty morsels, where does one begin?"),
        ("0A012C40.ogg", "Euer Leben wird nun ein Ende finden! Doch wenigstens könnt Ihr meiner Armee im Tode beitreten!", "Your life will now come to an end! But at least you may join my army in death!"),
        ("0A012D58.ogg", "Ein weiterer Narr stirbt, um bald meinen Befehlen zu gehorchen!", "Another fool dies, soon to rise up by my bidding!"),
        ("0A012BA8.ogg", "Geht zurück zu den Schatten!", "Return to the shadows!")
    ],
    
    # 13. Narrator (Atmospheric, deep, clear storytelling)
    "narrator": [
        ("0A0085A0.ogg", "Dieser Tag eignet sich gut, um Geschichten zu erzählen.", "This day is well suited for telling tales."),
        ("0A013999.ogg", "Doch die Menschen des Gebirges weigerten sich, ihrem Eid Folge zu leisten.", "Yet the Men of the Mountains refused to fulfill their oath."),
        ("0A01002E.ogg", "Ich kann kaum schlafen, da die Schatten der Nacht Angst bereiten.", "Sleep escapes me, for the night shadows bring fear."),
        ("0A0085A5.ogg", "Angmar wirft seine finsteren Schatten über das Land.", "Angmar casts its dark shadow across the land."),
        ("0A0085A7.ogg", "Unheilvolle Stimmen flüstern im Wind der Dämmerung.", "Ominous voices whisper in the twilight wind."),
        ("0A01001E.ogg", "Böse Dinge wandern durch die finstere Nacht.", "Evil things wander through the dark of night.")
    ]
}

def assemble_library(output_base="data/voices"):
    base_path = Path(output_base)
    german_src = Path(r"D:\temp\lotro-voices\german")
    english_src = Path(r"D:\temp\lotro-voices\english")
    
    for lang, src_dir in [("de", german_src), ("en", english_src)]:
        print(f"\n========================================================")
        print(f"Assembling Production Voice Library: [{lang.upper()}]")
        print(f"Source: {src_dir}")
        print(f"Target: {base_path / lang}")
        print(f"========================================================")
        
        lang_dir = base_path / lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        
        index_items = []
        
        for category, voice_list in CURATED_MAP.items():
            cat_dir = lang_dir / category
            cat_dir.mkdir(parents=True, exist_ok=True)
            for old_f in cat_dir.glob("*.*"):
                try:
                    old_f.unlink()
                except Exception:
                    pass
            
            for idx, (ogg_file, text_de, text_en) in enumerate(voice_list, 1):
                voice_id = f"{category}_{idx}"
                src_file = src_dir / ogg_file
                
                if not src_file.exists():
                    print(f"WARNING: File {src_file} not found! Skipping.")
                    continue
                    
                dst_ogg = cat_dir / f"{voice_id}.ogg"
                dst_txt = cat_dir / f"{voice_id}.txt"
                
                shutil.copyfile(str(src_file), str(dst_ogg))
                
                selected_text = text_de if lang == "de" else text_en
                dst_txt.write_text(selected_text, encoding="utf-8")
                
                gender = "female" if "female" in category else ("neutral" if category in ["narrator", "ent", "dead"] else "male")
                race = category.split("_")[0]
                
                index_items.append({
                    "voice_id": voice_id,
                    "category": category,
                    "gender": gender,
                    "race": race,
                    "original_file": ogg_file,
                    "text": selected_text,
                    "audio_file": str(dst_ogg.relative_to(base_path))
                })
                
            print(f"  [OK] {category:<16}: {len(voice_list)} authentic voices")
            
        index_file = lang_dir / "voice_index.json"
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index_items, f, indent=2, ensure_ascii=False)
            
        print(f"Wrote master index: {index_file} ({len(index_items)} total profiles)")

if __name__ == "__main__":
    assemble_library("data/voices")
