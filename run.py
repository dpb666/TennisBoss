#!/usr/bin/env python3
"""Point d'entrée CLI de TennisBoss.

Commandes :
  python3 run.py start                       -> bot autonome (boucle infinie)
  python3 run.py train [--years ...] [--tours atp wta]  -> cycle d'apprentissage
  python3 run.py predict "J1" "J2"           -> prédit le 1er set entre deux joueurs
  python3 run.py players [--tour wta] [--export f.csv]  -> dictionnaire joueurs+probas
  python3 run.py backtest [--years ...]      -> backtest hors-échantillon (archivé)
  python3 run.py db                          -> contenu de la base + derniers backtests
  python3 run.py status                      -> état (poids, précision, top joueurs)
  python3 run.py reset                       -> efface l'état appris
  python3 run.py dedupe-players [--apply]    -> fusionne les profils joueurs dupliqués
  python3 run.py set-app-version 2 "1.1"     -> publie la dernière version Android (bandeau app)
"""
from __future__ import annotations

import argparse
import csv as _csv
import json
import os
import sys
from pathlib import Path

from bot import (backtest as bt, backup as backup_mod, config, datasource, db, features,
                 learner, live_api, memory, namematch, odds_api, predictor, signal_backtest)
from bot.bootstrap import bootstrap
from bot.log import log


def cmd_start(_args) -> None:
    from bot.supervisor import run_forever

    run_forever()


def cmd_train(args) -> None:
    cfg = bootstrap()
    if args.years:
        cfg["years"] = args.years
    if args.tours:
        cfg["tours"] = args.tours
    db.init()
    mem = memory.load()
    challengers = getattr(args, "challengers", False)
    log(f"Apprentissage — années {cfg['years']} | tours {cfg['tours']}"
        f"{' + Futures/ITF' if challengers else ''}")
    matches = datasource.fetch_matches(cfg["years"], cfg["tours"],
                                       include_challengers=challengers)
    if not matches:
        log("Aucune donnée récupérée (réseau ?). Abandon.", "ERROR")
        sys.exit(1)
    learner.train(mem, matches, cfg)
    for y in cfg["years"]:
        if str(y) not in mem["datasets_loaded"]:
            mem["datasets_loaded"].append(str(y))
    memory.save(mem)
    # Persistance "base solide" : archive des matchs + dictionnaire joueurs.
    added = db.archive_matches(matches)
    n_players = db.sync_from_memory(mem)
    log(f"Base : +{added} matchs archivés, {n_players} joueurs synchronisés.")


def cmd_predict(args) -> None:
    bootstrap()
    mem = memory.load()
    if not mem["players"]:
        log("Aucun joueur appris. Lancez d'abord : python3 run.py train", "WARN")

    p1 = features.feature_vector(features.get_profile(mem, args.player1))
    p2 = features.feature_vector(features.get_profile(mem, args.player2))
    prof1 = features.get_profile(mem, args.player1)
    prof2 = features.get_profile(mem, args.player2)

    result = predictor.predict(mem, args.player1, p1, args.player2, p2)

    print("\n" + "=" * 56)
    print(f"  PRÉDICTION 1er SET")
    print("=" * 56)
    print(f"  {result['player1']:<28} {result['prob1']:>6.2f}%  "
          f"(matchs vus: {int(prof1.get('n', 0))})")
    print(f"  {result['player2']:<28} {result['prob2']:>6.2f}%  "
          f"(matchs vus: {int(prof2.get('n', 0))})")
    print("-" * 56)
    print(f"  {result['verdict']}")
    if not features.is_confident(prof1) or not features.is_confident(prof2):
        print("  ⚠️  Confiance faible (joueur(s) peu/pas connu(s)).")
    print("=" * 56 + "\n")

    # Historique en base (archive des prédictions).
    try:
        db.init()
        db.log_prediction(result["player1"], result["player2"],
                          result["prob1"] / 100.0, result["favorite"])
    except Exception as exc:  # noqa: BLE001
        log(f"Impossible d'archiver la prédiction : {exc}", "WARN")


def cmd_players(args) -> None:
    bootstrap()
    db.init()
    rows = db.top_players(limit=args.limit, tour=args.tour, min_n=args.min_n)
    if not rows:
        log("Aucun joueur en base. Lancez d'abord : python3 run.py train", "WARN")
        return

    print(f"\n=== DICTIONNAIRE JOUEURS — top {len(rows)} par probabilité "
          f"{'(' + args.tour.upper() + ')' if args.tour else '(ATP+WTA)'} ===")
    print(f"{'#':>3}  {'Joueur':<26}{'tour':<5}{'win_prob':>9}{'rating':>8}{'n':>6}")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}  {r['name']:<26}{(r['tour'] or '?'):<5}"
              f"{r['win_prob']*100:>8.2f}%{r['rating']:>8.3f}{r['n']:>6}")
    print()

    if args.export:
        with db.connect() as conn:
            allrows = conn.execute(
                "SELECT name,tour,n,serve,return1,return2,recent,rating,win_prob,updated "
                "FROM players ORDER BY win_prob DESC"
            ).fetchall()
        with open(args.export, "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(["name", "tour", "n", "serve", "return1", "return2",
                        "recent", "rating", "win_prob", "updated"])
            w.writerows([tuple(r) for r in allrows])
        log(f"Dictionnaire complet exporté ({len(allrows)} joueurs) -> {args.export}")


def cmd_backtest(args) -> None:
    if getattr(args, "full", False):
        from bot import backtest_report
        path, report = backtest_report.generate()
        core = report["core"]
        print("\n=== RAPPORT DE BACKTEST COMPLET ===")
        print(f"  matchs archive : {report['n_matches_archive']} ({core.get('span')})")
        print(f"  accuracy+ELO   : {core.get('accuracy_elo')} (baseline {core.get('baseline')})")
        print(f"  logloss+ELO    : {core.get('logloss_elo')}  brier={core.get('brier_elo')}")
        for src, r in report["roi_theorique"].items():
            print(f"  ROI théorique ({src}) : {r['roi_pct']}% sur {r['n_bets']} paris "
                  f"| confiants : {r['roi_confiants_pct']}% sur {r['n_bets_confiants']}")
        print(f"\n  Rapport HTML : {path}\n")
        return
    cfg = bootstrap()
    if args.years:
        cfg["years"] = args.years
    if args.tours:
        cfg["tours"] = args.tours
    db.init()
    challengers = getattr(args, "challengers", False)
    log(f"Backtest — années {cfg['years']} | tours {cfg['tours']}{' + Futures/ITF' if challengers else ''}")
    matches = datasource.fetch_matches(cfg["years"], cfg["tours"],
                                       include_challengers=challengers)
    if not matches:
        log("Aucune donnée récupérée. Abandon.", "ERROR")
        sys.exit(1)
    report = bt.run(matches, cfg, persist=True)
    print("\n=== RAPPORT DE BACKTEST (hors-échantillon) ===")
    for k in ("id", "span", "tours", "n_train", "n_test"):
        print(f"  {k:<14}: {report.get(k)}")
    print(f"  {'baseline':<14}: {report['baseline']} (serve seul)")
    print(f"  {'accuracy':<14}: {report['accuracy']}  (+{(report['accuracy']-report['baseline'])*100:+.2f} pts vs baseline)")
    if report.get("accuracy_elo"):
        print(f"  {'accuracy+ELO':<14}: {report['accuracy_elo']}  (+{(report['accuracy_elo']-report['baseline'])*100:.2f} pts vs baseline)")
        print(f"  {'logloss+ELO':<14}: {report['logloss_elo']}  brier_elo={report['brier_elo']}")
    print()


def cmd_upcoming(args) -> None:
    cfg = bootstrap()
    db.init()
    mem = memory.load()
    if not mem["players"]:
        log("Aucun joueur appris. Lancez d'abord : python3 run.py train", "WARN")
        return

    # Index de résolution de noms (nom API abrégé -> nom complet appris).
    counts = {n: int(p.get("n", 0)) for n, p in mem["players"].items()}
    index = namematch.build_index(list(mem["players"]), counts)

    fixtures = live_api.fetch_upcoming(cfg, days_ahead=args.days)
    if not fixtures:
        log("Aucun match à venir récupéré (clé API ? réseau ?).", "WARN")
        return

    # Cotes optionnelles (odds-api.io) : un seul appel /events, puis appariement.
    odds_index = None
    if args.odds:
        if odds_api.is_enabled():
            odds_index = odds_api.build_event_index(
                odds_api.fetch_tennis_events(upcoming_only=True))
            log(f"Cotes activées : {len(odds_index)} événements odds-api.io indexés.")
        else:
            log("ODDS_API_KEY absente — cotes ignorées.", "WARN")

    singles = [f for f in fixtures if not f["is_doubles"]]
    print(f"\n=== MATCHS À VENIR ({len(singles)} simples, {args.days}j) — "
          f"prédiction 1er set{' + cotes' if odds_index else ''} ===")
    shown = 0
    odds_found = 0
    for f in singles:
        n1 = namematch.resolve(f["player1"], index)
        n2 = namematch.resolve(f["player2"], index)
        when = f"{f['date']} {f['time']}"
        head = f"{f['player1']} vs {f['player2']}  [{f['tournament']}, {when}]"
        if not n1 or not n2:
            miss = f['player1'] if not n1 else f['player2']
            print(f"  • {head}\n      → joueur inconnu en base : {miss} (pas de prédiction)")
            continue
        fe1 = features.feature_vector(features.get_profile(mem, n1))
        fe2 = features.feature_vector(features.get_profile(mem, n2))
        r = predictor.predict(mem, n1, fe1, n2, fe2)
        live_tag = " 🔴LIVE" if f["live"] else ""
        print(f"  • {head}{live_tag}")
        print(f"      → {r['favorite'] or 'serré'} | "
              f"{n1} {r['prob1']:.1f}% / {n2} {r['prob2']:.1f}%")
        if odds_index is not None:
            odds_found += _print_odds_line(odds_index, f["player1"], f["player2"])
        try:
            db.log_prediction(n1, n2, r["prob1"] / 100.0, r["favorite"], source="live")
        except Exception:  # noqa: BLE001
            pass
        shown += 1
        if args.limit and shown >= args.limit:
            break
    if odds_index is not None:
        print(f"\n  Cotes appariées : {odds_found}/{shown} matchs "
              f"(les autres ont un adversaire/planning différent chez odds-api.io).")
    print()


def _print_odds_line(odds_index, raw1: str, raw2: str) -> bool:
    """Affiche la ligne de cotes marché (no-vig) si trouvée. Renvoie True si affichée."""
    ev = odds_api.find_event(odds_index, raw1, raw2)
    if not ev:
        print("      cotes : — (appariement introuvable / autre adversaire)")
        return False
    mw = odds_api.fetch_match_winner(ev["id"])
    if not mw:
        print("      cotes : — (aucune cote proposée par les 2 bookmakers)")
        return False
    # Aligner le côté "home" du marché sur le joueur 1 affiché.
    from bot.namematch import split_name
    _, l_raw1 = split_name(raw1)
    _, l_home = split_name(ev.get("home", ""))
    p1, p2 = (mw["home_prob"], mw["away_prob"]) if l_raw1 == l_home \
        else (mw["away_prob"], mw["home_prob"])
    o1, o2 = (mw["home_odds"], mw["away_odds"]) if l_raw1 == l_home \
        else (mw["away_odds"], mw["home_odds"])
    print(f"      marché (match, no-vig) : {p1*100:.1f}% / {p2*100:.1f}%  "
          f"cotes {o1}/{o2} [{', '.join(mw['books'])}]")
    return True


def cmd_value(args) -> None:
    bootstrap()
    db.init()
    mem = memory.load()
    if not mem["players"]:
        log("Aucun joueur appris. Lancez d'abord : python3 run.py train", "WARN")
        return
    if not odds_api.is_enabled():
        log("ODDS_API_KEY absente du .env — impossible de récupérer les cotes.", "WARN")
        return

    counts = {n: int(p.get("n", 0)) for n, p in mem["players"].items()}
    index = namematch.build_index(list(mem["players"]), counts)

    events = odds_api.fetch_tennis_events(upcoming_only=True)
    if not events:
        log("Aucun événement tennis à venir renvoyé par odds-api.io.", "WARN")
        return

    print(f"\n=== MODÈLE (1er set) vs MARCHÉ (vainqueur match) — odds-api.io ===")
    print("  Note : marchés différents (1er set ≠ match), comparaison indicative.\n")
    shown = 0
    for e in events:
        n1 = namematch.resolve(e.get("home", ""), index)
        n2 = namematch.resolve(e.get("away", ""), index)
        if not n1 or not n2:
            continue  # on ne montre que les matchs prédictibles
        mw = odds_api.fetch_match_winner(e["id"])
        if not mw:
            continue  # pas de cotes -> on passe (cible: matchs cotés)

        fe1 = features.feature_vector(features.get_profile(mem, n1))
        fe2 = features.feature_vector(features.get_profile(mem, n2))
        r = predictor.predict(mem, n1, fe1, n2, fe2)
        model_h = r["prob1"]                       # notre proba 1er set (home)
        mkt_h = mw["home_prob"] * 100              # proba marché match (home)
        edge = model_h - mkt_h
        flag = "  ⟵ écart notable" if abs(edge) >= 10 else ""

        print(f"  • {n1}  vs  {n2}   [{(e.get('league') or {}).get('name','')[:40]}]")
        print(f"      modèle 1er set : {model_h:5.1f}% / {r['prob2']:5.1f}%")
        print(f"      marché match   : {mkt_h:5.1f}% / {mw['away_prob']*100:5.1f}%  "
              f"(cotes {mw['home_odds']}/{mw['away_odds']}, {', '.join(mw['books'])})")
        print(f"      écart (1er set − match, côté {n1}) : {edge:+.1f} pts{flag}")
        shown += 1
        if shown >= args.limit:
            break
    if not shown:
        log("Aucun match à la fois prédictible ET coté dans l'échantillon.", "INFO")
    print()


def cmd_serve(args) -> None:
    import os
    from pathlib import Path
    from bot import api

    # Écrit le PID pour que le watchdog externe puisse tuer/redémarrer le bon process
    Path("/tmp/tennisboss_server.pid").write_text(str(os.getpid()))

    api.serve(host=args.host, port=args.port)


def cmd_db(_args) -> None:
    bootstrap()
    db.init()
    c = db.counts()
    print("\n--- BASE DE DONNÉES ---")
    print(f"Joueurs     : {c['players']}")
    print(f"Matchs      : {c['matches']}")
    print(f"Prédictions : {c['predictions']}")
    print(f"Backtests   : {c['backtests']}")
    rows = db.list_backtests(limit=5)
    if rows:
        print("\nDerniers backtests archivés :")
        for r in rows:
            print(f"  #{r['id']} {r['ts']} | {r['tours']} | acc={r['accuracy']} "
                  f"base={r['baseline']} logloss={r['logloss']} "
                  f"(test={r['n_test']})")
    print()


def cmd_status(_args) -> None:
    bootstrap()
    mem = memory.load()
    m = mem["metrics"]
    print("\n--- ÉTAT DU BOT ---")
    print(f"Battements de cœur : {mem['heartbeat'].get('count', 0)} "
          f"(dernier : {mem['heartbeat'].get('last_iso')})")
    print(f"Jeux de données chargés : {mem['datasets_loaded'] or '—'}")
    print(f"Joueurs connus : {len(mem['players'])}")
    print(f"Prédictions : {m['predictions']} | Précision globale : {m['accuracy']}")
    print(f"Dernière log-loss : {m['last_loss']}")
    print("\nPoids appris :")
    for k in config.FEATURE_ORDER:
        print(f"  {k:<8} : {mem['weights'][k]:+.4f}")
    print(f"  {'biais':<8} : {mem['bias']:+.4f}")

    if mem["players"]:
        top = sorted(
            mem["players"].items(),
            key=lambda kv: kv[1].get("serve", 0) + kv[1].get("recent", 0),
            reverse=True,
        )[:8]
        print("\nTop joueurs (serve + forme), parmi les bien connus :")
        shown = 0
        for name, prof in top:
            if prof.get("n", 0) >= config.DEFAULT_CONFIG["min_matches_confident"]:
                print(f"  {name:<26} serve={prof['serve']:.2f} "
                      f"forme={prof['recent']:.2f} n={prof['n']}")
                shown += 1
        if not shown:
            print("  (pas encore assez de matchs par joueur)")
    print()


def cmd_reset(args) -> None:
    paths = [config.MEMORY_FILE, config.MEMORY_FILE + ".corrupt"]
    if args.all:
        paths.append(config.DB_FILE)
    for path in paths:
        if os.path.exists(path):
            os.remove(path)
    log("État effacé" + (" (modèle + base)." if args.all else " (modèle ; base conservée)."))


def cmd_backup(_args) -> None:
    """Sauvegarde immédiate de state/tennisboss.db (utile avant une manip manuelle risquée)."""
    path = backup_mod.backup_now()
    if path:
        print(f"Sauvegarde créée : {path}")
    else:
        print("Rien à sauvegarder (base introuvable).")
    existing = backup_mod.list_backups()
    print(f"{len(existing)} sauvegarde(s) conservée(s) dans {backup_mod.BACKUP_DIR}")


def cmd_signals(_args) -> None:
    """Backtest walk-forward des signaux Sport Intelligence Layer (voir bot/signal_backtest.py)."""
    report = signal_backtest.run_all()
    print("\n--- CALIBRATION (calib_k / Platt) ---")
    c = report["calibration"]
    if not c.get("fitted"):
        print(c.get("note"))
    else:
        print(f"Train: {c['n_train']} ({c['span_train']}) | Test: {c['n_test']} ({c['span_test']})")
        print(f"Log-loss  brut={c['logloss_raw']}  température(k={c['fitted_k']})={c['logloss_temperature']}  "
              f"Platt(a={c['fitted_platt_a']},b={c['fitted_platt_b']})={c['logloss_platt']}")
        print(c["verdict"])

    print("\n--- FORM_SIGNAL ---")
    f = report["form_signal"]
    print(f"{f['n_matches_replayed']} matchs rejoués | seuil={f['threshold_pts']}pts, min={f['min_matches']} matchs")
    print(f"Surperformance : {f['surperformance']['wins']}/{f['surperformance']['total']} "
          f"({f['surperformance_win_rate']})")
    print(f"Méforme        : {f['méforme']['wins']}/{f['méforme']['total']} ({f['méforme_win_rate']})")
    print(f"Baseline       : {f['aucun_signal']['wins']}/{f['aucun_signal']['total']} ({f['baseline_win_rate']})")
    print(f"Limite : {f['caveat']}")
    print(f['verdict'])

    print("\n--- STEAM_MOVE ---")
    s = report["steam_move"]
    if s.get("n_with_move", 0) == 0:
        print(s.get("note"))
    else:
        print(f"n={s['n_with_move']} | taux de victoire réel={s['actual_win_rate_moved_side']} "
              f"vs implicite ouverture={s['avg_opening_implied_prob']} (edge {s['edge_vs_opening_line']:+})")
        print(s["verdict"])

    print("\n--- CLUTCH (BP sauvées) ---")
    c = report["clutch"]
    if c.get("n_evaluated", 0) == 0:
        print(c.get("note"))
    else:
        print(f"{c['n_matches_with_bp']} matchs avec stats BP | "
              f"{c['n_evaluated']} évalués (écart >= {c['diff_threshold']})")
        print(f"Côté plus clutch gagne : {c['clutch_side_win_rate']} (baseline 0.5)")
        print(f"Limite : {c['caveat']}")
        print(c["verdict"])
    print()


def _safe_print(text: str) -> None:
    """Print Unicode safely on Windows consoles (cp1252)."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc))


def cmd_clv_weekly(args) -> None:
    """Rapport CLV sur les N derniers jours (paper trading / validation edge)."""
    from bot import clv as clv_mod, digest
    days = max(1, int(getattr(args, "days", 7)))
    _safe_print(digest.build_weekly_clv_report(days=days))
    stats = clv_mod.weekly_stats(days=days)
    print("\n--- JSON ---")
    print(json.dumps(stats, indent=2, ensure_ascii=True, default=str))


def cmd_validate_tis(args) -> None:
    from bot import validate_tis
    db.init()
    rep = validate_tis.run_validation(limit=args.limit, write_report=True)
    print(json.dumps(rep, indent=2, ensure_ascii=True, default=str))


def cmd_calibration_report(args) -> None:
    from bot import calibration_report
    db.init()
    path, report = calibration_report.generate(days=args.days, write_file=True)
    print(f"Rapport écrit : {path}")
    if isinstance(report, dict):
        print(json.dumps(report, indent=2, ensure_ascii=True, default=str))


def cmd_data_quality(args) -> None:
    from bot import data_quality
    data_quality.print_report(active_days=args.days)


def cmd_ingest_rankings(args) -> None:
    from bot import ranking_feeder
    rep = ranking_feeder.ingest(
        years=args.years,
        tours=args.tours,
        live=not args.no_live,
        live_limit=args.limit,
    )
    print(json.dumps(rep, indent=2, ensure_ascii=True, default=str))


def cmd_backfill_bet_history(args) -> None:
    db.init()
    result = db.backfill_bet_history_from_clv(limit=args.limit)
    print(
        f"bet_history : {result['added']} lignes backfillées, "
        f"{result['patched']} surfaces corrigées (value_picks)"
    )
    if getattr(args, "archive", False):
        arch = db.backfill_bet_history_surface_from_matches()
        print(f"bet_history : {arch['patched']} surfaces corrigées (archive matches)")


def cmd_surface_benchmark(args) -> None:
    from bot import surface_experiment
    db.init()
    report = surface_experiment.run_benchmark(
        test_fraction=args.test_fraction,
        min_test=args.min_test,
        write_report=True,
    )
    print(json.dumps(report, indent=2, ensure_ascii=True, default=str))


def cmd_surface_data_audit(_args) -> None:
    import subprocess
    script = Path(__file__).resolve().parent / "scripts" / "surface_data_audit.py"
    subprocess.run([sys.executable, str(script)], check=False)


def cmd_set_app_version(args) -> None:
    """Publie la dernière version Android connue (bandeau "mise à jour
    disponible" côté app, avant publication Play Store — voir
    bot/db.py::set_app_version, GET /api/app/version)."""
    db.set_app_version(args.version_code, args.version_name,
                       notes=args.notes or "", download_url=args.download_url)
    print(f"Version publiée : code={args.version_code} name={args.version_name!r}"
          + (f" notes={args.notes!r}" if args.notes else "")
          + (f" url={args.download_url!r}" if args.download_url else ""))


def cmd_dedupe_players(args) -> None:
    """Fusionne les profils joueurs dupliqués par variation de format de nom
    (ex. "Andreeva M." / "Mirra Andreeva" — voir bot/dedupe_players.py pour
    le contexte du bug corrigé dans namematch.split_name()).

    Par défaut : dry-run (affiche le diagnostic, ne modifie rien).
    --apply : fusionne réellement (mem + DB matches + rebuild ELO complet).
    """
    from bot import dedupe_players

    mem = memory.load()
    rep = dedupe_players.report(mem)
    print(f"{rep['total_players']} joueurs, {rep['duplicate_groups']} groupes "
          f"dupliqués sûrs ({rep['players_involved']} profils concernés).")
    for d in rep["details"][:args.top]:
        print(f"  {d['canonical']!r} <- {d['aliases']} (n total={d['total_n']})")
    if len(rep["details"]) > args.top:
        print(f"  ... et {len(rep['details']) - args.top} autres groupes.")

    if rep["ambiguous_groups"]:
        print(f"\n{rep['ambiguous_groups']} groupes AMBIGUS (2+ prénoms complets "
              f"distincts partageant nom+initiale — non fusionnés automatiquement) :")
        for d in rep["ambiguous_details"][:args.top]:
            print(f"  {d['canonical']!r} vs {d['aliases']} (n total={d['total_n']})")

    if not args.apply:
        print("\nDry-run (aucune écriture). Relancer avec --apply pour fusionner.")
        return

    result = dedupe_players.merge(mem)
    memory.save(mem)
    print(f"\nFusion appliquée : {result['merged_groups']} groupes fusionnés, "
          f"{result['matches_renamed']} lignes matches renommées, "
          f"{result['players_deleted']} alias supprimés de la table players.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tennisboss", description="Bot tennis autonome")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("start", help="Lance le bot autonome").set_defaults(func=cmd_start)

    p_train = sub.add_parser("train", help="Un cycle d'apprentissage")
    p_train.add_argument("--years", nargs="+", type=int, help="Années à charger")
    p_train.add_argument("--tours", nargs="+", choices=["atp", "wta"],
                         help="Tours à charger (atp wta)")
    p_train.add_argument("--challengers", action="store_true",
                         help="Inclure matchs ITF/Futures ATP (~18k matchs/an)")
    p_train.set_defaults(func=cmd_train)

    p_pred = sub.add_parser("predict", help="Prédire le 1er set")
    p_pred.add_argument("player1")
    p_pred.add_argument("player2")
    p_pred.set_defaults(func=cmd_predict)

    p_players = sub.add_parser("players", help="Dictionnaire joueurs + probabilités")
    p_players.add_argument("--tour", choices=["atp", "wta"], help="Filtrer par tour")
    p_players.add_argument("--limit", type=int, default=20, help="Nb de lignes affichées")
    p_players.add_argument("--min-n", dest="min_n", type=int, default=5,
                           help="Min. de matchs pour être listé")
    p_players.add_argument("--export", help="Exporter TOUT le dictionnaire en CSV")
    p_players.set_defaults(func=cmd_players)

    p_bt = sub.add_parser("backtest", help="Backtest hors-échantillon (archivé)")
    p_bt.add_argument("--years", nargs="+", type=int, help="Années à charger")
    p_bt.add_argument("--tours", nargs="+", choices=["atp", "wta"], help="Tours")
    p_bt.add_argument("--challengers", action="store_true",
                      help="Inclure les Futures/ITF ATP dans le backtest")
    p_bt.add_argument("--full", action="store_true",
                      help="Rapport complet hors-ligne (archive DB) -> "
                           "reports/backtest_report.html")
    p_bt.set_defaults(func=cmd_backtest)

    p_up = sub.add_parser("upcoming", help="Matchs à venir (live) + prédiction 1er set")
    p_up.add_argument("--days", type=int, default=2, help="Horizon en jours")
    p_up.add_argument("--limit", type=int, default=25, help="Max de matchs affichés")
    p_up.add_argument("--odds", action="store_true",
                      help="Ajouter les cotes marché (odds-api.io)")
    p_up.set_defaults(func=cmd_upcoming)

    p_val = sub.add_parser("value", help="Compare modèle (1er set) vs cotes marché")
    p_val.add_argument("--limit", type=int, default=10, help="Max de matchs cotés")
    p_val.set_defaults(func=cmd_value)

    p_serve = sub.add_parser("serve", help="Lance l'API REST (backend Android)")
    p_serve.add_argument("--host", default="0.0.0.0", help="Adresse d'écoute")
    p_serve.add_argument("--port", type=int, default=8000, help="Port")
    p_serve.set_defaults(func=cmd_serve)

    sub.add_parser("db", help="Contenu de la base + backtests").set_defaults(func=cmd_db)
    sub.add_parser("status", help="État du bot").set_defaults(func=cmd_status)
    p_reset = sub.add_parser("reset", help="Effacer l'état appris")
    p_reset.add_argument("--all", action="store_true", help="Effacer aussi la base SQLite")
    p_reset.set_defaults(func=cmd_reset)

    sub.add_parser("backup", help="Sauvegarde immédiate de la base SQLite").set_defaults(func=cmd_backup)
    sub.add_parser("signals", help="Backtest calib_k/form_signal/steam_move").set_defaults(func=cmd_signals)

    p_clv = sub.add_parser("clv-weekly", help="Rapport CLV des N derniers jours")
    p_clv.add_argument("--days", type=int, default=7, help="Fenêtre glissante (défaut 7)")
    p_clv.set_defaults(func=cmd_clv_weekly)

    p_vtis = sub.add_parser("validate-tis", help="Validation Tennis Intelligence Score")
    p_vtis.add_argument("--limit", type=int, default=50, help="Nb de paires à tester")
    p_vtis.set_defaults(func=cmd_validate_tis)

    p_cal = sub.add_parser("calibration-report", help="Rapport calibration modèle")
    p_cal.add_argument("--days", type=int, default=90, help="Fenêtre en jours")
    p_cal.set_defaults(func=cmd_calibration_report)

    p_dq = sub.add_parser("data-quality", help="Couverture WTA serve + rankings")
    p_dq.add_argument("--days", type=int, default=365, help="Fenêtre joueurs actifs")
    p_dq.set_defaults(func=cmd_data_quality)

    p_rank = sub.add_parser("ingest-rankings", help="Ingestion classements ATP/WTA")
    p_rank.add_argument("--years", nargs="+", type=int, help="Années tennis-data")
    p_rank.add_argument("--tours", nargs="+", choices=["atp", "wta"])
    p_rank.add_argument("--no-live", action="store_true", help="Sans scrape live top-N")
    p_rank.add_argument("--limit", type=int, default=1000, help="Top N live par page")
    p_rank.set_defaults(func=cmd_ingest_rankings)

    p_bh = sub.add_parser("backfill-bet-history", help="Remplit bet_history depuis clv_log")
    p_bh.add_argument("--limit", type=int, default=5000, help="Max lignes clv_log")
    p_bh.add_argument("--archive", action="store_true",
                      help="Aussi backfill surface depuis archive matches")
    p_bh.set_defaults(func=cmd_backfill_bet_history)

    p_surf = sub.add_parser("surface-benchmark",
                            help="Walk-forward benchmark surface features (offline)")
    p_surf.add_argument("--test-fraction", type=float, default=0.25,
                        help="Fraction holdout test (défaut 0.25)")
    p_surf.add_argument("--min-test", type=int, default=500,
                        help="Minimum matchs dans le holdout")
    p_surf.set_defaults(func=cmd_surface_benchmark)

    sub.add_parser("surface-data-audit",
                   help="Rapport couverture surface (matches, bet_history)").set_defaults(
        func=cmd_surface_data_audit)

    p_dedupe = sub.add_parser("dedupe-players",
                              help="Fusionne les profils joueurs dupliqués (ex. 'Andreeva M.' / 'Mirra Andreeva')")
    p_dedupe.add_argument("--apply", action="store_true",
                          help="Applique la fusion (par défaut : dry-run, diagnostic seulement)")
    p_dedupe.add_argument("--top", type=int, default=15, help="Nb de groupes affichés dans le diagnostic")
    p_dedupe.set_defaults(func=cmd_dedupe_players)

    p_ver = sub.add_parser("set-app-version",
                           help="Publie la dernière version Android (bandeau mise à jour app)")
    p_ver.add_argument("version_code", type=int, help="versionCode (android/app/build.gradle.kts)")
    p_ver.add_argument("version_name", help="versionName (ex. '1.1')")
    p_ver.add_argument("--notes", help="Notes de version affichées dans le bandeau")
    p_ver.add_argument("--download-url", dest="download_url", help="Lien de téléchargement de l'APK (optionnel)")
    p_ver.set_defaults(func=cmd_set_app_version)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
