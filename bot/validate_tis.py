"""Validation du Tennis Intelligence Score (Phase 12 consolidation).

Exécute compute_tis sur un échantillon de matchs archivés et vérifie :
  - bornes 0-100, cohérence catégories, formules EV / fair_odds / edge
  - tiers de recommandation alignés avec les seuils
  - distribution et outliers

Usage :
  python run.py validate-tis --limit 200
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from . import db, match_intelligence, memory


REPORT_DIR = "reports"
REPORT_FILE = "tis_validation.md"


def _sample_pairs(limit: int = 200) -> List[Tuple[str, str, Optional[str]]]:
    """Paires joueur1/joueur2/surface depuis l'archive (matchs récents)."""
    mem = memory.load()
    known = set(mem.get("players") or {})
    if not known:
        return []

    with db.connect() as c:
        rows = c.execute(
            "SELECT winner, loser, surface FROM matches "
            "WHERE winner IS NOT NULL AND loser IS NOT NULL "
            "ORDER BY REPLACE(date,'-','') DESC, id DESC LIMIT ?",
            (max(limit * 3, limit),),
        ).fetchall()

    pairs: List[Tuple[str, str, Optional[str]]] = []
    seen: set = set()
    for r in rows:
        w, l = r["winner"], r["loser"]
        if w not in known or l not in known:
            continue
        key = tuple(sorted((w, l)))
        if key in seen:
            continue
        seen.add(key)
        surf = (r["surface"] or "").strip().lower() or None
        if surf and surf not in ("hard", "clay", "grass"):
            surf = "hard"
        pairs.append((w, l, surf))
        if len(pairs) >= limit:
            break
    return pairs


def sanity_check(result: Dict[str, Any], odds_data: Optional[Dict[str, Any]] = None) -> List[str]:
    """Retourne la liste des anomalies détectées sur un résultat TIS."""
    issues: List[str] = []
    tis = float(result.get("tis", -1))
    if not 0 <= tis <= 100:
        issues.append(f"tis hors bornes: {tis}")

    cats = result.get("categories") or {}
    cat_sum = float(cats.get("player", 0)) + float(cats.get("surface", 0)) + float(cats.get("market", 0))
    if abs(cat_sum - tis) > 0.25:
        issues.append(f"sum(categories)={cat_sum:.2f} != tis={tis:.2f}")

    prob = float(result.get("model_prob") or 0)
    fair = result.get("fair_odds")
    if prob > 0 and fair is not None:
        expected_fair = round(1.0 / prob, 2)
        if abs(float(fair) - expected_fair) > 0.02:
            issues.append(f"fair_odds={fair} != 1/prob={expected_fair}")

    risk = float(result.get("risk_score", -1))
    if not 0 <= risk <= 100:
        issues.append(f"risk_score hors bornes: {risk}")

    rec = result.get("recommendation")
    if rec not in ("STRONG_BET", "VALUE_BET", "WATCH", "NO_BET"):
        issues.append(f"recommendation invalide: {rec}")

    ev_pct = float(result.get("ev_pct") or 0)
    edge = float(result.get("edge_pct") or 0)
    if odds_data:
        fav = result.get("favorite")
        p1 = result.get("_p1")  # injected by runner
        p2 = result.get("_p2")
        if fav and p1 and p2:
            odds = float(
                odds_data.get("home_odds" if fav == p1 else "away_odds") or 0
            )
            if odds > 1.0 and prob > 0:
                expected_ev = round((prob * odds - 1.0) * 100.0, 1)
                if abs(ev_pct - expected_ev) > 0.15:
                    issues.append(f"ev_pct={ev_pct} != attendu {expected_ev}")
                implied = 1.0 / odds
                expected_edge = round((prob - implied) * 100.0, 1)
                if abs(edge - expected_edge) > 0.15:
                    issues.append(f"edge_pct={edge} != attendu {expected_edge}")

    # Cohérence tier vs seuils
    if rec == "STRONG_BET" and (tis < match_intelligence.TIER_STRONG_TIS or ev_pct < match_intelligence.TIER_STRONG_EV):
        if odds_data:
            issues.append("STRONG_BET mais sous les seuils TIS/EV")
    if rec == "VALUE_BET" and (tis < match_intelligence.TIER_VALUE_TIS or ev_pct < match_intelligence.TIER_VALUE_EV):
        if odds_data:
            issues.append("VALUE_BET mais sous les seuils TIS/EV")

    return issues


def run_validation(limit: int = 200, *, write_report: bool = True) -> Dict[str, Any]:
    """Valide TIS sur `limit` paires et produit un rapport."""
    db.init()
    mem = memory.load()
    pairs = _sample_pairs(limit)
    if not pairs:
        return {"error": "Aucune paire éligible (archive vide ou joueurs inconnus).", "n": 0}

    results: List[Dict[str, Any]] = []
    all_issues: List[str] = []
    tier_counts: Counter = Counter()
    tis_values: List[float] = []

    for p1, p2, surf in pairs:
        try:
            r = match_intelligence.compute_tis(p1, p2, surface=surf, mem=mem)
        except Exception as exc:  # noqa: BLE001
            all_issues.append(f"{p1} vs {p2}: exception {exc}")
            continue
        r["_p1"] = p1
        r["_p2"] = p2
        issues = sanity_check(r)
        # Avec cotes synthétiques pour tester les formules EV
        synth_odds = {"home_odds": 1.90, "away_odds": 2.05}
        fav = r.get("favorite")
        if fav == p1:
            synth_odds = {"home_odds": 2.20, "away_odds": 1.75}
        try:
            r_odds = match_intelligence.compute_tis(
                p1, p2, surface=surf, odds_data=synth_odds, mem=mem,
            )
            r_odds["_p1"] = p1
            r_odds["_p2"] = p2
            issues.extend(sanity_check(r_odds, synth_odds))
        except Exception:
            pass

        tier_counts[r["recommendation"]] += 1
        tis_values.append(float(r["tis"]))
        if issues:
            all_issues.extend([f"{p1} vs {p2}: {i}" for i in issues])
        results.append({
            "player1": p1, "player2": p2, "surface": surf,
            "tis": r["tis"], "recommendation": r["recommendation"],
            "model_prob": r.get("model_prob"), "ev_pct": r.get("ev_pct"),
            "issues": issues,
        })

    n = len(results)
    tis_sorted = sorted(tis_values)
    summary = {
        "n_requested": limit,
        "n_evaluated": n,
        "n_issues": len(all_issues),
        "tier_distribution": dict(tier_counts),
        "tis_min": round(min(tis_values), 1) if tis_values else None,
        "tis_max": round(max(tis_values), 1) if tis_values else None,
        "tis_median": round(tis_sorted[n // 2], 1) if tis_values else None,
        "tis_mean": round(sum(tis_values) / n, 1) if tis_values else None,
        "sample_issues": all_issues[:20],
        "sample_rows": results[:15],
    }

    if write_report:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, REPORT_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(summary))
        summary["report_path"] = path

    return summary


def render_markdown(summary: Dict[str, Any]) -> str:
    """Génère reports/tis_validation.md."""
    lines = [
        "# Validation Tennis Intelligence Score (TIS)",
        "",
        f"- Matchs évalués : **{summary.get('n_evaluated', 0)}** / {summary.get('n_requested', 0)}",
        f"- Anomalies détectées : **{summary.get('n_issues', 0)}**",
        "",
        "## Distribution TIS",
        "",
        f"| Stat | Valeur |",
        f"|------|--------|",
        f"| Min | {summary.get('tis_min')} |",
        f"| Max | {summary.get('tis_max')} |",
        f"| Médiane | {summary.get('tis_median')} |",
        f"| Moyenne | {summary.get('tis_mean')} |",
        "",
        "## Tiers de recommandation",
        "",
    ]
    for tier, cnt in sorted((summary.get("tier_distribution") or {}).items()):
        lines.append(f"- **{tier}** : {cnt}")
    lines.extend(["", "## Anomalies (échantillon)", ""])
    for issue in summary.get("sample_issues") or []:
        lines.append(f"- {issue}")
    if not summary.get("sample_issues"):
        lines.append("- Aucune anomalie sur l'échantillon.")
    lines.extend(["", "## Exemples de matchs", ""])
    lines.append("| Match | Surface | TIS | Tier | prob |")
    lines.append("|-------|---------|-----|------|------|")
    for row in summary.get("sample_rows") or []:
        p1 = row["player1"].split()[-1]
        p2 = row["player2"].split()[-1]
        lines.append(
            f"| {p1} vs {p2} | {row.get('surface') or '?'} | {row['tis']} | "
            f"{row['recommendation']} | {row.get('model_prob')} |"
        )
    lines.append("")
    return "\n".join(lines)
