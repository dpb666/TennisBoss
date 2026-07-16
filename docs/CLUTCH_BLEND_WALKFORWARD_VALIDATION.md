# Validation walk-forward du blend clutch — rapport complet

**Date :** 15 juillet 2026
**Fonction :** `bot/signal_backtest.py::backtest_clutch_blend_walkforward()`
**Tests :** `tests/test_signal_backtest.py` (9 nouveaux tests, `TestBacktestClutchBlendWalkforward` + helpers)
**Décision par défaut :** rejeter sauf preuve claire — appliquée ici.

---

## Contexte

`backtest_clutch_vs_elo()` (commit `a561d70`) avait établi qu'un résidu du
signal clutch (BP sauvées) survit à un contrôle ELO : 53.0% de réussite sur
les matchs à ELO proche (n=1357, p≈0.028) — réel mais modeste, et **pas**
encore une preuve qu'il améliore une prédiction déjà calibrée. Ce rapport
répond à la question suivante, posée explicitement par l'utilisateur :
*est-ce qu'ajouter ce signal (en blend logit faible) au predictor de
production réduit la log-loss/Brier/ECE hors-échantillon, de façon
consistante dans le temps et statistiquement significative ?*

**Aucune modification de `predictor.predict()`, `/api/value` ou toute
logique de production n'a été faite.** Cette analyse tourne entièrement en
lecture seule sur une copie en mémoire de l'état (poids/biais/elo_blend
gelés, chargés depuis `memory.json`) — zéro écriture.

---

## Méthodologie

1. **Walk-forward strict, découpage chronologique en 5 blocs** (pas de
   shuffle, pas de k-fold aléatoire) sur l'intégralité de la table
   `matches` (94 696 matchs, historique ATP+WTA complet).
2. Le **bloc 0 sert de warm-up** (accumulation initiale des profils EMA,
   de l'ELO walk-forward et des taux de BP sauvées) — **jamais évalué**.
   Les 4 blocs suivants sont évalués (75 757 matchs au total), chacun avec
   un état reconstruit **uniquement** à partir des matchs strictement
   antérieurs (aucune fuite future — même discipline que
   `backtest_form_signal`/`backtest_clutch_vs_elo`).
3. **Baseline** = predictor de production tel quel : score pondéré
   (poids/biais actuels de `memory.json`) + `elo_logit()` (code de
   production, réutilisé tel quel — pas réimplémenté), rejoué en
   walk-forward. *Limite assumée* : l'ELO répliqué ici est global+surface
   uniquement (pas le blend "forme récente 180j" de la prod complète) —
   documenté dans le docstring. La comparaison **relative** (avec/sans
   clutch) reste valide car les deux variantes partagent rigoureusement
   ce même baseline.
4. **Variante blend** = baseline + `poids × (logit(taux_BP_p1) −
   logit(taux_BP_p2))`, testé à 4 poids : **5%, 10%, 15%, 20%**. Quand
   l'historique BP est insuffisant pour l'un des deux joueurs, la variante
   est **strictement identique** au baseline pour ce match (comparaison
   appariée, jamais pénalisée par un manque de données).
5. Chaque variante évaluée sur l'**ensemble identique** de matchs par fold
   que le baseline (comparaison appariée point par point).

---

## Métriques calculées

- **Log Loss** (globale + par fold, pour juger la consistance temporelle)
- **Brier Score**
- **ECE** (Expected Calibration Error, 10 bins de largeur égale)
- **Courbe de fiabilité** (mean_pred vs mean_actual par bin)
- **Distribution de confiance** (`|p−0.5|×2`, en 5 buckets)
- **Test apparié** (z-test sur les diffs de log-loss match par match,
  approximation normale — cohérent avec `_proportion_ztest` déjà utilisé
  dans `backtest_clutch_vs_elo`)
- **IC bootstrap 95%** (2000 ré-échantillonnages, stdlib `random` seedé,
  sans scipy/numpy — cohérent avec le reste du projet)
- **ROI** : **non évaluable** — `matches` (l'historique utilisé, seul
  assez volumineux pour un walk-forward fiable) ne contient pas de cotes
  de marché ; `settled_matches` en contient mais n=94 est bien trop petit
  pour ce test. Documenté comme limite dans le code (`note_roi`).

---

## Résultats (données réelles, 15 juillet 2026)

**Baseline (predictor de production, sans clutch)**

| Métrique | Valeur |
|---|---|
| n évalués (hors warm-up) | 75 757 |
| Log Loss | 0.6541 |
| Log Loss par fold | 0.6757 / 0.6642 / 0.6287 / 0.6477 |
| Brier | 0.2277 |
| ECE | 0.0728 |

**Variantes blend clutch**

| Poids | Log Loss | Δ moyen vs baseline | z (apparié) | p | IC bootstrap 95% | Consistant (tous folds) | Significatif |
|---|---|---|---|---|---|---|---|
| 5%  | 0.6541 | −0.00001 | −0.259 | 0.796 | [−0.00004, 0.00003] | Non | Non |
| 10% | 0.6541 | −0.00002 | −0.751 | 0.453 | [−0.00009, 0.00004] | Non | Non |
| 15% | 0.6541 | −0.00006 | −1.243 | 0.214 | [−0.00016, 0.00004] | Non | Non |
| 20% | 0.6542 | −0.00011 | −1.733 | 0.083 | [−0.00024, 0.00002] | Non | Non |

(Δ moyen = logloss_baseline − logloss_variant ; **négatif** = le blend est
**légèrement pire**, pas meilleur.)

23 965 des 75 757 matchs évalués (31.6%) avaient un historique BP suffisant
des deux côtés pour que le blend s'exprime réellement ; les autres sont
identiques au baseline par construction.

**Observation clé :** plus le poids de blend augmente, plus la log-loss se
**dégrade** légèrement (tendance monotone 5%→20%, toutes négatives) — c'est
la signature attendue d'un signal sans valeur ajoutée nette une fois
qu'on est déjà calibré sur l'ELO : le résidu statistiquement significatif
trouvé par `backtest_clutch_vs_elo()` (comparaison brute de taux de
victoire) ne se traduit **pas** en gain de log-loss une fois combiné au
reste du modèle — le bruit qu'il ajoute au logit dépasse le signal qu'il
apporte.

---

## Décision

## **REJET**

Aucun des 4 poids testés n'améliore la log-loss de façon consistante sur
tous les folds (0/4 folds à chaque poids) ni statistiquement significative
(tous p > 0.08, tous les IC bootstrap incluent zéro). Le Brier et l'ECE
n'évoluent pas de façon notable non plus. Conforme à la règle du projet —
*"aucun signal n'entre dans predictor.predict() sans backtest walk-forward"*
— et à la consigne de cette validation (rejet par défaut sauf preuve
claire).

Le résidu identifié par `backtest_clutch_vs_elo()` est réel (au sens
statistique, sur une comparaison brute de taux de victoire) mais **trop
faible et trop bruité pour améliorer une prédiction déjà calibrée** une
fois combiné à l'ELO et aux features existantes. Ne pas intégrer, même en
expérimental/feature-flaggé.

**Recommandation :** ne pas poursuivre l'intégration de ce signal sous sa
forme actuelle. Si le volume de données double ou triple (plus de matchs
avec stats BP disponibles), rejouer `backtest_clutch_blend_walkforward()`
périodiquement — mais ne rien changer en production sur la base des
résultats actuels.
