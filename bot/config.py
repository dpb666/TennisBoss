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
# ⚠ INCIDENT (constaté 2026-07-12) : les repos GitHub JeffSackmann/tennis_atp
# et tennis_wta ont DISPARU (404, y compris via l'API — seuls des miroirs
# tiers subsistent, figés ~2026-06-09). Les gabarits restent pointés sur
# l'adresse canonique (si le repo revient) mais sont surchargeables par env
# pour basculer sur un miroir sans toucher au code. L'ingestion de NOUVEAUX
# matchs nécessite une source de remplacement (voir docs/AUDIT.md).
SACKMANN_URL = os.environ.get(
    "SACKMANN_URL_TEMPLATE",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master/"
    "{tour}_matches_{year}.csv",
)
# ATP Futures/Challengers (~18 000 matchs/an, joueurs peu connus).
CHALLENGER_URL = os.environ.get(
    "CHALLENGER_URL_TEMPLATE",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_{tour}/master/"
    "{tour}_matches_futures_{year}.csv",
)
# WTA ITF circuit (W15–W100) — même format CSV, fichier distinct du repo WTA.
# Couvre les joueuses ITF absentes du tableau principal WTA.
WTA_ITF_URL = os.environ.get(
    "WTA_ITF_URL_TEMPLATE",
    "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/"
    "wta_matches_qual_itf_{year}.csv",
)
# Endpoint "live" (souvent bloqué par Cloudflare -> géré par le self-healing).
SOFASCORE_LIVE_URL = "https://api.sofascore.com/api/v1/sport/tennis/events/live"

# Chat IA : Groq cloud primaire, Gemini/Gemma cloud fallback, Ollama local final.
GROQ_API_URL = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

# AI Assistant — outils de lecture seule (ai/chat/), voir
# docs/AI_ASSISTANT_ARCHITECTURE.md Phase 1. Désactivé par défaut : purement
# additif, n'affecte jamais predictor.py/calibrate.py/api_value ni le chat
# existant quand désactivé (comportement identique à avant ce flag).
AI_TOOLS_ENABLED = os.environ.get("TENNISBOSS_AI_TOOLS", "0") == "1"

# Surface detection from league/tournament name
_GRASS_KEYWORDS = {
    "wimbledon", "queen", "halle", "eastbourne", "hertogenbosch",
    "nottingham", "grass", "'s-hertogenbosch", "birmingham",
    "ilkley", "mallorca", "surbiton", "southsea", "roehampton",
    "newport grass", "aldershot",
}
_CLAY_KEYWORDS = {
    "clay", "roland", "french", "rome", "madrid", "barcelona",
    "hamburg", "monte", "bucharest", "istanbul", "estoril",
    "lyon", "geneva", "marrakech", "bastad", "umag",
    "kitzbuhel", "gstaad", "cordoba", "rio", "buenos",
    "stuttgart", "munich", "belgrade", "athens", "cagliari",
    "parma", "perugia", "modena", "foggia", "brescia", "cattolica",
    "poznan", "prostejov", "bratislava", "heilbronn",
    "royan", "makarska", "asuncion", "tucuman",
}
_HARD_KEYWORDS = {
    "hard", "us open", "australian", "dubai",
    "doha", "miami", "indian wells", "montreal", "toronto",
    "cincinnati", "winston", "washington", "tokyo", "beijing",
    "paris", "vienna", "rotterdam", "brisbane", "auckland",
    "adelaide", "sydney", "indoor", "astana", "nur-sultan",
    "riyadh", "dallas", "acapulco", "singapore", "wuhan",
    "shenzhen", "chengdu", "zhuhai", "tianjin",
}

# City → surface: circuit Challenger, ITF M15/M25, odd ATP/WTA events
_CITY_SURFACE: dict = {
    # Grass
    "ilkley": "grass", "mallorca": "grass", "surbiton": "grass",
    "roehampton": "grass", "southsea": "grass", "aldershot": "grass",
    "devonshire": "grass", "loughborough": "grass",
    "newport": "grass",   # Newport RI, USA grass Challenger
    # Clay — Europe
    "ajaccio": "clay", "alkmaar": "clay", "amstelveen": "clay",
    "bakio": "clay", "bergamo": "clay", "brussels": "clay",
    "figueira": "clay", "figueira da foz": "clay",
    "getxo": "clay", "kamen": "clay", "marburg": "clay",
    "monastir": "clay", "nivelles": "clay", "porto": "clay",
    "rabat": "clay", "rzeszow": "clay", "skopje": "clay",
    "slovenska bistrica": "clay", "store": "clay",
    "brescia": "clay", "cattolica": "clay", "heilbronn": "clay",
    "modena": "clay", "foggia": "clay", "perugia": "clay",
    "poznan": "clay", "prostejov": "clay", "bratislava": "clay",
    "makarska": "clay", "royan": "clay",
    "kayseri": "clay", "kursumlijska": "clay", "kursumlijska banja": "clay",
    "nyiregyhaza": "clay", "rosbach": "clay", "szentendre": "clay",
    "tsaghkadzor": "clay", "vaasa": "clay", "ljubljana": "clay",
    "mungia": "clay", "mungia-laukariz": "clay",
    "messina": "clay", "bistrita": "clay", "caltanissetta": "clay",
    "ceska lipa": "clay", "kiseljak": "clay", "martos": "clay",
    "varnamo": "clay", "trieste": "clay", "troyes": "clay",
    "iasi": "clay", "brasov": "clay", "targu mures": "clay",
    "braunschweig": "clay", "plovdiv": "clay", "liege": "clay",
    "bogota": "clay", "piracicaba": "clay", "quito": "clay",
    "cortina": "clay", "portoroz": "clay", "sao paulo": "clay",
    # Clay — South America / North Africa
    "asuncion": "clay", "tucuman": "clay", "san miguel": "clay",
    "cuiaba": "clay", "brasilia": "clay", "buenos aires": "clay",
    "curtea de arges": "clay", "curtea": "clay",
    # Hard — USA
    "cary": "hard", "lakewood": "hard", "los angeles": "hard",
    "wichita": "hard", "san diego": "hard", "claremont": "hard",
    "harmon": "hard", "hillcrest": "hard",
    # Hard — Asia
    "luan": "hard", "maanshan": "hard", "shenzhen": "hard",
    "chengdu": "hard", "beijing": "hard", "tianjin": "hard",
    "nanjing": "hard", "zhuhai": "hard",
    # Hard — misc
    "milan": "hard", "milano": "hard",   # Challenger Milan = indoor hard
    "dublin": "hard",
    # London disambiguation (Wimbledon → grass via keyword, Queen's via keyword)
    # plain "london" in odds-api can be Wimbledon qualifying → grass
    "london": "grass",
    # Misc ATP/WTA named by city only
    "berlin": "clay",      # WTA Berlin (outdoor clay)
    "stuttgart": "clay",   # ATP Stuttgart (clay)
    "munich": "clay",      # ATP Munich
    "lyon": "clay",
    "geneva": "clay",
    "parma": "clay",
    "poznan": "clay",
    "prostejov": "clay",
    "bratislava": "clay",
    "tyler": "hard",       # USA hard
    "knoxville": "hard",
    "boca raton": "hard",
    "budapest": "clay",    # WTA Budapest clay
    "olomouc": "clay",     # Czech Republic clay
    "pozoblanco": "clay",  # Challenger Spain (Jul 2026)
    "bunschoten": "clay",  # Challenger Netherlands
    "tampere": "hard",     # Challenger Finland (outdoor hard)
    "winnipeg": "hard",    # Challenger Canada
}

import re as _re_surf

# Pre-compiled word-boundary patterns for keyword sets
def _build_kw_pattern(kws: set) -> "_re_surf.Pattern":
    # Sort longest first to avoid short match shadowing longer one
    alts = "|".join(_re_surf.escape(k) for k in sorted(kws, key=len, reverse=True))
    return _re_surf.compile(r"\b(?:" + alts + r")\b")

_GRASS_RE = _build_kw_pattern(_GRASS_KEYWORDS)
_CLAY_RE  = _build_kw_pattern(_CLAY_KEYWORDS)
_HARD_RE  = _build_kw_pattern(_HARD_KEYWORDS)


def _extract_city(ln: str) -> str:
    """Extrait le nom de ville depuis les formats courants d'odds-api.io / api-tennis."""
    # "Tennis - ITF Men {City} - {Round}"
    m = _re_surf.search(r"itf (?:men|women|junior[s]?)\s+(.+?)\s*[-–]", ln)
    if m:
        return m.group(1).strip()
    # "Challenger - {City}, {Country}"  or  "Challenger - {City} N, {Country}"
    m = _re_surf.search(r"challenger\s*[-–]\s*([^,\d]+?)(?:\s+\d+)?\s*(?:,|$)", ln)
    if m:
        return m.group(1).strip()
    # "M15 {City}" / "M25 {City}"
    m = _re_surf.match(r"m(?:15|25)\s+(.+?)(?:\s+\d+)?(?:\s*[,(]|$)", ln)
    if m:
        return m.group(1).strip()
    # "ATP - {Tournament}, {City}, {Country}" → take first token after "ATP -"
    m = _re_surf.search(r"(?:atp|wta)\s*[-–]\s*([^,]+)", ln)
    if m:
        return m.group(1).strip()
    return ""


def surface_from_league(league_name: str) -> str:
    """Dérive la surface ('grass'|'clay'|'hard') depuis le nom du tournoi.

    Couches : keywords rapides → dict ville → extraction ville → règle format ITF/M15.
    """
    ln = (league_name or "").lower()
    if not ln:
        return ""

    # 1. Keywords rapides (ATP masters, GS, tournois nommés) — word boundaries
    if _GRASS_RE.search(ln):
        return "grass"
    if _CLAY_RE.search(ln):
        return "clay"
    if _HARD_RE.search(ln):
        return "hard"

    # 2. Dict ville direct sur le nom brut
    for city, surf in _CITY_SURFACE.items():
        if city in ln:
            return surf

    # 3. Parser : extraire la ville puis chercher dans le dict
    city = _extract_city(ln)
    if city:
        for key, surf in _CITY_SURFACE.items():
            if key in city or city in key:
                return surf

    # 4. Règle format : ITF et M15/M25 hors USA/Asie → clay par défaut
    is_itf_format = bool(_re_surf.match(r"(?:tennis\s*-\s*itf|m15|m25)\b", ln))
    if is_itf_format:
        us_asia = {"usa", " ca", " ks", " tx", " fl", "china", "japan", "korea",
                   "taiwan", "hong kong", "philippines", "thailand", "vietnam"}
        if not any(t in ln for t in us_asia):
            return "clay"

    return ""


def tournament_level_from_name(league_name: str) -> str:
    """Dérive un niveau de tournoi ('grand_slam'|'tour'|'challenger_itf'|'other')
    depuis le nom/slug du tournoi — pour le LOGGING uniquement (reproductibilité
    des picks, voir clv_log.tournament_level). N'affecte aucune décision de pari :
    la priorité de scan du _value_scanner_loop a sa propre logique locale
    (_tourn_rank_s dans bot/api.py), volontairement non touchée ici."""
    ln = (league_name or "").lower()
    if not ln:
        return "other"
    if any(k in ln for k in ("wimbledon", "roland-garros", "roland garros",
                              "us-open", "us open", "australian")):
        return "grand_slam"
    if any(k in ln for k in ("challenger", "125k", "itf", "m15", "m25")):
        return "challenger_itf"
    if ln.startswith("atp") or ln.startswith("wta") or " atp" in ln or " wta" in ln:
        return "tour"
    return "other"


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Track Record : mise unitaire analytique (ROI/yield affichés, n'affecte pas les paris).
TRACK_RECORD_STAKE = float(os.environ.get("TENNISBOSS_TRACK_RECORD_STAKE", "1.0"))
