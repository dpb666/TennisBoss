#!/usr/bin/env python3
"""Point d'entrée CLI de TennisBoss.

Commandes :
  python3 run.py start                 -> lance le bot autonome (boucle infinie)
  python3 run.py train [--years ...]   -> un seul cycle d'apprentissage
  python3 run.py predict "J1" "J2"     -> prédit le 1er set entre deux joueurs
  python3 run.py status                -> affiche l'état (poids, précision, top joueurs)
  python3 run.py reset                 -> efface l'état appris
"""
from __future__ import annotations

import argparse
import os
import sys

from bot import config, datasource, features, learner, memory, predictor
from bot.bootstrap import bootstrap
from bot.log import log


def cmd_start(_args) -> None:
    from bot.supervisor import run_forever

    run_forever()


def cmd_train(args) -> None:
    cfg = bootstrap()
    if args.years:
        cfg["years"] = args.years
    mem = memory.load()
    log(f"Cycle d'apprentissage unique sur les années : {cfg['years']}")
    matches = datasource.fetch_matches(cfg["years"])
    if not matches:
        log("Aucune donnée récupérée (réseau ?). Abandon.", "ERROR")
        sys.exit(1)
    learner.train(mem, matches, cfg)
    for y in cfg["years"]:
        if str(y) not in mem["datasets_loaded"]:
            mem["datasets_loaded"].append(str(y))
    memory.save(mem)
    log("Mémoire sauvegardée.")


def cmd_predict(args) -> None:
    bootstrap()
    mem = memory.load()
    if not mem["players"]:
        log("Aucun joueur appris. Lancez d'abord : python3 run.py train", "WARN")

    p1 = features.feature_vector(features.get_profile(mem, args.player1))
    p2 = features.feature_vector(features.get_profile(mem, args.player2))
    prof1 = features.get_profile(mem, args.player1)
    prof2 = features.get_profile(mem, args.player2)

    result = predictor.predict(mem, args.player1, p1, args.player2, p2)

    print("\n" + "=" * 56)
    print(f"  PRÉDICTION 1er SET")
    print("=" * 56)
    print(f"  {result['player1']:<28} {result['prob1']:>6.2f}%  "
          f"(matchs vus: {int(prof1.get('n', 0))})")
    print(f"  {result['player2']:<28} {result['prob2']:>6.2f}%  "
          f"(matchs vus: {int(prof2.get('n', 0))})")
    print("-" * 56)
    print(f"  {result['verdict']}")
    if not features.is_confident(prof1) or not features.is_confident(prof2):
        print("  ⚠️  Confiance faible (joueur(s) peu/pas connu(s)).")
    print("=" * 56 + "\n")


def cmd_status(_args) -> None:
    bootstrap()
    mem = memory.load()
    m = mem["metrics"]
    print("\n--- ÉTAT DU BOT ---")
    print(f"Battements de cœur : {mem['heartbeat'].get('count', 0)} "
          f"(dernier : {mem['heartbeat'].get('last_iso')})")
    print(f"Jeux de données chargés : {mem['datasets_loaded'] or '—'}")
    print(f"Joueurs connus : {len(mem['players'])}")
    print(f"Prédictions : {m['predictions']} | Précision globale : {m['accuracy']}")
    print(f"Dernière log-loss : {m['last_loss']}")
    print("\nPoids appris :")
    for k in config.FEATURE_ORDER:
        print(f"  {k:<8} : {mem['weights'][k]:+.4f}")
    print(f"  {'biais':<8} : {mem['bias']:+.4f}")

    if mem["players"]:
        top = sorted(
            mem["players"].items(),
            key=lambda kv: kv[1].get("serve", 0) + kv[1].get("recent", 0),
            reverse=True,
        )[:8]
        print("\nTop joueurs (serve + forme), parmi les bien connus :")
        shown = 0
        for name, prof in top:
            if prof.get("n", 0) >= config.DEFAULT_CONFIG["min_matches_confident"]:
                print(f"  {name:<26} serve={prof['serve']:.2f} "
                      f"forme={prof['recent']:.2f} n={prof['n']}")
                shown += 1
        if not shown:
            print("  (pas encore assez de matchs par joueur)")
    print()


def cmd_reset(_args) -> None:
    for path in (config.MEMORY_FILE, config.MEMORY_FILE + ".corrupt"):
        if os.path.exists(path):
            os.remove(path)
    log("État appris effacé (config conservée).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tennisboss", description="Bot tennis autonome")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("start", help="Lance le bot autonome").set_defaults(func=cmd_start)

    p_train = sub.add_parser("train", help="Un cycle d'apprentissage")
    p_train.add_argument("--years", nargs="+", type=int, help="Années ATP à charger")
    p_train.set_defaults(func=cmd_train)

    p_pred = sub.add_parser("predict", help="Prédire le 1er set")
    p_pred.add_argument("player1")
    p_pred.add_argument("player2")
    p_pred.set_defaults(func=cmd_predict)

    sub.add_parser("status", help="État du bot").set_defaults(func=cmd_status)
    sub.add_parser("reset", help="Effacer l'état appris").set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
