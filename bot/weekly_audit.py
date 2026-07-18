"""Weekly operational audit — bet_history, logging completeness, CLV, pick volume.

Used by ``python run.py weekly-audit`` and the Sunday scheduler digest.
Does not touch prediction logic or pick-selection gates (ADR-005).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from . import clv, db

# Documented in weekly output — quiet calendar weeks are expected, not a bug.
CALENDAR_QUIET_NOTE = (
    "Note calendrier : une semaine à faible volume peut refléter une pause "
    "naturelle ATP/WTA (entre Masters, post-GS, off-season fin nov–déc). "
    "Ne pas élargir les filtres de sélection — attendre le retour du flux."
)


def run_audit(*, days: int = 7, logging_hours: int = 24) -> Dict[str, Any]:
    """Collect audit metrics (read-only)."""
    days = max(1, int(days))
    logging_hours = max(1, int(logging_hours))
    db.init()

    period_end = _dt.date.today()
    period_start = period_end - _dt.timedelta(days=days - 1)
    since = period_start.isoformat()

    bh = db.bet_history_stats(days=days)
    logging_recent = db.clv_logging_completeness_recent(hours=logging_hours)
    logging_week = db.clv_logging_completeness_report(bucket="week")
    clv_stats = clv.weekly_stats(days=days)

    with db.connect() as conn:
        n_clv_picks = conn.execute(
            "SELECT COUNT(*) FROM clv_log WHERE date >= ?", (since,),
        ).fetchone()[0]
        n_value_picks = conn.execute(
            "SELECT COUNT(*) FROM value_picks WHERE date >= ?", (since,),
        ).fetchone()[0]
        n_open_clv = conn.execute(
            "SELECT COUNT(*) FROM clv_log WHERE result IS NULL",
        ).fetchone()[0]
        n_missing_closing = conn.execute(
            "SELECT COUNT(*) FROM clv_log WHERE result IS NULL AND closing_odds IS NULL",
        ).fetchone()[0]

    scanner = clv_stats.get("scanner") or {}
    glob = clv_stats.get("global") or {}

    return {
        "period_days": days,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "bet_history": bh,
        "logging_recent_hours": logging_hours,
        "logging_recent": logging_recent,
        "logging_week": logging_week,
        "clv": clv_stats,
        "pick_volume": {
            "clv_seeded": n_clv_picks,
            "value_picks": n_value_picks,
            "clv_open": n_open_clv,
            "clv_missing_closing": n_missing_closing,
        },
        "calendar_note": CALENDAR_QUIET_NOTE,
        "summary": {
            "bet_history_n": bh.get("n") or 0,
            "logging_completeness_pct": logging_recent.get("completeness_pct"),
            "avg_clv_pct": scanner.get("avg_clv_pct") or glob.get("avg_clv_pct"),
            "n_clv_settled": scanner.get("n_clv") or glob.get("n_clv") or 0,
            "verdict": clv_stats.get("verdict"),
            "verdict_label": clv_stats.get("verdict_label"),
        },
    }


def format_report(audit: Dict[str, Any]) -> str:
    """Human-readable report for CLI / logs."""
    s = audit.get("summary") or {}
    bh = audit.get("bet_history") or {}
    lr = audit.get("logging_recent") or {}
    pv = audit.get("pick_volume") or {}
    lines: List[str] = [
        f"=== Weekly audit {audit.get('period_start')} → {audit.get('period_end')} "
        f"({audit.get('period_days')}j) ===",
        "",
        f"bet_history (réglés) : {bh.get('n', 0)} "
        f"(ROI flat {bh.get('roi_pct', '—')}%, avg CLV {bh.get('avg_clv_pct', '—')}%)",
        f"Logging complétude ({audit.get('logging_recent_hours')}h) : "
        f"{lr.get('completeness_pct', '—')}% "
        f"({lr.get('n_complete', 0)}/{lr.get('n', 0)} picks)",
        f"Picks semés : CLV={pv.get('clv_seeded', 0)}, value={pv.get('value_picks', 0)}",
        f"CLV ouverts sans closing : {pv.get('clv_missing_closing', 0)} / "
        f"{pv.get('clv_open', 0)} ouverts",
        "",
        s.get("verdict_label") or "—",
    ]
    if s.get("avg_clv_pct") is not None:
        lines.append(f"CLV moyen (scanner) : {s['avg_clv_pct']:+.2f}% (n={s.get('n_clv_settled', 0)})")
    lines.extend(["", audit.get("calendar_note", ""), ""])
    return "\n".join(lines)


def format_telegram(audit: Dict[str, Any]) -> str:
    """Compact Markdown digest for Telegram."""
    s = audit.get("summary") or {}
    bh = audit.get("bet_history") or {}
    lr = audit.get("logging_recent") or {}
    pv = audit.get("pick_volume") or {}
    lines = [
        f"📋 *Audit hebdo* `{audit.get('period_start')}` → `{audit.get('period_end')}`",
        "",
        s.get("verdict_label") or "—",
        "",
        f"• bet_history : *{bh.get('n', 0)}* réglés",
        f"• Logging ({audit.get('logging_recent_hours')}h) : "
        f"*{lr.get('completeness_pct', '—')}%* "
        f"({lr.get('n_complete', 0)}/{lr.get('n', 0)})",
        f"• Picks : CLV *{pv.get('clv_seeded', 0)}* · value *{pv.get('value_picks', 0)}*",
        f"• Sans closing : *{pv.get('clv_missing_closing', 0)}* ouverts",
    ]
    if s.get("avg_clv_pct") is not None:
        lines.append(f"• CLV moyen : *{s['avg_clv_pct']:+.1f}%* (n={s.get('n_clv_settled', 0)})")
    lines.extend(["", f"_{audit.get('calendar_note', '')}_"])
    return "\n".join(lines)


def send_telegram_digest(audit: Optional[Dict[str, Any]] = None) -> bool:
    """Send weekly audit to owner Telegram (reuse digest transport)."""
    from . import digest

    audit = audit or run_audit()
    text = format_telegram(audit)
    return digest._send(text)  # noqa: SLF001 — intentional reuse of proven transport
