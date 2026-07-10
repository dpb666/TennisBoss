# Checklist Google Play — TennisBoss AI

Préparé le 10 juillet 2026. Contient des brouillons prêts à copier-coller dans
Play Console, basés sur une vérification réelle du code (pas des suppositions
génériques). Les décisions marquées **⚠️ À votre charge** sont légalement
engageantes — je donne une recommandation informée, la décision finale et la
responsabilité vous reviennent.

---

## 1. Data safety (Sécurité des données)

Formulaire Play Console : *Contenu de l'application → Sécurité des données*.

### Collecte de données — par catégorie

| Catégorie Play Console | Collectée ? | Détail |
|---|---|---|
| Position | Non | Aucune permission de localisation dans le manifest |
| Infos personnelles (nom, email, ID utilisateur...) | Non | Pas de compte, pas d'inscription |
| Infos financières | Non | Aucun paiement, aucune transaction |
| Santé et fitness | Non | — |
| Messages | **Oui** | Contenu des messages du chat IA (voir ci-dessous) |
| Photos et vidéos | Non | — |
| Fichiers et documents | **Oui** | Si l'utilisateur importe un PDF/CSV/TXT dans le chat |
| Contacts | Non | — |
| Activité dans l'app | **Oui** | Recherches de joueurs, interactions (non liées à une identité) |
| Navigation web | Non | — |
| Infos sur l'app et perf. | Non | Pas de SDK de crash/analytics (Firebase retiré) |
| Identifiants d'appareil | Non | Pas d'IDFA/AAID collecté |

### Pour chaque type "Oui", répondre ainsi dans le formulaire :

**Messages (contenu du chat)**
- Collectée : Oui
- Partagée avec un tiers : Oui — *fournisseur de traitement du langage (Groq
  Inc. ou API Google Gemini), uniquement pour générer la réponse à la question
  posée*
- Traitement éphémère (non stockée durablement) : Oui — aucune conservation
  server-side associée à un utilisateur identifiable
- Finalité : Fonctionnalité de l'app (pas publicité, pas analytics)
- Optionnelle ou obligatoire : Optionnelle (le chat est une fonctionnalité,
  pas un passage obligé)

**Fichiers et documents**
- Collectée : Oui, seulement si l'utilisateur choisit d'importer un fichier
- Partagée avec un tiers : Potentiellement, mêmes fournisseurs que ci-dessus,
  seulement pour répondre à la question posée sur ce fichier
- Traitement éphémère : Oui
- Finalité : Fonctionnalité de l'app
- Optionnelle : Oui

**Activité dans l'app (recherches de joueurs)**
- Collectée : Oui
- Partagée avec un tiers : Non
- Finalité : Fonctionnalité de l'app (générer la prédiction demandée)
- Optionnelle : Non (nécessaire au fonctionnement de base)

### Pratiques de sécurité à cocher
- ✅ Les données sont chiffrées en transit (HTTPS uniquement, cleartext
  désactivé en release — vérifié ce jour)
- ✅ Vous pouvez demander la suppression des données — cocher **"Non
  applicable"** ou expliquer qu'il n'y a pas de compte donc rien à supprimer
  côté serveur
- ⚠️ **À vérifier par vous** : cochez uniquement les cases correspondant à ce
  qui est vrai à la date de soumission (si vous ajoutez un compte utilisateur
  plus tard, ce formulaire devra être remis à jour)

---

## 2. Classification par contenu (questionnaire IARC)

Formulaire Play Console : *Contenu de l'application → Classification du contenu*.

### Point le plus important : la question sur le jeu d'argent/gambling

**Vérifié dans le code** : l'app affiche des cotes de bookmakers (Bet365,
Betfair, Pinnacle) **à titre purement informatif** — aucun bouton, aucun lien
(`Uri`/`Intent`), aucun mécanisme pour placer un pari, transférer de l'argent,
ou parier depuis l'app. Aucune monnaie virtuelle liée à un résultat.

**Recommandation** : répondre **Non** à :
- "L'application permet-elle de parier de l'argent réel ?"
- "L'application simule-t-elle des jeux d'argent (casino, paris) ?"

C'est cohérent avec des apps grand public qui affichent des cotes à titre
d'info (ex. apps de stats sportives) sans être classées "jeu d'argent".

⚠️ **À votre charge** : si vous ajoutez un jour un lien cliquable vers un
bookmaker ou un moyen de parier depuis l'app, cette classification devient
fausse et devra être refaite — les règles Google Play sur le gambling réel
sont strictes (certification par pays, âge minimum, etc.). Tant que l'app
reste un outil d'analyse pure (positionnement déjà décidé cette semaine),
cette réponse tient.

### Autres catégories du questionnaire
- Violence, contenu sexuel, langage grossier, drogues/alcool/tabac : **Non**
  à tout — rien de tel dans l'app
- Contenu généré par les utilisateurs partagé publiquement : **Non** — le
  chat n'est pas un espace public/partagé entre utilisateurs
- Interactions entre utilisateurs (chat, multijoueur) : **Non** — le chat est
  un assistant IA, pas une messagerie entre personnes

Résultat attendu : classification **"Tout public" / PEGI 3** ou équivalent
selon le territoire.

---

## 3. Fiche store (Store listing)

### Titre de l'app (30 caractères max)
```
TennisBoss AI
```

### Description courte (80 caractères max)
```
Analyse tennis par IA : ELO, forme, H2H, value — aide à la décision
```

### Description complète (4000 caractères max)

```
TennisBoss AI est un outil d'analyse tennis par intelligence artificielle,
pensé pour comprendre un match en profondeur — pas pour promettre de gagner.

🎾 CE QUE FAIT L'APP
• Prédiction du 1er set avec explicabilité complète (quels facteurs pèsent
  et pourquoi : service, retour, forme récente, niveau ELO historique)
• Fiche joueur détaillée : bilan victoires/défaites, forme des 10 derniers
  matchs, ELO et classement parmi les joueurs suivis
• Face-à-face (head-to-head) entre deux joueurs sur l'historique complet
• Comparaison de cotes marché vs modèle (à titre informatif — l'app ne
  permet PAS de parier ni de transférer de l'argent)
• Chat IA : posez vos questions tennis en langage naturel, réponses ancrées
  dans les vraies statistiques quand c'est pertinent
• Suivi de performance transparent : précision réelle du modèle, Closing Line
  Value (indicateur avancé d'edge utilisé par les parieurs professionnels),
  historique des matchs réglés — rien n'est caché, même quand c'est négatif

🤖 HONNÊTETÉ AVANT TOUT
Aucun modèle ne gagne à tous les coups. Contrairement à beaucoup de services
d'analyse sportive qui affichent des taux de réussite invérifiables, TennisBoss
AI mesure et montre sa performance réelle avec une méthode reconnue du monde
du pari (la Closing Line Value), y compris quand elle n'est pas favorable.
C'est un outil d'aide à la décision et d'analyse — pas un système de paris,
pas une promesse de profit.

📊 DONNÉES
Basé sur des dizaines de milliers de matchs ATP/WTA/ITF, mis à jour en
continu, avec un modèle qui se recalibre automatiquement.

Pas de compte requis. Pas de publicité. Pas de collecte de données
personnelles.
```

### Catégorie
**Sport** (recommandé plutôt que "Outils" — le contenu est spécifiquement
tennis, pas un utilitaire générique)

### Classification du contenu
Voir section 2 — Tout public attendu.

### Coordonnées du développeur
⚠️ **À compléter par vous** : email de contact, site web (vous pouvez utiliser
`https://tennisboss.online`), politique de confidentialité
(`https://api.tennisboss.online/privacy`, déjà en ligne).

### Éléments graphiques à préparer
- Icône déjà prête (icône adaptative néon, cf. mémoire projet)
- **Screenshots** ✅ générés depuis l'émulateur, dans `store_assets/screenshots/`
  (7 images, 1080x2400, PNG 24-bit sans alpha — conforme aux specs Play) :
  1. `01_predict.png` — Prédiction + explicabilité (Djokovic vs Alcaraz)
  2. `02_predict_h2h_betbuilder.png` — Face-à-face + Bet Builder IA
  3. `03_value.png` — Value bets avec EV, honeypot, cotes marché vs modèle
  4. `04_live.png` — Live : ROI inplay, meilleur pick, picks récents réglés
  5. `05_edge_clv.png` — Edge/CLV : verdict honnête (montre le CLV négatif actuel,
     à évaluer si on la garde en 1ère position ou en dernière — voir note ci-dessous)
  6. `06_players_compare.png` — Comparaison joueurs (Djokovic vs Alcaraz, H2H complet)
  7. `07_chat.png` — Chat IA avec badge "Basé sur nos données (ELO, forme, H2H)"

  ⚠️ Point d'attention sur `05_edge_clv.png` : elle montre le CLV actuellement négatif
  (-3.9%, -9.8% ROI) en rouge. C'est cohérent avec le positionnement honnête, mais
  un visiteur qui *scanne* les screenshots sans lire peut mal l'interpréter. Gardée
  dans le set par défaut (elle prouve la transparence annoncée dans la description) —
  à vous de décider si vous la mettez en position 5-7 (après avoir capté l'intérêt)
  plutôt qu'en position 1-2.
- **Feature graphic** (1024x500) — bannière promotionnelle, pas encore créée
- Pas de vidéo promo nécessaire (optionnelle)

---

## Résumé — ce qui reste après ce document

| Tâche | Statut |
|---|---|
| Politique de confidentialité | ✅ Faite et en ligne |
| Data safety (contenu du formulaire) | ✅ Brouillon prêt ci-dessus |
| Classification contenu (réponses) | ✅ Brouillon prêt ci-dessus |
| Texte fiche store | ✅ Rédigé ci-dessus |
| Screenshots | ✅ 7 générées (`store_assets/screenshots/`) |
| Feature graphic (bannière 1024x500) | ⏳ À créer |
| Keystore de signature | ⏳ À votre charge (Android Studio) |
| Compte développeur Google Play (25$ unique) | ⏳ À votre charge |
| Nom/email dans PRIVACY_POLICY.md | ⏳ 2 placeholders à remplir |
