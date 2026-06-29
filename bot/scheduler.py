"""Background scheduler for periodic tasks (learn, ingest, monitor).

Runs continuously with these jobs:
- Every 1h: Auto-learning cycle
- Every 6h: tennis-data.co.uk ingest (remplace Sackmann GitHub — repos supprimés)
- Every 5m: System monitor
"""

import schedule
import time
from datetime import datetime

from . import auto_learner, monitor, tennisdata_feeder
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

    def setup_jobs(self):
        """Configure job schedule."""
        schedule.every(1).hours.do(self.job_learn)
        schedule.every(6).hours.do(self.job_ingest)
        schedule.every(5).minutes.do(self.job_monitor)
        log("Scheduler: 3 jobs configured (learn 1h, ingest 6h, monitor 5m)", "INFO")

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
