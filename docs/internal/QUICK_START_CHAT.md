# 🎾 TennisBoss AI Chat — Quick Start

_Rafraîchi 2026-07-23 : les sections `/tg-chat`, `/tg-webhook`, port 8001
référençaient l'ancien service FastAPI `app/`, retiré le 2026-07-13 — elles
ont été retirées de ce document (le canal réel est décrit ci-dessous)._

## Tester en local (API directe)

```bash
cd /mnt/c/Users/donpa/TennisBoss
python run.py serve --host 127.0.0.1 --port 8000

curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Qui est favori sur terre battue entre Sinner et Alcaraz ?"}'
```

Réponse attendue :

```json
{"reply": "...", "context_used": true, "agent": null, "mode": "chat"}
```

## Bot Telegram (canal réel de production)

Le bot Telegram tourne en **long-polling** (`bot/workers/telegram_worker.py`,
pas de webhook), démarré automatiquement par `bot/api.py::serve()` quand
`TELEGRAM_BOT_TOKEN` est défini dans `.env`. Accès restreint à
`TELEGRAM_ADMIN_ID` (ou `TELEGRAM_OWNER_CHAT_ID`) — un seul utilisateur.

```bash
# .env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_ADMIN_ID=<votre chat_id Telegram>
```

### Commandes

```text
/start        → liste des commandes
/picks        → picks du jour
/value        → picks ouverts (value bets)
/clv          → Closing Line Value
/clv-weekly   → CLV des 7 derniers jours
/roi          → ROI par tranche EV
/intel        → cerveau IA (blacklist, zones)
/scanner      → état du scanner 90s
/stats        → bilan global
/digest       → rapport complet
/clear        → efface l'historique de conversation
<texte libre> → assistant analyste complet (voir ci-dessous)
```

### Chat texte libre = assistant analyste complet (corrigé 2026-07-23)

Tout message qui n'est pas une commande `/xxx` est traité **en process** par
`bot/chat.py::answer()` — la même fonction que `POST /api/chat`, en
`mode="analyst"` (réponses détaillées, outils IA Phase 1 actifs si
`TENNISBOSS_AI_TOOLS=1`, sources citées en pied de message). L'historique de
conversation est conservé en mémoire par chat_id (perdu au redémarrage,
`/clear` l'efface).

**Avant ce correctif**, ce chemin appelait `http://127.0.0.1:8001/api/chat` —
le port de l'ex-service FastAPI `app/`, retiré le 2026-07-13 : chaque message
texte échouait silencieusement depuis (`"Erreur chat: ..."`). C'est réparé.

## AI Analyst Tools (Phase 1, 2026-07-16)

`POST /api/chat` (et donc aussi le chat Telegram) peut répondre à des
questions analytiques en s'appuyant sur des outils de lecture seule plutôt
que sur le seul LLM — voir `docs/AI_ASSISTANT_ARCHITECTURE.md` et
`ai/chat/`. Désactivé par défaut ; activer avec `TENNISBOSS_AI_TOOLS=1`.
Purement additif : les questions sur un joueur précis gardent le grounding
`build_match_context()` existant ; les outils ne s'exécutent qu'en repli
quand aucun joueur n'est détecté dans le message.

Exemples de questions débloquées :

```
"Quel est notre ROI sur les 30 derniers jours ?"        -> query_bet_history
"Sommes-nous bien calibrés en ce moment ?"               -> get_calibration_summary
"Le logging est-il complet cette semaine ?"              -> get_logging_health
"Quels endpoints exposent le bet_history ?"              -> list_api_endpoints
"Comment fonctionne l'architecture du projet ?"          -> read_doc(ai_architecture)
"Quelles suggestions avez-vous cette semaine ?"          -> get_learning_report (Phase 3, 2026-07-23)
```

Réponse (quand des outils se sont déclenchés) :

```json
{
  "reply": "...",
  "context_used": true,
  "tools_called": ["query_bet_history"],
  "sources": ["bet_history"]
}
```

**Ne fait jamais** : placer un pari, changer une prédiction, modifier
`predictor.py`/`calibrate.py`/la logique de production — lecture seule
uniquement. Voir `ai/chat/tools/registry.py` pour la liste exacte des outils
et `tests/test_ai_tools.py` pour les tests de garde-fou (frontière figée).

### mode=analyst (2026-07-16)

Passer `"mode": "analyst"` dans le corps de `POST /api/chat` pour des
réponses plus longues et factuelles (budget de tokens plus élevé,
température plus basse) au lieu des 3 phrases mobiles par défaut :

```json
{"message": "Quel est notre ROI ?", "mode": "analyst"}
```

`"max_tokens"` (optionnel) surcharge le défaut analyste (512). La réponse
inclut `"mode"` en écho. `mode=chat` (défaut, ou omis) est identique au
comportement précédent — rien ne change sans opt-in explicite du client.

## Phase 3 — Rapport d'apprentissage hebdomadaire (2026-07-23)

`ai/learning/analyzer.py` synthétise chaque semaine (job scheduler, dimanche
22h30) les patterns de calibration/surface/tournoi/désaccord marché en
**suggestions** — jamais un changement automatique du prédicteur/de la
calibration (ADR-005). Consultable via :

```bash
python run.py learning-report              # génère + affiche
python run.py learning-report --no-write   # affiche seulement
```

Ou en posant une question au chat (Telegram ou `/api/chat`, voir ci-dessus).
Voir `docs/ARCHITECTURE_BLUEPRINT.md` §6.5.

---

**Docs liées :** `docs/AI_ASSISTANT_ARCHITECTURE.md` (plan détaillé),
`docs/ARCHITECTURE_BLUEPRINT.md` (référence permanente), `TELEGRAM_SETUP.md`
(config bot). `docs/audits/AI_CHAT_AUDIT.md` reste stale (prédate le retrait de
`app/`, archivé 2026-07-23) — ne pas s'y fier.
