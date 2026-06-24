"""Météo des venues de tennis via Open-Meteo (100% gratuit, sans clé).

Utilisé pour enrichir les prédictions des matchs outdoor (gazon, terre battue).
Impact : vent fort -> avantage serveur, pluie -> surface lente, chaleur -> fatigue.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import requests

from .log import log

BASE = "https://api.open-meteo.com/v1/forecast"
TTL = 1800  # 30 min — la météo ne change pas vite

_CACHE: Dict[str, Tuple[float, Any]] = {}

# Coordonnées GPS des principaux tournois (lat, lon, timezone)
VENUES: Dict[str, Tuple[float, float, str]] = {
    # Grand Chelems
    "wimbledon":         (51.433, -0.214, "Europe/London"),
    "roland garros":     (48.847,  2.249, "Europe/Paris"),
    "australian open":   (-37.820, 144.978, "Australia/Melbourne"),
    "us open":           (40.750, -73.846, "America/New_York"),
    # Masters 1000
    "monte-carlo":       (43.740,  7.427, "Europe/Paris"),
    "madrid":            (40.435, -3.700, "Europe/Madrid"),
    "rome":              (41.929, 12.466, "Europe/Rome"),
    "canada":            (45.508, -73.553, "America/Toronto"),
    "cincinnati":        (39.103, -84.512, "America/New_York"),
    "shanghai":          (31.230, 121.473, "Asia/Shanghai"),
    "miami":             (25.686, -80.237, "America/New_York"),
    "indian wells":      (33.718,-116.301, "America/Los_Angeles"),
    # ATP 500
    "eastbourne":        (50.769,  0.290, "Europe/London"),
    "halle":             (51.923, 8.876, "Europe/Berlin"),
    "queens":            (51.491, -0.207, "Europe/London"),
    "barcelona":         (41.387,  2.170, "Europe/Madrid"),
    "vienna":            (48.208, 16.373, "Europe/Vienna"),
    "basel":             (47.558,  7.587, "Europe/Zurich"),
    "rotterdam":         (51.925,  4.478, "Europe/Amsterdam"),
    "dubai":             (25.205, 55.270, "Asia/Dubai"),
    "acapulco":          (16.853,-99.829, "America/Mexico_City"),
}

# Surfaces par défaut (pour la pertinence météo)
OUTDOOR_SURFACES = {"grass", "clay"}


def _get_coords(tournament_name: str) -> Optional[Tuple[float, float, str]]:
    """Trouve les coordonnées d'un tournoi par correspondance partielle."""
    name_lower = tournament_name.lower()
    for keyword, coords in VENUES.items():
        if keyword in name_lower:
            return coords
    return None


def fetch_weather(tournament_name: str, surface: str = "") -> Optional[Dict[str, Any]]:
    """Retourne la météo actuelle pour un tournoi donné.

    Renvoie None si tournoi inconnu ou si la surface est indoor (hard/carpet).
    """
    # Indoor = météo non pertinente
    if surface and surface.lower() not in OUTDOOR_SURFACES and surface.lower() not in ("", "unknown"):
        return None

    coords = _get_coords(tournament_name)
    if not coords:
        return None

    lat, lon, tz = coords
    cache_key = f"{lat},{lon}"
    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and hit[0] > now:
        return hit[1]

    try:
        r = requests.get(BASE, params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,precipitation,weather_code,relative_humidity_2m",
            "wind_speed_unit": "mph",
            "timezone": tz,
        }, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        current = data.get("current", {})
        result = {
            "temp_c": current.get("temperature_2m"),
            "wind_mph": current.get("wind_speed_10m"),
            "rain_mm": current.get("precipitation", 0.0),
            "humidity_pct": current.get("relative_humidity_2m"),
            "weather_code": current.get("weather_code"),
            "conditions": _describe_weather(current),
            "venue": tournament_name,
        }
        _CACHE[cache_key] = (now + TTL, result)
        return result
    except Exception as exc:
        log(f"Open-Meteo KO pour '{tournament_name}': {exc}", "WARN")
        return None


def weather_impact(weather: Dict[str, Any]) -> Dict[str, float]:
    """Traduit la météo en modificateurs de probabilité (deltas en points).

    Retourne des ajustements à appliquer au favori/outsider selon conditions.
    Positif = avantage supplémentaire au serveur/favori.
    """
    impact = {"server_bonus": 0.0, "surface_speed": 0.0, "fatigue_factor": 0.0}

    wind = weather.get("wind_mph", 0) or 0
    rain = weather.get("rain_mm", 0) or 0
    temp = weather.get("temp_c", 20) or 20

    # Vent fort -> avantage serveur (service difficile à lire)
    if wind > 20:
        impact["server_bonus"] = min((wind - 20) * 0.3, 4.0)

    # Pluie -> surface lente (ralentit le jeu, avantage défenseur/fondeur)
    if rain > 0.5:
        impact["surface_speed"] = -2.0
    elif rain > 2.0:
        impact["surface_speed"] = -4.0

    # Chaleur extrême -> avantage joueur le plus endurant (souvent le mieux classé)
    if temp > 35:
        impact["fatigue_factor"] = (temp - 35) * 0.5

    return impact


def _describe_weather(current: Dict) -> str:
    code = current.get("weather_code", 0)
    wind = current.get("wind_speed_10m", 0)
    rain = current.get("precipitation", 0)
    if rain and rain > 1:
        return "pluie"
    if code in range(51, 68):
        return "bruine/pluie"
    if code in range(71, 78):
        return "neige"
    if code in range(80, 83):
        return "averses"
    if code in (95, 96, 99):
        return "orage"
    if code in range(1, 4):
        return "nuageux"
    if wind and wind > 20:
        return "venteux"
    return "ensoleillé"
