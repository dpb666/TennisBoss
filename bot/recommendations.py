"""Recommandations personnalisées — Sport Intelligence Layer.

Personnalise l'usage du compte ACTUEL (joueurs consultés via /api/predict,
picks réellement pris via value_picks/inplay_picks, surfaces récurrentes) —
pas des comptes multi-utilisateurs distincts. Décision produit explicite :
TennisBoss reste mono-compte pour l'instant (voir note personnalisation dans
bot/intelligence_layer.py, tranchée quand la question s'est posée) ; ceci
personnalise l'expérience du compte partagé actuel, pas une isolation
par utilisateur — pas de refonte d'authentification nécessaire.

Aucun calcul de probabilité ici : ce module classe/filtre des matchs déjà
prédits par le pipeline existant (/api/upcoming), il n'invente aucune
nouvelle estimation.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Set

from . import db


def favorite_players(limit: int = 10, min_queries: int = 2) -> List[Dict[str, Any]]:
    """Joueurs les plus consultés récemment (proxy : /api/predict demandé)."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT player1, player2 FROM predictions ORDER BY ts DESC LIMIT 500"
        ).fetchall()
    counts: Counter = Counter()
    for r in rows:
        counts[r["player1"]] += 1
        counts[r["player2"]] += 1
    return [{"player": name, "queries": n} for name, n in counts.most_common(limit) if n >= min_queries]


def risk_profile() -> Dict[str, Any]:
    """Profil de risque déduit des cotes des picks réellement pris (pas des picks suggérés)."""
    with db.connect() as conn:
        odds_rows = list(conn.execute(
            "SELECT odds FROM value_picks WHERE odds IS NOT NULL"
        ).fetchall())
        odds_rows += list(conn.execute(
            "SELECT odds FROM inplay_picks WHERE odds IS NOT NULL"
        ).fetchall())
    odds = [r["odds"] for r in odds_rows if r["odds"] and r["odds"] > 1.0]
    n = len(odds)
    if n < 5:
        return {"n_picks": n, "profile": "insuffisant", "avg_odds": None}
    avg_odds = sum(odds) / n
    if avg_odds < 1.8:
        profile = "prudent"
    elif avg_odds < 3.0:
        profile = "équilibré"
    else:
        profile = "agressif"
    return {"n_picks": n, "profile": profile, "avg_odds": round(avg_odds, 2)}


def preferred_surfaces(limit: int = 3) -> List[Dict[str, Any]]:
    """Surfaces les plus représentées dans les picks pris."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT surface, COUNT(*) as n FROM value_picks "
            "WHERE surface IS NOT NULL AND surface != '' "
            "GROUP BY surface ORDER BY n DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"surface": r["surface"], "n": r["n"]} for r in rows]


def score_upcoming_match(match: Dict[str, Any], favorites: Set[str],
                         risk_profile_label: str, surfaces: Set[str]) -> Dict[str, Any]:
    """Score un match "à venir" pour la personnalisation (0 = pas pertinent).

    Ne recalcule aucune probabilité : lit uniquement ce que /api/upcoming a
    déjà produit. Les noms/surface résolus vivent sous `prediction` (le
    `player1_raw`/`player2_raw` de premier niveau sont bruts — ex.
    "Mejia, Nicolas" côté fixture vs "Nicolas Mejia" une fois résolu — donc
    ne matcheraient jamais `favorite_players()`, qui stocke des noms résolus
    via /api/predict. Sans `prediction` (match non prédictible), pas de
    signal de personnalisation possible sur ce match.
    """
    reasons: List[str] = []
    score = 0.0
    pred = match.get("prediction") or {}
    p1, p2 = pred.get("player1", ""), pred.get("player2", "")

    fav = next((p for p in (p1, p2) if p in favorites), None)
    if fav:
        score += 2.0
        reasons.append(f"Tu suis {fav}")

    surf = (pred.get("surface") or "").lower()
    if surf and surf in surfaces:
        score += 1.0
        reasons.append(f"Surface {surf} que tu regardes souvent")

    conf = pred.get("confidence") or 0.0
    if risk_profile_label == "prudent" and conf >= 0.65:
        score += 1.0
        reasons.append("Confiance élevée (cohérent avec ton profil prudent)")
    elif risk_profile_label == "agressif" and 0.0 < conf < 0.55:
        score += 0.5
        reasons.append("Match plus incertain (cohérent avec ton profil)")

    return {"score": round(score, 2), "reasons": reasons}


def daily_digest(window_hours: int = 24) -> Dict[str, Any]:
    """Résumé pour la notification push quotidienne (bot/scheduler.py::job_daily_digest).

    Ne re-fetch aucune fixture live : le scheduler tourne hors contexte Flask/
    requête, contrairement à /api/recommendations qui peut appeler la vue
    /api/upcoming directement. S'appuie uniquement sur ce qui est déjà en
    base (picks capturés/réglés) — pas de nouvel appel réseau.

    Fenêtre glissante sur `ts` (horodatage de capture, toujours ISO) plutôt
    que sur la colonne `date` (date du match) : `date` a des formats
    incohérents selon la source d'origine (vu en pratique : "2026-06-05" et
    "20260602" mélangés), `ts` est fiable pour un intervalle "dernières 24h".
    """
    import datetime as _dt
    cutoff = (_dt.datetime.now() - _dt.timedelta(hours=window_hours)).isoformat(timespec="seconds")

    with db.connect() as conn:
        vp_settled = conn.execute(
            "SELECT result, pnl FROM value_picks WHERE result IS NOT NULL AND ts >= ?",
            (cutoff,),
        ).fetchall()
        ip_settled = conn.execute(
            "SELECT result, pnl FROM inplay_picks WHERE result IS NOT NULL AND ts >= ?",
            (cutoff,),
        ).fetchall()
        n_new_picks = conn.execute(
            "SELECT COUNT(*) FROM value_picks WHERE ts >= ?", (cutoff,),
        ).fetchone()[0]

    wins = sum(1 for r in vp_settled if r["result"] == 1)
    wins += sum(1 for r in ip_settled if r["result"] == "W")
    losses = sum(1 for r in vp_settled if r["result"] == 0)
    losses += sum(1 for r in ip_settled if r["result"] == "L")
    pnl = sum((r["pnl"] or 0.0) for r in vp_settled) + sum((r["pnl"] or 0.0) for r in ip_settled)

    favs = favorite_players(limit=3)
    risk = risk_profile()

    if risk.get("profile") == "insuffisant" and not favs:
        return {
            "title": "🎾 Bienvenue sur TennisBoss",
            "body": "Analyse quelques matchs et prends tes premiers picks pour débloquer tes recommandations personnalisées.",
            "cold_start": True,
        }

    parts: List[str] = []
    if wins or losses:
        sign = "+" if pnl >= 0 else ""
        parts.append(f"{wins}W-{losses}L ({sign}{pnl:.1f}u) sur les dernières 24h")
    if n_new_picks:
        parts.append(f"{n_new_picks} pick(s) détecté(s)")
    if favs:
        parts.append(f"tu suis {', '.join(f['player'] for f in favs[:2])}")

    body = " · ".join(parts) if parts else "Rien de neuf depuis hier — reviens plus tard."
    return {"title": "🎾 Ton résumé TennisBoss", "body": body, "cold_start": False}


def build_recommendations(upcoming_matches: List[Dict[str, Any]], limit: int = 10) -> Dict[str, Any]:
    """Assemble le profil (favoris/risque/surfaces) et score les matchs fournis."""
    favs = {f["player"] for f in favorite_players()}
    risk = risk_profile()
    surfs = {s["surface"] for s in preferred_surfaces()}

    scored = []
    for m in upcoming_matches:
        s = score_upcoming_match(m, favs, risk.get("profile", ""), surfs)
        if s["score"] > 0:
            scored.append({**m, "recommendation_score": s["score"], "recommendation_reasons": s["reasons"]})
    scored.sort(key=lambda m: -m["recommendation_score"])

    return {
        "favorite_players": sorted(favs),
        "risk_profile": risk,
        "preferred_surfaces": sorted(surfs),
        "matches": scored[:limit],
    }
