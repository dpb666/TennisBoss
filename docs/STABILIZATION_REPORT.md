# TennisBoss — Stabilization Report

**Date :** 15 juillet 2026  
**Base prod :** `da0be76` → `f7ec92b` (stabilization pass)  
**Mode :** STABILIZATION — preuve de fiabilité statistique du moteur de prédiction

---

## Synthèse exécutive

| Zone | Statut | Détail |
|------|--------|--------|
| Services systemd (WSL) | **OK** | `tennisboss-bot` + `tennisboss-scheduler` actifs depuis 12:50 EDT |
| `/health` | **OK** | 4524 joueurs, status ok |
| `/api/monitor/status` | **WARNING** | Endpoints OK ; Odds-API budget épuisé ; bet_history sparse alert ajoutée |
| Scheduler jobs | **OK** | 11 jobs configurés (incl. `espn_warm`, `bet_history`, `rankings`, `calibration`) |
| DB integrity | **OK** | 94 bet_history, 0 doublons, 0 null prediction/CLV sur réglés |
| Calibration (90j) | **SPARSE** | n=94, Brier=0.231 — seuil 200 non atteint |
| Cache engineer/today | **OK** | cold ~10s → cached ~0.17s (TTL 90s) |
| Fixes appliqués | **3** | surface backfill, rankings retry quotidien, monitor bet_history alert |

**Verdict :** moteur opérationnel et mathématiquement sain (`validate-tis` 0 anomalies historiques), mais **volume d'évaluation insuffisant** pour conclure sur la calibration. Pas de régression critique détectée.

---

## 1. Inspection logs

### api.py WARN patterns (dernières heures)

| Pattern | Fréquence | Impact | Action |
|---------|-----------|--------|--------|
| `Endpoint lent engineer/today` | Intermittent (2.6–11s cold) | **M** — acceptable post-batch prefetch ; WARN >5s attendu | Surveiller `endpoint_timings` |
| `Sackmann CSV HTTP 404` | Chaque cycle learn (1h) | **L** — incident connu depuis 2026-07-12 ; MTD/MCP compensent | Pas de fix (source morte) |
| `API-Tennis inactive` | Récurrent | **L** — fallback odds-api.io fonctionne | — |
| `oddspapi: pool épuisé` | Récurrent | **L** — non bloquant pour picks | — |
| `Odds-API budget exhausted` | Monitor 5min | **M** — rate limit temporaire | Normal en pic de scan |
| `unable to open database file` | Transitoire 09:12–12:50 | **M** — redémarrages service + verrou SQLite NTFS/WSL | Résolu après restart 12:51 |
| `Telegram getUpdates` timeout | Intermittent | **L** — réseau ; retry auto | — |
| `WebSocket odds-api.io accès refusé` | Au boot | **L** — plan sans WS live | — |

### Scheduler jobs (24h journalctl)

| Job | Statut | Notes |
|-----|--------|-------|
| `job_monitor` | OK (warnings Odds-API) | Fausses alertes 500 pendant restart bot 12:50 |
| `job_espn_warm` | OK | Actif depuis 12:51 (2min) |
| `job_bet_history_backfill` | OK | Configuré 04:30/j ; pas encore exécuté aujourd'hui post-restart |
| `job_rankings` | OK (tests) | Dernier succès test : live=10, official=70% |
| `job_calibration_report` | OK (tests) | n=94, brier=0.231, verdict=sparse |

Erreurs `Scheduler loop error: unable to open database file` (09:12–09:22) : **résolues** après redémarrage services.

---

## 2. API health

### `/health`
```json
{"status":"ok","players_loaded":4524,"service":"TennisBoss","version":"1.0.0"}
```

### `/api/monitor/status` (auth requis)
| Check | Résultat |
|-------|----------|
| health / status / value / upcoming | 200 OK |
| database | 91946 matchs, 5000 settled, 5163 joueurs |
| odds_api | exhausted (remaining=0) |
| model_drift | ok — accuracy 55.0%, drift 0pts |
| endpoint_timings | engineer/today avg 2414ms, max 11153ms, count 27 |

**overall_status :** `warning` (Odds-API budget uniquement)

---

## 3. DB integrity

Script : `scripts/stabilization_db_check.py`

| Métrique | Valeur |
|----------|--------|
| bet_history total | 94 |
| bet_history réglés (result 0/1) | 94 |
| Doublons event_key | 0 |
| prediction NULL sur réglés | 0 |
| clv_pct NULL sur réglés | 0 |
| clv_log total | 95 (1 sans closing_odds) |
| bet_history sans clv_log | 0 |
| PnL total | -0.11u |
| ROI | -0.12% |

### Surfaces (après fix)
| Surface | n |
|---------|---|
| clay | 11 |
| grass | 11 |
| *(vide/inconnu)* | 72 |

72 paris sans surface car `value_picks` associés n'ont pas de champ surface renseigné — limite données source, pas bug DB.

---

## 4. Cache TTL

| Endpoint | TTL | Cold | Cached |
|----------|-----|------|--------|
| `/api/engineer/today` | 90s | ~10.3s | ~0.17s |
| `/api/match/intelligence` | 60s | N/A (non mesuré ce cycle) | — |
| `/api/upcoming` | 270s | — | — |

Cache engineer/today **fonctionnel** (ratio ~60×).

---

## 5. Calibration (90 jours)

```
python run.py calibration-report --days 90
```

| Métrique | Valeur |
|----------|--------|
| n_settled | 94 |
| Brier score | 0.2312 |
| ROI | -0.12% |
| Win rate | 31.9% |
| CLV moyen | +1.37% |
| Verdict | Pas assez de paris par bin pour conclure |

### Bins probabilité modèle
| Bin | n |
|-----|---|
| 50-55% | 2 |
| 55-60% | 4 |
| 60-65% | 2 |
| 65-70% | 0 |
| 70-75% | 2 |
| 75-100% | 0 |

**Max bin = 4** — loin du seuil 200+ requis pour évaluation fiable.

### Performance par bookmaker (closing source)
| Source | n | Win% | Yield |
|--------|---|------|-------|
| pre_closing | 13 | 46.2% | +45.1% |
| snapshot | 41 | 39.0% | +16.3% |
| last_seen | 40 | 20.0% | -31.6% |

Signal positif : CLV pre_closing fort (+21% avg CLV) mais N trop petit.

---

## 6. Issues trouvées + fixes appliqués

### FIX-1 : bet_history surface vide (P1)

| | |
|---|---|
| **Problème** | `backfill_bet_history_from_clv()` hardcodait `surface=""` → 100% `unknown` dans rapports calibration |
| **Impact** | Impossible de segmenter ROI/calibration par surface (clay/grass/hard) |
| **Fix** | `_value_pick_surface()` helper ; backfill lookup value_picks ; patch des lignes existantes |
| **Validation** | `pytest tests/test_bet_history.py` ; prod : **22 surfaces corrigées** (11 clay, 11 grass) |
| **Fichiers** | `bot/db.py`, `run.py`, `tests/test_bet_history.py` |

### FIX-2 : Rankings ingest sans retry (P1)

| | |
|---|---|
| **Problème** | `job_rankings` planifié lundi 03:00 uniquement — échec = attente 7 jours |
| **Impact** | Dérive classements si scrape échoue un lundi |
| **Fix** | Schedule quotidien 03:00 avec garde-fou ISO week existant (retry auto jusqu'à succès) |
| **Validation** | `pytest tests/test_scheduler.py` |
| **Fichiers** | `bot/scheduler.py` |

### FIX-3 : Monitor sans alerte calibration sparse (P2)

| | |
|---|---|
| **Problème** | Pas d'alerte quand bet_history < 200 settled |
| **Impact** | Ops ne voit pas le blocage évaluation statistique |
| **Fix** | `check_database()` alerte `bet_history sparse: N settled (need 200+)` |
| **Validation** | `pytest tests/test_monitor.py` |
| **Fichiers** | `bot/monitor.py` |

### NON FIXÉ (documenté, pas de changement code)

| Issue | Raison |
|-------|--------|
| Sackmann repos 404 | Source morte ; MTD + MCP actifs ; rewrite non justifié |
| 72 surfaces encore vides | value_picks source sans surface — nécessite enrichissement à la capture pick |
| Odds-API budget alerts | Comportement normal rate limiter |
| NTFS/WSL disk I/O transitoire | Infra ; résolu par restart ; pas de patch code |

---

## 7. Fichiers modifiés

| Fichier | Changement |
|---------|------------|
| `bot/db.py` | `_value_pick_surface()`, backfill surface + patch |
| `bot/scheduler.py` | Rankings daily retry ; log backfill patched count |
| `bot/monitor.py` | Alert bet_history sparse < 200 |
| `run.py` | CLI backfill output |
| `tests/test_bet_history.py` | Test surface backfill |
| `tests/test_scheduler.py` | Mock dict return |
| `scripts/stabilization_db_check.py` | **Nouveau** — checks DB reproductibles |
| `docs/STABILIZATION_REPORT.md` | **Nouveau** — ce rapport |

---

## 8. Tests

```
pytest tests/test_bet_history.py tests/test_scheduler.py tests/test_monitor.py
→ 27 passed
```

---

## 9. Commits

| Hash | Message |
|------|---------|
| `f7ec92b` | `fix(stab): bet_history surface backfill, rankings retry, sparse alert` |

---

## 10. Risques restants

| Risque | Sévérité | Mitigation |
|--------|----------|------------|
| **94 settled << 200** | **H** | Continuer picks + settlement ; job backfill 04:30/j |
| Calibration bins trop sparse | **H** | Attendre volume ; Brier 0.231 prometteur mais non concluant |
| 72/94 sans surface | **M** | Enrichir `log_value_pick` / settlement avec surface ESPN |
| engineer/today cold 6–11s | **M** | Cache 90s + espn_warm 2min ; acceptable |
| Odds-API quota | **M** | RL_SAFETY actif ; alertes attendues |
| SQLite NTFS/WSL locks | **M** | Éviter restart simultané bot+scheduler |
| Rankings couverture 70% | **M** | Ingest quotidien retry activé |
| Danger zones EV 8-18% | **M** | ROI négatif documenté (n=8-10) — intelligence layer actif |

---

## 11. Recommandations

1. **Priorité #1 — Accumuler 200+ paris réglés** : seul bloqueur pour prouver fiabilité statistique. ETA ~8-12 semaines au rythme actuel.
2. **Capturer surface à la source** : lors du `log_value_pick` / scanner, propager surface ESPN → éliminer les 72 vides restants.
3. **Redémarrer services après deploy** : `sudo systemctl restart tennisboss-bot tennisboss-scheduler` pour activer fixes scheduler/monitor.
4. **Surveiller `endpoint_timings`** : alerte si engineer/today max_ms > 15s récurrent.
5. **Ne pas activer ML production** avant 1000+ paris (P2-5 audit).

---

## 12. Next highest ROI task

**Enrichir surface à la capture pick** (scanner → value_picks → bet_history) pour débloquer calibration par surface dès le prochain settlement, sans attendre 200 paris globaux.

Alternative si volume picks faible : **abaisser temporairement le seuil EV** pour générer plus de data d'évaluation — **uniquement** avec tracking CLV séparé et review hebdo calibration report.

---

*Rapport généré automatiquement — Lead Engineer Stabilization Pass, 15 juillet 2026*
