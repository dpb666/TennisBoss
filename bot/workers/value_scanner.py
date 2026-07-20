"""Value-picks background scanner worker.

Extracted from ``bot/api.py::_value_scanner_loop`` (api.py decomposition Phase 5).

Detects value picks from live odds using the frozen predictor pipeline — decision
gates are unchanged; only the hosting module moved. Shared state is exposed for
``GET /api/scanner/status``.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set

from .. import calibrate, clv, config, db, features, intelligence, mistake_learner, odds_api, predictor
from ..log import log

DEFAULT_STARTUP_DELAY_S = 45
DEFAULT_LOOP_INTERVAL_S = 90
MAX_ODDS_PER_CYCLE = 25
HIGH_CONF_MIN_EV_DEFAULT = 15.0

# Shared with GET /api/scanner/status (imported by bot.api for compatibility).
SCANNER_STATE: Dict[str, Any] = {
    "running": False,
    "last_cycle_ts": None,
    "next_cycle_ts": None,
    "interval": DEFAULT_LOOP_INTERVAL_S,
    "total_events": 0,
    "checked": 0,
    "cap": MAX_ODDS_PER_CYCLE,
    "active_picks": 0,
    "last_pick_ts": None,
    "last_pick": None,
    "rejections": {},
    "near_misses": [],
}
SCANNER_STATE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ScannerDeps:
    """Runtime dependencies injected from ``bot.api`` (avoids import cycles)."""

    get_mem: Callable[[], Dict[str, Any]]
    resolve: Callable[[str], Optional[str]]
    calibrate_match_prob: Callable[[float], float]
    get_calib_k: Callable[[], float]
    get_market_blend_w: Callable[[], float]
    build_pick_repro: Callable[..., Dict[str, Any]]
    set_to_match_prob: Callable[[float], float]
    high_conf_min_ev: float = HIGH_CONF_MIN_EV_DEFAULT


def get_status() -> Dict[str, Any]:
    """Thread-safe snapshot for ``/api/scanner/status``."""
    with SCANNER_STATE_LOCK:
        return dict(SCANNER_STATE)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"Worker config: {name}={raw!r} invalide — défaut {default}.", "WARN")
        return default


def _tourn_rank(event: Dict[str, Any]) -> int:
    league = event.get("league") or {}
    slug = "" if isinstance(league, str) else league.get("slug", "")
    if any(k in slug for k in ("wimbledon", "roland-garros", "us-open", "australian")):
        return 0
    if slug.startswith("atp") or slug.startswith("wta"):
        return 1
    if any(k in slug for k in ("challenger", "125k", "itf")):
        return 3
    return 2


@dataclass
class _ScannerSession:
    """Per-daemon mutable caches (persist across cycles)."""

    seen: Dict[str, float] = field(default_factory=dict)
    no_odds_seen: Dict[str, float] = field(default_factory=dict)
    alerted: Set[str] = field(default_factory=set)


def run_scanner_cycle(
    deps: ScannerDeps,
    session: _ScannerSession,
    *,
    interval: int = DEFAULT_LOOP_INTERVAL_S,
) -> Dict[str, Any]:
    """Run one scanner cycle (testable). Returns cycle summary."""
    from .. import realtime_alerts as realtime_alerts_mod

    summary: Dict[str, Any] = {
        "skipped": False,
        "reason": None,
        "events_total": 0,
        "odds_calls": 0,
        "picks_alerted": 0,
    }

    if not odds_api.is_enabled() or odds_api._current_key() is None:
        summary["skipped"] = True
        summary["reason"] = "odds_api_unavailable"
        return summary

    mem = deps.get_mem()
    mkt_w = deps.get_market_blend_w()
    calib_k = deps.get_calib_k()
    now_utc = dt.datetime.now(dt.timezone.utc)
    near_misses: list = []
    rankings_cache = db.get_all_player_rankings()

    events = sorted(odds_api.fetch_tennis_events(upcoming_only=True), key=_tourn_rank)
    odds_calls = 0
    rej_time = rej_seen = rej_no_odds = rej_conf = rej_mkt = rej_ev = 0
    rej_dead = rej_bl = rej_surf = 0

    for event in events:
        if odds_calls >= MAX_ODDS_PER_CYCLE:
            break

        eid = str(event.get("id", ""))
        if not eid:
            continue

        event_date = event.get("commence_time") or event.get("date") or ""
        hours_ahead: Optional[float] = None
        if event_date:
            try:
                edt = dt.datetime.fromisoformat(str(event_date).replace("Z", "+00:00"))
                hours_ahead = (edt - now_utc).total_seconds() / 3600
                if hours_ahead > 6.0 or hours_ahead < -1.0:
                    rej_time += 1
                    continue
            except Exception as exc:  # noqa: BLE001
                log(
                    f"Parsing date événement échoué ({event_date!r}: {exc}) "
                    "— filtre temporel ignoré (scanner).",
                    "WARN",
                )

        if eid in session.alerted:
            continue

        last_check = session.seen.get(eid, 0.0)
        recheck_window = hours_ahead is not None and hours_ahead < 2.0
        if last_check and not recheck_window:
            if time.time() - last_check < 600:
                rej_seen += 1
                continue

        no_odds_ts = session.no_odds_seen.get(eid, 0.0)
        if no_odds_ts and time.time() - no_odds_ts < 600:
            rej_no_odds += 1
            continue

        mw = odds_api.fetch_match_winner(eid)
        session.seen[eid] = time.time()
        odds_calls += 1

        if not mw or not mw.get("home_odds") or not mw.get("away_odds"):
            session.no_odds_seen[eid] = time.time()
            rej_no_odds += 1
            continue

        n1 = deps.resolve(event.get("home", "")) or str(event.get("home", "")).strip()
        n2 = deps.resolve(event.get("away", "")) or str(event.get("away", "")).strip()
        if not n1 or not n2:
            continue

        try:
            db.record_market_snapshot(
                eid, n1, n2, mw["home_odds"], mw["away_odds"],
                hours_ahead=round(hours_ahead, 2) if hours_ahead is not None else None,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"record_market_snapshot échoué pour {n1} vs {n2} ({exc}) — ligne non archivée.", "WARN")

        t1 = (mem.get("players") or {}).get(n1, {}).get("tour", "")
        t2 = (mem.get("players") or {}).get(n2, {}).get("tour", "")
        if t1 and t2 and {t1, t2} == {"atp", "wta"}:
            continue

        league_obj = event.get("league")
        league_name = (
            league_obj.get("name", "") if isinstance(league_obj, dict) else str(league_obj or "")
        )
        surface = db.resolve_pick_surface(
            n1, n2, league_name, event.get("surface"), event.get("date", ""),
        )

        try:
            f1 = features.feature_vector(features.get_profile(mem, n1))
            f2 = features.feature_vector(features.get_profile(mem, n2))
            prediction = predictor.predict(mem, n1, f1, n2, f2, surface=surface or None)
        except Exception as exc:  # noqa: BLE001
            log(f"Prédiction échouée pour {n1} vs {n2} (scanner) ({exc}) — événement ignoré.", "WARN")
            continue

        tier = _tourn_rank(event)
        conf_threshold = 0.65 if tier >= 3 else 0.55
        if prediction.get("confidence", 0.0) < conf_threshold:
            rej_conf += 1
            continue

        pm1_raw = deps.set_to_match_prob(prediction["prob1"] / 100.0)
        pm1 = deps.calibrate_match_prob(pm1_raw)
        pm2 = 1.0 - pm1
        ho, ao = mw["home_odds"], mw["away_odds"]
        pb1 = calibrate.blend_probs(pm1, mw["home_prob"], mkt_w)
        pb2 = 1.0 - pb1
        ev1 = pb1 * ho - 1.0
        ev2 = pb2 * ao - 1.0

        if mkt_w > 0.05:
            model_beats_mkt1 = pm1 > mw["home_prob"]
            model_beats_mkt2 = pm2 > mw["away_prob"]
        else:
            model_beats_mkt1 = model_beats_mkt2 = True

        if ev1 >= ev2:
            best_side, best_ev, pick_odds, pb_pick = n1, ev1, ho, pb1
            if not model_beats_mkt1:
                rej_mkt += 1
                continue
        else:
            best_side, best_ev, pick_odds, pb_pick = n2, ev2, ao, pb2
            if not model_beats_mkt2:
                rej_mkt += 1
                continue

        best_ev_pct = round(best_ev * 100, 1)
        dead_zone = 12.0 <= best_ev_pct < 18.0
        below_floor = pick_odds < 1.40
        above_ceil = pick_odds > 5.0
        implied = 1.0 / pick_odds if pick_odds > 1.0 else 1.0
        overconfident = (pb_pick / implied) > 3.0
        learned_danger = mistake_learner.is_danger_zone(best_ev_pct, pick_odds, surface or None)
        intel_blacklist = intelligence.is_blacklisted(best_side)
        intel_surf_danger = intelligence.is_surface_danger(surface or None)
        high_conf_low_ev = (
            prediction["confidence"] >= 0.75 and best_ev_pct < deps.high_conf_min_ev
        )

        if best_ev_pct < 8.0 or below_floor or above_ceil or overconfident or high_conf_low_ev:
            rej_ev += 1
            if 2.0 <= best_ev_pct < 8.0 and not below_floor and not above_ceil and not overconfident:
                near_misses.append({
                    "player1": n1, "player2": n2,
                    "side": best_side, "ev": best_ev_pct,
                    "odds": pick_odds,
                    "hours": round(hours_ahead, 1) if hours_ahead else None,
                    "league": league_name,
                })
            continue
        if dead_zone or learned_danger:
            rej_dead += 1
            continue
        if intel_blacklist:
            rej_bl += 1
            continue
        if intel_surf_danger:
            rej_surf += 1
            continue

        b = pick_odds - 1.0
        kelly = round(max(0.0, (pb_pick * b - (1.0 - pb_pick)) / b * 0.25 * 100), 1) if b > 0 else 0.0
        honeypot = None
        try:
            from .. import weather_profile as weather_profile_mod
            honeypot = weather_profile_mod.analyze(
                mem, n1, features.get_profile(mem, n1),
                n2, features.get_profile(mem, n2),
                None, league_name, surface or "hard",
            ).get("honeypot")
        except Exception as exc:  # noqa: BLE001
            log(
                f"weather_profile.analyze (honeypot) échoué pour {n1} vs {n2} (scanner) ({exc}) — ignoré.",
                "WARN",
            )

        try:
            db.log_value_pick(
                event.get("date", ""), n1, n2, best_side,
                pick_odds, best_ev_pct, league=league_name,
                surface=surface, kelly_u=kelly,
            )
            opponent = n2 if best_side == n1 else n1
            repro = deps.build_pick_repro(
                best_side, opponent,
                pm1_raw if best_side == n1 else (1.0 - pm1_raw),
                pm1 if best_side == n1 else pm2,
                mw["home_prob"] if best_side == n1 else mw["away_prob"],
                best_ev_pct, surface, league_name, rankings_cache,
                calib_k, mkt_w, event_key=eid, home_player=n1,
            )
            clv.seed_pick(
                eid, event.get("date", ""), n1, n2, best_side,
                pick_odds, pb_pick, prediction["confidence"],
                honeypot=honeypot, repro=repro,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"log_value_pick/seed_pick échoué pour {n1} vs {n2} (scanner) ({exc}) — pick non archivé.", "WARN")
            continue

        alerter = realtime_alerts_mod.get()
        if alerter:
            hours_label = f"{hours_ahead:.1f}h" if hours_ahead is not None else "?"
            urgency = "⚡" if (hours_ahead is not None and hours_ahead < 1.0) else "🔔"
            fair_prob = mw["home_prob"] if best_side == n1 else mw["away_prob"]
            fair_odds = round(1.0 / fair_prob, 2) if fair_prob > 0 else None
            pick_entry = {
                "player1": n1, "player2": n2,
                "best_side": best_side, "best_ev": best_ev_pct,
                "pick_odds": pick_odds, "kelly_u": kelly,
                "confidence_label": prediction.get("confidence_label", ""),
                "league": league_name,
                "surface": surface or "",
                "fair_odds": fair_odds,
                "best_book": (mw.get("books") or [""])[0] if mw.get("books") else "",
                "hours_ahead": hours_ahead,
                "urgency": urgency,
                "scanner": True,
            }
            threading.Thread(
                target=alerter.on_value_pick,
                args=(pick_entry,),
                daemon=True,
                name=f"scanner-alert-{eid}",
            ).start()
            log(f"{urgency} Scanner value pick: {best_side} EV+{best_ev_pct}% @ {pick_odds} ({hours_label} avant match)")

        session.alerted.add(eid)
        summary["picks_alerted"] += 1
        with SCANNER_STATE_LOCK:
            SCANNER_STATE["last_pick_ts"] = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            SCANNER_STATE["last_pick"] = {
                "side": best_side, "ev": best_ev_pct,
                "odds": pick_odds,
                "hours": round(hours_ahead, 1) if hours_ahead else None,
                "league": league_name,
            }

    now_iso = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    next_iso = (dt.datetime.utcnow() + dt.timedelta(seconds=interval)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with SCANNER_STATE_LOCK:
        SCANNER_STATE.update({
            "last_cycle_ts": now_iso,
            "next_cycle_ts": next_iso,
            "total_events": len(events),
            "checked": odds_calls,
            "cap": MAX_ODDS_PER_CYCLE,
            "active_picks": len(session.alerted),
            "rejections": {
                "fenetre": rej_time, "cache": rej_seen,
                "no_odds": rej_no_odds, "conf": rej_conf,
                "mkt": rej_mkt, "ev": rej_ev,
                "zone": rej_dead, "bl": rej_bl, "surf": rej_surf,
            },
            "near_misses": near_misses[:10],
        })

    if len(session.seen) > 500 or len(session.no_odds_seen) > 500:
        cutoff = time.time() - 28800
        session.seen = {k: v for k, v in session.seen.items() if v > cutoff}
        session.no_odds_seen = {k: v for k, v in session.no_odds_seen.items() if v > cutoff}

    log(
        f"Scanner: {odds_calls}/{MAX_ODDS_PER_CYCLE} vérifiés ({len(events)} events)"
        f" | skip: fenêtre={rej_time} cache={rej_seen} no_odds={rej_no_odds}"
        f" conf={rej_conf} mkt={rej_mkt} EV={rej_ev} zone={rej_dead} BL={rej_bl} surf={rej_surf}"
        f" | {len(session.alerted)} pick(s) actifs",
    )

    summary.update({
        "events_total": len(events),
        "odds_calls": odds_calls,
    })
    return summary


def run_loop(
    *,
    interval: Optional[int] = None,
    deps: ScannerDeps,
    startup_delay: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    session: Optional[_ScannerSession] = None,
) -> None:
    """Daemon loop: scan for value picks until ``stop_event`` is set."""
    _interval = interval if interval is not None else _env_int(
        "SCANNER_INTERVAL_S", DEFAULT_LOOP_INTERVAL_S,
    )
    _startup = startup_delay if startup_delay is not None else _env_int(
        "SCANNER_STARTUP_DELAY_S", DEFAULT_STARTUP_DELAY_S,
    )
    _stop = stop_event or threading.Event()
    _session = session or _ScannerSession()

    if _startup > 0:
        if _stop.wait(_startup):
            return

    log(f"Value scanner démarré (intervalle {_interval}s).")
    with SCANNER_STATE_LOCK:
        SCANNER_STATE["running"] = True
        SCANNER_STATE["interval"] = _interval

    while not _stop.is_set():
        try:
            run_scanner_cycle(deps, _session, interval=_interval)
        except Exception as exc:  # noqa: BLE001
            log(f"Value scanner erreur: {exc}", "WARN")
        if _stop.wait(_interval):
            break


def start_daemon_thread(
    *,
    interval: Optional[int] = None,
    deps: ScannerDeps,
) -> threading.Thread:
    """Start the worker in a daemon thread (used by ``api.serve()``)."""
    thread = threading.Thread(
        target=run_loop,
        kwargs={"interval": interval, "deps": deps},
        daemon=True,
        name="value-scanner-worker",
    )
    thread.start()
    return thread
