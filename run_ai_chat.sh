#!/bin/bash
# Quick start AI Chat system with optional Telegram token

set -e

echo "🎾 TennisBoss AI Chat Starter"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Default Telegram token (user can override)
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"

if [ -z "$TG_TOKEN" ]; then
    echo "⚠️  No TELEGRAM_BOT_TOKEN set"
    echo "   Set it with: export TELEGRAM_BOT_TOKEN='your_token'"
    echo "   Or message @BotFather on Telegram for a new token."
    echo ""
    echo "   (You can still test with /tg-chat endpoint without a token)"
fi

# Check if Ollama is running
echo "🔍 Checking Ollama..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama not running on localhost:11434"
    echo "   Start it with: ollama serve"
    echo ""
fi

# Export token if set
if [ -n "$TG_TOKEN" ]; then
    export TELEGRAM_BOT_TOKEN="$TG_TOKEN"
    echo "✅ TELEGRAM_BOT_TOKEN set"
fi

# Start FastAPI server
echo ""
echo "Starting FastAPI server..."
echo "Endpoints:"
echo "  📊 Docs: http://localhost:8001/docs"
echo "  💬 Chat API: POST /tg-chat"
echo "  🔗 Webhook: POST /tg-webhook"
echo "  📜 History: GET /tg-sessions/{user_id}"
echo ""

cd /mnt/c/Users/donpa/TennisBoss

# Run server with reload
python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8001 \
    --reload \
    --log-level info
