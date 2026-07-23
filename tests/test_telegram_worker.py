"""Tests for bot.workers.telegram_worker (Phase 6 api.py decomposition)."""
from __future__ import annotations

import datetime as dt
import threading
from unittest.mock import MagicMock, patch

from bot.workers import telegram_worker as worker
from bot.workers.telegram_worker import DigestCycleState


def _conn_mock(*, pending: int = 0, total: int = 0):
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [(pending,), (total,)]
    return conn


class TestRunDigestOnce:
    def test_sends_daily_digest_at_21h(self):
        state = DigestCycleState()
        now = dt.datetime(2026, 7, 16, 21, 0, 0)

        # hour=21 >= all_settled_min_hour : run_digest_once() touche AUSSI
        # inconditionnellement db.connect() pour le bloc all-settled (même si
        # ce test ne vérifie que le digest quotidien) — non mocké auparavant,
        # d'où un échec CI-only (state/ absent sur un checkout neuf).
        with patch("bot.digest.send_daily_digest") as send_daily, patch(
            "bot.digest.send_weekly_clv_digest",
        ) as send_weekly, patch("bot.db.connect") as connect:
            connect.return_value.__enter__.return_value = _conn_mock(pending=0, total=0)
            out = worker.run_digest_once(now=now, state=state)

        send_daily.assert_called_once_with("2026-07-16")
        send_weekly.assert_not_called()
        assert out["daily_digest_sent"] is True
        assert state.sent_date == "2026-07-16"

    def test_skips_daily_if_already_sent_today(self):
        state = DigestCycleState(sent_date="2026-07-16")
        now = dt.datetime(2026, 7, 16, 21, 30, 0)

        with patch("bot.digest.send_daily_digest") as send_daily, \
             patch("bot.db.connect") as connect:
            connect.return_value.__enter__.return_value = _conn_mock(pending=0, total=0)
            out = worker.run_digest_once(now=now, state=state)

        send_daily.assert_not_called()
        assert out["daily_digest_sent"] is False

    def test_sends_weekly_clv_on_sunday_21h(self):
        state = DigestCycleState()
        # 2026-07-19 is a Sunday
        now = dt.datetime(2026, 7, 19, 21, 0, 0)

        with patch("bot.digest.send_daily_digest"), patch(
            "bot.digest.send_weekly_clv_digest",
        ) as send_weekly, patch("bot.db.connect") as connect:
            connect.return_value.__enter__.return_value = _conn_mock(pending=0, total=0)
            out = worker.run_digest_once(now=now, state=state)

        send_weekly.assert_called_once()
        assert out["weekly_clv_sent"] is True
        assert state.weekly_sent_week == now.strftime("%G-W%V")

    def test_all_settled_digest_after_14h(self):
        state = DigestCycleState()
        now = dt.datetime(2026, 7, 16, 15, 0, 0)

        with patch("bot.db.connect") as connect, patch(
            "bot.digest.send_daily_digest",
        ) as send_daily:
            connect.return_value.__enter__.return_value = _conn_mock(pending=0, total=5)
            out = worker.run_digest_once(now=now, state=state)

        send_daily.assert_called_once_with("2026-07-16")
        assert out["all_settled_digest_sent"] is True
        assert state.all_settled_notified == "2026-07-16"

    def test_skips_all_settled_before_14h(self):
        state = DigestCycleState()
        now = dt.datetime(2026, 7, 16, 10, 0, 0)

        with patch("bot.db.connect") as connect, patch("bot.digest.send_daily_digest") as send_daily:
            connect.return_value.__enter__.return_value = _conn_mock(pending=0, total=5)
            out = worker.run_digest_once(now=now, state=state)

        send_daily.assert_not_called()
        assert out["all_settled_digest_sent"] is False

    def test_skips_all_settled_when_few_picks(self):
        state = DigestCycleState()
        now = dt.datetime(2026, 7, 16, 16, 0, 0)

        with patch("bot.db.connect") as connect, patch("bot.digest.send_daily_digest") as send_daily:
            connect.return_value.__enter__.return_value = _conn_mock(pending=0, total=2)
            out = worker.run_digest_once(now=now, state=state)

        send_daily.assert_not_called()
        assert out["all_settled_digest_sent"] is False


class TestRunDigestLoop:
    def test_stops_on_event_before_first_cycle(self):
        stop = threading.Event()
        stop.set()
        with patch.object(worker, "run_digest_once") as once:
            worker.run_digest_loop(interval=60, stop_event=stop)
        once.assert_not_called()

    def test_runs_one_cycle_then_stops(self):
        stop = threading.Event()

        def _once_and_stop(**_kwargs):
            stop.set()
            return {}

        with patch.object(worker, "run_digest_once", side_effect=_once_and_stop):
            worker.run_digest_loop(interval=999, stop_event=stop)


class TestHandleTelegramMessage:
    def test_access_denied_for_non_admin(self):
        sent: list[tuple[int, str]] = []

        def _send(chat_id: int, text: str) -> None:
            sent.append((chat_id, text))

        action = worker.handle_telegram_message(
            "/picks", 999, admin_id=123, send_message=_send,
        )
        assert action == "access_denied"
        assert sent == [(999, "Accès restreint.")]

    def test_picks_command(self):
        sent: list[tuple[int, str]] = []

        with patch("bot.digest.build_picks_summary", return_value="picks text"):
            action = worker.handle_telegram_message(
                "/picks", 123, admin_id=123,
                send_message=lambda c, t: sent.append((c, t)),
            )

        assert action == "picks"
        assert sent == [(123, "picks text")]

    def test_clv_weekly_before_clv_prefix(self):
        sent: list[tuple[int, str]] = []

        with patch("bot.digest.build_weekly_clv_report", return_value="weekly"), patch(
            "bot.digest.build_clv_report",
        ) as clv:
            action = worker.handle_telegram_message(
                "/clv-weekly", 123, admin_id=123,
                send_message=lambda c, t: sent.append((c, t)),
            )

        assert action == "clv-weekly"
        clv.assert_not_called()
        assert sent == [(123, "weekly")]

    def test_start_command(self):
        sent: list[tuple[int, str]] = []
        worker.handle_telegram_message(
            "/start", 123, admin_id=0,
            send_message=lambda c, t: sent.append((c, t)),
        )
        assert len(sent) == 1
        assert "TennisBoss" in sent[0][1]


class TestFreeTextChatForward:
    """Chat texte libre (2026-07-23) : bascule sur bot.chat.answer() en process,
    mode=analyst. Remplace un ancien forward HTTP vers 127.0.0.1:8001 (port de
    l'ex-service FastAPI app/, retiré le 2026-07-13) — chaque message texte
    échouait silencieusement depuis, avant ce fix."""

    def setup_method(self):
        worker._chat_history.clear()

    def teardown_method(self):
        worker._chat_history.clear()

    def test_calls_answer_in_process_with_analyst_mode(self):
        sent: list[tuple[int, str]] = []
        with patch("bot.memory.load", return_value={"players": {}}), \
             patch("bot.chat.answer", return_value={
                 "reply": "Sinner est favori.", "context_used": True,
                 "agent": None, "mode": "analyst", "tools_called": [], "sources": [],
             }) as answer_mock:
            action = worker.handle_telegram_message(
                "Qui va gagner ce soir ?", 123, admin_id=123,
                send_message=lambda c, t: sent.append((c, t)),
            )
        assert action == "chat"
        assert sent == [(123, "Sinner est favori.")]
        assert answer_mock.call_args.kwargs.get("mode") == "analyst"
        assert answer_mock.call_args.args[0] == "Qui va gagner ce soir ?"

    def test_no_longer_calls_the_dead_fastapi_port(self):
        with patch("bot.memory.load", return_value={"players": {}}), \
             patch("bot.chat.answer", return_value={
                 "reply": "ok", "context_used": False, "agent": None,
                 "mode": "analyst", "tools_called": [], "sources": [],
             }), patch("requests.post") as post_mock:
            worker.handle_telegram_message(
                "Bonjour", 123, admin_id=123, send_message=lambda c, t: None,
            )
        post_mock.assert_not_called()

    def test_sources_are_appended_as_footer(self):
        sent: list[tuple[int, str]] = []
        with patch("bot.memory.load", return_value={"players": {}}), \
             patch("bot.chat.answer", return_value={
                 "reply": "Le ROI 30j est de +5%.", "context_used": False,
                 "agent": None, "mode": "analyst",
                 "tools_called": ["query_bet_history"], "sources": ["bet_history"],
             }):
            worker.handle_telegram_message(
                "Quel est notre ROI ?", 123, admin_id=123,
                send_message=lambda c, t: sent.append((c, t)),
            )
        assert "bet_history" in sent[0][1]
        assert sent[0][1].startswith("Le ROI 30j est de +5%.")

    def test_history_accumulates_across_messages(self):
        with patch("bot.memory.load", return_value={"players": {}}), \
             patch("bot.chat.answer", return_value={
                 "reply": "reponse", "context_used": False, "agent": None,
                 "mode": "analyst", "tools_called": [], "sources": [],
             }) as answer_mock:
            worker.handle_telegram_message(
                "premier message", 123, admin_id=123, send_message=lambda c, t: None,
            )
            worker.handle_telegram_message(
                "deuxieme message", 123, admin_id=123, send_message=lambda c, t: None,
            )
        second_call_history = answer_mock.call_args_list[1].args[1]
        assert {"role": "user", "content": "premier message"} in second_call_history
        assert {"role": "assistant", "content": "reponse"} in second_call_history

    def test_history_is_bounded(self):
        with patch("bot.memory.load", return_value={"players": {}}), \
             patch("bot.chat.answer", return_value={
                 "reply": "r", "context_used": False, "agent": None,
                 "mode": "analyst", "tools_called": [], "sources": [],
             }):
            for i in range(20):
                worker.handle_telegram_message(
                    f"message {i}", 123, admin_id=123, send_message=lambda c, t: None,
                )
        assert len(worker._chat_history[123]) <= worker._CHAT_HISTORY_MAX_MESSAGES

    def test_clear_empties_history_without_network_call(self):
        worker._chat_history[123] = [{"role": "user", "content": "ancien"}]
        sent: list[tuple[int, str]] = []
        with patch("requests.post") as post_mock:
            action = worker.handle_telegram_message(
                "/clear", 123, admin_id=123,
                send_message=lambda c, t: sent.append((c, t)),
            )
        assert action == "clear"
        assert 123 not in worker._chat_history
        assert sent == [(123, "Historique effacé.")]
        post_mock.assert_not_called()

    def test_llm_failure_still_reports_error_message(self):
        sent: list[tuple[int, str]] = []
        with patch("bot.memory.load", return_value={"players": {}}), \
             patch("bot.chat.answer", side_effect=RuntimeError("timeout")):
            worker.handle_telegram_message(
                "Bonjour", 123, admin_id=123,
                send_message=lambda c, t: sent.append((c, t)),
            )
        assert "Erreur chat" in sent[0][1]


class TestPollOnce:
    def test_processes_updates_and_advances_offset(self):
        updates = [
            {"update_id": 10, "message": {"chat": {"id": 123}, "text": "/stats"}},
            {"update_id": 11, "message": {"chat": {"id": 123}, "text": ""}},
        ]
        sent: list[tuple[int, str]] = []

        def _fetch(_token: str, _offset: int):
            return updates

        with patch("bot.digest.build_global_stats", return_value="stats"):
            new_offset, handled = worker.poll_once(
                token="tok",
                admin_id=123,
                offset=0,
                send_message=lambda c, t: sent.append((c, t)),
                get_updates_fn=_fetch,
            )

        assert new_offset == 12
        assert handled == 1
        assert sent == [(123, "stats")]


class TestRunPollLoop:
    def test_exits_immediately_without_token(self):
        with patch.object(worker, "poll_once") as poll:
            worker.run_poll_loop(token="", stop_event=threading.Event())
        poll.assert_not_called()

    def test_survives_get_updates_failure(self):
        stop = threading.Event()
        calls = {"n": 0}

        def _fail_then_stop(**_kwargs):
            calls["n"] += 1
            if calls["n"] >= 1:
                stop.set()
            raise OSError("network")

        with patch.object(worker, "log"), patch.object(worker, "poll_once", side_effect=_fail_then_stop):
            worker.run_poll_loop(token="tok", admin_id=0, stop_event=stop, poll_sleep_s=0)

        assert calls["n"] == 1


class TestApiShim:
    def test_digest_loop_delegates(self):
        from bot import api

        with patch("bot.workers.telegram_worker.run_digest_loop") as run_digest:
            api._digest_loop()
        run_digest.assert_called_once()

    def test_tg_poll_loop_delegates(self):
        from bot import api

        with patch("bot.workers.telegram_worker.run_poll_loop") as run_poll:
            api._tg_poll_loop()
        run_poll.assert_called_once()
