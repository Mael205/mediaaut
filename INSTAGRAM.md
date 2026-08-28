# Instagram Reels — mise en service

Environ 20 minutes, **sans aucune revue d'application**. La revue de Meta ne
concerne que les comptes qu'on ne possède pas ; publier sur son propre compte
depuis une application en mode Développement ne la déclenche pas.

À la fin, `mediaaut publish <job> -p instagram` publiera un Reel public
automatiquement, sans geste manuel.

---

## 1. Compte Instagram professionnel

Le compte doit être **Professionnel** (Business ou Créateur). Un compte
personnel ne peut pas publier par API.

Sur l'application Instagram : **Paramètres → Compte → Passer à un compte
professionnel**. Choisis Créateur ou Entreprise, peu importe.

⚠️ **Utilise un compte dédié**, pas ton compte personnel — même raisonnement que
pour la chaîne YouTube : isoler le risque.

## 2. Page Facebook liée

L'API passe par le graphe Facebook, donc le compte Instagram doit être relié à
une Page Facebook.

1. [facebook.com/pages/create](https://www.facebook.com/pages/create) — crée une
   Page (nom libre, aucune publication nécessaire)
2. Sur Instagram : **Paramètres → Partage sur d'autres applications → Facebook**,
   et relie la Page

## 3. Application Meta

1. [developers.facebook.com/apps](https://developers.facebook.com/apps) →
   **Créer une application**
2. Cas d'usage : **Autre** → type **Entreprise**
3. Nom : `mediaaut`
4. Dans le tableau de bord, ajoute le produit **Instagram** →
   **Configurer l'API avec Facebook Login**

L'application **reste en mode Développement**. C'est voulu : c'est ce qui évite
la revue.

## 4. Rôle Instagram Tester

C'est l'étape qui débloque tout, et celle qu'on oublie.

1. Dans l'application : **Rôles de l'application → Rôles → Ajouter des
   personnes** → **Testeur Instagram** → saisis ton pseudo Instagram
2. Puis **accepte l'invitation** côté Instagram :
   [instagram.com/accounts/manage_access_tools](https://www.instagram.com/accounts/manage_access_tools/)
   → **Invitations de testeur** → Accepter

Sans cette acceptation, tous les appels renvoient une erreur de permission.

## 5. Jeton d'accès

1. [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer/)
2. Application : `mediaaut`
3. **Générer un jeton d'accès utilisateur**, avec ces permissions :
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
4. Copie le jeton

### Le convertir en jeton longue durée

Le jeton de l'explorateur expire en **1 heure**. Il faut l'échanger contre un
jeton de 60 jours :

```powershell
$SHORT = "colle_le_jeton_court_ici"
$APPID = "ton_app_id"
$SECRET = "ton_app_secret"   # Paramètres → Général → Clé secrète

curl "https://graph.facebook.com/v23.0/oauth/access_token?grant_type=fb_exchange_token&client_id=$APPID&client_secret=$SECRET&fb_exchange_token=$SHORT"
```

Le champ `access_token` de la réponse est ton jeton longue durée.

## 6. Identifiant du compte Instagram

Ce n'est pas ton pseudo, c'est un identifiant numérique.

```powershell
# 1. Trouver l'identifiant de la Page
curl "https://graph.facebook.com/v23.0/me/accounts?access_token=TON_JETON_LONG"

# 2. En déduire l'identifiant du compte Instagram lié
curl "https://graph.facebook.com/v23.0/PAGE_ID?fields=instagram_business_account&access_token=TON_JETON_LONG"
```

Le champ `instagram_business_account.id` est ton `IG_USER_ID`.

## 7. Renseigner `.env`

```
IG_USER_ID=17841400000000000
IG_ACCESS_TOKEN=EAAG...
```

## 8. Vérifier

```powershell
.venv\Scripts\mediaaut doctor
```

La ligne `instagram` doit afficher `@ton_pseudo`. Puis, sur une vidéo déjà
rendue :

```powershell
.venv\Scripts\mediaaut publish <job-id> -p instagram
```

---

## Limites à connaître

| | |
|---|---|
| Publications par API | **25 à 100 par 24 h** selon le compte — très au-dessus de tes besoins |
| Durée d'un Reel | 5 à 90 secondes |
| Format | 9:16, H.264 ou HEVC, AAC — c'est déjà ce que produit le pipeline |
| Expiration du jeton | **60 jours.** À régénérer, sinon la publication s'arrête sans prévenir |

Le jeton qui expire silencieusement est le piège principal. `mediaaut doctor`
le détecte : si la ligne `instagram` passe au rouge avec un code 190, c'est ça.

## Si ça échoue

| Message | Cause |
|---|---|
| `190` | Jeton expiré ou révoqué → en régénérer un |
| `10` | Permission manquante, ou invitation Testeur non acceptée (étape 4) |
| `100` | Compte non professionnel, ou Page Facebook non liée |
| `4` | Limite de fréquence atteinte |
