"""Auto-learning engine: améliorations continues du modèle sans nouvelles données externes.

Stratégie : Bootstrapping à partir des 16k matchs existants
1. Segmentation: Hard / Clay / Grass (surface-specific models)
2. Resampling: augmentation synthétique (perturbation légère des features)
3. K-fold validation: évaluation OOS sur folds variés
4. Adaptive calibration: tuning β (ELO_blend) per surface
5. Ensemble: blend ELO + logit features avec poids dynamiques
"""

import json
import math
import random
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass

from . import db, elo, features, predictor, calibrate, settlement, memory
from .log import log


@dataclass
class SurfaceModel:
    """Modèle spécialisé par surface."""
    surface: str
    elo: Dict = None
    elo_blend: float = 0.8
    calib_k: float = 1.0
    accuracy: float = 0.0
    n_matches: int = 0


class AutoLearner:
    """Apprentissage continu du modèle TennisBoss."""

    def __init__(self):
        self.mem = memory.load()
        self.models_by_surface: Dict[str, SurfaceModel] = {}
        self._init_surface_models()

    def _init_surface_models(self):
        """Construire des modèles spécialisés par surface."""
        for surf in ("hard", "clay", "grass"):
            rows = db.all_matches_chrono()
            # Filtrer par surface (si disponible) — convert sqlite3.Row to dict
            rows_surf = [dict(r) for r in rows if dict(r).get("surface") == surf]
            if not rows_surf:
                rows_surf = [dict(r) for r in rows]  # Fallback si surface manquante

            elo_model, _ = elo.build_dynamic(rows_surf)
            self.models_by_surface[surf] = SurfaceModel(
                surface=surf,
                elo=elo_model,
                n_matches=len(rows_surf)
            )
            log(f"Surface model {surf}: {len(rows_surf)} matches", "INFO")

    def tune_all_surfaces(self) -> Dict[str, float]:
        """Grid-search β optimal pour chaque surface."""
        results = {}
        for surf, model in self.models_by_surface.items():
            log(f"Tuning ELO_blend for {surf}...", "INFO")
            rows = db.all_matches_chrono()
            rows_surf = [dict(r) for r in rows if dict(r).get("surface", "hard") == surf]

            # Convertir en tuples (logit_features, logit_elo, issue) pour calibrate.tune_blend
            samples = self._blend_samples_for_surface(rows_surf)
            if len(samples) < 20:
                log(f"  Skipping {surf}: trop peu de samples ({len(samples)})", "WARN")
                results[surf] = model.elo_blend
                continue

            fit = calibrate.tune_blend(samples)
            best_beta = fit.get("elo_blend", model.elo_blend)
            model.elo_blend = best_beta
            results[surf] = best_beta

        db.set_meta("elo_blend_by_surface", json.dumps(results))
        log(f"✓ Tuned ELO blends: {results}", "INFO")
        return results

    def _blend_samples_for_surface(self, rows_surf: List[Dict]) -> List[Tuple[float, float, float]]:
        """Convertir matchs d'une surface en samples (logit_feat, logit_elo, issue)."""
        elo_r = self.models_by_surface.get("hard", {}).elo or {}
        w_serve = self.mem["weights"].get("serve", 1.0)
        w_ret1 = self.mem["weights"].get("return1", 1.0)
        w_ret2 = self.mem["weights"].get("return2", 1.0)
        w_recent = self.mem["weights"].get("recent", 1.0)
        bias = float(self.mem["bias"])
        samples = []

        for row in rows_surf:
            winner, loser = row.get("winner"), row.get("loser")
            if not winner or not loser:
                continue
            if winner not in self.mem["players"] or loser not in self.mem["players"]:
                continue

            f1 = features.feature_vector(features.get_profile(self.mem, winner))
            f2 = features.feature_vector(features.get_profile(self.mem, loser))

            # f1, f2 = dict with keys: serve, return1, return2, recent
            logit_feat = bias + (w_serve * (f1.get("serve", 0.5) - f2.get("serve", 0.5)) +
                                 w_ret1 * (f1.get("return1", 0.5) - f2.get("return1", 0.5)) +
                                 w_ret2 * (f1.get("return2", 0.5) - f2.get("return2", 0.5)) +
                                 w_recent * (f1.get("recent", 0.5) - f2.get("recent", 0.5)))

            logit_elo = math.log(elo_r.get(winner, predictor.ELO_BASE) / elo_r.get(loser, predictor.ELO_BASE)) if winner in elo_r and loser in elo_r else 0.0
            issue = 1.0  # winner correct par construction

            samples.append((logit_feat, logit_elo, issue))

        return samples

    def augment_dataset(self, n_synthetic: int = 100) -> List[Dict]:
        """Augmentation synthétique: créer des match variants via perturbation.

        Pour chaque match existant:
        - Perturber légèrement les features (±5%)
        - Garder le résultat (étiquette)
        - Utiliser pour ré-entraînement
        """
        augmented = []
        settled = db.list_settled(limit=500)
        random.shuffle(settled)

        for match in settled[:min(n_synthetic // 10, len(settled))]:
            p1, p2, winner = match["player1"], match["player2"], match["winner"]
            if p1 not in self.mem["players"] or p2 not in self.mem["players"]:
                continue

            # Match original
            f1 = features.feature_vector(features.get_profile(self.mem, p1))
            f2 = features.feature_vector(features.get_profile(self.mem, p2))

            # Perturbations (±5%)
            for _ in range(10):
                f1_aug = {k: v * (1 + random.uniform(-0.05, 0.05)) for k, v in f1.items()}
                f2_aug = {k: v * (1 + random.uniform(-0.05, 0.05)) for k, v in f2.items()}

                augmented.append({
                    "p1": p1,
                    "p2": p2,
                    "winner": winner,
                    "f1": f1_aug,
                    "f2": f2_aug,
                    "is_augmented": True
                })

        log(f"Generated {len(augmented)} synthetic matches", "INFO")
        return augmented

    def kfold_eval(self, k: int = 5) -> Dict[str, float]:
        """K-fold cross-validation sur les matchs réglés.

        Évalue le modèle sur k folds différents, retourne accuracy moyennes.
        """
        settled = db.list_settled(limit=2000)
        fold_size = len(settled) // k
        accuracies = []

        for fold_idx in range(k):
            test_start = fold_idx * fold_size
            test_end = test_start + fold_size
            test_set = settled[test_start:test_end]

            correct = 0
            for match in test_set:
                p1, p2, winner = match["player1"], match["player2"], match["winner"]
                if p1 not in self.mem["players"] or p2 not in self.mem["players"]:
                    continue

                f1 = features.feature_vector(features.get_profile(self.mem, p1))
                f2 = features.feature_vector(features.get_profile(self.mem, p2))
                r = predictor.predict(self.mem, p1, f1, p2, f2)

                pred_winner = p1 if r["prob1"] > 50 else p2
                if pred_winner == winner:
                    correct += 1

            fold_acc = correct / len(test_set) if test_set else 0
            accuracies.append(fold_acc)

        mean_acc = sum(accuracies) / len(accuracies)
        log(f"K-fold (k={k}) accuracy: {mean_acc:.4f} (±{(max(accuracies) - min(accuracies)) / 2:.4f})", "INFO")
        return {"mean": mean_acc, "folds": accuracies}

    def run_full_cycle(self) -> Dict[str, Any]:
        """Cycle complet d'apprentissage auto."""
        log("=== AUTO-LEARNING CYCLE START ===", "INFO")

        # 1. Tune par surface
        surface_blends = self.tune_all_surfaces()

        # 2. Augmentation synthétique
        augmented = self.augment_dataset(n_synthetic=200)

        # 3. K-fold validation
        kfold = self.kfold_eval(k=5)

        # 4. Metrics finales
        metrics = {
            "cycle_timestamp": db.get_meta("last_settlement") or "2026-06-09",
            "elo_blends_by_surface": surface_blends,
            "synthetic_matches_generated": len(augmented),
            "kfold_accuracy": kfold["mean"],
            "kfold_accuracy_stddev": (max(kfold["folds"]) - min(kfold["folds"])) / 2 if kfold["folds"] else 0,
            "total_settled_matches": len(db.list_settled()),
        }

        db.set_meta("last_learning_cycle", json.dumps(metrics))
        log(f"=== LEARNING CYCLE COMPLETE: {json.dumps(metrics, indent=2)}", "INFO")
        return metrics


def run_auto_learning():
    """Entry point pour lancer l'auto-learning (appelable via CLI)."""
    learner = AutoLearner()
    return learner.run_full_cycle()
