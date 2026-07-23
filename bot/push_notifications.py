"""Notifications push (Firebase Cloud Messaging) — envoi HTTP v1 direct.

Utilise `google-auth` + `requests` (déjà des dépendances du projet) plutôt
que le SDK `firebase-admin` : ce dernier entraîne google-cloud-firestore/
storage (jamais utilisés ici, on ne fait qu'envoyer des messages) qui
imposent protobuf<6, en conflit avec d'autres projets Python sur cette
machine (tensorflow>=6.31, streamlit<7) partageant le même environnement.
`google-auth` seul (déjà présent) n'a aucune dépendance sur protobuf.

Doc FCM HTTP v1 : https://firebase.google.com/docs/cloud-messaging/migrate-v1
  POST https://fcm.googleapis.com/v1/projects/{project_id}/messages:send

Clé de compte de service : secrets/firebase-adminsdk.json (hors git). Chemin
configurable via FIREBASE_ADMIN_KEY_PATH. L'ancien emplacement
(state/firebase-adminsdk.json) reste lu en repli, avec un avertissement, pour
les déploiements pas encore migrés (debt D-6).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional

import requests

from . import config
from .log import log

_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
_FCM_URL_TMPL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

_lock = threading.Lock()
_cached_token: Optional[str] = None
_cached_token_expiry: float = 0.0
_project_id: Optional[str] = None


_warned_legacy_path = False


def _key_path() -> str:
    """Résout le chemin de la clé FCM.

    Priorité : FIREBASE_ADMIN_KEY_PATH (env) > secrets/firebase-adminsdk.json
    (nouvel emplacement) > state/firebase-adminsdk.json (ancien emplacement,
    repli avec avertissement — debt D-6, à migrer sans casser un déploiement
    existant)."""
    global _warned_legacy_path
    override = os.environ.get("FIREBASE_ADMIN_KEY_PATH", "").strip()
    if override:
        return override
    new_path = os.path.join(config.SECRETS_DIR, "firebase-adminsdk.json")
    if os.path.exists(new_path):
        return new_path
    legacy_path = os.path.join(config.STATE_DIR, "firebase-adminsdk.json")
    if os.path.exists(legacy_path):
        if not _warned_legacy_path:
            log(f"Clé FCM lue depuis l'ancien emplacement {legacy_path} — "
                f"déplacer vers {new_path} (debt D-6).", "WARN")
            _warned_legacy_path = True
        return legacy_path
    return new_path


def is_enabled() -> bool:
    return os.path.exists(_key_path())


def _access_token() -> Optional[str]:
    """Jeton OAuth2 pour l'API FCM, mis en cache jusqu'à expiration (~1h)."""
    global _cached_token, _cached_token_expiry, _project_id
    with _lock:
        if _cached_token and time.time() < _cached_token_expiry:
            return _cached_token
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            path = _key_path()
            with open(path, encoding="utf-8") as f:
                _project_id = json.load(f).get("project_id")
            creds = service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)
            creds.refresh(Request())
            _cached_token = creds.token
            # expiry côté google-auth est un datetime naïf UTC ; marge de sécurité 60s.
            _cached_token_expiry = time.time() + 3000  # ~50min (tokens FCM valides 1h)
            return _cached_token
        except Exception as exc:  # noqa: BLE001
            log(f"Push: échec obtention token FCM: {exc}", "ERROR")
            return None


def send_push(device_token: str, title: str, body: str,
              data: Optional[Dict[str, str]] = None) -> Optional[bool]:
    """Envoie une notification push à un appareil.

    True = accepté par FCM. False = token invalide/désinstallé (404/400 —
    à retirer de la base, ne jamais ré-essayer). None = échec transitoire
    (réseau, quota, 5xx) — ne rien conclure sur la validité du token.
    """
    if not is_enabled():
        return None
    token = _access_token()
    if not token or not _project_id:
        return None

    payload: Dict[str, Any] = {
        "message": {
            "token": device_token,
            "notification": {"title": title, "body": body},
        }
    }
    if data:
        payload["message"]["data"] = {str(k): str(v) for k, v in data.items()}

    try:
        resp = requests.post(
            _FCM_URL_TMPL.format(project_id=_project_id),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload, timeout=8,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (400, 404):
            log(f"Push: token invalide/désinstallé ({resp.status_code})", "INFO")
            return False
        log(f"Push: FCM a refusé le message ({resp.status_code}): {resp.text[:200]}", "WARN")
        return None
    except Exception as exc:  # noqa: BLE001
        log(f"Push: erreur envoi FCM: {exc}", "ERROR")
        return None


def broadcast(title: str, body: str, data: Optional[Dict[str, str]] = None) -> int:
    """Envoie à tous les appareils enregistrés. Renvoie le nombre de succès."""
    from . import db
    if not is_enabled():
        return 0
    sent = 0
    for row in db.list_device_tokens():
        result = send_push(row["token"], title, body, data)
        if result is True:
            sent += 1
        elif result is False:
            db.delete_device_token(row["token"])
    return sent
