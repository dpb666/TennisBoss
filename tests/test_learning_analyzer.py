"""Tests pour ai/learning/analyzer.py — Phase 3 self-learning (suggestion-only).

Vérifie : (1) frontière figée jamais importée, (2) les helpers _xxx_findings()
classent correctement "insuffisant" vs "à investiguer" selon MIN_N_SUGGESTION,
(3) generate_weekly_report() marche de bout en bout sur une DB seedée, sans
jamais écrire ailleurs que reports/learning/.
"""
from __future__ import annotations

import inspect
import os
import tempfile
import unittest

from ai.learning import analyzer
from bot import clv, config, db


class TestNoFrozenImports(unittest.TestCase):
    def test_analyzer_never_imports_frozen_modules(self):
        src = inspect.getsource(analyzer)
        for forbidden in ("import predictor", "from bot import predictor",
                         "import calibrate", "from bot import calibrate",
                         "import learner", "from bot import learner"):
            self.assertNotIn(forbidden, src)


class TestCalibrationFindings(unittest.TestCase):
    """Les fixtures reprennent EXACTEMENT la shape réelle de
    calibration_report.build_calibration_report() (clé `calibration_bins`,
    pas `bins`) — un bug avec les mauvais noms de clé (`bins`/`n` au lieu de
    `calibration_bins`/`n_settled`) a été trouvé par un smoke-test manuel
    contre la vraie prod, PAS par ces tests unitaires initiaux : ils
    validaient la logique interne contre leurs propres suppositions de clés,
    jamais contre le contrat réel de calibration_report.py. Corrigé + verrouillé
    ici, et voir TestGenerateWeeklyReportIntegration pour un test de bout en
    bout qui aurait dû attraper ça dès le départ."""

    def test_below_threshold_is_insufficient(self):
        report = {"calibration_bins": [{"bin": "70-75%", "n": 5, "predicted": 0.72,
                                        "observed": 0.40, "gap": -0.32}]}
        out = analyzer._calibration_findings(report)
        self.assertEqual(out[0]["status"], "insuffisant")
        self.assertNotIn("suggestion", out[0])

    def test_large_gap_above_threshold_is_investigate(self):
        report = {"calibration_bins": [{"bin": "70-75%", "n": 30, "predicted": 0.72,
                                        "observed": 0.40, "gap": -0.32}]}
        out = analyzer._calibration_findings(report)
        self.assertEqual(out[0]["status"], "à investiguer")
        self.assertIn("sur-confiant", out[0]["suggestion"])
        self.assertIn("ADR-005", out[0]["suggestion"])

    def test_small_gap_above_threshold_is_ok(self):
        report = {"calibration_bins": [{"bin": "70-75%", "n": 30, "predicted": 0.72,
                                        "observed": 0.70, "gap": -0.02}]}
        out = analyzer._calibration_findings(report)
        self.assertEqual(out[0]["status"], "ok")

    def test_zero_n_bins_are_skipped(self):
        report = {"calibration_bins": [{"bin": "50-55%", "n": 0, "predicted": None,
                                        "observed": None, "gap": None}]}
        self.assertEqual(analyzer._calibration_findings(report), [])

    def test_wrong_top_level_key_yields_no_findings_not_a_crash(self):
        # Documente le bug corrigé : une shape avec la mauvaise clé ne doit
        # jamais lever, juste ne rien trouver (défensif, pas silencieusement
        # faux — voir le test d'intégration pour la vraie garantie).
        self.assertEqual(analyzer._calibration_findings({"bins": [{"n": 30}]}), [])


class TestSurfaceFindings(unittest.TestCase):
    def test_unknown_label_skipped(self):
        rows = [{"label": "unknown", "n": 50, "roi": -0.5, "yield_pct": -50.0,
                "win_rate": 0.1, "avg_clv_pct": -5.0}]
        self.assertEqual(analyzer._surface_findings(rows), [])

    def test_bad_roi_below_threshold_is_insufficient_not_suggestion(self):
        rows = [{"label": "clay", "n": 5, "roi": -0.30, "yield_pct": -30.0,
                "win_rate": 0.2, "avg_clv_pct": -10.0}]
        out = analyzer._surface_findings(rows)
        self.assertEqual(out[0]["status"], "insuffisant")

    def test_bad_roi_above_threshold_is_investigate(self):
        rows = [{"label": "clay", "n": 20, "roi": -0.30, "yield_pct": -30.0,
                "win_rate": 0.2, "avg_clv_pct": -10.0}]
        out = analyzer._surface_findings(rows)
        self.assertEqual(out[0]["status"], "à investiguer")
        self.assertIn("clay", out[0]["suggestion"])

    def test_good_roi_above_threshold_is_ok(self):
        rows = [{"label": "hard", "n": 20, "roi": 0.05, "yield_pct": 5.0,
                "win_rate": 0.4, "avg_clv_pct": 3.0}]
        out = analyzer._surface_findings(rows)
        self.assertEqual(out[0]["status"], "ok")


class TestMarketDisagreementFindings(unittest.TestCase):
    def test_model_better_above_threshold_is_investigate(self):
        report = {"buckets": [{"disagreement_range": "0.20-1.01", "n": 25,
                              "brier_model": 0.18, "brier_market": 0.22,
                              "model_better_brier": True}]}
        out = analyzer._market_disagreement_findings(report)
        self.assertEqual(out[0]["status"], "à investiguer")

    def test_market_better_is_ok(self):
        report = {"buckets": [{"disagreement_range": "0.0-0.05", "n": 25,
                              "brier_model": 0.25, "brier_market": 0.18,
                              "model_better_brier": False}]}
        out = analyzer._market_disagreement_findings(report)
        self.assertEqual(out[0]["status"], "ok")


class TestGenerateWeeklyReportIntegration(unittest.TestCase):
    def setUp(self):
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._save_db = config.DB_FILE
        config.DB_FILE = self._db_path
        db.init()
        self._report_dir = tempfile.mkdtemp()
        self._save_report_dir = analyzer.REPORT_DIR
        analyzer.REPORT_DIR = self._report_dir

    def tearDown(self):
        config.DB_FILE = self._save_db
        analyzer.REPORT_DIR = self._save_report_dir
        for path in (self._db_path, self._db_path + "-wal", self._db_path + "-shm"):
            if os.path.exists(path):
                os.remove(path)
        for name in os.listdir(self._report_dir):
            os.remove(os.path.join(self._report_dir, name))
        os.rmdir(self._report_dir)

    def _seed(self, ek, p1, p2, side, odds, winner, surface="hard"):
        repro = {"tournament": "Test Open", "tournament_level": "tour",
                 "surface": surface, "ev_pct": 10.0,
                 "predictor_version": "1.0-test", "calibration_version": "1.0-test"}
        clv.seed_pick(ek, "2026-07-10", p1, p2, side, odds, 0.60, 0.70, repro=repro)
        clv.refresh_closing(ek, side, p1, odds, 2.5)
        clv.settle(p1, p2, winner)
        db.sync_bet_history_on_settle(p1, p2, winner, event_key=ek)

    def test_empty_db_does_not_crash_and_has_no_suggestions(self):
        report = analyzer.generate_weekly_report(write_files=False)
        self.assertEqual(report["suggestions"], [])
        self.assertEqual(report["findings"], [])

    def test_write_files_false_creates_nothing(self):
        analyzer.generate_weekly_report(write_files=False)
        self.assertEqual(os.listdir(self._report_dir), [])

    def test_write_files_true_creates_md_and_json(self):
        report = analyzer.generate_weekly_report(write_files=True)
        self.assertIn("report_path", report)
        self.assertTrue(os.path.exists(report["report_path"]))
        json_path = report["report_path"].replace(".md", ".json")
        self.assertTrue(os.path.exists(json_path))

    def test_seeded_picks_produce_calibration_and_surface_findings(self):
        self._seed("e1", "A", "B", "A", 2.0, "A", surface="clay")
        self._seed("e2", "C", "D", "C", 1.8, "D", surface="clay")
        report = analyzer.generate_weekly_report(write_files=False)
        dims = {f["dimension"] for f in report["findings"]}
        self.assertIn("surface", dims)
        # Contrat réel de calibration_report.build_calibration_report() : ce
        # test aurait dû attraper le bug clé "bins"/"n" vs "calibration_bins"/
        # "n_settled" — voir le commentaire dans TestCalibrationFindings.
        self.assertIn("calibration", dims)
        self.assertEqual(report["n_calibration"], 2)
        # n=2 << MIN_N_SUGGESTION : jamais présenté comme suggestion actionnable
        self.assertEqual(report["suggestions"], [])
        surface_findings = [f for f in report["findings"] if f["dimension"] == "surface"]
        self.assertTrue(all(f["status"] == "insuffisant" for f in surface_findings))

    def test_footer_always_present_and_mentions_adr005(self):
        report = analyzer.generate_weekly_report(write_files=False)
        self.assertIn("ADR-005", report["footer"])
        self.assertIn("AUCUNE", report["footer"])


class TestRenderMarkdown(unittest.TestCase):
    def test_renders_suggestions_and_insufficient_sections(self):
        report = {
            "generated_at": "2026-07-23T10:00:00",
            "footer": "test footer",
            "suggestions": [{"dimension": "surface", "segment": "clay", "n": 30,
                            "suggestion": "surveiller clay"}],
            "n_insufficient": 1,
            "findings": [{"dimension": "tournoi", "segment": "X", "n": 3,
                         "status": "insuffisant", "observation": "obs"}],
        }
        md = analyzer.render_markdown(report)
        self.assertIn("2026-07-23", md)
        self.assertIn("surveiller clay", md)
        self.assertIn("[tournoi] X", md)

    def test_empty_suggestions_says_so(self):
        report = {
            "generated_at": "2026-07-23T10:00:00", "footer": "f",
            "suggestions": [], "n_insufficient": 0, "findings": [],
        }
        md = analyzer.render_markdown(report)
        self.assertIn("Aucune suggestion actionnable", md)


if __name__ == "__main__":
    unittest.main()
