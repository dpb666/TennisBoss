# Market Efficiency Audit — le modèle apporte-t-il une info indépendante du marché ?

**Date :** 15 juillet 2026
**Module :** `bot/market_efficiency_audit.py` (lecture seule, aucune écriture DB)
**Tests :** `tests/test_market_efficiency_audit.py` (10 tests, mécanique/garde-fous)
**Règle appliquée :** rejeter toute hypothèse non confirmée par la donnée ;
aucune modification de `predictor.predict()`, `/api/value` ou logique de
production.

---

## 0. Résumé exécutif

Le modèle **n'apporte pas d'information indépendante mesurable** au-delà de
ce que le marché price déjà — et ce **n'est pas** un artefact de
calibration, de fuite ou de redondance de features : c'est un résultat
robuste, confirmé à 3 niveaux de calibration et sur une courbe log-loss
strictement monotone. En revanche, l'hypothèse précédemment évoquée
("la confiance ≥75% a le pire CLV") **n'est plus confirmée sur les données
actuelles** — elle doit être considérée comme du bruit d'échantillonnage
(n=97) et non comme un fait établi. La cause principale de la sous-performance
n'est donc pas un biais de confiance identifiable, mais l'absence de
contenu informationnel du modèle lui-même, concentrée précisément là où il
diverge le plus du marché.

---

## 1. Audit de `market_blend_w = 0.00`

**Question :** l'optimisation converge-t-elle à 0 à cause d'une
sur-régularisation, d'une fuite, d'un artefact de calibration ou d'une
redondance de features — ou est-ce un résultat réel ?

**Méthode :** `fit_market_blend()` reproduit à 3 niveaux de calibration du
modèle (brut k=1.0 ; calibration actuellement en prod k=0.21 ; calibration
re-fittée sur les données du jour, k=0.21 identique) sur n=687 échantillons
(jointure `settled_matches` × `bet_log`, la population disponible la plus
large pour ce test — bien plus robuste que l'échantillon CLV de 97 paris).

| Calibration | Log-loss modèle | Log-loss marché | w optimal |
|---|---|---|---|
| Brut (k=1.0) | 0.9678 | 0.4693 | **0.00** |
| Prod actuelle (k=0.21) | 0.6855 | 0.4693 | **0.00** |
| Re-fit du jour (k=0.21) | 0.6855 | 0.4693 | **0.00** |

**Sur-régularisation / artefact de grille :** rejeté. La courbe complète
log-loss(w) pour w∈[0,1] (pas 0.05) est **strictement croissante** — pas de
minimum local, pas de plateau, un vrai optimum au bord w=0.

**Calibration :** rejeté comme cause. Calibrer le modèle (k=1.0→0.21)
réduit bien sa log-loss (0.968→0.686, gain réel) mais le marché reste
**46% meilleur** même après ce correctif — la calibration corrige la
confiance, pas le contenu informationnel manquant.

**Redondance de features :** rejeté. Corrélation modèle/marché = **0.11**
(faible) — le modèle n'est pas une copie du marché déguisée. Le modèle et
le marché ne sont d'accord sur le favori que **66.7%** du temps : il y a un
désaccord réel et fréquent, pas une redondance.

**Fuite :** aucune fuite possible dans ce test — `p_marché` et `p_modèle`
sont tous deux mesurés AVANT le résultat (cote captée au pick, prédiction
enregistrée au moment du pari), et `market_blend_samples()` oriente les deux
probabilités sur la même référence (le favori du marché), donc pas de biais
d'appariement.

**Conclusion tâche 1 :** `w=0` est un résultat **réel**, pas un artefact.
Le modèle (dominé à 96.7% par l'ELO, cf. `predictor.ELO_BLEND`) porte une
information non-triviale mais **trop faible et trop bruitée** pour ajouter
de la valeur à un marché déjà très efficient sur ce sport.

---

## 2. Efficience de marché par bucket de désaccord

**Question :** même si le modèle perd globalement, existe-t-il des
segments où il bat le marché ?

| Désaccord \|p_modèle − p_marché\| | n | Brier modèle | Brier marché | Modèle meilleur ? |
|---|---|---|---|---|
| 0.00–0.05 | 78 | 0.238 | 0.236 | Non (quasi égalité) |
| 0.05–0.10 | 77 | 0.270 | 0.274 | **Oui** (marginal) |
| 0.10–0.20 | 156 | 0.225 | 0.203 | Non |
| 0.20–1.00 | 376 (55% du total) | 0.252 | **0.094** | Non — écart massif |

**Constat clé :** dans le bucket de plus fort désaccord (Δ≥0.20, qui
représente plus de la moitié de l'échantillon), le marché a un Brier
**2.7× meilleur** que le modèle. C'est exactement l'inverse de ce qu'on
voudrait : le modèle est le moins fiable précisément là où il s'écarte le
plus du marché — c'est-à-dire là où il serait le plus tentant de parier
dessus (grosse divergence = gros edge apparent).

Le seul bucket où le modèle bat marginalement le marché (0.05-0.10, n=77)
est une quasi-égalité (0.270 vs 0.274) sur un échantillon modeste — pas une
niche exploitable de façon fiable.

**Conclusion tâche 2 :** le modèle ne surperforme le marché dans aucun
segment de désaccord significatif. La zone de plus grand désaccord est
aussi la zone de plus grande erreur du modèle.

---

## 3. Investigation CLV par palier de confiance

**Question posée :** pourquoi les prédictions ≥75% de confiance ont-elles
le pire CLV ?

**Réponse honnête : cette prémisse n'est plus supportée par les données
actuelles.** Sur l'échantillon actuel (n=97 paris réglés, contre ~94 lors
du constat initial), le classement par palier n'est **pas monotone** :

| Confiance | n | Win rate | IC95 | ROI flat |
|---|---|---|---|---|
| 0–60% | 9 | 33.3% | ±30.8pt | −5.4% |
| 60–75% | 54 | 33.3% | ±12.6pt | −3.9% |
| **75–85%** | 19 | 21.1% | ±18.3pt | **−33.1%** (pire) |
| **85%+** | 15 | 40.0% | ±24.8pt | **+52.4%** (meilleur) |

Le palier ≥75% agrégé (n=34) : win rate 29.4% (IC95 ±15.3pt) vs <75%
(n=63) : win rate 33.3% (IC95 ±11.6pt) — **les IC se chevauchent
largement**. Le palier le plus haut (85%+) a en fait le **meilleur** ROI de
tous les paliers, et c'est le palier intermédiaire (75-85%) qui est le
pire — pas une dégradation progressive avec la confiance.

**Diagnostic :** avec n=15-19 par palier extrême, une seule série de 3-4
paris perdus ou gagnés fait basculer le ROI de ±30 points. C'est un signal
de **bruit d'échantillonnage**, pas un biais de confiance systématique. Le
constat antérieur ("−6.9% vs −1.3%") reflétait probablement un instantané
plus ancien et/ou pré-filtre (avant le durcissement du 2026-07-03) — il ne
se reproduit pas sur les données actuelles.

**Conclusion tâche 3 :** hypothèse **REJETÉE** telle que formulée. Aucune
sur-confiance systématique détectable au niveau confiance→CLV avec ce
volume de données. Ne pas construire de correctif (ex. plafond de mise
au-delà de 75%) sur la base de ce chiffre — il ne résiste pas à
l'examen. Ce qui reste vrai et solidement établi (tâche 1/2, n=687) est la
sous-performance globale du modèle vs marché, indépendamment de la
confiance affichée.

---

## 4. Audit des value bets : EV prédite vs réalisée

**Question :** les pertes viennent-elles d'une mauvaise estimation de
PROBABILITÉ ou de VALEUR (EV) ?

| EV prédite | n | p̄ prédite | Win rate réalisé | Écart (surconf. si +) | ROI réalisé |
|---|---|---|---|---|---|
| 0–5% | 26 | 41.8% | 26.9% | **+14.9pt** | −33.1% |
| 5–10% | 28 | 36.3% | 39.3% | −3.0pt | +19.8% |
| 10–20% | 24 | 37.2% | 33.3% | +3.9pt | +5.2% |
| 20%+ | 17 | 35.9% | 29.4% | +6.4pt | +16.5% |

**Constat clé :** l'écart le plus large entre probabilité prédite et
réalisée (+14.9 points, une vraie surconfiance) est concentré dans le
bucket EV **marginale (0-5%)** — exactement les paris les plus proches du
seuil de décision, et c'est aussi le seul bucket avec un ROI nettement
négatif (−33.1%). Les buckets à EV plus élevée (>5%) ont un écart de
probabilité beaucoup plus faible (−3 à +6.4pt, dans le bruit) et un ROI
positif malgré une forte volatilité (petit n).

**Conclusion tâche 4 :** les pertes ne viennent **pas** d'un calcul d'EV
structurellement erroné (la formule EV = p·cote−1 est correcte et le
classement des buckets EV est cohérent), mais d'une **estimation de
probabilité trop optimiste concentrée sur les picks à faible marge** — ce
sont des paris qui n'auraient jamais dû franchir le seuil de mise si le
modèle était mieux calibré sur ce segment précis. C'est cohérent avec le
Platt `a=0.21` (surconfiance globale) déjà documenté, mais montre que son
impact concret sur le ROI est concentré sur la marge, pas uniforme.

---

## 5. Segmentation

**Limite de données assumée en amont :** `bet_history`/`clv_log` ne
capturent NI le niveau de tournoi NI l'écart de classement au moment du
pick. Le classement actuel des joueurs n'est pas point-in-time (il a
changé depuis), donc l'utiliser rétroactivement serait trompeur — ces deux
axes ne sont **pas** segmentés ici avec des chiffres inventés ; c'est un
vrai trou d'instrumentation (voir §6, recommandation de fix).

| Segment | n | Win rate | ROI flat |
|---|---|---|---|
| **Surface** hard | 8 | 12.5% | −76.1% |
| clay | 16 | 25.0% | −20.9% |
| grass | 38 | 28.9% | −11.5% |
| inconnue (36% des lignes !) | 35 | 42.9% | +36.5% |
| **Favori/outsider modèle** favori (p≥0.5) | 11 | 36.4% | −29.9% |
| outsider (p<0.5) | 86 | 31.4% | +2.7% |
| **Cotes** 1.0–1.8 | 3 | 33.3% | −41.7% |
| 1.8–2.5 | 23 | 34.8% | −22.1% |
| 2.5–4.0 | 42 | 31.0% | −11.0% |
| 4.0+ | 29 | 31.0% | +34.3% |
| **Confiance** (cf. §3) | — | — | — |
| Tournoi | non instrumenté | — | — |
| Écart classement | non instrumenté | — | — |

**Constat de qualité de données :** 36% des lignes de `bet_history` n'ont
**pas de surface renseignée** — un vrai problème de complétude qui limite
la fiabilité de la segmentation surface elle-même (le sous-groupe "inconnu"
est justement celui avec le meilleur ROI apparent, un artefact probable de
sélection plutôt qu'un effet réel).

**Toutes ces cellules ont n<45, la plupart n<30** — aucune n'est
statistiquement exploitable individuellement. Elles sont rapportées comme
pistes exploratoires, pas comme conclusions.

---

## 6. Rapport final

### Causes racines, classées par force de preuve

1. **Le modèle n'a pas assez de contenu informationnel propre face au
   marché** (preuve la plus solide : n=687, courbe monotone, 3 niveaux de
   calibration testés, corrélation faible mais brier 2-3× pire). C'est la
   cause structurelle principale.
2. **Le modèle est structurellement le moins fiable exactement là où il
   diverge le plus du marché** (n=687, bucket Δ≥0.20 = 55% du volume,
   Brier 2.7× pire que le marché). C'est la cause qui rend le problème #1
   dangereux plutôt qu'anodin : le modèle inspire le plus confiance
   justement quand il a le plus tort.
3. **Surconfiance résiduelle concentrée sur les picks à EV marginale**
   (n=97, mais direction cohérente avec Platt a=0.21 déjà validé sur
   n=5015) — cause secondaire, plus petite mais réelle et actionnable
   (seuil EV).
4. **Trou d'instrumentation** (tournoi, ranking-diff, 36% de surfaces
   manquantes) — pas une cause de perte en soi, mais empêche de diagnostiquer
   plus finement les causes #1-3 à l'avenir.

### Hypothèse explicitement REJETÉE (non supportée par la donnée)

- **"La confiance ≥75% a le pire CLV/ROI"** — non confirmée sur n=97 actuel
  (IC se chevauchent, classement non monotone, palier 85%+ a le MEILLEUR
  ROI). Ne pas construire de correctif dessus.

### Recommandations classées par ROI attendu

1. **(ROI élevé, effort faible) Resserrer le seuil d'EV minimum pour
   déclencher un pick**, en particulier sur la zone 0-5% d'EV où la
   surconfiance est concentrée (tâche 4) — c'est le levier le plus direct
   et le moins risqué : ne pas parier sur les picks les plus marginaux
   plutôt que d'essayer de "réparer" leur probabilité.
2. **(ROI élevé, effort moyen) Réduire le poids du modèle propre dans les
   cas de fort désaccord avec le marché** (Δ≥0.20) — c'est là que le
   modèle a le plus tort ; un mécanisme qui rabaisse la confiance affichée
   (pas le calcul d'EV) quand le désaccord est extrême limiterait le risque
   sans nécessiter un nouveau modèle. À valider par un backtest walk-forward
   dédié avant tout déploiement, même expérimental — même discipline que le
   rejet du blend clutch.
3. **(ROI incertain mais fondation nécessaire, effort faible) Instrumenter
   `bet_history`/`clv_log`** : ajouter `tournament_level`, `ranking_diff`
   (capturé AU MOMENT du pick, pas recalculé après coup) et corriger la
   complétude `surface` (36% manquant). Sans ça, tout futur audit
   segmentation restera aussi peu concluant que celui-ci.
4. **(ROI incertain, effort élevé) Continuer à accumuler du volume**
   (bet_history, CLV) avant de tirer des conclusions définitives sur la
   confiance/segmentation — n=97 est structurellement insuffisant pour ces
   axes ; ce n'est pas un fix logiciel mais une contrainte de temps.

### Changements à NE PAS tenter

- **Ne pas** essayer de "réparer" la sur-confiance en gonflant le poids
  modèle dans le blend marché — c'est l'inverse de ce que montrent les
  données (tâche 1) : plus de poids modèle = pire log-loss, systématiquement.
- **Ne pas** construire un correctif spécifique au palier de confiance
  ≥75% (plafond de mise, décote automatique) — l'hypothèse sous-jacente
  n'est pas confirmée (tâche 3) ; un tel correctif serait du sur-ajustement
  au bruit d'un échantillon de 97 paris.
- **Ne pas** remplacer le predictor par un modèle plus complexe sans
  d'abord résoudre le trou d'instrumentation (#3 ci-dessus) — sans
  tournoi/ranking-diff/surface complets, on ne peut pas savoir si un nouveau
  modèle serait réellement meilleur ou juste sur-ajusté à un biais de
  sélection non détecté (cf. le rejet du blend clutch, même risque).
- **Ne pas** interpréter le ratio "outsider (+2.7% ROI) vs favori (−29.9%
  ROI)" comme une stratégie fiable — n=11 côté favori, bien trop petit.

### Production logic : doit-elle rester inchangée ?

**Oui.** Aucune preuve ici ne justifie de modifier `predictor.predict()`,
`/api/value` ou le blend marché actuel (`market_blend_w=0.00` reste
l'optimum mesuré). Les seuls changements recommandés (resserrement du
seuil EV, instrumentation) sont des ajustements de politique de décision
et de logging — pas des changements de logique de prédiction — et
nécessitent de toute façon leur propre validation avant tout déploiement,
conformément à la discipline déjà appliquée au signal clutch.
