"""Self-healing agent TennisBoss — surveille l'app et corrige les problèmes.

Tourne en thread daemon. Utilise DeepSeek R1 via Ollama pour analyser
les logs et décider des actions correctives.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .log import log

# Configuration
HEALTH_URL      = "http://127.0.0.1:8000/health"
OLLAMA_URL      = "http://127.0.0.1:11434/api/chat"
HEALER_MODEL    = "qwen2.5:7b"    # même modèle que le chat — pas de chargement concurrent
HEALER_FALLBACK = "deepseek-r1:8b"
LOG_FILE        = Path("/tmp/serve.log")
SERVE_CMD       = ["python3", "run.py", "serve"]

HEALTH_INTERVAL    = 60    # secondes entre chaque ping
LOG_INTERVAL       = 900   # analyse logs toutes les 15 min
ACCURACY_INTERVAL  = 1800  # check précision toutes les 30 min
LOG_TAIL_LINES     = 50    # dernières lignes de log à analyser

_running = False
_last_log_check: float = 0.0
_last_accuracy_check: float = 0.0
_server_proc: Optional[subprocess.Popen] = None


def start(mem: Dict[str, Any]) -> None:
    """Démarre le thread healer en arrière-plan."""
    global _running
    _running = True
    t = threading.Thread(target=_loop, args=(mem,), daemon=True, name="healer")
    t.start()
    log("Self-healing agent démarré (DeepSeek R1).", "INFO")


def stop() -> None:
    global _running
    _running = False


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def _loop(mem: Dict[str, Any]) -> None:
    global _last_log_check, _last_accuracy_check
    # Délai initial : laisser le serveur démarrer et le modèle chat se charger
    time.sleep(120)
    _last_log_check = time.time()
    _last_accuracy_check = time.time()
    while _running:
        now = time.time()
        try:
            _check_health()
            if now - _last_log_check > LOG_INTERVAL:
                _check_logs()
                _last_log_check = now
            if now - _last_accuracy_check > ACCURACY_INTERVAL:
                _check_accuracy(mem)
                _last_accuracy_check = now
        except Exception as exc:
            log(f"Healer erreur inattendue : {exc}", "WARN")
        time.sleep(HEALTH_INTERVAL)


# ---------------------------------------------------------------------------
# Vérifications
# ---------------------------------------------------------------------------

def _check_health() -> None:
    """Ping /health — redémarre le serveur si down."""
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code == 200:
            return
        log(f"Healer: /health retourné {r.status_code} — analyse en cours.", "WARN")
    except requests.RequestException:
        log("Healer: API injoignable — tentative de redémarrage.", "WARN")
        _restart_server()


def _check_logs() -> None:
    """Lit les dernières lignes du log, envoie à DeepSeek pour analyse."""
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text(errors="replace").splitlines()
    recent = "\n".join(lines[-LOG_TAIL_LINES:])
    if not any(kw in recent for kw in ("ERROR", "WARN", "Exception", "Traceback", "inaccessible")):
        return  # pas d'anomalie visible

    analysis = _ask_llm(
        f"Voici les derniers logs d'une API Flask Python (TennisBoss):\n\n{recent}\n\n"
        "Identifie les problèmes critiques (1 ligne par problème). "
        "Si tout est normal, réponds seulement: OK"
    )
    if analysis and "ok" not in analysis.lower():
        log(f"Healer analyse logs:\n{analysis}", "WARN")


def _check_accuracy(mem: Dict[str, Any]) -> None:
    """Vérifie la précision ELO via /api/calibration."""
    try:
        r = requests.get("http://127.0.0.1:8000/api/calibration", timeout=5)
        if r.status_code != 200:
            return
        data = r.json()
        acc = data.get("accuracy")
        if acc is None or acc >= 0.55:
            return
        log(f"Healer: précision ELO basse ({acc:.1%}) — analyse.", "WARN")
        analysis = _ask_llm(
            f"La précision du modèle ELO tennis est tombée à {acc:.1%} (seuil: 55%). "
            "Quelles en sont les causes probables et que faire ? 3 lignes max."
        )
        if analysis:
            log(f"Healer recommandation précision:\n{analysis}", "INFO")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Actions correctives
# ---------------------------------------------------------------------------

def _restart_server() -> None:
    """Redémarre le serveur Flask si le process est mort."""
    global _server_proc
    try:
        if _server_proc and _server_proc.poll() is None:
            _server_proc.terminate()
            time.sleep(2)
        import os
        root = Path(__file__).parent.parent
        _server_proc = subprocess.Popen(
            SERVE_CMD, cwd=str(root),
            stdout=open("/tmp/serve.log", "a"),
            stderr=subprocess.STDOUT,
        )
        time.sleep(5)
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code == 200:
            log("Healer: serveur redémarré avec succès.", "INFO")
        else:
            log("Healer: redémarrage échoué — intervention manuelle requise.", "WARN")
    except Exception as exc:
        log(f"Healer: erreur redémarrage : {exc}", "WARN")


# ---------------------------------------------------------------------------
# LLM (DeepSeek R1 via Ollama)
# ---------------------------------------------------------------------------

def _ask_llm(prompt: str, max_tokens: int = 150) -> Optional[str]:
    """Envoie une question à DeepSeek R1 via Ollama — fallback qwen2.5:7b."""
    for model in (HEALER_MODEL, HEALER_FALLBACK):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.2},
                },
                timeout=60,
            )
            if resp.status_code == 404:
                continue  # modèle pas encore dispo
            resp.raise_for_status()
            return (resp.json().get("message") or {}).get("content", "").strip()
        except requests.HTTPError:
            continue
        except Exception as exc:
            log(f"Healer LLM ({model}) inaccessible : {exc}", "WARN")
            return None
    log("Healer: aucun modèle LLM disponible.", "WARN")
    return None
