#!/bin/bash
# TennisBoss — démarrage API + tunnel ngrok
# URL publique stable : https://tennisboss-api.walid-zahir89.workers.dev
cd "$(cd "$(dirname "$0")/.." && pwd)"
source .env 2>/dev/null || true

WORKER_URL="https://tennisboss-api.walid-zahir89.workers.dev"
STATIC_NGROK="https://plausible-matchbox-thrive.ngrok-free.dev"

echo "=== TennisBoss Startup ==="

pkill -f "run.py serve" 2>/dev/null || true
pkill -f "ngrok" 2>/dev/null || true
sleep 1

# 1. Démarrer l'API Flask
echo "→ API Flask (port 8000)..."
python3 run.py serve --host 0.0.0.0 --port 8000 > /tmp/tennisboss.log 2>&1 &
for i in $(seq 1 15); do
  curl -sf http://localhost:8000/health > /dev/null 2>&1 && break || sleep 1
done
echo "✅ API prête"

# 2. Démarrer ngrok (domaine statique gratuit — URL ne change pas)
echo "→ Tunnel ngrok ($STATIC_NGROK)..."
ngrok http 8000 --log=stdout --log-format=json > /tmp/ngrok.log 2>&1 &
sleep 4

NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | \
  python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print([x['public_url'] for x in t if x['proto']=='https'][0])" 2>/dev/null)

if [ -z "$NGROK_URL" ]; then
  echo "❌ ngrok KO — voir /tmp/ngrok.log"
  tail -5 /tmp/ngrok.log
  exit 1
fi
echo "✅ Tunnel : $NGROK_URL"

# 3. Si l'URL a changé (ne devrait pas arriver), redéployer le Worker
if [ "$NGROK_URL" != "$STATIC_NGROK" ]; then
  echo "⚠️  URL ngrok inattendue — mise à jour du Worker..."
  sed -i "s|TUNNEL_URL = \".*\"|TUNNEL_URL = \"$NGROK_URL\"|" cloudflare/wrangler.toml
  if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
    echo "⚠️  CLOUDFLARE_API_TOKEN non défini — mise à jour manuelle requise"
  else
    (cd cloudflare && npx wrangler@latest deploy 2>&1 | tail -3) && \
      echo "✅ Worker mis à jour" || echo "⚠️  Worker update manuelle requise"
  fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  API locale  : http://localhost:8000"
echo "  Tunnel ngrok: $NGROK_URL"
echo "  API publique: $WORKER_URL  ← app Android"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Logs API    : tail -f /tmp/tennisboss.log"
echo "  Logs tunnel : tail -f /tmp/ngrok.log"
