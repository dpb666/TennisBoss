# 🎾 TennisBoss — bot autonome de prédiction (1er set)

Bot Python **autonome** et **auto-apprenant**, spécialisé tennis, inspiré de
l'approche « openclaw » : il tourne en continu, se répare tout seul, garde une
mémoire sur disque et s'améliore à partir de vraies données.

Il part de votre script `predict_first_set` (poids serve / return1 / return2 /
recent) et le transforme en système qui **apprend ces poids** sur des matchs réels.

## Les concepts demandés, et où ils sont

| Concept | Implémentation |
|---|---|
| **bootstrap** | `bot/bootstrap.py` — crée `state/`, `logs/`, `config.json` au 1er lancement |
| **heartbeat** | `bot/heartbeat.py` — battement de cœur périodique (preuve de vie) |
| **self-healing** | `bot/supervisor.py` — capture toute exception, sauvegarde, backoff exponentiel, repart ; `bot/memory.py` reconstruit une mémoire corrompue |
| **memory** | `bot/memory.py` — mémoire JSON persistante, écriture atomique |
| **self-learning** | `bot/learner.py` — régression logistique en ligne ; ajuste les poids match après match |
| **données live (internet)** | `bot/datasource.py` — dataset ATP (Jeff Sackmann), sans clé API ; tente le live Sofascore puis bascule (self-healing) |
| **spécialisé tennis** | features = service, retour 1re/2e balle, forme récente |

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

```bash
python3 run.py train --years 2022 2023 2024   # apprentissage sur 3 saisons réelles
python3 run.py predict "Jannik Sinner" "Daniil Medvedev"
python3 run.py status                          # poids appris, précision, top joueurs
python3 run.py start                           # MODE AUTONOME (boucle infinie)
python3 run.py reset                           # efface l'état appris
```

## Comment ça apprend (sans tricher)

Pour chaque match, dans l'ordre chronologique :
1. on lit les profils des 2 joueurs **avant** le match (pas de fuite de données) ;
2. l'ordre des joueurs est **randomisé** (sinon le modèle devinerait via l'ordre) ;
3. on prédit, on compare au résultat réel, on corrige les poids (gradient) ;
4. on met à jour les profils (moyenne exponentielle) avec la perf observée.

Précision obtenue : ~0,58 (incluant les matchs « à froid » où les joueurs sont
encore inconnus) — un niveau réaliste pour ce type de prédiction.

## Fichiers d'état (créés automatiquement)

```
state/memory.json   # poids appris, profils joueurs, métriques, matchs traités
state/config.json   # réglages (intervalles, années, learning rate...)
logs/tennisboss.log  # journal complet
```

## Étape suivante : l'interface Android

Le « cerveau » est volontairement séparé de l'interface. Deux chemins pour Android :

1. **API REST** (recommandé) : exposer `predict` via Flask/FastAPI sur un petit
   serveur, l'app Android appelle l'API. Le bot reste autonome côté serveur.
2. **Tout-en-un Kivy/Buildozer** : empaqueter ce code Python en APK.

Dans les deux cas, la seule fonction à appeler est `bot.predictor.predict(...)`
avec les profils issus de `bot.features.get_profile(...)`.
```python
from bot import memory, features, predictor
mem = memory.load()
f1 = features.feature_vector(features.get_profile(mem, "Jannik Sinner"))
f2 = features.feature_vector(features.get_profile(mem, "Daniil Medvedev"))
print(predictor.predict(mem, "Jannik Sinner", f1, "Daniil Medvedev", f2))
```
```
