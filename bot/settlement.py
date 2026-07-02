"""Settlement + métriques de calibration de TennisBoss.

- run_settlement : récupère les matchs terminés, les apparie aux joueurs connus,
  calcule la prédiction du modèle et enregistre le résultat (correct ou non).
- calibration_metrics : agrège les matchs réglés (précision, Brier, par tour,
  favoris vs serrés). Honnête : le ROI n'est pas calculé tant qu'on ne stocke pas
  les cotes de clôture (pas de données fiables -> None).

Tout est côté Python (backend), sans dépendance Android.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from . import clv, config, db, elo, features, live_api, odds_api, predictor


def run_settlement(mem: Dict[str, Any],
                   resolve: Callable[[str], Optional[str]],
                   days_back: int = 2) -> Dict[str, Any]:
    """Enregistre les matchs terminés récents avec la prédiction du modèle.

    Sources : API-Tennis (primaire) + odds-api.io /events?status=settled (secondaire).
    """
    results = live_api.fetch_results({"live_api_provider": "api-tennis"}, days_back)

    # Compléter avec les résultats odds-api.io (disponibles 24h après la fin du match)
    settled_odds = odds_api.fetch_settled_events()
    existing_keys = {r.get("event_key") for r in results}
    for e in settled_odds:
        eid = str(e.get("id") or "")
        if eid and eid not in existing_keys:
            home, away = e.get("home", ""), e.get("away", "")
            scores = e.get("scores") or {}
            home_s = scores.get("home", 0)
            away_s = scores.get("away", 0)
            winner = "p1" if home_s > away_s else ("p2" if away_s > home_s else None)
            if winner and home and away:
                results.append({
                    "event_key": f"odds_{eid}",
                    "player1": home, "player2": away,
                    "winner": winner,
                    "final_score": f"{home_s} - {away_s}",
                    "sets": [], "status": "finished",
                    "tournament": (e.get("league") or {}).get("name", "") if isinstance(e.get("league"), dict) else str(e.get("league") or ""), "round": "",
                    "date": e.get("date", ""), "tour": "atp", "is_doubles": False,
                    "finished": True,
                })
    added = 0
    for r in results:
        ek = r.get("event_key")
        if ek is None or r.get("winner") is None:
            continue
        if db.settled_exists(str(ek)):
            continue

        n1_raw, n2_raw = r["player1"], r["player2"]
        n1 = resolve(n1_raw) or n1_raw
        n2 = resolve(n2_raw) or n2_raw
        pred_fav: Optional[str] = None
        pred_prob1: Optional[float] = None
        correct: Optional[int] = None

        winner_name = n1 if r["winner"] == "p1" else n2
        # On tente la prédiction même si un joueur est inconnu (profil neutre).
        try:
            f1 = features.feature_vector(features.get_profile(mem, n1))
            f2 = features.feature_vector(features.get_profile(mem, n2))
            pr = predictor.predict(mem, n1, f1, n2, f2)
            # N'enregistrer la prédiction que si la confiance est suffisante
            if pr.get("confidence", 0.0) >= 0.20:
                pred_fav = pr["favorite"]
                pred_prob1 = round(predictor.set_to_match_prob(pr["prob1"] / 100.0) * 100, 1)
                if pred_fav is not None:
                    correct = 1 if pred_fav == winner_name else 0
        except Exception:
            pass

        if db.insert_settled({
            "event_key": str(ek), "date": r["date"], "tour": r["tour"],
            "tournament": r["tournament"],
            "player1": n1, "player2": n2,
            "winner": winner_name, "final_score": r["final_score"], "sets": r["sets"],
            "pred_favorite": pred_fav, "pred_prob1": pred_prob1, "correct": correct,
        }):
            added += 1
            # CLV : règle le pick (P&L flat + Kelly, CLV%) s'il existe.
            try:
                clv.settle(n1_raw, n2_raw, winner_name)
                if n1 != n1_raw or n2 != n2_raw:
                    clv.settle(n1, n2, winner_name)  # noms résolus
            except Exception:  # noqa: BLE001
                pass
            # Value picks : marque le résultat pour le suivi de ROI individuel.
            try:
                db.settle_value_pick(n1, n2, winner_name)
                if n1 != n1_raw or n2 != n2_raw:
                    db.settle_value_pick(n1_raw, n2_raw, winner_name)
            except Exception:  # noqa: BLE001
                pass
            # Apprentissage continu : ELO mis à jour, pondéré par la dominance.
            if "elo" in mem:
                mult = elo.dominance_mult(r["sets"], r["winner"])
                loser_name = n2 if r["winner"] == "p1" else n1
                elo.update(mem["elo"], winner_name, loser_name, mult=mult)
                # Mise à jour ELO récent (forme courte 180j) — toujours
                if "elo_recent" in mem:
                    elo.update(mem["elo_recent"], winner_name, loser_name, mult=mult)
                # Mise à jour ELO de surface si détectable depuis le tournoi
                surface = config.surface_from_league(r.get("tournament", ""))
                if surface and "elo_surface" in mem:
                    surf_ratings = mem["elo_surface"].setdefault(surface, {})
                    elo.update(surf_ratings, winner_name, loser_name, mult=mult)

    # Repair pass: settle value_picks whose match is already in settled_matches.
    # Needed when a value_pick is logged after the match was already settled.
    repaired = 0
    try:
        open_picks = db.list_value_picks_open()
        for pick in open_picks:
            p1, p2 = pick["player1"], pick["player2"]
            sm = db.get_settled_by_players(p1, p2)
            if sm and sm["winner"]:
                if db.settle_value_pick(p1, p2, sm["winner"]):
                    repaired += 1
                    try:
                        clv.settle(p1, p2, sm["winner"])
                    except Exception:  # noqa: BLE001
                        pass
    except Exception:  # noqa: BLE001
        pass

    return {"results_seen": len(results), "added": added, "repaired": repaired}


def _acc(rows: List[Any]) -> Optional[float]:
    judged = [r for r in rows if r["correct"] is not None]
    if not judged:
        return None
    return round(sum(r["correct"] for r in judged) / len(judged), 4)


def market_blend_samples(calib_k: float) -> List[tuple]:
    """Échantillons (p_modèle_calibrée, p_marché, issue) pour fit_market_blend.

    Jointure settled_matches × bet_log (même clé que le ROI). p_marché = 1/cote
    du favori captée au pick — légère surestimation (vig inclus, ~1-2 pts sur
    Betfair Exchange), négligeable pour régler un scalaire sur ~250 points.
    """
    from . import calibrate

    bets = {frozenset((b["player1"], b["player2"])): b for b in db.list_bets()}
    samples: List[tuple] = []
    for r in db.list_settled(limit=100000):
        if r["correct"] is None or r["pred_prob1"] is None:
            continue
        b = bets.get(frozenset((r["player1"], r["player2"])))
        if not b or not b["fav_odds"] or b["fav_odds"] <= 1.0:
            continue
        p1 = r["pred_prob1"] / 100.0
        p_model = p1 if b["favorite"] == r["player1"] else 1.0 - p1
        p_model = calibrate.calibrated_prob(p_model, calib_k)
        p_market = min(0.99, 1.0 / float(b["fav_odds"]))
        y = 1.0 if r["winner"] == b["favorite"] else 0.0
        samples.append((p_model, p_market, y))
    return samples


def calibration_metrics() -> Dict[str, Any]:
    """Agrège les matchs réglés : précision globale, par tour, favoris/serrés, Brier."""
    rows = db.list_settled(limit=100000)
    judged = [r for r in rows if r["correct"] is not None]
    n = len(judged)
    if n == 0:
        return {"n": 0, "accuracy": None, "roi": None, "brier": None,
                "atp_acc": None, "wta_acc": None, "fav_acc": None, "dog_acc": None,
                "note": "Aucun match réglé apparié à une prédiction pour le moment."}

    # Favori "clair" si la proba s'éloigne de 50 % de plus de 10 points.
    clear = [r for r in judged if r["pred_prob1"] is not None
             and abs(r["pred_prob1"] - 50.0) > 10.0]
    close = [r for r in judged if r["pred_prob1"] is not None
             and abs(r["pred_prob1"] - 50.0) <= 10.0]

    # Brier : (P(J1 gagne) - issue)². issue = 1 si winner == player1.
    briers = []
    for r in judged:
        if r["pred_prob1"] is None:
            continue
        p = r["pred_prob1"] / 100.0
        outcome = 1.0 if r["winner"] == r["player1"] else 0.0
        briers.append((p - outcome) ** 2)
    brier = round(sum(briers) / len(briers), 4) if briers else None

    # ROI : mise 1u sur le favori du modèle, pour les matchs dont on a capté la cote.
    bets = {frozenset((b["player1"], b["player2"])): b for b in db.list_bets()}
    profits = []
    for r in judged:
        b = bets.get(frozenset((r["player1"], r["player2"])))
        if not b or b["fav_odds"] is None:
            continue
        won = (r["winner"] == b["favorite"])
        profits.append((b["fav_odds"] - 1.0) if won else -1.0)
    roi = round(sum(profits) / len(profits), 4) if profits else None

    # ROI value : directement depuis value_picks (EV≥8%, odds≤5.0, réglés)
    vp_stats = db.value_picks_stats()
    roi_value = vp_stats.get("roi")  # déjà calculé proprement dans value_picks_stats()
    v_profits = [None] * vp_stats.get("n", 0)  # pour roi_value_n uniquement

    return {
        "n": n,
        "accuracy": _acc(judged),
        "roi": roi,
        "roi_n": len(profits),
        "roi_value": roi_value,
        "roi_value_n": len(v_profits),
        "brier": brier,
        "atp_acc": _acc([r for r in judged if r["tour"] == "atp"]),
        "wta_acc": _acc([r for r in judged if r["tour"] == "wta"]),
        "fav_acc": _acc(clear),
        "dog_acc": _acc(close),
        "note": ("ROI = mise 1u sur le favori modèle, sur les paris dont la cote "
                 "a été captée (onglet Value)."),
    }
