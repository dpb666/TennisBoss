# 📲 Tester l'app sur un Google Pixel 9 Pro

Votre projet est sur `C:\Users\donpa\TennisBoss`, le serveur tourne dans **WSL2**.
La méthode recommandée pour relier le téléphone au serveur est **`adb reverse`
par câble USB** (simple, fiable, pas de pare-feu ni d'IP à gérer).

---

## 1. Préparer le Pixel 9 Pro

1. **Activer les options développeur**
   `Paramètres` → `À propos du téléphone` → tapez **7 fois** sur **Numéro de build**.
2. **Activer le débogage USB**
   `Paramètres` → `Système` → `Options pour les développeurs` → activez
   **Débogage USB**.
3. Branchez le téléphone en **USB** au PC. Sur le téléphone, **Autoriser le
   débogage USB** pour cet ordinateur (cochez « toujours »).

---

## 2. Construire et installer (Android Studio sur Windows)

1. Ouvrez **Android Studio** → **Open** → dossier `C:\Users\donpa\TennisBoss\android`.
   (Android Studio génère le wrapper Gradle et télécharge les dépendances — laissez
   le premier *Gradle sync* se terminer.)
2. En haut, dans le sélecteur d'appareil, choisissez votre **Pixel 9 Pro**.
3. Cliquez **Run ▶**. L'app s'installe et se lance sur le téléphone.

> Premier sync long la première fois (téléchargement des dépendances). Normal.

---

## 3. Relier le téléphone au serveur (le plus important)

### Option A — USB + adb reverse  ✅ recommandée
Dans un **terminal Windows** (PowerShell ou cmd), avec le téléphone branché :

```powershell
# adb fourni par Android Studio :
cd %LOCALAPPDATA%\Android\Sdk\platform-tools
adb devices                       # doit lister votre Pixel
adb reverse tcp:8000 tcp:8000     # le tel: localhost:8000 -> PC: localhost:8000
```

Démarrez le backend dans **WSL** :
```bash
cd /mnt/c/Users/donpa/TennisBoss
python3 run.py serve --host 0.0.0.0 --port 8000
```

Dans l'app, mettez le champ **URL du serveur** sur :
```
http://localhost:8000/
```
> Pourquoi ça marche : `adb reverse` envoie `localhost:8000` du téléphone vers
> `localhost:8000` du PC Windows, et WSL2 redirige automatiquement le `localhost`
> de Windows vers le serveur Flask dans WSL.
> ⚠️ `adb reverse` est à refaire après chaque rebranchement / redémarrage d'adb.

### Option B — même Wi-Fi, SANS USB  ✅ (pour ne plus dépendre du câble)
Le serveur étant dans WSL2, il faut rediriger le port depuis Windows. Un script
est fourni — lancez‑le dans un **PowerShell Administrateur** :
```powershell
cd C:\Users\donpa\TennisBoss\android\scripts
powershell -ExecutionPolicy Bypass -File .\wifi-forward.ps1
```
Le script recalcule l'IP de WSL, pose la redirection + la règle pare‑feu, et
affiche l'**URL à mettre dans l'app** (ex. `http://192.168.0.94:8000/`).
Téléphone et PC sur le **même Wi‑Fi**. Pour annuler : `wifi-forward-remove.ps1`.

> ⚠️ À relancer après un redémarrage du PC ou de WSL (l'IP de WSL change).

### Option C — Wi-Fi permanent (le plus propre, Windows 11 22H2+)
Activez le **réseau miroir** de WSL : éditez `%USERPROFILE%\.wslconfig` :
```ini
[wsl2]
networkingMode=mirrored
```
puis `wsl --shutdown` et rouvrez WSL. Le serveur WSL est alors **directement
joignable sur l'IP LAN du PC** (`http://192.168.0.94:8000/`), sans portproxy, et
ça survit aux redémarrages.

---

## 4. Vérifier que ça répond
Depuis le PC, l'API doit renvoyer du JSON :
```bash
curl http://localhost:8000/health
# {"status":"ok","service":"TennisBoss",...}
```
Dans l'app, allez sur **🎯 Prédire** → **Prédire** : vous devez voir les
probabilités. Sinon, voir le dépannage.

---

## 5. Dépannage
| Symptôme | Cause probable / solution |
|---|---|
| « Connexion impossible » dans l'app | mauvais URL : avec adb reverse → `http://localhost:8000/` ; le serveur tourne-t-il ? |
| `adb devices` ne voit rien | câble data (pas charge seule), débogage USB activé, autorisation acceptée |
| Marche puis se coupe | `adb reverse` perdu après débranchement → relancez la commande |
| Option B injoignable | l'IP de WSL change à chaque reboot → refaire le `portproxy` ; pare-feu Windows |
| `Cleartext HTTP not permitted` | déjà autorisé en dev (`network_security_config.xml`) ; en prod, passez en HTTPS |
| Token requis | si `TENNISBOSS_API_TOKEN` défini côté serveur, renseignez `ApiClient.apiToken` |

> Garde-fou : ne lancez pas l'API en clair sur un réseau public. Pour un usage
> hors de votre LAN, mettez l'API derrière HTTPS (gunicorn + reverse-proxy).
