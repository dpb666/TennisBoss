# ML Prep — Phase 12 (offline scaffold)

Package hors-ligne pour préparer et comparer des modèles ML sur l'archive
TennisBoss. **Ne modifie pas** `predictor.py` ni `/api/predict`.

## Modules

| Fichier | Rôle |
|---------|------|
| `features.py` | Features orientées p1−p2 : ranking, ELO, surface ELO, forme, serve/return, cotes |
| `dataset_builder.py` | Walk-forward sur `matches` + jointures `historical_odds` / `market_snapshots` |
| `train.py` | Comparaison LogisticRegression / RandomForest / XGBoost |
| `evaluate.py` | Accuracy, AUC, Brier, simulation ROI sur hold-out |

## Dépendances optionnelles

```bash
pip install scikit-learn xgboost
```

Sans elles, `build_dataset()` et les tests de forme fonctionnent ; `train_offline()`
lève une `ImportError` explicite.

## Usage

```python
from bot.ml_prep import build_dataset, train_offline

ds = build_dataset()
print(ds.meta)  # couverture odds / ranking / mouvement

report = train_offline(dataset=ds)
print(report["best_by_auc"], report["models"])
```

CLI :

```bash
python -m bot.ml_prep.train
```

## Sources de données

| Feature | Source actuelle | Couverture typique |
|---------|-----------------|-------------------|
| serve/return/form | `matches` (walk-forward EMA) | Haute (Sackmann) |
| elo_diff / surface_elo_diff | Rejoué depuis `matches` | Haute |
| ranking_diff | `memory.json` → `players[*].rank` | Faible sans ingest tennis-data |
| odds_implied_p1 | `historical_odds` (tennis-data.co.uk) | Moyenne si ingest fait |
| odds_move_* | `market_snapshots` × `settled_matches` | Faible (live scanner) |

## Ce qui manque (Agent 4)

Le champ `meta["needs_from_agent4"]` du dataset liste les lacunes détectées :

- **Rankings en DB** : aujourd'hui seulement dans `memory.json` après `tennisdata_feeder`
- **historical_odds** : nécessite `run.py ingest-tennisdata` (ATP/WTA 2022+)
- **market_snapshots** : nécessite le scanner live actif sur des matchs réglés

## Règles Phase 12

- Scaffold uniquement — pas de déploiement vers le prédicteur production
- Split chronologique (même fraction que `backtest_test_fraction`)
- Features calculées **avant** chaque match (pas de fuite)
- NaN → `0.5` (neutre) dans la matrice numérique

## Tests

```bash
python -m pytest tests/test_ml_prep_dataset.py -v
```
