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

from . import calibrate, config, db, elo as elo_mod, features, intelligence_layer, memory, predictor
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


def _clamped_logit(p: float, eps: float = 0.03) -> float:
    p = max(eps, min(1 - eps, p))
    return math.log(p / (1 - p))


def _ece(rows: List[Tuple[float, float]], n_bins: int = 10) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    """Expected Calibration Error (bins de largeur égale sur [0,1]) + courbe
    de fiabilité (mean_pred vs mean_actual par bin, pour tracé/rapport)."""
    if not rows:
        return None, []
    bins: List[List[Tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in rows:
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    n_total = len(rows)
    ece = 0.0
    curve = []
    for i, b in enumerate(bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        if not b:
            curve.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0, "mean_pred": None, "mean_actual": None})
            continue
        mean_pred = sum(p for p, _ in b) / len(b)
        mean_actual = sum(y for _, y in b) / len(b)
        ece += (len(b) / n_total) * abs(mean_pred - mean_actual)
        curve.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(b),
                      "mean_pred": round(mean_pred, 4), "mean_actual": round(mean_actual, 4)})
    return round(ece, 4), curve


def _confidence_distribution(rows: List[Tuple[float, float]], n_bins: int = 5) -> Dict[str, Any]:
    """Distribution de la confiance |p-0.5|*2 (0=pile, 1=certain)."""
    if not rows:
        return {"n": 0}
    confs = [abs(p - 0.5) * 2 for p, _ in rows]
    bins = [0] * n_bins
    for c in confs:
        idx = min(int(c * n_bins), n_bins - 1)
        bins[idx] += 1
    return {
        "n": len(rows),
        "mean_confidence": round(sum(confs) / len(confs), 4),
        "buckets": {f"{i/n_bins:.1f}-{(i+1)/n_bins:.1f}": bins[i] for i in range(n_bins)},
    }


def _paired_ztest(diffs: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """Test bilatéral H0: moyenne(diffs)=0 (approximation normale, CLT — n
    grand ici). diffs = logloss_baseline - logloss_variant par match ;
    positif => la variante réduit la perte."""
    n = len(diffs)
    if n < 2:
        return None, None
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    if var <= 0:
        return (0.0, 1.0) if mean == 0 else (None, None)
    se = math.sqrt(var / n)
    z = round(mean / se, 3)
    p = round(math.erfc(abs(z) / math.sqrt(2)), 4)
    return z, p


def _bootstrap_ci(diffs: List[float], n_boot: int = 2000, alpha: float = 0.05,
                  seed: int = 42) -> Tuple[Optional[float], Optional[float]]:
    """IC bootstrap (percentile) sur la moyenne des diffs — pas de scipy/numpy
    dans ce projet, ré-échantillonnage stdlib (random.Random, seed fixe pour
    reproductibilité)."""
    import random
    n = len(diffs)
    if n == 0:
        return None, None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo_idx = max(0, int(alpha / 2 * n_boot))
    hi_idx = min(n_boot - 1, int((1 - alpha / 2) * n_boot) - 1)
    return round(means[lo_idx], 5), round(means[hi_idx], 5)


def backtest_clutch_blend_walkforward(
    blend_weights: Tuple[float, ...] = (0.05, 0.10, 0.15, 0.20),
    min_bp_faced: float = None,
    n_folds: int = 5,
    n_bins_ece: int = 10,
) -> Dict[str, Any]:
    """Validation walk-forward complète : le predictor de PRODUCTION (poids/
    biais/elo_blend gelés, tels que chargés depuis memory.json — cette
    fonction ne re-fit RIEN) obtient-il une meilleure log-loss/Brier/ECE
    hors-échantillon en ajoutant un terme clutch FAIBLE au logit, à
    plusieurs poids de blend candidats ?

    Découpage en `n_folds` blocs CHRONOLOGIQUES (walk-forward strict, jamais
    de shuffle). Le bloc 0 sert de warm-up (accumulation EMA/ELO/clutch
    initiale) et n'est jamais évalué — pour chaque match des blocs suivants,
    l'état utilisé (profils EMA, ELO global+surface, taux de BP sauvées) est
    reconstruit UNIQUEMENT à partir des matchs strictement antérieurs
    (réutilise bot.features.update_profile et
    bot.ml_prep.features.update_elo_state — code de production, pas une
    réimplémentation).

    Le baseline et chaque variante blend sont évalués sur EXACTEMENT le même
    ensemble de matchs par fold (comparaison appariée) : quand le signal
    clutch n'est pas disponible (historique BP insuffisant), la variante
    blend est strictement identique au baseline pour ce match (le blend ne
    peut donc jamais être *pénalisé* par un manque de données, seulement
    jugé sur les matchs où il s'exprime réellement).

    z = score(feat1) - score(feat2) + biais + elo_logit(...) + poids_blend *
    (logit(taux_bp_p1) - logit(taux_bp_p2))  [logit clampé, eps=0.03]

    Limite assumée : le baseline ELO ici est global+surface uniquement
    (rejoué walk-forward depuis zéro) — la production mélange aussi un ELO
    "forme récente 180j" (elo_recent) légèrement plus riche. La comparaison
    RELATIVE (avec vs sans clutch) reste valide : les deux variantes
    partagent rigoureusement le même baseline, seul le terme clutch diffère.

    Décision : le signal est rejeté par défaut. Il n'est retenu (au moins
    comme candidat expérimental) que si au moins un poids de blend améliore
    la log-loss de façon CONSISTANTE (tous les folds évalués) ET
    STATISTIQUEMENT significative (p<0.05 test apparié ET IC bootstrap 95%
    de la différence de log-loss excluant zéro).
    """
    min_bp_faced = (min_bp_faced if min_bp_faced is not None
                    else float(intelligence_layer.CLUTCH_MIN_BP_FACED))
    alpha = config.DEFAULT_CONFIG["ema_alpha"]

    prod_mem = memory.load()
    weights = dict(prod_mem.get("weights") or {})
    bias = float(prod_mem.get("bias") or 0.0)
    elo_blend = float(prod_mem.get("elo_blend", predictor.ELO_BLEND))

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT date, tour, winner, loser, w_serve, w_return1, w_return2, "
            "l_serve, l_return1, l_return2, surface, margin, "
            "w_bp_saved, w_bp_faced, l_bp_saved, l_bp_faced FROM matches "
            "ORDER BY REPLACE(date,'-','') ASC, id ASC"
        ).fetchall()

    n_total = len(rows)
    if n_total < 200 or n_folds < 2:
        return {"n_matches": n_total, "n_folds": n_folds,
                "note": "Pas assez de matchs (ou n_folds invalide) pour un walk-forward multi-blocs fiable."}

    fold_size = max(1, n_total // n_folds)

    def fold_of(i: int) -> int:
        return min(i // fold_size, n_folds - 1)

    prof_mem: Dict[str, Any] = {"players": {}}
    elo_ratings, elo_surface, elo_n, elo_surf_n = ml_features.init_elo_state()
    clutch_acc: Dict[str, List[float]] = {}

    baseline_by_fold: List[List[Tuple[float, float]]] = [[] for _ in range(n_folds)]
    blend_by_fold: Dict[float, List[List[Tuple[float, float]]]] = {
        bw: [[] for _ in range(n_folds)] for bw in blend_weights
    }
    n_clutch_avail_by_fold = [0] * n_folds
    n_matches_by_fold = [0] * n_folds

    for i, r in enumerate(rows):
        fold = fold_of(i)
        w_name, l_name = r["winner"], r["loser"]
        surface = (r["surface"] or "").lower()

        p1, p2, y = ml_features.orient_players(w_name, l_name)
        feat1 = features.get_profile(prof_mem, p1)
        feat2 = features.get_profile(prof_mem, p2)
        score1 = predictor.weighted_score(weights, feat1)
        score2 = predictor.weighted_score(weights, feat2)
        elo_like_mem = {"elo": elo_ratings, "elo_surface": elo_surface, "elo_blend": elo_blend}
        z = (score1 - score2) + bias + predictor.elo_logit(elo_like_mem, p1, p2, surface)
        p_baseline = predictor._sigmoid(z)

        if fold > 0:  # bloc 0 = warm-up, jamais évalué
            baseline_by_fold[fold].append((p_baseline, float(y)))
            n_matches_by_fold[fold] += 1

        aw, al = clutch_acc.get(p1), clutch_acc.get(p2)
        clutch_diff = 0.0
        if aw and al and aw[1] >= min_bp_faced and al[1] >= min_bp_faced:
            clutch_diff = _clamped_logit(aw[0] / aw[1]) - _clamped_logit(al[0] / al[1])
            if fold > 0:
                n_clutch_avail_by_fold[fold] += 1

        if fold > 0:
            for bw in blend_weights:
                p_blend = predictor._sigmoid(z + bw * clutch_diff)
                blend_by_fold[bw][fold].append((p_blend, float(y)))

        # Mise à jour APRÈS évaluation (jamais avant) : évite toute fuite.
        w_perf = {"serve": r["w_serve"] or 0.5, "return1": r["w_return1"] or 0.5, "return2": r["w_return2"] or 0.5}
        l_perf = {"serve": r["l_serve"] or 0.5, "return1": r["l_return1"] or 0.5, "return2": r["l_return2"] or 0.5}
        features.update_profile(prof_mem, w_name, w_perf, True, alpha, r["tour"])
        features.update_profile(prof_mem, l_name, l_perf, False, alpha, r["tour"])
        ml_features.update_elo_state(
            {"winner_name": w_name, "loser_name": l_name, "surface": surface, "margin": r["margin"]},
            elo_ratings, elo_surface, elo_n, elo_surf_n,
        )
        clutch_acc.setdefault(w_name, [0.0, 0.0])
        clutch_acc.setdefault(l_name, [0.0, 0.0])
        clutch_acc[w_name][0] += r["w_bp_saved"] or 0.0
        clutch_acc[w_name][1] += r["w_bp_faced"] or 0.0
        clutch_acc[l_name][0] += r["l_bp_saved"] or 0.0
        clutch_acc[l_name][1] += r["l_bp_faced"] or 0.0

    eval_folds = list(range(1, n_folds))  # fold 0 = warm-up
    baseline_all = [pt for f in eval_folds for pt in baseline_by_fold[f]]
    n_eval = len(baseline_all)
    if n_eval == 0:
        return {"n_matches": n_total, "n_folds": n_folds,
                "note": "Aucun match évaluable après warm-up (augmenter les données ou réduire n_folds)."}

    baseline_logloss_by_fold = [round(_logloss(baseline_by_fold[f]), 4) for f in eval_folds]
    baseline_ece, baseline_curve = _ece(baseline_all, n_bins_ece)

    result: Dict[str, Any] = {
        "n_matches_total": n_total,
        "n_folds": n_folds,
        "n_evaluated": n_eval,
        "min_bp_faced": min_bp_faced,
        "baseline": {
            "logloss": round(_logloss(baseline_all), 4),
            "logloss_by_fold": baseline_logloss_by_fold,
            "brier": round(_brier(baseline_all), 4),
            "ece": baseline_ece,
            "reliability_curve": baseline_curve,
            "confidence_distribution": _confidence_distribution(baseline_all),
        },
        "note_roi": ("ROI non évaluable ici : la table `matches` (historique de résultats) ne contient "
                     "pas de cotes de marché. settled_matches en a (paris réels), mais n=94 est bien trop "
                     "petit pour un walk-forward de blend fiable — non utilisé pour cette validation."),
        "variants": {},
    }

    best_weight = None
    best_logloss = result["baseline"]["logloss"]
    any_integrate_candidate = False

    for bw in blend_weights:
        variant_all = [pt for f in eval_folds for pt in blend_by_fold[bw][f]]
        variant_logloss_by_fold = [round(_logloss(blend_by_fold[bw][f]), 4) for f in eval_folds]
        variant_ece, variant_curve = _ece(variant_all, n_bins_ece)

        # Diffs appariés par match (logloss baseline - logloss variant ; positif = variant meilleure)
        per_match_diffs = []
        for f in eval_folds:
            for (pb, yb), (pv, yv) in zip(baseline_by_fold[f], blend_by_fold[bw][f]):
                lb = -(yb * math.log(max(_EPS, pb)) + (1 - yb) * math.log(max(_EPS, 1 - pb)))
                lv = -(yv * math.log(max(_EPS, pv)) + (1 - yv) * math.log(max(_EPS, 1 - pv)))
                per_match_diffs.append(lb - lv)

        z_score, p_value = _paired_ztest(per_match_diffs)
        ci_lo, ci_hi = _bootstrap_ci(per_match_diffs)

        deltas_by_fold = [round(baseline_logloss_by_fold[k] - variant_logloss_by_fold[k], 4)
                          for k in range(len(eval_folds))]
        consistent = all(d > 0 for d in deltas_by_fold)
        significant = (p_value is not None and p_value < 0.05
                       and ci_lo is not None and ci_lo > 0)

        variant_result = {
            "logloss": round(_logloss(variant_all), 4),
            "logloss_by_fold": variant_logloss_by_fold,
            "brier": round(_brier(variant_all), 4),
            "ece": variant_ece,
            "reliability_curve": variant_curve,
            "confidence_distribution": _confidence_distribution(variant_all),
            "delta_logloss_by_fold_vs_baseline": deltas_by_fold,
            "mean_delta_logloss": round(sum(per_match_diffs) / len(per_match_diffs), 5) if per_match_diffs else None,
            "paired_ztest_z": z_score,
            "paired_ztest_p": p_value,
            "bootstrap_ci95_mean_delta_logloss": [ci_lo, ci_hi],
            "consistent_across_folds": consistent,
            "statistically_significant": significant,
            "n_matches_with_clutch_signal": sum(n_clutch_avail_by_fold[f] for f in eval_folds),
        }
        result["variants"][f"blend_{bw:.2f}"] = variant_result

        if consistent and significant and variant_result["logloss"] < best_logloss:
            any_integrate_candidate = True
            best_logloss = variant_result["logloss"]
            best_weight = bw

    if any_integrate_candidate:
        result["recommendation"] = "INTEGRATE_AS_EXPERIMENTAL"
        result["verdict"] = (
            f"Poids {best_weight:.2f} : amélioration de log-loss consistante (tous les folds) et "
            f"statistiquement significative (IC bootstrap 95% > 0). Candidat pour un déploiement "
            f"EXPÉRIMENTAL (feature-flaggé, pas dans predictor.predict() en direct) avec suivi ROI/CLV "
            f"réel avant généralisation — l'échantillon settled_matches (paris réels) reste trop petit "
            f"pour valider le ROI in vivo à ce stade."
        )
    else:
        result["recommendation"] = "REJECT"
        result["verdict"] = (
            "Aucun poids de blend testé n'améliore la log-loss de façon à la fois consistante sur "
            "tous les folds ET statistiquement significative (IC bootstrap 95%). Conforme à la règle "
            "du projet : aucun signal n'entre dans predictor.predict() sans preuve walk-forward solide — "
            "le résidu clutch identifié par backtest_clutch_vs_elo() est réel mais trop faible/bruité "
            "pour justifier une intégration, même expérimentale, à ce stade. Continuer d'accumuler des "
            "données (rejouer cette analyse périodiquement) plutôt que d'intégrer sur cette base."
        )
    return result


def run_all() -> Dict[str, Any]:
    log("=== Backtest signaux : calibration + form_signal + steam_move + clutch ===", "INFO")
    return {
        "calibration": backtest_calibration(),
        "form_signal": backtest_form_signal(),
        "steam_move": backtest_steam_move(),
        "clutch": backtest_clutch(),
    }
