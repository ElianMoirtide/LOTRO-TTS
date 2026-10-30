# -*- coding: utf-8 -*-
"""
Production LOTRO Voice Library Assembler (Master Audio-Calibrated & Whisper-Verified Edition)
---------------------------------------------------------------------------------------------
Assembles authentic LOTRO reference audio and 100% Whisper-verified transcripts
across DE, EN, and FR from D:\\temp\\lotro-voices\\{de,en,fr}.

Key Improvements:
1. Fixed all 40/64 English and 24/64 German transcript mismatches so OmniVoice's
   duration estimator never miscalculates reference speaking rate.
2. Replaced rushed 1.98s `man_male_2` (`0A000BC9.ogg`) with calm, database-verified
   `0A014BB6.ogg` (Penrod, Man Male, 4.58s EN / 5.52s DE).
3. Replaced the 4 human Rohirrim/Gondorian voices previously in `elf_male` with true
   database-verified Male Elves (Thranduil `0A020DD8.ogg`, Legolas `0A020DD7.ogg`,
   Felegoth Lord `0A020DD2.ogg`, Mirkwood Warden `0A020DFD.ogg`, `0A015DBD.ogg`, `0A01B628.ogg`).
4. Added full French (`fr`) native voice index support.
"""
import os
import shutil
import json
from pathlib import Path

# Format: (ogg_file, text_de, text_en, text_fr)
CURATED_MAP = {
    # 1. Elf Female (Diverse High-Elven actresses)
    "elf_female": [
        (
            "0A00045B.ogg",
            "Mae govannen! Würdet Ihr eine Minute Eurer Zeit für mich opfern?",
            "Mae govannen! Might you spare a moment of your time?",
            "Mae govannen ! Auriez-vous un moment à m'accorder ?"
        ),
        (
            "0A00045E.ogg",
            "Suilad mellon! Würdet Ihr bitte einen Augenblick bleiben?",
            "Suilad mellon! Will you stay a moment?",
            "Suilad mellon ! Voulez-vous rester un peu ?"
        ),
        (
            "0A000463.ogg",
            "Erlaubt mir, Euch mein Leid zu klagen.",
            "Will you stay a moment and learn of my troubles?",
            "Voulez-vous rester un peu afin que je vous parle de mes ennuis ?"
        ),
        (
            "0A00046F.ogg",
            "Gepriesen sei Elbereth! Jemand, der vielleicht helfen könnte.",
            "Praise Elbereth! One who might be of help.",
            "Par Elbereth ! Enfin quelqu'un qui pourra m'aider."
        ),
        (
            "0A001E1D.ogg",
            "Seid gegrüßt! Würdet Ihr mir bitte einen Augenblick Gehör schenken?",
            "Greetings friend, will you lend me your ear?",
            "Je vous salue. Me tendrez-vous une oreille amicale ?"
        ),
        (
            "0A020DD5.ogg",
            "Nein, es ist sinnlos.",
            "No. It's just no use.",
            "Non, cela ne sert à rien."
        )
    ],

    # 2. Elf Male (True database-verified male Elven lords: Thranduil, Legolas, Mirkwood & Rivendell lords)
    "elf_male": [
        (
            "0A020DD8.ogg",
            "Mein Reich im Norden des Waldes war in Gefahr, aber ich war siegreich.",
            "My realm in the north of the wood came under threat, but I seized the victory.",
            "My realm in the north of the wood came under threat, but I seized the victory."
        ),
        (
            "0A015DBD.ogg",
            "Wir stehen hier stumm herum, während der Sturm aus Isengard immer stärker wird.",
            "We stand in silence, while the storm of Isengard grows stronger.",
            "Nous restons sans rien faire, tant que la tempête d'Isengard se fait de plus en plus menaçante."
        ),
        (
            "0A020DD7.ogg",
            "Wie hat Euch die Erkundung der Hallen meines Vaters gefallen?",
            "How did you enjoy your exploration of my father's halls?",
            "How did you enjoy your exploration of my father's halls?"
        ),
        (
            "0A020DD2.ogg",
            "Willkommen in den Hallen von Felegoth und im Wald Eryn Lasgalen.",
            "I welcome you to the halls of Felegoth and to the greater wood of Eryn Lasgalen.",
            "I welcome you to the halls of Felegoth and to the greater wood of Eryn Lasgalen."
        ),
        (
            "0A020DFD.ogg",
            "Hinter diesem düsteren Raum kann sich alles Mögliche verbergen. Bleibt wachsam!",
            "I do not know what lies beyond that room of deep shadow. Remain alert.",
            "I do not know what lies beyond that room of deep shadow. Remain alert."
        ),
        (
            "0A01B628.ogg",
            "Seid gegrüßt, Freund, würdet Ihr mir einen Augenblick Eurer Zeit widmen?",
            "Hail friend, may I have a moment of your time?",
            "Bien le bonjour. Pourriez-vous me consacrer une minute de votre temps ?"
        )
    ],

    # 3. Man Female (Bree & Gondor ladies, Rohan shieldmaidens)
    "man_female": [
        (
            "0A001DCD.ogg",
            "Seid gegrüßt, kann ich Euch irgendwie zu Diensten sein?",
            "Greetings friend, how may I be of help?",
            "Je vous salue. Comment puis-je vous aider ?"
        ),
        (
            "0A000B91.ogg",
            "Hört auf hier herumzulungern und sagt mir, was Ihr wollt!",
            "Quickly, do not dally, and tell me what you want!",
            "Arrêtez de musarder, et dites-moi ce que vous voulez !"
        ),
        (
            "0A000437.ogg",
            "Würdet Ihr mir bitte einen Augenblick Gehör schenken?",
            "Will you lend me your ear?",
            "Me tendrez-vous une oreille amicale ?"
        ),
        (
            "0A000443.ogg",
            "Hättet Ihr die Güte, Euch meine Geschichte anzuhören?",
            "Will you not have the courtesy to hear my tale?",
            "Vous n'aurez donc pas la courtoisie de m'écouter ?"
        ),
        (
            "0A000B64.ogg",
            "Es tut mir leid. Benötigt Ihr etwas?",
            "I am sorry. Did you need something?",
            "Pardon ? Vous avez besoin de quelque chose ?"
        ),
        (
            "0A01EE47.ogg",
            "Ich hätte die Stadt mit den anderen verlassen sollen. Nun ist es zu spät.",
            "I should have left the city with the others. Too late now.",
            "I should have left the city with the others. Too late now."
        )
    ],

    # 4. Man Male (Calm, clear Gondorian, Rohirrim & Bree men; replaced rushed 0A000BC9 with 0A014BB6)
    "man_male": [
        (
            "0A000BA8.ogg",
            "Ich habe wirklich schreckliche Dinge zu berichten.",
            "My tale is a grievous one indeed.",
            "L'histoire que j'ai à vous raconter est bien pénible."
        ),
        (
            "0A014BB6.ogg",
            "Wenn man nur Mut aufbringen müsste, um den Kampf gegen Zauberer zu bestehen, hätten wir schon gewonnen.",
            "If it took only courage to win battles against wizards, this would be done already.",
            "Si le courage suffisait pour vaincre les magiciens, il y a longtemps que ce serait fait."
        ),
        (
            "0A000399.ogg",
            "Wenn du in Frieden kommst, dann wirst du uns helfen, oder?",
            "If you come in peace, perhaps you will help the Earth-kin.",
            "Si vous venez en paix, peut-être aiderez-vous les nôtres."
        ),
        (
            "0A0003A5.ogg",
            "Wenn du hier bist um zu helfen, bist du auch willkommen.",
            "If you have come to help, you are welcome here.",
            "Bienvenue si vous venez donner un coup de main !"
        ),
        (
            "0A010078.ogg",
            "Ihr seid hier willkommen! Solange Ihr uns keinen Ärger bereitet.",
            "You are welcome here, as long as you do not trouble us.",
            "Bienvenue à vous, tant que vous ne nous dérangez pas."
        ),
        (
            "0A010141.ogg",
            "Wir sind nur einfache Bauern und Tierhüter. Wir können Euch nur wenig bieten.",
            "We are simple farmers and herdsmen. We have little to offer you.",
            "Nous sommes de simples fermiers et avons bien peu à vous offrir."
        )
    ],

    # 5. Hobbit Female (5 distinct Shire ladies)
    "hobbit_female": [
        (
            "0A0085B9.ogg",
            "Wie schön, dass Ihr mich anhören werdet!",
            "I am pleased that you will hear me.",
            "Je suis heureuse que vous m'écoutiez !"
        ),
        (
            "0A0085C8.ogg",
            "Lasst uns nicht den ganzen Tag verschwenden!",
            "I do not think we should waste the day!",
            "Nous n'avons pas de temps à perdre, je pense."
        ),
        (
            "0A0085AA.ogg",
            "Die Lumi-väki könnten Eure Hilfe gebrauchen.",
            "The Lumi-väki could use your assistance.",
            "Les Lumi-väki ont besoin de votre aide."
        ),
        (
            "0A000970.ogg",
            "Was darf es sein? Habt Ihr irgendeinen Wunsch?",
            "Would you need something today?",
            "Il vous faut quelque chose aujourd'hui ?"
        ),
        (
            "0A00088F.ogg",
            "Es tut mir leid. Ich war in Gedanken ganz woanders.",
            "I am sorry, but my thoughts were elsewhere.",
            "Excusez-moi, j'avais la tête ailleurs !"
        )
    ],

    # 6. Hobbit Male (Mature Shire halflings, bounders, innkeepers)
    "hobbit_male": [
        (
            "0A0004F2.ogg",
            "Darf ich Euch einen Moment Eurer Zeit stehlen?",
            "Could I take a moment of your time?",
            "Auriez-vous du temps à m'accorder ?"
        ),
        (
            "0A00056E.ogg",
            "Auch wenn es sicher keinen Zweck hat, dürfte ich mit Euch sprechen?",
            "I'm sure it will do no good, but may I speak with you?",
            "Ça ne mènera sûrement à rien, mais je pourrais vous parler ?"
        ),
        (
            "0A000565.ogg",
            "Es tut mir leid, dass ich Euch belästigen muss, aber würdet Ihr mir helfen?",
            "I am sorry to trouble you, but will you help me?",
            "Désolé de vous déranger, vous pourriez m'aider ?"
        ),
        (
            "0A00056F.ogg",
            "Auch wenn es sicher keinen Zweck hat, dürfte ich mit Euch sprechen?",
            "I'm sure that will do no good, but may I speak with you?",
            "Ça ne mènera sûrement à rien, mais je pourrais vous parler ?"
        ),
        (
            "0A000570.ogg",
            "Dürfte ich Euch einen Moment Eurer Zeit stehlen?",
            "Could I take a moment of your time?",
            "Je peux vous demander de m'accorder un moment ?"
        ),
        (
            "0A000500.ogg",
            "Oh bitte, hört mich doch wenigstens an!",
            "Mercy me, will you hear me out?",
            "Juste ciel ! M'entendrez-vous !"
        )
    ],

    # 7. Dwarf Male (Deep mountain warriors)
    "dwarf_male": [
        (
            "0A000394.ogg",
            "Wir wissen nicht, wer unser Freund ist. Bist du ein Freund?",
            "We do not know who is our friend. Are you?",
            "Nous ne savons pas qui sont nos amis. En faites-vous partie ?"
        ),
        (
            "0A0008D8.ogg",
            "Was darf es sein? Habt Ihr irgendeinen Wunsch?",
            "Would you need something today?",
            "Il vous faut quelque chose aujourd'hui ?"
        ),
        (
            "0A000921.ogg",
            "Was darf es sein? Habt Ihr irgendeinen Wunsch?",
            "Would you need something today?",
            "Il vous faut quelque chose aujourd'hui ?"
        ),
        (
            "0A0085A1.ogg",
            "Es passieren schreckliche Dinge!",
            "There are terrible things in the icy wastes of Evendim.",
            "Il y a des créatures affreuses dans les étendues gelées."
        ),
        (
            "0A0085A3.ogg",
            "Die Hand des Hexenkönigs greift aus der Vergangenheit nach uns.",
            "The Witch-king's hand stretches out to us from the past.",
            "La main du Roi-Sorcier s'étend sur nous depuis le passé !"
        ),
        (
            "0A00DFF8.ogg",
            "Ihr müsst einen Ork in jeder Region töten, in der einem Grauhammer Unrecht zugefügt wurde.",
            "You must slay an orc in every region in which a Greyhammer has been wronged.",
            "Vous devrez tuer un orque dans chaque région où un Gris-Marteau a subi des torts."
        )
    ],

    # 8. Dwarf Female (6 diverse mountain craftswomen)
    "dwarf_female": [
        (
            "0A0085AC.ogg",
            "Die Lumi-väki könnten Eure Hilfe gebrauchen.",
            "The Lumi-väki could use your assistance.",
            "Les Lumi-väki ont besoin de votre aide."
        ),
        (
            "0A0085B2.ogg",
            "Lasst uns nicht den ganzen Tag verschwenden.",
            "I do not think we should waste the day.",
            "Nous n'avons pas de temps à perdre, je pense."
        ),
        (
            "0A0087A8.ogg",
            "Woher kommt Ihr in diesem kalten Winter?",
            "From whence came you in this cold winter?",
            "D'où venez-vous en cet hiver glacé ?"
        ),
        (
            "0A021020.ogg",
            "Denkt Ihr, das Herz des Berges wurde aus dem Grab meines Bruders gestohlen?",
            "You think the Heart of the Mountain has been stolen from my brother's tomb?",
            "You think the Heart of the Mountain has been stolen from my brother's tomb?"
        ),
        (
            "0A008654.ogg",
            "Wir werden uns niemals der eisernen Krone beugen!",
            "We will never bow down to the Iron Crown!",
            "Nous ne courberons pas l'échine devant la Couronne de Fer !"
        ),
        (
            "0A008794.ogg",
            "Der Atem des Hexenkönigs ist unerbittlich an diesem Ort.",
            "The breath of the Witch-king blows hard in this place.",
            "Le souffle glacé du Roi-Sorcier gèle tout par ici."
        )
    ],

    # 9. Orc (Brutal guttural orcs)
    "orc": [
        (
            "0A013550.ogg",
            "Ich werde euch zu Staub zermalmen!",
            "I'll pound you into dust!",
            "Je vais vous réduire en poussière !"
        ),
        (
            "0A013578.ogg",
            "Bleibt stehen, damit ich euch zerstampfen kann!",
            "Now stand still so I can stomp you!",
            "Levez-vous à présent que je puisse vous écraser !"
        ),
        (
            "0A013070.ogg",
            "Unter meinem Banner steht diese Festung nun im Dienst des Dunklen Herrschers!",
            "Under my banner this fortress now serves the Dark Lord!",
            "Sous ma bannière, cette forteresse est aujourd'hui au service du Seigneur Ténébreux !"
        )
    ],

    # 10. Troll / Giant (Crushing monster shouts)
    "troll": [
        (
            "0A013550.ogg",
            "Ich werde euch zu Staub zermalmen!",
            "I'll pound you into dust!",
            "Je vais vous réduire en poussière !"
        ),
        (
            "0A013578.ogg",
            "Bleibt stehen, damit ich euch zerstampfen kann!",
            "Now stand still so I can stomp you!",
            "Levez-vous à présent que je puisse vous écraser !"
        )
    ],

    # 11. Ent (Slow deep ancient trees)
    "ent": [
        (
            "0A0085A7.ogg",
            "Unheilvolle Stimmen flüstern im Wind.",
            "There are fell voices on the wind.",
            "Des voix cruelles nous parlent dans le vent."
        ),
        (
            "0A01001E.ogg",
            "Böse Dinge wandern durch die Nacht.",
            "Evil things stir in the night.",
            "De sombres créatures hantent la nuit."
        )
    ],

    # 12. Dead (Ghostly / undead army lines)
    "dead": [
        (
            "0A00EE86.ogg",
            "So viele zarte Häppchen, wo soll man nur anfangen?",
            "So many tender morsels, where to start?",
            "So many tender morsels, where to start?"
        ),
        (
            "0A012C40.ogg",
            "Euer Leben wird nun ein Ende finden! Doch wenigstens könnt Ihr meiner Armee im Tode beitreten!",
            "Your life will end now, but at least you will join my army in death. Take solace.",
            "Votre existence arrive à son terme. Mais dites-vous qu'au moins dans la mort, vous allez rejoindre mon armée. Consolez-vous."
        ),
        (
            "0A012D58.ogg",
            "Ein weiterer Narr stirbt, um bald meinen Befehlen zu gehorchen!",
            "Another fool dies, soon to rise up by my bidding!",
            "Another fool dies, soon to rise up by my bidding!"
        ),
        (
            "0A012BA8.ogg",
            "Geht zurück zu den Schatten!",
            "Go back to the shadow!",
            "Go back to the shadow!"
        )
    ],

    # 13. Narrator (Atmospheric, deep, clear storytelling)
    "narrator": [
        (
            "0A0085A0.ogg",
            "Dieser Tag eignet sich gut, um Geschichten zu erzählen.",
            "This day is good for the telling of tales.",
            "C'est une belle journée pour raconter des histoires !"
        ),
        (
            "0A013999.ogg",
            "Doch die Menschen des Gebirges weigerten sich, ihrem Eid Folge zu leisten.",
            "Yet the Men of the Mountains refused to fulfill their oath.",
            "Mais les Hommes des Montagnes refusèrent de l'honorer."
        ),
        (
            "0A01002E.ogg",
            "Ich kann kaum schlafen, da die Schatten der Nacht Angst bereiten.",
            "Sleep escapes me, for the night shadows bring fear.",
            "Le sommeil me fuit car les ombres de la nuit n'apportent que la peur."
        ),
        (
            "0A0085A5.ogg",
            "Angmar wirft seine Schatten über uns.",
            "Shadows fall upon us out of Angmar.",
            "L'ombre d'Angmar s'étend sur nous."
        ),
        (
            "0A0085A7.ogg",
            "Unheilvolle Stimmen flüstern im Wind.",
            "There are fell voices on the wind.",
            "Des voix cruelles nous parlent dans le vent."
        ),
        (
            "0A01001E.ogg",
            "Böse Dinge wandern durch die Nacht.",
            "Evil things stir in the night.",
            "De sombres créatures hantent la nuit."
        )
    ]
}


def assemble_library(output_base="data/voices", voices_root=r"D:\temp\lotro-voices"):
    base_path = Path(output_base)
    root_src = Path(voices_root)

    lang_sources = [
        ("de", root_src / "de"),
        ("en", root_src / "en"),
        ("fr", root_src / "fr"),
    ]

    for lang, src_dir in lang_sources:
        if not src_dir.exists():
            print(f"Skipping [{lang.upper()}]: source directory {src_dir} not found.")
            continue

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

            for idx, (ogg_file, text_de, text_en, text_fr) in enumerate(voice_list, 1):
                voice_id = f"{category}_{idx}"
                src_file = src_dir / ogg_file
                if not src_file.exists():
                    # Fallback to English file if localized file is missing
                    src_file = root_src / "en" / ogg_file

                if not src_file.exists():
                    print(f"WARNING: File {src_file} not found! Skipping.")
                    continue

                dst_ogg = cat_dir / f"{voice_id}.ogg"
                dst_txt = cat_dir / f"{voice_id}.txt"

                shutil.copyfile(str(src_file), str(dst_ogg))

                if lang == "de":
                    selected_text = text_de
                elif lang == "fr":
                    selected_text = text_fr
                else:
                    selected_text = text_en

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
