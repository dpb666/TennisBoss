# Logging Schema — reproductibilité complète des picks

**Date :** 15 juillet 2026
**Mission :** rendre TennisBoss entièrement mesurable — tout pick futur doit
contenir assez d'information pour reproduire n'importe quelle analyse sans
reconstruction a posteriori.
**Origine :** `docs/EVIDENCE_DRIVEN_OPTIMIZATION.md` §3 avait identifié que
5 des 10 champs requis étaient totalement absents du logging (tournament,
ranking_diff, model_prob_raw, calibration score, market_disagreement), 2
partiels (surface, market_prob) — ce document implémente le plan proposé
là-bas.

**Périmètre respecté :** `predictor.predict()` et la logique de décision
`/api/value` (seuils EV, filtres `is_value`, sélection du côté) sont
**inchangés**. Seuls les points de CAPTURE/LOGGING ont été étendus.

---

## 1. Schéma — `clv_log`

Table déjà existante (seed → closing → settlement), étendue de façon
**additive** (17 nouvelles colonnes, migration `ALTER TABLE` idempotente
dans `db.init()` — aucune perte de données, l'historique déjà loggé garde
ces colonnes à `NULL`).

| Colonne | Type | Rempli depuis | Champ requis de la mission |
|---|---|---|---|
| `pick_ts` | TEXT | déjà existant | timestamp |
| `tournament` | TEXT | nom du tournoi (`league.name`) au pick | tournament |
| `tournament_level` | TEXT | `config.tournament_level_from_name()` | tournament level |
| `surface` | TEXT | surface détectée au pick | surface |
| `player_rank` | REAL | `db.get_all_player_rankings()` | player ranking |
| `opponent_rank` | REAL | idem | opponent ranking |
| `ranking_diff` | REAL | `opponent_rank - player_rank` | ranking difference |
| `model_prob_raw` | REAL | proba AVANT calibration (`set_to_match_prob` brut) | model probability (raw) |
| `model_prob_calibrated` | REAL | proba APRÈS calibration, AVANT blend marché | calibrated probability |
| `market_prob` | REAL | proba marché utilisée dans le blend (`mw["home_prob"]`/`away_prob`) | implied market probability |
| `market_disagreement` | REAL | `abs(model_prob_calibrated - market_prob)` | market disagreement |
| `ev_pct` | REAL | EV% de la proba blendée (`best_ev_pct`) | expected value |
| `confidence` | REAL | déjà existant | confidence |
| `calib_k` | REAL | `_CALIB_K` en vigueur au pick | (composant de calibration version) |
| `market_blend_w` | REAL | `_MKT_W` en vigueur au pick | (composant de calibration version) |
| `calibration_version` | TEXT | `bot.versions.CALIBRATION_VERSION` | calibration version |
| `predictor_version` | TEXT | `bot.versions.PREDICTOR_VERSION` | predictor version |
| `feature_set_version` | TEXT | `bot.versions.FEATURE_SET_VERSION` | feature set version |
| `pick_odds` | REAL | déjà existant | market odds |
| `opening_odds` | REAL | `db.earliest_market_snapshot()` (si disponible) | opening odds (if available) |
| `closing_odds`/`closing_src`/`closing_ts` | REAL/TEXT/TEXT | déjà existant | closing odds (when available) |
| `result`/`clv_pct`/`beat_closing`/`pnl_flat`/`pnl_kelly`/`settled_ts` | — | déjà existant | settlement result |

**Note sur `calibration_version` :** la méthode de calibration (Platt vs
température vs poids de blend) est capturée par un label statique
(`bot/versions.py`, à bumper manuellement si la MÉTHODE change), tandis que
les VALEURS numériques réellement en vigueur (`calib_k`, `market_blend_w`,
qui changent souvent — auto-fittées) sont stockées séparément par pick.
Les deux sont nécessaires : le label dit "avec quel algorithme", les
valeurs disent "avec quel réglage exact".

---

## 2. Points de capture (pick creation paths)

Deux (et seulement deux) endroits créent un pick en production —
`clv.seed_pick()` y est appelé, désormais toujours avec `repro=...` :

1. **`api_value()`** (`bot/api.py`, endpoint `/api/value`, capture papier des
   picks qui passent `is_value`).
2. **`_value_scanner_loop()`** (`bot/api.py`, thread de fond, capture réelle
   des picks alertés).

Les deux appellent la nouvelle fonction partagée `_build_pick_repro()`
(`bot/api.py`) qui construit le dict `repro` à partir de valeurs **déjà
calculées** par la logique de décision existante (aucune requête
supplémentaire coûteuse dans la boucle chaude, sauf `get_all_player_rankings()`
et `earliest_market_snapshot()`, tous deux des lectures légères et déjà
mises en cache une fois par requête/cycle — pas par match).

`bot/clv.py::seed_pick()` et `bot/db.py::log_clv_pick()` acceptent le
paramètre `repro` en option (`None` par défaut) : **rétrocompatible**, tout
appelant existant (y compris les tests déjà écrits) continue de fonctionner
sans le fournir.

---

## 3. Validation — détection automatique des enregistrements incomplets

- `db.CLV_REPRO_FIELDS` : tuple des 13 champs requis évalués pour la
  complétude (`tournament` → `feature_set_version`, hors `opening_odds`/
  `closing_odds` qui sont légitimement absents avant qu'un mouvement de
  marché/la fin du match ne survienne — pas un défaut de capture).
- `db.validate_clv_pick_row(row)` → liste des champs manquants pour UNE
  ligne (liste vide = complet).
- `db.find_incomplete_clv_picks(limit=200, since=None)` → liste des picks
  incomplets avec leurs champs manquants, triés du plus récent au plus
  ancien.

---

## 4. Rapport de santé — complétude dans le temps

`db.clv_logging_completeness_report(bucket="week"|"day", limit_buckets=26)` :

- `n_total` / `n_complete` / `completeness_pct_overall`
- `by_period` : complétude % par semaine (ou jour), les `limit_buckets`
  périodes les plus récentes
- `missing_field_counts` : combien de picks manquent CHAQUE champ (identifie
  le champ le moins bien capturé)
- `most_incomplete_field`

Exposé en lecture seule via **`GET /api/logging/health`**
(`?bucket=week|day`, `?incomplete_limit=N`) — documenté dans l'OpenAPI
(`bot/openapi_spec.py`, tag `observability`). Ne modifie aucune décision de
pari, purement diagnostique.

---

## 5. Ce qui n'a PAS changé

- `predictor.predict()` : intact.
- `/api/value` : mêmes seuils (`min_ev`, `max_odds`, `min_confidence`),
  même sélection de côté (`ev1 >= ev2`), mêmes filtres (`_dead_zone`,
  `_overconfident`, `_learned_danger`, `_intel_blacklist`,
  `_intel_surf_danger`, `_high_conf_low_ev`). Seule la construction du dict
  `repro`, purement informative, a été ajoutée après la décision.
- La priorité de scan (`_tourn_rank`/`_tourn_rank_s`, définies localement
  dans `api_value()`/`_value_scanner_loop()`) n'a pas été touchée —
  `config.tournament_level_from_name()` est une fonction NEUVE et
  INDÉPENDANTE, utilisée uniquement pour le champ de logging
  `tournament_level`, pas pour trier ou filtrer les événements.

---

## 6. Limites assumées

- `player_rank`/`opponent_rank` viennent de `player_rankings` (classement
  officiel le plus récent connu) — pas un ranking Elo de fallback comme
  utilisé ailleurs (`ml_prep.features.load_rankings`), pour rester rapide
  dans la boucle de scan (le fallback Elo trie tout le dict Elo à chaque
  appel, trop coûteux à 90s/cycle). Résultat : `player_rank`/`opponent_rank`/
  `ranking_diff` restent `NULL` pour les joueurs sans classement officiel —
  visible et mesurable via le rapport de complétude, pas silencieusement
  approximé.
- `opening_odds` dépend de l'existence d'au moins un snapshot
  `market_snapshots` antérieur — reste `NULL` pour un pick sur un match tout
  juste apparu (premier snapshot = le pick lui-même). Non compté comme un
  défaut de capture (exclu de `CLV_REPRO_FIELDS`).
- Les picks déjà loggés AVANT ce déploiement gardent leurs nouvelles
  colonnes à `NULL` (visibles et comptés comme "incomplets" par le rapport
  de santé — c'est le comportement voulu, pas un bug : on ne peut pas
  reconstruire rétroactivement une information jamais capturée).

---

## 7. Tests

- `tests/test_clv.py` : rétrocompatibilité de `seed_pick()` sans `repro`,
  persistance complète avec `repro`.
- `tests/test_logging_schema.py` : validation de complétude, détection des
  picks incomplets, rapport de santé (DB vide, mixte, par période),
  `tournament_level_from_name()`, `earliest_market_snapshot()`.
- `tests/test_api_endpoints_db.py` : endpoint `/api/logging/health` (DB
  vide, pick incomplet détecté, paramètre invalide géré), `_build_pick_repro()`
  (calcul de `ranking_diff`/`market_disagreement`, cas rankings manquants).

498/498 tests passent (21 nouveaux, aucune régression).
