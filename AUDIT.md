# Formulaire d'audit YouTube API — fiche de réponses

Formulaire : <https://support.google.com/youtube/contact/yt_api_form>

Objectif : lever le verrouillage en privé des vidéos uploadées par API. **Ce
n'est pas une demande d'extension de quota** — le quota par défaut (100 uploads
par jour) suffit largement, et une demande sans extension passe beaucoup mieux.

Les champs marqués `[À REMPLIR]` contiennent des données personnelles que je ne
peux pas deviner. Tout le reste est prêt à coller.

---

## À faire avant d'ouvrir le formulaire

1. ~~Publier les deux pages sur GitHub Pages~~ — **fait**, elles sont en ligne :
   - <https://mael205.github.io/mediaaut/>
   - <https://mael205.github.io/mediaaut/privacy.html>
2. **Créer le projet Google Cloud** et noter son **numéro de projet** (un
   nombre, pas l'identifiant texte) : Console → page d'accueil du projet.
3. **Prendre trois captures d'écran** :
   - la page d'accueil publiée (navigateur, URL visible)
   - la page de politique de confidentialité (navigateur, URL visible)
   - le terminal pendant `mediaaut publish`, montrant l'upload — c'est la
     preuve « Upload Interface »

---

## Section 1 — Motif de la demande

| Champ | Réponse |
|---|---|
| Select the reason for your request | `Complete a compliance audit to request for additional quota` |

> C'est le seul choix ouvert à un premier audit. On demandera malgré tout le
> quota par défaut en section 5, ce qui est cohérent et attendu.

---

## Section 2 — Identité et contacts

| Champ | Réponse |
|---|---|
| Are you applying | **As an individual user** |
| Your Full Legal Name | `Maël Mouisset--Ferrara` |
| Your Organization's Legal Name | *(laisser vide, ou recopier ton nom légal si le champ est obligatoire)* |
| Parent Company Name | *(vide)* |
| Your Organization's Primary Website | `https://Mael205.github.io/mediaaut/` |
| Country | `France` |
| Street Address | `[À REMPLIR]` |
| City | `[À REMPLIR]` |
| State/Province | `[À REMPLIR — ta région]` |
| Postal Code | `[À REMPLIR]` |
| Category | `Media/Entertainment` |
| Organization Size / Type | `Individual` (ou `Startup` si `Individual` n'existe pas) |

**Primary Contact / Technical Contact / Business Contact** : cocher
« Same as Primary Contact » partout.

| Champ | Réponse |
|---|---|
| Name | `Maël Mouisset--Ferrara` |
| Email | `maelmouisset1@gmail.com` |

---

## Section 3 — Activité et modèle économique

### « Describe your organization's work as it relates to YouTube »

*(100 à 5000 caractères — à coller tel quel)*

```
mediaaut is a personal, self-hosted command-line tool that I built and use
alone. It produces short-form videos and uploads them to YouTube channels that
I personally own.

The tool runs entirely on my own computer. There is no server, no hosted
service, no sign-up, and no other user. Everything upstream of the upload is
local: narration is synthesised with Kokoro-82M, an Apache-2.0 text-to-speech
model running offline; subtitle timing comes from faster-whisper running on my
own GPU; captions and compositing are done with ffmpeg and libass. Background
footage, when used, comes from the Pexels and Pixabay APIs under licences that
permit commercial use.

My use of the YouTube Data API is deliberately narrow. I call exactly three
endpoints. videos.insert uploads a video I produced, to my own channel.
videos.list reads back the privacy status of the video I have just uploaded, so
the tool reports accurately what YouTube actually applied rather than what was
requested. channels.list confirms which of my channels a stored OAuth token
belongs to, before anything is uploaded, so that a video is never sent to the
wrong channel.

I do not search YouTube, do not retrieve other creators' content, do not
collect analytics, and do not store YouTube data beyond the OAuth token, the
channel identity, and the identifier of each video I have uploaded myself. No
data is shared with any third party.

Because narration is machine-generated, every upload sets
status.containsSyntheticMedia to true, so YouTube's altered-or-synthetic-content
disclosure is applied automatically rather than depending on my remembering to
set it.

I am requesting this audit solely to lift the private-visibility restriction
that applies to unaudited projects. I am not requesting quota above the default
allocation.
```

### Autres champs

| Champ | Réponse |
|---|---|
| Who is your target audience? | `General consumers` (et `Content creators` si tu veux) |
| How does your API Client monetize or generate revenue? | `Not monetized` si l'option existe. Sinon `Advertising` — le revenu vient du programme partenaire YouTube sur mes propres vidéos, pas de l'outil. |
| Do you sell advertisements or sponsorships ON or WITHIN YouTube video content? | **No** |
| If yes, prior written approval from YouTube? | *(sans objet)* |
| Do you currently have a designated Google Partner Manager? | **No** |
| Representative Name / Email / Team | *(vide)* |
| How did you first learn about the YouTube Data API? | `Google Developer Documentation` |
| Content Owner ID(s) | *(vide — réservé aux partenaires multi-chaînes)* |
| Google Ads Customer ID(s) | *(vide)* |

---

## Section 4 — Description du client API

| Champ | Réponse |
|---|---|
| API Client Name | `mediaaut` |
| Does this API Client name contain the word "YouTube"? | **No** |
| Primary Access URL | `https://Mael205.github.io/mediaaut/` |
| Privacy Policy URL | `https://Mael205.github.io/mediaaut/privacy.html` |
| Terms of Service URL | *(vide — facultatif)* |
| Is your API Client publicly accessible? | **No** |

> Répondre **No** est important et exact : c'est un outil local à usage unique,
> sans inscription ni interface publique. Prétendre le contraire créerait une
> incohérence avec la page projet, et c'est exactement le genre d'écart qui
> fait échouer un audit.

### Demo Account Credentials

Normalement sans objet puisque le client n'est pas publiquement accessible.
Si le formulaire l'exige quand même :

| Champ | Réponse |
|---|---|
| Demo Account Username or Email | `Not applicable — local command-line tool, no accounts` |
| Demo Account Password | `Not applicable` |
| Login URL | `Not applicable` |
| Special Instructions for Access | `mediaaut is a command-line application that runs on my own machine. It has no login and no hosted interface. The source code and documentation are public at https://github.com/Mael205/mediaaut. A screenshot of the upload command in use is attached as evidence.` |

⚠️ **Ne jamais fournir tes vrais identifiants Google.** Si la case
d'acquittement bloque l'envoi, écris ce qui précède dans les instructions.

---

## Section 5 — Cas d'usage et quota

| Champ | Réponse |
|---|---|
| How many project numbers are you adding? | `1` |
| Google Cloud Project Number | `[À REMPLIR — le numéro, pas l'ID texte]` |
| Use Case Category | `Content upload / publishing` (l'option décrivant l'upload vers sa propre chaîne) |
| Does this API Client require users to sign in with their Google Account? | **Yes** — je m'authentifie moi-même par OAuth |
| Accord sur les métriques dérivées et le stockage | **Cocher** |
| Expected API Usage Volume | Le palier le plus bas (`< 1,000 queries/day`) |

### Endpoints — ne cocher que ces trois

- `youtube.videos.insert`
- `youtube.videos.list`
- `youtube.channels.list`

> Ne coche rien d'autre. Une liste courte et exacte est un signal de sérieux ;
> cocher des endpoints inutilisés est un des motifs de rejet les plus courants.

### Quota

| Champ | Réponse |
|---|---|
| What is the total quota you are requesting? | **Default** |
| Total Per Day Quota | `10000` (le défaut) |
| Peak Per Min Quota | laisser la valeur par défaut |
| Detailed Justification | voir ci-dessous |

```
I am not requesting quota above the default allocation. The default is already
far beyond my needs: I upload a small number of my own videos per day, and the
only other calls are one videos.list and one channels.list per upload.

The purpose of this request is solely to complete the compliance audit so that
videos uploaded through videos.insert are no longer restricted to private
visibility.
```

| Champ | Réponse |
|---|---|
| youtube.search.list quota | `0` — cet endpoint n'est pas utilisé |
| youtube.videos.insert — par jour | `100` (le défaut) |
| youtube.videos.insert — pic par minute | `10` |

```
A small number of uploads per day to my own channels. The default allocation of
100 videos.insert calls per day is more than sufficient.

Peak per-minute usage is negligible. Each video I publish costs exactly three
API calls: one channels.list to confirm the target channel, one videos.insert,
and one videos.list to read back the resulting privacy status. Even if two
videos were rendered and published back to back, the peak would be six calls in
a minute. I am requesting 10 as a round figure with headroom, not because I
expect to approach it.
```

### Sur le quota par minute — ce qu'il faut savoir

Google ne publie pas de valeur unique pour le « queries per minute » par défaut,
et la limite par utilisateur n'est de toute façon **pas modifiable** : seule la
limite journalière l'est. Deux conséquences pratiques :

1. **Ne demande rien d'exceptionnel ici.** Le champ sert à vérifier que ton
   usage est cohérent avec ta description, pas à négocier. Un chiffre modeste
   et justifié vaut mieux qu'un chiffre rond sorti de nulle part.
2. **Va lire ta propre valeur** avant de remplir : Google Cloud Console →
   **API et services → YouTube Data API v3 → Quotas et limites système**. Tu y
   verras les compteurs réels de ton projet. Si la valeur affichée diffère de
   ce que je propose, mets la tienne — c'est celle qui fait foi.

---

## Pièces à joindre

| Preuve demandée | Quoi fournir |
|---|---|
| Privacy Policy Screenshot | capture de `https://Mael205.github.io/mediaaut/privacy.html`, URL visible |
| Homepage Screenshot | capture de `https://Mael205.github.io/mediaaut/`, URL visible |
| Terms of Service Documentation | pas de CGU (outil personnel) — joindre à nouveau la politique de confidentialité, ou laisser vide si facultatif |
| OAuth screenshot | capture de l'écran de consentement Google pendant `mediaaut auth youtube` |
| Upload Interface screenshot | capture du terminal pendant `mediaaut publish`, montrant la progression |

---

## Ce que les relecteurs vérifient réellement

L'audit ne juge pas la qualité de ton produit : il vérifie la conformité aux
[YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies-guide).
Voici les obligations effectivement contrôlées, et où en est le dossier.

| Obligation | État | Où c'est traité |
|---|---|---|
| Politique de confidentialité publique et conforme | **fait** | `docs/privacy.html`, en ligne en https |
| Suppression des données sous 30 jours sur demande ou révocation | **fait** | section 5 de la politique |
| Ne jamais demander ni stocker identifiant/mot de passe | **fait** | OAuth uniquement, dit explicitement dans la politique |
| Pas de collecte d'identifiants, santé, opinions politiques ou religieuses | sans objet | aucune donnée d'autrui n'est traitée |
| Pas de métriques recalculées se substituant à celles de l'API | sans objet | aucune métrique n'est affichée |
| Ne pas bloquer le lecteur YouTube ni masquer titre/miniature | sans objet | aucun lecteur intégré |
| Pas de téléchargement de vidéos pour lecture hors ligne | sans objet | l'outil téléverse, il ne télécharge pas |
| **Pas de « sharding »** : plusieurs projets pour gonfler le quota | **fait** | un seul projet, déclaré tel quel |
| Divulgation du contenu altéré ou synthétique | **fait** | `containsSyntheticMedia` à chaque upload, vérifiable dans `src/mediaaut/publish/youtube.py` |

Le point le plus sanctionné est le dernier de la liste des motifs de rejet
courants : **les cas d'usage qui ressemblent à du scraping, de la collecte en
masse ou de l'analyse concurrentielle.** Ton dossier est à l'exact opposé —
trois endpoints, aucune lecture de contenu d'autrui, aucun `search.list` — et
c'est ce qu'il faut mettre en avant.

---

## Combien de temps avant une réponse

**Prévois 4 à 8 semaines, et sache que ça peut être bien plus long.**

Google ne s'engage sur aucun délai. La formule officielle est « un membre de
l'équipe vous contactera dès que possible ». Ce que rapportent les développeurs :

| Ce qu'on observe | Fréquence |
|---|---|
| Quelques semaines | cas courant |
| 4 semaines et plus de silence, relances sans réponse | fréquemment rapporté sur le forum développeurs |
| Plusieurs mois — un cas documenté à 5 mois | minoritaire mais réel |
| Accord partiel, en dessous de ce qui était demandé | courant sur les demandes d'extension |

Ce dernier point est une raison de plus de ne demander **que le quota par
défaut** : il n'y a rien à rogner, donc rien à négocier.

**Trois conséquences concrètes pour toi :**

1. **Dépose le formulaire avant tout le reste.** C'est le seul élément du projet
   dont le délai ne dépend pas de toi. Tout le reste — clés, chaînes, contenu —
   peut avancer en parallèle.
2. **Ne reste pas bloqué en attendant.** `mediaaut publish --private` fonctionne
   dès maintenant : le pipeline complet est validé, les vidéos arrivent sur la
   chaîne, elles restent simplement privées. Le jour de l'accord, tu retires le
   drapeau et tu publies.
3. **Attention aux vidéos uploadées entre-temps.** Celles envoyées par API avant
   l'accord sont verrouillées **définitivement** en privé — elles ne pourront pas
   être rendues publiques rétroactivement. Ne « stocke » donc pas des semaines de
   contenu par API en espérant tout publier à l'accord : ces fichiers seraient
   perdus. Garde les MP4 en local, ils sont dans `data/out/`.

Si aucune réponse au bout de 6 semaines, relance via le même formulaire en
citant la date de la demande initiale.

---

## Principes qui rendent ce dossier acceptable

- **Ne rien surestimer.** L'outil est personnel, local, mono-utilisateur : le
  dire clairement est plus solide qu'une présentation gonflée en « plateforme ».
- **Cohérence stricte** entre le formulaire, la page projet, la politique de
  confidentialité et le code publié. Les relecteurs comparent les trois.
- **Périmètre minimal** : trois endpoints, deux scopes, quota par défaut.
- **Divulgation du contenu synthétique déjà implémentée**, et vérifiable dans
  `src/mediaaut/publish/youtube.py`.
