"""Sauvegarde périodique de la base SQLite (state/tennisboss.db).

Motivation concrète : un incident réel a fait passer la DB de production de
91 946 matchs / 7 758 joueurs à 0/5 163 (schéma réinitialisé pendant une
manipulation manuelle du dossier state/ alors que le service tournait).
Elle n'a été récupérable que par chance (une copie de secours créée par
inadvertance existait encore). Ce module élimine ce hasard.

Utilise l'API de sauvegarde native de sqlite3 (`Connection.backup`) plutôt
qu'une simple copie de fichier : une copie brute pendant une écriture WAL en
cours peut capturer un état incohérent (fichier .db sans son .db-wal), alors
que l'API backup produit un snapshot cohérent même base ouverte.
"""
from __future__ import annotations

import glob
import os
import sqlite3
import time
from typing import List, Optional

from . import config
from .log import log

BACKUP_DIR = os.path.join(config.STATE_DIR, "backups")
MAX_BACKUPS = 28  # à 1 backup/6h -> 7 jours d'historique
_FILENAME_PREFIX = "tennisboss-"
_FILENAME_SUFFIX = ".db"


_last_timestamp = ""
_seq = 0


def _timestamp() -> str:
    """Horodatage unique même sur des appels rapprochés (tests, rattrapage)."""
    global _last_timestamp, _seq
    base = time.strftime("%Y%m%dT%H%M%S")
    if base == _last_timestamp:
        _seq += 1
    else:
        _last_timestamp = base
        _seq = 0
    return f"{base}-{_seq:03d}" if _seq else base


def list_backups() -> List[str]:
    """Chemins des sauvegardes existantes, les plus récentes en dernier."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted(glob.glob(os.path.join(BACKUP_DIR, f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}")))


def _prune(keep: Optional[int] = None) -> int:
    """Supprime les sauvegardes les plus anciennes au-delà de `keep` (MAX_BACKUPS par défaut).

    `keep` lu dynamiquement (pas en valeur par défaut figée à l'import) pour
    que patcher MAX_BACKUPS en test ait un effet réel.
    """
    if keep is None:
        keep = MAX_BACKUPS
    backups = list_backups()
    excess = backups[:-keep] if keep > 0 else backups
    for path in excess:
        try:
            os.remove(path)
        except OSError as exc:
            log(f"Backup: échec suppression {path}: {exc}", "WARN")
    return len(excess)


def backup_now() -> Optional[str]:
    """Crée une sauvegarde cohérente de la DB courante. Renvoie le chemin créé.

    None si la DB source n'existe pas encore (première exécution avant tout
    bootstrap) — pas une erreur à alerter.
    """
    if not os.path.exists(config.DB_FILE):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest_path = os.path.join(BACKUP_DIR, f"{_FILENAME_PREFIX}{_timestamp()}{_FILENAME_SUFFIX}")

    src = sqlite3.connect(config.DB_FILE)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    removed = _prune()
    log(f"Backup: {dest_path} créé"
        + (f", {removed} ancien(s) supprimé(s)" if removed else ""), "INFO")
    return dest_path
