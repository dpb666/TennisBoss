"""Tests pour bot/mantennisdata_feeder.py (source de remplacement de
Sackmann pour l'ingestion continue ATP, voir docstring du module et
[[tennisboss-sackmann-incident]] en mémoire).

Aucun accès réseau : _match_features est pur, et fetch_year/ingest sont
testés via monkeypatch de _http_get. Le seul test réseau réel (récupération
d'un vrai tournoi ManTennisData) est fait manuellement hors suite CI.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bot import config, db, mantennisdata_feeder as mtd


def _row(**overrides) -> dict:
    base = {
        "id": "2026-9900-ag37-z371-RR", "tournament_id": "2026-9900",
        "winner_name": "Felix Auger-Aliassime", "loser_name": "Zhizhen Zhang",
        "winner_games_won": "12", "loser_games_won": "8",
        "win_service_points_won": "42", "win_service_points_total": "55",
        "los_service_points_won": "35", "los_service_points_total": "55",
        "win_first_serve_return_won": "11", "win_first_serve_return_total": "34",
        "win_second_serve_return_won": "9", "win_second_serve_return_total": "21",
        "los_first_serve_return_won": "10", "los_first_serve_return_total": "37",
        "los_second_serve_return_won": "5", "los_second_serve_return_total": "18",
        "win_break_points_saved": "1", "win_break_points_serve_total": "1",
        "los_break_points_saved": "0", "los_break_points_serve_total": "2",
        "winner_tiebreaks_won": "0", "loser_tiebreaks_won": "0",
    }
    base.update(overrides)
    return base


_TINFO = {"2026-9900": {"surface": "hard", "start_dtm": "20260518"}}


class TestMatchFeatures(unittest.TestCase):
    def test_maps_ratios_and_bp_tb_directly(self):
        m = mtd._match_features(_row(), _TINFO, "atp")
        self.assertIsNotNone(m)
        self.assertEqual(m["id"], "atp-mtd-2026-9900-ag37-z371-RR")
        self.assertEqual(m["date"], "20260518")
        self.assertEqual(m["surface"], "hard")
        self.assertAlmostEqual(m["winner"]["serve"], 42 / 55)
        self.assertAlmostEqual(m["winner"]["return1"], 11 / 34)
        self.assertAlmostEqual(m["loser"]["return2"], 5 / 18)
        self.assertEqual(m["w_bp_saved"], 1.0)
        self.assertEqual(m["l_bp_faced"], 2.0)
        self.assertEqual(m["margin"], 4)  # 12 - 8

    def test_none_when_tournament_unknown(self):
        m = mtd._match_features(_row(tournament_id="9999-0"), _TINFO, "atp")
        self.assertIsNone(m)

    def test_none_when_service_stats_missing_retirement(self):
        m = mtd._match_features(
            _row(win_service_points_total="", los_service_points_total=""),
            _TINFO, "atp",
        )
        self.assertIsNone(m)

    def test_none_when_player_name_missing(self):
        m = mtd._match_features(_row(winner_name=""), _TINFO, "atp")
        self.assertIsNone(m)

    def test_ratio_clamped_and_zero_denom_neutral(self):
        self.assertEqual(mtd._ratio(5, 0), 0.5)
        self.assertEqual(mtd._ratio(None, 10), 0.5)
        self.assertEqual(mtd._ratio(10, 10), 1.0)


class TestFetchYearCutoff(unittest.TestCase):
    def test_filters_matches_before_cutoff(self):
        rows = [_row(id="m-early"), _row(id="m-late", tournament_id="2026-9901")]
        tinfo = {
            "2026-9900": {"surface": "hard", "start_dtm": "20260101"},  # avant cutoff
            "2026-9901": {"surface": "clay", "start_dtm": "20260601"},  # après cutoff
        }
        csv_text = _rows_to_csv(rows)
        with patch.object(mtd, "_http_get", side_effect=[csv_text]), \
             patch.object(mtd, "_tournament_index", return_value=tinfo):
            matches = mtd.fetch_year(2026, cutoff_date="20260518")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], "atp-mtd-m-late")

    def test_returns_empty_on_fetch_failure(self):
        with patch.object(mtd, "_http_get", return_value=None):
            self.assertEqual(mtd.fetch_year(2026), [])


def _rows_to_csv(rows: list) -> str:
    import csv
    import io
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


class IngestTestCase(unittest.TestCase):
    def setUp(self):
        self._fd, self._path = tempfile.mkstemp(suffix=".db")
        self._save_db = config.DB_FILE
        config.DB_FILE = self._path
        db.init()
        self._save_mem = config.MEMORY_FILE
        # memory.save() écrit un tmp dans config.STATE_DIR puis os.replace vers
        # MEMORY_FILE : les deux doivent être sur le même device, donc le
        # fichier de test doit aussi vivre dans STATE_DIR (pas /tmp, souvent
        # un tmpfs séparé -> "Invalid cross-device link").
        self._mem_fd, self._mem_path = tempfile.mkstemp(suffix=".json", dir=config.STATE_DIR)
        config.MEMORY_FILE = self._mem_path

    def tearDown(self):
        config.DB_FILE = self._save_db
        config.MEMORY_FILE = self._save_mem
        os.close(self._fd)
        os.remove(self._path)
        os.close(self._mem_fd)
        os.remove(self._mem_path)


class TestIngest(IngestTestCase):
    def test_ingest_trains_and_archives_new_matches(self):
        matches = [mtd._match_features(_row(), _TINFO, "atp")]
        with patch.object(mtd, "fetch_matches", return_value=matches):
            report = mtd.ingest(years=[2026])
        self.assertEqual(report["trained"], 1)
        self.assertEqual(report["inserted"], 1)
        with db.connect() as conn:
            row = conn.execute(
                "SELECT w_bp_saved, w_tb_won, surface FROM matches WHERE id=?",
                ("atp-mtd-2026-9900-ag37-z371-RR",),
            ).fetchone()
        self.assertEqual(row["w_bp_saved"], 1.0)
        self.assertEqual(row["surface"], "hard")

    def test_ingest_does_not_retrain_same_match_twice(self):
        matches = [mtd._match_features(_row(), _TINFO, "atp")]
        with patch.object(mtd, "fetch_matches", return_value=matches):
            r1 = mtd.ingest(years=[2026])
            r2 = mtd.ingest(years=[2026])
        self.assertEqual(r1["trained"], 1)
        self.assertEqual(r2["trained"], 0)  # déjà dans mem["processed"]
        self.assertEqual(r2["inserted"], 0)  # déjà dans la DB (INSERT OR IGNORE)

    def test_ingest_empty_fetch_reports_error(self):
        with patch.object(mtd, "fetch_matches", return_value=[]):
            report = mtd.ingest(years=[2026])
        self.assertEqual(report["inserted"], 0)
        self.assertIn("error", report)


if __name__ == "__main__":
    unittest.main()
