"""Cerveau autonome de TennisBoss — auto-diagnostic + auto-adaptation.

Cycle toutes les 6h :
1. Drift detector     — rolling accuracy 50 picks vs all-time; alerte si chute > 5%
2. Surface audit      — accuracy par surface; danger si < 48% sur N≥30 matchs
3. Player blacklist   — joueurs mis-prédits ≥ MIN_MISS fois → réduction confidence
4. ELO blend retune  — refit β par surface depuis les matchs réglés récents
5. Telegram report   — bilan autonome envoyé si changement significatif

Données sources : settled_matches (accuracy) + value_picks (ROI réel).
Persistance     : DB meta ("intelligence_*" keys) + fichier mémoire JSON.
"""
from __future__ import annotations

import json
import math
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from . import db
from .log import log

# ── Seuils ──────────────────────────────────────────────────────────────────
MIN_MISS = 5          # mis-prédictions consécutives pour blacklister
MIN_SURF_N = 30       # minimum matchs par surface pour déclarer danger
SURF_DANGER_ACC = 0.48   # accuracy < 48% → surface en danger
DRIFT_WINDOW = 50     # fenêtre glissante pour détecter le drift
DRIFT_ALERT_PCT = 5.0    # alerte si accuracy chute de > 5 pts vs all-time
CYCLE_SECONDS = 6 * 3600  # toutes les 6h

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {
    "blacklist": [],       # noms de joueurs sur-évalués
    "surface_danger": [],  # surfaces avec accuracy < seuil
    "accuracy_drift": 0.0,
    "last_cycle_ts": 0,
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _surf_of(tournament: str) -> Optional[str]:
    t = (tournament or "").lower()
    if any(k in t for k in ("wimbledon", "grass", "halle", "queens", "hertogenbosch", "eastbourne", "nottingham", "s-hertogenbosch")):
        return "grass"
    if any(k in t for k in ("clay", "roland", "french open", "madrid", "rome", "monte-carlo", "monte carlo", "hamburg", "gstaad", "bastad", "umag", "kitzbuhel", "winston-salem", "marrakech", "estoril", "bucharest", "geneva", "lyon", "houston")):
        return "clay"
    if any(k in t for k in ("hard", "us open", "australian", "miami", "indian wells", "canada", "toronto", "montreal", "beijing", "shanghai", "paris", "cincinnati", "washington", "atlanta")):
        return "hard"
    return None


def _accuracy(rows: List[Any]) -> Optional[float]:
    judged = [r for r in rows if r["correct"] is not None]
    if not judged:
        return None
    return sum(r["correct"] for r in judged) / len(judged)


# ── 1. Drift detector ────────────────────────────────────────────────────────

def check_drift(rows: List[Any]) -> Dict[str, Any]:
    """Compare rolling 50 vs all-time. Retourne le drift en points de %."""
    alltime = _accuracy(rows)
    recent_rows = sorted(
        [r for r in rows if r["correct"] is not None],
        key=lambda r: r["date"] or "", reverse=True
    )[:DRIFT_WINDOW]
    recent = _accuracy(recent_rows)

    drift = None
    if alltime is not None and recent is not None:
        drift = (recent - alltime) * 100

    return {
        "alltime_acc": round(alltime * 100, 1) if alltime else None,
        "recent_acc": round(recent * 100, 1) if recent else None,
        "drift_pts": round(drift, 1) if drift is not None else None,
        "n_recent": len(recent_rows),
        "alert": (drift is not None and drift < -DRIFT_ALERT_PCT),
    }


# ── 2. Surface audit ─────────────────────────────────────────────────────────

def check_surfaces(rows: List[Any]) -> Dict[str, Any]:
    """Accuracy par surface. Retourne les surfaces en danger."""
    by_surf: Dict[str, List[int]] = {}
    for r in rows:
        if r["correct"] is None:
            continue
        surf = _surf_of(r.get("tournament") or r.get("tour") or "")
        if surf is None:
            surf = "unknown"
        by_surf.setdefault(surf, []).append(r["correct"])

    result = {}
    danger = []
    for surf, data in by_surf.items():
        if surf == "unknown":
            continue
        n = len(data)
        acc = sum(data) / n
        result[surf] = {"n": n, "acc": round(acc * 100, 1)}
        if n >= MIN_SURF_N and acc < SURF_DANGER_ACC:
            danger.append(surf)

    return {"by_surface": result, "danger_surfaces": danger}


# ── 3. Player blacklist ───────────────────────────────────────────────────────

def check_player_reliability(rows: List[Any]) -> Dict[str, Any]:
    """Joueurs prédits favoris mais perdus ≥ MIN_MISS fois → blacklist."""
    from collections import Counter
    miss_counts: Counter = Counter()
    for r in rows:
        if r["correct"] == 0 and r.get("pred_favorite"):
            miss_counts[r["pred_favorite"]] += 1

    blacklist = [name for name, n in miss_counts.items() if n >= MIN_MISS]
    top_miss = miss_counts.most_common(10)

    return {
        "blacklist": blacklist,
        "top_overvalued": [(n, c) for n, c in top_miss],
    }


# ── 4. ELO surface retune ────────────────────────────────────────────────────

def retune_surface_blends() -> Dict[str, Any]:
    """Relance le grid-search ELO blend par surface (via auto_learner)."""
    try:
        from . import auto_learner as _al
        learner = _al.AutoLearner()
        results = learner.tune_all_surfaces()
        return {"fitted": True, "blends": results}
    except Exception as exc:
        return {"fitted": False, "error": str(exc)}


# ── 5. Rapport Telegram ───────────────────────────────────────────────────────

def _send_report(report: Dict[str, Any]) -> None:
    try:
        from . import realtime_alerts as _ra
        alerter = _ra.get()
        if not alerter:
            return

        drift = report.get("drift", {})
        surfs = report.get("surfaces", {})
        bl = report.get("blacklist", [])
        blends = report.get("blends", {})

        lines = ["🧠 *Auto-diagnostic TennisBoss*\n"]

        # Drift
        d = drift.get("drift_pts")
        r_acc = drift.get("recent_acc")
        a_acc = drift.get("alltime_acc")
        if d is not None:
            arrow = "⬆️" if d > 0 else ("⬇️" if d < 0 else "➡️")
            alert = " ⚠️ DRIFT!" if drift.get("alert") else ""
            lines.append(f"📊 Précision: `{r_acc}%` récents vs `{a_acc}%` all-time {arrow} {d:+.1f}pts{alert}")

        # Surfaces
        by_s = surfs.get("by_surface", {})
        danger_s = surfs.get("danger_surfaces", [])
        if by_s:
            surf_line = " | ".join(f"{s}:`{v['acc']}%`(n={v['n']})" for s, v in by_s.items())
            lines.append(f"🏟 Surfaces: {surf_line}")
        if danger_s:
            lines.append(f"⚠️ Surfaces en danger: *{', '.join(danger_s)}* (<{int(SURF_DANGER_ACC*100)}% acc)")

        # Blacklist
        if bl:
            lines.append(f"🚫 Joueurs sur-évalués bloqués: _{', '.join(bl[:5])}_")

        # ELO blends
        b = blends.get("blends", {})
        if b:
            blend_line = " | ".join(f"{s}:{v:.2f}" for s, v in b.items())
            lines.append(f"⚙️ ELO blend/surface: {blend_line}")

        msg = "\n".join(lines)
        import requests as _req, os as _os
        token = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
        cid = int(_os.environ.get("TELEGRAM_OWNER_CHAT_ID") or _os.environ.get("TELEGRAM_ADMIN_ID", "0") or 0)
        if token and cid:
            _req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
                timeout=8,
            )
    except Exception as exc:
        log(f"intelligence.send_report échoué: {exc}", "WARN")


# ── Cycle principal ───────────────────────────────────────────────────────────

def run_cycle(send_telegram: bool = True) -> Dict[str, Any]:
    """Lance un cycle complet d'auto-diagnostic et d'adaptation."""
    t0 = time.time()
    log("Intelligence: cycle auto-diagnostic démarré.", "INFO")

    try:
        rows = [dict(r) for r in db.list_settled(limit=100000)]
    except Exception as exc:
        log(f"Intelligence: liste settled échouée — {exc}", "WARN")
        return {"error": str(exc)}

    drift = check_drift(rows)
    surfaces = check_surfaces(rows)
    player_data = check_player_reliability(rows)

    blacklist = player_data["blacklist"]
    danger_surfaces = surfaces["danger_surfaces"]

    # Persistance DB
    try:
        db.set_meta("intelligence_blacklist", json.dumps(blacklist))
        db.set_meta("intelligence_surface_danger", json.dumps(danger_surfaces))
        db.set_meta("intelligence_drift_pts", str(drift.get("drift_pts") or 0))
    except Exception as exc:
        log(f"Intelligence: persistance DB échouée — {exc}", "WARN")

    with _LOCK:
        _STATE["blacklist"] = blacklist
        _STATE["surface_danger"] = danger_surfaces
        _STATE["accuracy_drift"] = drift.get("drift_pts") or 0.0
        _STATE["last_cycle_ts"] = time.time()

    # Retune ELO blends si surfaces en danger
    blends_result = {}
    if danger_surfaces:
        log(f"Intelligence: surfaces en danger {danger_surfaces} → retune ELO.", "INFO")
        blends_result = retune_surface_blends()

    # Logs
    if drift.get("alert"):
        log(f"Intelligence ⚠️ DRIFT: accuracy chute {drift['drift_pts']:+.1f}pts "
            f"(récents={drift['recent_acc']}% vs all-time={drift['alltime_acc']}%)", "WARN")
    else:
        log(f"Intelligence drift: {drift.get('drift_pts', 0):+.1f}pts "
            f"(récents={drift['recent_acc']}% / all-time={drift['alltime_acc']}%)", "INFO")

    for surf, data in surfaces["by_surface"].items():
        flag = " ⚠️ DANGER" if surf in danger_surfaces else ""
        log(f"Intelligence surface {surf}: {data['acc']}% (n={data['n']}){flag}", "INFO")

    if blacklist:
        log(f"Intelligence blacklist: {blacklist}", "INFO")

    report = {
        "drift": drift,
        "surfaces": surfaces,
        "player": player_data,
        "blends": blends_result,
        "duration_s": round(time.time() - t0, 1),
    }

    if send_telegram:
        _send_report(report)

    return report


def load_from_db() -> None:
    """Charge l'état persisté au démarrage."""
    global _STATE
    try:
        bl = db.get_meta("intelligence_blacklist")
        sd = db.get_meta("intelligence_surface_danger")
        dt = db.get_meta("intelligence_drift_pts")
        with _LOCK:
            if bl:
                _STATE["blacklist"] = json.loads(bl)
            if sd:
                _STATE["surface_danger"] = json.loads(sd)
            if dt:
                _STATE["accuracy_drift"] = float(dt)
        n_bl = len(_STATE["blacklist"])
        log(f"Intelligence chargé: {n_bl} joueur(s) blacklisté(s), "
            f"surfaces en danger: {_STATE['surface_danger']}", "INFO")
    except Exception as exc:
        log(f"Intelligence.load_from_db échoué: {exc}", "WARN")


def is_blacklisted(player_name: str) -> bool:
    """Retourne True si le joueur est dans la blacklist d'apprentissage."""
    with _LOCK:
        return player_name in _STATE["blacklist"]


def is_surface_danger(surface: Optional[str]) -> bool:
    """Retourne True si la surface a une accuracy systématiquement mauvaise."""
    if not surface:
        return False
    with _LOCK:
        return surface.lower() in _STATE["surface_danger"]


def stats() -> Dict[str, Any]:
    with _LOCK:
        return {
            "blacklist": list(_STATE["blacklist"]),
            "surface_danger": list(_STATE["surface_danger"]),
            "accuracy_drift_pts": _STATE["accuracy_drift"],
            "last_cycle_ts": _STATE["last_cycle_ts"],
            "thresholds": {
                "min_miss": MIN_MISS,
                "surf_danger_acc_pct": int(SURF_DANGER_ACC * 100),
                "drift_alert_pts": DRIFT_ALERT_PCT,
            },
        }


# ── Boucle de fond ────────────────────────────────────────────────────────────

def _loop(first_delay: int = 300) -> None:
    """Lance le cycle toutes les 6h. Attend first_delay secondes au démarrage."""
    time.sleep(first_delay)
    while True:
        try:
            run_cycle(send_telegram=True)
        except Exception as exc:
            log(f"Intelligence loop erreur: {exc}", "WARN")
        time.sleep(CYCLE_SECONDS)
