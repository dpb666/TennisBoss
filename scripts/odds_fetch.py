"""Fetch tennis odds from odds-api.io v3 — hybrid coverage.

Sources (par ordre de priorité) :
  1. odds-api.io v3  (MelBet / Betfair Exchange — plan gratuit)
  2. TennisBoss model (ELO + features → probas synthétiques) si aucun bookmaker ne couvre le match

Usage:
    python3 scripts/odds_fetch.py
    python3 scripts/odds_fetch.py --limit 5
    python3 scripts/odds_fetch.py --event-id 12695429680
    python3 scripts/odds_fetch.py --bookmakers "MelBet,Betfair Exchange" --limit 10
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.odds-api.io/v3"
DEFAULT_BOOKMAKERS = "Bet365,Betfair Exchange"  # free plan allowlist

# ---------------------------------------------------------------------------
# TennisBoss model — hybrid fallback
# ---------------------------------------------------------------------------

def _load_model() -> Optional[Dict]:
    """Charge le moteur TennisBoss local. Retourne _MEM ou None si indisponible."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from bot import db, memory as mem_mod, elo
        db.init()
        mem = mem_mod.load()
        rows = db.all_matches_chrono()
        mem["elo"], _ = elo.build_dynamic(rows)
        return mem
    except Exception as exc:
        print(f"[MODEL] Indisponible ({exc}) — mode bookmakers uniquement.")
        return None


def _resolve_players(mem: Dict, home: str, away: str,
                     league: str = "") -> Tuple[Optional[str], Optional[str]]:
    """Résout les noms via namematch (même logique que le backend principal)."""
    try:
        from bot import namematch
        players = mem.get("players") or {}
        counts = {n: int(p.get("n", 0)) for n, p in players.items()}
        idx = namematch.build_index(list(players.keys()), counts)
        return namematch.resolve(home, idx), namematch.resolve(away, idx)
    except Exception as exc:
        print(f"[RESOLVER] Erreur : {exc}")
        return None, None


def _model_predict(mem: Dict, name1: str, name2: str) -> Optional[Dict]:
    """Prédit les probas match via ELO + features. Retourne None si joueurs inconnus."""
    try:
        from bot import predictor, features, namematch
        players = mem.get("players") or {}
        counts  = {n: int(p.get("n", 0)) for n, p in players.items()}
        idx     = namematch.build_index(list(players.keys()), counts)
        n1 = namematch.resolve(name1, idx)
        n2 = namematch.resolve(name2, idx)
        if not n1 or not n2:
            return None
        f1 = features.feature_vector(features.get_profile(mem, n1))
        f2 = features.feature_vector(features.get_profile(mem, n2))
        r  = predictor.predict(mem, n1, f1, n2, f2)
        pm1 = predictor.set_to_match_prob(r["prob1"] / 100.0)
        pm2 = 1.0 - pm1
        elo_vals = mem.get("elo") or {}
        return {
            "player1": n1, "player2": n2,
            "prob1": round(pm1, 4), "prob2": round(pm2, 4),
            "elo1": round(elo_vals.get(n1, 1500), 0),
            "elo2": round(elo_vals.get(n2, 1500), 0),
            "fair_odds1": round(1 / pm1, 2) if pm1 > 0 else None,
            "fair_odds2": round(1 / pm2, 2) if pm2 > 0 else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get(path: str, params: Dict[str, Any], api_key: str) -> Any:
    """GET with basic error handling. Returns parsed JSON or raises."""
    params["apiKey"] = api_key
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=20)
    except requests.ConnectionError as exc:
        sys.exit(f"[ERROR] Connexion impossible : {exc}")
    except requests.Timeout:
        sys.exit("[ERROR] Timeout — odds-api.io ne répond pas.")

    remaining = r.headers.get("x-ratelimit-remaining", "?")
    reset     = r.headers.get("x-ratelimit-reset", "?")
    print(f"[RL] {path} → HTTP {r.status_code} | quota restant: {remaining} | reset: {reset}")

    if r.status_code == 401:
        sys.exit("[ERROR] Clé API invalide (401).")
    if r.status_code == 403:
        sys.exit("[ERROR] Accès refusé (403) — vérifier le plan ou les bookmakers autorisés.")
    if r.status_code == 429:
        sys.exit("[ERROR] Rate limit atteint (429). Attendre le reset.")
    if r.status_code != 200:
        sys.exit(f"[ERROR] HTTP {r.status_code} : {r.text[:200]}")

    try:
        return r.json()
    except ValueError:
        sys.exit(f"[ERROR] Réponse non-JSON : {r.text[:200]}")


# ---------------------------------------------------------------------------
# Step 1 — list events
# ---------------------------------------------------------------------------

def fetch_events(api_key: str, status: str = "pending,live") -> List[Dict]:
    """GET /events?sport=tennis — retourne les matchs en cours / à venir."""
    data = get("/events", {"sport": "tennis", "status": status}, api_key)
    if not isinstance(data, list):
        sys.exit(f"[ERROR] Format inattendu pour /events : {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Step 2 — pick an event
# ---------------------------------------------------------------------------

def pick_event(events: List[Dict]) -> Optional[Dict]:
    """Retourne le premier match live, sinon le premier pending."""
    live    = [e for e in events if e.get("status") in ("live", "inplay")]
    pending = [e for e in events if e.get("status") in ("pending", "not_started")]
    return (live or pending or [None])[0]


# ---------------------------------------------------------------------------
# Step 3 — fetch odds
# ---------------------------------------------------------------------------

def fetch_odds(event_id: Any, bookmakers: str, api_key: str) -> Dict:
    """GET /odds?eventId=...&bookmakers=... — retourne les cotes du match."""
    data = get("/odds", {"eventId": event_id, "bookmakers": bookmakers}, api_key)
    if not isinstance(data, dict):
        sys.exit(f"[ERROR] Format inattendu pour /odds : {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_line(name: str, line: Dict, home: str, away: str) -> None:
    """Format one odds line — handles ML/Spread (home/away) and Totals (over/under)."""
    try:
        # ── ML / Spread : home vs away ────────────────────────────────────
        if "home" in line and "away" in line:
            ho = float(line["home"])
            ao = float(line["away"])
            inv_h, inv_a = 1 / ho, 1 / ao
            total = inv_h + inv_a
            prob_h = inv_h / total * 100
            prob_a = inv_a / total * 100
            hdp = line.get("hdp")
            hdp_str = f" ({hdp:+g})" if hdp is not None else ""
            print(f"     [{name}{hdp_str}]  {home}: {ho:.2f} ({prob_h:.1f}%)"
                  f"  |  {away}: {ao:.2f} ({prob_a:.1f}%)")

        # ── Totals : over / under ─────────────────────────────────────────
        elif "over" in line or "under" in line:
            hdp   = line.get("hdp", "?")
            over  = line.get("over",  "N/A")
            under = line.get("under", "N/A")
            try:
                ov = float(over)
                un = float(under)
                inv_o, inv_u = 1 / ov, 1 / un
                t = inv_o + inv_u
                po = inv_o / t * 100
                pu = inv_u / t * 100
                print(f"     [{name} {hdp}]  Over: {ov:.2f} ({po:.1f}%)"
                      f"  |  Under: {un:.2f} ({pu:.1f}%)")
            except (ValueError, ZeroDivisionError):
                print(f"     [{name} {hdp}]  Over: {over}  |  Under: {under}")

        else:
            print(f"     [{name}]  {line}")

    except (KeyError, ValueError, ZeroDivisionError):
        print(f"     [{name}]  parse error : {line}")


def print_event(e: Dict) -> None:
    print(f"\n{'─'*55}")
    print(f"  Match   : {e['home']}  vs  {e['away']}")
    print(f"  ID      : {e['id']}")
    print(f"  Statut  : {e.get('status','?')}")
    print(f"  Date    : {e.get('date','?')}")
    print(f"  Ligue   : {e.get('league', {}).get('name','?')}")
    print(f"{'─'*55}")


def print_odds(odds_data: Dict) -> bool:
    home  = odds_data.get("home", "?")
    away  = odds_data.get("away", "?")
    books = odds_data.get("bookmakers") or {}

    if not books:
        return False  # signal: no market coverage

    print(f"\n{'─'*55}")
    print(f"  Cotes pour : {home}  vs  {away}")
    print(f"{'─'*55}")

    for bname, markets in books.items():
        print(f"\n  📚 {bname}")
        if not isinstance(markets, list):
            print("     (format inconnu)")
            continue
        for mk in markets:
            name = mk.get("name", "?")
            for line in mk.get("odds", []):
                _print_line(name, line, home, away)

    print(f"{'─'*55}\n")
    return True  # market coverage found


def print_model_fallback(pred: Dict) -> None:
    """Affiche les probas synthétiques du modèle avec source + confiance."""
    p1, p2 = pred["player1"], pred["player2"]
    c1 = pred.get("conf1", 1.0)
    c2 = pred.get("conf2", 1.0)
    s1 = pred.get("src1", "local_db")
    s2 = pred.get("src2", "local_db")

    def _tag(conf: float, src: str) -> str:
        if conf >= 0.85: return "✅ DB"
        if conf >= 0.65: return f"🔍 {src.split('_')[0]}"
        if conf >= 0.30: return f"🌐 {src.split('_')[0]}"
        return "⚠️  inféré"

    print(f"\n{'─'*55}")
    print(f"  [HYBRIDE]  {p1}  vs  {p2}")
    print(f"{'─'*55}")
    print(f"  Résolution : {_tag(c1,s1)} ({c1:.0%})  |  {_tag(c2,s2)} ({c2:.0%})")
    print(f"  ELO        : {p1} {pred['elo1']:.0f}  |  {p2} {pred['elo2']:.0f}")
    print(f"  Prob ML    : {p1} {pred['prob1']*100:.1f}%  |  {p2} {pred['prob2']*100:.1f}%")
    print(f"  Cote fair  : {p1} {pred['fair_odds1']}  |  {p2} {pred['fair_odds2']}")
    print(f"{'─'*55}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch tennis odds — odds-api.io v3")
    parser.add_argument("--key",        default=os.environ.get("ODDS_API_KEY", ""),
                        help="Clé API (ou variable ODDS_API_KEY)")
    parser.add_argument("--bookmakers", default=DEFAULT_BOOKMAKERS,
                        help="Bookmakers séparés par virgule")
    parser.add_argument("--limit",      type=int, default=3,
                        help="Nb de matchs à afficher (défaut 3)")
    parser.add_argument("--event-id",   default=None,
                        help="Forcer un eventId spécifique")
    args = parser.parse_args()

    if not args.key:
        sys.exit("[ERROR] Clé API manquante — set ODDS_API_KEY ou --key=xxx")

    # ── Chargement modèle (une seule fois) ───────────────────────────────
    print("[MODEL] Chargement du moteur TennisBoss…")
    mem = _load_model()
    model_ok = mem is not None
    if model_ok:
        n_players = len(mem.get("players") or {})
        print(f"[MODEL] OK — {n_players} joueurs chargés (fallback hybride actif)")
    else:
        print("[MODEL] Désactivé — bookmakers uniquement")

    # ── Step 1 : list events ─────────────────────────────────────────────
    print("\n[1/3] Récupération des matchs tennis…")
    events = fetch_events(args.key)
    live    = [e for e in events if e.get("status") in ("live", "inplay")]
    pending = [e for e in events if e.get("status") in ("pending", "not_started")]
    print(f"      → {len(events)} événements total  |  {len(live)} live  |  {len(pending)} à venir")

    if not events:
        sys.exit("[INFO] Aucun match disponible pour le moment.")

    # ── Step 2 : pick target events ──────────────────────────────────────
    if args.event_id:
        targets = [e for e in events if str(e["id"]) == str(args.event_id)]
        if not targets:
            sys.exit(f"[ERROR] eventId {args.event_id} introuvable dans les événements.")
    else:
        targets = (live + pending)[: args.limit]

    # ── Step 3 : fetch odds + hybrid fallback ────────────────────────────
    covered = 0
    hybrid  = 0
    blind   = 0

    for ev in targets:
        print(f"\n[2/3] Match sélectionné")
        print_event(ev)

        print(f"[3/3] Récupération des cotes (bookmakers: {args.bookmakers})…")
        odds = fetch_odds(ev["id"], args.bookmakers, args.key)
        has_market = print_odds(odds)

        if has_market:
            covered += 1
        elif model_ok:
            league = ev.get("league", {}).get("name", "")
            n1, n2 = _resolve_players(mem, ev.get("home", ""), ev.get("away", ""), league)
            if n1 and n2:
                pred = _model_predict(mem, n1, n2)
                if pred:
                    print_model_fallback(pred)
                    hybrid += 1
                else:
                    print(f"  [INFO] Prédiction impossible pour {n1} vs {n2}.\n")
                    blind += 1
            else:
                print(f"  [INFO] Résolution joueurs impossible.\n")
                blind += 1
        else:
            print(f"  [INFO] Aucune cote disponible et modèle désactivé.\n")
            blind += 1

    total = len(targets)
    print(f"{'═'*55}")
    print(f"  Résumé couverture : {total} matchs analysés")
    print(f"  ✅ Bookmaker réel   : {covered}")
    print(f"  🔬 Modèle hybride  : {hybrid}")
    print(f"  ❌ Aucune couverture: {blind}")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    main()
