"""Backtest walk-forward des signaux Sport Intelligence Layer.

Contexte : Phase 2/3 (bot/intelligence_layer.py, bot/sentiment.py) ont ajouté
form_signal, steam_move et sentiment comme signaux PUREMENT INFORMATIFS —
volontairement tenus à l'écart de predictor.predict() et du filtre is_value
de /api/value, en attendant une preuve statistique qu'ils portent une
information réelle (voir la note en tête de intelligence_layer.py). Ce
module est cette preuve : il répond, pour calib_k, form_signal et
steam_move, à la question "est-ce que ce signal aurait amélioré une
décision passée ?" sur les données réellement réglées en base — jamais sur
les données d'entraînement (pas de fuite).

1. Calibration (température k / Platt a,b) : split chronologique train/test
   sur settled_matches ; le facteur est appris sur train, évalué en log-loss
   hors-échantillon sur test. Répond à "calib_k=1.0 est-il vraiment
   optimal, ou existe-t-il un facteur qui généralise mieux ?"

2. form_signal : rejoue tout l'historique (table `matches`) chronologiquement
   avec bot.features.update_profile (même code que la production, pas une
   réimplémentation) pour reconstruire l'EMA de forme AVANT chaque match
   (jamais après — sinon fuite). Compare le taux de victoire réel des
   joueurs signalés "surperformance"/"méforme" à celui des apparitions non
   signalées.

   Limite assumée et documentée : ne contrôle pas la force de l'adversaire
   (ELO, surface). Un signal validé ici mérite un contrôle plus strict avant
   d'entrer dans le modèle — cette limite est un point de départ, pas une
   preuve définitive.

3. steam_move : jointure market_snapshots × settled_matches (mouvement de
   cote réellement capté par le scanner, résultat réel du match). Compare le
   taux de victoire du côté vers lequel la cote a bougé à la probabilité
   implicite par la cote d'ouverture (est-ce que le mouvement contient de
   l'info au-delà de ce que la cote de départ prix déjà ?).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from . import calibrate, config, db, features, intelligence_layer
from .log import log

_EPS = 1e-9


def _logloss(rows: List[Tuple[float, float]]) -> float:
    """rows: (p, y) — p = proba prédite que y=1."""
    if not rows:
        return float("nan")
    total = 0.0
    for p, y in rows:
        p = max(_EPS, min(1 - _EPS, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(rows)


def _brier(rows: List[Tuple[float, float]]) -> float:
    if not rows:
        return float("nan")
    return sum((p - y) ** 2 for p, y in rows) / len(rows)


# ── 1. Calibration (calib_k / Platt) ─────────────────────────────────────────

def backtest_calibration(test_fraction: float = 0.3, min_test: int = 50) -> Dict[str, Any]:
    """Split chronologique : k/Platt appris sur train, évalués en hors-échantillon sur test."""
    rows = [r for r in db.list_settled(limit=200000)
            if r["pred_prob1"] is not None and r["winner"] is not None
            and (r["date"] or "")]
    rows.sort(key=lambda r: r["date"])

    split = int(len(rows) * (1 - test_fraction))
    train, test = rows[:split], rows[split:]
    if len(test) < min_test:
        return {"fitted": False, "n_train": len(train), "n_test": len(test),
                "note": f"Pas assez de matchs réglés datés pour un holdout fiable (min {min_test})."}

    def as_py(p, y_row) -> Tuple[float, float]:
        return p / 100.0, (1.0 if y_row["winner"] == y_row["player1"] else 0.0)

    raw = [as_py(r["pred_prob1"], r) for r in test]

    fit_k = calibrate.fit_temperature(train, half_life_days=0.0)  # pas de pondération récence : cohérence du holdout
    fit_platt = calibrate.fit_platt(train, half_life_days=0.0)

    k_rows = [(calibrate.calibrated_prob(p, fit_k.get("k", 1.0)), y) for p, y in raw] if fit_k.get("fitted") else None
    platt_rows = ([(calibrate.calibrated_prob_platt(p, fit_platt.get("a", 1.0), fit_platt.get("b", 0.0)), y)
                   for p, y in raw] if fit_platt.get("fitted") else None)

    result = {
        "fitted": True,
        "n_train": len(train), "n_test": len(test),
        "span_train": f"{train[0]['date']}..{train[-1]['date']}",
        "span_test": f"{test[0]['date']}..{test[-1]['date']}",
        "logloss_raw": round(_logloss(raw), 4),
        "brier_raw": round(_brier(raw), 4),
        "fitted_k": fit_k.get("k"), "fitted_k_train_n": fit_k.get("n"),
        "logloss_temperature": round(_logloss(k_rows), 4) if k_rows else None,
        "fitted_platt_a": fit_platt.get("a"), "fitted_platt_b": fit_platt.get("b"),
        "logloss_platt": round(_logloss(platt_rows), 4) if platt_rows else None,
    }
    best = min(
        [("raw", result["logloss_raw"]),
         ("temperature", result["logloss_temperature"]),
         ("platt", result["logloss_platt"])],
        key=lambda t: t[1] if t[1] is not None else float("inf"),
    )
    result["best"] = best[0]
    result["verdict"] = (
        f"'{best[0]}' minimise la log-loss hors-échantillon ({best[1]}). "
        + ("La calibration actuelle (k=1.0, non ajustée) est proche de l'optimal."
           if best[0] == "raw" else
           "Un ajustement (temperature/Platt) améliore la calibration hors-échantillon "
           "— candidat à activer en production.")
    )
    return result


# ── 2. form_signal ────────────────────────────────────────────────────────────

def backtest_form_signal(threshold_pts: float = None, min_matches: int = None) -> Dict[str, Any]:
    """Rejoue l'historique complet, EMA/bilan carrière reconstruits AVANT chaque
    match (bot.features.update_profile), pour éviter toute fuite de données.
    """
    threshold_pts = threshold_pts if threshold_pts is not None else intelligence_layer.FORM_SWING_THRESHOLD_PTS
    min_matches = min_matches if min_matches is not None else intelligence_layer.FORM_SWING_MIN_MATCHES
    alpha = config.DEFAULT_CONFIG["ema_alpha"]

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT date, tour, winner, loser, w_serve, w_return1, w_return2, "
            "l_serve, l_return1, l_return2 FROM matches "
            "ORDER BY REPLACE(date,'-','') ASC, id ASC"  # cf. db.player_recent_matches : formats de date mixtes
        ).fetchall()

    mem: Dict[str, Any] = {"players": {}}
    career: Dict[str, List[int]] = {}  # name -> [wins, losses]

    stats = {
        "surperformance": {"wins": 0, "total": 0},
        "méforme": {"wins": 0, "total": 0},
        "aucun_signal": {"wins": 0, "total": 0},
    }

    for r in rows:
        winner, loser = r["winner"], r["loser"]
        for name, won in ((winner, True), (loser, False)):
            prof = mem["players"].get(name)
            rec = career.get(name, [0, 0])
            total = rec[0] + rec[1]
            direction = None
            if prof is not None and int(prof.get("n", 0)) >= min_matches and total >= min_matches:
                recent = float(prof.get("recent", 0.5))
                baseline = rec[0] / total
                diff_pts = (recent - baseline) * 100
                if diff_pts >= threshold_pts:
                    direction = "surperformance"
                elif diff_pts <= -threshold_pts:
                    direction = "méforme"
            bucket = stats[direction] if direction else stats["aucun_signal"]
            bucket["total"] += 1
            if won:
                bucket["wins"] += 1

        # Mise à jour APRÈS évaluation (jamais avant) : évite la fuite.
        w_perf = {"serve": r["w_serve"] or 0.5, "return1": r["w_return1"] or 0.5, "return2": r["w_return2"] or 0.5}
        l_perf = {"serve": r["l_serve"] or 0.5, "return1": r["l_return1"] or 0.5, "return2": r["l_return2"] or 0.5}
        features.update_profile(mem, winner, w_perf, True, alpha, r["tour"])
        features.update_profile(mem, loser, l_perf, False, alpha, r["tour"])
        career.setdefault(winner, [0, 0])[0] += 1
        career.setdefault(loser, [0, 0])[1] += 1

    def rate(bucket) -> Optional[float]:
        return round(bucket["wins"] / bucket["total"], 4) if bucket["total"] else None

    baseline_rate = rate(stats["aucun_signal"])
    surperf_rate = rate(stats["surperformance"])
    meforme_rate = rate(stats["méforme"])

    verdict_bits = []
    if surperf_rate is not None and baseline_rate is not None:
        verdict_bits.append(
            f"surperformance : {surperf_rate:.1%} de victoires réelles vs {baseline_rate:.1%} sans signal"
            + (" — signal informatif" if surperf_rate > baseline_rate + 0.02 else " — pas d'écart net")
        )
    if meforme_rate is not None and baseline_rate is not None:
        verdict_bits.append(
            f"méforme : {meforme_rate:.1%} de victoires réelles vs {baseline_rate:.1%} sans signal"
            + (" — signal informatif" if meforme_rate < baseline_rate - 0.02 else " — pas d'écart net")
        )

    return {
        "threshold_pts": threshold_pts, "min_matches": min_matches,
        "n_matches_replayed": len(rows),
        "surperformance": stats["surperformance"], "surperformance_win_rate": surperf_rate,
        "méforme": stats["méforme"], "méforme_win_rate": meforme_rate,
        "aucun_signal": stats["aucun_signal"], "baseline_win_rate": baseline_rate,
        "caveat": "Ne contrôle pas la force de l'adversaire (ELO/surface) — comparaison brute des taux de victoire.",
        "verdict": " ; ".join(verdict_bits) if verdict_bits else "Échantillon insuffisant pour conclure.",
    }


# ── 3. steam_move ──────────────────────────────────────────────────────────────

def backtest_steam_move(threshold_pct: float = None) -> Dict[str, Any]:
    """Jointure market_snapshots × settled_matches : le mouvement de cote capté
    contient-il de l'info au-delà de la cote d'ouverture (déjà backée par le marché) ?
    """
    threshold_pct = threshold_pct if threshold_pct is not None else intelligence_layer.STEAM_MOVE_THRESHOLD_PCT

    with db.connect() as conn:
        event_keys = [row[0] for row in conn.execute(
            "SELECT DISTINCT ms.event_key FROM market_snapshots ms "
            "JOIN settled_matches sm ON sm.event_key = ms.event_key"
        ).fetchall()]
        winners = {row["event_key"]: row["winner"] for row in conn.execute(
            "SELECT event_key, winner FROM settled_matches WHERE event_key IN "
            f"({','.join('?' for _ in event_keys)})", event_keys
        ).fetchall()} if event_keys else {}
        snap_players = {row["event_key"]: (row["player1"], row["player2"]) for row in conn.execute(
            "SELECT event_key, player1, player2 FROM market_snapshots WHERE event_key IN "
            f"({','.join('?' for _ in event_keys)}) GROUP BY event_key", event_keys
        ).fetchall()} if event_keys else {}

    n_with_move = n_move_side_won = 0
    n_beat_opening_implied = 0
    opening_implied_probs = []
    move_side_win_flags = []

    for eid in event_keys:
        mv = db.line_movement(eid)
        if not mv or mv.get("n_snapshots", 0) < 2:
            continue
        move_home, move_away = mv["move_home_pct"], mv["move_away_pct"]
        # "Steam move" = la cote RACCOURCIT (move_pct négatif : closing < opening,
        # donc plus de monde parie dessus) — pas juste "la plus grosse variation
        # en valeur absolue", qui inclurait à tort un allongement de cote (moins
        # de monde dessus, l'exact opposé d'un steam move).
        if move_home <= -threshold_pct and move_home <= move_away:
            side = "home"
        elif move_away <= -threshold_pct and move_away <= move_home:
            side = "away"
        else:
            continue
        p1, p2 = snap_players.get(eid, (None, None))
        winner = winners.get(eid)
        if not p1 or not p2 or not winner:
            continue

        moved_toward_player = p1 if side == "home" else p2
        opening_odds = mv["opening_odds_home"] if side == "home" else mv["opening_odds_away"]
        if not opening_odds or opening_odds <= 1.0:
            continue
        implied_prob = 1.0 / opening_odds

        n_with_move += 1
        won = (winner == moved_toward_player)
        if won:
            n_move_side_won += 1
        move_side_win_flags.append((implied_prob, 1.0 if won else 0.0))
        if won and implied_prob < 0.5:
            n_beat_opening_implied += 1
        opening_implied_probs.append(implied_prob)

    if n_with_move == 0:
        return {"n_with_move": 0, "note": "Aucun match avec steam move + résultat réglé en base."}

    actual_rate = n_move_side_won / n_with_move
    avg_implied = sum(opening_implied_probs) / len(opening_implied_probs)

    return {
        "threshold_pct": threshold_pct,
        "n_with_move": n_with_move,
        "actual_win_rate_moved_side": round(actual_rate, 4),
        "avg_opening_implied_prob": round(avg_implied, 4),
        "edge_vs_opening_line": round(actual_rate - avg_implied, 4),
        "verdict": (
            f"Le côté vers lequel la cote a bougé gagne {actual_rate:.1%} du temps, "
            f"contre {avg_implied:.1%} impliqué par la cote d'ouverture "
            f"(écart {actual_rate - avg_implied:+.1%})."
            + (" Le mouvement de cote contient une info réelle au-delà du prix d'ouverture."
               if actual_rate - avg_implied > 0.03 else
               " Pas d'écart net détecté — le mouvement ne semble pas ajouter d'info "
               "au-delà de ce que la cote d'ouverture pricait déjà.")
        ),
    }


def run_all() -> Dict[str, Any]:
    log("=== Backtest signaux : calibration + form_signal + steam_move ===", "INFO")
    return {
        "calibration": backtest_calibration(),
        "form_signal": backtest_form_signal(),
        "steam_move": backtest_steam_move(),
    }
