"""Sport Intelligence Layer — façade Phase 1 + Pattern Detection Phase 2 + Phase 3.

Ne calcule rien de nouveau pour la partie Phase 1 : regroupe en un seul
objet ce que `intelligence.py` (drift/blacklist/surfaces), `db.line_movement`
(mouvement de cotes) et `api._explain` (décomposition exacte du logit,
facteur par facteur) exposent déjà séparément. Sert de source unique à
`/api/insight`, qui répond à "pourquoi ce pick ?" en un seul appel au
lieu de 3 (auparavant : /api/predict + /api/intelligence/stats +
/api/line-movement, recomposés manuellement côté client).

Ne recalcule pas les facteurs depuis les features brutes : ça dupliquerait
`api._explain`, qui fait déjà une décomposition exacte du logit (pas une
approximation) et connaît le poids réel de chaque feature. On lui passe
son résultat tel quel.

Phase 2 ajoute deux signaux réellement nouveaux (form_signal, steam_move),
mais volontairement INFORMATIFS UNIQUEMENT : ni l'un ni l'autre n'entre
dans predictor.predict() ni dans le filtre is_value de /api/value. Le
memory du projet est explicite là-dessus (modèle déjà surconfiant, calib_k
figé à 1.0 faute de recul) — un signal non backtesté qui influencerait une
probabilité répéterait cette erreur. Une fois assez de picks avec/sans ces
signaux réglés (voir bot/clv.py), un backtest décidera s'ils méritent de
peser sur le modèle.

Phase 3 ajoute le sentiment/actualités (bot/sentiment.py, NewsAPI.org) —
même prudence : informatif uniquement. Contrainte supplémentaire propre à
cette source : le plan gratuit NewsAPI est à 100 requêtes/jour (bien plus
serré que le pool ODDS_API). Le signal est donc désactivé par défaut dans
/api/insight (paramètre `sentiment=true` explicite) plutôt qu'appelé à
chaque ouverture de "Pourquoi ce pick ?" côté app — un signal qui grille le
quota en quelques minutes d'usage normal serait pire qu'utile.

Phase 4 (audit "Senior Software Engineer") ajoute fatigue et qualité des
adversaires récents — même prudence, informatifs uniquement. Piège
concret rencontré en les construisant : matches.date mélange deux formats
selon la source d'ingestion (Sackmann "20220103" vs tennis-data.co.uk
"2022-01-17" — confirmé 87%/13% sur les 91946 lignes). Un filtre
`date >= cutoff` naïf comparerait des chaînes de longueurs différentes et
raterait silencieusement la majorité des matchs récents. REPLACE(date,'-','')
normalise les deux formats avant comparaison.
"""
from __future__ import annotations

import contextvars
import datetime as _dt
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from . import db, intelligence, sentiment

# Cache requête-scopé (prefetch batch pour engineer/today).
_intel_cache: contextvars.ContextVar[Optional[db.PlayerIntelCache]] = contextvars.ContextVar(
    "intel_cache", default=None,
)


@contextmanager
def intel_batch(
    names: Sequence[str],
    pairs: Sequence[Tuple[str, str]],
) -> Iterator[None]:
    """Prefetch SQLite pour une série de compute_tis (une connexion vs N×8)."""
    cutoff = (_dt.date.today() - _dt.timedelta(days=FATIGUE_WINDOW_DAYS)).strftime("%Y%m%d")
    cache = db.prefetch_player_intel(
        names, pairs,
        fatigue_cutoff=cutoff,
        opp_limit=OPPONENT_QUALITY_WINDOW,
        clutch_limit=CLUTCH_WINDOW_MATCHES,
    )
    token = _intel_cache.set(cache)
    try:
        yield
    finally:
        _intel_cache.reset(token)


def _cached_record(name: str) -> Dict[str, int]:
    cache = _intel_cache.get()
    if cache is not None:
        return cache.records.get(name, {"wins": 0, "losses": 0})
    return db.player_record(name)


def _cached_recent_count(name: str, cutoff: str) -> int:
    cache = _intel_cache.get()
    if cache is not None:
        return cache.recent_counts.get(name, 0)
    return db.player_recent_match_count(name, cutoff)


def _cached_last_date(name: str) -> Optional[str]:
    cache = _intel_cache.get()
    if cache is not None:
        return cache.last_dates.get(name)
    return db.player_last_match_date(name)


def _cached_opponents(name: str, limit: int) -> List[Any]:
    cache = _intel_cache.get()
    if cache is not None:
        return cache.opponents.get(name, [])[:limit]
    return db.player_recent_opponents(name, limit)


def _cached_clutch(name: str, limit: int) -> Dict[str, float]:
    cache = _intel_cache.get()
    if cache is not None:
        empty = {
            "bp_saved": 0.0, "bp_faced": 0.0, "bp_converted": 0.0,
            "bp_chances": 0.0, "tb_won": 0.0, "tb_played": 0.0, "n_matches": 0.0,
        }
        return cache.clutch.get(name, empty)
    return db.player_clutch_stats(name, limit)


def _cached_h2h(n1: str, n2: str) -> List[Any]:
    cache = _intel_cache.get()
    if cache is not None:
        return cache.h2h.get((n1, n2), [])
    return db.head_to_head(n1, n2)

# Écart (points de %) entre forme récente (EMA) et bilan carrière pour
# déclencher un signal de bascule de forme. En dessous, c'est du bruit normal
# d'échantillonnage, pas un vrai changement de niveau.
FORM_SWING_THRESHOLD_PTS = 15.0
FORM_SWING_MIN_MATCHES = 10

# Mouvement de cote (%) entre ouverture et dernier relevé pour parler de
# "steam move" (argent qui bouge la ligne) plutôt que du bruit de marché normal.
STEAM_MOVE_THRESHOLD_PCT = 15.0

# Nombre de matchs sur une fenêtre glissante pour signaler une charge de jeu
# inhabituelle (proxy de fatigue — pas de données physio/médicales disponibles).
FATIGUE_WINDOW_DAYS = 14
FATIGUE_MATCH_THRESHOLD = 6

# Écart ELO (points) entre un joueur et ses N derniers adversaires pour
# signaler un calendrier récent anormalement facile/difficile.
OPPONENT_QUALITY_WINDOW = 10
OPPONENT_QUALITY_MIN_MATCHES = 5
OPPONENT_QUALITY_ELO_THRESHOLD = 100.0

# Signal "clutch" (points sous pression) : taux de BP sauvées au service et de
# tie-breaks gagnés sur les derniers matchs avec stats Sackmann. Repères
# circuit : ~62-65% de BP sauvées (corrélé au % de points gagnés au service),
# ~50% de TB gagnés par construction. On ne signale que les écarts nets, avec
# un échantillon minimal — sinon c'est du bruit.
CLUTCH_WINDOW_MATCHES = 20
CLUTCH_MIN_BP_FACED = 15
CLUTCH_BP_SAVE_HIGH = 0.72
CLUTCH_BP_SAVE_LOW = 0.52
CLUTCH_MIN_TB_PLAYED = 5
CLUTCH_TB_WIN_HIGH = 0.70
CLUTCH_TB_WIN_LOW = 0.30

# Jours de repos avant le match : complète fatigue_signals (qui compte le
# volume sur une fenêtre glissante) avec le signal inverse — un retour après
# une longue coupure (blessure, pause) n'apparaît pas dans une fenêtre de
# matchs joués. Repères calendrier uniquement, pas de données physio/médicales.
REST_DAYS_LOW = 2       # <= : enchaînement rapide, fatigue potentielle
REST_DAYS_HIGH = 21     # >= : retour après coupure, rythme de jeu incertain


def _form_signal(name: str, prof: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compare la forme récente (EMA `recent`) au bilan carrière du joueur.

    Un écart important suggère une bascule de niveau que l'EMA seule (déjà
    lissée) peut sous-représenter — utile à l'œil humain, pas injecté dans
    le modèle (voir note Phase 2 en tête de fichier).
    """
    n = int(prof.get("n", 0))
    if n < FORM_SWING_MIN_MATCHES:
        return None
    record = _cached_record(name)
    total = record["wins"] + record["losses"]
    if total < FORM_SWING_MIN_MATCHES:
        return None
    recent = float(prof.get("recent", 0.5))
    baseline = record["wins"] / total
    diff_pts = (recent - baseline) * 100
    if abs(diff_pts) < FORM_SWING_THRESHOLD_PTS:
        return None
    return {
        "player": name,
        "direction": "surperformance" if diff_pts > 0 else "méforme",
        "recent_form_pct": round(recent * 100, 1),
        "career_baseline_pct": round(baseline * 100, 1),
        "diff_pts": round(diff_pts, 1),
    }


def form_signals(mem: Dict[str, Any], n1: str, n2: str) -> List[Dict[str, Any]]:
    from . import features
    out = []
    for name in (n1, n2):
        sig = _form_signal(name, features.get_profile(mem, name))
        if sig:
            out.append(sig)
    return out


def _fatigue_signal(name: str) -> Optional[Dict[str, Any]]:
    """Nombre de matchs joués sur les FATIGUE_WINDOW_DAYS derniers jours.

    Voir note en tête de fichier pour le piège de format de date.
    """
    cutoff = (_dt.date.today() - _dt.timedelta(days=FATIGUE_WINDOW_DAYS)).strftime("%Y%m%d")
    n = _cached_recent_count(name, cutoff)
    if n < FATIGUE_MATCH_THRESHOLD:
        return None
    return {
        "player": name,
        "matches_recent": n,
        "window_days": FATIGUE_WINDOW_DAYS,
    }


def fatigue_signals(n1: str, n2: str) -> List[Dict[str, Any]]:
    out = []
    for name in (n1, n2):
        sig = _fatigue_signal(name)
        if sig:
            out.append(sig)
    return out


def _rest_days_signal(name: str) -> Optional[Dict[str, Any]]:
    """Jours écoulés depuis le dernier match connu du joueur.

    Voir note en tête de fichier pour le piège de format de date (même
    normalisation que fatigue_signals, via db.player_last_match_date).
    """
    last = _cached_last_date(name)
    if not last:
        return None
    try:
        last_date = _dt.datetime.strptime(last, "%Y%m%d").date()
    except ValueError:
        return None
    rest_days = (_dt.date.today() - last_date).days
    if rest_days < 0 or REST_DAYS_LOW < rest_days < REST_DAYS_HIGH:
        return None
    return {
        "player": name,
        "rest_days": rest_days,
        "flag": "enchainement_rapide" if rest_days <= REST_DAYS_LOW else "retour_apres_coupure",
    }


def rest_days_signals(n1: str, n2: str) -> List[Dict[str, Any]]:
    out = []
    for name in (n1, n2):
        sig = _rest_days_signal(name)
        if sig:
            out.append(sig)
    return out


def _opponent_quality_signal(mem: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Compare l'ELO du joueur à celui de ses OPPONENT_QUALITY_WINDOW derniers
    adversaires : un calendrier récent anormalement facile/difficile est un
    signal que l'EMA de forme seule ne distingue pas d'une vraie évolution
    de niveau (voir note en tête de fichier pour le format de date).
    """
    rows = _cached_opponents(name, OPPONENT_QUALITY_WINDOW)
    if len(rows) < OPPONENT_QUALITY_MIN_MATCHES:
        return None
    elo = mem.get("elo") or {}
    own_elo = elo.get(name)
    if own_elo is None:
        return None
    opp_elos = [elo.get(r["loser"] if r["winner"] == name else r["winner"], 1500.0) for r in rows]
    avg_opp_elo = sum(opp_elos) / len(opp_elos)
    diff = avg_opp_elo - own_elo
    if abs(diff) < OPPONENT_QUALITY_ELO_THRESHOLD:
        return None
    return {
        "player": name,
        "n_matches": len(rows),
        "avg_opponent_elo": round(avg_opp_elo, 1),
        "own_elo": round(own_elo, 1),
        "diff_elo": round(diff, 1),
        "direction": "adversaires plus forts que lui" if diff > 0 else "adversaires plus faibles que lui",
    }


def opponent_quality_signals(mem: Dict[str, Any], n1: str, n2: str) -> List[Dict[str, Any]]:
    out = []
    for name in (n1, n2):
        sig = _opponent_quality_signal(mem, name)
        if sig:
            out.append(sig)
    return out


def _clutch_signal(name: str) -> Optional[Dict[str, Any]]:
    """Comportement sous pression : BP sauvées au service et tie-breaks gagnés
    sur les CLUTCH_WINDOW_MATCHES derniers matchs avec stats (Sackmann).

    Deux dimensions indépendantes, chacune avec son propre seuil d'échantillon ;
    on ne renvoie un signal que si AU MOINS une est notable. Informationnel
    uniquement (voir note Phase 2) — backtest walk-forward dans
    bot/signal_backtest.py::backtest_clutch avant toute entrée dans le modèle.
    """
    stats = _cached_clutch(name, CLUTCH_WINDOW_MATCHES)
    notes: List[str] = []
    out: Dict[str, Any] = {"player": name, "n_matches": int(stats["n_matches"])}

    if stats["bp_faced"] >= CLUTCH_MIN_BP_FACED:
        save_rate = stats["bp_saved"] / stats["bp_faced"]
        out["bp_saved"] = int(stats["bp_saved"])
        out["bp_faced"] = int(stats["bp_faced"])
        out["bp_save_rate"] = round(save_rate, 3)
        if save_rate >= CLUTCH_BP_SAVE_HIGH:
            notes.append("solide sur balles de break")
        elif save_rate <= CLUTCH_BP_SAVE_LOW:
            notes.append("fragile sur balles de break")

    if stats["tb_played"] >= CLUTCH_MIN_TB_PLAYED:
        tb_rate = stats["tb_won"] / stats["tb_played"]
        out["tb_won"] = int(stats["tb_won"])
        out["tb_played"] = int(stats["tb_played"])
        out["tb_win_rate"] = round(tb_rate, 3)
        if tb_rate >= CLUTCH_TB_WIN_HIGH:
            notes.append("très bon en tie-break")
        elif tb_rate <= CLUTCH_TB_WIN_LOW:
            notes.append("faible en tie-break")

    if not notes:
        return None
    out["direction"] = " ; ".join(notes)
    return out


def clutch_signals(n1: str, n2: str) -> List[Dict[str, Any]]:
    out = []
    for name in (n1, n2):
        sig = _clutch_signal(name)
        if sig:
            out.append(sig)
    return out


def steam_move_signal(event_id: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Mouvement de cote anormal capté par le scanner, si suivi pour ce match.

    Un "steam move" (terme du milieu du paris) désigne une cote qui RACCOURCIT
    (move_pct négatif : closing < opening — plus de monde parie dessus), pas
    juste "la plus grosse variation en valeur absolue" : un allongement de
    cote (moins de monde dessus) est l'exact opposé et ne doit pas être
    labellisé comme un steam move sur ce côté. Bug trouvé et corrigé via
    bot/signal_backtest.py::backtest_steam_move (même erreur reproduite dans
    le backtest avant d'être repérée par le résultat aberrant qu'elle produisait).

    Purement diagnostique : n'affecte ni le calcul d'EV ni le filtre
    `is_value` de /api/value (voir note Phase 2 en tête de fichier).
    """
    if not event_id:
        return None
    mv = db.line_movement(str(event_id))
    if not mv or mv.get("n_snapshots", 0) < 2:
        return None
    move_home, move_away = mv["move_home_pct"], mv["move_away_pct"]
    if move_home <= -STEAM_MOVE_THRESHOLD_PCT and move_home <= move_away:
        side, biggest = "home", move_home
    elif move_away <= -STEAM_MOVE_THRESHOLD_PCT and move_away <= move_home:
        side, biggest = "away", move_away
    else:
        return None
    return {
        "side": side,
        "move_pct": biggest,
        "n_snapshots": mv["n_snapshots"],
    }


def sentiment_signals(n1: str, n2: str) -> List[Dict[str, Any]]:
    """Sentiment récent (NewsAPI) pour les 2 joueurs, si NEWSAPI_KEY configurée.

    Appelant responsable d'activer ceci explicitement (voir note Phase 3 en
    tête de fichier) — pas de coût caché.
    """
    if not sentiment.is_enabled():
        return []
    out = []
    for name in (n1, n2):
        sig = sentiment.player_sentiment(name)
        if sig:
            out.append(sig)
    return out


def _h2h_factor(n1: str, n2: str) -> Optional[Dict[str, Any]]:
    h2h = _cached_h2h(n1, n2)
    w1 = sum(1 for row in h2h if row["winner"] == n1)
    w2 = sum(1 for row in h2h if row["winner"] == n2)
    if not w1 and not w2:
        return None
    return {
        "key": "h2h", "label": "Confrontations directes",
        "value1": w1, "value2": w2,
        "favors": n1 if w1 > w2 else (n2 if w2 > w1 else None),
    }


def _model_health(n1: str, n2: str, surface: Optional[str]) -> Dict[str, Any]:
    stats = intelligence.stats()
    blacklist = set(stats.get("blacklist") or [])
    surface_danger = set(stats.get("surface_danger") or [])
    return {
        "player1_blacklisted": n1 in blacklist,
        "player2_blacklisted": n2 in blacklist,
        "surface_danger": bool(surface) and surface in surface_danger,
        "accuracy_drift_pts": stats.get("accuracy_drift_pts", 0.0),
    }


def build_insight(
    mem: Dict[str, Any],
    n1: str,
    n2: str,
    explain: Dict[str, Any],
    confidence: float = 0.0,
    confidence_label: str = "?",
    surface: Optional[str] = None,
    event_id: Optional[str] = None,
    include_sentiment: bool = False,
) -> Dict[str, Any]:
    """Agrège facteurs de décision + santé du modèle + mouvement de marché.

    `explain` est le résultat de `api._explain(...)` (décomposition exacte
    du logit) — on ne relance aucun calcul de prédiction ici.
    `confidence`/`confidence_label` viennent du même résultat de prédiction
    déjà calculé par l'appelant. `mem` sert uniquement à lire les profils
    joueurs pour `form_signals` (EMA déjà en mémoire, pas de recalcul).
    `include_sentiment` : opt-in explicite (voir note Phase 3, quota NewsAPI).
    """
    factors: List[Dict[str, Any]] = list(explain.get("factors") or [])
    h2h = _h2h_factor(n1, n2)
    if h2h:
        factors.append(h2h)
    market = db.line_movement(str(event_id)) if event_id else None
    return {
        "player1": n1,
        "player2": n2,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "decisive_factor": explain.get("decisive"),
        "factors": factors,
        "form_signals": form_signals(mem, n1, n2),
        "fatigue_signals": fatigue_signals(n1, n2),
        "rest_days_signals": rest_days_signals(n1, n2),
        "opponent_quality_signals": opponent_quality_signals(mem, n1, n2),
        "clutch_signals": clutch_signals(n1, n2),
        "sentiment_signals": sentiment_signals(n1, n2) if include_sentiment else [],
        "market": market,
        "model_health": _model_health(n1, n2, surface),
    }
