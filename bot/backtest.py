"""Backtest : évaluation HORS-ÉCHANTILLON du modèle, archivée en base.

Principe (sans fuite de données) :
  1. on trie les matchs chronologiquement ;
  2. on apprend les poids sur la 1re partie (entraînement) ;
  3. on GÈLE les poids et on évalue sur la 2e partie (test), match après match,
     en ne mettant à jour que les profils joueurs (jamais les poids).

Le backtest tourne sur un état neuf en mémoire : il ne touche PAS au modèle
de production (state/memory.json). Chaque campagne est enregistrée dans la
table `backtests` (archive).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from . import config, db, features, memory, predictor
from .learner import _train_one
from .log import log


def _safe_log(p: float) -> float:
    return math.log(max(1e-9, min(1.0, p)))


def run(matches: List[Dict], cfg: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """Exécute un backtest et renvoie (et archive) le rapport de métriques."""
    if len(matches) < 50:
        raise ValueError("Pas assez de matchs pour un backtest fiable.")

    frac = cfg.get("backtest_test_fraction", 0.25)
    split = int(len(matches) * (1 - frac))
    train, test = matches[:split], matches[split:]

    mem = memory.default_memory()
    lr, reg, alpha = cfg["learning_rate"], cfg["l2_reg"], cfg["ema_alpha"]

    # --- Phase entraînement : on apprend les poids ------------------------
    for m in train:
        _train_one(mem, m, lr, reg, alpha)
    weights, bias = mem["weights"], mem["bias"]

    # --- Phase test : poids GELÉS, on ne met à jour que les profils -------
    n = correct = base_correct = 0
    logloss_sum = brier_sum = 0.0
    for m in test:
        fw = features.feature_vector(features.get_profile(mem, m["winner_name"]))
        fl = features.feature_vector(features.get_profile(mem, m["loser_name"]))

        p_win, _, _, _ = predictor.probability(weights, bias, fw, fl)  # P(vainqueur réel)
        n += 1
        correct += 1 if p_win >= 0.5 else 0
        base_correct += 1 if fw["serve"] >= fl["serve"] else 0  # heuristique naïve
        logloss_sum += -_safe_log(p_win)
        brier_sum += (1.0 - p_win) ** 2

        tour = m.get("tour")
        features.update_profile(mem, m["winner_name"], m["winner"], True, alpha, tour)
        features.update_profile(mem, m["loser_name"], m["loser"], False, alpha, tour)

    report = {
        "span": f"{matches[0]['date']}..{matches[-1]['date']}",
        "tours": ",".join(sorted({m.get("tour", "atp") for m in matches})),
        "n_train": len(train),
        "n_test": n,
        "accuracy": round(correct / n, 4) if n else None,
        "logloss": round(logloss_sum / n, 4) if n else None,
        "brier": round(brier_sum / n, 4) if n else None,
        "baseline": round(base_correct / n, 4) if n else None,
        "notes": f"frac_test={frac}",
    }

    log(
        f"Backtest : acc={report['accuracy']} (baseline serve={report['baseline']}) | "
        f"logloss={report['logloss']} | brier={report['brier']} | "
        f"train={report['n_train']} test={report['n_test']}"
    )
    if persist:
        bid = db.save_backtest(report)
        report["id"] = bid
        log(f"Backtest archivé en base (id={bid}).")
    return report
