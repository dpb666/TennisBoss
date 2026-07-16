# 🎾 TennisBoss AI Chat — Quick Start

## Test Locally (No Bot Needed)

```bash
# 1. Start server (Terminal 1)
cd /mnt/c/Users/donpa/TennisBoss
./run_ai_chat.sh

# 2. Test in another terminal (Terminal 2)
./test_telegram.sh http://localhost:8001 999 "Is Djokovic favored on clay?"
```

Expected output:
```json
{
  "user_id": 999,
  "reply": "Based on ELO data... [AI response]",
  "agent": null,
  "confidence": null
}
```

## With Real Telegram Bot

```bash
# 1. Create bot with @BotFather on Telegram
# Copy token: 123456:ABC-DEF...

# 2. Export token
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."

# 3. Start server
./run_ai_chat.sh

# 4. Register webhook (from separate terminal)
curl -X POST "https://api.telegram.org/bot{TOKEN}/setWebhook" \
  -d "url=https://your-domain.com/tg-webhook"

# 5. Message the bot on Telegram → instant AI replies
```

## Endpoints Reference

| Method | Endpoint | Use |
|--------|----------|-----|
| POST | `/tg-chat` | Direct API (test locally) |
| POST | `/tg-webhook` | Telegram bot webhook |
| GET | `/tg-sessions/{id}` | View conversation history |

## Commands in Telegram

```
/help              → Show commands
/clear             → Reset conversation
@stats_agent: ... → Send to stats agent
@odds_agent: ...  → Send to odds agent
<any text>         → Direct AI chat
```

## Debugging

```bash
# View session history
curl http://localhost:8001/tg-sessions/999 | jq

# Check DB directly
sqlite3 /tmp/tg_sessions.db "SELECT * FROM tg_history LIMIT 5;"

# View logs
tail -f app.log
```

## Architecture

```
User Message
    ↓
/tg-webhook (Telegram)  OR  /tg-chat (API)
    ↓
parse + route
    ↓
Local LLM (Ollama)
    ↓
SQLite storage
    ↓
Response
```

---

## AI Analyst Tools (Phase 1, 2026-07-16)

`POST /api/chat` can now answer read-only analytical questions using
structured tool output instead of only free-form LLM guessing — see
`docs/AI_ASSISTANT_ARCHITECTURE.md` and `ai/chat/`. Disabled by default;
enable with `TENNISBOSS_API_TOKEN`-style env var `TENNISBOSS_AI_TOOLS=1`.
Purely additive: player-specific questions still use the existing
`build_match_context()` grounding unchanged; tools only run as a fallback
when no player is detected in the message.

Example questions this unlocks:

```
"Quel est notre ROI sur les 30 derniers jours ?"        -> query_bet_history
"Sommes-nous bien calibrés en ce moment ?"               -> get_calibration_summary
"Le logging est-il complet cette semaine ?"              -> get_logging_health
"Quels endpoints exposent le bet_history ?"              -> list_api_endpoints
"Comment fonctionne l'architecture du projet ?"          -> read_doc(ai_architecture)
```

Response now includes (when tools fired):

```json
{
  "reply": "...",
  "context_used": true,
  "tools_called": ["query_bet_history"],
  "sources": ["bet_history"]
}
```

**Never** does this layer place bets, change predictions, or modify
`predictor.py`/`calibrate.py`/production logic — it only reads. See
`ai/chat/tools/registry.py` for the exact read-only tool list and
`tests/test_ai_tools.py` for the frozen-boundary guard tests.

### mode=analyst (2026-07-16)

Pass `"mode": "analyst"` in the `/api/chat` request body for longer, more
detailed factual answers (higher token budget, lower temperature) instead
of the default mobile-friendly 3-sentence replies:

```json
{"message": "Quel est notre ROI ?", "mode": "analyst"}
```

Optional `"max_tokens"` overrides the analyst default (512). Response
includes `"mode"` echoing back what was used. `mode=chat` (default, or
omitted) is byte-identical to prior behavior — nothing changes unless a
client opts in.

**Full docs:** See `TELEGRAM_SETUP.md`, `AI_CHAT_AUDIT.md` (stale — predates
the `app/` removal), and `docs/AI_ASSISTANT_ARCHITECTURE.md` (current).
