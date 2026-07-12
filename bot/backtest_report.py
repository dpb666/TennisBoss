"""Rapport de backtest consolidé (run.py backtest --full).

Rassemble en un seul document HTML auto-suffisant (reports/backtest_report.html)
tout ce que le projet sait mesurer sur la qualité du modèle :

  1. Backtest hors-échantillon classique (bot/backtest.py) sur l'ARCHIVE en
     base (db.matches_for_backtest, ordre chronologique strict, aucun réseau) :
     accuracy / log-loss / Brier, modèle features seul et features+ELO,
     contre la baseline "meilleur service gagne".
  2. Courbe de calibration (reliability diagram) construite sur les
     prédictions du split de test — chaque match compté dans les deux
     orientations (p, gagné) et (1-p, perdu) pour ne pas biaiser les bins.
  3. ROI théorique : mise à plat de 1u sur le favori du modèle, réglée aux
     cotes marché historiques (tennis-data.co.uk, table historical_odds),
     jointes par (date normalisée, vainqueur, perdant). Cotes moyennes marché
     et Pinnacle séparément.
  4. Backtest walk-forward des signaux (bot/signal_backtest.py) : calibration
     k/Platt, form_signal, steam_move.
  5. Performance RÉELLE en production : picks value réglés, picks in-play,
     CLV — les seules mesures qui comptent vraiment pour prouver un edge.

Limites assumées, affichées dans le rapport : le modèle prédit le 1er set,
les cotes historiques portent sur le match ; le ROI théorique est donc
indicatif, pas une promesse. Aucun pari automatique — outil d'analyse.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import os
from typing import Any, Dict, List, Optional, Tuple

from . import backtest as bt, clv, config, db, signal_backtest
from .bootstrap import bootstrap
from .log import log

REPORT_DIR = "reports"
REPORT_FILE = "backtest_report.html"
N_BINS = 10


# ── Collecte ──────────────────────────────────────────────────────────────────

def _reliability_bins(details: List[Dict[str, Any]], n_bins: int = N_BINS) -> List[Dict[str, Any]]:
    """Bins de calibration. Chaque match de test fournit deux points
    symétriques — (p, 1) côté vainqueur réel et (1-p, 0) côté perdant — sinon
    tous les y valent 1 (p est la proba du vainqueur réel) et le diagramme
    n'a aucun sens."""
    pairs: List[Tuple[float, float]] = []
    for d in details:
        p = float(d["p_elo"])
        pairs.append((p, 1.0))
        pairs.append((1.0 - p, 0.0))
    bins = [{"lo": i / n_bins, "hi": (i + 1) / n_bins, "n": 0,
             "sum_p": 0.0, "sum_y": 0.0} for i in range(n_bins)]
    for p, y in pairs:
        # +1e-9 : 1.0-0.8 vaut 0.1999...96 en flottant et tomberait dans le
        # bin inférieur sans cette tolérance.
        idx = min(int(p * n_bins + 1e-9), n_bins - 1)
        b = bins[idx]
        b["n"] += 1
        b["sum_p"] += p
        b["sum_y"] += y
    out = []
    for b in bins:
        out.append({
            "range": f"{b['lo']:.1f}–{b['hi']:.1f}",
            "n": b["n"],
            "mean_predicted": round(b["sum_p"] / b["n"], 4) if b["n"] else None,
            "observed_rate": round(b["sum_y"] / b["n"], 4) if b["n"] else None,
        })
    return out


def _theoretical_roi(details: List[Dict[str, Any]],
                     odds_index: Dict[tuple, Dict[str, Any]]) -> Dict[str, Any]:
    """Mise à plat 1u sur le favori du modèle (p_elo), réglée aux cotes
    historiques. Seuls les matchs de test présents dans historical_odds
    comptent (sous-ensemble tennis-data)."""
    def settle(odds_w: Optional[float], odds_l: Optional[float],
               p_elo: float) -> Optional[float]:
        # p_elo = proba prédite que le vainqueur réel gagne.
        if p_elo >= 0.5:           # favori modèle = vainqueur réel -> pari gagné
            return (odds_w - 1.0) if odds_w and odds_w > 1.0 else None
        return -1.0 if odds_l and odds_l > 1.0 else None  # favori = perdant réel

    out: Dict[str, Any] = {}
    for src, kw, kl in (("marché_moyen", "avgw", "avgl"), ("pinnacle", "psw", "psl")):
        n = 0
        pnl = 0.0
        n_conf = 0
        pnl_conf = 0.0
        for d in details:
            key = ((d["date"] or "").replace("-", ""), d["winner"], d["loser"])
            odds = odds_index.get(key)
            if not odds:
                continue
            res = settle(odds.get(kw), odds.get(kl), float(d["p_elo"]))
            if res is None:
                continue
            n += 1
            pnl += res
            conf = max(float(d["p_elo"]), 1.0 - float(d["p_elo"]))
            if conf >= 0.60:
                n_conf += 1
                pnl_conf += res
        out[src] = {
            "n_bets": n,
            "pnl_flat": round(pnl, 2),
            "roi_pct": round(pnl / n * 100, 2) if n else None,
            "n_bets_confiants": n_conf,
            "roi_confiants_pct": round(pnl_conf / n_conf * 100, 2) if n_conf else None,
        }
    return out


def full_report() -> Dict[str, Any]:
    """Collecte toutes les sections. Lève ValueError si l'archive est vide."""
    cfg = bootstrap()
    db.init()
    matches = db.matches_for_backtest()
    log(f"Backtest --full : {len(matches)} matchs archivés (ordre chronologique normalisé).")
    core = bt.run(matches, cfg, persist=True, return_details=True)
    details = core.pop("details", [])

    report = {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "n_matches_archive": len(matches),
        "core": core,
        "calibration_bins": _reliability_bins(details),
        "roi_theorique": _theoretical_roi(details, db.historical_odds_index()),
        "signals": signal_backtest.run_all(),
        "production": {
            "value_picks": db.value_picks_stats(),
            "inplay": db.inplay_roi_stats(),
            "clv": clv.stats(),
        },
    }
    return report


# ── Rendu HTML ────────────────────────────────────────────────────────────────

def _esc(v: Any) -> str:
    return _html.escape(str(v))


def _kv_table(d: Dict[str, Any], skip: tuple = ()) -> str:
    """Table clé/valeur générique pour un dict plat (les valeurs conteneurs
    sont résumées) — robuste aux évolutions de schéma des sections."""
    rows = []
    for k, v in d.items():
        if k in skip:
            continue
        if isinstance(v, dict):
            v = ", ".join(f"{ik}={iv}" for ik, iv in v.items()
                          if not isinstance(iv, (dict, list)))
        elif isinstance(v, list):
            v = f"[{len(v)} éléments]"
        rows.append(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>")
    return f"<table>{''.join(rows)}</table>"


def _calibration_svg(bins: List[Dict[str, Any]]) -> str:
    """Reliability diagram en SVG inline (aucune dépendance)."""
    size, pad = 320, 36
    span = size - 2 * pad

    def x(p: float) -> float:
        return pad + p * span

    def y(p: float) -> float:
        return size - pad - p * span

    parts = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
             f'role="img" aria-label="Courbe de calibration">']
    parts.append(f'<rect x="{pad}" y="{pad}" width="{span}" height="{span}" '
                 'fill="none" stroke="#ccc"/>')
    # Diagonale = calibration parfaite
    parts.append(f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" '
                 'stroke="#999" stroke-dasharray="4 3"/>')
    pts = [(b["mean_predicted"], b["observed_rate"]) for b in bins
           if b["mean_predicted"] is not None]
    if pts:
        path = " ".join(f"{'M' if i == 0 else 'L'}{x(p):.1f},{y(o):.1f}"
                        for i, (p, o) in enumerate(pts))
        parts.append(f'<path d="{path}" fill="none" stroke="#1a7f37" stroke-width="2"/>')
        for p, o in pts:
            parts.append(f'<circle cx="{x(p):.1f}" cy="{y(o):.1f}" r="3.5" fill="#1a7f37"/>')
    for t in (0.0, 0.5, 1.0):
        parts.append(f'<text x="{x(t):.0f}" y="{size - pad + 16}" font-size="11" '
                     f'text-anchor="middle" fill="#555">{t:.1f}</text>')
        parts.append(f'<text x="{pad - 8}" y="{y(t) + 4:.0f}" font-size="11" '
                     f'text-anchor="end" fill="#555">{t:.1f}</text>')
    parts.append(f'<text x="{size / 2}" y="{size - 4}" font-size="11" '
                 'text-anchor="middle" fill="#333">probabilité prédite</text>')
    parts.append(f'<text x="12" y="{size / 2}" font-size="11" text-anchor="middle" '
                 f'fill="#333" transform="rotate(-90 12 {size / 2})">fréquence observée</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_html(report: Dict[str, Any]) -> str:
    core = report["core"]
    sig = report["signals"]
    prod = report["production"]
    roi = report["roi_theorique"]

    def metric_card(label: str, value: Any, note: str = "") -> str:
        return (f'<div class="card"><div class="v">{_esc(value)}</div>'
                f'<div class="l">{_esc(label)}</div>'
                + (f'<div class="n">{_esc(note)}</div>' if note else "") + "</div>")

    acc, acc_elo, base = core.get("accuracy"), core.get("accuracy_elo"), core.get("baseline")
    cards = "".join([
        metric_card("Accuracy features+ELO", acc_elo,
                    f"+{(acc_elo - base) * 100:.1f} pts vs baseline" if acc_elo and base else ""),
        metric_card("Accuracy features seul", acc),
        metric_card("Baseline (meilleur service)", base),
        metric_card("Log-loss (+ELO)", core.get("logloss_elo")),
        metric_card("Brier (+ELO)", core.get("brier_elo")),
        metric_card("Matchs test", core.get("n_test"), f"train : {core.get('n_train')}"),
    ])

    roi_rows = ""
    for src, r in roi.items():
        roi_rows += (f"<tr><td>{_esc(src)}</td><td>{r['n_bets']}</td>"
                     f"<td>{r['pnl_flat']}</td><td>{_esc(r['roi_pct'])}%</td>"
                     f"<td>{r['n_bets_confiants']}</td><td>{_esc(r['roi_confiants_pct'])}%</td></tr>")

    bins_rows = "".join(
        f"<tr><td>{b['range']}</td><td>{b['n']}</td>"
        f"<td>{_esc(b['mean_predicted'])}</td><td>{_esc(b['observed_rate'])}</td></tr>"
        for b in report["calibration_bins"])

    calib = sig.get("calibration", {})
    form = sig.get("form_signal", {})
    steam = sig.get("steam_move", {})

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TennisBoss — Rapport de backtest</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f6f8fa;color:#1f2328}}
main{{max-width:900px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:1.5em}} h2{{font-size:1.15em;margin-top:2em;border-bottom:1px solid #d1d9e0;padding-bottom:.3em}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.card{{background:#fff;border:1px solid #d1d9e0;border-radius:8px;padding:14px}}
.card .v{{font-size:1.5em;font-weight:600}} .card .l{{color:#59636e;font-size:.85em;margin-top:2px}}
.card .n{{color:#1a7f37;font-size:.8em;margin-top:4px}}
table{{border-collapse:collapse;background:#fff;width:100%;font-size:.9em}}
th,td{{border:1px solid #d1d9e0;padding:6px 10px;text-align:left}}
th{{background:#f6f8fa;font-weight:600}}
.verdict{{background:#fff8c5;border:1px solid #d4a72c66;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:.92em}}
.caveat{{color:#59636e;font-size:.85em;font-style:italic}}
.flex{{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start}}
svg{{background:#fff;border:1px solid #d1d9e0;border-radius:8px}}
footer{{margin-top:48px;color:#59636e;font-size:.8em}}
</style></head><body><main>
<h1>🎾 TennisBoss — Rapport de backtest</h1>
<p>Généré le {_esc(report['generated'])} · {report['n_matches_archive']} matchs en archive
· période {_esc(core.get('span'))} · tours : {_esc(core.get('tours'))}</p>

<h2>1. Backtest hors-échantillon (split chronologique, poids gelés)</h2>
<div class="cards">{cards}</div>
<p class="caveat">Protocole : entraînement sur les {core.get('n_train')} premiers matchs
(ordre chronologique strict, dates normalisées), poids gelés, évaluation sur les
{core.get('n_test')} suivants. Aucune fuite de données : profils et ELO mis à jour
match après match, jamais avant l'évaluation.</p>

<h2>2. Calibration (reliability diagram)</h2>
<div class="flex">
{_calibration_svg(report['calibration_bins'])}
<table><tr><th>Bin prédit</th><th>n</th><th>Prédit (moy.)</th><th>Observé</th></tr>{bins_rows}</table>
</div>
<p class="caveat">Plus la courbe verte colle à la diagonale, mieux le modèle est
calibré. Chaque match compte dans les deux orientations (vainqueur et perdant).</p>

<h2>3. ROI théorique (mise à plat 1u sur le favori du modèle)</h2>
<table><tr><th>Cotes</th><th>Paris</th><th>P&amp;L (u)</th><th>ROI</th>
<th>Paris «&nbsp;confiants&nbsp;» (p≥60%)</th><th>ROI confiants</th></tr>{roi_rows}</table>
<p class="caveat">Réglé aux cotes historiques tennis-data.co.uk (sous-ensemble des
matchs de test présents dans historical_odds). Le modèle prédit le 1er set, les
cotes portent sur le match : indicatif, pas une promesse. Aucun pari automatique.</p>

<h2>4. Signaux (walk-forward, données réglées réelles)</h2>
<h3>Calibration k / Platt</h3>
{_kv_table(calib, skip=('verdict',))}
<div class="verdict">{_esc(calib.get('verdict', calib.get('note', '—')))}</div>
<h3>form_signal</h3>
{_kv_table(form, skip=('verdict', 'caveat'))}
<div class="verdict">{_esc(form.get('verdict', '—'))}</div>
<p class="caveat">{_esc(form.get('caveat', ''))}</p>
<h3>steam_move</h3>
{_kv_table(steam, skip=('verdict',))}
<div class="verdict">{_esc(steam.get('verdict', steam.get('note', '—')))}</div>

<h2>5. Performance réelle en production</h2>
<h3>Picks value réglés</h3>
{_kv_table(prod['value_picks'])}
<h3>Picks in-play</h3>
{_kv_table(prod['inplay'])}
<h3>Closing Line Value (preuve d'edge)</h3>
{_kv_table(prod['clv'], skip=('verdict', 'verdict_label', 'note'))}
<div class="verdict">{_esc((prod['clv'] or {}).get('verdict_label', '—'))}</div>
<p class="caveat">La CLV (battre la cote de clôture) est la seule preuve
statistiquement sérieuse d'un edge durable. Tant qu'elle n'est pas positive sur un
échantillon suffisant, TennisBoss reste un outil d'aide à la décision, pas un
prédicteur «&nbsp;gagnant&nbsp;».</p>

<footer>TennisBoss · rapport généré par <code>python3 run.py backtest --full</code>
· backtest archivé en base (id={_esc(core.get('id', '—'))})</footer>
</main></body></html>"""


def generate(output_dir: str = REPORT_DIR) -> Tuple[str, Dict[str, Any]]:
    """Génère le rapport complet et l'écrit dans reports/backtest_report.html."""
    report = full_report()
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, REPORT_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(report))
    log(f"Rapport de backtest écrit -> {path}")
    return path, report
