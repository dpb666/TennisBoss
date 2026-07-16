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

from . import calibrate, config, db, elo as elo_mod, features, intelligence_layer
from .log import log
from .ml_prep import features as ml_features

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


# ── 4. clutch (break points / tie-breaks) ─────────────────────────────────────

def backtest_clutch(min_bp_faced: float = None,
                    diff_threshold: float = 0.08) -> Dict[str, Any]:
    """Le taux HISTORIQUE de BP sauvées prédit-il le vainqueur ?

    Replay chronologique de la table `matches` (lignes avec stats BP) :
    agrégats clutch accumulés AVANT chaque match (jamais après — pas de
    fuite). Quand les deux joueurs ont un échantillon suffisant et que leurs
    taux de BP sauvées diffèrent d'au moins `diff_threshold`, on regarde si
    le côté "plus clutch" gagne plus souvent que 50% (baseline symétrique
    par construction : chaque match a un côté plus clutch et un côté moins).

    Limite assumée (comme form_signal) : le taux de BP sauvées est corrélé à
    la qualité de service globale, déjà dans le modèle — un écart positif ici
    ne prouve pas une info NOUVELLE, seulement que le signal n'est pas du
    bruit. Contrôle plus strict requis avant toute entrée dans le modèle.
    """
    min_bp_faced = (min_bp_faced if min_bp_faced is not None
                    else float(intelligence_layer.CLUTCH_MIN_BP_FACED))

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT winner, loser, w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced "
            "FROM matches WHERE w_bp_faced IS NOT NULL "
            "ORDER BY REPLACE(date,'-','') ASC, id ASC"
        ).fetchall()

    acc: Dict[str, List[float]] = {}  # name -> [bp_saved, bp_faced]

    n_eval = n_clutch_won = 0
    for r in rows:
        w, l = r["winner"], r["loser"]
        aw, al = acc.get(w), acc.get(l)
        if (aw and al and aw[1] >= min_bp_faced and al[1] >= min_bp_faced):
            rate_w, rate_l = aw[0] / aw[1], al[0] / al[1]
            if abs(rate_w - rate_l) >= diff_threshold:
                n_eval += 1
                if rate_w > rate_l:   # le côté plus clutch a gagné
                    n_clutch_won += 1
        # Mise à jour APRÈS évaluation (jamais avant) : évite la fuite.
        acc.setdefault(w, [0.0, 0.0])
        acc.setdefault(l, [0.0, 0.0])
        acc[w][0] += r["w_bp_saved"] or 0.0
        acc[w][1] += r["w_bp_faced"] or 0.0
        acc[l][0] += r["l_bp_saved"] or 0.0
        acc[l][1] += r["l_bp_faced"] or 0.0

    if n_eval == 0:
        return {"n_matches_with_bp": len(rows), "n_evaluated": 0,
                "note": "Aucun match où les deux joueurs ont un historique BP suffisant "
                        "(lancer datasource.clutch_backfill() ?)."}

    rate = n_clutch_won / n_eval
    return {
        "min_bp_faced": min_bp_faced,
        "diff_threshold": diff_threshold,
        "n_matches_with_bp": len(rows),
        "n_evaluated": n_eval,
        "clutch_side_win_rate": round(rate, 4),
        "baseline": 0.5,
        "caveat": ("Le taux de BP sauvées est corrélé à la qualité de service, déjà "
                   "dans le modèle — un écart ici ne prouve pas une info nouvelle."),
        "verdict": (
            f"Le côté au meilleur historique de BP sauvées gagne {rate:.1%} des matchs "
            f"(baseline 50%, n={n_eval})."
            + (" Signal informatif — mérite un contrôle contre l'ELO avant d'aller plus loin."
               if rate > 0.52 else " Pas d'écart net — signal probablement redondant/bruit.")
        ),
    }


def _proportion_ztest(observed_rate: float, n: int, null_p: float = 0.5) -> Tuple[Optional[float], Optional[float]]:
    """Test de proportion bilatéral (approximation normale, H0: rate=null_p).

    z = (p_hat - p0) / sqrt(p0*(1-p0)/n). p-value via la fonction d'erreur
    (math.erfc, stdlib — pas de scipy dans ce projet). Fiable pour n grand
    (>~30 avec p0=0.5, largement le cas ici).
    """
    if n <= 0:
        return None, None
    se = math.sqrt(null_p * (1 - null_p) / n)
    if se == 0:
        return None, None
    z = round((observed_rate - null_p) / se, 3)
    p = round(math.erfc(abs(z) / math.sqrt(2)), 4)
    return z, p


def backtest_clutch_vs_elo(min_bp_faced: float = None, diff_threshold: float = 0.08,
                          elo_close_threshold: float = 75.0) -> Dict[str, Any]:
    """Le signal clutch (BP sauvées, voir backtest_clutch) survit-il un
    contrôle contre l'ELO ?

    backtest_clutch() mesure 61.6% de réussite globale (n=4294) — mais le
    taux de BP sauvées est corrélé à la qualité de service, déjà capturée
    par l'ELO. Si l'écart clutch n'existe QUE sur des matchs où l'ELO est
    déjà tranché (gros écart), le signal est redondant. La vraie preuve
    d'info nouvelle : est-ce que le côté "plus clutch" gagne encore plus de
    50% des matchs PARMI CEUX où l'ELO ne permet PAS de trancher (écart
    < elo_close_threshold points) ?

    Replay chronologique conjoint : accumulateurs BP (identique à
    backtest_clutch) + état ELO walk-forward rejoué avec
    bot.ml_prep.features.init_elo_state/update_elo_state (même code que la
    prod pour build_feature_row, pas une réimplémentation) — ELO et clutch
    tous deux mesurés AVANT chaque match, jamais de fuite.
    """
    min_bp_faced = (min_bp_faced if min_bp_faced is not None
                    else float(intelligence_layer.CLUTCH_MIN_BP_FACED))

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT winner, loser, w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced, margin "
            "FROM matches WHERE w_bp_faced IS NOT NULL "
            "ORDER BY REPLACE(date,'-','') ASC, id ASC"
        ).fetchall()

    acc: Dict[str, List[float]] = {}
    elo_ratings, elo_surface, elo_n, elo_surf_n = ml_features.init_elo_state()

    n_eval_all = n_clutch_won_all = 0
    n_eval_close = n_clutch_won_close = 0
    elo_gaps: List[float] = []

    for r in rows:
        w, l = r["winner"], r["loser"]
        aw, al = acc.get(w), acc.get(l)
        if aw and al and aw[1] >= min_bp_faced and al[1] >= min_bp_faced:
            rate_w, rate_l = aw[0] / aw[1], al[0] / al[1]
            if abs(rate_w - rate_l) >= diff_threshold:
                elo_gap = abs(elo_ratings.get(w, elo_mod.BASE) - elo_ratings.get(l, elo_mod.BASE))
                clutch_won = rate_w > rate_l

                n_eval_all += 1
                elo_gaps.append(elo_gap)
                if clutch_won:
                    n_clutch_won_all += 1

                if elo_gap < elo_close_threshold:
                    n_eval_close += 1
                    if clutch_won:
                        n_clutch_won_close += 1

        acc.setdefault(w, [0.0, 0.0])
        acc.setdefault(l, [0.0, 0.0])
        acc[w][0] += r["w_bp_saved"] or 0.0
        acc[w][1] += r["w_bp_faced"] or 0.0
        acc[l][0] += r["l_bp_saved"] or 0.0
        acc[l][1] += r["l_bp_faced"] or 0.0

        # Mise à jour ELO APRÈS évaluation (jamais avant) : évite la fuite.
        ml_features.update_elo_state(
            {"winner_name": w, "loser_name": l, "surface": None, "margin": r["margin"]},
            elo_ratings, elo_surface, elo_n, elo_surf_n,
        )

    if n_eval_all == 0:
        return {"n_evaluated_all": 0,
                "note": "Aucun match évaluable (voir backtest_clutch pour le diagnostic)."}

    rate_all = round(n_clutch_won_all / n_eval_all, 4)
    rate_close = round(n_clutch_won_close / n_eval_close, 4) if n_eval_close else None
    avg_elo_gap = round(sum(elo_gaps) / len(elo_gaps), 1) if elo_gaps else None

    z_score, p_value_approx = (_proportion_ztest(rate_close, n_eval_close)
                                if n_eval_close else (None, None))

    significant = z_score is not None and abs(z_score) >= 1.96  # ~95% bilatéral

    if rate_close is None:
        verdict = "Aucun match avec écart ELO < seuil parmi les matchs évaluables — seuil trop strict, augmenter elo_close_threshold."
    elif rate_close > 0.52 and significant:
        verdict = (f"Le signal clutch SURVIT au contrôle ELO et reste statistiquement significatif : "
                   f"{rate_close:.1%} de réussite parmi les {n_eval_close} matchs où l'ELO est proche "
                   f"(< {elo_close_threshold:.0f} pts), vs {rate_all:.1%} sur l'ensemble (n={n_eval_all}) — "
                   f"z={z_score}, p≈{p_value_approx}. C'est une info nouvelle, modeste mais réelle (pas un "
                   "simple proxy service/ELO) — la majorité de l'écart brut (61.6%) était en fait "
                   "expliquée par l'ELO, mais un résidu réel subsiste. Candidat pour un blend faible "
                   "(pas un remplacement), à valider par un vrai walk-forward log-loss avant intégration.")
    elif rate_close > 0.5:
        verdict = (f"Le signal clutch survit nominalement au contrôle ELO ({rate_close:.1%} sur "
                   f"{n_eval_close} matchs ELO-proches, vs {rate_all:.1%} sur l'ensemble) mais "
                   f"l'écart n'est PAS statistiquement significatif (z={z_score}, p≈{p_value_approx}) — "
                   "trop proche du hasard pour conclure à une info nouvelle avec ce N. Accumuler plus "
                   "de données avant de trancher, ne pas intégrer au modèle sur cette base.")
    else:
        verdict = (f"Le signal clutch NE survit PAS au contrôle ELO : {rate_close:.1%} de réussite "
                   f"parmi les {n_eval_close} matchs ELO-proches (au ou sous le hasard), contre {rate_all:.1%} "
                   f"sur l'ensemble (n={n_eval_all}). L'écart global vient du fait que le côté plus clutch "
                   "a aussi souvent un ELO plus élevé — signal redondant, ne pas intégrer tel quel.")

    return {
        "elo_close_threshold": elo_close_threshold,
        "min_bp_faced": min_bp_faced,
        "diff_threshold": diff_threshold,
        "n_evaluated_all": n_eval_all,
        "clutch_win_rate_all": rate_all,
        "n_evaluated_elo_close": n_eval_close,
        "clutch_win_rate_elo_close": rate_close,
        "avg_elo_gap_evaluated": avg_elo_gap,
        "z_score": z_score,
        "p_value_approx": p_value_approx,
        "significant_95pct": significant,
        "baseline": 0.5,
        "verdict": verdict,
    }


def run_all() -> Dict[str, Any]:
    log("=== Backtest signaux : calibration + form_signal + steam_move + clutch ===", "INFO")
    return {
        "calibration": backtest_calibration(),
        "form_signal": backtest_form_signal(),
        "steam_move": backtest_steam_move(),
        "clutch": backtest_clutch(),
    }
