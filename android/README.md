# 🎾 TennisBoss — App Android (Kotlin + Jetpack Compose)

Client Android minimal qui consomme l'API REST de TennisBoss (`run.py serve`).
Écran de prédiction du 1er set : saisir deux joueurs → barres de probabilité.

## Pile technique
- **Kotlin** + **Jetpack Compose** (Material 3)
- **Retrofit** + **Gson** + **Coroutines** (réseau)
- **ViewModel** (état d'écran)
- minSdk 24 · targetSdk/compileSdk 35

## Prérequis
1. **Android Studio** (Ladybug 2024.2+ recommandé).
2. Le backend qui tourne :
   ```bash
   cd ..            # dossier TennisBoss
   python3 run.py train --years 2022 2023 2024 --tours atp wta
   python3 run.py serve --host 0.0.0.0 --port 8000
   ```

## Ouvrir & lancer
1. Android Studio → **Open** → choisir le dossier `android/`.
   (Android Studio génère le wrapper Gradle et télécharge les dépendances.)
2. Choisir un émulateur ou un téléphone, puis **Run ▶**.

### Quelle URL de serveur ?
Réglable directement dans l'app (champ « URL du serveur ») :
| Contexte | URL |
|---|---|
| Émulateur | `http://10.0.2.2:8000/` (valeur par défaut) |
| Téléphone réel (même Wi-Fi) | `http://IP_DU_PC:8000/` (ex. `http://192.168.1.20:8000/`) |

> Sur téléphone réel, trouvez l'IP du PC : `ip addr` (WSL/Linux) ou `ipconfig`
> (Windows). Le PC et le téléphone doivent être sur le **même réseau**.

### Token (optionnel)
Si le serveur a défini `TENNISBOSS_API_TOKEN`, renseignez `ApiClient.apiToken`
(dans `data/ApiClient.kt`) ; l'en-tête `X-API-Token` sera ajouté automatiquement.

## Structure
```
android/
├── settings.gradle.kts · build.gradle.kts · gradle.properties
├── gradle/wrapper/gradle-wrapper.properties
└── app/
    ├── build.gradle.kts
    └── src/main/
        ├── AndroidManifest.xml          (INTERNET + cleartext dev)
        ├── res/values/strings.xml
        ├── res/xml/network_security_config.xml
        └── java/com/tennisboss/app/
            ├── MainActivity.kt          (UI Compose : écran de prédiction)
            ├── data/ApiModels.kt        (modèles JSON)
            ├── data/TennisBossApi.kt    (endpoints Retrofit)
            ├── data/ApiClient.kt        (client + URL + token)
            └── ui/PredictViewModel.kt   (état + appel réseau)
```

## Étendre l'app (déjà câblé côté API)
L'interface `TennisBossApi` couvre aussi `players()` (autocomplete) et
`upcoming()` (matchs à venir + cotes). Ajoutez un écran qui les consomme :
- recherche joueurs → `ApiClient.create().players(q = "alc")`
- matchs du jour → `ApiClient.create().upcoming(days = 1, odds = true)`

## Notes
- Le HTTP en clair est activé pour le **dev** uniquement (voir
  `network_security_config.xml`). En production : HTTPS + retirer le cleartext.
- Précision modèle ~0,61 : aide à la décision, **aucun pari placé**.
