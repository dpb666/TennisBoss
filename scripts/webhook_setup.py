#!/usr/bin/env python3
"""Telegram webhook setup automation."""

import os
import json
import requests
import sys
from dotenv import load_dotenv
import time

# Load environment
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NGROK_URL = os.getenv("NGROK_URL")

if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "REPLACE_ME":
    print("❌ TELEGRAM_BOT_TOKEN not set in .env")
    sys.exit(1)

if not NGROK_URL:
    print("❌ NGROK_URL not set in .env")
    sys.exit(1)

WEBHOOK_URL = f"{NGROK_URL}/telegram"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

print("════════════════════════════════════════════════════════════")
print("🔗 Telegram Webhook Setup")
print("════════════════════════════════════════════════════════════")
print()
print(f"Bot Token: {TELEGRAM_BOT_TOKEN[:20]}...")
print(f"Webhook URL: {WEBHOOK_URL}")
print()

# Step 1: Delete existing webhook
print("1️⃣  Deleting old webhook (if exists)...")
try:
    resp = requests.post(f"{TELEGRAM_API}/deleteWebhook")
    print(json.dumps(resp.json(), indent=2))
except Exception as e:
    print(f"⚠️  {e}")
time.sleep(1)
print()

# Step 2: Set new webhook
print("2️⃣  Setting new webhook...")
webhook_data = {"url": WEBHOOK_URL}
resp = requests.post(f"{TELEGRAM_API}/setWebhook", json=webhook_data)
webhook_response = resp.json()
print(json.dumps(webhook_response, indent=2))
print()

if webhook_response.get("ok"):
    print("✅ Webhook set successfully!")
else:
    print("❌ Webhook setup failed")
    sys.exit(1)

# Step 3: Get webhook info
print()
print("3️⃣  Checking webhook info...")
resp = requests.post(f"{TELEGRAM_API}/getWebhookInfo")
print(json.dumps(resp.json(), indent=2))
print()

# Step 4: Get bot info
print("4️⃣  Bot info...")
resp = requests.post(f"{TELEGRAM_API}/getMe")
bot_info = resp.json()
if bot_info.get("ok"):
    result = bot_info.get("result", {})
    info_dict = {
        "id": result.get("id"),
        "is_bot": result.get("is_bot"),
        "first_name": result.get("first_name"),
        "username": result.get("username"),
    }
    print(json.dumps(info_dict, indent=2))
print()

print("════════════════════════════════════════════════════════════")
print("✅ Webhook setup complete!")
print()
print("📱 Next: Send a message to your bot on Telegram")
print("   → Watch the server logs for incoming updates")
print("════════════════════════════════════════════════════════════")
