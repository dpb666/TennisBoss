# Evidence-Driven Optimization — validation walk-forward des 2 hypothèses ROI

**Date :** 15 juillet 2026
**Module :** `bot/decision_policy_backtest.py` (lecture seule, zéro écriture
DB, zéro modification de `predictor.predict()`/`api.py`)
**Tests :** `tests/test_decision_policy_backtest.py` (4 tests, mécanique)
**Production predictor :** gelé, inchangé.

---

## Résumé exécutif

**Hypothèse A (seuil EV) : NO-GO.** Aucun seuil testé (0/2/5/7.5/10/12.5%)
n'améliore le ROI de façon à la fois consistante entre les 2 blocs
chronologiques et statistiquement significative (IC bootstrap 95%). n=97
est trop petit — au-delà de 7.5% d'EV, il reste moins de 15 paris par
palier, largement insuffisant.

**Hypothèse B (amortissement du désaccord) : NO-GO.** Aucune stratégie
d'amortissement ne bat le poids fixe de même niveau de façon
CONSISTANTE (bien que 4/8 variantes soient statistiquement significatives
en agrégat, chacune échoue sur au moins 1 des 4 folds chronologiques — le
critère de consistance, requis explicitement par la mission, n'est pas
satisfait). Par ailleurs la question est aujourd'hui contre-factuelle :
la production tourne à `market_blend_w=0.00`, donc il n'y a actuellement
aucun poids modèle à amortir.

**Décision globale : NO-GO sur les deux hypothèses.** Aucun changement de
`predictor.predict()`, `/api/value` ou de la politique de décision n'est
recommandé sur cette base. La recommandation à plus fort ROI attendu est
l'audit de logging (§3) — pas un changement de modèle.

---

## 1. Hypothèse A — seuil d'EV minimum

**Méthode :** walk-forward sur les paris RÉELLEMENT décidés par la
production (`bet_history` × `clv_log`, n=97, seul jeu contenant une vraie
variation d'EV — l'edge de production vient du line-shopping entre
bookmakers, cf. `docs/MARKET_EFFICIENCY_AUDIT.md` §1). Découpage
chronologique en 2 blocs (n trop petit pour plus de folds). Le seuil est
appliqué rétrospectivement sur des décisions déjà prises (EV connue au
moment du pick, donc pas de fuite), mais chaque seuil plus élevé réduit
mécaniquement le n disponible.

| Seuil EV | n (couverture) | Win rate | ROI flat | IC bootstrap 95% ROI | Fold 1 (n / ROI) | Fold 2 (n / ROI) | Consistant | Significatif |
|---|---|---|---|---|---|---|---|---|
| 0% (référence) | 97 (100%) | 32.0% | −1.0% | [−29.5%, +30.3%] | 48 / −21.9% | 49 / +19.4% | Non | Non |
| 2% | 85 (87.6%) | 32.9% | +4.2% | [−29.6%, +41.5%] | 36 / −16.6% | 49 / +19.4% | Non | Non |
| 5% | 71 (73.2%) | 33.8% | +10.7% | [−25.8%, +50.7%] | 22 / −8.7% | 49 / +19.4% | Non | Non |
| 7.5% | 64 (66.0%) | 31.2% | −1.8% | [−38.6%, +40.5%] | 15 / **−71.1%** | 49 / +19.4% | Non | Non |
| 10% | 43 (44.3%) | 30.2% | +4.8% | [−45.0%, +56.8%] | 11 / −60.6% | 32 / +27.3% | Non | Non |
| 12.5% | 28 (28.9%) | 28.6% | +6.5% | [−53.3%, +74.9%] | 7 / −38.1% | 21 / +21.3% | Non | Non |

**Lecture :** le ROI global semble s'améliorer avec le seuil (−1.0% →
+10.7% à 5%), mais **chaque IC bootstrap inclut largement zéro** et
**aucun seuil n'est consistant entre les deux blocs** — le premier bloc
chronologique est systématiquement pire (voire catastrophique à 7.5-10%,
−60 à −71% sur n=7-15) que le second, pour TOUS les seuils. C'est le
signe d'un effet de PÉRIODE (le filtre Bet365/dead-zone du 2026-07-03 a
amélioré la qualité des picks après cette date, cf.
`docs/MARKET_EFFICIENCY_AUDIT.md` §3), pas d'un effet du seuil EV
lui-même — relever le seuil ne fait qu'amplifier le bruit d'un
échantillon déjà minuscule par bloc.

**Verdict : REJET.** Ne pas relever le seuil de production sur cette base.
À ré-évaluer avec n≥200-300 paris réglés post-filtre (2026-07-03), en
séparant proprement l'effet "seuil EV" de l'effet "avant/après filtre" —
actuellement les deux sont confondus dans ce petit échantillon.

---

## 2. Hypothèse B — amortissement de la confiance selon le désaccord marché

**Méthode :** jeu de données proxy plus large (`settled_matches` ×
`bet_log`, n=687, même source que `market_efficiency_audit`), walk-forward
en 4 blocs chronologiques. Testé à 4 poids modèle de base (0.05/0.10/0.15/
0.20 — la production réelle tourne à w=0.00, donc ce test est
**contre-factuel** : "si on donnait un jour du poids au modèle, un
amortissement selon le désaccord le rendrait-il plus sûr qu'un poids
fixe ?") × 3 stratégies : `flat` (référence, poids constant), `linear_decay`
(poids → 0 linéairement au-delà de 30pt de désaccord), `hard_cutoff`
(poids → 0 dès 20pt de désaccord, le seuil où `market_efficiency_audit`
a mesuré le pire Brier du modèle).

**Comparaison amortissement vs poids fixe de même niveau** (paired z-test
+ IC bootstrap 95% sur le delta de log-loss, sur les 4 folds) :

| Variante | Δ log-loss moyen | p | IC bootstrap 95% | Significatif | Consistant (4/4 folds) |
|---|---|---|---|---|---|
| w=0.05 linear_decay | +0.00113 | 0.127 | [−0.0003, +0.0025] | Non | Non |
| w=0.05 hard_cutoff | +0.00121 | 0.112 | [−0.0003, +0.0027] | Non | Non |
| w=0.10 linear_decay | +0.00278 | 0.060 | [−0.0001, +0.0056] | Non | Non |
| w=0.10 hard_cutoff | +0.00291 | 0.057 | [−0.0001, +0.0058] | Non | Non |
| **w=0.15 linear_decay** | **+0.00501** | **0.024** | **[+0.0007, +0.0093]** | **Oui** | **Non (2/4)** |
| **w=0.15 hard_cutoff** | **+0.00514** | **0.025** | **[+0.0007, +0.0095]** | **Oui** | **Non (2/4)** |
| **w=0.20 linear_decay** | **+0.00787** | **0.008** | **[+0.0021, +0.0136]** | **Oui** | **Non (2/4)** |
| **w=0.20 hard_cutoff** | **+0.00796** | **0.009** | **[+0.0020, +0.0138]** | **Oui** | **Non (2/4)** |

**Lecture :** aux poids de base plus élevés (0.15-0.20), l'amortissement
bat significativement le poids fixe **en moyenne agrégée sur les 4 folds**
(p<0.05, IC bootstrap excluant zéro). Mais décomposé fold par fold, la
dampened variant est **meilleure sur seulement 2 des 4 blocs
chronologiques** et pire sur les 2 autres — ce n'est PAS consistant, la
signification globale vient d'un ou deux folds à forte variance, pas d'un
effet stable dans le temps. Conformément à la règle explicite de la
mission ("rejeter tout changement qui ne montre pas une amélioration
CONSISTANTE"), ces variantes sont rejetées malgré leur significativité
agrégée.

Comparé au marché pur (référence de production actuelle, w=0), **aucune**
variante (fixe ou amortie) ne bat le marché de façon consistante — confirme
et prolonge le constat de `MARKET_EFFICIENCY_AUDIT.md` : donner du poids au
modèle, avec ou sans amortissement, ne bat pas le marché seul.

**Verdict : REJET.** L'amortissement du désaccord n'apporte pas de gain
robuste au-delà d'un choix de poids plus faible ; et de toute façon, à
poids de production actuel (w=0.00), la question ne se pose pas encore
concrètement.

---

## 3. Audit du pipeline de logging (obligatoire, indépendant du Go/No-Go)

**Constat :** `clv.seed_pick()` / `db.log_clv_pick()` (le point de capture
AU MOMENT DU PICK, avant résultat) n'enregistre aujourd'hui que : `event_key,
date, player1, player2, pick_side, pick_odds, pick_prob, confidence,
honeypot`. Vérification champ par champ de la checklist demandée :

| Champ requis | Statut actuel | Détail |
|---|---|---|
| tournament | ❌ absent | Ni `clv_log` ni `bet_history` ne stockent le nom/niveau de tournoi. Disponible en mémoire au moment du pick (`e.get("league")` dans `api.py`) mais jamais persisté. |
| surface | 🟡 partiel | `bet_history.surface` existe mais **36.1% des lignes sont vides** (`market_efficiency_audit`, segmentation §5) — calculée au pick (`_surf_pick`/`_ev_surf`) mais pas systématiquement propagée jusqu'à l'écriture ; un backfill partiel existe (`backfill_bet_history_surface_from_matches`) mais ne couvre pas tout. |
| ranking difference | ❌ absent | Aucune colonne. Recalculer après coup avec le classement ACTUEL serait trompeur (pas point-in-time) — nécessite capture au moment du pick. |
| implied market probability | 🟡 partiel | Récupérable approximativement via `1/pick_odds`, mais la vraie probabilité marché de référence utilisée pour le blend (`mw["home_prob"]`, potentiellement une source différente du bookmaker de la mise) n'est PAS stockée séparément. |
| model probability (brute, pré-blend) | ❌ absent | Seule la probabilité **blendée** (`pick_prob`) est stockée ; `pm1` (modèle seul, avant blend marché) n'est jamais persisté. |
| EV | 🟡 partiel | `value_picks.ev` existe mais seulement pour les picks passés par `is_value` ; `clv_log`/`bet_history` n'ont pas de colonne EV dédiée (reconstructible via `pick_prob × odds − 1`, mais ce n'est pas le calcul exact utilisé à la décision si le blend a changé depuis). |
| calibration score | ❌ absent | Aucune trace de `calib_k`/`a`/`b`/`market_blend_w` en vigueur au moment du pick. Sans ça, tout backtest futur doit deviner quelle calibration était active à quelle date (déjà une source d'ambiguïté dans cette analyse même, cf. `_MKT_W` historique inconnu). |
| confidence | ✅ présent | `bet_history.confidence` et `clv_log.confidence` déjà loggés. |
| market disagreement | ❌ absent | `\|p_modèle − p_marché\|` jamais calculé/stocké — a dû être reconstruit a posteriori dans cette analyse et dans `market_efficiency_audit`. |
| closing odds | ✅ présent | `clv_log.closing_odds`/`closing_src` déjà capturés (le pipeline CLV existant fait déjà bien ce point précis). |

**Constat transversal :** 5 des 10 champs requis sont totalement absents,
2 sont partiels, seuls confidence et closing odds sont pleinement couverts.
C'est la cause directe pour laquelle les 3 audits successifs de cette
session (clutch, market efficiency, cette validation) ont dû
**reconstruire a posteriori** des quantités qui auraient dû être
enregistrées au moment de la décision — avec toute l'incertitude que
cela implique (calibration active à l'époque inconnue, EV non stocké
distinctement, désaccord marché jamais mesuré).

### Plan d'implémentation (proposé, PAS exécuté — changement de schéma/code de production)

1. **Étendre `clv_log`** (le point de capture le plus précoce, `seed_pick()`)
   avec les colonnes : `tournament TEXT`, `ranking_diff REAL`,
   `market_prob REAL` (la probabilité marché de référence utilisée pour le
   blend, distincte de `pick_odds`), `model_prob_raw REAL` (avant blend),
   `ev_pct REAL`, `calib_k REAL`, `market_blend_w REAL`,
   `market_disagreement REAL` (= `abs(model_prob_raw − market_prob)`,
   calculée une fois à l'écriture, pas recalculée après coup).
2. **Point d'écriture :** `api_value()`/`_value_scanner_loop()` calculent
   déjà `pm1`, `mw["home_prob"]`, `best_ev_pct`, `_MKT_W`, `_surf_pick`,
   `r["confidence"]` — il s'agit de les faire transiter jusqu'à l'appel
   `clv.seed_pick()`/`db.log_clv_pick()` (actuellement seuls
   `pick_odds`/`pick_prob`/`confidence` y passent), plus un lookup
   ranking (déjà fait ailleurs via `ml_prep.features.load_rankings`) et le
   nom de tournoi (`e.get("league")`, déjà en mémoire).
3. **Migration DB :** `ALTER TABLE clv_log ADD COLUMN ...` (additive, dans
   `db.init()`, cohérent avec le style de migration déjà utilisé dans ce
   fichier) — aucune perte de données existantes, les nouvelles colonnes
   restent NULL pour l'historique déjà loggé.
4. **Corriger la complétude `surface`** dans `bet_history` : s'assurer que
   `_surf_pick`/`_ev_surf` (déjà calculé) est systématiquement transmis à
   `log_bet_history`/`sync_bet_history_on_settle`, pas seulement récupéré
   par un backfill partiel après coup.

**Mise à jour 2026-07-15 : ce plan a été implémenté** (mission "Data
Observability Engineer" distincte, avec accord explicite séparé) — voir
**`docs/LOGGING_SCHEMA.md`** pour le détail complet (schéma, points de
capture, validation, rapport de santé `/api/logging/health`). Aucun
changement à `predictor.predict()` ni à la logique de décision
`/api/value` : uniquement les points de capture/logging.

---

## 4. Recommandation finale

| Item | Décision |
|---|---|
| Hypothèse A (seuil EV) | **NO-GO** — pas assez de données pour distinguer un effet de seuil d'un effet de période |
| Hypothèse B (amortissement désaccord) | **NO-GO** — pas de gain consistant ; question actuellement contre-factuelle (w=0) |
| `predictor.predict()` / `/api/value` | **Rester inchangés** |
| Logging pipeline | **GO** sur le plan d'implémentation (§3), à exécuter séparément après accord explicite — c'est le changement à plus fort ROI attendu, car il ne modifie aucune décision de pari mais rend TOUTE future analyse (y compris une ré-évaluation des hypothèses A et B) beaucoup plus fiable et rapide à mener. |

**Go/No-Go global : NO-GO sur les changements de politique de décision.
GO sur l'instrumentation du logging (implémentation séparée, hors de cette
mission).** Aucune ligne de `predictor.predict()`, `api.py` (logique de
décision) ou de la politique de blend n'a été modifiée par cette
validation.
