# TennisBoss — Audit Pipeline de Données (Phase 12)

**Date :** 15 juillet 2026  
**Périmètre :** audit READ-ONLY — `bot/datasource.py`, feeders (Sackmann, tennis-data, ManTennisData, MCP), `bot/odds_api.py`, schéma `bot/db.py`, `docs/AUDIT.md`.  
**Objectif :** inventorier les données disponibles pour l'intelligence de paris, identifier les lacunes Phase 12, recommander des sources et prioriser la qualité des données avant toute montée en ML.

---

## Synthèse exécutive

TennisBoss dispose d'une **base historique solide (~92 000 matchs)** avec serve/return/BP/TB pour l'ATP (archive Sackmann + ingestion continue ManTennisData) et une **couche marché fonctionnelle** (cotes live odds-api.io, snapshots CLV, cotes historiques tennis-data.co.uk). Les signaux Phase 12 (TIS, clutch, steam move, fatigue) s'appuient sur cette fondation.

**Trois gaps structurels persistent :**

1. **WTA feature-complete** — pas de source gratuite équivalente à ManTennisData ; serve/return restent neutres (0.5), seul le clutch BP est partiellement enrichi via MCP (~200 matchs/an).
2. **Classement live** — seul un ranking moyen historique (tennis-data) est stocké ; pas de feed ATP/WTA officiel à jour.
3. **Indoor / tie-break profil joueur** — indoor n'est pas une dimension distincte (hard indoor = hard) ; les TB sont stockés par match mais pas agrégés en profil EMA comme serve/return.

**Recommandation centrale :** consolider et fiabiliser les données existantes (WTA clutch, ranking live, indoor split, unification dates) **avant** d'entraîner un modèle ML supervisé (`bot/ml_prep/`). Le modèle actuel (features pondérées + Elo) fonctionne déjà ; le ML n'apportera de la valeur que si les features manquantes sont comblées.

---

## 1. Architecture du pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SOURCES EXTERNES (gratuites / clés)                  │
├──────────────────┬──────────────────┬──────────────────┬────────────────────┤
│ Sackmann CSV     │ tennis-data.co.uk│ ManTennisData    │ MCP (charting W)   │
│ (archive 404)    │ GS/Masters 2020+ │ ATP post-05/2026 │ enrichissement WTA │
│ ATP+WTA histor.  │ ATP+WTA + cotes  │ serve/return/BP  │ BP clutch partiel  │
└────────┬─────────┴────────┬─────────┴────────┬─────────┴──────────┬─────────┘
         │                  │                  │                    │
         ▼                  ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  bot/datasource.py  │  tennisdata_feeder  │  mantennisdata_feeder │ mcp_feeder│
│  (parse CSV, TB, BP)│  (ingest 6h)        │  (ingest 6h, ATP)     │ (12h bf)  │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  SQLite state/tennisboss.db                                                 │
│  matches (~92k) │ players │ historical_odds │ market_snapshots │ clv_log    │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  memory.json → learner.train → Elo global/surface → predictor / TIS         │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LIVE : API-Tennis (fixtures) → odds-api.io (cotes, live, CLV snapshots)    │
│         ESPN (fallback fixtures) │ Sofascore (probe, souvent 403)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Scheduler (`bot/scheduler.py`) :**

| Job | Fréquence | Rôle |
|-----|-----------|------|
| `tennisdata_feeder.ingest` | 6 h | ELO + ranking moyen + cotes historiques (ATP+WTA) |
| `mantennisdata_feeder.ingest` | 6 h | Features complètes ATP (serve/return/BP/TB) |
| `mcp_feeder.backfill` | 12 h | Enrichissement clutch WTA (non destructif) |
| `auto_learner` | 1 h | Réentraînement après settlement |

---

## 2. Données actuellement disponibles

### 2.1 Matchs historiques

| Dimension | ATP | WTA | Source(s) | Notes |
|-----------|-----|-----|-----------|-------|
| Matchs archivés | ✅ ~majorité | ✅ ~minorité | Sackmann archive + tennis-data + MTD | ~92 000 lignes en prod |
| Serve / return1 / return2 | ✅ | ⚠️ partiel | Sackmann, MTD (ATP ongoing) | WTA : 0.5 neutre sauf MCP (non appliqué — voir §3) |
| Break points (saved/faced) | ✅ | ⚠️ partiel | Sackmann, MTD, MCP backfill | WTA : ~923 matchs enrichis MCP (12/07/2026) |
| Tie-breaks gagnés/match | ✅ | ⚠️ partiel | Score parsé (Sackmann) ou colonnes MTD | Agrégés en `player_clutch_stats`, pas en profil EMA |
| Surface (hard/clay/grass) | ✅ | ✅ | Toutes sources | Indoor hard traité comme `hard` |
| Marge de victoire (jeux) | ✅ | ✅ | Sackmann, MTD | Utilisée par Elo dynamique |
| Challengers / ITF | ✅ archive | ✅ archive | Sackmann (historique) | **Pas d'ingestion continue** depuis disparition repos |
| Tournoi / round / best-of | ⚠️ partiel | ⚠️ partiel | tennis-data, Sackmann CSV | Non persisté en colonnes DB dédiées |
| Ranking au moment du match | ⚠️ partiel | ⚠️ partiel | tennis-data (WRank/LRank) | Moyenne stockée dans profil ; Sackmann CSV non ingéré |
| Retraits / walkover | ⚠️ implicite | ⚠️ implicite | Score vide → margin NULL | Pas de flag explicite |

### 2.2 Surfaces

| Type | Disponible | Implémentation |
|------|------------|----------------|
| Hard (outdoor) | ✅ | Colonne `matches.surface` |
| Clay | ✅ | Idem |
| Grass | ✅ | Idem |
| **Indoor hard** | ❌ split | Détecté par mots-clés tournoi (`config.py` : "indoor", "rotterdam", "basel"…) mais **non stocké** comme surface distincte |
| Carpet | ❌ | Absent (circuit disparu) |

### 2.3 Serve / Return

| Métrique | ATP | WTA | Stockage |
|----------|-----|-----|----------|
| % points gagnés au service | ✅ | ⚠️ | `matches.w_serve` / `l_serve` → profils EMA |
| % retour 1re balle adverse | ✅ | ⚠️ | `w_return1` / `l_return1` |
| % retour 2e balle adverse | ✅ | ⚠️ | `w_return2` / `l_return2` |
| Forme récente (EMA) | ✅ | ✅ | `players.recent` (dérivé des 4 features) |
| Séparation indoor/outdoor serve | ❌ | ❌ | — |

**Parsing :** `datasource._match_features()` reconstruit serve/return depuis comptes bruts Sackmann ; ManTennisData fournit des ratios pré-calculés.

### 2.4 Break points & clutch

| Métrique | ATP | WTA | Usage |
|----------|-----|-----|-------|
| BP saved / faced au service | ✅ | ⚠️ MCP | `matches.w_bp_*` / `l_bp_*` |
| BP converties au retour | ✅ (calculé) | ⚠️ | `db.player_clutch_stats()` |
| Tie-breaks gagnés/joués | ✅ | ⚠️ | Parsés score ou MTD ; signal informatif `clutch_signals()` |
| Backtest clutch | ✅ | ⚠️ | `signal_backtest.backtest_clutch()` — **pas encore dans le modèle** |

### 2.5 Rankings

| Type | Disponible | Source | Limitation |
|------|------------|--------|------------|
| Ranking moyen historique | ✅ | tennis-data → `players.rank` | Moyenne sur matchs GS/Masters, pas live |
| Ranking au match (point-in-time) | ⚠️ CSV seulement | Sackmann `winner_rank` / `loser_rank` | **Non ingéré en DB** |
| Ranking live ATP/WTA | ❌ | — | API `/api/players` calcule un rang ELO interne, pas officiel |
| Points ATP/WTA | ❌ | Sackmann CSV | Non persistés |

### 2.6 Cotes & marché

| Dimension | Disponible | Source | Stockage |
|-----------|------------|--------|----------|
| Cotes live ML (pre-match) | ✅ | odds-api.io (Bet365 + Betfair Exchange) | Cache TTL 10 min |
| Cotes live in-play | ✅ | odds-api.io | Spread/totals games (Betfair) |
| Cotes historiques closing | ✅ | tennis-data.co.uk | `historical_odds` (B365, Pinnacle, Max, Avg) |
| Snapshots pré-match (CLV) | ✅ | Scheduler + API | `market_snapshots` |
| Line movement / steam move | ✅ | `db.line_movement()` | Ouverture → dernière capture ; seuil 15 % |
| CLV mesuré | ✅ | `bot/clv.py` | `clv_log` (pick vs closing line) |
| ITF / Challenger cotés | ❌ | odds-api.io plan limité | Non couverts |
| Spread/totals historiques | ❌ | — | Live seulement |

**Quota odds-api.io :** 100 req/h/clé, pool jusqu'à 12 clés (~1 200 req/h). WebSocket 403 documenté.

### 2.7 Live & fixtures

| Source | Rôle | Auth | Fiabilité |
|--------|------|------|-----------|
| API-Tennis | Fixtures + live (primaire) | `AT_API_KEY` | ✅ actif |
| odds-api.io | Fixtures fallback + cotes + live scores | Pool clés | ✅ actif |
| ESPN | Fixtures fallback ATP+WTA | Gratuit, non officiel | ✅ backup |
| Sofascore | Probe live | Gratuit | ❌ souvent 403 |
| Sportradar | Gabarit prêt | `SR_KEY` | ⚠️ non câblé |

---

## 3. Lacunes Phase 12

Priorisées par impact sur TIS (`bot/match_intelligence.py`) et ML prep (`bot/ml_prep/features.py`).

### 3.1 Critiques (bloquent la qualité ML)

| Gap | Impact | État actuel |
|-----|--------|-------------|
| **WTA serve/return ongoing** | Profils femmes biaisés (0.5) ; TIS player score faible | Aucune source gratuite identifiée post-Sackmann |
| **Ranking live / point-in-time** | `ranking_diff` ML = NaN pour joueurs sans tennis-data ; pas de signal "upset seed" | Seul ranking moyen GS/Masters |
| **Ingestion Challenger/ITF continue** | Joueurs bas circuit invisibles à l'apprentissage | Archive Sackmann figée (~juin 2026) |

### 3.2 Importantes (affaiblissent les signaux)

| Gap | Impact | État actuel |
|-----|--------|-------------|
| **Indoor / outdoor split** | Paris indoor (Rotterdam, Paris-Bercy) mal modélisés | Hard unique |
| **Tie-break profil joueur** | TB agrégés en fenêtre clutch (20 matchs) mais pas en feature modèle | Informatif seulement |
| **MCP serve/return WTA** | Données MCP disponibles mais **non appliquées** (COALESCE bloqué par 0.5 explicite) | Fix trivial possible |
| **Unification format date** | 87 % `YYYYMMDD` / 13 % `YYYY-MM-DD` | Normalisation en lecture, pas en source |
| **Ranking Sackmann non ingéré** | Perte de ranking point-in-time sur ~70k matchs historiques | Colonnes absentes du schéma |

### 3.3 Souhaitables (edge marginal)

| Gap | Impact |
|-----|--------|
| Point-by-point / charting complet | Modèle in-play avancé, momentum |
| Météo / conditions (vent, chaleur) | `weather_profile` partiel ; pas de feed météo match |
| Retraits / blessures structurés | Fatigue signal proxy seulement |
| Cotes spread/totals historiques | Backtest marchés alternatifs |
| Doubles | Filtrés ESPN, ignorés ailleurs |
| H2H externe (surface-specific) | Calculé depuis DB locale uniquement |

---

## 4. APIs candidates (gratuites & payantes)

### 4.1 Déjà intégrées — maintenir

| API | Coût | Données | Recommandation |
|-----|------|---------|----------------|
| **ManTennisData** | Gratuit (GitHub) | ATP serve/return/BP/TB | ✅ Continuer ; surveiller fraîcheur repo |
| **tennis-data.co.uk** | Gratuit | GS/Masters + cotes closing + ranking match | ✅ Continuer ; étendre liste tournois si besoin |
| **MCP (Sackmann charting)** | Gratuit | WTA BP (crowdsourcé) | ✅ Continuer backfill ; ne pas sur-estimer couverture |
| **odds-api.io** | Payant (plan limité) | Live + pre-match cotes | ✅ Conserver ; budgéter requêtes ; envisager upgrade si CLV scale |
| **API-Tennis** | Payant (clé existante) | Fixtures live | ✅ Primaire fixtures |
| **ESPN** | Gratuit (non officiel) | Fixtures fallback | ✅ Garder en backup |

### 4.2 Gratuites — à évaluer

| API | Données potentielles | Risque | Recommandation |
|-----|---------------------|--------|----------------|
| **Wayback / miroirs Sackmann** | Archive ATP/WTA complète | Figé, maintenance | ⚠️ Backup seulement ; `SACKMANN_URL_TEMPLATE` env déjà prévu |
| **Tennis Abstract (scraping)** | Elo TA, rankings, stats avancées | ToS / fragilité HTML | ❌ Éviter en prod — pas de API officielle |
| **Flashscore / Sofascore** | Live scores, stats match | 403 / anti-bot | ❌ Déjà abandonné (`probe_live()`) |
| **Wikipedia / Wikidata** | Métadonnées tournois | Bruit | ❌ ROI faible |

### 4.3 Payantes — recommandations

| API | Données | Coût estimé | Recommandation |
|-----|---------|-------------|----------------|
| **Sportradar Tennis** | Scores live, stats match, rankings officiels | $$$ | ⭐ **Priorité #1 payant** — gabarit déjà dans `live_api.py` ; rankings live + stats WTA |
| **Odds API upgrade** | Plus de books, ITF, WebSocket | $$ | ⭐ Si volume picks augmente ; ITF critical pour CLV bas circuit |
| **Betfair Exchange API** | Cotes sharp directes, marchés profonds | Gratuit (commission) | ⭐ Complément à odds-api pour CLV ; dev integration modérée |
| **Pinnacle API (via broker)** | Closing lines sharp historiques | $$ | Utile backtest ROI ; tennis-data PS déjà couvre partiellement |
| **Stats Perform / Opta** | Stats officielles WTA/ATP | $$$$ | Overkill pour taille actuelle |
| **RapidAPI tennis bundles** | Variable | $ | ⚠️ Due diligence ToS ; souvent re-scrape |

**Recommandation globale :** rester sur stack gratuite + API-Tennis/odds-api existantes pour 3–6 mois. Investir dans **Sportradar** uniquement si le volume de picks réglés justifie rankings live WTA et stats feature-complete femmes.

---

## 5. Priorité : qualité des données avant ML

Le module `bot/ml_prep/` définit 10 features (`ranking_diff`, Elo, surface Elo, forme, serve/return, cotes). État de remplissage estimé sur l'archive :

| Feature ML | Couverture estimée | Qualité | Action avant ML |
|------------|-------------------|---------|-----------------|
| `elo_diff` / `surface_elo_diff` | ~95 % | ✅ Haute | — |
| `form_diff` | ~90 % ATP / ~60 % WTA | ⚠️ | Combler WTA serve/return |
| `serve_diff` / `return*_diff` | ~85 % ATP / ~40 % WTA | ⚠️ | WTA source ou MCP fix |
| `ranking_diff` | ~30 % (tennis-data GS/Masters) | ❌ Faible | **Ranking live feed requis** |
| `odds_implied_p1` | ~15 % (historical_odds) | ⚠️ | Acceptable pour backtest GS |
| `odds_move_*` | <5 % (market_snapshots récents) | ❌ | Accumuler snapshots ; pas bloquant ML offline |

**Principe du projet (cf. `AGENTS.md`, `signal_backtest.py`) :** aucun signal n'entre dans `predictor.predict()` sans backtest walk-forward. Le ML supervisé doit suivre la même règle — entraîner sur des features à 40 % de NaN produira un modèle non calibré pire que le baseline Elo.

**Ordre de priorité data > ML :**

1. Fiabiliser les features existantes (WTA, ranking, indoor)
2. Accumuler CLV / snapshots (preuve d'edge, pas feature ML immédiate)
3. Backtester clutch / form / steam sur échantillon suffisant
4. Seulement alors : entraîner XGBoost/MLP sur `ml_prep` avec features complètes

---

## 6. Prochaines étapes (classées valeur / effort)

| # | Action | Valeur | Effort | Owner suggéré |
|---|--------|--------|--------|---------------|
| 1 | **Fix MCP serve/return WTA** — backfill avec UPDATE ciblant `w_serve=0.5` au lieu de COALESCE seul | ⭐⭐⭐ | S | Agent data |
| 2 | **Feed ranking live** — scraper/API ATP & WTA rankings hebdo → table `rankings` + snapshot date | ⭐⭐⭐ | M | Agent data |
| 3 | **Ingérer ranking Sackmann rétroactif** — colonnes `w_rank`/`l_rank` sur matchs archive | ⭐⭐⭐ | M | Agent data |
| 4 | **Surface indoor** — colonne `indoor INTEGER` ou surface `hard_indoor` ; mapping tournois config | ⭐⭐ | M | Agent data |
| 5 | **TB profil EMA** — feature `tb_rate` dans profils (comme serve) + backtest | ⭐⭐ | M | Agent ML |
| 6 | **Source WTA ongoing** — évaluer Sportradar trial OU extension MCP + tennis-data | ⭐⭐⭐ | L | Agent data |
| 7 | **Migration date unifiée** — `UPDATE matches SET date=REPLACE(date,'-','')` (92k lignes) | ⭐ | S | Agent ops |
| 8 | **Étendre tennis-data tournois** — couvrir 250/500 manquants | ⭐⭐ | S | Agent data |
| 9 | **Accumuler market_snapshots** — T-24h/T-6h/T-1h automatiques | ⭐⭐ | S | Déjà partiel |
| 10 | **Backtest clutch → modèle** — si `backtest_clutch` > 52 % sur N>500 | ⭐⭐ | M | Agent ML |
| 11 | **ML prep dry-run** — `dataset_builder` avec rapport % NaN par feature | ⭐ | S | Agent ML |
| 12 | **Sportradar POC** — rankings + WTA stats si budget validé | ⭐⭐⭐ | L | Product |

**Légende effort :** S = <1 jour, M = 1–3 jours, L = >1 semaine.

---

## 8. Résultats correctifs (15 juillet 2026)

| Métrique | Avant | Après |
|----------|-------|-------|
| WTA joueurs serve non-neutre | 94.19% (3259/3460) | **94.34%** (3264/3460) |
| MCP matchs serve/return enrichis | BP seulement (COALESCE bloqué par 0.5) | **922** matchs avec serve/return réels |
| Matchs avec w_rank/l_rank | 0 | **12 094** (tennis-data 2020–2026) |
| Joueurs classés (`player_rankings`) | 0 | **4 197** (live-tennis + tennis-data + memory) |
| Couverture ranking actifs confiants (n≥5) | ~0% | **70.3%** officiel ; **100%** avec Elo fallback |
| `bet_history` rows | 0 | **94** (backfill clv_log) |

**Commandes :**
```bash
python run.py data-quality
python run.py ingest-rankings --years 2020 2021 2022 2023 2024 2025 2026
python -m bot.mcp_feeder  # ou scheduler job_mcp_backfill
python run.py backfill-bet-history --limit 5000
python -m pytest tests/ -q -k "mcp or ranking or bet_history"
```

**Commits :** WTA MCP fix → rankings ingestion → bet_history backfill (séparés).

---

## 7. Inventaire technique par module

### `bot/datasource.py`
- Parse CSV Sackmann : serve, return1/2, surface, margin, BP, TB (via score).
- `fetch_matches()` / `fetch_challengers()` : téléchargement multi-années ATP/WTA.
- `surface_backfill()` / `clutch_backfill()` : rétro-remplissage DB depuis CSV.
- `probe_live()` : test Sofascore (fallback self-healing).

### `bot/sackmann_feeder.py`
- Orchestrateur ingestion bulk Sackmann → `learner.train()` → `db.archive_matches()`.
- **Statut :** repos GitHub 404 depuis ~juin 2026 ; archive DB intacte.

### `bot/tennisdata_feeder.py`
- Source : `tennis-data.co.uk` (ATP + WTA, 2020–2026).
- Apporte : ranking match, cotes B365/Pinnacle/Max/Avg, ELO rebuild.
- **Limite :** pas de stats serve/return ; profils neutres 0.5.

### `bot/mantennisdata_feeder.py`
- Source : `github.com/msolonskyi/ManTennisData` (ATP only).
- Cutoff `20260518` — évite doublons avec archive Sackmann.
- Apporte : serve/return/BP/TB complets pour matchs ATP récents.

### `bot/mcp_feeder.py`
- Source : `tennis_MatchChartingProject` (WTA crowdsourcé).
- Mode : enrichissement non destructif (`db.backfill_match_stats_bulk`).
- **Limite :** ~200 matchs WTA/an ; serve/return MCP non appliqués (bug COALESCE).

### `bot/odds_api.py`
- Pool clés rotatif, cache TTL, line shopping Bet365/Betfair.
- Endpoints : events, odds ML, spread/totals live.
- Rate limit : 100 req/h/clé, bascule automatique.

### Schéma DB pertinent (`bot/db.py`)

**`matches`** — cœur historique :
```
id, date, tour, winner, loser,
w_serve, w_return1, w_return2, l_serve, l_return1, l_return2,
surface, margin,
w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced, w_tb_won, l_tb_won
```

**`historical_odds`** — cotes tennis-data :
```
match_id, b365w/l, psw/l, maxw/l, avgw/l
```

**`market_snapshots`** — line movement / CLV :
```
event_key, ts, odds_home, odds_away, hours_ahead
```

**`players`** — profils EMA :
```
name, tour, serve, return1, return2, recent, rating, rank (optionnel)
```

---

## 8. Références

- Audit système complet : [`docs/AUDIT.md`](AUDIT.md)
- Incident Sackmann + remediation : `docs/AUDIT.md` §5.1bis, `bot/config.py` L54–59
- Signaux informatifs Phase 12 : `bot/intelligence_layer.py`, `bot/match_intelligence.py`
- Garde-fou backtest : `bot/signal_backtest.py`
- Features ML planifiées : `bot/ml_prep/features.py`

---

*Document produit dans le cadre de TennisBoss Phase 12 — Agent 4. Aucune modification de code ; audit read-only.*
