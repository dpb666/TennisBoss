"""Telegram digest and bot polling workers.

Extracted from ``bot/api.py::_digest_loop`` and ``_tg_poll_loop`` (api.py decomposition Phase 6).

Responsibilities:
- Daily digest at 21h + weekly CLV on Sunday
- "All settled" notification when today's picks are fully settled (>=14h, >=3 picks)
- Telegram long-polling bot (/picks, /digest, /clear, IA chat forward)

Does **not** touch prediction, value scanner, or settlement logic.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from ..log import log

DEFAULT_DIGEST_INTERVAL_S = 60
DEFAULT_DIGEST_HOUR = 21
ALL_SETTLED_MIN_HOUR = 14
ALL_SETTLED_MIN_PICKS = 3
DEFAULT_POLL_SLEEP_S = 1
POLL_GET_UPDATES_TIMEOUT = 16
POLL_LONG_POLL_TIMEOUT = 10


@dataclass
class DigestCycleState:
    sent_date: str = ""
    all_settled_notified: str = ""
    weekly_sent_week: str = ""


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


def run_digest_once(
    *,
    now: Optional[dt.datetime] = None,
    state: Optional[DigestCycleState] = None,
    digest_hour: int = DEFAULT_DIGEST_HOUR,
    all_settled_min_hour: int = ALL_SETTLED_MIN_HOUR,
    min_picks_for_all_settled: int = ALL_SETTLED_MIN_PICKS,
) -> Dict[str, Any]:
    """Run one digest notification check (testable, no sleep)."""
    from .. import db, digest as digest_mod

    _now = now or dt.datetime.now()
    _state = state if state is not None else DigestCycleState()
    today = _now.date().isoformat()

    summary: Dict[str, Any] = {
        "today": today,
        "hour": _now.hour,
        "daily_digest_sent": False,
        "weekly_clv_sent": False,
        "all_settled_digest_sent": False,
    }

    if _now.hour == digest_hour and _state.sent_date != today:
        digest_mod.send_daily_digest(today)
        _state.sent_date = today
        summary["daily_digest_sent"] = True
        iso_week = _now.strftime("%G-W%V")
        if _now.weekday() == 6 and _state.weekly_sent_week != iso_week:
            digest_mod.send_weekly_clv_digest()
            _state.weekly_sent_week = iso_week
            summary["weekly_clv_sent"] = True

    if _state.all_settled_notified != today and _now.hour >= all_settled_min_hour:
        with db.connect() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM value_picks WHERE date LIKE ? AND result IS NULL",
                (f"{today}%",),
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM value_picks WHERE date LIKE ? AND odds<=5.0",
                (f"{today}%",),
            ).fetchone()[0]
        if pending == 0 and total >= min_picks_for_all_settled:
            digest_mod.send_daily_digest(today)
            _state.all_settled_notified = today
            summary["all_settled_digest_sent"] = True

    return summary


def run_digest_loop(
    *,
    interval: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    state: Optional[DigestCycleState] = None,
) -> None:
    """Daemon loop: check digest triggers every ``interval`` seconds."""
    _interval = interval if interval is not None else _env_int(
        "DIGEST_INTERVAL_S", DEFAULT_DIGEST_INTERVAL_S,
    )
    _stop = stop_event or threading.Event()
    _state = state or DigestCycleState()

    while not _stop.is_set():
        try:
            run_digest_once(state=_state)
        except Exception as exc:  # noqa: BLE001 — worker must survive cycle errors
            log(f"Digest loop (notifications quotidiennes) échoué ({exc}).", "WARN")
        if _stop.wait(_interval):
            break


def start_digest_thread(
    *,
    interval: Optional[int] = None,
) -> threading.Thread:
    """Start the digest worker in a daemon thread (used by ``api.serve()``)."""
    thread = threading.Thread(
        target=run_digest_loop,
        kwargs={"interval": interval},
        daemon=True,
        name="telegram-digest-worker",
    )
    thread.start()
    return thread


def _make_send_message(token: str) -> Callable[[int, str], None]:
    base = f"https://api.telegram.org/bot{token}"

    def _send(chat_id: int, text: str) -> None:
        try:
            requests.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"Envoi Telegram échoué vers chat {chat_id} ({exc}).", "WARN")

    return _send


def handle_telegram_message(
    text: str,
    chat_id: int,
    *,
    admin_id: int,
    send_message: Callable[[int, str], None],
) -> Optional[str]:
    """Handle one Telegram message. Returns action label for tests."""
    if admin_id and chat_id != admin_id:
        send_message(chat_id, "Accès restreint.")
        return "access_denied"

    from .. import digest as digest_mod

    if text.startswith("/picks"):
        send_message(chat_id, digest_mod.build_picks_summary())
        return "picks"
    if text.startswith("/value"):
        send_message(chat_id, digest_mod.build_value_open())
        return "value"
    if text.startswith("/clv-weekly"):
        send_message(chat_id, digest_mod.build_weekly_clv_report())
        return "clv-weekly"
    if text.startswith("/clv"):
        send_message(chat_id, digest_mod.build_clv_report())
        return "clv"
    if text.startswith("/digest"):
        send_message(chat_id, digest_mod.build_digest())
        return "digest"
    if text.startswith("/stats"):
        send_message(chat_id, digest_mod.build_global_stats())
        return "stats"
    if text.startswith("/intel"):
        send_message(chat_id, digest_mod.build_intel_report())
        return "intel"
    if text.startswith("/roi"):
        send_message(chat_id, digest_mod.build_roi_breakdown())
        return "roi"
    if text.startswith("/scanner"):
        send_message(chat_id, digest_mod.build_scanner_status())
        return "scanner"
    if text.startswith("/start"):
        send_message(
            chat_id,
            "🎾 *TennisBoss*\n\n"
            "/picks — picks du jour\n"
            "/value — picks ouverts\n"
            "/clv — Closing Line Value\n"
            "/clv-weekly — CLV des 7 derniers jours\n"
            "/roi — ROI par tranche EV\n"
            "/intel — cerveau IA (blacklist, zones)\n"
            "/scanner — état du scanner 90s\n"
            "/stats — bilan global\n"
            "/digest — rapport complet\n"
            "/clear — reset chat\n\n"
            "_Ou posez n'importe quelle question en texte libre._",
        )
        return "start"
    if text.startswith("/clear"):
        try:
            requests.post(f"http://127.0.0.1:8001/tg-sessions/{chat_id}/clear", timeout=5)
        except Exception:  # noqa: BLE001 — FastAPI service may be offline
            pass
        send_message(chat_id, "Historique effacé.")
        return "clear"

    try:
        resp = requests.post(
            "http://127.0.0.1:8001/api/chat",
            json={"user_id": chat_id, "username": "tg", "message": text},
            timeout=60,
        )
        reply = resp.json().get("reply") or resp.json().get("response") or "..."
    except Exception as exc:  # noqa: BLE001
        reply = f"Erreur chat: {exc}"
    send_message(chat_id, reply)
    return "chat"


def _fetch_updates(token: str, offset: int) -> List[Dict[str, Any]]:
    base = f"https://api.telegram.org/bot{token}"
    r = requests.get(
        f"{base}/getUpdates",
        params={
            "offset": offset,
            "timeout": POLL_LONG_POLL_TIMEOUT,
            "allowed_updates": ["message"],
        },
        timeout=POLL_GET_UPDATES_TIMEOUT,
    )
    if not r.ok:
        return []
    return r.json().get("result", [])


def poll_once(
    *,
    token: str,
    admin_id: int,
    offset: int,
    send_message: Optional[Callable[[int, str], None]] = None,
    get_updates_fn: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
) -> Tuple[int, int]:
    """Fetch and process one batch of Telegram updates.

    Returns ``(new_offset, messages_handled)``.
    """
    _send = send_message or _make_send_message(token)
    _fetch = get_updates_fn or _fetch_updates
    updates = _fetch(token, offset)
    handled = 0

    for upd in updates:
        offset = upd["update_id"] + 1
        msg = upd.get("message", {})
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        chat_id = msg["chat"]["id"]
        handle_telegram_message(text, chat_id, admin_id=admin_id, send_message=_send)
        handled += 1

    return offset, handled


def run_poll_loop(
    *,
    stop_event: Optional[threading.Event] = None,
    token: Optional[str] = None,
    admin_id: Optional[int] = None,
    poll_sleep_s: int = DEFAULT_POLL_SLEEP_S,
) -> None:
    """Daemon loop: long-poll Telegram until ``stop_event`` is set."""
    _token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
    _admin = admin_id if admin_id is not None else int(
        os.environ.get("TELEGRAM_ADMIN_ID", "0") or 0,
    )
    if not _token:
        return

    _stop = stop_event or threading.Event()
    send = _make_send_message(_token)
    offset = 0

    while not _stop.is_set():
        try:
            offset, _ = poll_once(
                token=_token,
                admin_id=_admin,
                offset=offset,
                send_message=send,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"Telegram getUpdates échoué ({exc}) — retry dans 5s.", "WARN")
            if _stop.wait(5):
                break
            continue
        if _stop.wait(poll_sleep_s):
            break


def start_poll_thread(
    *,
    token: Optional[str] = None,
    admin_id: Optional[int] = None,
) -> Optional[threading.Thread]:
    """Start the Telegram poll worker in a daemon thread."""
    _token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not _token:
        return None
    thread = threading.Thread(
        target=run_poll_loop,
        kwargs={"token": _token, "admin_id": admin_id},
        daemon=True,
        name="telegram-poll-worker",
    )
    thread.start()
    return thread
