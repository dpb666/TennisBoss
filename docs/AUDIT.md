# TennisBoss — Audit complet (12 juillet 2026)

Rapport demandé par la directive « Senior AI Software Architect ». Périmètre :
backend Python (`bot/`), API Flask, modèle ML, base SQLite, app Android
Kotlin Compose, configuration, tests, dépendances, déploiement.

**Conclusion en une phrase : le projet n'est plus un prototype.** L'essentiel
des 8 étapes de la directive est déjà implémenté, testé (298 tests backend +
suite Android) et déployé en production (systemd + tunnel Cloudflare +
domaine tennisboss.online). Ce rapport détaille ce qui existe, ce qui manque
réellement, et ce qui est délibérément écarté avec justification.

---

## 1. Architecture actuelle

```
TennisBoss/
├── bot/                    # Backend Python (~55 modules)
│   ├── api.py              # API Flask : 30+ endpoints, auth X-API-Token,
│   │                       #   rate limiting (CF-Connecting-IP), Swagger UI
│   ├── openapi_spec.py     # Spec OpenAPI 3.0 écrite à la main (/api/docs)
│   ├── predictor.py        # Modèle : features pondérées + Elo global/surface
│   │                       #   (blend par surface), calibration calib_k
│   ├── elo.py              # Elo global + par surface
│   ├── signal_backtest.py  # Backtest walk-forward des signaux (garde-fou :
│   │                       #   aucun signal n'entre dans le modèle sans preuve)
│   ├── calibrate.py        # Calibration des probabilités
│   ├── auto_learner.py     # Réentraînement automatique après résultats réels
│   ├── settlement.py       # Règlement des picks (résultats réels)
│   ├── clv.py              # Closing Line Value — preuve d'edge
│   ├── intelligence_layer.py # Signaux informationnels : forme, steam moves,
│   │                       #   fatigue, qualité adversaires, sentiment (opt-in)
│   ├── scheduler.py        # Worker 24/7 : ingestion, auto-learn, monitor,
│   │                       #   backup, digest quotidien (5 jobs)
│   ├── monitor.py          # Health-checks endpoints (base URL configurable)
│   ├── db.py               # TOUT le SQL vit ici (70 fonctions nommées,
│   │                       #   mockables) — convention structurante du projet
│   ├── sackmann_feeder.py  # Ingestion Jeff Sackmann (légal, open data)
│   ├── tennisdata_feeder.py# Ingestion tennis-data.co.uk (légal)
│   ├── odds_api.py         # Cotes via odds-api.io (plan limité 100 req/h)
│   └── ...                 # chat IA, Telegram, push FCM, paper trading, CLV
├── android/                # Kotlin Compose, MVVM (ViewModel par écran),
│   │                       #   Retrofit, nav 5 groupes (NavGroups.kt)
├── tests/                  # 298 tests backend (pytest) + tests unitaires Android
├── state/                  # SQLite (WAL) : matches (91 946 lignes), picks,
│   │                       #   odds snapshots, meta — hors git, hors Docker
├── Dockerfile + docker-compose.yml  # 3 services : api, worker, cloudflared
├── .dockerignore           # secrets/.env exclus des images (fix sécurité)
└── systemd (hors repo)     # tennisboss-bot, -scheduler, -supervisor, tunnel
```

**Flux de données** : feeders (Sackmann + tennis-data) → SQLite → auto-learner
recalcule Elo/poids → predictor sert `/api/predict` et `/api/insight` →
settlement règle les picks après résultats réels → CLV mesure l'edge réel
contre la closing line → auto-calibration ajuste `calib_k`.

## 2. Points forts

- **Garde-fou méthodologique central** : aucun signal n'influence
  `predictor.predict()` sans backtest walk-forward préalable
  (`signal_backtest.py`). Les signaux non prouvés (forme, fatigue, qualité
  adversaires, steam, sentiment) restent **informationnels** dans
  `/api/insight`. C'est le bon design pour un outil d'aide à la décision.
- **Boucle d'apprentissage fermée** : ingestion → prédiction → settlement →
  recalibration automatique, sans intervention manuelle.
- **Mesure d'edge honnête** : la couche CLV compare chaque pick à la closing
  line — la seule preuve statistiquement sérieuse d'un avantage.
- **Convention SQL stricte** : tout le SQL dans `db.py` en fonctions nommées →
  mockable, testable (la violation ponctuelle de cette règle a coûté un bug
  de perf 109 s → 0.9 s, voir §3).
- **Sécurité correcte pour la taille du projet** : token API hors git (.env),
  CORS verrouillé, rate limiting par vrai client (CF-Connecting-IP), secrets
  exclus des images Docker, upload borné.
- **Déploiement réel et résilient** : systemd avec auto-restart, tunnel
  Cloudflare permanent, backups automatiques avec rétention.
- **Tests substantiels** : 298 tests backend couvrant API, DB, modèle,
  calibration, settlement, CLV, rate limiting, scheduler ; suite Android.

## 3. Bugs connus (corrigés cette session — documentés pour mémoire)

| Bug | Impact | Fix |
|---|---|---|
| `matches.date` mélange 2 formats (`20220103` 87 % / `2022-01-17` 13 %) | tout filtre/tri lexicographique naïf est faux pour la majorité des lignes | `REPLACE(date,'-','')` avant comparaison + tests couvrant les 2 formats |
| `.env` embarqué dans les images Docker (`COPY . .` sans `.dockerignore`) | secrets en clair dans chaque image | `.dockerignore` (fix vérifié par rebuild) |
| `monitor.py` codait `localhost:8000` en dur | health-checks cassés en multi-conteneurs | env `TENNISBOSS_API_BASE_URL` |
| SQL brut hors `db.py` dans `intelligence_layer.py` | tests non mockés tapaient la DB de prod → 109 s | SQL relocalisé dans `db.py`, mocks ajoutés |

**Piège résiduel à connaître** : toute nouvelle requête sur `matches.date`
doit normaliser le format. C'est documenté en tête de `intelligence_layer.py`
et dans les docstrings de `db.py`.

## 4. Dette technique

- **`bot/` est plat (~55 modules)** : lisible mais la limite approche. Un
  regroupement en sous-packages (`bot/ml/`, `bot/ingest/`, `bot/serve/`)
  serait cosmétiquement propre mais casserait tous les imports pour zéro
  gain fonctionnel — à faire seulement si le projet accueille d'autres devs.
- **Android sans Room/offline** : l'app est online-only. Acceptable pour un
  outil de consultation temps réel ; à revoir seulement si les retours
  utilisateurs Google Play le demandent.
- **Suite de tests à 82 s en local (WSL)** : dû à la croissance (298 tests) et
  aux tests I/O réels (backup, DB temporaires) — pas de régression cachée,
  CI reste rapide sur runner propre.
- **Deux formats de date en base** : non unifiés à la source (une migration
  `UPDATE matches SET date=REPLACE(date,'-','')` serait possible mais touche
  91 946 lignes de prod — bénéfice faible tant que la normalisation en
  lecture est systématique).

## 5. Risques production

1. **Dépendance odds-api.io plan limité** (100 req/h, WebSocket 403, ITF non
   cotés) : le cache rate-limit existe, mais toute nouvelle feature
   consommatrice de cotes doit budgéter ses requêtes.
2. **Pas d'edge prouvé à ce stade** : la couche CLV est en place pour le
   mesurer, mais l'échantillon de picks réglés est encore petit. Le
   positionnement Google Play (« aide à la décision », pas « prédicteur
   gagnant ») reflète correctement cette réalité — à maintenir.
3. **SQLite mono-serveur** : suffisant pour la charge actuelle (une app,
   WAL, accès concurrents testés). Migration Postgres seulement si
   multi-utilisateurs réels.
4. **Machine unique (WSL)** : systemd + backups atténuent, mais une panne
   matérielle interrompt le service. Le docker-compose permet une
   redéploiement rapide sur un VPS Ubuntu 24.04 si besoin.

## 6. État vs les 8 étapes de la directive

| Étape | État | Détail |
|---|---|---|
| 1. Audit | ✅ ce document | |
| 2. Cerveau IA | ✅ ~85 % | Elo global+surface, forme, fatigue, qualité adversaires, H2H, service/retour, odds/value : faits. **Manquent : break points, tie-breaks, jours de repos** (nécessitent parsing de stats fines Sackmann). Restructuration `bot/ml/` : écartée (voir §4). |
| 3. Backtest | ✅ ~80 % | `signal_backtest.py` (walk-forward strict) + `backtest.py` + calibration. **Manque : rapport HTML** (`reports/backtest_report.html`) et une commande unifiée `backtest --full` avec Brier/log-loss/ROI consolidés. |
| 4. API prod | ✅ fait | Auth, rate limiting, Swagger, validation, logs. Migration FastAPI : **écartée** — aucun besoin async avéré, réécriture risquée de 30+ endpoints stables. Redis : **écarté** — cache SQLite/mémoire suffit à cette charge. |
| 5. Mode autonome | ✅ fait | Scheduler 5 jobs 24/7, settlement, auto-learn, monitor + `/api/monitor/status`. |
| 6. Android | ✅ ~80 % | MVVM, Retrofit, nav 5 groupes, prédiction/confiance/value/historique/Edge/notifications : faits. **Manquent : Room/offline** (écarté sauf demande) et un vrai écran Dashboard synthétique. |
| 7. Déploiement | ✅ fait | Dockerfile, compose 3 services, .env.example, systemd, DEPLOYMENT.md. |
| 8. Qualité | ✅ fait | 298 tests, commits documentés, CI GitHub Actions verte. |

## 7. Roadmap recommandée (par valeur décroissante)

1. **Rapport de backtest consolidé** (étape 3) : commande
   `python -m bot.backtest --full` produisant `reports/backtest_report.html`
   avec accuracy, log loss, Brier, calibration, ROI théorique — c'est aussi
   un argument de transparence pour Google Play.
2. **Features stats fines** (étape 2) : break points convertis/sauvés et
   tie-breaks depuis les CSV Sackmann (colonnes déjà présentes dans les
   données brutes) — à backtester avant toute entrée dans le modèle, comme
   toujours.
3. **Écran Dashboard Android** (étape 6) : synthèse du jour (digest, picks
   ouverts, CLV cumulé, santé modèle) en écran d'accueil.
4. **Jours de repos** (étape 2) : complément naturel du signal fatigue déjà
   livré (même infra `db.player_recent_*`).
5. (Différé) Migration format de date en base, Room Android, sous-packages
   `bot/` — seulement sur besoin avéré.
