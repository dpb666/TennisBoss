"""Telegram polling bot — no webhook/ngrok needed.

Polls Telegram getUpdates, forwards to local FastAPI /api/chat, replies.
"""
from __future__ import annotations

import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = os.environ.get("CHAT_API_URL", "http://127.0.0.1:8001/api/chat")
POLL_TIMEOUT = 30  # long-poll seconds

TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_get_updates(offset: int) -> list:
    try:
        r = requests.get(
            f"{TG_BASE}/getUpdates",
            params={"offset": offset, "timeout": POLL_TIMEOUT, "allowed_updates": ["message"]},
            timeout=POLL_TIMEOUT + 5,
        )
        data = r.json()
        if data.get("ok"):
            return data["result"]
    except Exception as e:
        print(f"[POLL] getUpdates error: {e}")
    return []


def tg_send(chat_id: int, text: str):
    try:
        requests.post(
            f"{TG_BASE}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
    except Exception as e:
        print(f"[SEND] error: {e}")


def chat(user_id: int, username: str, text: str) -> str:
    """Forward message to local FastAPI chat endpoint."""
    try:
        r = requests.post(
            API_URL,
            json={"user_id": user_id, "username": username, "message": text},
            timeout=120,
        )
        data = r.json()
        return data.get("reply") or data.get("response") or "..."
    except requests.exceptions.ConnectionError:
        return "Serveur hors ligne. Lance: python3 run.py quant"
    except Exception as e:
        return f"Erreur: {e}"


def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN manquant dans .env")
        sys.exit(1)

    # Validate token
    me = requests.get(f"{TG_BASE}/getMe", timeout=10).json()
    if not me.get("ok"):
        print(f"Token invalide: {me}")
        sys.exit(1)

    bot_name = me["result"]["username"]
    print(f"[BOT] @{bot_name} démarré en mode polling → {API_URL}")

    offset = 0
    while True:
        updates = tg_get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            if not msg.get("text"):
                continue

            chat_id = msg["chat"]["id"]
            user = msg.get("from", {})
            user_id = user.get("id", chat_id)
            username = user.get("username", f"user_{user_id}")
            text = msg["text"].strip()

            print(f"[MSG] @{username}: {text}")

            if text == "/start":
                tg_send(chat_id, f"Bienvenue sur TennisBoss ! Pose ta question sur un match, joueur ou cote.")
                continue
            if text == "/clear":
                requests.post(f"http://127.0.0.1:8001/tg-sessions/{user_id}/clear", timeout=5)
                tg_send(chat_id, "Historique effacé.")
                continue

            # Indicate typing
            requests.post(f"{TG_BASE}/sendChatAction",
                          json={"chat_id": chat_id, "action": "typing"}, timeout=5)

            reply = chat(user_id, username, text)
            tg_send(chat_id, reply)
            print(f"[REPLY] {reply[:80]}...")


if __name__ == "__main__":
    main()
