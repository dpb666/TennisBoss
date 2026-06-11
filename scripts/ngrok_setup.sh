#!/bin/bash

# TennisBoss ngrok automation setup
set -e

NGROK_TOKEN="3EwrfnlIvID8UBbcc1ZVM4xIooG_3rjXXPvhPAzNoKKAUFa4e"
PORT=8000
WEBHOOK_BASE="telegram"

echo "════════════════════════════════════════════════════════════"
echo "🚀 TennisBoss ngrok Setup Automation"
echo "════════════════════════════════════════════════════════════"
echo ""

# 1. Check if ngrok is installed
echo "📦 Checking ngrok installation..."
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok not found. Installing..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt-get update && sudo apt-get install -y ngrok
else
    echo "✅ ngrok is installed"
fi
echo ""

# 2. Configure ngrok token
echo "🔑 Configuring ngrok authtoken..."
ngrok config add-authtoken "$NGROK_TOKEN" 2>/dev/null || true
echo "✅ Token configured"
echo ""

# 3. Check if server is running
echo "🔍 Checking if server is running on port $PORT..."
if netstat -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "✅ Server is running on port $PORT"
else
    echo "⚠️  No server detected on port $PORT"
    echo "   Make sure your FastAPI server is running:"
    echo "   $ python app/main.py"
fi
echo ""

# 4. Start ngrok
echo "🌐 Starting ngrok on port $PORT..."
echo "════════════════════════════════════════════════════════════"
echo ""
echo "ngrok will display your public URL below."
echo "Copy the URL and use it for Telegram webhook:"
echo "  /set_webhook <YOUR_NGROK_URL>/telegram"
echo ""
echo "────────────────────────────────────────────────────────────"

ngrok http $PORT --log=stdout

