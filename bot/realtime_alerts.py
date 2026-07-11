"""Alertes Telegram temps réel : nouveaux picks value + résultats settlement."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

import requests

from . import push_notifications
from .log import log

_ALERTED_LOCK = threading.Lock()
_ALERT_COOLDOWN = 3600              # 1h avant de réalerter le même pick
_DEDUP_FILE = Path("/tmp/tennisboss_alerted.json")


def _load_alerted() -> Dict[str, float]:
    try:
        if _DEDUP_FILE.exists():
            data = json.loads(_DEDUP_FILE.read_text())
            cutoff = time.time() - _ALERT_COOLDOWN
            return {k: v for k, v in data.items() if v > cutoff}
    except Exception:
        pass
    return {}


def _save_alerted(data: Dict[str, float]) -> None:
    try:
        _DEDUP_FILE.write_text(json.dumps(data))
    except Exception:
        pass


_ALERTED_AT: Dict[str, float] = _load_alerted()


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _chat_id() -> int:
    raw = os.environ.get("TELEGRAM_OWNER_CHAT_ID") or os.environ.get("TELEGRAM_ADMIN_ID", "")
    try:
        return int(raw.strip()) if raw.strip() else 0
    except (ValueError, TypeError):
        return 0


def _send(text: str) -> None:
    token = _bot_token()
    cid = _chat_id()
    if not token or not cid:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": cid, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception as exc:
        log(f"realtime_alerts: envoi échoué — {exc}", "WARN")


_SURF_EMOJI = {"clay": "🔴", "grass": "🟢", "hard": "🔵"}


def on_value_pick(pick: Dict[str, Any]) -> None:
    """Alerte immédiate pour un nouveau pick value. Dédupliqué sur 1h."""
    p1 = pick.get("player1", "?")
    p2 = pick.get("player2", "?")
    side = pick.get("best_side") or pick.get("side", "?")
    ev = pick.get("best_ev") or pick.get("ev") or 0.0
    pick_odds = pick.get("pick_odds") or pick.get("odds")
    fair_odds = pick.get("fair_odds")
    kelly = pick.get("kelly_u", 0.0)
    conf_label = pick.get("confidence_label", "")
    league = pick.get("league", "")
    surface = (pick.get("surface") or "").lower()
    book = pick.get("best_book", "") or pick.get("odds_book", "")

    alert_key = f"{p1}|{p2}|{side}"
    now = time.time()

    with _ALERTED_LOCK:
        last = _ALERTED_AT.get(alert_key, 0)
        if now - last < _ALERT_COOLDOWN:
            return
        _ALERTED_AT[alert_key] = now
        _save_alerted(_ALERTED_AT)

    is_scanner = pick.get("scanner", False)
    hours_ahead = pick.get("hours_ahead")
    urgency = pick.get("urgency", "🎾")

    # Countdown
    if hours_ahead is not None:
        if hours_ahead < 1.0:
            time_s = f"⏱ {int(hours_ahead * 60)}min avant le match"
        elif hours_ahead < 3.0:
            time_s = f"⏱ {hours_ahead:.1f}h avant le match"
        else:
            time_s = f"⏱ {hours_ahead:.0f}h avant le match"
    else:
        time_s = ""

    # Surface
    surf_em = _SURF_EMOJI.get(surface, "")
    surf_s = f" {surf_em} {surface.capitalize()}" if surface and surf_em else ""

    # Line shopping gap : Bet365 vs Betfair
    odds_s = f"`{pick_odds:.2f}`" if pick_odds else "—"
    if fair_odds and pick_odds and fair_odds > 1.0:
        gap_pct = (pick_odds / fair_odds - 1) * 100
        shop_s = f"\n🏦 Bet365 `{pick_odds:.2f}` vs Betfair `{fair_odds:.2f}` (+{gap_pct:.0f}%)"
    else:
        shop_s = ""

    # Titre
    if is_scanner:
        title = f"{urgency} *SCANNER PICK*{surf_s}"
    else:
        title = f"🎾 *VALUE PICK*{surf_s}"

    league_s = f"\n📍 _{league}_" if league else ""

    msg = (
        f"{title}{league_s}\n\n"
        f"*{p1}* vs *{p2}*\n"
        f"✅ Miser *{side}* @ {odds_s}"
        f"{shop_s}\n"
        f"📈 EV `+{ev:.0f}%`"
    )
    if kelly and kelly > 0:
        msg += f" · Kelly `{kelly:.1f}%`"
    if time_s:
        msg += f"\n{time_s}"
    if conf_label:
        msg += f"\n🔒 Confiance : {conf_label}"

    _send(msg)

    if push_notifications.is_enabled():
        push_title = "🎾 Scanner pick" if is_scanner else "💎 Value pick"
        push_body = f"{p1} vs {p2} — {side} @ {odds_s.strip('`')} (EV +{ev:.0f}%)"
        push_notifications.broadcast(push_title, push_body, data={"type": "value_pick", "player1": p1, "player2": p2})


def on_odds_move(p1: str, p2: str, side: str,
                 pick_odds: float, current_odds: float) -> None:
    """Alerte quand la cote a bougé ≥ 10% contre notre pick depuis la décision."""
    move_pct = (current_odds - pick_odds) / pick_odds * 100
    if abs(move_pct) < 10.0:
        return

    alert_key = f"move|{p1}|{p2}|{side}"
    now = time.time()
    with _ALERTED_LOCK:
        last = _ALERTED_AT.get(alert_key, 0)
        if now - last < _ALERT_COOLDOWN:
            return
        _ALERTED_AT[alert_key] = now
        _save_alerted(_ALERTED_AT)

    direction = "⬇️ baissé" if move_pct < 0 else "⬆️ monté"
    warn = "⚠️" if move_pct < 0 else "ℹ️"
    msg = (
        f"{warn} *Mouvement de cote*\n\n"
        f"*{p1}* vs *{p2}*\n"
        f"Pick : *{side}* @ {pick_odds:.2f}\n"
        f"Actuel : `{current_odds:.2f}` ({direction} {abs(move_pct):.0f}%)"
    )
    if move_pct < 0:
        msg += "\n_⚠️ Marché contre nous — surveiller_"
    _send(msg)

    if push_notifications.is_enabled():
        push_title = "⚠️ Cote défavorable" if move_pct < 0 else "ℹ️ Mouvement de cote"
        push_body = f"{p1} vs {p2} — {side} : {pick_odds:.2f} → {current_odds:.2f} ({direction} {abs(move_pct):.0f}%)"
        push_notifications.broadcast(push_title, push_body, data={"type": "odds_move", "player1": p1, "player2": p2})


def on_settlement(p1: str, p2: str, winner: str, side: str,
                  odds: float, pnl: float) -> None:
    """Alerte résultat quand un value pick est réglé."""
    won = winner == side
    em = "✅" if won else "❌"
    pnl_s = f"+{pnl:.2f}u" if pnl >= 0 else f"{pnl:.2f}u"

    msg = (
        f"{em} *Résultat pick*\n\n"
        f"*{p1}* vs *{p2}*\n"
        f"Misé : *{side}* @ {odds:.2f}\n"
        f"Gagnant : *{winner}*\n"
        f"P&L : `{pnl_s}`"
    )

    # CLV du pick (si disponible dans clv_log)
    try:
        from . import db as _db
        with _db.connect() as _c:
            clv_row = _c.execute(
                "SELECT clv_pct, closing_odds, closing_src FROM clv_log "
                "WHERE player1=? AND player2=? AND pick_side=? "
                "AND result IS NOT NULL ORDER BY rowid DESC LIMIT 1",
                (p1, p2, side)
            ).fetchone()
        if clv_row and clv_row["closing_src"] not in (None, "last_seen"):
            clv_pct = clv_row["clv_pct"] or 0.0
            clv_em = "🟢" if clv_pct > 2 else "🟡" if clv_pct > 0 else "🔴"
            msg += f"\nCLV : {clv_em} `{clv_pct:+.1f}%` vs clôture `{clv_row['closing_odds']:.2f}`"
    except Exception:
        pass

    # Stats cumulées scanner (post-filtre)
    try:
        from . import clv as _clv
        sc = _clv.stats().get("scanner", {})
        if sc and sc.get("n_settled", 0) >= 3:
            roi = sc.get("roi_flat_pct", 0)
            wr = sc.get("win_rate_pct", 0)
            n = sc.get("n_settled", 0)
            roi_em = "📈" if roi > 0 else "📉"
            msg += f"\n{roi_em} _Scanner : {wr:.0f}% WR · ROI {roi:+.0f}% ({n} picks)_"
    except Exception:
        pass

    _send(msg)

    if push_notifications.is_enabled():
        push_title = "✅ Pick gagné" if won else "❌ Pick perdu"
        push_body = f"{p1} vs {p2} — {side} @ {odds:.2f} ({pnl_s})"
        push_notifications.broadcast(push_title, push_body, data={"type": "settlement", "player1": p1, "player2": p2})


# --- Compat singleton (ancien code utilise _ra.get()) ---

class _Compat:
    """Shim pour l'ancien code qui appelle _ra.get().on_value_pick(pick)."""
    def on_value_pick(self, pick: Dict[str, Any]) -> None:
        on_value_pick(pick)

    def on_settlement(self, event: Dict[str, Any]) -> None:
        data = event.get("data", {})
        p1, p2 = data.get("player1", ""), data.get("player2", "")
        winner = data.get("winner", "")
        # Chercher dans value_picks pour avoir les vraies cotes et le pnl
        try:
            from . import db as _db
            with _db.connect() as _c:
                vp = _c.execute(
                    "SELECT side, odds, pnl FROM value_picks "
                    "WHERE ((player1=? AND player2=?) OR (player1=? AND player2=?)) "
                    "AND result IS NOT NULL ORDER BY rowid DESC LIMIT 1",
                    (p1, p2, p2, p1)
                ).fetchone()
        except Exception:
            vp = None
        if not vp or not vp["odds"] or vp["odds"] <= 0:
            return  # pas de value pick → pas d'alerte
        on_settlement(p1, p2, winner, vp["side"],
                      float(vp["odds"]), float(vp["pnl"] or 0))

    def is_enabled(self) -> bool:
        return bool(_bot_token() and _chat_id())


_SINGLETON: Optional[_Compat] = None


def init() -> _Compat:
    global _SINGLETON
    _SINGLETON = _Compat()
    if _SINGLETON.is_enabled():
        log("Alertes Telegram temps réel activées.")
    return _SINGLETON


def get() -> Optional[_Compat]:
    if _SINGLETON is None:
        init()
    return _SINGLETON if (_SINGLETON and _SINGLETON.is_enabled()) else None
