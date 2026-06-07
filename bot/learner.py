"""Self-learning : régression logistique en ligne sur des matchs réels.

Pour chaque match (dans l'ordre chronologique) :
  1. on récupère les profils des 2 joueurs AVANT le match (pas de fuite),
  2. on prédit le vainqueur,
  3. on compare à la réalité -> met à jour les poids (descente de gradient),
  4. on met à jour les profils des joueurs avec la perf observée.

Le bot s'améliore donc à mesure qu'il voit des matchs.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List

from . import config, features, predictor
from .log import log


def _train_one(mem: Dict[str, Any], match: Dict, lr: float, reg: float, alpha: float):
    weights = mem["weights"]
    name_w, name_l = match["winner_name"], match["loser_name"]

    # Profils AVANT le match (vecteurs de features) -> pas de fuite.
    fw = features.feature_vector(features.get_profile(mem, name_w))
    fl = features.feature_vector(features.get_profile(mem, name_l))

    # IMPORTANT : on randomise l'ordre A/B, sinon "joueur 1" encoderait toujours
    # le vainqueur et le modèle tricherait via le biais (précision artificielle).
    if random.random() < 0.5:
        fa, fb, label = fw, fl, 1.0   # A = vainqueur réel
    else:
        fa, fb, label = fl, fw, 0.0   # A = perdant réel

    # Prédiction : proba que A gagne.
    p_a, _, _, _ = predictor.probability(weights, mem["bias"], fa, fb)
    correct = (p_a >= 0.5) == (label == 1.0)

    # --- Mise à jour des poids (gradient de la log-loss) -------------------
    err = label - p_a
    for k in config.FEATURE_ORDER:
        grad = err * (fa[k] - fb[k]) - reg * weights[k]
        weights[k] += lr * grad
    mem["bias"] += lr * err

    # --- Mise à jour des profils joueurs avec la perf réelle du match ------
    features.update_profile(mem, name_w, match["winner"], won=True, alpha=alpha)
    features.update_profile(mem, name_l, match["loser"], won=False, alpha=alpha)

    # --- Métriques --------------------------------------------------------
    m = mem["metrics"]
    m["predictions"] += 1
    if correct:
        m["correct"] += 1
    p_label = p_a if label == 1.0 else (1.0 - p_a)
    m["last_loss"] = round(-_safe_log(p_label), 4)
    return correct


def _safe_log(p: float) -> float:
    import math

    return math.log(max(1e-9, min(1.0, p)))


def train(mem: Dict[str, Any], matches: List[Dict], cfg: Dict[str, Any]) -> Dict:
    """Apprend sur tous les matchs non encore vus. Renvoie un petit rapport."""
    lr = cfg["learning_rate"]
    reg = cfg["l2_reg"]
    alpha = cfg["ema_alpha"]
    processed = set(mem["processed"])

    new_count = 0
    correct = 0
    for match in matches:
        if match["id"] in processed:
            continue
        ok = _train_one(mem, match, lr, reg, alpha)
        processed.add(match["id"])
        new_count += 1
        correct += 1 if ok else 0

    # On borne la liste des ids traités pour ne pas faire enfler la mémoire.
    mem["processed"] = list(processed)[-200000:]

    m = mem["metrics"]
    if m["predictions"]:
        m["accuracy"] = round(m["correct"] / m["predictions"], 4)

    report = {
        "new_matches": new_count,
        "batch_accuracy": round(correct / new_count, 4) if new_count else None,
        "global_accuracy": m["accuracy"],
        "players_known": len(mem["players"]),
    }
    if new_count:
        log(
            f"Apprentissage : +{new_count} matchs | précision lot="
            f"{report['batch_accuracy']} | précision globale={m['accuracy']} | "
            f"{report['players_known']} joueurs connus"
        )
    else:
        log("Apprentissage : aucun nouveau match à traiter.")
    return report
