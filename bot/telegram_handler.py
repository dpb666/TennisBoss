"""Telegram bot handler — webhook integration + session mgmt.

Sessions are stored in SQLite with threading-safe locking.
Multi-user support with individual conversation histories.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from .log import log

_LOCK = threading.RLock()
_DB_PATH = "/tmp/tg_sessions.db"


def _init_schema():
    """Create session storage schema."""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_sessions (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            created_at TEXT,
            last_msg   TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            role       TEXT,
            content    TEXT,
            timestamp  TEXT,
            FOREIGN KEY (user_id) REFERENCES tg_sessions(user_id)
        )
        """)
        conn.commit()


_init_schema()


def get_session(user_id: int, username: str = "") -> Dict[str, Any]:
    """Get or create user session."""
    with _LOCK:
        with sqlite3.connect(_DB_PATH) as conn:
            # Create session if missing
            conn.execute(
                "INSERT OR IGNORE INTO tg_sessions (user_id, username, created_at) "
                "VALUES (?, ?, datetime('now'))",
                (user_id, username),
            )
            # Update last_msg
            conn.execute(
                "UPDATE tg_sessions SET last_msg = datetime('now') WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()

            # Fetch history (last 20 msgs)
            rows = conn.execute(
                "SELECT role, content FROM tg_history WHERE user_id = ? "
                "ORDER BY id DESC LIMIT 20",
                (user_id,),
            ).fetchall()
            history = [
                {"role": r[0], "content": r[1]}
                for r in reversed(rows)
            ]
            return {"user_id": user_id, "username": username, "history": history}


def save_message(user_id: int, role: str, content: str):
    """Save message to history."""
    with _LOCK:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO tg_history (user_id, role, content, timestamp) "
                "VALUES (?, ?, ?, datetime('now'))",
                (user_id, role, content),
            )
            conn.commit()


def clear_history(user_id: int):
    """Clear user's conversation history."""
    with _LOCK:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute("DELETE FROM tg_history WHERE user_id = ?", (user_id,))
            conn.commit()


def validate_telegram_signature(body: str, signature: str, token: str) -> bool:
    """Validate Telegram X-Telegram-Bot-Api-Secret-Chat-Id header.

    Not critical for local testing but required for prod Telegram webhook.
    """
    expected = hashlib.sha256(f"{token}{body}".encode()).hexdigest()
    return signature == expected


def parse_telegram_message(update: Dict[str, Any]) -> tuple[int, str, str] | None:
    """Extract (user_id, username, text) from Telegram update.

    Returns None if not a text message.
    """
    msg = update.get("message", {})
    if not msg.get("text"):
        return None

    user = msg.get("from", {})
    user_id = user.get("id")
    username = user.get("username", f"user_{user_id}")
    text = msg.get("text", "").strip()

    if user_id and text:
        return (user_id, username, text)
    return None


def route_agent_command(text: str) -> Optional[str]:
    """Detect @agent_name mentions and return agent name.

    @stats_agent, @odds_agent, @analyzer_agent
    Returns None if no agent command.
    """
    agents = ["stats_agent", "odds_agent", "analyzer_agent", "coder_agent"]
    text_lower = text.lower()
    for agent in agents:
        if f"@{agent}" in text_lower or text_lower.startswith(agent):
            return agent
    return None


def extract_match_context(text: str) -> Dict[str, str]:
    """Extract player names and surface from text.

    Examples:
      - "Djokovic vs Sinner on hard"
      - "Alcaraz clay"
      - "Swiatek vs Sabalenka"
    """
    context = {}
    # Simple parsing — could be improved with NLP
    text_lower = text.lower()

    for surface in ["clay", "hard", "grass"]:
        if surface in text_lower:
            context["surface"] = surface
            break

    # Try to extract player names (very basic)
    # Real implementation would use named entity recognition
    return context
