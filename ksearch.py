#!/usr/bin/env python3
"""Grid search K_FAST / K_STD / K_SLOW pour l'ELO dynamique TennisBoss.

Usage:
    python3 ksearch.py                    # ATP+WTA standard
    python3 ksearch.py --challengers      # ATP + Futures/ITF (recommandé)
    python3 ksearch.py --n-thresholds     # aussi cherche N_FAST / N_SLOW
"""
import argparse
import copy
import math
import sys
from collections import defaultdict
from itertools import product

from bot import config, datasource, features, memory, predictor
from bot import elo as elo_mod
from bot.learner import _train_one
from bot.log import log


# ---- helpers ---------------------------------------------------------------

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-500, min(500, x))))


def _safe_log(p: float) -> float:
    return math.log(max(1e-9, min(1.0, p)))


# ---- ELO build + eval ------------------------------------------------------

def _build_and_eval(train, test, weights, bias, mem_frozen,
                    k_fast, k_std, k_slow, n_fast, n_slow):
    """Construit ELO sur `train` avec les K donnés, évalue sur `test`.

    Les profils features sont gelés (mem_frozen) — seul l'ELO varie par combo.
    ELO mis à jour live sur le test pour être réaliste.
    """
    def dyn_k(n: int) -> float:
        if n < n_fast: return k_fast
        if n < n_slow: return k_std
        return k_slow

    def upd(ratings, n_played, winner, loser, mult=1.0):
        if not winner or not loser:
            return
        rw = ratings.get(winner, elo_mod.BASE)
        rl = ratings.get(loser,  elo_mod.BASE)
        ew = elo_mod.expected(rw, rl)
        kw = dyn_k(n_played.get(winner, 0))
        kl = dyn_k(n_played.get(loser,  0))
        delta = (1.0 - ew)
        ratings[winner] = rw + kw * mult * delta
        ratings[loser]  = rl - kl * mult * delta
        n_played[winner] = n_played.get(winner, 0) + 1
        n_played[loser]  = n_played.get(loser,  0) + 1

    # --- phase train ---
    ratings: dict = {}
    n_played: dict = {}
    surf_ratings: dict = defaultdict(dict)
    surf_n: dict = defaultdict(dict)

    for m in train:
        mult = elo_mod.mult_from_margin(m.get("margin") or 0)
        upd(ratings, n_played, m["winner_name"], m["loser_name"], mult)
        surf = (m.get("surface") or "").lower()
        if surf in ("hard", "clay", "grass"):
            upd(surf_ratings[surf], surf_n[surf],
                m["winner_name"], m["loser_name"], mult)

    # --- phase test (features gelées, ELO live) ---
    blend = predictor.ELO_BLEND
    n = correct = 0
    ll = br = 0.0

    for m in test:
        n1, n2 = m["winner_name"], m["loser_name"]
        surf = (m.get("surface") or "").lower()

        fw = features.feature_vector(features.get_profile(mem_frozen, n1))
        fl = features.feature_vector(features.get_profile(mem_frozen, n2))
        s1 = predictor.weighted_score(weights, fw)
        s2 = predictor.weighted_score(weights, fl)

        base_logit = ((ratings.get(n1, elo_mod.BASE) - ratings.get(n2, elo_mod.BASE))
                      / 400.0 * math.log(10))
        if surf in surf_ratings and surf_ratings[surf]:
            s_logit = ((surf_ratings[surf].get(n1, elo_mod.BASE) -
                        surf_ratings[surf].get(n2, elo_mod.BASE))
                       / 400.0 * math.log(10))
            combined = 0.5 * base_logit + 0.5 * s_logit
        else:
            combined = base_logit

        z = (s1 - s2) + bias + blend * combined
        p = _sigmoid(z)

        n += 1
        correct += 1 if p >= 0.5 else 0
        ll += -_safe_log(p)
        br += (1.0 - p) ** 2

        mult = elo_mod.mult_from_margin(m.get("margin") or 0)
        upd(ratings, n_played, n1, n2, mult)
        if surf in ("hard", "clay", "grass"):
            if surf not in surf_ratings:
                surf_ratings[surf] = {}
                surf_n[surf] = {}
            upd(surf_ratings[surf], surf_n[surf], n1, n2, mult)

    if n == 0:
        return None
    return {
        "acc":     round(correct / n, 4),
        "logloss": round(ll / n, 4),
        "brier":   round(br / n, 4),
    }


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Grid search K-factor ELO")
    ap.add_argument("--challengers", action="store_true",
                    help="Inclure ATP Futures/ITF")
    ap.add_argument("--tours", nargs="+", default=["atp"],
                    choices=["atp", "wta"])
    ap.add_argument("--years", nargs="+", type=int,
                    default=config.DEFAULT_CONFIG["years"])
    ap.add_argument("--frac-test", type=float, default=0.25,
                    help="Fraction test (défaut 0.25)")
    ap.add_argument("--n-thresholds", action="store_true",
                    help="Aussi chercher N_FAST / N_SLOW")
    args = ap.parse_args()

    log(f"Chargement des matchs ({args.years}, tours={args.tours}"
        f"{', +challengers' if args.challengers else ''})…")
    matches = datasource.fetch_matches(args.years, args.tours,
                                       include_challengers=args.challengers)
    if not matches:
        log("Aucune donnée. Abandon.", "ERROR"); sys.exit(1)

    frac = args.frac_test
    split = int(len(matches) * (1 - frac))
    train, test = matches[:split], matches[split:]
    log(f"{len(matches)} matchs | train={len(train)} test={len(test)}")

    # --- entraîner le modèle features (une seule fois) ---
    dc = config.DEFAULT_CONFIG
    cfg = {
        "learning_rate": dc["learning_rate"],
        "l2_reg":        dc["l2_reg"],
        "ema_alpha":     dc["ema_alpha"],
    }
    mem = memory.default_memory()
    for m in train:
        _train_one(mem, m, cfg["learning_rate"], cfg["l2_reg"], cfg["ema_alpha"])
    weights = mem["weights"]
    bias    = mem["bias"]
    mem_frozen = copy.deepcopy(mem)   # profils gelés pour tous les combos K
    log("Poids features appris. Démarrage grid search…")

    # --- grilles ---
    K_FAST_VALS = [16, 24, 32, 40, 48, 56, 64, 80]
    K_STD_VALS  = [10, 12, 16, 20, 24, 28, 32]
    K_SLOW_VALS = [6,  8,  10, 12, 16, 20, 24]

    if args.n_thresholds:
        N_FAST_VALS = [15, 20, 30, 50]
        N_SLOW_VALS = [80, 100, 150, 200]
    else:
        N_FAST_VALS = [30]
        N_SLOW_VALS = [150]

    combos = [
        (kf, ks, kl, nf, nl)
        for kf in K_FAST_VALS
        for ks in K_STD_VALS  if ks < kf          # strict décroissant
        for kl in K_SLOW_VALS if kl < ks
        for nf in N_FAST_VALS
        for nl in N_SLOW_VALS if nl > nf
    ]
    log(f"{len(combos)} combinaisons à tester…")

    # --- current baseline (K actuels) ---
    current = (elo_mod.K_FAST, elo_mod.K_STD, elo_mod.K_SLOW,
               elo_mod.N_FAST, elo_mod.N_SLOW)

    results = []
    for i, (kf, ks, kl, nf, nl) in enumerate(combos):
        r = _build_and_eval(train, test, weights, bias, mem_frozen,
                            kf, ks, kl, nf, nl)
        if r:
            r.update(k_fast=kf, k_std=ks, k_slow=kl, n_fast=nf, n_slow=nl)
            results.append(r)
        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(combos)} combos…")

    results.sort(key=lambda x: (-x["acc"], x["logloss"]))

    # --- affichage ---
    print(f"\n{'='*72}")
    print(f"{'GRID SEARCH K-FACTOR':^72}")
    print(f"  train={len(train)}  test={len(test)}")
    print(f"{'='*72}")
    print(f"{'K_FAST':>7} {'K_STD':>6} {'K_SLOW':>6} "
          f"{'N_FAST':>6} {'N_SLOW':>6} "
          f"{'ACC':>7} {'LOGLOSS':>8} {'BRIER':>7}  NOTE")
    print("-" * 72)

    seen_acc = set()
    for r in results[:25]:
        tag = ""
        combo = (r["k_fast"], r["k_std"], r["k_slow"],
                 r["n_fast"], r["n_slow"])
        if combo == current:
            tag = "← actuel"
        if combo == combos[results.index(r)] and r["acc"] not in seen_acc:
            pass
        seen_acc.add(r["acc"])
        print(f"  {r['k_fast']:>5}  {r['k_std']:>5}  {r['k_slow']:>5} "
              f" {r['n_fast']:>5}  {r['n_slow']:>5} "
              f" {r['acc']:>6.4f}  {r['logloss']:>7.4f}  {r['brier']:>6.4f}  {tag}")

    best = results[0]
    print(f"\n{'='*72}")
    print(f"MEILLEUR : K_FAST={best['k_fast']}  K_STD={best['k_std']}"
          f"  K_SLOW={best['k_slow']}"
          f"  N_FAST={best['n_fast']}  N_SLOW={best['n_slow']}")
    print(f"  acc={best['acc']}  logloss={best['logloss']}  brier={best['brier']}")

    # Valeurs courantes pour comparaison
    cur_r = next((r for r in results if (r["k_fast"], r["k_std"], r["k_slow"],
                                          r["n_fast"], r["n_slow"]) == current), None)
    if cur_r:
        print(f"ACTUEL  : K_FAST={current[0]}  K_STD={current[1]}"
              f"  K_SLOW={current[2]}  N_FAST={current[3]}  N_SLOW={current[4]}")
        print(f"  acc={cur_r['acc']}  logloss={cur_r['logloss']}  brier={cur_r['brier']}")
        delta = best["acc"] - cur_r["acc"]
        print(f"  → gain : {delta:+.4f} acc  ({delta*100:+.2f} pts)")
    print()


if __name__ == "__main__":
    main()
