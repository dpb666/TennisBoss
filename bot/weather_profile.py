"""Profil conditions de jeu : style joueur × météo × surface × foule.

Tout repose sur les données DÉJÀ en mémoire (pas d'API supplémentaire) :
  - Profil joueur (serve, return1, return2, n) → style de jeu
  - Win rate par surface → préférence terrain
  - Conditions météo (temp, vent, pluie, humidité) → impact physique

Physique du tennis par surface :
  Herbe  : balle rapide et basse → vent + humidité amplifient l'avantage serveur
  Terre  : balle lente + rebond haut → pluie/humidité double l'avantage baseliner
  Dur    : neutre, chaleur accélère la balle → favorise les frappes plates
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Tournois couverts (météo sans effet)
# ──────────────────────────────────────────────────────────────────────────────
_INDOOR_PATTERNS = [
    "o2 arena", "o2 london", "indoor", "covered", "bercy", "stuttgart indoor",
    "rotterdam", "sofia", "vienna", "st. petersburg", "metz", "marseille",
    "lyon indoor", "glasgow", "dallas", "cleveland indoor", "nitto", "finals",
]

def _is_indoor(tournament: str) -> bool:
    tn = tournament.lower()
    return any(p in tn for p in _INDOOR_PATTERNS)


# ──────────────────────────────────────────────────────────────────────────────
# Prestige du tournoi → magnitude crowd
# ──────────────────────────────────────────────────────────────────────────────
_SLAM_PATTERNS    = ["grand slam", "australian open", "french open", "roland", "wimbledon", "us open", "flushing"]
_M1000_PATTERNS   = ["masters 1000", "indian wells", "miami", "madrid", "rome", "montreal", "canada",
                     "cincinnati", "shanghai", "paris masters", "rolex"]
_W1000_PATTERNS   = ["wta 1000"]
_500_PATTERNS     = ["500", "halle", "queens", "eastbourne", "dubai", "doha", "barcelona",
                     "hamburg", "washington", "tokyo", "beijing", "wuhan", "guangzhou",
                     "ostrava", "guadalajara", "abu dhabi"]

def _crowd_magnitude(tournament: str) -> float:
    tn = tournament.lower()
    if any(p in tn for p in _SLAM_PATTERNS):
        return 0.08
    if any(p in tn for p in _M1000_PATTERNS + _W1000_PATTERNS):
        return 0.06
    if any(p in tn for p in _500_PATTERNS):
        return 0.05
    return 0.04


# ──────────────────────────────────────────────────────────────────────────────
# Joueurs "à domicile" par tournoi
# ──────────────────────────────────────────────────────────────────────────────
_HOME_PATTERNS: list[tuple[str, list[str]]] = [
    ("roland|french open|paris|open de france",
     ["gasquet", "moutet", "rinderknech", "mannarino", "monfils", "humbert",
      "chardy", "simon", "mahut", "cornet", "garcia", "dodin", "parry",
      "rune", "tsitsipas", "marozsan"]),
    ("wimbledon|queens|eastbourne",
     ["murray", "evans", "draper", "norrie", "edmund", "skupski",
      "watson", "raducanu", "boulter", "broady", "dart"]),
    ("us open|flushing|washington|atlanta|cincinnati",
     ["tiafoe", "fritz", "paul", "isner", "sock", "querrey", "opelka",
      "nakashima", "kovacevic", "korda", "harris", "keys", "gauff",
      "pegula", "collins", "navarro"]),
    ("australian|melbourne|sydney|brisbane|adelaide",
     ["kyrgios", "de minaur", "kokkinakis", "thompson", "popyrin",
      "hijikata", "duckworth", "tomljanovic", "stosur", "barty"]),
    ("madrid|barcelona|valencia",
     ["alcaraz", "davidovich", "carballes", "zapata", "munar",
      "badosa", "sorribes", "martinez", "bolsova"]),
    ("rome|foro italico|internazionali",
     ["sinner", "musetti", "sonego", "fognini", "berrettini",
      "cobolli", "darderi", "arnaldi", "trevisan", "paolini", "bronzetti"]),
    ("canada|montreal|toronto",
     ["auger-aliassime", "shapovalov", "andreescu", "fernandez",
      "diallo", "tabilo"]),
    ("mallorca|barcelona|marbella",
     ["alcaraz", "davidovich", "munar", "carballes"]),
]


def _is_home(player_name: str, tournament: str) -> bool:
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
# Style de jeu
# ──────────────────────────────────────────────────────────────────────────────

def player_style(profile: Dict[str, float]) -> Dict[str, Any]:
    serve  = float(profile.get("serve", 0.5))
    ret1   = float(profile.get("return1", 0.5))
    ret2   = float(profile.get("return2", 0.5))
    avg_return = (ret1 + ret2) / 2.0
    n = int(profile.get("n", 0))

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
# Win rate par surface
# ──────────────────────────────────────────────────────────────────────────────

def surface_win_rate(mem: Dict[str, Any], player: str) -> Dict[str, Optional[float]]:
    elo_surf = mem.get("elo_surface") or {}
    result: Dict[str, Optional[float]] = {}
    for surf in ("hard", "clay", "grass"):
        surf_r = (elo_surf.get(surf) or {}).get(player)
        if surf_r is not None:
            delta = surf_r - 1500.0          # vs joueur moyen
            approx = 0.5 + delta / 700.0
            result[surf] = round(max(0.3, min(0.8, approx)), 2)
        else:
            result[surf] = None
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Impact météo — physique du jeu par surface
# ──────────────────────────────────────────────────────────────────────────────

def weather_impact(
    weather: Dict[str, Any],
    style1: Dict[str, Any],
    style2: Dict[str, Any],
    surface: str = "hard",
) -> Dict[str, Any]:
    """Impact météo avec physique surface-spécifique.

    Herbe  : balle basse rapide
      • Vent ≥ 10mph → avantage serveur (seuil plus bas qu'hard)
      • Humidité ≥ 70% → herbe mouillée = balle encore plus basse → serveur ++
      • Pluie → balle lourde lente → returner légèrement + (inverse de l'herbe sèche)

    Terre  : rebond haut, balle lente
      • Pluie ≥ 0.5mm → clay détrempé, balle mort → returner ×2 plus avantagé
      • Humidité ≥ 75% → conditions très lentes
      • Vent ≥ 12mph → chaos rebonds → serveur

    Dur    : neutre
      • Pluie/froid → balle lente → returner
      • Chaleur ≥ 28°C → balle plus vite → serveur ou all-court flat hitter
      • Humidité ≥ 80% → légèrement plus lent
    """
    wind_mph  = float(weather.get("wind_mph") or 0)
    rain_mm   = float(weather.get("rain_mm") or 0)
    temp_c    = float(weather.get("temp_c") or 20)
    humidity  = float(weather.get("humidity_pct") or 50)

    factors: list[tuple[str, float, str]] = []

    edge1 = style1["serve_edge"]
    edge2 = style2["serve_edge"]
    ret1  = style1["return_score"]
    ret2  = style2["return_score"]
    n1, n2 = style1["n_matches"], style2["n_matches"]

    # ── HERBE ────────────────────────────────────────────────────────────────
    if surface == "grass":
        # Vent : seuil plus bas sur herbe (10mph vs 12mph sur hard)
        if wind_mph >= 10:
            intensity = min((wind_mph - 8) / 18.0, 1.0)
            wind_adv = (edge1 - edge2) * intensity * 0.35
            factors.append(("p1" if wind_adv > 0 else "p2", abs(wind_adv),
                            f"Vent {wind_mph:.0f}mph · herbe → serveur dominant"))

        # Humidité : herbe humide = balle encore plus basse → serveur ++
        if humidity >= 70 and rain_mm < 1.0:
            hum_i = min((humidity - 65) / 35.0, 1.0)
            hum_adv = (edge1 - edge2) * hum_i * 0.20
            factors.append(("p1" if hum_adv > 0 else "p2", abs(hum_adv),
                            f"Herbe humide ({humidity:.0f}%) → balle basse, serveur avantagé"))

        # Pluie sur herbe : balle lourde → returner (inverse herbe sèche)
        if rain_mm >= 0.5:
            rain_i = min(rain_mm / 4.0, 1.0)
            rain_adv = (ret1 - ret2) * rain_i * 0.20
            factors.append(("p1" if rain_adv > 0 else "p2", abs(rain_adv),
                            f"Pluie {rain_mm:.1f}mm · herbe lourde → returner"))

        # Froid sur herbe : balle skid, effet rapide → serveur
        if temp_c < 15:
            cold_i = min((18 - temp_c) / 15.0, 1.0)
            cold_adv = (edge1 - edge2) * cold_i * 0.15
            factors.append(("p1" if cold_adv > 0 else "p2", abs(cold_adv),
                            f"Froid {temp_c:.0f}°C · herbe → balle rase"))

    # ── TERRE BATTUE ─────────────────────────────────────────────────────────
    elif surface == "clay":
        # Pluie sur clay : ×2 plus lent qu'hard, returner très avantagé
        if rain_mm >= 0.5:
            rain_i = min(rain_mm / 3.0, 1.0)
            rain_adv = (ret1 - ret2) * rain_i * 0.40
            factors.append(("p1" if rain_adv > 0 else "p2", abs(rain_adv),
                            f"Pluie {rain_mm:.1f}mm · terre détrempée → returner très avantagé"))

        # Humidité élevée sur clay : balle plus lente + rebond haut
        if humidity >= 75 and rain_mm < 0.5:
            hum_i = min((humidity - 70) / 30.0, 1.0)
            hum_adv = (ret1 - ret2) * hum_i * 0.22
            factors.append(("p1" if hum_adv > 0 else "p2", abs(hum_adv),
                            f"Humidité {humidity:.0f}% · clay → balle lente, returner"))

        # Vent sur clay : rebonds imprévisibles → avantage serveur puissant
        if wind_mph >= 12:
            intensity = min((wind_mph - 10) / 20.0, 1.0)
            wind_adv = (edge1 - edge2) * intensity * 0.28
            factors.append(("p1" if wind_adv > 0 else "p2", abs(wind_adv),
                            f"Vent {wind_mph:.0f}mph · clay imprévisible → serveur"))

        # Chaleur sur clay : échanges longs → endurance
        if temp_c >= 28:
            heat_i = min((temp_c - 26) / 12.0, 1.0) * (1.2 if humidity >= 70 else 1.0)
            if n1 > 0 and n2 > 0:
                phys_adv = (n1 - n2) / max(n1, n2) * heat_i * 0.18
                factors.append(("p1" if phys_adv > 0 else "p2", abs(phys_adv),
                                f"Chaleur {temp_c:.0f}°C · clay → endurance décisive"))

    # ── DUR (et défaut) ───────────────────────────────────────────────────────
    else:
        # Vent standard
        if wind_mph >= 12:
            intensity = min((wind_mph - 10) / 20.0, 1.0)
            wind_adv = (edge1 - edge2) * intensity * 0.30
            factors.append(("p1" if wind_adv > 0 else "p2", abs(wind_adv),
                            f"Vent {wind_mph:.0f}mph → avantage serveur"))

        # Pluie / froid : balle lente
        if rain_mm >= 0.5 or (temp_c < 12):
            cold_i = min(max(rain_mm / 5.0, (15 - temp_c) / 15.0, 0), 1.0)
            rain_adv = (ret1 - ret2) * cold_i * 0.25
            reason = f"Pluie {rain_mm:.1f}mm" if rain_mm >= 0.5 else f"Froid {temp_c:.0f}°C"
            factors.append(("p1" if rain_adv > 0 else "p2", abs(rain_adv),
                            f"{reason} → balle lente, returner"))

        # Humidité sans pluie sur dur : légèrement plus lent
        if humidity >= 80 and rain_mm < 0.5:
            hum_i = min((humidity - 75) / 25.0, 1.0)
            hum_adv = (ret1 - ret2) * hum_i * 0.10
            factors.append(("p1" if hum_adv > 0 else "p2", abs(hum_adv),
                            f"Humidité {humidity:.0f}% → conditions légèrement lentes"))

        # Chaleur : balle plus rapide, flat hitter avantagé
        if temp_c >= 28:
            heat_i = min((temp_c - 26) / 10.0, 1.0) * (1.3 if humidity >= 70 else 1.0)
            if n1 > 0 and n2 > 0:
                phys_adv = (n1 - n2) / max(n1, n2) * heat_i * 0.15
                factors.append(("p1" if phys_adv > 0 else "p2", abs(phys_adv),
                                f"Chaleur {temp_c:.0f}°C → endurance"))

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
        label = f"+{pct}% → {style1['style_label']}"
    else:
        beneficiary = "p2"
        pct = round(abs(net) * 100, 1)
        label = f"+{pct}% → {style2['style_label']}"

    impact_level = (
        "faible"  if abs(net) < 0.05 else
        "modéré"  if abs(net) < 0.12 else
        "fort"
    )

    return {
        "beneficiary": beneficiary,
        "label": label,
        "impact_level": impact_level,
        "net_edge": round(net, 3),
        "factors": [{"side": b, "magnitude": round(m, 3), "reason": r}
                    for b, m, r in factors],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Résumé naturel des conditions
# ──────────────────────────────────────────────────────────────────────────────

def _conditions_summary(
    weather: Optional[Dict[str, Any]],
    surface: str,
    impact: Dict[str, Any],
    surf_adv: Optional[Dict],
    crowd: Dict[str, Any],
    is_indoor: bool,
) -> str:
    if is_indoor:
        return "Match en salle — météo sans effet."
    if not weather:
        return "Données météo indisponibles."

    wind_mph  = float(weather.get("wind_mph") or 0)
    rain_mm   = float(weather.get("rain_mm") or 0)
    temp_c    = float(weather.get("temp_c") or 20)
    humidity  = float(weather.get("humidity_pct") or 50)

    parts = []

    # Conditions principales
    if rain_mm >= 0.5:
        parts.append(f"Pluie {rain_mm:.1f}mm")
    elif humidity >= 80:
        parts.append(f"Très humide ({humidity:.0f}%)")
    elif humidity >= 70:
        parts.append(f"Humide ({humidity:.0f}%)")

    if temp_c >= 30:
        parts.append(f"Forte chaleur {temp_c:.0f}°C")
    elif temp_c >= 28:
        parts.append(f"Chaud {temp_c:.0f}°C")
    elif temp_c < 12:
        parts.append(f"Froid {temp_c:.0f}°C")
    else:
        parts.append(f"{temp_c:.0f}°C")

    if wind_mph >= 15:
        parts.append(f"Vent fort {wind_mph:.0f}mph")
    elif wind_mph >= 10:
        parts.append(f"Vent {wind_mph:.0f}mph")

    # Surface
    surf_label = {"grass": "herbe", "clay": "terre", "hard": "dur"}.get(surface, surface)
    base = f"{surf_label.capitalize()} · " + " · ".join(parts) if parts else surf_label.capitalize()

    # Verdict impact
    if impact["beneficiary"] != "neutre":
        base += f" → {impact['label']}"
    else:
        base += " — conditions neutres"

    if crowd["beneficiary"] != "neutre":
        base += f" · {crowd['label']}"

    return base


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
    style1 = player_style(profile1)
    style2 = player_style(profile2)
    surf1  = surface_win_rate(mem, player1)
    surf2  = surface_win_rate(mem, player2)

    indoor = _is_indoor(tournament)

    # Impact météo (neutre si indoor)
    if weather and not indoor:
        impact = weather_impact(weather, style1, style2, surface)
    else:
        impact = {
            "beneficiary": "neutre",
            "label": "Match en salle — météo sans effet" if indoor else "Météo inconnue",
            "impact_level": "faible", "net_edge": 0.0, "factors": [],
        }

    # Crowd
    crowd_mag = _crowd_magnitude(tournament)
    home1 = _is_home(player1, tournament)
    home2 = _is_home(player2, tournament)
    if home1 and not home2:
        crowd = {"beneficiary": "p1",
                 "label": f"Foule pour {player1.split()[-1]} ({int(crowd_mag*100)}%)",
                 "magnitude": crowd_mag}
    elif home2 and not home1:
        crowd = {"beneficiary": "p2",
                 "label": f"Foule pour {player2.split()[-1]} ({int(crowd_mag*100)}%)",
                 "magnitude": crowd_mag}
    else:
        crowd = {"beneficiary": "neutre", "label": "Foule neutre", "magnitude": 0.0}

    # Edge total conditions
    total_edge = impact["net_edge"]
    if crowd["beneficiary"] == "p1":
        total_edge += crowd["magnitude"]
    elif crowd["beneficiary"] == "p2":
        total_edge -= crowd["magnitude"]

    # Préférence surface
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
                "label": (
                    f"{(player1 if delta>0 else player2).split()[-1]} "
                    f"surperforme sur {surface} "
                    f"(+{round(abs(delta)*100,1)}% vs adversaire moyen)"
                ),
            }

    # Intégrer avantage surface dans l'edge total (poids plus faible — historique)
    if surf_adv:
        surf_contrib = surf_adv["delta_pct"] / 100.0 * 0.5
        if surf_adv["beneficiary"] == "p1":
            total_edge += surf_contrib
        else:
            total_edge -= surf_contrib

    # Honeypot
    honeypot = None
    if abs(total_edge) >= 0.08:
        bname = player1 if total_edge > 0 else player2
        honeypot = {
            "flag": True,
            "beneficiary": "p1" if total_edge > 0 else "p2",
            "player": bname,
            "edge_pct": round(abs(total_edge) * 100, 1),
            "note": (
                f"Conditions + surface + foule en faveur de {bname.split()[-1]} "
                f"(+{round(abs(total_edge)*100,1)}%) — "
                "à surveiller si les cotes ne le reflètent pas."
            ),
        }

    summary = _conditions_summary(weather, surface, impact, surf_adv, crowd, indoor)

    def _flat_player(name: str, style: Dict, wr: Dict) -> Dict:
        return {
            "name": name,
            "style_label": style["style_label"],
            "serve_score": style["serve_score"],
            "return_score": style["return_score"],
            "serve_edge": style["serve_edge"],
            "n_matches": style["n_matches"],
            "surface_wr": wr,
        }

    return {
        "player1": _flat_player(player1, style1, surf1),
        "player2": _flat_player(player2, style2, surf2),
        "weather_impact": impact,
        "crowd": crowd,
        "surface_advantage": surf_adv,
        "honeypot": honeypot,
        "total_condition_edge": round(total_edge * 100, 1),
        "summary": summary,
        "is_indoor": indoor,
    }
