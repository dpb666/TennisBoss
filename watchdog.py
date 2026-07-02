#!/usr/bin/env python3
"""Watchdog externe TennisBoss — surveille et redémarre le serveur si mort.

Usage:
    python3 watchdog.py &          # lance en arrière-plan
    python3 watchdog.py --once     # un seul check (pour cron)

Ce script est INDÉPENDANT du serveur Flask — il survit aux crashs.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HEALTH_URL      = "http://127.0.0.1:8000/health"
SERVE_CMD       = [sys.executable, "run.py", "serve", "--host", "0.0.0.0", "--port", "8000"]
LOG_FILE        = Path("/tmp/tennisboss_server.log")
PID_FILE        = Path("/tmp/tennisboss_watchdog.pid")
SERVER_PID_FILE = Path("/tmp/tennisboss_server.pid")
CHECK_INTERVAL  = 30    # secondes entre chaque ping
STARTUP_GRACE   = 12    # secondes pour que le serveur démarre
MAX_RESTARTS    = 10    # redémarrages max par heure avant pause
ROOT            = Path(__file__).parent


def _ts() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    line = f"[{_ts()}] [WATCHDOG] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _is_alive() -> bool:
    """Ping /health — retourne True si le serveur répond 200."""
    try:
        import urllib.request
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _server_pid() -> int | None:
    """Lit le PID du serveur depuis le fichier PID, vérifie qu'il tourne."""
    if SERVER_PID_FILE.exists():
        try:
            pid = int(SERVER_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # signal 0 = check existence seulement
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    # Fallback: cherche le process par nom
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "run.py serve"], text=True
        ).strip()
        if out:
            return int(out.splitlines()[0])
    except (subprocess.CalledProcessError, ValueError):
        pass
    return None


def _kill_server() -> None:
    """Tue le process serveur s'il tourne encore (zombie ou bloqué)."""
    pid = _server_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if SERVER_PID_FILE.exists():
        SERVER_PID_FILE.unlink(missing_ok=True)


def _start_server() -> subprocess.Popen:
    """Démarre le serveur Flask et écrit son PID."""
    _log("Démarrage du serveur...")
    proc = subprocess.Popen(
        SERVE_CMD,
        cwd=str(ROOT),
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,  # détache du groupe de process du watchdog
    )
    SERVER_PID_FILE.write_text(str(proc.pid))
    _log(f"Serveur démarré (PID {proc.pid}).")
    return proc


def _run_watchdog() -> None:
    """Boucle principale — surveille indéfiniment."""
    PID_FILE.write_text(str(os.getpid()))
    _log(f"Watchdog démarré (PID {os.getpid()}).")

    restarts: list[float] = []
    first_check = True

    while True:
        now = time.time()
        # Purge les redémarrages vieux de plus d'1h
        restarts = [t for t in restarts if now - t < 3600]

        alive = _is_alive()

        if alive:
            if not first_check:
                pass  # silencieux si tout va bien
            first_check = False
            time.sleep(CHECK_INTERVAL)
            continue

        first_check = False
        _log("Serveur injoignable.")

        if len(restarts) >= MAX_RESTARTS:
            _log(f"ALERTE: {MAX_RESTARTS} redémarrages en 1h — pause 10min avant retry.")
            time.sleep(600)
            restarts.clear()
            continue

        _kill_server()
        time.sleep(1)
        _start_server()

        _log(f"Attente {STARTUP_GRACE}s pour le démarrage...")
        time.sleep(STARTUP_GRACE)

        if _is_alive():
            _log("Serveur redémarré avec succès.")
            restarts.append(time.time())
        else:
            _log("Redémarrage échoué — retry dans 30s.")
            restarts.append(time.time())

        time.sleep(CHECK_INTERVAL)


def _run_once() -> None:
    """Mode cron : un seul check, redémarre si mort."""
    if _is_alive():
        return
    _log("Serveur mort détecté (mode --once).")
    _kill_server()
    time.sleep(1)
    _start_server()
    time.sleep(STARTUP_GRACE)
    if _is_alive():
        _log("Redémarré avec succès (mode --once).")
    else:
        _log("Redémarrage échoué (mode --once).")
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Watchdog TennisBoss")
    ap.add_argument("--once", action="store_true", help="Un seul check (mode cron)")
    args = ap.parse_args()

    os.chdir(ROOT)

    if args.once:
        _run_once()
    else:
        _run_watchdog()
