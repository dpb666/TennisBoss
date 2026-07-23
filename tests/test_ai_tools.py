"""Tests pour ai/chat/tools/registry.py et ai/chat/orchestrator.py (Phase 1
Slice 1 de docs/AI_ASSISTANT_ARCHITECTURE.md) — outils de lecture seule pour
l'assistant IA, et garde-fou : jamais d'accès à predictor/calibrate/learner.
"""
from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from unittest.mock import patch

from ai.chat import orchestrator
from ai.chat.tools import registry
from bot import api, clv, config, db


class AiToolsTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)


class TestFrozenBoundary(unittest.TestCase):
    """Garde-fou explicite : le module d'outils ne doit jamais toucher au
    moteur de prédiction gelé (predictor.py, calibrate.py, learner.py)."""

    def test_no_frozen_imports_in_registry(self):
        src = inspect.getsource(registry)
        for forbidden in ("import predictor", "from bot import predictor",
                         "import calibrate", "from bot import calibrate",
                         "import learner", "from bot import learner"):
            self.assertNotIn(forbidden, src)

    def test_no_frozen_imports_in_orchestrator(self):
        import_lines = [ln for ln in inspect.getsource(orchestrator).splitlines()
                        if ln.strip().startswith(("import ", "from "))]
        for forbidden in ("predictor", "calibrate", "learner"):
            self.assertFalse(any(forbidden in ln for ln in import_lines), forbidden)

    def test_no_write_tools_registered(self):
        forbidden_names = {"train_model", "settle_match", "place_bet",
                           "modify_memory", "bump_version", "run_learn"}
        self.assertEqual(forbidden_names & set(registry.ALL_TOOLS.keys()), set())


class TestReadDoc(unittest.TestCase):
    def test_known_doc_returns_excerpt(self):
        result = registry.read_doc("logging_schema")
        self.assertIn("path", result.data)
        self.assertTrue(result.summary)

    def test_unknown_doc_key_returns_error_not_arbitrary_path(self):
        # Défense en profondeur : une clé hors allowlist ne doit JAMAIS lire
        # un fichier arbitraire, même si le nom ressemble à un chemin.
        result = registry.read_doc("../../../etc/passwd")
        self.assertIn("error", result.data)
        self.assertEqual(result.summary, "")


class TestQueryBetHistory(AiToolsTestCase):
    def test_empty_db_flags_sparse(self):
        result = registry.query_bet_history(days=30)
        self.assertIn("n=0", result.summary)
        self.assertIn("indicatives", result.summary)

    def test_with_data_reports_n(self):
        db.log_bet_history({
            "event_key": "e1", "player1": "A", "player2": "B", "date": "2026-07-01",
            "prediction": 0.6, "pick_side": "A", "odds": 2.0, "confidence": 0.6,
            "result": 1, "profit_loss": 1.0, "surface": "hard",
        })
        result = registry.query_bet_history(days=30)
        self.assertIn("n=1", result.summary)


class TestGetCalibrationSummary(AiToolsTestCase):
    def test_empty_db_reports_zero_bins(self):
        result = registry.get_calibration_summary(days=90)
        self.assertIn("n total=0", result.summary)


class TestExplainPick(AiToolsTestCase):
    def test_no_pick_found(self):
        result = registry.explain_pick("Nobody1", "Nobody2")
        self.assertEqual(result.data, {})
        self.assertIn("Aucun pick", result.summary)

    def test_pick_found_with_repro(self):
        repro = {
            "tournament": "ATP Miami", "tournament_level": "tour", "surface": "hard",
            "model_prob_calibrated": 0.55, "market_prob": 0.5, "ev_pct": 8.0,
        }
        clv.seed_pick("ep1", "2026-07-15", "X", "Y", "X", 2.0, 0.55, 0.7, repro=repro)
        result = registry.explain_pick("X", "Y")
        self.assertIn("X @ 2.0", result.summary)
        self.assertIn("EV 8.0%", result.summary)

    def test_pick_found_reports_missing_fields(self):
        clv.seed_pick("ep2", "2026-07-15", "Z", "W", "Z", 2.0, 0.55, 0.7)
        result = registry.explain_pick("Z", "W")
        self.assertIn("manquants", result.summary)


class TestListApiEndpoints(unittest.TestCase):
    def test_returns_endpoints_and_filters_by_tag(self):
        result_all = registry.list_api_endpoints()
        self.assertGreater(len(result_all.data["endpoints"]), 10)
        result_value = registry.list_api_endpoints(tag="value")
        self.assertTrue(all("value" in e["tags"] for e in result_value.data["endpoints"]))
        self.assertLess(len(result_value.data["endpoints"]), len(result_all.data["endpoints"]))


class TestGetLoggingHealth(AiToolsTestCase):
    def test_empty_db(self):
        result = registry.get_logging_health()
        self.assertIn("n_total", result.data)
        self.assertEqual(result.data["n_total"], 0)


class TestGetLearningReport(AiToolsTestCase):
    """Phase 3 (ai/learning/analyzer.py), exposé au chat en lecture seule."""

    def test_empty_db_reports_no_suggestions(self):
        result = registry.get_learning_report()
        self.assertEqual(result.data["suggestions"], [])
        self.assertIn("Aucune suggestion", result.summary)

    def test_does_not_write_report_files(self):
        # write_files=False côté outil — jamais d'écriture disque déclenchée
        # par une simple question de chat.
        from ai.learning import analyzer
        with patch.object(analyzer, "generate_weekly_report",
                          wraps=analyzer.generate_weekly_report) as spy:
            registry.get_learning_report()
        self.assertFalse(spy.call_args.kwargs.get("write_files", True))


class TestClassifyIntents(unittest.TestCase):
    def test_bet_history_intent(self):
        self.assertIn("bet_history", orchestrator.classify_intents("Quel est notre ROI ce mois-ci ?"))

    def test_calibration_intent(self):
        self.assertIn("calibration", orchestrator.classify_intents("Sommes-nous bien calibrés à 70% ?"))

    def test_learning_report_intent(self):
        self.assertIn("learning_report",
                      orchestrator.classify_intents("Quelles suggestions avez-vous cette semaine ?"))

    def test_no_intent_for_generic_message(self):
        self.assertEqual(orchestrator.classify_intents("Bonjour, comment vas-tu ?"), [])

    def test_multiple_intents_stable_order(self):
        intents = orchestrator.classify_intents("Quel est le ROI et la calibration ?")
        self.assertEqual(intents, ["bet_history", "calibration"])


class TestRunToolsForMessage(AiToolsTestCase):
    def test_no_intent_returns_empty(self):
        ctx, tools, sources = orchestrator.run_tools_for_message("Bonjour !")
        self.assertEqual((ctx, tools, sources), ("", [], []))

    def test_bet_history_intent_calls_tool(self):
        ctx, tools, sources = orchestrator.run_tools_for_message("Quel est notre ROI ?")
        self.assertIn("query_bet_history", tools)
        self.assertIn("bet_history", sources)
        self.assertIn("bet_history", ctx)


class ApiChatAiToolsTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        api._MEM = {
            "players": {}, "elo": {}, "elo_surface": {}, "weights": {},
            "bias": 0.0, "metrics": {}, "datasets_loaded": [],
        }
        api.app.testing = True
        self.client = api.app.test_client()

    def tearDown(self):
        config.DB_FILE = self._save
        os.close(self._fd)
        os.remove(self._path)

    def test_flag_disabled_by_default_behaves_unchanged(self):
        self.assertFalse(config.AI_TOOLS_ENABLED)
        with patch.object(api.chat_mod, "build_match_context", return_value=""), \
             patch.object(api.chat_mod, "chat", return_value="reponse") as mock_chat:
            resp = self.client.post("/api/chat", json={"message": "Quel est notre ROI ?"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertNotIn("tools_called", data)
        # extra_context doit rester vide (comportement identique à avant ce flag)
        self.assertEqual(mock_chat.call_args.kwargs.get("extra_context"), "")

    def test_flag_enabled_injects_tool_context(self):
        with patch.object(config, "AI_TOOLS_ENABLED", True), \
             patch.object(api.chat_mod, "build_match_context", return_value=""), \
             patch.object(api.chat_mod, "chat", return_value="reponse") as mock_chat:
            resp = self.client.post("/api/chat", json={"message": "Quel est notre ROI ?"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("query_bet_history", data.get("tools_called", []))
        self.assertNotEqual(mock_chat.call_args.kwargs.get("extra_context"), "")

    def test_flag_enabled_but_player_context_found_skips_tools(self):
        # build_match_context non-vide -> les outils ne doivent PAS s'exécuter
        # (priorité au contexte joueur existant, cf. api_chat()).
        with patch.object(config, "AI_TOOLS_ENABLED", True), \
             patch.object(api.chat_mod, "build_match_context", return_value="Sinner: ELO 2100"), \
             patch.object(api.chat_mod, "chat", return_value="reponse") as mock_chat:
            resp = self.client.post("/api/chat", json={"message": "Quel est le ROI de Sinner ?"})
        data = resp.get_json()
        self.assertNotIn("tools_called", data)
        self.assertEqual(mock_chat.call_args.kwargs.get("extra_context"), "Sinner: ELO 2100")


if __name__ == "__main__":
    unittest.main()
