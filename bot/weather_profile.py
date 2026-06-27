"""Profil météo par joueur : croise style de jeu + conditions météo + foule.

Tout repose sur les données DÉJÀ en mémoire (pas d'API supplémentaire) :
  - Profil joueur (serve, return1, return2, n) → style de jeu
  - Win rate par surface → préférence terrain
  - Conditions météo actuelles (temp, vent, pluie) → impact heuristique

Résultat : qui bénéficie des conditions, quelle est l'ampleur, et si la
foule joue en faveur d'un des deux joueurs (potentiel honeypot marché).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# Joueurs "à domicile" par tournoi (nom du tournoi → pattern noms)
# ──────────────────────────────────────────────────────────────────────────────
_HOME_PATTERNS: list[tuple[str, list[str]]] = [
    # Roland Garros / French Open → joueurs français
    ("roland|french open|paris|open de france",
     ["gasquet", "moutet", "rinderknech", "mannarino", "monfils", "humbert",
      "chardy", "simon", "mahut", "cornet", "garcia", "dodin", "parry",
      "rune", "tsitsipas", "marozsan"]),  # souvent cheers aussi
    # Wimbledon → joueurs britanniques
    ("wimbledon|queens|eastbourne",
     ["murray", "evans", "draper", "norrie", "edmund", "skupski",
      "watson", "raducanu", "boulter", "broady", "dart"]),
    # US Open → joueurs américains
    ("us open|flushing|washington|atlanta|cincinnati",
     ["tiafoe", "fritz", "paul", "isner", "sock", "querrey", "opelka",
      "nakashima", "kovacevic", "korda", "harris", "keys", "gauff",
      "pegula", "collins", "navarro"]),
    # Australian Open → australiens
    ("australian|melbourne|sydney|brisbane|adelaide",
     ["kyrgios", "de minaur", "kokkinakis", "thompson", "popyrin",
      "hijikata", "duckworth", "tomljanovic", "stosur", "barty"]),
    # Madrid / Barcelona → espagnols
    ("madrid|barcelona|valencia",
     ["alcaraz", "davidovich", "carballes", "zapata", "munar",
      "badosa", "sorribes", "martinez", "bolsova"]),
    # Rome → italiens
    ("rome|foro italico|internazionali",
     ["sinner", "musetti", "sonego", "fognini", "berrettini",
      "cobolli", "darderi", "arnaldi", "trevisan", "paolini", "bronzetti"]),
    # Monte Carlo / Rolex Paris Masters → Monaco vibe (pas vraiment home)
    # Canada → canadiens
    ("canada|montreal|toronto",
     ["auger-aliassime", "shapovalov", "andreescu", "fernandez",
      "diallo", "tabilo"]),
]


def _is_home(player_name: str, tournament: str) -> bool:
    """Vrai si le joueur est 'à domicile' pour ce tournoi."""
    if not player_name or not tournament:
        return False
    pn = player_name.lower()
    tn = tournament.lower()
    for pattern, players in _HOME_PATTERNS:
        if re.search(pattern, tn):
            if any(p in pn for p in players):
                return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Style de jeu à partir du profil features
# ──────────────────────────────────────────────────────────────────────────────

def player_style(profile: Dict[str, float]) -> Dict[str, Any]:
    """Classe le joueur en termes de style de jeu depuis son profil."""
    serve = float(profile.get("serve", 0.5))
    ret1 = float(profile.get("return1", 0.5))
    ret2 = float(profile.get("return2", 0.5))
    avg_return = (ret1 + ret2) / 2.0
    n = int(profile.get("n", 0))

    # Style dominant
    serve_edge = serve - avg_return
    if serve_edge > 0.08:
        style = "serve_dominant"
        style_label = "Serveur dominant"
    elif serve_edge < -0.06:
        style = "baseline_returner"
        style_label = "Baseliner / Returneur"
    else:
        style = "all_court"
        style_label = "Joueur polyvalent"

    return {
        "style": style,
        "style_label": style_label,
        "serve_score": round(serve, 3),
        "return_score": round(avg_return, 3),
        "serve_edge": round(serve_edge, 3),
        "n_matches": n,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Win rate par surface depuis la mémoire (accumulé par learner)
# ──────────────────────────────────────────────────────────────────────────────

def surface_win_rate(mem: Dict[str, Any], player: str) -> Dict[str, Optional[float]]:
    """Win rate par surface extrait de l'ELO surface (proxy).

    L'ELO de surface est centré à 1500 (neutre). On convertit en taux approximatif :
    si ELO_surface > ELO_global → surperforme sur cette surface.
    """
    elo_global = mem.get("elo") or {}
    elo_surf = mem.get("elo_surface") or {}
    result: Dict[str, Optional[float]] = {}
    for surf in ("hard", "clay", "grass"):
        surf_r = (elo_surf.get(surf) or {}).get(player)
        if surf_r is not None:
            # Delta vs base 1500 (= joueur moyen) : mesure la spécialisation surface
            # ±100 ELO ≈ ±14% de win rate vs adversaire moyen
            delta = surf_r - 1500.0
            approx = 0.5 + delta / 700.0
            result[surf] = round(max(0.3, min(0.8, approx)), 2)
        else:
            result[surf] = None
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Impact météo sur le matchup
# ──────────────────────────────────────────────────────────────────────────────

def weather_impact(
    weather: Dict[str, Any],
    style1: Dict[str, Any],
    style2: Dict[str, Any],
    surface: str = "hard",
) -> Dict[str, Any]:
    """Calcule l'avantage météo pour chaque joueur.

    Heuristiques calibrées sur la littérature tennis :
    - Vent fort  → avantage serveur (rallies perturbés, gros service = +)
    - Pluie/froid → avantage returneur (balle lente, échanges longs)
    - Chaleur    → avantage joueur avec plus de matchs (endurance/expérience)
    - Herbe      → amplifie vent (balle basse + vent = chaos)
    """
    wind_mph = float(weather.get("wind_mph") or 0)
    rain_mm = float(weather.get("rain_mm") or 0)
    temp_c = float(weather.get("temp_c") or 20)
    humidity = float(weather.get("humidity_pct") or 50)

    factors: list[tuple[str, float, str]] = []  # (beneficiary, magnitude, reason)

    # ── Vent ───────────────────────────────────────────────────────────────────
    if wind_mph >= 12:
        intensity = min((wind_mph - 10) / 20.0, 1.0)  # 0..1
        # Le serveur bénéficie du vent (service direct, adversaire déstabilisé)
        edge1 = style1["serve_edge"]
        edge2 = style2["serve_edge"]
        wind_adv = (edge1 - edge2) * intensity * 0.3
        factors.append(("p1" if wind_adv > 0 else "p2", abs(wind_adv),
                        f"Vent {wind_mph:.0f}mph → avantage serveur"))
        # Herbe amplifie l'effet du vent
        if surface == "grass" and wind_mph >= 15:
            extra = intensity * 0.1 * (1 if wind_adv > 0 else -1)
            factors.append(("p1" if extra > 0 else "p2", abs(extra),
                            "Surface herbe amplifie le vent"))

    # ── Pluie / Conditions lentes ─────────────────────────────────────────────
    if rain_mm >= 0.5 or (temp_c < 12 and surface in ("grass", "hard")):
        # Conditions lentes → avantage returneur/baseliner
        ret_edge = (style1["return_score"] - style2["return_score"])
        cold_intensity = min(max(rain_mm / 5.0, (15 - temp_c) / 15.0), 1.0)
        rain_adv = ret_edge * cold_intensity * 0.25
        reason = f"Pluie {rain_mm:.1f}mm" if rain_mm >= 0.5 else f"Froid {temp_c:.0f}°C"
        factors.append(("p1" if rain_adv > 0 else "p2", abs(rain_adv),
                        f"{reason} → balle lente, avantage returneur"))

    # ── Chaleur / Humidité ────────────────────────────────────────────────────
    if temp_c >= 28:
        heat_intensity = min((temp_c - 26) / 10.0, 1.0)
        if humidity >= 70:
            heat_intensity *= 1.3
        # Chaleur + humidité → avantage physique (on utilise n_matches comme proxy)
        n1, n2 = style1["n_matches"], style2["n_matches"]
        if n1 > 0 and n2 > 0:
            # Plus de matchs = plus d'expérience de la chaleur (approximation)
            phys_adv = (n1 - n2) / max(n1, n2) * heat_intensity * 0.15
            factors.append(("p1" if phys_adv > 0 else "p2", abs(phys_adv),
                            f"Chaleur {temp_c:.0f}°C → avantage endurance"))

    # ── Synthèse ──────────────────────────────────────────────────────────────
    total_p1 = sum(mag for ben, mag, _ in factors if ben == "p1")
    total_p2 = sum(mag for ben, mag, _ in factors if ben == "p2")
    net = total_p1 - total_p2

    if abs(net) < 0.03:
        beneficiary = "neutre"
        label = "Conditions neutres"
    elif net > 0:
        beneficiary = "p1"
        pct = round(net * 100, 1)
        label = f"+{pct}% condition p1"
    else:
        beneficiary = "p2"
        pct = round(abs(net) * 100, 1)
        label = f"+{pct}% condition p2"

    impact_level = "faible" if abs(net) < 0.05 else ("modéré" if abs(net) < 0.12 else "fort")

    return {
        "beneficiary": beneficiary,
        "label": label,
        "impact_level": impact_level,
        "net_edge": round(net, 3),
        "factors": [{"side": b, "magnitude": round(m, 3), "reason": r}
                    for b, m, r in factors],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée principal
# ──────────────────────────────────────────────────────────────────────────────

def analyze(
    mem: Dict[str, Any],
    player1: str,
    profile1: Dict[str, float],
    player2: str,
    profile2: Dict[str, float],
    weather: Optional[Dict[str, Any]],
    tournament: str = "",
    surface: str = "hard",
) -> Dict[str, Any]:
    """Analyse complète météo + crowd pour un matchup."""
    style1 = player_style(profile1)
    style2 = player_style(profile2)
    surf1 = surface_win_rate(mem, player1)
    surf2 = surface_win_rate(mem, player2)

    # Impact météo
    if weather:
        impact = weather_impact(weather, style1, style2, surface)
    else:
        impact = {"beneficiary": "neutre", "label": "Météo inconnue",
                  "impact_level": "faible", "net_edge": 0.0, "factors": []}

    # Crowd factor
    home1 = _is_home(player1, tournament)
    home2 = _is_home(player2, tournament)
    if home1 and not home2:
        crowd = {"beneficiary": "p1", "label": f"Foule pour {player1.split()[-1]}",
                 "magnitude": 0.05}
    elif home2 and not home1:
        crowd = {"beneficiary": "p2", "label": f"Foule pour {player2.split()[-1]}",
                 "magnitude": 0.05}
    else:
        crowd = {"beneficiary": "neutre", "label": "Foule neutre", "magnitude": 0.0}

    # Honeypot signal : conditions + crowd vont clairement dans 1 sens mais
    # les cotes marchés ne le reflètent pas forcément
    total_condition_edge = impact["net_edge"]
    if crowd["beneficiary"] == "p1":
        total_condition_edge += crowd["magnitude"]
    elif crowd["beneficiary"] == "p2":
        total_condition_edge -= crowd["magnitude"]

    honeypot = None
    if abs(total_condition_edge) >= 0.08:
        beneficiary_name = player1 if total_condition_edge > 0 else player2
        honeypot = {
            "flag": True,
            "beneficiary": "p1" if total_condition_edge > 0 else "p2",
            "player": beneficiary_name,
            "edge_pct": round(abs(total_condition_edge) * 100, 1),
            "note": (f"Conditions + foule en faveur de {beneficiary_name.split()[-1]} "
                     f"(+{round(abs(total_condition_edge)*100,1)}%) — "
                     "à surveiller si les cotes ne le reflètent pas."),
        }

    # Préférence de surface
    surf_adv = None
    s1 = surf1.get(surface)
    s2 = surf2.get(surface)
    if s1 is not None and s2 is not None:
        delta = s1 - s2
        if abs(delta) >= 0.04:
            surf_adv = {
                "beneficiary": "p1" if delta > 0 else "p2",
                "player": player1 if delta > 0 else player2,
                "delta_pct": round(abs(delta) * 100, 1),
                "label": (f"{(player1 if delta>0 else player2).split()[-1]} "
                          f"surperforme sur {surface} "
                          f"(+{round(abs(delta)*100,1)}% vs adversaire moyen)"),
            }

    return {
        "player1": {"name": player1, "style": style1, "surface_wr": surf1},
        "player2": {"name": player2, "style": style2, "surface_wr": surf2},
        "weather_impact": impact,
        "crowd": crowd,
        "surface_advantage": surf_adv,
        "honeypot": honeypot,
        "total_condition_edge": round(total_condition_edge * 100, 1),
    }
