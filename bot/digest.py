"""Digest quotidien TennisBoss — rapport Telegram 21h."""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import requests

from . import clv, config, db
from .log import log

_BOT_TOKEN = ""
_OWNER_CHAT_ID = 0


def _load_config() -> None:
    global _BOT_TOKEN, _OWNER_CHAT_ID
    import os
    _BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    # TELEGRAM_OWNER_CHAT_ID prioritaire, sinon fallback sur TELEGRAM_ADMIN_ID
    raw = os.environ.get("TELEGRAM_OWNER_CHAT_ID") or os.environ.get("TELEGRAM_ADMIN_ID", "")
    try:
        _OWNER_CHAT_ID = int(raw.strip()) if raw.strip() else 0
    except (ValueError, TypeError):
        _OWNER_CHAT_ID = 0


def _send(text: str) -> bool:
    _load_config()
    if not _BOT_TOKEN or not _OWNER_CHAT_ID:
        log("digest: TELEGRAM_BOT_TOKEN ou TELEGRAM_OWNER_CHAT_ID manquant")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            json={"chat_id": _OWNER_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log(f"digest: envoi Telegram échoué — {e}")
        return False


def _fmt_pnl(pnl: Optional[float]) -> str:
    if pnl is None:
        return "—"
    return f"+{pnl:.1f}u" if pnl >= 0 else f"{pnl:.1f}u"


def _pnl_emoji(pnl: Optional[float]) -> str:
    if pnl is None:
        return "⏳"
    return "✅" if pnl >= 0 else "❌"


def build_digest(date: Optional[str] = None) -> str:
    """Génère le texte du rapport quotidien."""
    db.init()
    today = date or datetime.date.today().isoformat()
    dt_label = datetime.date.fromisoformat(today).strftime("%d/%m/%Y")

    with db.connect() as c:
        # Value picks du jour
        vp_rows = c.execute(
            "SELECT player1, player2, side, odds, ev, result, pnl "
            "FROM value_picks WHERE date LIKE ? ORDER BY ev DESC",
            (f"{today}%",)
        ).fetchall()

        # Inplay picks du jour (excl. voided)
        ip_rows = c.execute(
            "SELECT pick, player1, player2, odds, result, pnl "
            "FROM inplay_picks WHERE ts LIKE ? AND result != 'V' ORDER BY id DESC",
            (f"{today}%",)
        ).fetchall()

    # --- Value picks stats ---
    vp_settled = [r for r in vp_rows if r["result"] is not None]
    vp_wins = [r for r in vp_settled if r["result"] == 1]
    vp_pnl = sum(r["pnl"] for r in vp_settled if r["pnl"] is not None)
    vp_n = len(vp_rows)
    vp_ns = len(vp_settled)

    # --- Inplay picks stats ---
    ip_settled = [r for r in ip_rows if r["result"] in ("W", "L")]
    ip_wins = [r for r in ip_settled if r["result"] == "W"]
    ip_pnl = sum(r["pnl"] for r in ip_settled if r["pnl"] is not None)

    # --- CLV ---
    clv_stats = clv.stats().get("global", {})
    avg_clv = clv_stats.get("avg_clv_pct")
    beat_pct = clv_stats.get("beat_closing_pct")
    n_clv = clv_stats.get("n_clv", 0)

    lines: List[str] = []
    lines.append(f"📊 *TennisBoss — Bilan {dt_label}*")
    lines.append("")

    # ── Value picks ──────────────────────────────────────
    lines.append("🎯 *Value Picks*")
    if not vp_rows:
        lines.append("  Aucun pick aujourd'hui.")
    else:
        if vp_ns:
            roi_flat = vp_pnl / vp_ns * 100 if vp_ns else 0
            lines.append(
                f"  {vp_ns}/{vp_n} réglés • "
                f"{len(vp_wins)}W/{vp_ns - len(vp_wins)}L • "
                f"P&L {_fmt_pnl(vp_pnl)} • ROI {roi_flat:+.1f}%"
            )
        else:
            lines.append(f"  {vp_n} picks • résultats en attente")

        # Top 5 par EV
        top5 = sorted(vp_rows, key=lambda r: -(r["ev"] or 0))[:5]
        for r in top5:
            side = (r["side"] or r["player1"] or "?")[:20]
            em = ("✅" if r["result"] == 1 else "❌" if r["result"] == 0 else "⏳")
            pnl_s = f" {_fmt_pnl(r['pnl'])}" if r["result"] is not None else ""
            lines.append(f"  {em} {side} @ {r['odds']} (EV {r['ev']:+.0f}%){pnl_s}")

    lines.append("")

    # ── Inplay picks ─────────────────────────────────────
    lines.append("⚡ *Live Picks*")
    if not ip_rows:
        lines.append("  Aucun pick live aujourd'hui.")
    else:
        if ip_settled:
            lines.append(
                f"  {len(ip_settled)}/{len(ip_rows)} réglés • "
                f"{len(ip_wins)}W/{len(ip_settled) - len(ip_wins)}L • "
                f"P&L {_fmt_pnl(ip_pnl)}"
            )
        for r in ip_rows[:5]:
            em = ("✅" if r["result"] == "W" else "❌" if r["result"] == "L" else "⏳")
            pnl_s = f" {_fmt_pnl(r['pnl'])}" if r["result"] in ("W", "L") else ""
            pick = (r["pick"] or "?")[:20]
            lines.append(f"  {em} {pick}{pnl_s}")

    lines.append("")

    # ── CLV ──────────────────────────────────────────────
    lines.append("📈 *CLV (Closing Line Value)*")
    if avg_clv is not None and n_clv >= 10:
        clv_em = "🟢" if avg_clv > 2 else "🟡" if avg_clv > 0 else "🔴"
        lines.append(
            f"  {clv_em} Avg CLV {avg_clv:+.1f}% • "
            f"Beat closing {beat_pct:.0f}% (n={n_clv})"
        )
    else:
        lines.append(f"  Données insuffisantes (n={n_clv})")

    lines.append("")
    lines.append("_TennisBoss — rapport automatique 21h_")
    return "\n".join(lines)


def send_daily_digest(date: Optional[str] = None) -> bool:
    """Génère et envoie le digest. Retourne True si envoyé."""
    try:
        text = build_digest(date)
        log(f"digest: envoi rapport {date or datetime.date.today()}")
        return _send(text)
    except Exception as e:
        log(f"digest: erreur génération — {e}", "ERROR")
        return False
