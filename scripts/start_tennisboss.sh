#!/bin/bash
# Lance TennisBoss API + expose via Cloudflare Tunnel (accès partout)
# Usage: bash scripts/start_tennisboss.sh [--tunnel]
#
# Prérequis tunnel: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

set -e
cd "$(dirname "$0")/.."

# Tuer les instances précédentes
fuser -k 8000/tcp 2>/dev/null || true
pkill -f cloudflared 2>/dev/null || true
sleep 1

# Lancer le serveur API
nohup python3 run.py serve > /tmp/tennisboss.log 2>&1 &
API_PID=$!
echo "[TennisBoss] Serveur API démarré (PID=$API_PID)"

# Attendre que l'API soit prête
for i in $(seq 1 15); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "[TennisBoss] API prête sur http://localhost:8000"
        break
    fi
    sleep 2
done

# Optionnel : tunnel Cloudflare pour accès depuis n'importe où
if [[ "$1" == "--tunnel" ]]; then
    if ! command -v cloudflared &> /dev/null; then
        echo "[TennisBoss] Installation cloudflared..."
        curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
        chmod +x /usr/local/bin/cloudflared
    fi
    echo "[TennisBoss] Démarrage tunnel Cloudflare..."
    cloudflared tunnel --url http://localhost:8000 > /tmp/tunnel.log 2>&1 &
    sleep 4
    # Extraire l'URL publique
    URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/tunnel.log | head -1)
    if [[ -n "$URL" ]]; then
        echo ""
        echo "╔══════════════════════════════════════════════════════╗"
        echo "║  TennisBoss accessible depuis partout :              ║"
        echo "║  $URL"
        echo "║  Mets cette URL dans l'app Android (ApiClient.kt)   ║"
        echo "╚══════════════════════════════════════════════════════╝"
        echo "$URL" > /tmp/tunnel_url.txt
    fi
fi

echo "[TennisBoss] Logs: tail -f /tmp/tennisboss.log"
