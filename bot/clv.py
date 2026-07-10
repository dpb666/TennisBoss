"""Closing Line Value (CLV) — la preuve d'edge de TennisBoss.

Le CLV mesure si nos picks battent la cote de CLÔTURE (le dernier prix avant
le coup d'envoi). C'est l'indicateur AVANCÉ de profitabilité : un edge réel se
voit sur le CLV (~30-50 paris) bien avant que le ROI converge (~200 paris,
très bruyant). On pilote sur le CLV, on confirme sur le ROI.

Flux :
1. seed_pick      : à la décision (onglet Value), on logue cote + proba modèle.
2. refresh_closing: à chaque quote pré-match, on écrase la closing line (le
   dernier quote avant le départ = la vraie clôture). src='snapshot'.
   Fallback 'last_seen' = cote du pick si aucun quote frais n'a été capté.
3. settle         : au résultat, on calcule CLV%, P&L flat (1u) et P&L Kelly.

P&L :
- flat  : mise fixe 1 unité. won -> (cote-1), lost -> -1.  (edge brut, peu bruité)
- kelly : fraction de bankroll (Kelly 0.25 sur la proba modèle). Réaliste.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db

try:
    from app.trading.kelly_dynamic import kelly_fraction
except Exception:  # noqa: BLE001 — app/ optionnel hors contexte serveur
    def kelly_fraction(prob: float, odds: float, kelly_pct: float = 0.25) -> float:
        if prob <= 0 or prob >= 1 or odds <= 1:
            return 0.0
        edge = prob * odds - 1.0
        if edge <= 0:
            return 0.0
        return max(0.0, (edge / (odds - 1.0)) * kelly_pct)


# Fenêtre de capture de la closing line : un quote vu à ≤ ce délai du départ
# est considéré "closing". On reste large car upcoming_only filtre déjà les
# matchs commencés — le dernier quote AVANT départ fait foi.
CLOSING_WINDOW_MIN = 120


def seed_pick(event_key: str, date: str, p1: str, p2: str, side: str,
              pick_odds: float, pick_prob: float, confidence: float,
              honeypot: Optional[Dict[str, Any]] = None) -> None:
    """Logue un pick à l'instant de la décision (idempotent sur event_key)."""
    if not event_key or not pick_odds or pick_odds <= 1.0:
        return
    db.log_clv_pick(event_key, date, p1, p2, side, float(pick_odds),
                    float(pick_prob), float(confidence), honeypot=honeypot)


def refresh_closing(event_key: str, side: str,
                    home: str, home_odds: float, away_odds: float,
                    match_date: str = "") -> None:
    """Met à jour la closing line d'un pick avec un quote frais.

    `side` = joueur misé ; on prend sa cote selon qu'il est home ou away.
    `match_date` (ISO) : si fourni, on marque 'closing' seulement dans la
    fenêtre 0-2h pré-match ; avant ce délai on stocke sous 'pre_closing'
    pour suivre le drift sans polluer la closing line finale.
    """
    import datetime as _dt
    closing = home_odds if side == home else away_odds
    if not closing or closing <= 1.0:
        return

    # Déterminer si on est dans la fenêtre pré-match (<2h)
    src = "snapshot"
    if match_date:
        try:
            match_ts = _dt.datetime.fromisoformat(str(match_date).replace("Z", "+00:00"))
            now_utc = _dt.datetime.now(_dt.timezone.utc)
            hours_to_match = (match_ts - now_utc).total_seconds() / 3600
            if hours_to_match > 2.0:
                src = "pre_closing"   # trop tôt — on stocke mais pas comme final
        except Exception:
            pass

    db.update_clv_closing(event_key, float(closing), src)


def _name_vars(name: str):
    """Last,First ↔ First Last variants pour la comparaison."""
    variants = {name}
    if ", " in name:
        parts = name.split(", ", 1)
        variants.add(f"{parts[1]} {parts[0]}")
    elif " " in name:
        parts = name.rsplit(" ", 1)
        variants.add(f"{parts[1]}, {parts[0]}")
    return variants


def settle(p1: str, p2: str, winner_name: str) -> bool:
    """Règle un pick CLV au résultat. True si un pick a été réglé.

    Appariement par PAIRE de joueurs (la clé d'event diffère entre la capture
    odds-api et la source de résultats). Fallback closing : si aucune closing
    line n'a été captée, on retombe sur la cote du pick (CLV=0, flag
    'last_seen') pour ne pas perdre le P&L.
    """
    p1_vars = _name_vars(p1)
    p2_vars = _name_vars(p2)
    winner_vars = _name_vars(winner_name)

    unsettled = db.list_clv_unsettled()
    row = None
    for r in unsettled:
        r1_vars = _name_vars(r["player1"])
        r2_vars = _name_vars(r["player2"])
        if (r1_vars & p1_vars and r2_vars & p2_vars) or \
           (r1_vars & p2_vars and r2_vars & p1_vars):
            row = r
            break
    if row is None:
        return False
    event_key = row["event_key"]

    pick_odds = float(row["pick_odds"] or 0)
    if pick_odds <= 1.0:
        return False

    # Fallback closing line si jamais captée.
    if row["closing_odds"] is None:
        db.update_clv_closing(event_key, pick_odds, "last_seen")

    pick_side_vars = _name_vars(row["pick_side"])
    won = 1 if pick_side_vars & winner_vars else 0
    pnl_flat = (pick_odds - 1.0) if won else -1.0

    frac = kelly_fraction(float(row["pick_prob"] or 0), pick_odds, 0.25)
    pnl_kelly = frac * (pick_odds - 1.0) if won else -frac

    db.update_clv_result(event_key, won, round(pnl_flat, 4), round(pnl_kelly, 5))
    return True


def _ci95(p: float, n: int) -> float:
    """Demi-intervalle de confiance 95% d'une proportion (approx normale)."""
    if n <= 0:
        return 0.0
    return round(1.96 * ((p * (1 - p) / n) ** 0.5) * 100, 1)


def _agg(rows: List[Any]) -> Dict[str, Any]:
    settled = [r for r in rows if r["result"] is not None]
    with_clv = [r for r in rows if r["clv_pct"] is not None]
    n = len(settled)
    if not with_clv and n == 0:
        return {"n": 0}

    out: Dict[str, Any] = {"n": len(rows), "n_picks": len(rows), "n_settled": n}

    if with_clv:
        clvs = [r["clv_pct"] for r in with_clv]
        beats = [r["beat_closing"] for r in with_clv if r["beat_closing"] is not None]
        beat_rate = (sum(beats) / len(beats)) if beats else 0.0
        out["avg_clv_pct"] = round(sum(clvs) / len(clvs), 2)
        out["beat_closing_pct"] = round(beat_rate * 100, 1)
        out["beat_closing_ci95"] = _ci95(beat_rate, len(beats))
        out["n_clv"] = len(with_clv)

    if n:
        out["roi_flat_pct"] = round(sum(r["pnl_flat"] for r in settled) / n * 100, 1)
        out["pnl_kelly_units"] = round(sum(r["pnl_kelly"] for r in settled), 3)
        out["win_rate_pct"] = round(sum(r["result"] for r in settled) / n * 100, 1)
    return out


def stats() -> Dict[str, Any]:
    """Dashboard CLV honnête : global, par palier de confiance, par échantillon.

    `verdict` traduit les chiffres en langage investisseur :
    - edge prouvé  : beat_closing > 52% ET borne basse IC95 > 50% ET n_clv ≥ 30
    - prometteur   : avg_clv_pct > 0 mais échantillon trop petit
    - pas d'edge   : CLV ≤ 0 sur échantillon suffisant
    - insuffisant  : pas assez de données réglées

    `scanner` = picks post-filtre seulement (depuis Bet365 + dead zone, 2026-07-03).
    Les anciens picks (pre-filtre, juin 2026) sont contaminés par des règles d'avant.
    """
    rows = db.list_clv()
    # Scanner-only = picks après activation du filtre complet (Bet365 + dead zone)
    SCANNER_CUTOFF = "2026-07-03"
    scanner_rows = [r for r in rows if (r["pick_ts"] or "") >= SCANNER_CUTOFF]

    glob = _agg(rows)
    scanner = _agg(scanner_rows)

    def tier(pool: List[Any], lo: float, hi: float) -> List[Any]:
        return [r for r in pool if r["confidence"] is not None
                and lo <= r["confidence"] < hi]

    # Post-filtre uniquement (comme "scanner") : les anciens picks (avant le
    # durcissement du 2026-07-03) faussent la comparaison par confiance —
    # voir [[tennisboss-clv-edge]].
    by_conf = {
        "high":   _agg(tier(scanner_rows, 0.75, 1.01)),
        "medium": _agg(tier(scanner_rows, 0.60, 0.75)),
        "low":    _agg(tier(scanner_rows, 0.0, 0.60)),
    }

    # Verdict basé sur le scanner (post-filtre) si assez de data, sinon global
    verdict_src = scanner if scanner.get("n_clv", 0) >= 15 else glob
    verdict, label = _verdict(verdict_src)
    return {
        "global": glob,
        "scanner": scanner,      # stats post-filtre (signal propre)
        "by_confidence": by_conf,
        "verdict": verdict,
        "verdict_label": label,
        "note": ("CLV% = (cote_pick/cote_clôture − 1)×100. 'Beat closing' = on a "
                 "verrouillé un meilleur prix que la clôture. Indicateur AVANCÉ "
                 "d'edge : fiable dès ~30-50 paris, avant le ROI."),
    }


def _verdict(glob: Dict[str, Any]) -> tuple:
    n_clv = glob.get("n_clv", 0)
    avg = glob.get("avg_clv_pct")
    beat = glob.get("beat_closing_pct")
    ci = glob.get("beat_closing_ci95", 0)
    if not n_clv or n_clv < 15 or avg is None:
        return "insuffisant", "📊 Pas encore assez de paris réglés — continue à logguer."
    if beat is not None and beat - ci > 50.0 and beat > 52.0 and n_clv >= 30:
        return "edge_prouvé", f"✅ Edge réel : tu bats la clôture {beat}% du temps (n={n_clv})."
    if avg > 0:
        return "prometteur", f"🟡 CLV positif (+{avg}%) mais échantillon trop court (n={n_clv})."
    return "pas_d_edge", f"🔴 CLV ≤ 0 ({avg}%) sur n={n_clv} — pas d'edge mesurable à ce stade."
