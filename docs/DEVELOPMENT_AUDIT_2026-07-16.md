# TennisBoss — Audit de développement

**Date :** 16 juillet 2026  
**Périmètre :** audit read-only du dépôt `C:\Users\donpa\TennisBoss`  
**Référence :** `docs/AI_ASSISTANT_ARCHITECTURE.md` (plan du 16/07), `PROJECT_STATUS.md` (14/07), production `api.tennisboss.online`  
**HEAD git au moment de l'audit :** `d009461c` — *AI Assistant : mode=analyst pour /api/chat*  
**Note :** l'arbre de travail contient des modifications non commitées (voir §1.3).

---

## Résumé exécutif

- **Maturité globale : ~92 %** — application production-ready pour usage personnel / beta ; pas encore prête pour une validation statistique d'edge à grande échelle.
- **Velocity élevée (14–16 juil.) :** observabilité picks (17 colonnes `clv_log`), Phase 12 ops, rejet documenté des features surface/clutch, **Phase 1 assistant IA** (outils read-only + `mode=analyst`), **Bet Builder** (marchés + combo).
- **Tests : ~585 pytest** (cache local) et **~64 tests unitaires Android** — hausse nette vs ~357/54 au 14/07 ; couverture ViewModels quasi complète + nouveaux domaines (AI tools, bet-builder, logging).
- **Frontière figée respectée** pour `predictor.py` / `calibrate.py` / seuils `/api/value` dans les livraisons du 16/07 (Bet Builder = combinatoire sur probas existantes ; AI tools = lecture seule).
- **Blocage produit principal inchangé :** `bet_history` ~97 paris réglés (< seuil n≥200) — calibration/ROI en mode « indicatif » uniquement.
- **Prochain ROI :** activer `TENNISBOSS_AI_TOOLS=1` en prod, UI Android `tools_called`/`mode=analyst`, Phase 2 mémoire projet, accumuler `bet_history`, brancher `compare-engines` dans `run.py`.

---

## Tableau comparatif avant / après

| Indicateur | 14 juil. 2026 (`PROJECT_STATUS.md`) | 16 juil. 2026 (cet audit) | Δ |
|---|---|---|---|
| **Complétion globale** | ~90 %, release-ready | ~92 % | +2 pts |
| **Modules `bot/`** | ~78 (flat) | **69** `.py` (+ **5** dans `ai/`) | −9 orphelins, +package `ai/` |
| **`bot/api.py`** | ~4 000 lignes, ~45 routes | **~3 705 lignes**, **52** décorateurs route | +7 endpoints |
| **Tests backend** | 357–369 | **~585** (`.pytest_cache`) | **+~220** |
| **Tests Android** | 54 | **~64** (`@Test`) | **+10** |
| **Écrans Compose** | 13 + NavGroups (4 onglets Value) | 13 + **Combo** (5 onglets Value) | +1 sous-écran |
| **Assistant IA** | Chat grounding seul | **Phase 1 Slice 1** + **`mode=analyst`** | Livré (flag off) |
| **`bet_history` settled** | n≈97 | n≈97 (sparse) | ≈0 |
| **`docs/`** | 11 fichiers | **12** (+ `AI_ASSISTANT_ARCHITECTURE.md`) | +1 |
| **Predictor figé** | Oui (directive user) | **Oui** — pas de commit direct sur formule core | ✓ |
| **`compare-engines` CLI** | Documenté, absent de `run.py` | **Toujours absent** | Gap |

---

## 1. Git & vélocité des changements

### 1.1 Derniers commits (30, extraits `.git/logs/HEAD`)

| Hash (court) | Thème |
|---|---|
| `d009461` | AI Assistant : `mode=analyst` pour `/api/chat` |
| `5f1fd85` | Docs : statut Phase 1 + Bet Builder dans `MASTER_TODO.md` |
| `44beaa5` | **Bet Builder** : marchés, EV, combo, badge meilleur pari |
| `0de72a8` | **AI Assistant Phase 1 Slice 1** : outils chat read-only |
| `9fbae3c` | **Logging reproductibilité** : 17 colonnes `clv_log` |
| `a4c8ce3` | Evidence-Driven Optimization (NO-GO seuil EV) |
| `55827d7` | Market Efficiency Audit |
| `a6d98e1` | Rejet blend clutch (walk-forward) |
| `a561d70` | Backtest signal clutch |
| `4f4a788` | Fix scheduler Phase 12 |
| `cd86fef` | Persist monitor check (scheduler) |
| `95c4bb7`–`f586e8e` | Surface benchmark + backfill `bet_history` surface |
| `da0be76`–`680e5bd` | Perf `engineer/today`, TIS calibration dans pipeline API |
| `fa14a79` | CLV hebdomadaire + digest |
| `54c241d` | Suppression modules orphelins (`ai_resolver`, telegram_*) |
| `8b1367f`–`1d9e154` | Rankings ATP/WTA, pipeline WTA/MCP |

**Thèmes dominants :** fiabilité prod, mesurabilité, rejets evidence-driven, assistant analytique, UX parieur (combo), sans toucher au cœur prédictif.

### 1.2 Statistiques de diff

Les commandes `git diff --stat HEAD~30..HEAD` n'ont pas pu être exécutées dans l'environnement d'audit (shell sans sortie). Les thèmes ci-dessus couvrent la fenêtre récente ; estimation qualitative : **~15–25 % du backend touché** sur 3 jours (ops + API + docs + `ai/`), **`predictor.py` / `calibrate.py` hors périmètre des livraisons du 16/07**.

### 1.3 Arbre de travail (non commité au moment de l'audit)

Fichiers modifiés / non suivis pertinents :

- `bot/api.py`, `bot/chat.py`, `bot/openapi_spec.py`, `QUICK_START_CHAT.md`
- `ai/chat/*` (package entier)
- `tests/test_ai_tools.py`, `tests/test_api_endpoints2.py`, `tests/test_chat.py`
- `docs/AI_ASSISTANT_ARCHITECTURE.md`
- `android/build.gradle.kts`, `android/gradle.properties`

**Recommandation :** commit groupé « AI Phase 1 + analyst mode + tests » si pas déjà poussé au-delà de `d009461c`.

---

## 2. Backend

### 2.1 Structure `bot/`

| Métrique | Valeur |
|---|---|
| Fichiers Python `bot/` | **69** (incl. `ml_prep/`) |
| Package `ai/` | **5 fichiers** — `orchestrator.py`, `tools/registry.py`, shims `__init__` |
| Suppressions récentes | `ai_resolver.py`, `alerts.py`, `telegram_handler.py`, `telegram_poll.py` |

Modules notables ajoutés / actifs depuis le 14/07 :

- `surface_features.py`, `surface_experiment.py` (offline, rejet documenté)
- `market_efficiency_audit.py`, `decision_policy_backtest.py`
- `ranking_feeder.py`, enrichissement logging via `versions.py`
- `openapi_spec.py` (spec OpenAPI maintenue à la main)

### 2.2 `bot/api.py` — routes

**52** routes Flask (`@app.get` / `@app.route`), vs ~45 au plan architecture.

| Catégorie | Endpoints clés | Nouveauté 16/07 |
|---|---|---|
| **Core** | `/health`, `/api/status`, `/api/predict`, `/api/players`, `/api/player`, `/api/h2h` | — |
| **Matchs** | `/api/upcoming`, `/api/live`, `/api/inplay/*`, `/api/recommendations` | — |
| **Value / picks** | `/api/value`, `/api/value/open`, `/api/value/history` | — |
| **Bet Builder** | `POST /api/bet-builder/combo` | **Nouveau** |
| **Watchlist** | `POST /api/match/follow`, `unfollow`, `GET /api/matches/followed` | 15/07 |
| **Performance** | `/api/bet-history/*`, `/api/clv`, `/api/clv/weekly`, `/api/calibration` | CLV weekly 15/07 |
| **Observabilité** | `/api/logging/health`, `/api/monitor/status`, `/api/scanner/status` | logging health 15/07 |
| **Intelligence** | `/api/insight`, `/api/match/intelligence`, `/api/intelligence/*`, `/api/engineer/today` | perf TIS 15/07 |
| **Chat** | `POST /api/chat`, `POST /api/upload` | **`mode`**, **`tools_called`** |
| **Admin** | settlement, learn, ingest | Bloqués assistant |

**Taille :** ~3 705 lignes (monolithique — dette structurelle Phase 4).

### 2.3 Assistant IA — implémentation

| Composant | État |
|---|---|
| `ai/chat/tools/registry.py` | **6 outils read-only** : `read_doc`, `query_bet_history`, `get_calibration_summary`, `explain_pick`, `list_api_endpoints`, `get_logging_health` |
| `ai/chat/orchestrator.py` | Classification regex (pas de function-calling LLM) |
| `config.AI_TOOLS_ENABLED` | `TENNISBOSS_AI_TOOLS=1`, **défaut OFF** |
| `api_chat()` | Tools **uniquement** si `build_match_context()` vide ; réponse optionnelle `tools_called` / `sources` |
| `mode=analyst` | `ANALYST_MAX_TOKENS=512`, `ANALYST_TEMPERATURE=0.3` dans `bot/chat.py` |
| Tests | `tests/test_ai_tools.py` — **22 tests** + garde-fou imports figés |

**Non implémenté (plan) :** `query_clv_log`, `get_project_status`, `run_report_read`, `search_knowledge`, embeddings.

### 2.4 Frontière figée — vérification

| Fichier / zone | Statut 16/07 |
|---|---|
| `bot/predictor.py` | **Pas de modification** dans les commits Bet Builder / AI Phase 1 ; formule core intacte |
| `bot/calibrate.py` | **Pas de modification** annoncée ; `PREDICTOR_VERSION` / `CALIBRATION_VERSION` = `"1.0"` |
| `/api/value` seuils | Bet Builder explicitement **hors** pipeline de décision value |
| `_bet_builder()` | Combinatoire (match, set2, total_sets, handicap) sur probas déjà calculées |
| `680e5bd` (TIS) | Calibration appliquée dans couche API/TIS — **à surveiller** vs directive « figé » ; pas un changement de `calibrate.py` |

### 2.5 Scheduler (`bot/scheduler.py`)

**11 jobs** confirmés :

`job_learn`, `job_ingest`, `job_mtd_ingest`, `job_mcp_backfill`, `job_monitor`, `job_backup`, `job_daily_digest`, `job_rankings`, `job_bet_history_backfill`, `job_espn_warm`, `job_calibration_report`.

### 2.6 CLI (`run.py`)

Commandes enregistrées : `start`, `train`, `predict`, `players`, `backtest`, `upcoming`, `value`, `serve`, `db`, `status`, `reset`, `backup`, `signals`, **`clv-weekly`**, `validate-tis`, `calibration-report`, `data-quality`, `ingest-rankings`, `backfill-bet-history`, `surface-benchmark`, `surface-data-audit`, `dedupe-players`.

**Gap persistant :** `compare-engines` documenté dans `MASTER_TODO.md` / `LEAD_ENGINEER_AUDIT.md` — code dans `bot/compare_engines.py`, **absent de `run.py`**.

---

## 3. Android

### 3.1 Écrans & navigation

- **5 destinations** bottom nav (`MainActivity.kt`) via `NavGroups.kt`
- **14 composants écran** (13 historiques + **`ComboBuilderScreen`**)
- **ValueGroupScreen** : 5 sous-onglets — Value, Scanner, Stats, Edge, **Combo**

ViewModels : 14 (+ `ComboBuilderViewModel`).

### 3.2 Client API (`TennisBossApi.kt`)

Endpoints consommés : predict, upcoming, value, live, inplay, chat, upload, CLV, intelligence, etc.

**Ajout récent :** `POST api/bet-builder/combo`.

**Non consommé côté Android :**

- `mode=analyst`, affichage `tools_called` / `sources`
- `/api/match/follow` (watchlist match — API prête, UI `MatchDetailScreen` non câblée, cf. `MASTER_TODO.md` §5b)
- `/api/clv/weekly`, `/api/logging/health`, `/api/bet-history/*` (partiellement via Performance)

### 3.3 Build

| Élément | Valeur |
|---|---|
| AGP (root) | **9.3.0** |
| Kotlin Compose plugin | **2.2.10** |
| Compose BOM | **2026.06.01** |
| `minSdk` | 24 (desugaring `java.time` activé) |
| `compileSdk` / `targetSdk` | 35 |
| R8 minify release | **désactivé** |
| `security-crypto` | **1.1.0-alpha06** (dette connue) |
| Token release | Vide (Cloudflare Worker côté prod) |

`android/gradle.properties` : parallel sync Gradle 9.4+, configuration-cache.

### 3.4 Tests Android

**~64** méthodes `@Test` dans `android/app/src/test/` :

- 13 ViewModels couverts (+ **`ComboBuilderViewModelTest`** — 7 tests)
- Utilitaires : `SortUpcomingTest`, `SortForDashboardTest`
- Pattern `FakeApi.kt` + injectable `io` dispatcher

**Gaps :** pas de tests instrumentés Compose UI ; `uploadFile()` Chat non testé (besoin Robolectric).

---

## 4. AI / Chat

### 4.1 Capacités actuelles

| Capacité | Maturité |
|---|---|
| `POST /api/chat` (Groq → Gemini → Ollama) | Production |
| Grounding joueurs (`build_match_context`) | Bon |
| Préfixes `@stats_agent` etc. | Prompt-only |
| Upload PDF/CSV/TXT | Production |
| **Outils analytiques read-only** | **Code livré, flag OFF par défaut** |
| **`mode=analyst`** | **Backend livré ; Android envoie encore `mode=chat` implicite** |
| Persistance conversation Android | Absente (historique session only) |
| Telegram poll intégré (`api.py`) | Production (admin) |

### 4.2 Documentation chat

| Fichier | État |
|---|---|
| `QUICK_START_CHAT.md` | **Mis à jour** — section AI Analyst Tools |
| `AI_CHAT_AUDIT.md` | **Obsolète** — référence `/tg-chat`, port 8001, couche `app/` supprimée |
| `RELEASE_NOTES_CHAT.md` | Historique — ne pas réécrire |

---

## 5. Tests

### 5.1 Backend pytest

| Métrique | Valeur |
|---|---|
| Fichiers `tests/test_*.py` | **47** |
| Tests collectés (cache) | **~585** |
| Dernière baseline documentée | 533 (Bet Builder, `MASTER_TODO.md`) |

Suites notables :

| Suite | ~Tests | Focus |
|---|---|---|
| `test_api_endpoints2.py` | 54 | API incl. combo, chat analyst |
| `test_predict_math.py` | 29 | Bet builder math |
| `test_chat.py` | 27 | LLM, analyst mode |
| `test_ai_tools.py` | 22 | Outils + frontière figée |
| `test_logging_schema.py` | 14 | Repro picks |
| `test_bet_history.py` | 12 | Performance API |

**Exécution :** `python -m pytest` n'a pas produit de sortie dans l'environnement d'audit ; le cache `.pytest_cache` indique une collecte récente à 585 tests.

### 5.2 Couverture — gaps

- Pas de tests E2E prod (health monitorés manuellement)
- `compare_engines.py` sans tests CLI intégrés
- Feeders externes (Odds API live) majoritairement mockés
- UI Compose : 0 tests instrumentés malgré `testTag` ajoutés

---

## 6. Documentation

### 6.1 Inventaire `docs/`

| Fichier | Rôle | Nouveau / maj. |
|---|---|---|
| `AI_ASSISTANT_ARCHITECTURE.md` | Plan 5 phases + journal impl. | **Nouveau 16/07** |
| `LOGGING_SCHEMA.md` | 17 colonnes repro `clv_log` | **15/07** |
| `EVIDENCE_DRIVEN_OPTIMIZATION.md` | NO-GO seuils EV | 15–16/07 |
| `MARKET_EFFICIENCY_AUDIT.md` | Analyse blend marché | 15–16/07 |
| `CLUTCH_BLEND_WALKFORWARD_VALIDATION.md` | Rejet clutch | 15/07 |
| `PRODUCTION_RELIABILITY_REPORT.md` | Santé prod, n=97 | 15/07 |
| `LEAD_ENGINEER_AUDIT.md` | Phase 12 | 15/07 |
| `STABILIZATION_REPORT.md`, `CTO_SESSION_REPORT.md`, `DATA_PIPELINE_AUDIT.md` | Ops | Existants |
| `surface_features.md` | Rejet surface features | 15/07 |
| `AUDIT.md` | Audit 12/07 (298 tests) | **Partiellement stale** |

Racine : `PROJECT_STATUS.md` (14/07 — **à rafraîchir**), `MASTER_TODO.md` (**à jour** sections Phase 1 + Bet Builder), `AGENTS.md`.

### 6.2 `MASTER_TODO.md`

- Items critiques #0–#3 : **Done**
- Phase 12 validation : **Done**
- Logging schema mission : **Done** (498→520 tests)
- AI Phase 1 Slice 1 : **Done**
- Bet Builder : **Done** (533 backend / 61 Android documentés ; cache local ~585/64)
- Phase 2–5 assistant : **Planned**

---

## 7. Données & production

### 7.1 `state/` & logging

| Artefact | Rôle |
|---|---|
| `state/tennisboss.db` | SQLite prod (hors git) — players, matches, clv_log, bet_history |
| `state/memory.json` | Poids entraînement (≠ mémoire projet) |
| `logs/tennisboss.log` | App log (`bot/log.py`) |
| `GET /api/logging/health` | Complétude champs repro |

**bet_history :** ~**97** paris réglés (90j) — seuil n≥200 non atteint ; warnings calibration « sparse » attendus.

### 7.2 Production (`api.tennisboss.online`)

- Services systemd : `tennisboss-bot`, `tennisboss-scheduler`
- Auth : `X-API-Token` si `TENNISBOSS_API_TOKEN` défini
- Dernière fiabilité documentée : OK (`docs/PRODUCTION_RELIABILITY_REPORT.md`, 15/07)
- **À redeployer** si commits post-15/07 non restartés : AI tools, analyst mode, Bet Builder

---

## 8. Gap analysis vs `AI_ASSISTANT_ARCHITECTURE.md`

| Phase | Objectif | Statut | Détail |
|---|---|---|---|
| **0** | Audit + plan | ✅ **Done** | Ce document + plan 16/07 |
| **1** Slice 1 | 5–6 outils read-only + flag | ✅ **Done** | 6 outils, orchestrateur, tests, OpenAPI |
| **1** Rank #2 | `mode=analyst` | ✅ **Done** (backend) | Android pas encore |
| **1** Rank #4–5 | `compare-engines`, sources UI | ⏳ **Partiel** | CLI toujours absent ; pas de chip Sources Android |
| **2** | `project_knowledge.db`, FTS | ❌ **Missing** | — |
| **3** | Learning loop suggestions | ❌ **Missing** | `mistake_learner` existe mais opaque au chat |
| **4** | Réorg dossiers (`prediction/`, `data/`) | ⏳ **Début** | `ai/` créé ; `bot/` toujours flat |
| **5** | Design system chat | ❌ **Missing** | Spec seulement |

---

## 9. Dette technique & risques

### 9.1 Code / architecture

| Risque | Sévérité | Note |
|---|---|---|
| `api.py` monolithique (~3.7k lignes) | Moyenne | Maintenabilité ; Phase 4 différée |
| `compare-engines` non branché | Faible | Workflow doc cassé |
| `AI_CHAT_AUDIT.md` stale | Faible | Induit en erreur nouveaux devs |
| `PROJECT_STATUS.md` (14/07) | Moyenne | Sous-estime tests et features 16/07 |
| `job_learn` / `auto_learner` actif | Info | Prédate freeze ; séparé de l'assistant |
| Commits non pushés / WT dirty | Moyenne | Risque dérive prod vs repo |

### 9.2 Android

| Risque | Sévérité |
|---|---|
| `security-crypto` alpha | Moyenne |
| R8 off en release | Faible (APK plus gros) |
| Watchlist match API sans UI | Faible |
| Pas de persistance chat | Faible |

### 9.3 Produit / stats

| Risque | Sévérité |
|---|---|
| n=97 << 200 pour calibration fiable | **Élevée** (attendu) |
| Surface capture value_picks ~28 % | Moyenne |
| Edge non prouvé statistiquement | **Élevée** (modèle, pas bug code) |

### 9.4 Orphelins / stale

- **`AI_CHAT_AUDIT.md`** — référence architecture supprimée
- **`QUICK_START_CHAT.md`** (début) — encore endpoints `/tg-chat` legacy vs `/api/chat` actuel
- **`REALTIME-ROI.md`** — mentionné stale dans `MASTER_TODO.md` #1
- Modules orphelins backend : **nettoyés** (15/07)

---

## 10. Recommandations priorisées (ROI)

| Rang | Action | Impact | Effort | Pourquoi |
|---|---|---|---|---|
| **1** | **Activer `TENNISBOSS_AI_TOOLS=1` en prod** + doc ops | Élevé | 0.5 j | Valeur immédiate analyste ; code déjà testé, flag off = 0 gain user |
| **2** | **Android : `mode=analyst` + chip Sources** (`tools_called`) | Élevé | 1–2 j | Transparence confiance ; roadmap Phase 1 #5 |
| **3** | **Accumuler `bet_history`** (settlement + backfill scheduler) | Élevé | Continu | Débloque calibration, Phase 3, crédibilité ROI |
| **4** | **Brancher `python run.py compare-engines`** | Moyen | 0.5 j | Ferme gap doc ; outil offline valuable |
| **5** | **Phase 2 MVP : FTS sur `docs/`** → `search_knowledge` | Moyen–élevé | 4–6 j | Mémoire projet distincte de `memory.json` |

Actions secondaires : rafraîchir `PROJECT_STATUS.md` ; archiver ou corriger `AI_CHAT_AUDIT.md` ; UI follow match sur `MatchDetailScreen` ; swap `security-crypto` stable.

---

## 11. Verdict — prêt pour quoi ?

| Scénario | Prêt ? | Commentaire |
|---|---|---|
| **Usage quotidien parieur (Android + API prod)** | ✅ **Oui** | Release-ready depuis 14/07 ; Bet Builder renforce UX |
| **Chat joueur / grounding ELO-H2H** | ✅ **Oui** | Production stable |
| **Chat analyste technique (ROI, calibration, docs)** | ⏳ **Presque** | Backend prêt ; activer flag + Android analyst |
| **Validation statistique edge (n≥200, compare-engines)** | ❌ **Non** | Données insuffisantes ; CLI manquant |
| **Auto-amélioration modèle via assistant** | ❌ **Non** | By design — suggestions only Phase 3 |
| **Scale multi-utilisateur / App Store public** | ⏳ **Partiel** | Alpha crypto, R8 off, auth optionnelle LAN |
| **Refactor package `prediction/` / `data/`** | ❌ **Non urgent** | Phase 4 — après stabilisation assistant |

---

## Annexe A — Fichiers clés

| Chemin | Rôle |
|---|---|
| `bot/api.py` | API Flask, Bet Builder, chat, bet_history |
| `bot/chat.py` | LLM, analyst constants |
| `ai/chat/orchestrator.py` | Intent → tools |
| `ai/chat/tools/registry.py` | 6 outils read-only |
| `bot/config.py` | `AI_TOOLS_ENABLED` |
| `bot/predictor.py` | 🔒 Figé |
| `bot/calibrate.py` | 🔒 Figé |
| `docs/AI_ASSISTANT_ARCHITECTURE.md` | Roadmap assistant |
| `docs/LOGGING_SCHEMA.md` | Schéma repro |
| `MASTER_TODO.md` | Backlog à jour |
| `android/.../ComboBuilderScreen.kt` | Nouveau UI combo |
| `tests/test_ai_tools.py` | Garde-fous assistant |

---

## Annexe B — Commandes de vérification

```bash
# Tests backend
python -m pytest -q

# Compter tests
python -m pytest --co -q

# Activer outils IA (prod / local)
export TENNISBOSS_AI_TOOLS=1

# Chat analyste (curl)
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"ROI last 30 days?","mode":"analyst"}'

# Android unit tests
cd android && ./gradlew testDebugUnitTest
```

---

*Audit read-only — aucun code production modifié. Rapport généré le 16 juillet 2026.*
