# Audit Android — TennisBoss

Date : 2026-07-12
Périmètre : `android/app/src/main/java/com/tennisboss/app/` uniquement (aucun fichier backend touché).

## 1. Architecture actuelle

MVVM sans couche Repository explicite : chaque `ViewModel` appelle directement
`ApiClient.create()` (Retrofit) dans `viewModelScope.launch { }`. C'est le
pattern utilisé par **tous** les écrans existants (Upcoming, Value, Live,
Predict, Players, Performance, Edge, Scanner, Chat, Dashboard, MatchDetail).
Je le garde tel quel pour cette mission — introduire une couche Repository
serait un changement d'architecture transversal, hors périmètre demandé
("préserve l'architecture actuelle").

```
com.tennisboss.app/
├── MainActivity.kt              # NavigationBar (5 tabs) + AnimatedContent + routing MatchDetail
├── data/
│   ├── ApiClient.kt              # Retrofit singleton, apiOverride pour les tests
│   ├── TennisBossApi.kt          # interface Retrofit (29 endpoints @GET/@POST/@DELETE)
│   ├── ApiModels.kt               # ~90 data class (réponses JSON)
│   └── TokenManager.kt
├── ui/
│   ├── DashboardScreen.kt + DashboardViewModel.kt        # écran d'accueil
│   ├── ValueScreen.kt + ValueViewModel.kt                # value bets + historique
│   ├── MatchDetailScreen.kt + MatchDetailViewModel.kt    # fiche match premium
│   ├── UpcomingScreen.kt / LiveScreen.kt / PredictScreen.kt / PlayersScreen.kt
│   │   / PerformanceScreen.kt / EdgeScreen.kt / ScannerScreen.kt / ChatScreen.kt
│   ├── NavGroups.kt              # regroupe les 9 écrans en 5 tabs (sous-onglets TabRow)
│   ├── components/               # composants Compose réutilisables
│   │   ConfidenceBadge.kt, SurfaceBadge.kt, Skeleton.kt, H2HView.kt,
│   │   ExplainView.kt, WhyThisPickView.kt, BetBuilderView.kt, PlayerDetailSheet.kt
│   └── theme/
└── notifications/                 # FCM + WorkManager (non concerné par cette mission)
```

Navigation : `MainActivity.AppRoot()` gère 5 tabs (Accueil / Prédire / Matchs /
Value / Chat) + un état `selectedMatch` qui bascule vers `MatchDetailScreen`
en plein écran (pas une vraie route NavHost, mais un simple `if/else` sur un
state — cohérent avec le reste de l'app, pas de Navigation-Compose utilisé
nulle part ailleurs).

## 2. État actuel des 3 écrans de la mission (déjà présents, non commités)

Un travail antérieur (session précédente) avait déjà implémenté l'essentiel
de ce qui est demandé, mais n'était jamais commité et ne compilait pas. Je
l'ai retrouvé, corrigé (2 erreurs Kotlin + 1 bug de concurrence silencieux
dans `DashboardViewModel`/`MatchDetailViewModel` où un échec réseau sur un
`async{}` pouvait laisser l'écran bloqué en `Loading` au lieu d'afficher une
erreur — fixé avec `coroutineScope{}`), et ajouté 2 suites de tests
(`DashboardViewModelTest`, `MatchDetailViewModelTest`). `assembleDebug` et
`testDebugUnitTest` passent.

### DashboardScreen.kt — ✅ déjà conforme à l'étape 2
- Section "Matchs du jour" : `MatchSummaryCard` (joueurs, tournoi ; **heure et
  surface pas affichées sur la card**, seulement `tournament` — écart mineur
  vs la demande, voir plan §3).
- Section "Value Opportunities" : `ValueOpportunityCard` (best_side, best_ev,
  confidence badge — proba IA et cote marché pas affichées ici, juste sur
  ValueScreen).
- Section "Model Status" : `ModelStatusCard` (précision, nb prédictions, ROI
  value). **Calibration (Platt/k) et "dernière mise à jour" pas affichées.**
- Preview Compose présente (`DashboardPreview`).

### ValueScreen.kt — ✅ conforme à l'étape 3, composants pas encore extraits
- `ValueCard` (privée, dans ValueScreen.kt) affiche déjà : proba IA vs marché
  par joueur (`ProbCompareRow`), cote + EV par côté (`SideBox`), edge (`EvBadge`),
  mouvement des odds (`SignalChip` steam move), badge confiance
  (`ConfidenceBadge`, déjà un composant partagé).
- **`ValueCard.kt` et `EdgeIndicator.kt` n'existent pas comme fichiers séparés**
  — tout est privé dans `ValueScreen.kt` (`ValueCard`, `EvBadge`, `SideBox`,
  `ProbCompareRow`). C'est le seul écart réel vs la demande de l'étape 3.

### MatchDetailScreen.kt — ✅ déjà conforme à l'étape 4
`ComparisonHeader` (Elo global + rang), `SurfaceEloComparison` (Elo par
surface clay/hard/grass), `PremiumSignalsSection` (fatigue, clutch, qualité
adversaires), `FormSection` (forme récente), `H2HSection`. Service/retour
bruts (`serve`/`return1`/`return2` déjà dans `PlayerDetail`) **pas affichés**
sur cet écran (seulement utilisés ailleurs, ex. PlayersScreen).

## 3. Plan d'implémentation (pour validation)

Écarts réels à combler, classés par effort :

1. **Extraire `ValueCard.kt` et `EdgeIndicator.kt`** dans `ui/components/`
   (déplacer `ValueCard`/`EvBadge` hors de `ValueScreen.kt`, les rendre
   publics et réutilisables — `EdgeIndicator` reprend `EvBadge` sous un nom
   aligné avec la demande). Aucune donnée nouvelle, refactor pur + previews.
2. **DashboardScreen** : ajouter heure + surface sur `MatchSummaryCard`.
   `UpcomingMatch.time` existe directement ; la surface n'est pas un champ
   top-level de `UpcomingMatch` mais est disponible via
   `m.prediction?.surface` (déjà rempli quand une prédiction existe) — pas
   besoin d'inventer de donnée, juste l'afficher quand non-null (via
   `SurfaceBadge`, composant déjà existant).
3. **ModelStatusCard** : ajouter `calibration_k`/`platt_a`/`platt_b` (déjà
   dans `CalibrationResponse`, juste pas rendus) + un horodatage si l'API en
   expose un (sinon ne pas en afficher un inventé).
4. **MatchDetailScreen** : ajouter une ligne service/retour dans
   `PlayerBrief` ou une nouvelle section, à partir de `PlayerDetail.serve` /
   `.return1` / `.return2` (déjà chargés, juste pas affichés).

Aucun de ces points ne touche l'API, le backend, ou l'architecture — uniquement
de l'UI Compose + extraction de composants, sur des champs déjà présents
dans `ApiModels.kt`.

**En attente de validation avant de commencer l'implémentation.**
