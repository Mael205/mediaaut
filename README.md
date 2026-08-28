# mediaaut

<https://mael205.github.io/mediaaut/>

Pipeline automatise de creation et de publication de videos courtes et longues.
Tout tourne en local, sans service payant sur le chemin critique.

## Etat

| Phase | Contenu | Etat |
|-------|---------|------|
| 1 | Socle + rendu d'un short de bout en bout | **fait** |
| 2 | Publication YouTube + b-roll de banque | **fait** |
| 3 | Publication Instagram + TikTok | **fait** |
| 4 | Pipeline de decoupage (video longue -> shorts) | **fait** |
| 5 | Ecriture des scripts par LLM + file d'idees | **fait** |
| 6 | Scheduler + rotation des templates | a faire |
| 9 | Production long-form (16:9, chapitree, miniature) | **fait** |
| -- | Console locale de mise en ligne assistee | **fait** |
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

# produire une semaine de videos d'un coup
.venv\Scripts\mediaaut batch ai-builders-en -n 7

# console locale : file de mise en ligne, metadonnees a un clic
.venv\Scripts\mediaaut studio

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
  clip/        decoupage d'une video longue en shorts verticaux
  longform/    videos longues 16:9, ecrites section par section
  script/      ecriture des idees et des scripts par Claude
  ideas/       file d'idees par chaine, avec garde anti-repetition
  studio/      console locale de mise en ligne, tant que l'audit n'est pas accorde
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

**Mise en ligne manuelle assistee, pas contournee.** Tant que l'audit n'est pas
accorde, `videos.insert` verrouille toute video en prive definitivement, sans
recours. La console `mediaaut studio` ne contourne pas cette regle : elle reduit
le geste manuel a son minimum et enregistre l'etat. Le televersement reste fait
par un humain sur youtube.com, parce que piloter le site par navigateur viole
les CGU de YouTube et expose la chaine — l'actif meme qu'on construit.

**Instagram et TikTok n'attendent aucun audit.** Instagram publie depuis une
application Meta en mode Developpement des lors que le compte vise porte le role
« Instagram Tester » — la revue ne concerne que les comptes qu'on ne possede
pas. TikTok depose en brouillon via le scope `video.upload`, sans audit ; seul
le Direct Post en exige un. Les deux sont donc automatisables integralement
aujourd'hui, la ou YouTube reste manuel.

**Envoi de fichier local sur Instagram.** L'API Reels attend normalement une URL
publique, ce qui obligerait a heberger les videos. `upload_type=resumable` evite
cela : le binaire part sur `rupload.facebook.com`, un hote distinct du reste de
l'API.

**Dossier de donnees redirigeable.** `MEDIAAUT_DATA`, lu depuis l'environnement
ou depuis `.env`, deplace `data/` vers un dossier synchronise. Produire sur une
machine et mettre en ligne depuis une autre ne demande rien de plus.

**Le decoupage produit du volume sans consommer d'idees.** Six extraits d'une
meme video sont six sujets distincts sans avoir eu a en trouver six — et comme
le contenu vient d'un enregistrement reel, il echappe entierement a la question
du contenu fabrique.

**Le hook sert d'ancre de position, pas de decoration.** Les horodatages rendus
par le modele derivent : un extrait annonce a 59 s visait en realite un passage
trente secondes plus loin, et son titre ne correspondait plus au contenu. On
demande donc au modele de recopier la premiere phrase du passage, puis on la
retrouve dans la transcription pour corriger la position.

## Politique de contenu

YouTube a renomme sa regle « Repetitious Content » en « Inauthentic Content »
en juillet 2026 et cible explicitement le contenu « qui semble fait avec un
modele, avec peu ou pas de variation d'une video a l'autre ». La rotation des
templates (`render/templates.py`) et l'angle editorial impose par chaine
(`channels.yaml`) sont des contre-mesures directes, pas de la decoration.
