# Instagram Reels — mise en service

Environ 15 minutes, **sans aucune revue d'application**. La revue de Meta ne
concerne que les comptes qu'on ne possède pas ; publier sur son propre compte
depuis une application en mode Développement ne la déclenche pas.

Meta propose deux parcours. Ce guide suit **« API setup with Instagram login »**,
qui ne demande **pas de Page Facebook**. C'est le plus court, et le défaut du
code (`IG_LOGIN_FLOW=instagram` dans `.env`).

---

## 1. Compte Instagram professionnel

Le compte doit être **Professionnel** (Business ou Créateur) : un compte
personnel ne peut pas publier par API.

Application Instagram → **Paramètres → Compte → Passer à un compte professionnel**.

⚠️ Utilise un **compte dédié**, pas ton compte personnel — même raisonnement que
pour la chaîne YouTube : isoler le risque.

## 2. Application Meta

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) →
   **Créer une application**
2. Cas d'usage : **Autre** → type **Entreprise**
3. Ajoute le produit **Instagram** → **API setup with Instagram login**

L'application **reste en mode Développement**. C'est voulu : c'est ce qui évite
la revue.

Note au passage l'**ID d'app** et la **clé secrète** (bouton « Afficher ») —
ils serviront à l'étape 4.

## 3. Rôle Testeur Instagram

C'est l'étape qu'on rate, et elle bloque tout le reste.

1. Onglet **Rôles** → **Testeur Instagram** (pas « Testeur » tout court, qui est
   un rôle sur l'application Facebook et n'accorde aucun accès au compte) →
   saisis ton pseudo Instagram
2. Le statut affiche **« en attente »**. C'est normal : l'acceptation se fait
   côté Instagram.
3. Connecte-toi sur Instagram **avec le compte invité**, puis
   [instagram.com/accounts/manage_access_tools](https://www.instagram.com/accounts/manage_access_tools/)
   → **Invitations de testeur** → **Accepter**
4. Rafraîchis la page Meta : le statut doit passer à **« Actif »**

## 4. Jeton d'accès

Dans **« 1. Générez des tokens d'accès »** → **Ajouter un compte** → autorise.
Tu obtiens un jeton.

### Le convertir en jeton longue durée

Le jeton initial est court. L'échanger contre un jeton de **60 jours** :

```powershell
curl "https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=TA_CLE_SECRETE&access_token=TON_JETON_COURT"
```

Le champ `access_token` de la réponse est celui à garder.

## 5. Identifiant du compte

```powershell
curl "https://graph.instagram.com/v23.0/me?fields=id,username&access_token=TON_JETON_LONG"
```

Le champ `id` est ton `IG_USER_ID` (un nombre, pas ton pseudo).

## 6. Renseigner `.env`

```
IG_LOGIN_FLOW=instagram
IG_USER_ID=17841400000000000
IG_ACCESS_TOKEN=IGAA...
```

## 7. Vérifier

```powershell
.venv\Scripts\mediaaut doctor
```

La ligne `instagram` doit afficher `@ton_pseudo`. Puis, sur une vidéo rendue :

```powershell
.venv\Scripts\mediaaut publish <job-id> -p instagram
```

---

## Ce que tu ne remplis pas

| Section de la page Meta | Pourquoi |
|---|---|
| **Webhooks** | Sert à *recevoir* des événements (commentaires, messages). Tu ne fais que publier. |
| **Connexion professionnelle** | Sert à faire autoriser ton app par d'autres entreprises. |
| **Contrôle app** | C'est l'App Review. Inutile pour ton propre compte — c'est tout l'intérêt du mode Développement. |

## Limites à connaître

| | |
|---|---|
| Publications par API | 25 à 100 par 24 h selon le compte — très au-dessus de tes besoins |
| Durée d'un Reel | 5 à 90 secondes |
| Format | 9:16, H.264 ou HEVC, AAC — c'est déjà ce que produit le pipeline |
| Expiration du jeton | **60 jours.** À régénérer, sinon la publication s'arrête sans prévenir |

Le jeton qui expire en silence est le piège principal. `mediaaut doctor` le
détecte : ligne `instagram` en rouge avec un code 190.

## Si ça échoue

| Message | Cause |
|---|---|
| `190` | Jeton expiré ou révoqué → en régénérer un |
| `10` | Invitation Testeur non acceptée (étape 3), ou permission manquante |
| `100` | Compte non professionnel, ou mauvais `IG_USER_ID` |
| `4` | Limite de fréquence atteinte |

Si les appels échouent sans raison claire, vérifie `IG_LOGIN_FLOW` : le parcours
Instagram Login et le parcours Facebook Login n'utilisent pas le même hôte, et
se tromper donne une erreur d'autorisation qui n'indique jamais que l'URL est
en cause.
