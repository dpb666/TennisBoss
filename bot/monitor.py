"""System monitor : health checks, uptime tracking, alerts.

Runs continuously to:
1. Check API responsiveness
2. Monitor database consistency
3. Track model drift
4. Alert on failures
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any

from . import db, intelligence, live_api, memory, odds_api, predictor, settlement
from .log import log


class SystemMonitor:
    """Health monitoring engine."""

    def __init__(self):
        self.mem = memory.load()
        self.last_check = {}
        self.alerts = []

    def check_database(self) -> Dict[str, Any]:
        """Verify database integrity."""
        try:
            db.init()
            matches_count = len(db.all_matches_chrono())
            settled_count = len(db.list_settled())
            players_count = len(self.mem["players"])

            bh = db.bet_history_stats(days=90)
            bh_n = bh.get("n") or 0
            if bh_n < 200:
                self.alerts.append(
                    f"bet_history sparse: {bh_n} settled (need 200+ for calibration)"
                )
            return {
                "status": "ok",
                "matches": matches_count,
                "settled": settled_count,
                "players": players_count,
                "bet_history_settled_90d": bh_n,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:  # noqa: BLE001
            log(f"Database health check failed: {e}", "ERROR")
            return {"status": "error", "error": str(e)}

    def check_api_endpoints(self) -> Dict[str, Any]:
        """Test critical API endpoints.

        Envoie X-API-Token si TENNISBOSS_API_TOKEN est définie : sans ça,
        /api/status, /api/value, /api/upcoming renvoient systématiquement 401
        dès que le token est actif (voir bot/api.py::_auth), et CE check lui-même
        générait une fausse alerte à chaque cycle (5 min) depuis l'activation du
        token — le monitor était aveugle à ses propres échecs par un bug, pas
        par un vrai problème de disponibilité.

        Base URL configurable (TENNISBOSS_API_BASE_URL) : en déploiement
        systemd (tout sur le même hôte), "localhost:8000" est correct. En
        déploiement Docker avec le worker (bot/scheduler.py) dans un
        conteneur SÉPARÉ de l'API (voir docker-compose.yml), "localhost"
        dans le conteneur worker ne pointe PAS vers le conteneur API — il
        faut le nom du service Compose ("tennisboss:8000").
        """
        import urllib.request

        endpoints = {
            "health": "/health",
            "status": "/api/status",
            "value": "/api/value?limit=1",
            "upcoming": "/api/upcoming?days=1&limit=1",
        }
        results = {}
        token = os.environ.get("TENNISBOSS_API_TOKEN", "").strip()
        base = os.environ.get("TENNISBOSS_API_BASE_URL", "").strip().rstrip("/") or "http://localhost:8000"

        for name, path in endpoints.items():
            try:
                url = f"{base}{path}"
                req = urllib.request.Request(url)
                if token:
                    req.add_header("X-API-Token", token)
                # /api/value fait plusieurs appels odds-api.io séquentiels par
                # requête (voir bot/api.py::api_value) — 5s était trop court et
                # produisait de faux timeouts sans rapport avec une vraie panne.
                response = urllib.request.urlopen(req, timeout=15)
                status = response.status
                results[name] = {"status": "ok", "code": status}
            except Exception as e:  # noqa: BLE001
                results[name] = {"status": "error", "error": str(e)}
                self.alerts.append(f"API endpoint {name} failed: {e}")

        return results

    def check_odds_api(self) -> Dict[str, Any]:
        """Monitor Odds-API quota."""
        rate_limit = odds_api.rate_limit_status()
        remaining = rate_limit.get("remaining") or 0
        reset_in = rate_limit.get("reset_in_s") or 0

        status = "ok" if remaining > 10 else "warning" if remaining > 0 else "exhausted"
        if remaining == 0:
            self.alerts.append(f"Odds-API budget exhausted, reset in {reset_in}s")

        return {
            "status": status,
            "remaining": remaining,
            "reset_in_s": reset_in,
        }

    def check_model_drift(self) -> Dict[str, Any]:
        """Detect model degradation over time.

        Délègue à bot.intelligence.stats() (fenêtre glissante de
        DRIFT_WINDOW=50 picks vs précision all-time, alerte si écart >
        DRIFT_ALERT_PCT) plutôt que de comparer la précision all-time à une
        constante codée en dur (0.62) : cette dernière approche ne peut
        jamais détecter une vraie dérive RÉCENTE — une précision all-time
        est diluée par tout l'historique, une dégradation des 50 derniers
        picks y est noyée. bot/intelligence.py fait déjà ce calcul
        correctement (fenêtre glissante) ; ne pas le dupliquer en moins bien.
        """
        metrics = settlement.calibration_metrics()
        n_settled = metrics.get("n", 0)

        if n_settled < 50:
            return {"status": "low_data", "settled": n_settled}

        accuracy = metrics.get("accuracy", 0.0)
        roi = metrics.get("roi", 0.0)

        intel_stats = intelligence.stats()
        drift_pts = intel_stats.get("accuracy_drift_pts", 0.0)
        drift_threshold = intel_stats.get("thresholds", {}).get("drift_alert_pts", 5.0)
        if drift_pts <= -drift_threshold:
            self.alerts.append(
                f"Model accuracy drift detected: {drift_pts:.1f}pts vs all-time "
                f"(50 derniers picks, seuil {drift_threshold}pts)"
            )

        return {
            "status": "ok",
            "accuracy": accuracy,
            "roi_pct": roi * 100,
            "n_settled": n_settled,
            "accuracy_drift_pts": drift_pts,
        }

    def check_logging_completeness(self, *, hours: int = 24,
                                   threshold_pct: float = 90.0) -> Dict[str, Any]:
        """Alert if CLV repro-field completeness in the last N hours drops below threshold."""
        report = db.clv_logging_completeness_recent(hours=hours)
        pct = report.get("completeness_pct")
        n = report.get("n") or 0
        status = "ok"
        if n >= 3 and pct is not None and pct < threshold_pct:
            status = "warning"
            self.alerts.append(
                f"CLV logging completeness {pct}% < {threshold_pct}% "
                f"({report.get('n_complete', 0)}/{n} picks, {hours}h)"
            )
            try:
                from . import realtime_alerts as _ra
                _ra.alert_logging_completeness(pct, n, report.get("n_complete", 0), hours=hours)
            except Exception as exc:  # noqa: BLE001
                log(f"Logging completeness Telegram alert failed: {exc}", "WARN")
        return {"status": status, **report}

    def run_full_check(self) -> Dict[str, Any]:
        """Execute all health checks."""
        log("=== SYSTEM MONITOR: Full check ===", "INFO")

        checks = {
            "database": self.check_database(),
            "api_endpoints": self.check_api_endpoints(),
            "odds_api": self.check_odds_api(),
            "model_drift": self.check_model_drift(),
            "logging_completeness": self.check_logging_completeness(),
        }
        try:
            endpoint_timings = json.loads(db.get_meta("endpoint_timings") or "{}")
        except (json.JSONDecodeError, TypeError):
            endpoint_timings = {}
        if endpoint_timings:
            checks["endpoint_timings"] = endpoint_timings

        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "checks": checks,
            "alerts": self.alerts,
            "overall_status": "ok" if not self.alerts else "warning",
        }

        if self.alerts:
            log(f"Alerts: {'; '.join(self.alerts)}", "WARN")

        self.alerts = []  # Reset for next cycle
        return summary

    def continuous_monitor(self, interval_seconds: int = 300):
        """Run monitoring loop (5 minutes default)."""
        log(f"Monitor: continuous mode, check every {interval_seconds}s", "INFO")
        while True:
            try:
                result = self.run_full_check()
                db.set_meta("last_monitor_check", json.dumps(result))
            except Exception as e:  # noqa: BLE001
                log(f"Monitor error: {e}", "ERROR")

            time.sleep(interval_seconds)


def run_monitor():
    """Entry point for CLI."""
    monitor = SystemMonitor()
    return monitor.run_full_check()


def run_continuous():
    """Entry point for daemon mode."""
    monitor = SystemMonitor()
    monitor.continuous_monitor(interval_seconds=300)
