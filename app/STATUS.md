# Statut : désactivé (2026-07-11)

Ce module (`app/` — `analytics/`, `core/`, `risk/`, `trading/`) est un second
backend FastAPI indépendant (moteur de trading/risque : `auto_bet_engine`,
`hedge_manager`, `position_tracker`, `portfolio_greeks`, `correlation_matrix`,
`drawdown_alerts`...), lancé via `run.py quant` (service systemd
`tennisboss-quant`, port 8001).

Confirmé abandonné par l'utilisateur lors d'un audit du projet. Constaté avant
désactivation :
- Jamais appelé par l'app Android (qui ne parle qu'à `bot/api.py`, port 8000).
- Aucun test ne couvre ce module.
- Pas d'appel réseau sortant trouvé dans `auto_bet_engine.py` (pas de preuve
  qu'il exécute de vrais ordres), mais le module n'a pas été audité en détail.

Le service `tennisboss-quant` a été **stoppé et désactivé**
(`systemctl stop/disable tennisboss-quant`) — le code n'est pas supprimé,
au cas où il faille le reprendre. `bot/clv.py` importe encore
`app.trading.kelly_dynamic.kelly_fraction` (fonction pure, sans lien avec le
service FastAPI) — ce lien reste nécessaire, ne pas supprimer `app/trading/`
sans vérifier cet import en premier.

Voir `DEPLOYMENT.md` pour le détail infra.
