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
POLL_TIMEOUT = 10  # short-poll — avoids WSL2 TCP resets on idle long-polls

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
        if not updates:
            time.sleep(2)
            continue
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
                tg_send(chat_id,
                    "🎾 *TennisBoss*\n\n"
                    "/picks — picks du jour (value + live)\n"
                    "/value — picks ouverts en attente\n"
                    "/roi — bilan P&L rapide\n"
                    "/clv — bilan Closing Line Value\n"
                    "/wimbledon — stats Wimbledon 2026\n"
                    "/model — paramètres du modèle\n"
                    "/stats — bilan global\n"
                    "/digest — rapport complet\n"
                    "/clear — effacer l'historique\n\n"
                    "_Ou pose une question directement !_"
                )
                continue
            if text == "/clear":
                requests.post(f"http://127.0.0.1:8001/tg-sessions/{user_id}/clear", timeout=5)
                tg_send(chat_id, "Historique effacé.")
                continue
            if text in ("/picks", "/picks@TennisBossBot"):
                from . import digest as _digest
                tg_send(chat_id, _digest.build_picks_summary())
                continue
            if text in ("/value", "/value@TennisBossBot"):
                from . import digest as _digest
                tg_send(chat_id, _digest.build_value_open())
                continue
            if text in ("/clv", "/clv@TennisBossBot"):
                from . import digest as _digest
                tg_send(chat_id, _digest.build_clv_report())
                continue
            if text in ("/stats", "/stats@TennisBossBot"):
                from . import digest as _digest
                tg_send(chat_id, _digest.build_global_stats())
                continue
            if text in ("/roi", "/roi@TennisBossBot"):
                from . import db as _db
                _rows = [r for r in _db.list_value_history(limit=500)
                         if (r["result"] in (0, 1)
                             and (r["odds"] or 99) <= 5.0
                             and (r["ev"] or 0) >= 8.0)]
                if _rows:
                    _n = len(_rows)
                    _w = sum(1 for r in _rows if r["result"] == 1)
                    _pnl = sum(r["pnl"] for r in _rows if r["pnl"] is not None)
                    tg_send(chat_id,
                        f"📈 *ROI (EV≥8%, cotes ≤5.0)*\n"
                        f"  {_w}W / {_n-_w}L sur {_n} picks\n"
                        f"  P&L `{'+' if _pnl>=0 else ''}{_pnl:.1f}u`\n"
                        f"  ROI `{_pnl/_n*100:+.1f}%`\n"
                        f"  WR `{_w/_n*100:.0f}%`"
                    )
                else:
                    tg_send(chat_id, "Aucun pick réglé (EV≥8%).")
                continue
            if text in ("/wimbledon", "/wimbledon@TennisBossBot", "/grass"):
                import sqlite3 as _sq, datetime as _dt2
                _db_path = "/mnt/c/Users/donpa/TennisBoss/state/tennisboss.db"
                _conn = _sq.connect(_db_path)
                _conn.row_factory = _sq.Row
                _wimb_start = "2026-06-23"
                _rows = _conn.execute('''SELECT result, pnl, ev, odds, player1, player2, side
                    FROM value_picks
                    WHERE date >= ? AND result IN (0,1) AND odds <= 5.0 AND ev >= 8.0
                    AND league LIKE "%Wimbledon%"''', (_wimb_start,)).fetchall()
                _conn.close()
                if _rows:
                    _n = len(_rows)
                    _w = sum(1 for r in _rows if r["result"] == 1)
                    _pnl = sum(r["pnl"] for r in _rows if r["pnl"] is not None)
                    _msg = (f"🌱 *Wimbledon 2026 (EV≥8%, cotes≤5)*\n"
                            f"  {_w}W / {_n-_w}L sur {_n} picks\n"
                            f"  P&L `{'+' if _pnl>=0 else ''}{_pnl:.1f}u`\n"
                            f"  ROI `{_pnl/_n*100:+.1f}%`\n"
                            f"  WR `{_w/_n*100:.0f}%`")
                else:
                    _msg = "Aucun pick Wimbledon réglé (EV≥8%)."
                tg_send(chat_id, _msg)
                continue
            if text in ("/model", "/model@TennisBossBot"):
                import sqlite3 as _sq2, json as _jj
                _db_path = "/mnt/c/Users/donpa/TennisBoss/state/tennisboss.db"
                _c2 = _sq2.connect(_db_path)
                _c2.row_factory = _sq2.Row
                _get = lambda k: (_c2.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone() or {}).get("value")
                _blend = _get("elo_blend") or "?"
                _blends = _jj.loads(_get("elo_blend_by_surface") or "{}")
                _lc = _jj.loads(_get("last_learning_cycle") or "{}")
                _c2.close()
                _acc = _lc.get("kfold_accuracy", 0)
                _bs = " | ".join(f"{s}={v:.2f}" for s, v in _blends.items()) if _blends else "—"
                tg_send(chat_id,
                    f"🤖 *Modèle TennisBoss*\n"
                    f"  ELO blend global: `{float(_blend):.2f}` (settlement)\n"
                    f"  Blends surface: `{_bs}`\n"
                    f"  K-fold acc: `{_acc*100:.1f}%` (auto-learn)\n"
                    f"  Dead zone: `EV 12-18%` bloquée\n"
                    f"  Filter: `EV≥8%, cotes≤5.0`"
                )
                continue
            if text in ("/digest", "/digest@TennisBossBot"):
                from . import digest as _digest
                tg_send(chat_id, _digest.build_digest())
                continue

            # Indicate typing
            requests.post(f"{TG_BASE}/sendChatAction",
                          json={"chat_id": chat_id, "action": "typing"}, timeout=5)

            reply = chat(user_id, username, text)
            tg_send(chat_id, reply)
            print(f"[REPLY] {reply[:80]}...")


if __name__ == "__main__":
    main()
