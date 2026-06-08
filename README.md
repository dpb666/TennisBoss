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
python3 run.py train --years 2022 2023 2024 --tours atp wta   # apprentissage (H+F)
python3 run.py predict "Jannik Sinner" "Daniil Medvedev"
python3 run.py players --tour wta --limit 20                  # dictionnaire + probas
python3 run.py players --export players.csv                   # export CSV complet
python3 run.py backtest --years 2022 2023 2024 --tours atp wta   # backtest archivé
python3 run.py db                              # contenu base + derniers backtests
python3 run.py serve --host 0.0.0.0 --port 8000  # API REST (backend Android)
python3 run.py status                          # poids appris, précision, top joueurs
python3 run.py start                           # MODE AUTONOME (boucle infinie)
python3 run.py reset [--all]                   # efface le modèle (--all = + la base)
```

## API REST pour l'app Android

`python3 run.py serve` expose une API JSON (Flask) : `/health`, `/api/status`,
`/api/players` (autocomplete), `/api/predict`, `/api/upcoming`, `/api/value`.
CORS ouvert ; auth optionnelle via `TENNISBOSS_API_TOKEN` (en-tête `X-API-Token`).
**Guide d'intégration : [ANDROID.md](ANDROID.md).**

### App Android (Kotlin + Compose)
Un squelette d'app Android prêt à ouvrir dans Android Studio est dans
**[`android/`](android/README.md)** : écran de prédiction du 1er set qui appelle
l'API (Retrofit + Compose + ViewModel).

## Base de données solide, dictionnaire & backtests

Tout est stocké dans une base **SQLite** (`state/tennisboss.db`, sans dépendance) :

| Table | Contenu |
|---|---|
| `players` | dictionnaire de **tous** les joueurs ATP+WTA, avec `win_prob` (proba de battre un adversaire moyen), `rating`, profils service/retour/forme |
| `matches` | archive de tous les matchs exploités (pour rejouer / backtester) |
| `predictions` | historique des prédictions demandées |
| `backtests` | **archive des campagnes de backtest** (accuracy, log-loss, brier, baseline) |

Le **backtest** est honnête (hors-échantillon, sans fuite) : il apprend sur la 1re
partie chronologique, **gèle les poids**, puis évalue sur la partie finale.
Exemple obtenu (ATP+WTA 2022-2024, 1117 joueurs) : accuracy **0,614** vs baseline
service **0,611** — le modèle bat la baseline, et le backtest est archivé en base.

## Matchs à venir en live (API-Tennis)

Le bot prédit le 1er set des **vrais matchs à venir** via **API-Tennis** :

```bash
python3 run.py upcoming --days 2          # fixtures réelles + prédiction 1er set
python3 run.py upcoming --days 2 --odds   # + cotes marché (odds-api.io) quand appariées
```

Avec `--odds`, chaque match est apparié à odds-api.io par **paire de noms de
famille** ; l'appariement n'affiche les cotes que si les **deux** joueurs
correspondent (sinon « introuvable » — les fournisseurs ont parfois des affiches
différentes le même jour). Pour une couverture cotes maximale, voir `value`.

Les noms abrégés de l'API ("A. Zverev") sont automatiquement reliés aux profils
appris ("Alexander Zverev") par `bot/namematch.py`.

### Cotes & comparaison au marché (odds-api.io)

```bash
python3 run.py value --limit 10     # modèle 1er set vs cotes marché (no-vig)
```

Source : **odds-api.io** (`bot/odds_api.py`, base `https://api.odds-api.io/v3`,
auth `apiKey`). Le plan actuel autorise **2 bookmakers** (MelBet, Betfair
Exchange) qui exposent le marché **ML = vainqueur du match**. Les probabilités
implicites sont calculées **sans la marge** (no-vig).

> ⚠️ **Marchés différents** : notre modèle prédit le **1er set**, le marché donne
> le **match**. Gagner un set est plus aléatoire → le favori y est mécaniquement
> moins marqué. La commande `value` est une **comparaison indicative**, pas un
> signal de pari. Le marché "First Set Winner" exigerait un bookmaker/plan le
> proposant.

### Clés API — fichier `.env` (jamais commité)
Les clés vivent dans `TennisBoss/.env` (exclu de git) :
```
AT_API_KEY=...      # API-Tennis   (ACTIF : fixtures + live)
ODDS_API_KEY=...    # odds-api.io  (ACTIF : cotes vainqueur de match, no-vig)
SR_KEY=...          # Sportradar   (INACTIF : HTTP 429 quota/produit -> dashboard)
```
⚠️ Ne jamais committer `.env`. Régénérer toute clé ayant transité en clair.

> **Paris** : TennisBoss prédit et lit des cotes, mais **ne place aucun pari
> automatiquement** (aucune exécution d'ordres financiers ; clé Stake non utilisée).

## Sources de données : ouvertes et légales (aucun contournement)

Les données proviennent des datasets **ouverts** de Jeff Sackmann (ATP + WTA) et
de votre future API officielle. TennisBoss **ne contourne aucune protection
anti-bot** de site tiers : ce n'est ni nécessaire ni souhaitable.

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
