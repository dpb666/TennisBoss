# TennisBoss — Lead Engineer Audit

**Date :** 15 juillet 2026  
**Auditeur :** session Lead Engineer autonome  
**Périmètre :** `bot/`, `android/`, `tests/`, scheduler, API, DB, pipelines Phase 12

---

## Synthèse exécutive

TennisBoss est **production-ready côté Android** et **fonctionnel côté backend**, avec une architecture Phase 12 orientée décision (TIS, bet_history, calibration). Les risques principaux ne sont plus des bugs crash — ce sont **le volume de données d'évaluation** (94 paris réglés, bins calibration trop sparse) et **l'automation incomplète** (rankings/calibration CLI existent mais n'étaient pas planifiés dans le scheduler).

---

## P0 — Critique (corriger en priorité)

| # | Problème | Impact | Statut |
|---|----------|--------|--------|
| P0-1 | **Scheduler sans ingest rankings hebdo** | `ranking_feeder.ingest()` existe (`run.py ingest-rankings`) mais le worker 24/7 ne l'appelle pas → dérive des classements | **Fixé cette session** (`job_rankings`) |
| P0-2 | **Pas de rapport calibration automatique** | `calibration-report` CLI existe mais rien ne l'exécute → métriques ROI/CLV non suivies sans action manuelle | **Fixé cette session** (`job_calibration_report`) |
| P0-3 | **OpenAPI incomplet Phase 12** | `/api/match/intelligence`, `/api/engineer/today`, `/api/bet-history/*`, `/api/clv/weekly` absents de Swagger | **Fixé cette session** |
| P0-4 | **Deploy prod en attente** | Logs WARN api.py (#7), watchlist loop, endpoints Phase 12 non actifs sans restart service | **Documenté — OK utilisateur requis** |

---

## P1 — Important

| # | Problème | Impact | Recommandation |
|---|----------|--------|----------------|
| P1-1 | **Calibration bins sparse** | 94 paris → max 4 picks/bin ; impossible de conclure sur 70% prédit | Continuer settlement + `backfill-bet-history` ; viser 200+ picks |
| P1-2 | **Couverture ranking officiel ~70%** (joueurs actifs confiants) | 30% sans rang officiel ; fallback Elo masque le gap dans TIS | `ingest-rankings` hebdo + tennisdata ingest 6h |
| P1-3 | **WTA serve/return partiel** | 922 matchs MCP enrichis mais couverture charting faible (~200/an) | MCP backfill 12h OK ; pas de source WTA feature-complete gratuite |
| P1-4 | **Indoor non splitté** | Rotterdam/Basel = hard outdoor dans le modèle | Migration surface `indoor` — effort moyen, P2 |
| P1-5 | **Master TODO #7 logs non déployés** | 26 WARN ajoutés en prod code mais service pas restart | `sudo systemctl restart tennisboss-bot.service` après OK user |
| P1-6 | **Engineer Android UI absent** | API `engineer/today` prête, pas de sub-tab Value | Repoussé volontairement — moteur d'abord |

---

## P2 — Amélioration continue

| # | Item |
|---|------|
| P2-1 | TabRow deprecated → PrimaryTabRow (cosmétique Compose) |
| P2-2 | `security-crypto` alpha → stable 1.1.0 |
| P2-3 | R8 shrinking disabled en release |
| P2-4 | REALTIME-ROI.md stale (FastAPI supprimé) |
| P2-5 | ML production — attendre 1000+ paris réglés + data complète |
| P2-6 | OpenClaw agent_router stubs |

---

## Bugs / points faibles confirmés

### API & rate limits
- `odds_api.py` : pool multi-clés, cache TTL, RL_SAFETY — **solide**
- Live odds TTL 60s sur 4 sites — **corrigé** (MASTER_TODO #3c)
- `/api/engineer/today` limité 10/min — **correct**

### Données
- Formats date mixtes en DB (`YYYYMMDD` vs ISO) — normalisés en lecture, pas migrés à la source
- `ranking_diff` 100% via fallback Elo quand rang absent — **transparent** mais peut sur-estimer confiance ranking

### DB
- SQLite WAL, migrations additive dans `db.init()` — **OK**
- `bet_history` dedup sur `event_key` — **OK**

### Prédictions & évaluation
- `validate-tis` : 0 anomalies sur échantillon 50-200 matchs — **math OK**
- Brier 0.231 sur 94 picks CLV — **prometteur** mais N trop petit
- `compare_engines` : heuristique ≥ ML offline avec data actuelle — **ne pas remplacer predictor**

### Code dupliqué / risques
- `bot/` plat ~59 modules — lisible, limite approche
- Pas de duplication critique détectée post-Phase 12

### Error handling
- `api.py` : 26/31 silent swallows → WARN (non déployé)
- Scheduler jobs : try/except + log ERROR — **OK**

---

## Architecture (carte mentale)

```
Sources → Feeders → SQLite → memory.json/Elo → predictor + intelligence_layer
                                              → match_intelligence (TIS)
                                              → settlement/CLV → bet_history
Live: odds-api.io → api.py → Android (10.0.2.2:8000 emulator)
Worker: scheduler.py (learn, ingest, mtd, mcp, monitor, backup, digest, rankings*, calibration*)
```

---

## Fixes appliqués (session Lead Engineer)

1. `bot/scheduler.py` — `job_rankings` (hebdo lundi 03:00) + `job_calibration_report` (hebdo dimanche 22:00)
2. `bot/openapi_spec.py` — endpoints Phase 12 documentés
3. `tests/test_scheduler.py` — tests garde-fou anti-doublon rankings/calibration
4. Ce document + mise à jour `MASTER_TODO.md`

---

## Routine hebdomadaire recommandée (utilisateur)

```bash
# Lundi — qualité données (automatique via scheduler si worker actif)
python run.py data-quality

# Après chaque session de paris / fin de semaine
python run.py calibration-report --days 90
python run.py validate-tis --limit 200

# Mensuel
python run.py backfill-bet-history --limit 5000
python run.py compare-engines   # offline, pas prod
```

**Deploy prod (quand prêt) :**
```bash
sudo systemctl restart tennisboss-bot.service
curl -s http://127.0.0.1:8000/health
```
