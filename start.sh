#!/bin/bash
# Démarre TennisBoss — serveur API + tunnel Cloudflare permanent
cd "$(dirname "$0")"

echo "=== TennisBoss Startup ==="

pkill -f "run.py serve" 2>/dev/null
pkill -f "cloudflared tunnel run" 2>/dev/null
sleep 1

echo "→ Tunnel Cloudflare (api.tennisboss.ca.eu.org)..."
cloudflared tunnel run tennisboss > /tmp/cloudflared.log 2>&1 &

echo "→ Serveur API (port 8000)..."
python3 run.py serve --host 0.0.0.0 --port 8000 > /tmp/tennisboss.log 2>&1 &

sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/status | grep -q "200\|401" \
  && echo "→ Serveur OK" || echo "⚠️  Serveur pas prêt"

echo ""
echo "  API local  : http://localhost:8000"
echo "  API public : https://api.tennisboss.ca.eu.org"
echo "  Logs : tail -f /tmp/tennisboss.log"
