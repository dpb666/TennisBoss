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
    from .live_api import load_env as _load_env; _load_env()
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
        # Value picks du jour (filtrés : cotes ≤5.0 uniquement, cohérent avec les stats)
        vp_rows = c.execute(
            "SELECT player1, player2, side, odds, ev, result, pnl "
            "FROM value_picks WHERE date LIKE ? AND odds <= 5.0 AND ev >= 8.0 ORDER BY ev DESC",
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

        # Top 5 par EV (filtrer cotes > 15 comme l'app)
        top5 = sorted((r for r in vp_rows if (r["odds"] or 0) <= 15.0),
                      key=lambda r: -(r["ev"] or 0))[:5]
        if not top5:
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

    # ── Stats globales (depuis le début) ─────────────────
    with db.connect() as c:
        glob = c.execute('''
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w,
                   SUM(pnl) as pnl
            FROM value_picks WHERE result IN (0,1) AND odds<=5.0
        ''').fetchone()
    if glob and glob["n"]:
        roi = (glob["pnl"] or 0) / glob["n"] * 100
        lines.append(f"📋 *Depuis le début (cotes ≤5)*")
        lines.append(
            f"  {glob['w']}W/{glob['n']-glob['w']}L sur {glob['n']} picks • "
            f"P&L {_fmt_pnl(glob['pnl'])} • ROI {roi:+.1f}%"
        )
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


def build_picks_summary() -> str:
    """Résumé picks du jour : value + live, avec tournoi/surface/heure."""
    db.init()
    today = datetime.date.today().isoformat()
    with db.connect() as c:
        vp = c.execute(
            "SELECT date, player1, player2, side, odds, ev, result, pnl "
            "FROM value_picks WHERE date LIKE ? AND odds <= 5.0 ORDER BY ev DESC",
            (f"{today}%",)
        ).fetchall()
        ip = c.execute(
            "SELECT pick, league, market_label, odds, result, pnl "
            "FROM inplay_picks "
            "WHERE ts LIKE ? AND result != 'V' ORDER BY id DESC LIMIT 8",
            (f"{today}%",)
        ).fetchall()

    lines = [f"📋 *Picks du {datetime.date.today().strftime('%d/%m/%Y')}*", ""]

    lines.append("🎯 *Value picks*")
    if not vp:
        lines.append("  Aucun pick value aujourd'hui.")
    else:
        settled_vp = [r for r in vp if r["result"] is not None]
        pending_vp = [r for r in vp if r["result"] is None]
        # Bilan only counts in-strategy picks (ev ≥ 8%)
        in_strat = [r for r in settled_vp if (r["ev"] or 0) >= 8.0]
        for r in vp:
            em = "✅" if r["result"] == 1 else "❌" if r["result"] == 0 else "⏳"
            side = (r["side"] or "?")[:20]
            opp = r["player2"] if r["side"] == r["player1"] else r["player1"]
            opp_s = f" vs {opp[:15]}" if opp else ""
            # Heure du match depuis date ISO
            try:
                dt = datetime.datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                heure = dt.strftime("%Hh%M")
            except Exception:
                heure = ""
            heure_s = f" {heure}" if heure else ""
            pnl_s = f" → {_fmt_pnl(r['pnl'])}" if r["result"] is not None else ""
            # Mark off-strategy picks
            strat_mark = "" if (r["ev"] or 0) >= 8.0 else " _(hors filtre)_"
            lines.append(f"  {em} *{side}*{opp_s} @ {r['odds']:.2f} EV{r['ev']:+.0f}%{heure_s}{pnl_s}{strat_mark}")
        if in_strat:
            w = sum(1 for r in in_strat if r["result"] == 1)
            pnl = sum(r["pnl"] for r in in_strat if r["pnl"] is not None)
            lines.append(f"  _Bilan (EV≥8%): {w}W/{len(in_strat)-w}L — P&L {_fmt_pnl(pnl)}_")
        elif settled_vp:
            w = sum(1 for r in settled_vp if r["result"] == 1)
            pnl = sum(r["pnl"] for r in settled_vp if r["pnl"] is not None)
            lines.append(f"  _Bilan: {w}W/{len(settled_vp)-w}L — P&L {_fmt_pnl(pnl)}_")
        if pending_vp:
            lines.append(f"  _{len(pending_vp)} pick(s) en attente_")

    lines.append("")
    lines.append("⚡ *Live picks*")
    if not ip:
        lines.append("  Aucun pick live aujourd'hui.")
    else:
        for r in ip:
            em = "✅" if r["result"] == "W" else "❌" if r["result"] == "L" else "⏳"
            pick = (r["pick"] or "?")[:20]
            mkt = r["market_label"] or ""
            mkt_s = f" [{mkt[:12]}]" if mkt else ""
            odds_s = f" @ {r['odds']:.2f}" if r["odds"] else ""
            pnl_s = f" → {_fmt_pnl(r['pnl'])}" if r["result"] in ("W", "L") else ""
            lines.append(f"  {em} {pick}{mkt_s}{odds_s}{pnl_s}")

    lines.append("")
    lines.append("_/picks /value /clv /digest — TennisBoss_")
    return "\n".join(lines)


def build_value_open() -> str:
    """Liste des picks value actuellement OUVERTS (non settlés), avec détails."""
    db.init()
    with db.connect() as c:
        vp = c.execute(
            "SELECT date, player1, player2, side, odds, ev, kelly_u, league "
            "FROM value_picks WHERE result IS NULL ORDER BY date ASC LIMIT 15"
        ).fetchall()

    if not vp:
        return "🎯 *Value picks ouverts*\n\nAucun pick en attente de résultat."

    lines = ["🎯 *Value picks ouverts*", ""]
    for r in vp:
        side = (r["side"] or "?")[:20]
        opp = r["player2"] if r["side"] == r["player1"] else r["player1"]
        opp_s = f" vs {opp[:15]}" if opp else ""
        try:
            dt = datetime.datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
            heure = dt.strftime("%d/%m %Hh%M")
        except Exception:
            heure = r["date"][:10] if r["date"] else ""
        kelly_s = f" · Kelly `{r['kelly_u']:.1f}%`" if r.get("kelly_u") else ""
        league_s = f"\n   📍 _{(r['league'] or '')[:30]}_" if r.get("league") else ""
        lines.append(f"⏳ *{side}*{opp_s} @ {r['odds']:.2f}")
        lines.append(f"   EV{r['ev']:+.0f}%{kelly_s} — {heure}{league_s}")
    lines.append(f"\n_{len(vp)} pick(s) ouverts_")
    return "\n".join(lines)


def build_clv_report() -> str:
    """Rapport CLV concis pour /clv."""
    try:
        stats = clv.stats()
    except Exception:
        return "❌ Erreur lors du calcul CLV."

    gl = stats.get("global", {})
    verdict_label = stats.get("verdict_label", "—")
    lines = ["📊 *Closing Line Value (CLV)*", ""]
    lines.append(verdict_label)
    lines.append("")

    n_clv = gl.get("n_clv", 0)
    if n_clv:
        lines.append(f"CLV moyen : *{gl.get('avg_clv_pct', 0):+.1f}%*")
        lines.append(f"Beat closing : *{gl.get('beat_closing_pct', 0):.0f}%* "
                     f"(±{gl.get('beat_closing_ci95', 0):.1f}%, n={n_clv})")
    if gl.get("n_settled", 0):
        lines.append(f"ROI flat : *{gl.get('roi_flat_pct', 0):+.1f}%* "
                     f"(n={gl.get('n_settled', 0)})")
        lines.append(f"Win rate : *{gl.get('win_rate_pct', 0):.0f}%*")

    # Par confiance
    bc = stats.get("by_confidence", {})
    for tier, label in [("high", "Conf ≥ 75%"), ("medium", "Conf 60-75%")]:
        t = bc.get(tier, {})
        if t.get("n_settled", 0):
            lines.append(f"\n_{label}_ : {t.get('n_settled')} réglés, "
                         f"ROI {t.get('roi_flat_pct', 0):+.1f}%")

    lines.append("\n_/clv — TennisBoss_")
    return "\n".join(lines)


def build_global_stats() -> str:
    """Bilan global depuis le début : value picks + streaks + par surface."""
    db.init()
    with db.connect() as c:
        # Global (odds ≤ 5.0)
        glob = c.execute('''
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w,
                   SUM(pnl) as pnl,
                   MAX(date) as last_date
            FROM value_picks WHERE result IN (0,1) AND odds <= 5.0 AND ev >= 8.0
        ''').fetchone()

        # Dernières 20 (pour streak)
        recent = c.execute('''
            SELECT result, pnl FROM value_picks
            WHERE result IN (0,1) AND odds <= 5.0 AND ev >= 8.0
            ORDER BY date DESC, ts DESC LIMIT 20
        ''').fetchall()

        # Aujourd'hui
        today = datetime.date.today().isoformat()
        today_row = c.execute('''
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w,
                   SUM(pnl) as pnl
            FROM value_picks WHERE result IN (0,1) AND date LIKE ? AND odds <= 5.0 AND ev >= 8.0
        ''', (f"{today}%",)).fetchone()

        # Cette semaine
        week_start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        week_row = c.execute('''
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w,
                   SUM(pnl) as pnl
            FROM value_picks WHERE result IN (0,1) AND date >= ? AND odds <= 5.0 AND ev >= 8.0
        ''', (week_start,)).fetchone()

    lines = ["📊 *Stats TennisBoss — Bilan Global*", ""]

    if glob and glob["n"]:
        n, w, pnl = glob["n"], glob["w"] or 0, glob["pnl"] or 0.0
        roi = pnl / n * 100
        wr = w / n * 100
        em = "🟢" if pnl > 0 else "🔴"
        lines.append(f"{em} *Depuis le début (cotes ≤5.0)*")
        lines.append(f"  {w}W / {n-w}L sur {n} picks")
        lines.append(f"  WR: {wr:.0f}% | P&L: {_fmt_pnl(pnl)} | ROI: {roi:+.1f}%")
        lines.append("")

    if today_row and today_row["n"]:
        tn, tw, tpnl = today_row["n"], today_row["w"] or 0, today_row["pnl"] or 0.0
        lines.append(f"📅 *Aujourd'hui*")
        lines.append(f"  {tw}W / {tn-tw}L | P&L {_fmt_pnl(tpnl)}")
        lines.append("")

    if week_row and week_row["n"]:
        wn, ww, wpnl = week_row["n"], week_row["w"] or 0, week_row["pnl"] or 0.0
        wroi = wpnl / wn * 100
        lines.append(f"📆 *7 derniers jours*")
        lines.append(f"  {ww}W / {wn-ww}L sur {wn} picks | P&L {_fmt_pnl(wpnl)} | ROI {wroi:+.1f}%")
        lines.append("")

    # Par surface (si données)
    with db.connect() as c:
        surf_rows = c.execute('''
            SELECT surface, COUNT(*) as n,
                   SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w,
                   SUM(pnl) as pnl
            FROM value_picks WHERE result IN (0,1) AND odds<=5.0 AND ev>=8.0
                AND surface IS NOT NULL AND surface != ""
            GROUP BY surface ORDER BY pnl DESC
        ''').fetchall()
        wimb_row = c.execute('''
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w,
                   SUM(pnl) as pnl
            FROM value_picks
            WHERE result IN (0,1) AND odds<=5.0 AND ev>=8.0
              AND date >= "2026-06-23" AND league LIKE "%Wimbledon%"
        ''').fetchone()
    if surf_rows:
        lines.append("🎾 *Par surface (EV≥8%)*")
        for sr in surf_rows:
            sp = (sr["pnl"] or 0) / sr["n"] * 100
            lines.append(f"  {(sr['surface'] or '?').capitalize()}: {sr['w']}W/{sr['n']-sr['w']}L · P&L {_fmt_pnl(sr['pnl'])} · ROI {sp:+.1f}%")
        lines.append("")

    if wimb_row and wimb_row["n"]:
        wn, ww = wimb_row["n"], wimb_row["w"] or 0
        wpnl = wimb_row["pnl"] or 0.0
        wroi = wpnl / wn * 100
        em = "🟢" if wpnl >= 0 else "🔴"
        lines.append(f"{em} *Wimbledon 2026 (EV≥8%)*")
        lines.append(f"  {ww}W/{wn-ww}L sur {wn} picks · P&L {_fmt_pnl(wpnl)} · ROI {wroi:+.1f}%")
        lines.append("")

    # EV band breakdown
    with db.connect() as c:
        ev_bands = [
            ("EV 8-12%", 8.0, 12.0), ("EV 18-30%", 18.0, 30.0),
        ]
        ev_lines = []
        for label, lo, hi in ev_bands:
            r = c.execute('''
                SELECT COUNT(*) as n, SUM(CASE WHEN result=1 THEN 1 ELSE 0 END) as w, SUM(pnl) as pnl
                FROM value_picks WHERE result IN (0,1) AND odds<=5.0 AND ev>=? AND ev<?
            ''', (lo, hi)).fetchone()
            if r and r["n"] and r["n"] >= 3:
                roi = (r["pnl"] or 0) / r["n"] * 100
                ev_lines.append(f"  {label}: {r['w']}W/{r['n']-r['w']}L · ROI {roi:+.1f}%")
    if ev_lines:
        lines.append("📈 *Par tranche EV*")
        lines.extend(ev_lines)
        lines.append("  _(zone 12-18% EV bloquée)_")
        lines.append("")

    # Inplay stats (picks avec cotes connues)
    with db.connect() as c:
        ip_all = c.execute('''
            SELECT result, pnl FROM inplay_picks WHERE result IN ('W','L') AND pnl IS NOT NULL
        ''').fetchall()
    if ip_all:
        ip_w = sum(1 for r in ip_all if r['result'] == 'W')
        ip_pnl = sum(r['pnl'] or 0 for r in ip_all)
        ip_n = len(ip_all)
        lines.append(f"⚡ *Inplay (cotes connues)*")
        lines.append(f"  {ip_w}W / {ip_n - ip_w}L | P&L {_fmt_pnl(ip_pnl)}")
        lines.append("")

    # Streak
    if recent:
        streak_val = recent[0]["result"]
        streak_n = 0
        for r in recent:
            if r["result"] == streak_val:
                streak_n += 1
            else:
                break
        streak_label = f"{'🔥' if streak_val == 1 else '❄️'} Série en cours: {streak_n} {'WIN' if streak_val == 1 else 'LOSS'}"
        lines.append(streak_label)
        lines.append("")

    lines.append("_/picks /value /clv /digest — TennisBoss_")
    return "\n".join(lines)


def send_picks_summary() -> bool:
    """Envoie le résumé on-demand des picks du jour."""
    try:
        text = build_picks_summary()
        return _send(text)
    except Exception as e:
        log(f"digest: /picks erreur — {e}", "ERROR")
        return False
