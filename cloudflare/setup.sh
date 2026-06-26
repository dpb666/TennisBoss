#!/bin/bash
# TennisBoss — Setup Cloudflare Worker + Tunnel
# Prérequis : CLOUDFLARE_API_TOKEN dans l'env ou passé en argument
#
# Usage :
#   export CLOUDFLARE_API_TOKEN=ton_token
#   bash cloudflare/setup.sh

set -e

CF_TOKEN="${CLOUDFLARE_API_TOKEN:-$1}"
ACCOUNT_ID="cdbd81bae4e8a81f7c9d9022fb5470c5"
TUNNEL_NAME="tennisboss"
WORKER_NAME="tennisboss-api"

if [ -z "$CF_TOKEN" ]; then
  echo "ERREUR: CLOUDFLARE_API_TOKEN requis"
  echo "Usage: CLOUDFLARE_API_TOKEN=xxx bash cloudflare/setup.sh"
  exit 1
fi

echo "=== 1. Vérification du token ==="
cf_check=$(curl -s "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  -H "Authorization: Bearer $CF_TOKEN")
if echo "$cf_check" | grep -q '"status":"active"'; then
  echo "✅ Token valide"
else
  echo "❌ Token invalide : $cf_check"
  exit 1
fi

echo ""
echo "=== 2. Création du tunnel Cloudflare ==="
if ! command -v cloudflared &>/dev/null; then
  echo "Installation de cloudflared..."
  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared
  chmod +x /usr/local/bin/cloudflared
fi

# Créer le tunnel via API Cloudflare
TUNNEL_RESP=$(curl -s -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$TUNNEL_NAME\",\"tunnel_secret\":\"$(openssl rand -base64 32)\"}")

TUNNEL_SUCCESS=$(echo "$TUNNEL_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success',''))" 2>/dev/null)

if [ "$TUNNEL_SUCCESS" = "True" ]; then
  TUNNEL_ID=$(echo "$TUNNEL_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result']['id'])" 2>/dev/null)
  TUNNEL_TOKEN=$(echo "$TUNNEL_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'].get('token',''))" 2>/dev/null)
  echo "✅ Tunnel créé : $TUNNEL_ID"
else
  # Tunnel existe déjà — récupérer l'ID
  TUNNEL_ID=$(curl -s \
    "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel?name=$TUNNEL_NAME" \
    -H "Authorization: Bearer $CF_TOKEN" | \
    python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print(r[0]['id'] if r else '')" 2>/dev/null)
  echo "ℹ️  Tunnel existant : $TUNNEL_ID"
fi

if [ -z "$TUNNEL_ID" ]; then
  echo "❌ Impossible de récupérer l'ID du tunnel"
  exit 1
fi

echo ""
echo "=== 3. Mise à jour de wrangler.toml avec l'UUID du tunnel ==="
sed -i "s|TUNNEL_UUID_ICI|$TUNNEL_ID|g" cloudflare/wrangler.toml
echo "✅ TUNNEL_URL = https://$TUNNEL_ID.cfargotunnel.com"

echo ""
echo "=== 4. Mise à jour du .env ==="
if grep -q "CLOUDFLARE_TUNNEL_TOKEN" .env 2>/dev/null; then
  if [ -n "$TUNNEL_TOKEN" ]; then
    sed -i "s|^CLOUDFLARE_TUNNEL_TOKEN=.*|CLOUDFLARE_TUNNEL_TOKEN=$TUNNEL_TOKEN|" .env
  fi
else
  echo "" >> .env
  echo "CLOUDFLARE_TUNNEL_TOKEN=${TUNNEL_TOKEN:-}" >> .env
fi
echo "TUNNEL_UUID=$TUNNEL_ID" >> .env 2>/dev/null || true
echo "✅ .env mis à jour"

echo ""
echo "=== 5. Déploiement du Worker ==="
if ! command -v npx &>/dev/null; then
  echo "❌ Node.js requis pour wrangler. Installer: https://nodejs.org"
  echo "   Ou déployer manuellement via le Dashboard Cloudflare."
else
  cd cloudflare
  CLOUDFLARE_API_TOKEN="$CF_TOKEN" npx wrangler@latest deploy
  cd ..
  echo "✅ Worker déployé"
fi

echo ""
echo "================================================================"
echo "✅ SETUP COMPLET"
echo ""
echo "URL publique de l'API (permanente) :"
echo "  https://$WORKER_NAME.$(curl -s \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/subdomain" \
  -H "Authorization: Bearer $CF_TOKEN" | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('subdomain','TON_SUBDOMAIN'))" 2>/dev/null).workers.dev"
echo ""
echo "Mettre à jour android/app/.../data/ApiClient.kt :"
echo "  const val DEFAULT_BASE_URL = \"https://$WORKER_NAME.XXX.workers.dev/\""
echo ""
echo "Démarrer le tunnel + API :"
echo "  docker-compose up -d"
echo "================================================================"
