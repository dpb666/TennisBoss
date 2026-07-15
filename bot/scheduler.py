"""Background scheduler for periodic tasks (learn, ingest, monitor, rankings).

Runs continuously with these jobs:
- Every 1h: Auto-learning cycle
- Every 6h: tennis-data.co.uk ingest + ManTennisData ATP + DB backup
- Every 12h: MCP WTA backfill
- Every 5m: System monitor
- Daily 09:00: Push digest
- Weekly Mon 03:00: Rankings ingest (ATP/WTA live)
- Weekly Sun 22:00: Calibration report → reports/calibration_report.md
"""

import schedule
import time
from datetime import date, datetime

from . import (auto_learner, backup, db, mantennisdata_feeder, mcp_feeder, monitor,
              push_notifications, ranking_feeder, recommendations, tennisdata_feeder)
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

    def job_mtd_ingest(self):
        """Ingest ManTennisData ATP (serve/return/BP/TB) — voir mantennisdata_feeder.py.

        Complète job_ingest (tennisdata.co.uk, ELO+ranking seulement, ATP+WTA)
        avec des matchs FEATURE-COMPLETS pour l'entraînement des poids/profils,
        côté ATP uniquement (pas d'équivalent WTA connu à ce jour).
        """
        log("=== SCHEDULER: ManTennisData ingest (ATP, features complètes) ===", "INFO")
        try:
            report = mantennisdata_feeder.ingest()
            log(f"MTD ingest job complete: {report}", "INFO")
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"MTD ingest job failed: {e}", "ERROR")

    def job_mcp_backfill(self):
        """Enrichit les matchs WTA déjà archivés avec les stats Match Charting
        Project (serve/return/break points) — voir mcp_feeder.py. Purement
        additif (MCP remplace 0.5 neutre pour serve/return ; BP en COALESCE) :
        sûr à rejouer souvent, mais peu de nouveaux matchs chartés par jour ->
        fréquence basse suffit.
        """
        log("=== SCHEDULER: MCP backfill (WTA, stats serve/return/BP) ===", "INFO")
        try:
            result = mcp_feeder.backfill()
            log(f"MCP backfill job complete: {result}", "INFO")
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"MCP backfill job failed: {e}", "ERROR")

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

    def job_rankings(self):
        """Ingestion hebdomadaire ATP/WTA (live-tennis.eu + archive tennis-data).

        Garde-fou meta last_rankings_ingest_week : un redémarrage du worker
        dans la même semaine ISO ne relance pas l'ingest (évite scrape HTML
        répété).
        """
        log("=== SCHEDULER: Rankings ingest (weekly) ===", "INFO")
        iso_week = datetime.now().strftime("%G-W%V")
        if db.get_meta("last_rankings_ingest_week") == iso_week:
            return
        try:
            result = ranking_feeder.ingest(
                years=[datetime.now().year, datetime.now().year - 1],
                tours=["atp", "wta"],
                live=True,
                live_limit=500,
            )
            cov = (result.get("coverage") or {})
            log(
                f"Rankings ingest: live={result.get('live_rankings_upserted', 0)}, "
                f"official_active={cov.get('official_pct_active', '?')}%, "
                f"synced={result.get('memory_synced', 0)}",
                "INFO",
            )
            db.set_meta("last_rankings_ingest_week", iso_week)
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Rankings ingest job failed: {e}", "ERROR")

    def job_bet_history_backfill(self):
        """Backfill bet_history depuis clv_log réglés (migration incrémentale).

        Garde-fou last_bet_history_backfill_date : une fois par jour max.
        """
        log("=== SCHEDULER: bet_history backfill ===", "INFO")
        today = date.today().isoformat()
        if db.get_meta("last_bet_history_backfill_date") == today:
            return
        try:
            result = db.backfill_bet_history_from_clv(limit=200)
            log(
                f"bet_history backfill: {result['added']} lignes ajoutées, "
                f"{result['patched']} surfaces corrigées",
                "INFO",
            )
            db.set_meta("last_bet_history_backfill_date", today)
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"bet_history backfill job failed: {e}", "ERROR")

    def job_espn_warm(self):
        """Prefetch ESPN scoreboards — garde le cache chaud pour engineer/today."""
        try:
            from . import espn_api
            espn_api.fetch_upcoming(days_ahead=1)
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"ESPN warm job failed: {e}", "ERROR")

    def job_calibration_report(self):
        """Rapport calibration hebdo → reports/calibration_report.md + meta summary.

        Garde-fou last_calibration_report_week : idempotent par semaine ISO.
        """
        log("=== SCHEDULER: Calibration report (weekly) ===", "INFO")
        iso_week = datetime.now().strftime("%G-W%V")
        if db.get_meta("last_calibration_report_week") == iso_week:
            return
        try:
            from . import calibration_report

            path, report = calibration_report.generate(days=90, write_file=True)
            n = report.get("n_settled", 0)
            brier = report.get("brier_score")
            verdict = report.get("verdict", "—")
            log(
                f"Calibration report: n={n}, brier={brier}, verdict={verdict}, "
                f"path={path}",
                "INFO",
            )
            db.set_meta("last_calibration_report_week", iso_week)
            db.set_meta("last_calibration_summary", str({
                "week": iso_week,
                "n_settled": n,
                "brier_score": brier,
                "verdict": verdict,
                "path": path,
            }))
            self.jobs_run += 1
        except Exception as e:  # noqa: BLE001
            log(f"Calibration report job failed: {e}", "ERROR")

    def setup_jobs(self):
        """Configure job schedule."""
        schedule.every(1).hours.do(self.job_learn)
        schedule.every(6).hours.do(self.job_ingest)
        schedule.every(6).hours.do(self.job_mtd_ingest)
        schedule.every(12).hours.do(self.job_mcp_backfill)
        schedule.every(5).minutes.do(self.job_monitor)
        schedule.every(2).minutes.do(self.job_espn_warm)
        schedule.every(6).hours.do(self.job_backup)
        schedule.every().day.at("09:00").do(self.job_daily_digest)
        schedule.every().day.at("04:30").do(self.job_bet_history_backfill)
        # Quotidien 03:00 avec garde-fou ISO week : retry auto si échec lundi.
        schedule.every().day.at("03:00").do(self.job_rankings)
        schedule.every().sunday.at("22:00").do(self.job_calibration_report)
        log("Scheduler: 11 jobs configured (learn 1h, ingest 6h, mtd_ingest 6h, "
            "mcp_backfill 12h, monitor 5m, espn_warm 2m, backup 6h, digest 9h/j, "
            "bet_history 4h30/j, rankings Mon 3h, calibration Sun 22h)", "INFO")
        # Backup immédiat au démarrage : ne pas attendre 6h après un redémarrage
        # du service pour avoir une première sauvegarde fraîche.
        self.job_backup()
        self.job_espn_warm()

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
