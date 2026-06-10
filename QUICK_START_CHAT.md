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

**Full docs:** See `TELEGRAM_SETUP.md` and `AI_CHAT_AUDIT.md`
