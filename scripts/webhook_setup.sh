#!/bin/bash

# Webhook setup and test automation

set -e

# Load environment
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "REPLACE_ME" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN not set in .env"
    echo "Please add your bot token to .env:"
    echo "  TELEGRAM_BOT_TOKEN=<your_token_here>"
    exit 1
fi

if [ -z "$NGROK_URL" ]; then
    echo "❌ NGROK_URL not set in .env"
    exit 1
fi

WEBHOOK_URL="${NGROK_URL}/telegram"
TELEGRAM_API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

echo "════════════════════════════════════════════════════════════"
echo "🔗 Telegram Webhook Setup"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "Bot Token: ${TELEGRAM_BOT_TOKEN:0:20}..."
echo "Webhook URL: $WEBHOOK_URL"
echo ""

# Step 1: Delete existing webhook
echo "1️⃣  Deleting old webhook (if exists)..."
curl -s -X POST "${TELEGRAM_API}/deleteWebhook" | jq '.' || true
sleep 1
echo ""

# Step 2: Set new webhook
echo "2️⃣  Setting new webhook..."
WEBHOOK_RESPONSE=$(curl -s -X POST "${TELEGRAM_API}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"$WEBHOOK_URL\"}")

echo "$WEBHOOK_RESPONSE" | jq '.'
echo ""

if echo "$WEBHOOK_RESPONSE" | jq -e '.ok == true' >/dev/null; then
    echo "✅ Webhook set successfully!"
else
    echo "❌ Webhook setup failed"
    exit 1
fi

# Step 3: Get webhook info
echo ""
echo "3️⃣  Checking webhook info..."
WEBHOOK_INFO=$(curl -s -X POST "${TELEGRAM_API}/getWebhookInfo")
echo "$WEBHOOK_INFO" | jq '.'
echo ""

# Step 4: Get bot info
echo "4️⃣  Bot info..."
BOT_INFO=$(curl -s -X POST "${TELEGRAM_API}/getMe")
echo "$BOT_INFO" | jq '.result | {id, is_bot, first_name, username}'
echo ""

echo "════════════════════════════════════════════════════════════"
echo "✅ Webhook setup complete!"
echo ""
echo "📱 Next: Send a message to your bot on Telegram"
echo "   → Watch the server logs for incoming updates"
echo "════════════════════════════════════════════════════════════"
