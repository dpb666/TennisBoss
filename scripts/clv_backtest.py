"""Backtest walk-forward : le modèle ELO aurait-il battu le marché (2022-2026) ?

Contrairement au CLV live (bot/clv_log, ~54 picks), ce script rejoue TOUT
l'historique disponible avec cotes (table historical_odds, tennis-data.co.uk,
8847 matchs ATP/WTA grands tournois 2022-2026) et calcule pour CHAQUE match
la probabilité ELO du modèle *avant* de connaître le résultat.

Anti-fuite (leakage) — règles strictes :
  1. Source ELO canonique = matches Sackmann UNIQUEMENT (id NOT LIKE 'td_%').
     La table `matches` contient aussi des lignes tennisdata (même vrais
     matchs, features neutres) : les inclure doublonnerait les mises à jour
     ELO. `historical_odds` sert UNIQUEMENT de recherche de cotes, jamais
     pour construire l'ELO lui-même.
  2. Tri chronologique strict (dates normalisées YYYYMMDD).
  3. Pour un match à l'instant T, la proba modèle utilise l'ELO calculé sur
     tous les matchs < T uniquement (jamais T lui-même ni après) — la mise à
     jour ELO du match T n'a lieu qu'APRÈS avoir enregistré la prédiction.

Limite méthodologique assumée : les cotes tennis-data.co.uk sont une seule
cote par match (proche de la clôture), pas un couple entrée/clôture comme le
CLV live — ce script mesure donc un ROI/EV vs cote de clôture (edge), pas un
"beat closing" au sens strict. C'est un test plus direct de rentabilité, pas
un substitut identique au CLV live.

Usage : python3 scripts/clv_backtest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import calibrate, db, elo, namematch  # noqa: E402


def _norm_date(d: str) -> str:
    """Uniformise en YYYY-MM-DD (accepte YYYYMMDD ou déjà YYYY-MM-DD)."""
    d = (d or "").strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d


def _parse_td_name(name: str):
    """Format tennis-data.co.uk 'Djokovic N.' -> (initiale, nom_de_famille)."""
    toks = namematch._norm(name).split()
    if not toks:
        return "", ""
    if len(toks) == 1:
        return "", toks[0]
    return toks[-1][:1], " ".join(toks[:-1])


def _resolve_td_name(td_name: str, index) -> str | None:
    init, last = _parse_td_name(td_name)
    candidates = index.get(last)
    if not candidates:
        return None
    if len(candidates) == 1:
        if init:
            f_init, _ = namematch.split_name(candidates[0])
            if f_init and f_init != init:
                return None
        return candidates[0]
    matches_init = [c for c in candidates
                    if init and namematch.split_name(c)[0] == init]
    if matches_init:
        return matches_init[0]
    return None if init else candidates[0]


def devig(odds_w: float, odds_l: float) -> tuple[float, float]:
    """Retire la marge bookmaker : proba brute normalisée à somme=1."""
    pw, pl = 1.0 / odds_w, 1.0 / odds_l
    tot = pw + pl
    return pw / tot, pl / tot


def main() -> None:
    # calib_k et market_blend_w de production (fit sur les matchs réglés live —
    # échantillon disjoint de ce backtest, donc aucune fuite en les réutilisant
    # ici). Le blend marché est ESSENTIEL : sans lui, la compression calib_k
    # vers 50% gonfle artificiellement l'EV apparente des outsiders (petite
    # hausse de proba x grosse cote = "value" illusoire). La prod ne calcule
    # jamais l'EV sur la seule proba modèle/calibrée, toujours sur le blend.
    CALIB_K = float(db.get_meta("match_calib_k") or 1.0)
    MKT_W = float(db.get_meta("market_blend_w") or calibrate.DEFAULT_MARKET_BLEND_W)
    print(f"Calibration (hors échantillon) : calib_k={CALIB_K}  market_blend_w={MKT_W}")

    print("Chargement des matchs Sackmann (source ELO canonique)...")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, date, winner, loser, surface, margin FROM matches "
            "WHERE id NOT LIKE 'td_%' ORDER BY date"
        ).fetchall()
    sackmann = [dict(r) for r in rows]
    for m in sackmann:
        m["date"] = _norm_date(m["date"])
    print(f"  {len(sackmann)} matchs Sackmann ({sackmann[0]['date']}..{sackmann[-1]['date']})")

    print("Index de résolution des noms...")
    counts: dict[str, int] = {}
    all_names: list[str] = []
    for m in sackmann:
        for n in (m["winner"], m["loser"]):
            counts[n] = counts.get(n, 0) + 1
            all_names.append(n)
    index = namematch.build_index(list(set(all_names)), counts)

    print("Chargement + résolution des cotes historiques (tennis-data.co.uk)...")
    with db.connect() as conn:
        odds_rows = conn.execute(
            "SELECT date, winner, loser, avgw, avgl, maxw, maxl, b365w, b365l "
            "FROM historical_odds"
        ).fetchall()

    # Sackmann date = DÉBUT DU TOURNOI (identique pour tous ses matchs), tandis
    # que tennis-data.co.uk donne la vraie date du match. Jointure par paire de
    # noms + fenêtre [date_tournoi, date_tournoi+21j] plutôt que date exacte.
    from datetime import date as _date, timedelta as _td

    odds_by_pair: dict[frozenset, list] = {}
    unresolved = 0
    for r in odds_rows:
        rw = _resolve_td_name(r["winner"], index)
        rl = _resolve_td_name(r["loser"], index)
        if not rw or not rl:
            unresolved += 1
            continue
        odds_by_pair.setdefault(frozenset((rw, rl)), []).append(
            (_norm_date(r["date"]), dict(r))
        )
    n_resolved = sum(len(v) for v in odds_by_pair.values())
    print(f"  {n_resolved} cotes résolues, {unresolved} noms non résolus "
          f"({unresolved/len(odds_rows)*100:.1f}%)")

    def _find_odds(pair: frozenset, tourney_start: str):
        candidates = odds_by_pair.get(pair)
        if not candidates:
            return None
        try:
            start = _date.fromisoformat(tourney_start)
        except ValueError:
            return None
        window_end = start + _td(days=21)
        best = None
        for d_str, odds in candidates:
            try:
                d = _date.fromisoformat(d_str)
            except ValueError:
                continue
            if start <= d <= window_end:
                if best is None or d < best[0]:
                    best = (d, odds)
        return best[1] if best else None

    print("Walk-forward : ELO chronologique + prédiction pré-match...")
    ratings: dict[str, float] = {}
    n_played: dict[str, int] = {}

    n_tested = 0
    n_correct = 0
    n_picked = 0          # nb de fois où le modèle aurait misé (EV>0 sur un côté)
    n_picked_correct = 0
    briers = []
    pnl_flat = 0.0
    pnl_market_favorite = 0.0  # baseline : toujours le favori du marché (Avg)

    for m in sackmann:
        odds = _find_odds(frozenset((m["winner"], m["loser"])), m["date"])

        if odds is not None:
            rw = ratings.get(m["winner"], elo.BASE)
            rl = ratings.get(m["loser"], elo.BASE)
            p_model_w = elo.expected(rw, rl)  # proba ELO que "winner" gagne, pré-match

            # Référence marché : Avg (moyenne tous bookmakers), dévigée.
            avgw, avgl = odds.get("avgw"), odds.get("avgl")
            if avgw and avgl and avgw > 1.0 and avgl > 1.0:
                mkt_pw, mkt_pl = devig(avgw, avgl)

                n_tested += 1
                pred_correct = p_model_w > 0.5  # le modèle penchait-il pour le vrai vainqueur ?
                n_correct += 1 if pred_correct else 0
                briers.append((p_model_w - 1.0) ** 2)  # issue=1 (winner a gagné)

                # EV sur proba calibrée PUIS blendée avec le marché (comme en
                # prod : bot/api.py ne calcule jamais l'EV sur le modèle seul).
                p_calib_w = calibrate.calibrated_prob(p_model_w, CALIB_K)
                p_blend_w = calibrate.blend_probs(p_calib_w, mkt_pw, MKT_W)
                maxw, maxl = odds.get("maxw") or avgw, odds.get("maxl") or avgl
                ev_w = p_blend_w * maxw - 1.0
                ev_l = (1.0 - p_blend_w) * maxl - 1.0

                if ev_w >= 8.0 / 100.0 or ev_l >= 0.08:
                    n_picked += 1
                    if ev_w >= ev_l:
                        # Modèle mise sur "winner" (qui a réellement gagné) -> gain.
                        n_picked_correct += 1
                        pnl_flat += (maxw - 1.0)
                    else:
                        # Modèle mise sur "loser" (qui a perdu) -> perte.
                        pnl_flat += -1.0

                # Baseline : miser 1u sur le favori du MARCHÉ à chaque match testé.
                if mkt_pw >= mkt_pl:
                    pnl_market_favorite += (avgw - 1.0)  # favori = winner -> gagné
                else:
                    pnl_market_favorite += -1.0  # favori = loser -> perdu

        elo.update_dynamic(ratings, n_played, m["winner"], m["loser"],
                           mult=elo.mult_from_margin(m["margin"]) if m["margin"] is not None else 1.0)

    print()
    print("=== RÉSULTATS (walk-forward, sans fuite) ===")
    print(f"Matchs avec cote résolue et testés : {n_tested}")
    if n_tested:
        print(f"Précision ELO (bon vainqueur) : {n_correct/n_tested*100:.1f}%")
        print(f"Brier score : {sum(briers)/len(briers):.4f}")
        print()
        print(f"Picks value (EV>=8% vs Max) : {n_picked} "
              f"({n_picked/n_tested*100:.1f}% des matchs testés)")
        if n_picked:
            print(f"  Win rate : {n_picked_correct/n_picked*100:.1f}%")
            print(f"  ROI flat (1u/pick, cote Max) : {pnl_flat/n_picked*100:+.1f}%  "
                  f"(P&L total {pnl_flat:+.1f}u)")
        print()
        print(f"Baseline 'toujours le favori du marché Avg' : "
              f"ROI {pnl_market_favorite/n_tested*100:+.1f}% sur {n_tested} matchs")


if __name__ == "__main__":
    main()
