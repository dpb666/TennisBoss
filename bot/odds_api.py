"""Cotes via odds-api.io — pool de clés rotatif (ODDS_API_KEY, ODDS_API_KEY_2..5).

Doc : https://docs.odds-api.io/  — base https://api.odds-api.io/v3
  GET /sports
  GET /events?sport=tennis
  GET /odds?eventId={id}&bookmakers={liste}

Pool de clés : jusqu'à 5 clés (.env ODDS_API_KEY, ODDS_API_KEY_2..5).
Rotation automatique quand une clé atteint RL_SAFETY requêtes restantes.
Chaque clé = 100 req/h → 5 clés = 500 req/h.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .live_api import load_env
from .log import log

BASE = "https://api.odds-api.io/v3"


# IMPORTANT : lecture PARESSEUSE de l'env. Ce module est importé avant que
# load_env() ne charge le .env (ordre d'import dans bot/api.py) — lire au
# chargement retomberait sur le défaut. On lit donc à chaque appel.
def _bookmakers() -> str:
    """Liste de books à comparer (line shopping). Élargissable via ODDS_BOOKMAKERS."""
    return os.environ.get("ODDS_BOOKMAKERS", "Betfair Exchange").strip()


def _sharp_book() -> str:
    """Book sharp (faible vig) servant de proba juste no-vig."""
    return os.environ.get("ODDS_SHARP_BOOK", "Betfair Exchange").strip()

TTL_EVENTS = 900       # 15 min — économise le quota 100 req/h
TTL_ODDS = 600         # 10 min (était 5min — divisé par 2 le nombre de req/h)
TTL_LEAGUES = 3600
RL_SAFETY = 5          # seuil bas -> on passe à la clé suivante

_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()           # évite les race conditions entre threads
_IN_FLIGHT: Dict[str, threading.Event] = {}  # une seule requête par cache key
_RL_WARN_AT: float = 0.0
_RL_WARN_LOCK = threading.Lock()
_RL: Dict[str, Any] = {"remaining": None, "reset": 0.0}  # compat tests / ancien format

# Pool de clés : {key_str -> {remaining, reset}}
_KEY_POOL: Dict[str, Dict[str, Any]] = {}
_KEY_ORDER: List[str] = []   # ordre stable de parcours
_CURRENT_KEY_IDX: int = 0    # index courant dans _KEY_ORDER


def _cache_key(path: str, params: Dict[str, Any]) -> str:
    items = sorted((k, str(v)) for k, v in params.items() if k != "apiKey")
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def _parse_reset(rst: str) -> Optional[float]:
    """x-ratelimit-reset -> epoch (s). Gère 3 formats vus en pratique :
    epoch absolu, nb de secondes restantes, ou timestamp ISO 8601 (doc odds-api)."""
    rst = rst.strip()
    try:
        v = float(rst)
        return v if v > 1e6 else time.time() + v
    except ValueError:
        pass
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(rst.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _load_key_pool() -> None:
    """Charge toutes les clés ODDS_API_KEY[_2..5] depuis l'environnement."""
    global _KEY_ORDER
    load_env()
    keys = []
    for suffix in ("", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9", "_10", "_11", "_12"):
        k = (os.environ.get(f"ODDS_API_KEY{suffix}") or "").strip()
        if k and k not in keys:
            keys.append(k)
    for k in keys:
        if k not in _KEY_POOL:
            _KEY_POOL[k] = {"remaining": None, "reset": 0.0}
    _KEY_ORDER = keys


def _current_key() -> Optional[str]:
    """Round-robin strict : avance d'1 après chaque appel pour répartir uniformément."""
    global _CURRENT_KEY_IDX
    if not _KEY_ORDER:
        _load_key_pool()
    if not _KEY_ORDER:
        return None
    now = time.time()
    n = len(_KEY_ORDER)
    for i in range(n):
        idx = (_CURRENT_KEY_IDX + i) % n
        k = _KEY_ORDER[idx]
        rl = _KEY_POOL[k]
        rem = rl["remaining"]
        # Reset automatique si l'heure de reset est passée
        if rem is not None and rem < RL_SAFETY and rl["reset"] and now >= rl["reset"]:
            rl["remaining"] = None
            rem = None
        if rem is None or rem >= RL_SAFETY:
            # Avance d'1 pour le prochain appel (round-robin)
            _CURRENT_KEY_IDX = (idx + 1) % n
            return k
    # Toutes épuisées — log throttlé 1x/5min (lock pour éviter flood multi-thread)
    global _RL_WARN_AT
    best = min(_KEY_ORDER, key=lambda k: _KEY_POOL[k]["reset"] or 0)
    reset_in = max(0, int((_KEY_POOL[best]["reset"] or 0) - now))
    with _RL_WARN_LOCK:
        if now - _RL_WARN_AT > 300:
            log(f"odds-api: toutes les clés épuisées — reset dans {reset_in}s.", "WARN")
            _RL_WARN_AT = now
    return None


def _explicit_key(key: str) -> str:
    """Force une clé unique fournie par l'appelant (compat ancien _get(... apiKey=))."""
    global _KEY_ORDER, _CURRENT_KEY_IDX
    if key not in _KEY_POOL:
        _KEY_POOL[key] = _RL
    else:
        _KEY_POOL[key] = _RL
    _KEY_ORDER = [key]
    _CURRENT_KEY_IDX = 0
    return key


def _update_rl(resp: requests.Response, key: str) -> None:
    """Lit x-ratelimit-remaining / x-ratelimit-reset pour la clé donnée."""
    rl = _KEY_POOL.get(key)
    if rl is None:
        return
    rem = resp.headers.get("x-ratelimit-remaining")
    if rem is not None:
        try:
            rl["remaining"] = int(rem)
            if _KEY_ORDER and key == _KEY_ORDER[0]:
                _RL["remaining"] = rl["remaining"]
        except ValueError:
            pass
    rst = resp.headers.get("x-ratelimit-reset")
    if rst is not None:
        parsed = _parse_reset(rst)
        if parsed is not None:
            rl["reset"] = parsed
            if _KEY_ORDER and key == _KEY_ORDER[0]:
                _RL["reset"] = parsed


def rate_limit_status() -> Dict[str, Any]:
    """État du pool de clés (pour /api/status / diagnostic)."""
    if not _KEY_ORDER and (_RL["remaining"] is not None or _RL["reset"]):
        reset_in = int(_RL["reset"] - time.time()) if _RL["reset"] else None
        return {
            "remaining": _RL["remaining"],
            "reset_in_s": max(0, reset_in) if reset_in is not None else None,
            "pool": [],
            "total_remaining": _RL["remaining"] or 0,
            "keys_count": 0,
        }
    if not _KEY_ORDER:
        _load_key_pool()
    pool = []
    for k in _KEY_ORDER:
        rl = _KEY_POOL[k]
        reset_in = int(rl["reset"] - time.time()) if rl["reset"] else None
        pool.append({
            "key_suffix": k[-6:],
            "remaining": rl["remaining"],
            "reset_in_s": max(0, reset_in) if reset_in is not None else None,
        })
    total_rem = sum(p["remaining"] or 0 for p in pool)
    # Compat avec l'ancien format (premier champ "remaining")
    first = pool[0] if pool else {}
    return {
        "remaining": first.get("remaining"),
        "reset_in_s": first.get("reset_in_s"),
        "pool": pool,
        "total_remaining": total_rem,
        "keys_count": len(_KEY_ORDER),
    }


def clear_cache() -> None:
    """Vide le cache et reset le pool (utile en tests)."""
    global _CURRENT_KEY_IDX
    _CACHE.clear()
    _RL.update(remaining=None, reset=0.0)
    _KEY_POOL.clear()
    _KEY_ORDER.clear()
    _CURRENT_KEY_IDX = 0


def _get(path: str, params: Dict[str, Any], ttl: float) -> Optional[Any]:
    """GET caché + pool de clés rotatif. Thread-safe : une seule requête par cache key."""
    cache_key_str = _cache_key(path, params)
    now = time.time()

    # Lecture rapide du cache (hors lock pour la perf)
    hit = _CACHE.get(cache_key_str)
    if hit and hit[0] > now:
        return hit[1]

    # Évite les requêtes dupliquées concurrentes sur la même cache key
    with _CACHE_LOCK:
        hit = _CACHE.get(cache_key_str)  # re-check sous lock
        if hit and hit[0] > now:
            return hit[1]
        # Marque la key comme "en vol" si pas déjà le cas
        if cache_key_str in _IN_FLIGHT:
            evt = _IN_FLIGHT[cache_key_str]
        else:
            evt = threading.Event()
            _IN_FLIGHT[cache_key_str] = evt
            evt = None  # ce thread fait la requête

    if evt is not None:
        # Un autre thread est en train de fetcher — on attend son résultat (max 25s)
        evt.wait(timeout=25)
        hit = _CACHE.get(cache_key_str)
        return hit[1] if (hit and hit[0] > now) else None

    # Ce thread est responsable de la requête
    result = None
    try:
        explicit_api_key = str(params.get("apiKey") or "").strip()
        if explicit_api_key:
            _explicit_key(explicit_api_key)
        api_key = _current_key()
        if not api_key:
            result = _CACHE.get(cache_key_str, (None, None))[1]
            return result

        call_params = {**params, "apiKey": api_key}
        # Retry avec backoff exponentiel : 3s → 9s (max 2 essais)
        _last_exc = None
        for _attempt, _wait in enumerate([0, 3, 9]):
            if _wait:
                time.sleep(_wait)
            try:
                r = requests.get(f"{BASE}{path}", params=call_params, timeout=20)
                _last_exc = None
                break
            except requests.RequestException as exc:
                _last_exc = exc
        if _last_exc is not None:
            log(f"odds-api {path} réseau KO après 3 essais ({_last_exc}).", "WARN")
            result = hit[1] if hit else None
            return result

        _update_rl(r, api_key)

        if r.status_code == 429:
            rl = _KEY_POOL[api_key]
            reset_at = rl["reset"] if (rl["reset"] and rl["reset"] > now) else now + 10
            rl["remaining"] = 0
            rl["reset"] = reset_at
            next_key = _current_key()
            if next_key and next_key != api_key:
                log(f"odds-api 429 sur clé ...{api_key[-6:]} — bascule sur ...{next_key[-6:]}.", "WARN")
                call_params["apiKey"] = next_key
                try:
                    r = requests.get(f"{BASE}{path}", params=call_params, timeout=20)
                    _update_rl(r, next_key)
                    api_key = next_key
                except requests.RequestException:
                    result = hit[1] if hit else None
                    return result
            else:
                log(f"odds-api 429 — pool épuisé.", "WARN")
                result = hit[1] if hit else None
                return result

        if r.status_code != 200:
            result = hit[1] if hit else None
            return result
        try:
            payload = r.json()
        except ValueError:
            result = hit[1] if hit else None
            return result

        _CACHE[cache_key_str] = (now + ttl, payload)
        result = payload
        return payload
    finally:
        # Libère l'event pour les threads qui attendaient
        with _CACHE_LOCK:
            ev_done = _IN_FLIGHT.pop(cache_key_str, None)
        if ev_done is not None:
            ev_done.set()


def _key() -> Optional[str]:
    """Compatibilité : retourne la clé active courante du pool."""
    if not _KEY_ORDER:
        _load_key_pool()
    return _KEY_ORDER[0] if _KEY_ORDER else None


def is_enabled() -> bool:
    if not _KEY_ORDER:
        _load_key_pool()
    return bool(_KEY_ORDER)


def fetch_tennis_events(upcoming_only: bool = True) -> List[Dict[str, Any]]:
    """Liste des événements tennis (id, home, away, date, league, status).

    v3 update: /events renvoie les 14 prochains jours par défaut (jusqu'à 5000 events).
    Le pool de clés est utilisé automatiquement via _get().
    """
    if not is_enabled():
        return []
    events = _get("/events", {"sport": "tennis"}, ttl=TTL_EVENTS)
    if not isinstance(events, list):
        return []
    if upcoming_only:
        events = [e for e in events
                  if e.get("status") in ("pending", "live", "inplay", "not_started")]
    return events


def fetch_live_events() -> List[Dict[str, Any]]:
    """Matchs tennis EN COURS avec score + jeu courant + serve.

    TTL 30s pour rester à jour durant le match.
    Structure retournée par odds-api.io :
      scores.home/away          = sets gagnés
      scores.periods.p1/p2...  = jeux par set (ex: {"home":6,"away":3})
      scores.periods.currentgame = score du jeu en cours (0/15/30/40/A)
      clock.serve               = "home" | "away"
      clock.statusDetail        = "1st set" | "2nd set" | ...
      clock.minute              = durée en minutes
    """
    if not is_enabled():
        return []
    events = _get("/events", {"sport": "tennis", "status": "live"}, ttl=60)
    if not isinstance(events, list):
        return []
    return [e for e in events if e.get("status") in ("live", "inplay")]


def fetch_settled_events() -> List[Dict[str, Any]]:
    """Résultats terminés des dernières 24h."""
    if not is_enabled():
        return []
    events = _get("/events", {"sport": "tennis", "status": "settled"}, ttl=300)
    if not isinstance(events, list):
        return []
    return events


def build_event_index(events: List[Dict[str, Any]]) -> Dict[frozenset, Dict[str, Any]]:
    """Index { {nom_famille_1, nom_famille_2} -> event } pour apparier 2 fournisseurs."""
    from .namematch import split_name

    idx: Dict[frozenset, Dict[str, Any]] = {}
    for e in events:
        _, l1 = split_name(e.get("home", ""))
        _, l2 = split_name(e.get("away", ""))
        if l1 and l2 and l1 != l2:
            idx[frozenset((l1, l2))] = e
    return idx


def find_event(index: Dict[frozenset, Dict[str, Any]],
               name1: str, name2: str) -> Optional[Dict[str, Any]]:
    """Retrouve l'événement odds-api.io pour deux joueurs (par noms de famille)."""
    from .namematch import split_name

    _, l1 = split_name(name1)
    _, l2 = split_name(name2)
    if not l1 or not l2:
        return None
    return index.get(frozenset((l1, l2)))


def build_time_index(events: List[Dict[str, Any]]) -> Dict[frozenset, str]:
    """Index { {nom_famille_1, nom_famille_2} -> "HH:MM" } depuis les events odds-api.

    Utilisé pour enrichir les fixtures ESPN quand l'heure est 00:00 (inconnue).
    Les heures sont converties de UTC en heure locale de Toronto (EDT = UTC-4).
    """
    import datetime as _dt
    from .namematch import split_name

    idx: Dict[frozenset, str] = {}
    for e in events:
        raw = e.get("date", "")
        if not raw or raw.endswith("T00:00:00Z"):
            continue  # heure inconnue, on ne peut pas enrichir
        try:
            dt = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            tz_toronto = _dt.timezone(_dt.timedelta(hours=-4))  # EDT
            dt = dt.astimezone(tz_toronto)
            t = dt.strftime("%H:%M")
        except Exception:
            continue
        _, l1 = split_name(e.get("home", ""))
        _, l2 = split_name(e.get("away", ""))
        if l1 and l2 and l1 != l2:
            idx[frozenset((l1, l2))] = t
    return idx


def fetch_match_winner(event_id: Any,
                       bookmakers: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Cotes "ML" (vainqueur de match) -> probabilités implicites SANS vig.

    Renvoie {home_prob, away_prob, home_odds, away_odds, books} ou None.
    """
    if not is_enabled():
        return None
    if bookmakers is None:
        bookmakers = _bookmakers()
    sharp = _sharp_book()
    data = _get("/odds", {"eventId": event_id, "bookmakers": bookmakers},
                ttl=TTL_ODDS)
    if not isinstance(data, dict):
        return None

    books = data.get("bookmakers") or {}
    # Par book : meilleure cote home/away qu'il propose (s'il y a plusieurs lignes).
    per_book: Dict[str, tuple] = {}
    for bname, markets in books.items():
        if not isinstance(markets, list):
            continue
        for mk in markets:
            if (mk.get("name") or "").upper() != "ML":
                continue
            for line in mk.get("odds", []):
                try:
                    ho, ao = float(line["home"]), float(line["away"])
                except (KeyError, ValueError, TypeError):
                    continue
                if ho > 1 and ao > 1:
                    ph, pa = per_book.get(bname, (0.0, 0.0))
                    per_book[bname] = (max(ph, ho), max(pa, ao))
    if not per_book:
        return None

    # 1) Cote d'EXÉCUTION = meilleur prix dispo (line shopping). On parie au
    #    book qui paie le plus pour le côté choisi → bat la moyenne/clôture.
    best_h_book, best_h = max(((b, o[0]) for b, o in per_book.items()),
                              key=lambda x: x[1])
    best_a_book, best_a = max(((b, o[1]) for b, o in per_book.items()),
                              key=lambda x: x[1])

    # 2) Proba JUSTE (no-vig) = book sharp si présent, sinon consensus (moyenne).
    if sharp in per_book:
        ref_h, ref_a = per_book[sharp]
    else:
        ref_h = sum(o[0] for o in per_book.values()) / len(per_book)
        ref_a = sum(o[1] for o in per_book.values()) / len(per_book)
    inv_h, inv_a = 1.0 / ref_h, 1.0 / ref_a
    total = inv_h + inv_a
    return {
        "home_prob": round(inv_h / total, 4),
        "away_prob": round(inv_a / total, 4),
        "home_odds": round(best_h, 2),   # meilleur prix (exécution)
        "away_odds": round(best_a, 2),
        "home_book": best_h_book,
        "away_book": best_a_book,
        "fair_source": sharp if sharp in per_book else "consensus",
        "books": sorted(per_book.keys()),
    }


def fetch_live_game_markets(event_id: Any,
                            bookmakers: Optional[str] = None) -> Dict[str, Any]:
    """Récupère Spread(Games) et Totals(Games) Betfair Exchange pour un event live.

    Renvoie :
      spread  : liste de {hdp, home_odds, away_odds, implied_home_prob}
      totals  : liste de {hdp, over_odds, under_odds, implied_over_prob}
      best_spread_hdp  : ligne la plus liquide (abs(over-under) minimal)
      best_totals_hdp  : idem
    """
    if not is_enabled():
        return {}
    # Betfair Exchange : toujours autorisé sur tous les plans odds-api.io
    bks = bookmakers or "Betfair Exchange"
    data = _get("/odds", {"eventId": event_id, "bookmakers": bks}, ttl=60)
    if not isinstance(data, dict):
        return {}

    books = data.get("bookmakers") or {}
    spread_lines: list = []
    totals_lines: list = []

    for bname, markets in books.items():
        if not isinstance(markets, list):
            continue
        for mk in markets:
            mname = (mk.get("name") or "").strip()
            for line in mk.get("odds", []):
                try:
                    hdp = float(line.get("hdp", 0))
                except (TypeError, ValueError):
                    continue
                if mname == "Spread (Games)":
                    try:
                        ho = float(line["home"])
                        ao = float(line["away"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if ho > 1 and ao > 1:
                        impl = round(1 / ho / (1 / ho + 1 / ao), 4)
                        spread_lines.append({"hdp": hdp, "home_odds": round(ho, 2),
                                             "away_odds": round(ao, 2),
                                             "implied_home_prob": impl})
                elif mname == "Totals (Games)":
                    try:
                        ov = float(line["over"])
                        un = float(line["under"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if ov > 1 and un > 1:
                        impl = round(1 / ov / (1 / ov + 1 / un), 4)
                        totals_lines.append({"hdp": hdp, "over_odds": round(ov, 2),
                                             "under_odds": round(un, 2),
                                             "implied_over_prob": impl})

    # Ligne la plus balanced (cotes proches de 2.0 → marché le plus efficace)
    def _most_balanced_spread(lines):
        return min(lines, key=lambda l: abs(l["home_odds"] - l["away_odds"]),
                   default=None)

    def _most_balanced_totals(lines):
        return min(lines, key=lambda l: abs(l["over_odds"] - l["under_odds"]),
                   default=None)

    best_spread = _most_balanced_spread(spread_lines)
    best_totals = _most_balanced_totals(totals_lines)

    return {
        "spread": spread_lines,
        "totals": totals_lines,
        "best_spread": best_spread,
        "best_totals": best_totals,
    }
