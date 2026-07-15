# TennisBoss — CTO Session Report

**Date :** 15 juillet 2026  
**Base prod :** `a299b80+`  
**Objectif :** améliorations autonomes à fort impact (perf, calibration, ops)

---

## Synthèse

| Métrique | Avant | Après | Impact |
|----------|-------|-------|--------|
| `/api/engineer/today` cold | ~36 s | **0.60 s** | **H** — 60× plus rapide |
| `/api/engineer/today` cached | <1 s | 0.04 s | stable |
| 52× `compute_tis` séquentiel | ~36 s (estimé) | **5.94 s** | **H** |
| TIS `model_prob` | brute (non calibrée) | Platt/temperature via `_calib` | **H** — EV/edge alignés sur `/api/predict` |
| bet_history backfill | manuel CLI | job scheduler 04:30/j | **M** |
| Slow endpoint visibility | logs seulement | `endpoint_timings` + `/api/monitor/status` | **M** |

---

## Travail complété

### 1. `/api/engineer/today` cold ~36s → 0.6s

| | |
|---|---|
| **Problème** | Chaque `compute_tis` ouvrait ~8 connexions SQLite (`player_record`, H2H, fatigue, clutch…) × 40 matchs = centaines de round-trips sur NTFS/WSL. |
| **Cause racine** | Pas de batch ; pattern N×requêtes documenté comme anti-pattern dans `db.py` (commentaire mcp_feeder). |
| **Fix** | `db.prefetch_player_intel()` + `intelligence_layer.intel_batch()` : une transaction pour records, counts, opponents, clutch, H2H. Filtre qualité : skip joueurs absents de `memory.json`. |
| **Validation** | `scripts/time_endpoints.py` ; `tests/test_prefetch_intel.py` ; 44 tests Phase 12/scheduler/TIS passent. |
| **Bénéfice attendu** | Plus de timeouts CF 524 sur cold start ; Engineer tab utilisable sans cache warm. |

### 2. TIS utilise probabilités calibrées

| | |
|---|---|
| **Problème** | `compute_tis` utilisait `predictor.set_to_match_prob` brut ; `/api/predict` applique `_calib` (Platt ou temperature). EV/edge TIS incohérents. |
| **Fix** | Paramètre `calibrate_match_prob` ; branché sur `_calib` dans `/api/match/intelligence`, `/api/insight`, `/api/engineer/today`. |
| **Validation** | `tests/test_match_intelligence.py::test_calibration_callback_changes_model_prob` |
| **Bénéfice** | Recommandations STRONG_BET/VALUE_BET basées sur probas honnêtes (même pipeline que value picks). |

### 3. Index DB bet_history + backfill auto

| | |
|---|---|
| **Problème** | Pas d'index `surface` ; backfill `bet_history` uniquement via CLI. |
| **Fix** | `idx_bet_history_surface` ; `job_bet_history_backfill` (daily 04:30, garde-fou meta). |
| **Validation** | `tests/test_scheduler.py::TestJobBetHistoryBackfill` |
| **Bénéfice** | Stats par surface plus rapides ; historique CLV migré automatiquement. |

### 4. Monitoring endpoint timings

| | |
|---|---|
| **Problème** | Lenteurs visibles seulement en logs ad hoc. |
| **Fix** | `api._record_endpoint_timing()` → meta `endpoint_timings` ; exposé dans `/api/monitor/status` et `monitor.run_full_check`. WARN si >5s. |
| **Validation** | Tests monitor existants passent. |
| **Bénéfice** | Ops peut corréler alertes worker avec latence TIS. |

---

## Commits (à créer localement)

| Hash | Message |
|------|---------|
| *(pending)* | `perf(db): batch prefetch player intel for TIS signal queries` |
| *(pending)* | `fix(tis): apply Platt/temperature calibration to model_prob and EV` |
| *(pending)* | `feat(ops): engineer/today batch path, endpoint timing, bet_history backfill job` |

---

## Fichiers modifiés

| Fichier | Changement |
|---------|------------|
| `bot/db.py` | `PlayerIntelCache`, `prefetch_player_intel`, index `idx_bet_history_surface` |
| `bot/intelligence_layer.py` | `intel_batch`, cache contextvar, wrappers `_cached_*` |
| `bot/match_intelligence.py` | `calibrate_match_prob` callback |
| `bot/api.py` | batch engineer/today, filtre joueurs connus, timing, monitor payload |
| `bot/scheduler.py` | `job_bet_history_backfill` daily 04:30 |
| `bot/monitor.py` | `endpoint_timings` dans full check |
| `scripts/time_endpoints.py` | benchmark cold/cached (nouveau) |
| `tests/test_prefetch_intel.py` | tests batch (nouveau) |
| `tests/test_match_intelligence.py` | test calibration |
| `tests/test_scheduler.py` | test backfill job |

---

## Prédiction / calibration

- TIS EV/edge/fair_odds alignés sur calibration production (`platt_a/b` ou `match_calib_k`).
- Pas de changement aux poids modèle — uniquement post-processing probabilité (honnête).
- Continuer accumulation bet_history (94→200+ picks) pour bins calibration fiables.

---

## Déploiement

**Restart requis :** oui — `bot/api.py`, `bot/scheduler.py`, `bot/monitor.py` modifiés.

```bash
sudo systemctl restart tennisboss-bot.service
sudo systemctl restart tennisboss-worker.service   # si scheduler séparé
```

Index SQLite `idx_bet_history_surface` créé automatiquement au prochain `db.init()` (démarrage API/worker).

---

## Roadmap restant

| Item | Impact | Notes |
|------|--------|-------|
| Calibration bins sparse (N<200 picks) | **H** | Attendre settlements ; job backfill aide |
| Couverture ranking ~70% | **M** | `job_rankings` hebdo déjà en prod |
| WTA serve/return partiel | **M** | MCP backfill 12h OK |
| Indoor surface split | **M** | Migration schema |
| Silent `except` hors api.py | **M** | ~15 fichiers (digest, clv, db…) |
| Engineer Android UI tab | **M** | API prête |
| Background TIS warm job | **L** | Cold déjà 0.6s — optionnel |
| TabRow deprecated Compose | **L** | Cosmétique |
| ML production | **L** | Attendre 1000+ picks |

---

## Tests exécutés

```
pytest tests/test_prefetch_intel.py tests/test_match_intelligence.py tests/test_scheduler.py  → 20 passed
pytest tests/test_phase12_de.py tests/test_bet_history.py tests/test_intelligence_layer.py  → 24 passed
python scripts/time_endpoints.py → engineer/today cold 0.60s
```
