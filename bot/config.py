"""Configuration centrale du bot."""
from __future__ import annotations

import os

# --- Chemins ---------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(ROOT, "state")
LOGS_DIR = os.path.join(ROOT, "logs")
MEMORY_FILE = os.path.join(STATE_DIR, "memory.json")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
LOG_FILE = os.path.join(LOGS_DIR, "tennisboss.log")

# --- Réglages par défaut (écrits dans state/config.json au bootstrap) ------
DEFAULT_CONFIG = {
    # Battement de cœur : intervalle (s) entre deux ticks de la boucle.
    "heartbeat_interval": 15,
    # Apprentissage : relancer un cycle de self-learning toutes les N secondes.
    "learn_interval": 300,
    # Années de données ATP à charger depuis internet (Jeff Sackmann).
    "years": [2022, 2023, 2024],
    # Self-healing : backoff exponentiel après erreur (secondes).
    "backoff_start": 5,
    "backoff_max": 300,
    # Apprentissage en ligne.
    "learning_rate": 0.05,
    "l2_reg": 0.0005,
    # Lissage exponentiel des profils joueurs (0 = figé, 1 = uniquement le dernier match).
    "ema_alpha": 0.20,
    # Nombre minimum de matchs avant de considérer un profil "fiable".
    "min_matches_confident": 5,
}

# --- Prior repris de votre script d'origine --------------------------------
# Poids initiaux : serve 0.30, return1 0.25, return2 0.25, recent 0.20
PRIOR_WEIGHTS = {"serve": 0.30, "return1": 0.25, "return2": 0.25, "recent": 0.20}
FEATURE_ORDER = ["serve", "return1", "return2", "recent"]

# Source des données (sans clé API).
SACKMANN_URL = (
    "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/"
    "atp_matches_{year}.csv"
)
# Endpoint "live" (souvent bloqué par Cloudflare -> géré par le self-healing).
SOFASCORE_LIVE_URL = "https://api.sofascore.com/api/v1/sport/tennis/events/live"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
