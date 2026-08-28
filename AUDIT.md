# Formulaire d'audit YouTube API — fiche de réponses

Formulaire : <https://support.google.com/youtube/contact/yt_api_form>

Objectif : lever le verrouillage en privé des vidéos uploadées par API. **Ce
n'est pas une demande d'extension de quota** — le quota par défaut (100 uploads
par jour) suffit largement, et une demande sans extension passe beaucoup mieux.

Les champs marqués `[À REMPLIR]` contiennent des données personnelles que je ne
peux pas deviner. Tout le reste est prêt à coller.

---

## À faire avant d'ouvrir le formulaire

1. **Publier les deux pages** (`docs/index.html` et `docs/privacy.html`) sur
   GitHub Pages :
   - créer un dépôt public `mediaaut` sur GitHub, y pousser ce projet
   - dépôt → **Settings → Pages** → Source : `Deploy from a branch`,
     branche `main`, dossier `/docs` → **Save**
   - au bout d'une minute les pages sont en ligne :
     - `https://<ton-user>.github.io/mediaaut/`
     - `https://<ton-user>.github.io/mediaaut/privacy.html`
2. **Remplacer `MAEL_NOM_LEGAL`** dans `docs/index.html` par ton nom légal,
   puis repousser.
3. **Créer le projet Google Cloud** et noter son **numéro de projet** (un
   nombre, pas l'identifiant texte) : Console → page d'accueil du projet.
4. **Prendre trois captures d'écran** :
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
| Your Full Legal Name | `[À REMPLIR — prénom + nom tels qu'à l'état civil]` |
| Your Organization's Legal Name | *(laisser vide, ou recopier ton nom légal si le champ est obligatoire)* |
| Parent Company Name | *(vide)* |
| Your Organization's Primary Website | `https://<ton-user>.github.io/mediaaut/` |
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
| Name | `[À REMPLIR — ton nom légal]` |
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
| Primary Access URL | `https://<ton-user>.github.io/mediaaut/` |
| Privacy Policy URL | `https://<ton-user>.github.io/mediaaut/privacy.html` |
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
| Special Instructions for Access | `mediaaut is a command-line application that runs on my own machine. It has no login and no hosted interface. The source code and documentation are public at https://github.com/<ton-user>/mediaaut. A screenshot of the upload command in use is attached as evidence.` |

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
| youtube.videos.insert quota | `100` par jour (le défaut), justification ci-dessous |

```
A small number of uploads per day to my own channels. The default allocation of
100 videos.insert calls per day is more than sufficient.
```

---

## Pièces à joindre

| Preuve demandée | Quoi fournir |
|---|---|
| Privacy Policy Screenshot | capture de `https://<ton-user>.github.io/mediaaut/privacy.html`, URL visible |
| Homepage Screenshot | capture de `https://<ton-user>.github.io/mediaaut/`, URL visible |
| Terms of Service Documentation | pas de CGU (outil personnel) — joindre à nouveau la politique de confidentialité, ou laisser vide si facultatif |
| OAuth screenshot | capture de l'écran de consentement Google pendant `mediaaut auth youtube` |
| Upload Interface screenshot | capture du terminal pendant `mediaaut publish`, montrant la progression |

---

## Principes qui rendent ce dossier acceptable

- **Ne rien surestimer.** L'outil est personnel, local, mono-utilisateur : le
  dire clairement est plus solide qu'une présentation gonflée en « plateforme ».
- **Cohérence stricte** entre le formulaire, la page projet, la politique de
  confidentialité et le code publié. Les relecteurs comparent les trois.
- **Périmètre minimal** : trois endpoints, deux scopes, quota par défaut.
- **Divulgation du contenu synthétique déjà implémentée**, et vérifiable dans
  `src/mediaaut/publish/youtube.py`.
