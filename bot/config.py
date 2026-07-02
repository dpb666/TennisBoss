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
DB_FILE = os.path.join(STATE_DIR, "tennisboss.db")  # base SQLite "solide"

# --- Réglages par défaut (écrits dans state/config.json au bootstrap) ------
DEFAULT_CONFIG = {
    # Battement de cœur : intervalle (s) entre deux ticks de la boucle.
    "heartbeat_interval": 15,
    # Apprentissage : relancer un cycle de self-learning toutes les N secondes.
    "learn_interval": 300,
    # Années de données ATP à charger depuis internet (Jeff Sackmann).
    "years": [2022, 2023, 2024, 2025, 2026],
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
    # Tours couverts pour le dictionnaire "tous les joueurs" : ATP (H) + WTA (F).
    "tours": ["atp", "wta"],
    # Inclure ATP Futures / Challengers + WTA ITF W15-W100 pour profiler les petits joueurs.
    "include_challengers": True,
    # Années pour les données challengers/ITF (limité pour ne pas surcharger).
    "challenger_years": [2024, 2025, 2026],
    # Backtest : fraction finale des matchs réservée au test (hors apprentissage).
    "backtest_test_fraction": 0.25,
    # --- API live officielle (vous fournirez une clé test puis l'abonnement) --
    # L'adaptateur lit la clé depuis l'env TENNISBOSS_API_KEY, sinon ce champ.
    "live_api_provider": "api-tennis",    # actif : clé lue dans .env (AT_API_KEY)
    "live_api_key": "",
}

# --- Prior repris de votre script d'origine --------------------------------
# Poids initiaux : serve 0.30, return1 0.25, return2 0.25, recent 0.20
PRIOR_WEIGHTS = {"serve": 0.30, "return1": 0.25, "return2": 0.25, "recent": 0.20}
FEATURE_ORDER = ["serve", "return1", "return2", "recent"]

# Sources de données ouvertes (sans contournement, sans clé API).
#   tour = "atp" (hommes) ou "wta" (femmes).
SACKMANN_URL = (
    "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master/"
    "{tour}_matches_{year}.csv"
)
# ATP Futures/Challengers (~18 000 matchs/an, joueurs peu connus).
CHALLENGER_URL = (
    "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master/"
    "{tour}_matches_futures_{year}.csv"
)
# WTA ITF circuit (W15–W100) — même format CSV, fichier distinct du repo WTA.
# Couvre les joueuses ITF absentes du tableau principal WTA.
WTA_ITF_URL = (
    "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/"
    "wta_matches_qual_itf_{year}.csv"
)
# Endpoint "live" (souvent bloqué par Cloudflare -> géré par le self-healing).
SOFASCORE_LIVE_URL = "https://api.sofascore.com/api/v1/sport/tennis/events/live"

# Chat IA : Groq cloud primaire, Gemini/Gemma cloud fallback, Ollama local final.
GROQ_API_URL = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

# Surface detection from league/tournament name
_GRASS_KEYWORDS = {"wimbledon", "queen", "halle", "eastbourne", "hertogenbosch",
                   "notting", "grass", "'s-hertogenbosch", "birmingham"}
_CLAY_KEYWORDS  = {"clay", "roland", "french", "rome", "madrid", "barcelona",
                   "hamburg", "monte", "bucharest", "istanbul", "estoril",
                   "lyon", "geneva", "marrakech", "bastad", "umag",
                   "kitzbuhel", "gstaad", "cordoba", "rio", "buenos"}
_HARD_KEYWORDS  = {"hard", "open", "us open", "australian", "dubai",
                   "doha", "miami", "indian wells", "montreal", "toronto",
                   "cincinnati", "winston", "washington", "tokyo", "beijing",
                   "paris", "vienna", "rotterdam", "brisbane", "auckland",
                   "adelaide", "sydney", "indoor"}


def surface_from_league(league_name: str) -> str:
    """Dérive la surface ('grass'|'clay'|'hard') depuis le nom du tournoi."""
    ln = (league_name or "").lower()
    if any(k in ln for k in _GRASS_KEYWORDS):
        return "grass"
    if any(k in ln for k in _CLAY_KEYWORDS):
        return "clay"
    if any(k in ln for k in _HARD_KEYWORDS):
        return "hard"
    return ""


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
