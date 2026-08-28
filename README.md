# mediaaut

<https://mael205.github.io/mediaaut/>

Pipeline automatise de creation et de publication de videos courtes et longues.
Tout tourne en local, sans service payant sur le chemin critique.

## Etat

| Phase | Contenu | Etat |
|-------|---------|------|
| 1 | Socle + rendu d'un short de bout en bout | **fait** |
| 2 | Publication YouTube + b-roll de banque | **fait** |
| 3 | Publication Instagram + TikTok | a faire |
| 4 | Pipeline de decoupage (video longue -> shorts) | a faire |
| 5 | Ecriture des scripts par LLM + file d'idees | **fait** |
| 6 | Scheduler + rotation des templates | a faire |
| 7 | Doublage FR | a faire |
| 8 | Video generative locale (LTX / Wan) | a faire |

## Installation

```powershell
winget install Gyan.FFmpeg
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m pip install faster-whisper kokoro-onnx nvidia-cublas-cu12 nvidia-cudnn-cu12 yt-dlp
copy .env.example .env
```

Puis verifier :

```powershell
.venv\Scripts\mediaaut doctor
```

## Utilisation

```powershell
# chaines configurees
.venv\Scripts\mediaaut channels

# voix disponibles
.venv\Scripts\mediaaut voices --lang en

# generer un short depuis un script
.venv\Scripts\mediaaut make ai-builders-en --script-file script.txt

# forcer un template et fournir du b-roll local
.venv\Scripts\mediaaut make ai-builders-en -f script.txt -t split_top -b clip1.mp4 -b clip2.mp4

# b-roll cherche automatiquement en banque (necessite PEXELS_API_KEY)
.venv\Scripts\mediaaut make ai-builders-en -f script.txt -q "developer coding" -q "server room" --title "Automate the right half" --tag ai --tag automation

# autoriser YouTube (une fois par chaine), puis publier
.venv\Scripts\mediaaut auth youtube --channel ai-builders-en
.venv\Scripts\mediaaut publish ai-builders-en-20260828-150709 --dry-run
.venv\Scripts\mediaaut publish ai-builders-en-20260828-150709
```

Chaque job ecrit dans `data/out/<job-id>/` : `voice.wav`, `subs.ass`, `script.txt`,
`short.mp4` et `result.json`. Les etapes intermediaires sont conservees pour
pouvoir diagnostiquer un rendu rate sans tout relancer.

## Architecture

```
src/mediaaut/
  core/        config (.env + channels.yaml), logging, chemins, ffmpeg, GPU, reseau
  voice/       synthese vocale derriere une interface (Kokoro local par defaut)
  subtitles/   transcription Whisper datee au mot, calibration typographique, ASS
  assets/      polices telechargees dans le projet
  render/      templates de mise en page, composition ffmpeg
  publish/     publication par plateforme (YouTube fait, IG/TikTok a venir)
  clip/        (phase 4) decoupage de video longue
  script/      ecriture des idees et des scripts par Claude
  ideas/       file d'idees par chaine, avec garde anti-repetition
  pipeline.py  orchestration
  cli.py       point d'entree unique, y compris pour les taches planifiees
```

## Choix techniques notables

**Kokoro plutot que edge-tts.** `edge-tts` exploite un service Microsoft non
documente qui a deja casse (tokens anti-abus, filtrage des IP datacenter).
Kokoro-82M est sous Apache 2.0, tourne hors-ligne, et ne peut donc pas
disparaitre. `edge-tts` reste branchable derriere `VoiceProvider` mais n'est
jamais sur le chemin critique.

**ASS/libass plutot que Remotion.** Le karaoke mot par mot est obtenu en
emettant une ligne `Dialogue` par mot actif. Le texte est incruste pendant
l'encodage : pas de Chromium, pas de capture image par image.

**Calibration typographique mesuree.** La taille de police ASS ne correspond
pas a la taille em de Pillow, et le rapport ne se deduit pas des metriques du
fichier de police (les hypotheses fondees sur ascent + descent se trompent de
15 a 30 %). `subtitles/metrics.py` mesure le rapport reel une fois par police
via un rendu temoin, et le met en cache. C'est ce qui permet a chaque cue de
remplir le cadre au lieu de flotter au milieu.

**Chemins ffmpeg resolus explicitement.** Windows ne rafraichit pas le PATH des
shells ouverts, et une tache planifiee n'a pas le meme environnement qu'une
session interactive. `core/ffmpeg.py` localise le binaire lui-meme.

**DLL CUDA exposees via le PATH.** `os.add_dll_directory` ne suffit pas :
CTranslate2 charge cuBLAS depuis du code natif, qui utilise l'ordre de
recherche Windows standard. `core/gpu.py` fait les deux, avant tout import de
`faster_whisper`.

**Loudness normalise a -14 LUFS.** YouTube, Instagram et TikTok ramenent tous
la lecture autour de cette valeur. Livrer plus fort ne rend pas plus fort : cela
fait seulement travailler leur limiteur sur le mix. Livrer plus faible fait
paraitre la video timide dans le fil.

**Visibilite relue apres upload.** La reponse de `videos.insert` reflete ce qui a
ete demande, pas ce que YouTube a applique. Sur un projet API non audite, l'ecart
entre les deux est exactement l'information utile, donc `publish/youtube.py`
relit l'etat reel et le remonte au lieu d'annoncer un succes trompeur.

**Un jeton OAuth par chaine.** Le projet Google Cloud, le client OAuth et
l'audit de conformite sont au niveau du projet : un seul suffit pour toutes les
chaines. Ce qui differe est le consentement, qui designe la chaine YouTube
ciblee. `secrets/youtube_token-<chaine>.json` les separe, faute de quoi
autoriser une deuxieme chaine ecraserait silencieusement la premiere.

**Anti-repetition mesuree, pas declarative.** Deux titres qui disent la meme
chose sous des formulations differentes sont bloques par un recouvrement de
Jaccard sur des racines lexicales (`ideas/store.py`). La premiere version
comparait les mots bruts et laissait passer « How I automated my channel » face
a « Automating a channel: how I did it » ; les cas qui ont motive le seuil
actuel sont figes dans `tests/test_ideas.py`.

**Debit de narration cale sur la mesure.** 215 mots par minute, moyenne relevee
sur deux shorts narratifs a tres forte audience (214 et 228). Un script ecrit
sans budget de mots produit une video deux fois trop longue pour sa duree visee.

## Politique de contenu

YouTube a renomme sa regle « Repetitious Content » en « Inauthentic Content »
en juillet 2026 et cible explicitement le contenu « qui semble fait avec un
modele, avec peu ou pas de variation d'une video a l'autre ». La rotation des
templates (`render/templates.py`) et l'angle editorial impose par chaine
(`channels.yaml`) sont des contre-mesures directes, pas de la decoration.
