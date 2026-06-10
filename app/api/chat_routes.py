"""Telegram AI Chat integration routes.

Endpoints:
  POST /tg-webhook      : Telegram bot webhook receiver
  POST /tg-chat         : Direct chat API (for testing)
  GET  /tg-sessions/<id>: Retrieve session history
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bot import chat as chat_mod
from bot import telegram_handler as tg
from bot.log import log

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_PATH = os.environ.get("TELEGRAM_WEBHOOK_PATH", "/tg-webhook")


class ChatRequest(BaseModel):
    user_id: int
    message: str
    session_context: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    user_id: int
    reply: str
    agent: Optional[str] = None
    confidence: Optional[float] = None


@router.post("/tg-webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram bot updates via webhook."""
    try:
        body = await request.body()
        update = json.loads(body)
    except (json.JSONDecodeError, ValueError) as e:
        log(f"Invalid webhook body: {e}", "WARN")
        return {"ok": False}

    # Parse message
    result = tg.parse_telegram_message(update)
    if not result:
        # Not a text message — ignore
        return {"ok": True}

    user_id, username, text = result
    log(f"TG message from @{username} (id={user_id}): {text[:50]}", "INFO")

    # Load session
    session = tg.get_session(user_id, username)

    # Check for special commands
    if text.lower() in ["/clear", "/reset", "clear"]:
        tg.clear_history(user_id)
        reply = "✅ Conversation cleared."
    elif text.lower() in ["/help", "help"]:
        reply = (
            "TennisBoss AI Chat 🎾\n\n"
            "Commands:\n"
            "• /clear — reset conversation\n"
            "• @stats_agent — analyze player performance\n"
            "• @odds_agent — check value bets\n"
            "• @analyzer_agent — combine signals\n\n"
            "Ask any tennis question!"
        )
    else:
        # Route to appropriate agent or general chat
        agent = tg.route_agent_command(text)
        reply = _route_chat(user_id, text, session["history"], agent)

    # Save to history
    tg.save_message(user_id, "user", text)
    tg.save_message(user_id, "assistant", reply)

    # Send reply back to Telegram
    if TELEGRAM_BOT_TOKEN:
        _send_telegram_message(user_id, reply)
    else:
        log("No TELEGRAM_BOT_TOKEN — reply not sent", "WARN")

    return {"ok": True, "reply": reply}


@router.post("/tg-chat")
def direct_chat(req: ChatRequest) -> ChatResponse:
    """Direct chat API for testing or non-webhook usage."""
    session = tg.get_session(req.user_id)
    history = session["history"]

    # Run chat
    reply = _run_chat(req.message, history, req.session_context or {})

    # Save
    tg.save_message(req.user_id, "user", req.message)
    tg.save_message(req.user_id, "assistant", reply)

    return ChatResponse(
        user_id=req.user_id,
        reply=reply,
        agent=None,
        confidence=None,
    )


@router.get("/tg-sessions/{user_id}")
def get_session_history(user_id: int):
    """Retrieve session history for a user."""
    session = tg.get_session(user_id)
    return {
        "user_id": user_id,
        "username": session.get("username", "unknown"),
        "history": session["history"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_chat(
    user_id: int,
    message: str,
    history: list,
    agent: Optional[str] = None,
) -> str:
    """Route message to appropriate agent or general chat."""
    if agent:
        return _agent_chat(user_id, message, history, agent)
    return _run_chat(message, history)


def _agent_chat(
    user_id: int, message: str, history: list, agent: str
) -> str:
    """Route to specific agent analysis."""
    # TODO: implement agent routing via openclaw sessions
    log(f"Agent routing to {agent} for user {user_id}", "INFO")

    # For now, call general chat with agent prefix
    system_msg = f"You are TennisBoss {agent}. Provide {agent.replace('_', ' ')} analysis."
    return f"[{agent}] Analysis pending — integration in progress."


def _run_chat(message: str, history: list, context: dict = None) -> str:
    """Run local LLM chat with context."""
    from app.main import _MEM

    try:
        reply = chat_mod.chat(message, history, _MEM)
        log(f"Chat reply: {reply[:50]}", "INFO")
        return reply
    except Exception as e:
        log(f"Chat error: {e}", "ERROR")
        return f"❌ Error: {e}"


def _send_telegram_message(chat_id: int, text: str):
    """Send message back to Telegram user."""
    import requests

    if not TELEGRAM_BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
        log(f"Telegram reply sent to {chat_id}", "INFO")
    except requests.RequestException as e:
        log(f"Failed to send Telegram message: {e}", "WARN")
