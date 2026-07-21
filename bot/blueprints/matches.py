"""Matches blueprint — upcoming + live read-only match feeds."""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from .. import (
    config,
    db,
    espn_api,
    features,
    live_api,
    odds_api,
    oddspapi_feeder,
    predictor,
    weather,
)
from ..log import log

bp = Blueprint("matches", __name__)

_upcoming_cache: Dict[str, Any] = {}
_upcoming_cache_ts: float = 0.0
_UPCOMING_TTL = 270  # 4.5 min — ESPN change rarement plus vite


@bp.get("/api/upcoming")
def api_upcoming():
    from .. import api

    import time as _t
    import datetime as _dt
    days = min(int(request.args.get("days", 2)), 7)
    limit = min(int(request.args.get("limit", 25)), 100)
    want_odds = request.args.get("odds", "false").lower() == "true"
    cache_key = f"{days}_{limit}_{want_odds}"
    now = _t.time()
    global _upcoming_cache_ts
    if cache_key in _upcoming_cache and (now - _upcoming_cache_ts) < _UPCOMING_TTL:
        return jsonify(_upcoming_cache[cache_key])

    # Source 1 : API-Tennis (payante)
    fixtures = live_api.fetch_upcoming({"live_api_provider": "api-tennis"}, days_ahead=days)

    # Source 2 : ESPN (gratuite, ~800 matchs ATP+WTA)
    espn_fixtures = espn_api.fetch_upcoming(days_ahead=days)

    # Source 3 : odds-api.io (fallback cotes + fixtures + heures manquantes)
    odds_events = []
    odds_index = None
    odds_time_index: Dict[frozenset, str] = {}
    if odds_api.is_enabled():
        odds_events = odds_api.fetch_tennis_events(upcoming_only=True)
        # Index temps : comble les 00:00 ESPN avec les vraies heures odds-api.io
        odds_time_index = odds_api.build_time_index(odds_events)
        if want_odds:
            odds_index = odds_api.build_event_index(odds_events)

    # Fusion des sources : ESPN en priorité si API-Tennis vide
    if not fixtures:
        if espn_fixtures:
            log(f"ESPN fallback: {len(espn_fixtures)} matchs ATP+WTA.", "INFO")
            fixtures = espn_fixtures
        elif odds_events:
            log("Fallback odds-api.io pour les fixtures.", "INFO")
            fixtures = live_api.parse_odds_events_as_fixtures(odds_events)
    else:
        # API-Tennis dispo : on enrichit avec ESPN (matchs non dupliqués)
        existing = {(f["player1"].lower(), f["player2"].lower()) for f in fixtures}
        added = 0
        for ef in espn_fixtures:
            key = (ef["player1"].lower(), ef["player2"].lower())
            if key not in existing:
                fixtures.append(ef)
                existing.add(key)
                added += 1
        if added:
            log(f"ESPN: {added} matchs supplémentaires ajoutés.", "INFO")

    # Source 4 : OddsPapi (gratuit, 250 req/mois/compte, pool de clés) — comble
    # la couverture ATP/WTA/Challenger/ITF pendant qu'API-Tennis est impayé
    # (voir bot/oddspapi_feeder.py). Toujours un ajout, jamais un remplacement :
    # is_enabled() renvoie False sans clé configurée -> aucun effet de bord.
    if oddspapi_feeder.is_enabled():
        try:
            raw_oddspapi = oddspapi_feeder.fetch_tennis_fixtures(days_ahead=days)
            oddspapi_fixtures = oddspapi_feeder.parse_fixtures(raw_oddspapi)
            existing = {(f["player1"].lower(), f["player2"].lower()) for f in fixtures}
            added = 0
            for opf in oddspapi_fixtures:
                key = (opf["player1"].lower(), opf["player2"].lower())
                if key not in existing:
                    fixtures.append(opf)
                    existing.add(key)
                    added += 1
            if added:
                log(f"OddsPapi: {added} matchs supplémentaires ajoutés.", "INFO")
        except Exception as exc:
            log(f"OddsPapi fixtures en échec ({exc}) — ignoré.", "WARN")

    # ── Injection des matchs live ITF/UTR (non couverts par ESPN) ───────────────
    # Les matchs odds-api.io "live" ne sont pas dans ESPN → ils disparaissent de
    # l'onglet "À venir" avant même d'y figurer.  On les injecte ici avec live=True
    # pour qu'ils soient visibles avec le badge 🔴 LIVE dans la liste à venir.
    if odds_api.is_enabled():
        try:
            live_odds_events = odds_api.fetch_live_events()
            live_fixtures = live_api.parse_odds_events_as_fixtures(live_odds_events)
            existing_keys = {(f["player1"].lower(), f["player2"].lower()) for f in fixtures}
            added_live = 0
            for lf in live_fixtures:
                if lf.get("is_doubles"):
                    continue
                key = (lf["player1"].lower(), lf["player2"].lower())
                if key not in existing_keys:
                    lf["live"] = True
                    fixtures.append(lf)
                    existing_keys.add(key)
                    added_live += 1
            if added_live:
                log(f"Inplay inject: {added_live} matchs live ITF/UTR ajoutés à upcoming.", "INFO")
        except Exception as exc:
            log(f"Inplay inject (matchs live ITF/UTR) échoué ({exc}) — ignoré.", "WARN")

    # Filet de sécurité global : quelle que soit la source (API-Tennis, ESPN,
    # odds-api.io, OddsPapi, injection live), un fixture non-live daté d'avant
    # aujourd'hui ne doit jamais atteindre l'app — c'est ce qui produisait des
    # matchs de la veille sur le Dashboard (2026-07-14, voir MASTER_TODO.md
    # #3d). Chaque source a déjà été corrigée individuellement ; ce filtre est
    # une seconde ligne de défense pour qu'une future source avec le même bug
    # ne puisse plus reproduire le symptôme en prod.
    _today_str = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    _before = len(fixtures)
    fixtures = [f for f in fixtures if f.get("live") or f.get("date", "") >= _today_str]
    if len(fixtures) < _before:
        log(f"Filet de sécurité upcoming : {_before - len(fixtures)} fixture(s) daté(s) "
            f"avant aujourd'hui écarté(s) (source non identifiée individuellement).", "WARN")

    # Priorité ATP/WTA avant Challenger/ITF/UTR dans l'ordre de troncature :
    # le cap `limit` (défaut 100) coupe la liste avant la fin, et le volume
    # Challenger/ITF (toujours majoritaire) noyait sinon les matchs ATP/WTA
    # fraîchement ajoutés par OddsPapi. Tri stable -> à priorité égale,
    # l'ordre d'origine (et donc les autres critères déjà appliqués) est conservé.
    def _fixture_prio(f: Dict) -> int:
        return 0 if (f.get("tour") or "").lower() in ("atp", "wta") else 1
    fixtures = sorted(fixtures, key=_fixture_prio)

    # Cache météo par tournoi pour éviter les appels répétés
    _weather_cache: Dict[str, Any] = {}

    out = []
    for f in fixtures:
        if f["is_doubles"]:
            continue
        n1, n2 = api._resolve(f["player1"]), api._resolve(f["player2"])

        # Enrichissement heure : si ESPN ne connaît pas l'heure (00:00 ou 06:00 =
        # placeholder API-Tennis pour « horaire non publié »), on complète via odds-api.io.
        match_time = f["time"]
        _placeholder = not match_time or match_time in ("00:00", "06:00")
        if _placeholder and odds_time_index:
            from ..namematch import split_name
            _, l1 = split_name(f["player1"])
            _, l2 = split_name(f["player2"])
            if l1 and l2:
                enriched_time = odds_time_index.get(frozenset((l1, l2)))
                if enriched_time:
                    match_time = enriched_time
        if _placeholder and (not match_time or match_time in ("00:00", "06:00")):
            match_time = "TBD"

        item = {
            "player1_raw": f["player1"], "player2_raw": f["player2"],
            "tournament": f["tournament"], "round": f["round"],
            "date": f["date"], "time": match_time, "live": f["live"],
            "tour": f["tour"], "predictable": bool(n1 and n2),
            "source": f.get("source", "api-tennis"),
        }
        if n1 and n2:
            # Guard: ne pas croiser ATP et WTA (ELO non comparables)
            t1 = (api._MEM.get("players") or {}).get(n1, {}).get("tour", "")
            t2 = (api._MEM.get("players") or {}).get(n2, {}).get("tour", "")
            if t1 and t2 and {t1, t2} == {"atp", "wta"}:
                item["predictable"] = False
                item["prediction_skip"] = "cross-gender"
                continue
            surface = api._surface_for(f["tournament"], f["date"])
            f1 = features.feature_vector(features.get_profile(api._MEM, n1))
            f2 = features.feature_vector(features.get_profile(api._MEM, n2))
            r = predictor.predict(api._MEM, n1, f1, n2, f2, surface=surface)
            # ITF/inconnu + joueurs peu vus → prédiction non fiable
            _tour_raw = (f.get("tour") or "").lower()
            _n1_matches = int((api._MEM.get("players") or {}).get(n1, {}).get("n", 0))
            _n2_matches = int((api._MEM.get("players") or {}).get(n2, {}).get("n", 0))
            _itf_unreliable = (_tour_raw in ("", "itf") and min(_n1_matches, _n2_matches) < 15)
            if _itf_unreliable:
                r["confidence"] = min(r.get("confidence", 0.0), 0.15)
                r["confidence_label"] = "très faible (ITF / données insuffisantes)"
            # Cote réelle (si dispo) récupérée AVANT _bet_builder pour lui passer
            # match_odds — un seul appel _odds_for, réutilisé pour item["odds"]
            # ci-dessous (pas de requête odds-api supplémentaire).
            odds_result = api._odds_for(odds_index, f["player1"], f["player2"]) if odds_index is not None else None
            match_odds_tuple = ((odds_result["home_odds"], odds_result["away_odds"])
                                if odds_result else None)
            bb = api._bet_builder(r["prob1"] / 100.0, n1, n2, match_odds=match_odds_tuple)
            fs_prob = max(r["prob1"], r["prob2"]) / 100.0
            fair_odds = round(1.0 / fs_prob, 2) if fs_prob > 0 else None
            item["prediction"] = {
                "player1": n1, "player2": n2,
                "prob1": r["prob1"], "prob2": r["prob2"],
                "favorite": r["favorite"],
                "surface": r["surface"],
                "confidence": r["confidence"],
                "confidence_label": r["confidence_label"],
                "first_set_prob": round(fs_prob * 100, 1),
                "fair_odds": fair_odds,
                "target_160": bool(fair_odds is not None and fair_odds >= 1.60),
                "ml_prob1": bb["match"]["prob1"], "ml_prob2": bb["match"]["prob2"],
                "set2_prob1": bb["set2"]["prob1"], "set2_prob2": bb["set2"]["prob2"],
                "total_sets_over": bb["third_set_prob"],
                "correct_score_probs": bb["correct_score"],
                "bet_builder": bb,
            }
            if odds_result is not None:
                item["odds"] = odds_result

            # ── Contexte pari : favori modèle vs marché ───────────────────────
            odds_item = item.get("odds")
            if odds_item and odds_item.get("home_odds") and odds_item.get("away_odds"):
                oh, oa = float(odds_item["home_odds"]), float(odds_item["away_odds"])
                mkt_fav = n1 if oh < oa else n2
                mkt_fav_prob = round((1.0 / oh if mkt_fav == n1 else 1.0 / oa) * 100, 1)
                model_fav = r.get("favorite")
                model_fav_prob = r["prob1"] if model_fav == n1 else r["prob2"]
                agree = (mkt_fav == model_fav)

                if agree:
                    edge_pct = round(model_fav_prob / 100.0 - (1.0 / (oh if mkt_fav == n1 else oa)), 4)
                    if edge_pct >= 0.04:
                        bet_tag = "good_bet"
                        bet_label = "✅ Good bet — modèle + marché accordés, edge positif"
                    elif edge_pct >= 0:
                        bet_tag = "neutral"
                        bet_label = "📊 Favori bookmaker — peu d'edge"
                    else:
                        bet_tag = "bad_bet"
                        bet_label = "⚠️ Bad bet — marché surpaye le favori"
                else:
                    edge_pct = round(model_fav_prob / 100.0 - (1.0 / (oh if model_fav == n1 else oa)), 4)
                    bet_tag = "value_underdog"
                    bet_label = f"💎 Value underdog — modèle: {model_fav}, marché: {mkt_fav}"

                item["bet_context"] = {
                    "model_fav": model_fav,
                    "model_fav_prob": model_fav_prob,
                    "market_fav": mkt_fav,
                    "market_fav_prob": mkt_fav_prob,
                    "agree": agree,
                    "edge_pct": round(edge_pct * 100, 1),
                    "tag": bet_tag,
                    "label": bet_label,
                }

            # Météo : uniquement pour les tournois outdoor connus
            tourn_key = f["tournament"].lower()
            if tourn_key not in _weather_cache:
                _weather_cache[tourn_key] = weather.fetch_weather(
                    f["tournament"], surface or "")
            w = _weather_cache[tourn_key]
            if w:
                item["weather"] = w

            # ── Analyse météo + crowd + honeypot ─────────────────────────────
            if n1 and n2:
                try:
                    from .. import weather_profile as wp
                    p1_prof = features.get_profile(api._MEM, n1)
                    p2_prof = features.get_profile(api._MEM, n2)
                    wa = wp.analyze(api._MEM, n1, p1_prof, n2, p2_prof,
                                    w, f["tournament"], surface or "hard")
                    item["weather_analysis"] = wa
                except Exception as exc:
                    log(f"weather_profile.analyze échoué pour {n1} vs {n2} ({exc}) — ignoré.", "WARN")

            # ── H2H résumé rapide ─────────────────────────────────────────────
            try:
                h2h_rows = db.head_to_head(n1, n2)
                hw1 = sum(1 for r in h2h_rows if r["winner"] == n1)
                hw2 = sum(1 for r in h2h_rows if r["winner"] == n2)
                item["h2h"] = {
                    "wins1": hw1, "wins2": hw2, "total": hw1 + hw2,
                    "last_winner": h2h_rows[0]["winner"] if h2h_rows else None,
                }
            except Exception as exc:
                log(f"H2H échoué pour {n1} vs {n2} ({exc}) — ignoré.", "WARN")

            # ── Ranking ───────────────────────────────────────────────────────
            item["rank1"] = api._MEM["players"].get(n1, {}).get("rank")
            item["rank2"] = api._MEM["players"].get(n2, {}).get("rank")
        out.append(item)
        if len(out) >= limit:
            break
    result = {"count": len(out), "matches": out}
    _upcoming_cache[cache_key] = result
    _upcoming_cache_ts = _t.time()
    return jsonify(result)


@bp.get("/api/live")
def api_live():
    """Matchs tennis EN COURS : score, jeu courant, serve, odds live, prédiction pré-match.

    Rafraîchissement côté Android recommandé : 30s.
    """
    from .. import api

    if not odds_api.is_enabled():
        return jsonify({"error": "ODDS_API_KEY absente"}), 503

    live_events = odds_api.fetch_live_events() or []
    # Priorité ATP/WTA → ITF en dernier ; cap à 30 pour éviter les timeouts
    def _live_prio(ev):
        lg = (ev.get("league") or {}).get("name", "") if isinstance(ev.get("league"), dict) else str(ev.get("league", ""))
        if "ATP" in lg or "WTA" in lg: return 0
        if "Challenger" in lg or "ITF" in lg: return 2
        return 1
    live_events = sorted(live_events, key=_live_prio)[:30]

    # Pré-charger les cotes live en une seule passe (max 5 matchs ATP/WTA)
    _odds_fetched: dict = {}
    _odds_budget = 5
    for _ev in live_events:
        if _odds_budget <= 0:
            break
        _lg_n = (_ev.get("league") or {}).get("name", "") if isinstance(_ev.get("league"), dict) else str(_ev.get("league", ""))
        if "ATP" in _lg_n or "WTA" in _lg_n:
            try:
                _mw = odds_api.fetch_match_winner(_ev["id"], ttl=60)
                if _mw:
                    _odds_fetched[str(_ev["id"])] = _mw
                    _odds_budget -= 1
            except Exception as exc:
                log(f"fetch_match_winner échoué pour event {_ev.get('id')} ({exc}) — ignoré.", "WARN")

    out = []
    for e in live_events:
        home_raw = e.get("home", "")
        away_raw = e.get("away", "")
        n1 = api._resolve(home_raw)
        n2 = api._resolve(away_raw)

        # ── Score ────────────────────────────────────────────────────────────
        scores = e.get("scores") or {}
        periods = scores.get("periods") or {}
        sets_home = int(scores.get("home") or 0)
        sets_away = int(scores.get("away") or 0)

        # Sets détaillés : [{"h":6,"a":3}, {"h":2,"a":4}, ...]
        set_scores = []
        for i in range(1, 8):
            p = periods.get(f"p{i}")
            if p and (p.get("home") is not None or p.get("away") is not None):
                set_scores.append({"h": int(p.get("home") or 0),
                                   "a": int(p.get("away") or 0)})

        cg = periods.get("currentgame") or {}
        game_h = str(cg.get("home", "")) if cg else ""
        game_a = str(cg.get("away", "")) if cg else ""

        # ── Horloge ──────────────────────────────────────────────────────────
        clock = e.get("clock") or {}
        serve = clock.get("serve", "")          # "home" | "away"
        status_detail = clock.get("statusDetail", "")
        minute = int(clock.get("minute") or 0)

        # ── Prédiction pré-match ──────────────────────────────────────────────
        prediction = None
        _live_lg = e.get("league") or {}
        _live_league = _live_lg if isinstance(_live_lg, str) else _live_lg.get("name", "")
        _live_surf = e.get("surface") or config.surface_from_league(_live_league) or None
        if n1 and n2:
            try:
                f1 = features.feature_vector(features.get_profile(api._MEM, n1))
                f2 = features.feature_vector(features.get_profile(api._MEM, n2))
                r = predictor.predict(api._MEM, n1, f1, n2, f2, surface=_live_surf)
                pm1_prematch = api._calib(api._set_to_match_prob(r["prob1"] / 100.0))
                # In-play : ré-ajuste au score en cours (sets gagnés/perdus),
                # pas juste la proba pré-match figée. Voir predictor.inplay_match_prob.
                _p_set_calib = predictor.invert_set_to_match_prob(pm1_prematch)
                _bo = api._best_of_for(e.get("tour") or _live_league, _live_league)
                pm1 = predictor.inplay_match_prob(_p_set_calib, sets_home, sets_away, best_of=_bo)
                prediction = {
                    "player1": n1, "player2": n2,
                    "prob1": round(pm1 * 100, 1),
                    "prob2": round((1 - pm1) * 100, 1),
                    # Favori recalculé sur la proba in-play (pas la pré-match r["favorite"]) —
                    # sinon il peut contredire prob1/prob2 une fois le score pris en compte.
                    "favorite": n1 if pm1 >= 0.5 else n2,
                    "confidence": r["confidence"],
                    "confidence_label": r["confidence_label"],
                }
                # Historique pour le graphique d'évolution (écran Live).
                try:
                    db.record_live_prob(str(e["id"]), round(pm1 * 100, 1),
                                       sets_home, sets_away, minute)
                    hist = db.live_prob_history(str(e["id"]))
                    prediction["prob_history"] = [
                        {"ts": h["ts"], "prob1": h["prob1"], "minute": h["minute"],
                         "sets": f"{h['sets_home']}-{h['sets_away']}"}
                        for h in hist
                    ]
                except Exception as exc:  # noqa: BLE001
                    log(f"record_live_prob/history échoué pour event {e.get('id')} ({exc}) — ignoré.", "WARN")
            except Exception as exc:  # noqa: BLE001
                log(f"Prédiction in-play échouée pour event {e.get('id')} ({exc}) — ignoré.", "WARN")

        # ── Cotes live (pré-chargées pour ATP/WTA uniquement) ────────────────
        live_mw = _odds_fetched.get(str(e["id"]))

        _lg = e.get("league") or {}
        league = _lg if isinstance(_lg, str) else _lg.get("name", "")
        out.append({
            "event_id": e["id"],
            "player1": home_raw, "player2": away_raw,
            "player1_resolved": n1, "player2_resolved": n2,
            "league": league,
            "surface": _live_surf,
            "sets_home": sets_home, "sets_away": sets_away,
            "set_scores": set_scores,
            "game_home": game_h, "game_away": game_a,
            "serve": serve,
            "status_detail": status_detail,
            "minute": minute,
            "prediction": prediction,
            "live_odds": {
                "home": live_mw["home_odds"] if live_mw else None,
                "away": live_mw["away_odds"] if live_mw else None,
                "books": live_mw["books"] if live_mw else [],
            } if live_mw else None,
        })

    # Matchs avec cotes live en premier, puis par durée décroissante
    out.sort(key=lambda m: (m["live_odds"] is None, -m["minute"]))

    # ── Auto-settlement des picks en attente ─────────────────────────────────
    try:
        live_ids = {str(m["event_id"]) for m in out}
        settled = db.auto_settle_picks(live_ids)
        if settled:
            log(f"Auto-settled {len(settled)} pick(s): {[s['pick'] for s in settled]}", "INFO")
    except Exception as _e:
        log(f"auto_settle_picks error: {_e}", "WARN")

    return jsonify({"count": len(out), "matches": out})
