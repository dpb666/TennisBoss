#!/usr/bin/env python3
"""Peuple la base locale avec le memory.json (tous les joueurs appris + leurs stats).

Usage:
    python3 scripts/populate_db.py          # Remplit depuis memory.json
    python3 scripts/populate_db.py --dry    # Affiche ce qui serait ajouté (sans modifier)
"""
import json
import sys
import argparse
from pathlib import Path

# Ajoute le bot au PATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot import config, db, features, predictor


def load_memory() -> dict:
    """Charge le memory.json."""
    with open(config.MEMORY_FILE, 'r') as f:
        return json.load(f)


def populate_players(dry_run: bool = False) -> int:
    """
    Remplît la table `players` à partir de memory.json.
    Retourne le nombre de joueurs insérés ou mis à jour.
    """
    mem = load_memory()
    weights = mem["weights"]
    bias = mem.get("bias", 0.0)
    players = mem.get("players", {})

    if not players:
        print("❌ Aucun joueur trouvé dans memory.json")
        return 0

    import datetime as dt
    now = dt.datetime.now().isoformat(timespec="seconds")

    # Profil neutre pour calculer la proba de victoire "de base"
    neutral = {k: 0.5 for k in config.FEATURE_ORDER}

    rows_to_insert = []
    for name, prof in players.items():
        # Construit le vecteur de features du joueur
        feat = features.feature_vector(prof)

        # Calcule sa probabilité de victoire contre un joueur "neutre"
        win_prob, _, score, _ = predictor.probability(weights, bias, feat, neutral)

        row = (
            name,
            prof.get("tour", "atp"),
            int(prof.get("n", 0)),
            round(feat["serve"], 4),
            round(feat["return1"], 4),
            round(feat["return2"], 4),
            round(feat["recent"], 4),
            round(score, 4),
            round(win_prob, 4),
            now,
        )
        rows_to_insert.append(row)

    if dry_run:
        print(f"ℹ️  DRY RUN : {len(rows_to_insert)} joueurs seront injectés")
        for i, row in enumerate(rows_to_insert[:5]):
            print(f"   {i+1}. {row[0]:<30} | tour={row[1]} | n={row[2]} | win_prob={row[8]:.3f}")
        if len(rows_to_insert) > 5:
            print(f"   ... et {len(rows_to_insert) - 5} autres")
        return len(rows_to_insert)

    # Insère en base pour de vrai
    db.init()
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO players "
            "(name,tour,n,serve,return1,return2,recent,rating,win_prob,updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "tour=excluded.tour,n=excluded.n,serve=excluded.serve,"
            "return1=excluded.return1,return2=excluded.return2,recent=excluded.recent,"
            "rating=excluded.rating,win_prob=excluded.win_prob,updated=excluded.updated",
            rows_to_insert,
        )

    print(f"✅ Base peuplée : {len(rows_to_insert)} joueurs injectés")

    # Affiche un résumé par tour
    atp_count = sum(1 for r in rows_to_insert if r[1] == "atp")
    wta_count = sum(1 for r in rows_to_insert if r[1] == "wta")
    print(f"   ATP: {atp_count} joueurs")
    print(f"   WTA: {wta_count} joueurs")

    return len(rows_to_insert)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Peuple la base locale depuis memory.json")
    parser.add_argument("--dry", action="store_true", help="Mode test (n'insère rien)")
    args = parser.parse_args()

    try:
        count = populate_players(dry_run=args.dry)
        if count == 0:
            sys.exit(1)
    except Exception as e:
        print(f"❌ Erreur : {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
