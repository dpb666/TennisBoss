"""Construction de la matrice de features à partir de la base SQLite.

Sources :
  - matches          : archive chronologique (serve/return/forme via walk-forward)
  - historical_odds  : cotes marché tennis-data.co.uk (implied prob)
  - market_snapshots : mouvement de ligne live (optionnel, souvent sparse)
  - memory.json      : rankings moyens (optionnel, via tennisdata_feeder)

Aucune connexion au prédicteur de production.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bot import config, db

from . import features as feat


@dataclass
class Dataset:
    """Jeu de features hors-ligne prêt pour train/evaluate."""

    rows: List[Dict[str, Any]]
    feature_names: List[str] = field(default_factory=lambda: list(feat.FEATURE_NAMES))
    train_rows: List[Dict[str, Any]] = field(default_factory=list)
    test_rows: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_train(self) -> int:
        return len(self.train_rows)

    @property
    def n_test(self) -> int:
        return len(self.test_rows)

    def matrix(self, split: str = "all") -> tuple:
        """Renvoie (X, y, feature_names) pour 'all', 'train' ou 'test'."""
        if split == "train":
            source = self.train_rows
        elif split == "test":
            source = self.test_rows
        else:
            source = self.rows
        return feat.rows_to_matrix(source, self.feature_names)


def _compact_date(date_str: str) -> str:
    return str(date_str or "").replace("-", "")


def _load_line_moves() -> Dict[str, Dict[str, Any]]:
    """Index event_key -> mouvement de ligne (market_snapshots)."""
    moves: Dict[str, Dict[str, Any]] = {}
    try:
        with db.connect() as conn:
            keys = conn.execute(
                "SELECT DISTINCT event_key FROM market_snapshots WHERE event_key IS NOT NULL"
            ).fetchall()
        for row in keys:
            ek = row["event_key"]
            mv = db.line_movement(ek)
            if mv:
                moves[ek] = mv
    except Exception:
        pass
    return moves


def _settled_event_index() -> Dict[tuple, str]:
    """(date_compact, p1_lower, p2_lower) -> event_key pour joindre snapshots."""
    index: Dict[tuple, str] = {}
    try:
        for row in db.list_settled(limit=200_000):
            ek = row["event_key"]
            if not ek:
                continue
            p1 = (row["player1"] or "").lower()
            p2 = (row["player2"] or "").lower()
            d = _compact_date(row["date"] or "")
            if p1 and p2 and d:
                key = (d, min(p1, p2), max(p1, p2))
                index[key] = ek
    except Exception:
        pass
    return index


def build_dataset(
    test_fraction: Optional[float] = None,
    min_matches: int = 10,
    mem: Optional[Dict[str, Any]] = None,
) -> Dataset:
    """Construit le dataset walk-forward (features calculées AVANT chaque match).

    Parameters
    ----------
    test_fraction : float, optional
        Fraction finale réservée au hold-out (défaut : config.backtest_test_fraction).
    min_matches : int
        Minimum de matchs requis ; lève ValueError sinon.
    mem : dict, optional
        Mémoire pré-chargée pour les rankings ; sinon chargée depuis memory.json.

    Returns
    -------
    Dataset
        rows (tous), train_rows, test_rows, meta (compteurs, couverture odds/rank).
    """
    matches = db.matches_for_backtest()
    if len(matches) < min_matches:
        raise ValueError(
            f"Pas assez de matchs pour ML prep ({len(matches)} < {min_matches})."
        )

    frac = test_fraction if test_fraction is not None else config.DEFAULT_CONFIG.get(
        "backtest_test_fraction", 0.25
    )
    split = int(len(matches) * (1 - frac))
    train_matches, test_matches = matches[:split], matches[split:]

    odds_index = db.historical_odds_index()
    line_moves = _load_line_moves()
    settled_events = _settled_event_index()
    rankings = feat.load_rankings(mem)

    mem_state: Dict[str, Any] = {"players": {}}
    alpha = config.DEFAULT_CONFIG.get("ema_alpha", 0.20)
    elo_ratings, elo_surface, elo_n, elo_surf_n = feat.init_elo_state()

    rows: List[Dict[str, Any]] = []
    n_with_odds = n_with_rank = n_with_move = 0

    for i, match in enumerate(matches):
        w, l = match["winner_name"], match["loser_name"]
        p1, p2, _ = feat.orient_players(w, l)
        dkey = _compact_date(match.get("date") or "")
        ek = settled_events.get((dkey, min(p1.lower(), p2.lower()), max(p1.lower(), p2.lower())))

        row = feat.build_feature_row(
            match,
            mem_state,
            elo_ratings,
            elo_surface,
            rankings,
            odds_index,
            line_moves,
            event_key=ek,
        )
        row["split"] = "train" if i < split else "test"
        rows.append(row)

        if row.get("odds_implied_p1") is not None:
            n_with_odds += 1
        if row.get("ranking_diff") is not None:
            n_with_rank += 1
        if row.get("odds_move_home_pct") is not None:
            n_with_move += 1

        feat.update_profile_state(mem_state, match, alpha)
        feat.update_elo_state(match, elo_ratings, elo_surface, elo_n, elo_surf_n)

    train_rows = [r for r in rows if r["split"] == "train"]
    test_rows = [r for r in rows if r["split"] == "test"]

    meta = {
        "n_matches": len(matches),
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "test_fraction": frac,
        "n_with_historical_odds": n_with_odds,
        "n_with_ranking": n_with_rank,
        "n_with_line_movement": n_with_move,
        "odds_coverage_pct": round(100.0 * n_with_odds / max(len(rows), 1), 2),
        "ranking_coverage_pct": round(100.0 * n_with_rank / max(len(rows), 1), 2),
        "movement_coverage_pct": round(100.0 * n_with_move / max(len(rows), 1), 2),
        "needs_from_agent4": _agent4_gaps(n_with_odds, n_with_rank, n_with_move, len(rows)),
    }

    return Dataset(
        rows=rows,
        train_rows=train_rows,
        test_rows=test_rows,
        meta=meta,
    )


def _agent4_gaps(n_odds: int, n_rank: int, n_move: int, total: int) -> List[str]:
    """Liste ce qui manque encore côté données (Agent 4)."""
    gaps: List[str] = []
    if total and n_rank / total < 0.1:
        gaps.append(
            "rankings en base (table dédiée ou enrichissement players) — "
            "actuellement memory.json uniquement"
        )
    if total and n_odds / total < 0.1:
        gaps.append(
            "historical_odds — lancer tennisdata_feeder ingest pour ATP/WTA 2022+"
        )
    if total and n_move / total < 0.05:
        gaps.append(
            "market_snapshots — le scanner live doit capturer des lignes "
            "sur settled_matches pour odds_move_*"
        )
    return gaps
