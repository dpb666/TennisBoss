"""Apprentissage des erreurs du modèle à partir des résultats réels.

Principe : on segmente les picks réglés par (EV bucket, fourchette de cotes,
surface) et on calcule le ROI réel. Quand un segment a ≥ MIN_N picks et
ROI < ROI_THRESHOLD → zone dangereuse. Le scanner et l'endpoint /picks
consultent `is_danger_zone()` avant d'alerter.

Les seuils appris sont persistés dans DB (meta "danger_zones_json") et
rechargés au démarrage. Mise à jour automatique à chaque settlement batch.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from . import db
from .log import log

# Paramètres de détection
MIN_N = 7           # minimum de picks réglés pour déclarer une zone dangereuse
ROI_THRESHOLD = -0.12   # ROI < -12% → danger

_LOCK = threading.Lock()
_DANGER_ZONES: List[Dict] = []   # chargé depuis DB au démarrage + mis à jour


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def _ev_bucket(ev: float) -> str:
    if ev < 12:
        return "8-12"
    if ev < 18:
        return "12-18"
    if ev < 25:
        return "18-25"
    return "25+"


def _odds_bucket(odds: float) -> str:
    if odds < 2.0:
        return "1.4-2.0"
    if odds < 3.0:
        return "2.0-3.0"
    if odds < 4.0:
        return "3.0-4.0"
    return "4.0+"


def _surf_key(surface: Optional[str]) -> str:
    if not surface:
        return "unknown"
    return surface.lower()


# ---------------------------------------------------------------------------
# Calcul des zones dangereuses
# ---------------------------------------------------------------------------

def _compute_zones(rows: List[Any]) -> List[Dict]:
    """Calcule les ROI par segment et retourne les zones dangereuses."""
    # Agrégation par (ev_bucket, odds_bucket, surface)
    buckets: Dict[Tuple, List[float]] = {}
    for r in rows:
        if r["result"] is None or r["pnl"] is None:
            continue
        ev = float(r["ev"] or 0)
        odds = float(r["odds"] or 0)
        surf = _surf_key(r.get("surface"))
        if ev < 8 or odds < 1.4:
            continue
        key = (_ev_bucket(ev), _odds_bucket(odds), surf)
        buckets.setdefault(key, []).append(float(r["pnl"]))

    # Aussi agréger par ev_bucket seul (signal plus fort sur petit échantillon)
    ev_only: Dict[str, List[float]] = {}
    for r in rows:
        if r["result"] is None or r["pnl"] is None:
            continue
        ev = float(r["ev"] or 0)
        if ev < 8:
            continue
        b = _ev_bucket(ev)
        ev_only.setdefault(b, []).append(float(r["pnl"]))

    zones = []

    # Zones fines (ev × odds × surface)
    for (ev_b, odds_b, surf), pnls in buckets.items():
        n = len(pnls)
        if n < MIN_N:
            continue
        roi = sum(pnls) / n
        if roi < ROI_THRESHOLD:
            zones.append({
                "type": "fine",
                "ev_bucket": ev_b,
                "odds_bucket": odds_b,
                "surface": surf,
                "n": n,
                "roi": round(roi, 3),
            })

    # Zones larges (ev seul) — seuil plus haut car signal fort
    for ev_b, pnls in ev_only.items():
        n = len(pnls)
        if n < MIN_N:
            continue
        roi = sum(pnls) / n
        if roi < ROI_THRESHOLD:
            zones.append({
                "type": "broad",
                "ev_bucket": ev_b,
                "odds_bucket": None,
                "surface": None,
                "n": n,
                "roi": round(roi, 3),
            })

    return zones


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def update() -> Dict[str, Any]:
    """Recalcule les zones dangereuses depuis les picks réglés. Sauvegarde en DB."""
    global _DANGER_ZONES
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT ev, odds, surface, result, pnl FROM value_picks "
                "WHERE result IS NOT NULL"
            ).fetchall()
        rows = [dict(r) for r in rows]
    except Exception as exc:
        log(f"mistake_learner.update: lecture DB échouée — {exc}", "WARN")
        return {"error": str(exc)}

    zones = _compute_zones(rows)

    with _LOCK:
        _DANGER_ZONES = zones

    try:
        db.set_meta("danger_zones_json", json.dumps(zones))
    except Exception as exc:
        log(f"mistake_learner.update: sauvegarde DB échouée — {exc}", "WARN")

    # Log synthétique
    if zones:
        for z in zones:
            extra = f" odds={z['odds_bucket']}" if z.get('odds_bucket') else ""
            surf = f" surf={z['surface']}" if z.get('surface') and z['surface'] != 'unknown' else ""
            log(f"Danger zone: EV {z['ev_bucket']}%{extra}{surf} → ROI {z['roi']*100:.1f}% (n={z['n']})", "INFO")
    else:
        log("Danger zones: aucune zone dangereuse détectée.", "INFO")

    return {"zones": zones, "n_picks": len(rows)}


def load_from_db() -> None:
    """Charge les zones sauvegardées au démarrage (avant le premier update)."""
    global _DANGER_ZONES
    try:
        raw = db.get_meta("danger_zones_json")
        if raw:
            with _LOCK:
                _DANGER_ZONES = json.loads(raw)
            log(f"Danger zones chargées depuis DB: {len(_DANGER_ZONES)} zone(s).", "INFO")
    except Exception:
        pass


def is_danger_zone(ev_pct: float, odds: float,
                   surface: Optional[str] = None) -> bool:
    """Retourne True si ce pick tombe dans une zone apprise comme dangereuse.

    Priorise les zones fines (ev × odds × surface). Si aucune correspondance
    fine, vérifie les zones larges (ev seul).
    """
    ev_b = _ev_bucket(ev_pct)
    odds_b = _odds_bucket(odds)
    surf = _surf_key(surface)

    with _LOCK:
        zones = list(_DANGER_ZONES)

    for z in zones:
        if z["ev_bucket"] != ev_b:
            continue
        if z["type"] == "fine":
            if z.get("odds_bucket") and z["odds_bucket"] != odds_b:
                continue
            if z.get("surface") and z["surface"] not in ("unknown", surf):
                continue
        # match
        return True
    return False


def stats() -> Dict[str, Any]:
    """Dashboard pour l'API — zones actuelles + timestamp dernier update."""
    with _LOCK:
        zones = list(_DANGER_ZONES)
    return {
        "n_zones": len(zones),
        "zones": zones,
        "thresholds": {
            "min_n": MIN_N,
            "roi_threshold_pct": round(ROI_THRESHOLD * 100, 1),
        },
    }
