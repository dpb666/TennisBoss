"""Backtest : évaluation HORS-ÉCHANTILLON du modèle, archivée en base.

Principe (sans fuite de données) :
  1. on trie les matchs chronologiquement ;
  2. on apprend les poids sur la 1re partie (entraînement) ;
  3. on GÈLE les poids et on évalue sur la 2e partie (test), match après match,
     en ne mettant à jour que les profils joueurs et les notes ELO.

Le backtest tourne sur un état neuf en mémoire : il ne touche PAS au modèle
de production (state/memory.json). Chaque campagne est enregistrée dans la
table `backtests` (archive).
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List

from . import config, db, elo as elo_mod, features, memory, predictor
from .learner import _train_one
from .log import log


def _safe_log(p: float) -> float:
    return math.log(max(1e-9, min(1.0, p)))


def _build_elo(matches: List[Dict]) -> tuple:
    """Construit ELO global et par surface avec K dynamique + dominance."""
    ratings: Dict[str, float] = {}
    n_played: Dict[str, int] = {}
    surf_ratings: Dict[str, Dict[str, float]] = defaultdict(dict)
    surf_n: Dict[str, Dict[str, int]] = defaultdict(dict)
    for m in matches:
        mult = elo_mod.mult_from_margin(m.get("margin") or 0)
        elo_mod.update_dynamic(ratings, n_played, m["winner_name"], m["loser_name"], mult=mult)
        surf = (m.get("surface") or "").lower()
        if surf in ("hard", "clay", "grass"):
            elo_mod.update_dynamic(surf_ratings[surf], surf_n[surf],
                                   m["winner_name"], m["loser_name"], mult=mult)
    return ratings, dict(surf_ratings), n_played, dict(surf_n)


def run(matches: List[Dict], cfg: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """Exécute un backtest et renvoie (et archive) le rapport de métriques."""
    if len(matches) < 50:
        raise ValueError("Pas assez de matchs pour un backtest fiable.")

    frac = cfg.get("backtest_test_fraction", 0.25)
    split = int(len(matches) * (1 - frac))
    train, test = matches[:split], matches[split:]

    mem = memory.default_memory()
    lr, reg, alpha = cfg["learning_rate"], cfg["l2_reg"], cfg["ema_alpha"]

    # --- Phase entraînement : poids + ELO ------------------------------------
    for m in train:
        _train_one(mem, m, lr, reg, alpha)
    weights, bias = mem["weights"], mem["bias"]

    # ELO construit sur les matchs d'entraînement (K dynamique + dominance)
    elo_ratings, elo_surface, elo_n, elo_surf_n = _build_elo(train)
    blend = predictor.ELO_BLEND

    # --- Phase test : poids GELÉS, ELO mis à jour match après match ----------
    n = correct = base_correct = 0
    correct_elo = 0
    logloss_sum = brier_sum = 0.0
    logloss_elo = brier_elo = 0.0

    for m in test:
        n1, n2 = m["winner_name"], m["loser_name"]
        surf = (m.get("surface") or "").lower()

        fw = features.feature_vector(features.get_profile(mem, n1))
        fl = features.feature_vector(features.get_profile(mem, n2))

        # ---- Modèle features seul
        p_win_feat, _, _, _ = predictor.probability(weights, bias, fw, fl)

        # ---- Modèle features + ELO
        s1 = predictor.weighted_score(weights, fw)
        s2 = predictor.weighted_score(weights, fl)
        base_logit = (elo_ratings.get(n1, elo_mod.BASE) -
                      elo_ratings.get(n2, elo_mod.BASE)) / 400.0 * math.log(10)
        if surf in elo_surface and elo_surface[surf]:
            surf_logit = (elo_surface[surf].get(n1, elo_mod.BASE) -
                          elo_surface[surf].get(n2, elo_mod.BASE)) / 400.0 * math.log(10)
            combined_logit = 0.5 * base_logit + 0.5 * surf_logit
        else:
            combined_logit = base_logit
        z_elo = (s1 - s2) + bias + blend * combined_logit
        p_win_elo = predictor._sigmoid(z_elo)

        n += 1
        correct += 1 if p_win_feat >= 0.5 else 0
        correct_elo += 1 if p_win_elo >= 0.5 else 0
        base_correct += 1 if fw["serve"] >= fl["serve"] else 0
        logloss_sum += -_safe_log(p_win_feat)
        brier_sum += (1.0 - p_win_feat) ** 2
        logloss_elo += -_safe_log(p_win_elo)
        brier_elo += (1.0 - p_win_elo) ** 2

        # Mise à jour profils et ELO live (K dynamique)
        tour = m.get("tour")
        features.update_profile(mem, n1, m["winner"], True, alpha, tour)
        features.update_profile(mem, n2, m["loser"], False, alpha, tour)
        mult = elo_mod.mult_from_margin(m.get("margin") or 0)
        elo_mod.update_dynamic(elo_ratings, elo_n, n1, n2, mult=mult)
        if surf in ("hard", "clay", "grass"):
            if surf not in elo_surface:
                elo_surface[surf] = {}
                elo_surf_n[surf] = {}
            elo_mod.update_dynamic(elo_surface[surf], elo_surf_n[surf], n1, n2, mult=mult)

    report = {
        "span": f"{matches[0]['date']}..{matches[-1]['date']}",
        "tours": ",".join(sorted({m.get("tour", "atp") for m in matches})),
        "n_train": len(train),
        "n_test": n,
        "accuracy": round(correct / n, 4) if n else None,
        "accuracy_elo": round(correct_elo / n, 4) if n else None,
        "logloss": round(logloss_sum / n, 4) if n else None,
        "logloss_elo": round(logloss_elo / n, 4) if n else None,
        "brier": round(brier_sum / n, 4) if n else None,
        "brier_elo": round(brier_elo / n, 4) if n else None,
        "baseline": round(base_correct / n, 4) if n else None,
        "notes": f"frac_test={frac}",
    }

    log(
        f"Backtest features : acc={report['accuracy']} logloss={report['logloss']} brier={report['brier']}"
    )
    log(
        f"Backtest +ELO     : acc={report['accuracy_elo']} logloss={report['logloss_elo']} brier={report['brier_elo']}"
    )
    log(
        f"Baseline (serve)  : {report['baseline']} | train={report['n_train']} test={report['n_test']}"
    )
    if persist:
        bid = db.save_backtest(report)
        report["id"] = bid
        log(f"Backtest archivé en base (id={bid}).")
    return report
