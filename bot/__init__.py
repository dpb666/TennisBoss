"""TennisBoss — bot autonome de prédiction tennis (1er set).

Modules :
  config      : constantes et chemins
  bootstrap   : amorçage (dossiers + état par défaut)
  memory      : mémoire persistante (JSON atomique)
  datasource  : récupération des données live/historiques depuis internet
  features    : calcul des profils joueurs (serve / return / forme)
  predictor   : modèle de prédiction du 1er set
  learner     : self-learning (régression logistique en ligne)
  heartbeat   : battement de cœur
  supervisor  : boucle autonome + self-healing
"""

__version__ = "1.0.0"
