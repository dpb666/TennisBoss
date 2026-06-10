# TennisBoss Telegram Bot Setup

## Quick Start

### 1. Create Telegram Bot
```bash
# Message @BotFather on Telegram
/newbot
# Follow prompts, get your TOKEN (example):
# 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

### 2. Set Environment Variable
```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
```

Or in `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

### 3. Start Server
```bash
python run.py quant
# Or directly:
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 4. Register Webhook (from outside WSL)
```bash
# On Windows CMD or PowerShell:
curl -X POST "https://api.telegram.org/botYOUR_TOKEN/setWebhook" `
  -d "url=https://your-domain.com/tg-webhook"

# Or if testing locally with ngrok:
ngrok http 8001
# Then:
curl -X POST "https://api.telegram.org/botYOUR_TOKEN/setWebhook" \
  -d "url=https://abc123.ngrok.io/tg-webhook"
```

## Endpoints

### Webhook (Telegram → App)
```
POST /tg-webhook
```
Telegram sends updates here. Auto-routes to agents.

### Direct Chat API (Testing)
```
POST /tg-chat
Content-Type: application/json

{
  "user_id": 123456789,
  "message": "Is Djokovic favored on clay?"
}
```

Response:
```json
{
  "user_id": 123456789,
  "reply": "Yes, Djokovic has 72% win prob on clay...",
  "agent": null,
  "confidence": 0.72
}
```

### Session History
```
GET /tg-sessions/123456789
```

Returns conversation history for that user.

## Commands

Users can message the bot:

### General
- `/help` — Show commands
- `/clear` — Reset conversation history
- Text message — Direct AI chat

### Agent Routing
- `@stats_agent: Who is best on clay?` — Player analysis
- `@odds_agent: Any arbitrage?` — Market value detection
- `@analyzer_agent: Djokovic vs Alcaraz` — Combined analysis

## Architecture

```
Telegram App
    ↓ (webhook POST)
/tg-webhook (FastAPI)
    ↓
parse_telegram_message()
    ↓
get_session() [SQLite]
    ↓
route_agent_command()
    ├→ _agent_chat() [future: OpenClaw agents]
    └→ _run_chat() [local LLM via chat.py]
    ↓
save_message() [SQLite history]
    ↓
_send_telegram_message()
    ↓
Telegram API → User
```

## Session Storage

Sessions are stored in SQLite (`/tmp/tg_sessions.db`):

```sql
tg_sessions:
  - user_id (int, primary key)
  - username (text)
  - created_at (datetime)
  - last_msg (datetime)

tg_history:
  - id (int, auto-increment)
  - user_id (int, FK)
  - role (text: "user" | "assistant")
  - content (text)
  - timestamp (datetime)
```

## Testing Without Telegram

Use the `/tg-chat` endpoint to test locally:

```bash
curl -X POST "http://localhost:8001/tg-chat" \
  -H "Content-Type: application/json" \
  -d '{"user_id": 999, "message": "Hi Djokovic vs Sinner?"}' | jq
```

## Troubleshooting

### "Invalid token" Error
- Check `TELEGRAM_BOT_TOKEN` is set correctly
- Message @BotFather → `/token` to get fresh token

### No replies from bot
- Check webhook URL is accessible (use `curl` to test)
- Check logs: `journalctl -u tennisboss -f`
- Verify bot is in chat (message it first)

### Sessions not persisting
- Check `/tmp/tg_sessions.db` exists
- Verify SQLite is writable: `ls -la /tmp/`

## Future: Agent Routing

Currently, agent routing is a stub. To enable:

1. Spawn OpenClaw sub-agents (`sessions_spawn`) for:
   - `@stats_agent` → stats analysis
   - `@odds_agent` → market value
   - `@analyzer_agent` → synthesis

2. Add to `/app/api/chat_routes.py`:
   ```python
   async def _agent_chat(...):
       agent_session = sessions_spawn(
           sessionName=agent,
           prompt=f"Analyze: {message}"
       )
       sessions_yield()
       return agent_session.output
   ```

3. Test with:
   ```
   @stats_agent: Why is Djokovic favored?
   ```
