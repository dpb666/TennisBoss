"""Background scheduler for periodic tasks (learn, ingest, monitor).

Runs continuously with these jobs:
- Every 1h: Auto-learning cycle
- Every 6h: tennis-data.co.uk ingest (remplace Sackmann GitHub — repos supprimés)
- Every 5m: System monitor
"""

import schedule
import time
from datetime import date, datetime

from . import auto_learner, backup, db, monitor, push_notifications, recommendations, tennisdata_feeder
from .log import log


class TennisBossScheduler:
    """Periodic task scheduler."""

    def __init__(self):
        self.jobs_run = 0

    def job_learn(self):
        """Run auto-learning cycle."""
        log("=== SCHEDULER: Auto-learning cycle ===", "INFO")
        try:
            learner = auto_learner.AutoLearner()
            result = learner.run_full_cycle()
            log(f"Learn job complete: {result.get('elo_blends_by_surface')}", "INFO")
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Learn job failed: {e}", "ERROR")

    def job_ingest(self):
        """Ingest tennis-data.co.uk data (ATP + WTA grands tournois + Masters)."""
        log("=== SCHEDULER: tennisdata ingest ===", "INFO")
        try:
            counts = tennisdata_feeder.ingest(years=[2024, 2025, 2026], tours=["atp", "wta"])
            log(f"Ingest job complete: {counts}", "INFO")
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Ingest job failed: {e}", "ERROR")

    def job_monitor(self):
        """Run system health check."""
        log("=== SCHEDULER: Health monitor ===", "INFO")
        try:
            mon = monitor.SystemMonitor()
            result = mon.run_full_check()
            status = result.get("overall_status", "unknown")
            alerts = len(result.get("alerts", []))
            log(f"Monitor job complete: {status} ({alerts} alerts)", "INFO" if status == "ok" else "WARN")
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Monitor job failed: {e}", "ERROR")

    def job_backup(self):
        """Sauvegarde cohérente de state/tennisboss.db (voir bot/backup.py)."""
        log("=== SCHEDULER: DB backup ===", "INFO")
        try:
            path = backup.backup_now()
            if path:
                self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Backup job failed: {e}", "ERROR")

    def job_daily_digest(self):
        """Notification push quotidienne (bot/recommendations.py::daily_digest).

        Garde-fou explicite (meta "last_daily_digest_date") plutôt que de
        s'appuyer uniquement sur schedule.every().day.at(...) : un redémarrage
        du service dans la même journée ne doit jamais renvoyer un 2e digest.
        """
        log("=== SCHEDULER: Daily digest ===", "INFO")
        today = date.today().isoformat()
        if db.get_meta("last_daily_digest_date") == today:
            return
        try:
            digest = recommendations.daily_digest()
            sent = push_notifications.broadcast(digest["title"], digest["body"])
            db.set_meta("last_daily_digest_date", today)
            log(f"Daily digest sent to {sent} device(s): {digest['body']}", "INFO")
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Daily digest job failed: {e}", "ERROR")

    def setup_jobs(self):
        """Configure job schedule."""
        schedule.every(1).hours.do(self.job_learn)
        schedule.every(6).hours.do(self.job_ingest)
        schedule.every(5).minutes.do(self.job_monitor)
        schedule.every(6).hours.do(self.job_backup)
        schedule.every().day.at("09:00").do(self.job_daily_digest)
        log("Scheduler: 5 jobs configured (learn 1h, ingest 6h, monitor 5m, backup 6h, digest 9h/j)", "INFO")
        # Backup immédiat au démarrage : ne pas attendre 6h après un redémarrage
        # du service pour avoir une première sauvegarde fraîche.
        self.job_backup()

    def run_loop(self):
        """Run scheduler loop forever."""
        self.setup_jobs()
        log("Scheduler: starting event loop", "INFO")
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except KeyboardInterrupt:
                log("Scheduler: shutting down", "INFO")
                break
            except Exception as e:  # noqa: BLE001
                log(f"Scheduler loop error: {e}", "ERROR")
                time.sleep(60)


def run_scheduler():
    """Entry point for scheduler daemon."""
    scheduler = TennisBossScheduler()
    scheduler.run_loop()
