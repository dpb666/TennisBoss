#!/bin/bash
# Test Telegram chat endpoint (no Telegram bot required)

BASE_URL="${1:-http://localhost:8001}"
USER_ID="${2:-12345}"
MESSAGE="${3:-Who is favored on clay?}"

echo "Testing /tg-chat endpoint..."
echo "URL: $BASE_URL/tg-chat"
echo "User: $USER_ID"
echo "Message: $MESSAGE"
echo ""

curl -X POST "$BASE_URL/tg-chat" \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": $USER_ID,
    \"message\": \"$MESSAGE\"
  }" | jq .

echo ""
echo "Session history:"
curl -s "$BASE_URL/tg-sessions/$USER_ID" | jq .
