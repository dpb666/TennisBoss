# TennisBoss — Release Audit (Phase 11)

_Audit exécuté 2026-07-14. Backend inchangé (hors scope de cette phase). Android uniquement._

## Résumé exécutif

**État global : NOT READY — un problème critique corrigé, un problème critique non résolu (décision requise).**

- ✅ **Corrigé pendant cet audit** : `assembleRelease`/`bundleRelease` étaient **cassés** (échec systématique). Root cause identifiée et corrigée, vérifiée.
- ❌ **Non corrigé, décision requise** : 44 usages de `java.time.*` dans `DateUtils.kt`/`UpcomingScreen.kt` **crashent sur tout appareil Android 7.0/7.1 (API 24-25)** — le `minSdk` déclaré (24) promet un support que le code ne tient pas. Ne bloque pas `assembleRelease` (donc pas corrigé automatiquement, conformément à la consigne "corrige uniquement si nécessaire pour la release"), mais bloque une release honnête.
- Tous les flux fonctionnels testés en live sur émulateur fonctionnent, zéro crash observé pendant le parcours complet.
- 54/54 tests unitaires passent, build debug + release compilent.

---

## Étape 1 — Audit technique

### 1.1 Build Android (debug)

```
compileDebugKotlin  : BUILD SUCCESSFUL
testDebugUnitTest   : 54/54 passed
assembleDebug        : BUILD SUCCESSFUL
```

Aucune régression. Confirmé après chaque modification de cette phase (fix Fragment, aucune autre modification de code).

### 1.2 Build release — **problème critique trouvé et corrigé**

**`./gradlew assembleRelease` échouait avant cet audit**, avec :

```
Task :app:lintVitalRelease FAILED
MainActivity.kt:80: Error: Upgrade Fragment version to at least 1.3.0.
[InvalidFragmentVersionForActivityResult from androidx.activity]
```

`lintVitalRelease` (contrairement à `lintDebug`) fait partie du pipeline `assembleRelease`/`bundleRelease` par défaut — ce n'est pas une vérification optionnelle, une release ne peut pas être produite tant que cette erreur existe.

**Root cause** : `androidx.fragment:fragment:1.1.0` est tiré **transitivement** par Google Play Services (`play-services-basement`, `play-services-base`), pas par une dépendance directe du projet. Cette version est trop ancienne pour les `ActivityResult` APIs (`registerForActivityResult`) utilisées dans `MainActivity.kt:80` pour la permission `POST_NOTIFICATIONS` — versions de `Fragment` < 1.3.0 n'appellent pas `super.onRequestPermissionsResult()` correctement et utilisent des request codes invalides.

**Fix appliqué** (`android/app/build.gradle.kts`) : ajout d'une dépendance directe `implementation("androidx.fragment:fragment-ktx:1.8.9")` — version stable actuelle vérifiée via `maven.google.com/androidx/fragment/fragment/maven-metadata.xml` (dernière release : `1.8.9`, `1.9.0` étant encore en alpha). Cela force Gradle à résoudre `1.8.9` partout au lieu du `1.1.0` transitif, sans toucher au reste de l'arbre de dépendances.

**Vérifié** :
```
compileDebugKotlin + testDebugUnitTest (54/54) : PASS
assembleRelease : BUILD SUCCESSFUL (échouait avant, confirmé par 2 tentatives)
```

Commit : `cf46a5e`.

### 1.3 Lint complet (`lintDebug`) — 45 erreurs, 102 avertissements, 1 hint

`lintDebug` (le rapport complet, plus large que le sous-ensemble `lintVital` qui bloque juste `assembleRelease`) révèle des problèmes que `assembleRelease` seul ne détecte pas :

#### 44 erreurs `NewApi` — **problème critique non corrigé, décision requise**

`DateUtils.kt` (27 sites) et `UpcomingScreen.kt` (15 sites) utilisent `java.time.*` (`LocalDate`, `ZonedDateTime`, `DateTimeFormatter`, `ZoneId`...) — ces APIs nécessitent **API 26** (Android 8.0). Le projet déclare `minSdk = 24` (Android 7.0) **sans core library desugaring activé**.

**Conséquence réelle** : sur un vrai appareil Android 7.0 ou 7.1 (API 24-25), tout écran qui appelle ce code (`DateUtils.kt` est utilisé pour l'affichage d'heure/date sur Dashboard, Upcoming, MatchDetail — c'est-à-dire les écrans les plus consultés de l'app) **plante immédiatement** avec `NoClassDefFoundError`/`NoSuchMethodError`. Ce n'est pas théorique : c'est un crash garanti au premier appel, pas un risque probabiliste.

**Pourquoi ce n'est pas corrigé automatiquement** : cette erreur n'est **pas** dans le sous-ensemble `lintVital` qui bloque `assembleRelease` — le build release réussit malgré elle. Or la consigne de cette phase est explicite : *"corrige uniquement s'il est nécessaire pour la release"* et *"aucun changement majeur d'architecture ne doit être introduit sans validation"*. Ceci est une décision de politique de support OS (pas juste un bug mécanique), donc je la présente pour arbitrage plutôt que de trancher seule :

| Option | Effort | Effet |
|---|---|---|
| **A. Activer le core library desugaring** (recommandé) | ~15 min, 1 dépendance (`coreLibraryDesugaring`) + 1 flag `compileOptions`, zéro changement de code métier | Le code `java.time.*` existant fonctionne tel quel sur API 24+, aucune régression sur API 26+ |
| B. Remonter `minSdk` à 26 | Trivial (1 ligne) | Exclut officiellement les appareils Android 7.0/7.1 du Play Store — perte de compatibilité déclarée, impact utilisateurs réels à évaluer |
| C. Ne rien faire | — | L'app plante pour tout utilisateur sur API 24-25 qui ouvre Dashboard/Upcoming/MatchDetail — ce n'est pas une release saine tant que `minSdk=24` reste affiché |

Aucune de ces 3 options n'a été appliquée — laissée à validation explicite, conformément aux règles de cette phase.

#### 1 erreur `InvalidFragmentVersionForActivityResult`

Déjà couverte en 1.2 (bloquait `assembleRelease`, corrigée).

#### 102 avertissements — non bloquants, non corrigés (hors scope "nécessaire pour la release")

- **`DefaultLocale` (56 sites)** : `String.format("%.1f%%", ...)` sans `Locale` explicite dans des composants d'affichage de pourcentages/cotes. Risque réel mais faible pour ce cas précis (formats numériques simples, pas de `toUpperCase()`/`toLowerCase()` sur texte utilisateur) — non corrigé, c'est un nettoyage cosmétique, pas un bloqueur.
- **`GradleDependency`/`NewerVersionAvailable` (11 sites)** : versions plus récentes disponibles pour `core-ktx`, `activity-compose`, `lifecycle-*`, `work-runtime-ktx`, `firebase-bom`, `retrofit`, `okhttp`, `kotlinx-coroutines`, et `security-crypto` (voir 1.4 — audit dépendances). Aucune n'est une CVE connue, juste de la staleness — non touché, conformément à *"ne fais pas de gros upgrades sans justification"*.
- **`UseKtx` (3 sites)** : `SharedPreferences.edit()` → extension KTX. Style, pas de risque.
- **`Typos` (10 faux positifs)** : dans `font_certs.xml` — ce sont des hash de certificats base64, pas du texte, faux positifs du correcteur orthographique de lint. Ignorable.
- **`UnusedResources` (2 couleurs)**, **`MonochromeLauncherIcon`**, **`ModifierParameter`**, **`OldTargetApi`**, **`RedundantLabel`**, **1 hint `AutoboxingStateCreation`** : cosmétique, zéro risque, non corrigés.

### 1.4 ProGuard / R8

`isMinifyEnabled = false` en configuration `release` (`android/app/build.gradle.kts:42`) — **le shrinking/l'obfuscation R8 ne s'applique pas**, malgré `proguardFiles` configuré (`proguard-android-optimize.txt` + `proguard-rules.pro`, qui existent mais ne sont actuellement pas exercés). L'APK release (14 Mo, non signé) est donc plus petit que le debug (24 Mo) uniquement grâce à la compression de ressources standard, pas au shrinking de code.

Ceci n'est **pas un bug** — c'est une configuration existante, potentiellement déjà un choix délibéré (le shrinking peut casser des choses via réflexion/sérialisation Gson sans règles ProGuard soigneusement testées). **Non modifié** : activer `isMinifyEnabled` sans valider que les règles ProGuard existantes sont réellement suffisantes serait exactement le genre de changement à ne pas faire sans validation explicite (risque de casser Gson/Retrofit en silence). Flagué pour décision future, pas pour cette phase.

### 1.5 Audit sécurité — clean

- Recherche de clés API/tokens hardcodés (Kotlin + Python) : **aucun trouvé**. Le token API est source depuis `local.properties`/variable d'environnement/propriété Gradle, jamais en dur (`android/app/build.gradle.kts:15-17`).
- `.env` : jamais commité dans l'historique git (`git log --all -- .env` vide).
- `local.properties` (contient `TENNISBOSS_API_TOKEN` en local) : correctement ignoré par `android/.gitignore`, non tracké.
- Aucun keystore (`.jks`/`.keystore`) commité — `google-services.json` est tracké, ce qui est normal (config Firebase publique, pas un secret).
- Le build release force explicitement `TENNISBOSS_API_TOKEN=""` (`build.gradle.kts:41`), même si la variable traîne dans l'environnement local au moment du build — protection déjà en place, vérifiée.
- **`security-crypto` (migration alpha → stable) : non touché**, conformément à la consigne explicite de cette phase.

### 1.6 Audit dépendances

Aucune dépendance avec une CVE connue identifiée. Versions en retard notées (voir 1.3), aucune mise à jour majeure appliquée :
- `retrofit`/`converter-gson` 2.11.0 → 3.0.0 disponible (**majeur**, breaking changes possibles — non touché)
- `okhttp:logging-interceptor` 4.12.0 → 5.4.0 disponible (**majeur** — non touché)
- `security-crypto` 1.1.0-alpha06 → **1.1.0 stable maintenant disponible** (info pertinente pour `MASTER_TODO.md` #8, non appliqué)
- `core-ktx`, `activity-compose`, `lifecycle-*`, `work-runtime-ktx`, `firebase-bom`, `kotlinx-coroutines` : versions mineures/patch en retard, non critiques

---

## Étape 2 — Tests fonctionnels (parcours live sur émulateur, logcat surveillé en continu)

Tous les flux suivants ont été exercés manuellement sur l'émulateur AVD "TennisBoss" avec l'APK debug la plus récente (incluant le fix Fragment). **Zéro `FATAL EXCEPTION`, zéro crash observé sur l'ensemble du parcours.**

| Flux | Résultat |
|---|---|
| **Dashboard** — chargement matchs, prédictions | ✅ Données réelles chargées, carte "Meilleures opportunités" affichée avec cotes/EV |
| **Dashboard → MatchDetail** (navigation) | ✅ Transition fluide, ELO par surface / intelligence sportive / H2H tous rendus |
| **Retour MatchDetail → Dashboard** (bouton back) | ✅ Fonctionne correctement |
| **Matchs / À venir** — récupération données, filtres | ✅ Skeleton loading → données réelles, filtres Fiable/Cotes fonctionnels |
| **Matchs / Live** — état temps réel | ✅ 13 matchs en cours affichés avec ROI Inplay, meilleur pick live, picks en attente (W/L/suppr fonctionnels visuellement) |
| **Value / Value** — sous-onglet | ✅ Value bets IA chargés avec EV/cotes réels |
| **Value / Scanner** — lancement/résultats | ✅ Cycle actif, dernier pick détecté, couverture cycle, filtres du cycle tous affichés |
| **Value / Stats** (Performance) — affichage données | ✅ Précision/ROI/calibration/segments tous rendus avec vraies données |
| **Value / Edge** — CLV/absence crash | ✅ CLV par palier de confiance, Scanner post-filtre, aucune erreur |
| **Chat** — input, envoi | ✅ Message envoyé, réponse IA reçue et groundée (badge "Basé sur nos données") |
| **Chat** — upload | Non testé de bout en bout (nécessite le file picker Android, hors portée du scripting `adb shell input` de cette session) — le bouton et son `contentDescription`/`testTag` sont vérifiés au niveau code (session précédente) |
| **Prédire** — analyse IA | ✅ Formulaire pré-rempli, verdict + explicabilité (facteur décisif, impact par variable) tous rendus |
| **Joueurs** (comparaison) — état vide | ✅ Rendu correct, prêt à recevoir une recherche |

**Note méthodologique** : deux faux positifs rencontrés pendant ce parcours (l'app est retournée au launcher après une pression BACK sur un écran racine de la bottom nav — comportement Android normal, pas un bug ; et une bulle d'outils de sélection de texte de l'émulateur qui interceptait des taps — artefact d'outillage `adb shell input text`, pas un bug de l'app). Les deux ont été confirmés via logcat (aucune `FATAL EXCEPTION` aux horodatages concernés) avant d'être écartés.

---

## Étape 3 — Performance

_Mesures indicatives sur émulateur x86_64 virtualisé (Windows/WSL) — probablement plus lent qu'un vrai appareil, à ne pas prendre comme valeur absolue de production._

### Temps de démarrage à froid

`adb shell am start -W` répété 4 fois après `force-stop` :

| Run | TotalTime |
|---|---|
| 1 (juste après réinstallation — inclut vérification APK/compilation ART) | 17163 ms |
| 2 | 7318 ms |
| 3 | 7983 ms |
| 4 | 8327 ms |

**~7,3 à 8,3 secondes de façon stable** (hors premier lancement post-install). C'est lent pour une app native — piste identifiée mais **non modifiée** : `TokenManager.initialize()` (création `MasterKey`/`EncryptedSharedPreferences`, backée par Android Keystore) est appelée **de façon synchrone avant `setContent{}`** dans `MainActivity.onCreate()` — un choix déjà délibéré et documenté en commentaire dans le code (nécessaire pour que le token soit prêt avant le tout premier appel API de `DashboardViewModel.init{}`, sinon 401 constaté). L'initialisation Keystore/Tink est documentée comme potentiellement lente, en particulier sur émulateur (backend logiciel du Keystore, plus lent qu'un TEE matériel réel). Non touché — correspondrait à une "optimisation prématurée" et toucherait au stockage des tokens (`security-crypto`, explicitement hors scope de cette phase).

### Taille des builds

| Variante | Taille | Note |
|---|---|---|
| Debug APK | 24 Mo | Inclut symboles debug, non optimisé |
| Release APK (non signé) | 14 Mo | Pas de shrinking R8 (`isMinifyEnabled = false`, voir 1.4) — la taille reflète la compression de ressources standard, pas un vrai build de production optimisé |

### Mémoire

`dumpsys meminfo` après le parcours fonctionnel complet (~10 écrans visités) : **~120 Mo PSS total**. Dans la norme pour une app Compose + Firebase + Retrofit + WorkManager à ce stade de navigation — rien d'alarmant. **Ceci n'est pas une session de détection de fuite mémoire rigoureuse** (aurait nécessité Android Studio Profiler + diff de heap dumps sur des cycles de navigation répétés, hors portée de cet outillage `adb`) — juste un instantané de sanité.

### UI

Aucun ralentissement visuel observé pendant le parcours (transitions, scroll, changements d'onglets tous fluides à l'œil). Pas de profiling frame-by-frame effectué (nécessiterait `adb shell dumpsys gfxinfo` sur des sessions d'interaction prolongées — non fait, hors scope "pas d'optimisation prématurée").

**Aucune optimisation de performance n'a été appliquée**, conformément à la consigne.

---

## Étape 4 — Documentation mise à jour

- `PROJECT_STATUS.md` — section build/release mise à jour
- `MASTER_TODO.md` — nouvel item critique ajouté (le choix desugaring vs minSdk)
- `TEST_REPORT.md` — inchangé (aucun nouveau test ajouté cette phase, 54/54 toujours valide)
- Ce fichier (`RELEASE_AUDIT.md`) — nouveau

---

## Conclusion

### État global : **READY** (mis à jour 2026-07-14, suite à la fermeture de MASTER_TODO #0)

Les deux bloqueurs identifiés dans cette phase sont maintenant résolus :

1. `assembleRelease`/`bundleRelease` cassés → **corrigé** (commit `cf46a5e`, pin `fragment-ktx:1.8.9`).
2. 44 erreurs `NewApi` (`java.time.*` sur minSdk 24-25 sans desugaring, crash garanti) → **corrigé** (`MASTER_TODO.md` #0) via **core library desugaring** (`coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")`), `minSdk` conservé à 24 comme demandé. Vérifié : `lintDebug` 0 erreurs (était 45), `compileDebugKotlin`/`assembleDebug`/`assembleRelease`/`bundleRelease`/`testDebugUnitTest` (54/54) tous verts, aucune régression visuelle ou fonctionnelle constatée sur device (Dashboard, MatchDetail, Matchs — y compris le `DayPicker` qui utilise exactement les APIs `java.time` concernées —, Value, Chat).

### Problèmes restants (aucun n'est un bloqueur de release)

1. **[Moyen — décision différée]** `security-crypto` alpha → stable disponible (1.1.0) — explicitement hors scope, non touché.
2. **[Bas — décision différée]** `isMinifyEnabled = false` en release — le shrinking R8 n'est pas exercé malgré des règles ProGuard configurées. Activer nécessiterait de valider ces règles (risque Gson/Retrofit), pas fait.
3. **[Bas — informationnel]** Release APK non signé (attendu à ce stade — un vrai déploiement Play Store nécessitera une configuration de signature, absente du repo, ce qui est correct : aucun keystore ne doit être commité).
4. **[Bas — informationnel]** 102 avertissements lint non bloquants (`DefaultLocale`, dépendances datées, style), inchangés par le fix de desugaring — voir 1.3 pour le détail complet.
5. **[Bas — informationnel]** Démarrage à froid ~7-8s sur émulateur — piste identifiée (`TokenManager.initialize()` synchrone), non modifiée (choix architectural déjà documenté, touche au stockage des tokens).

### Hash du dernier commit

Voir le commit de clôture de MASTER_TODO #0 (`Fix: enable Core Library Desugaring (MASTER_TODO #0)`), postérieur à `cf46a5e`.
