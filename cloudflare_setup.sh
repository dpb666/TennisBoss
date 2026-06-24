#!/bin/bash
# Setup Cloudflare Tunnel permanent pour TennisBoss API (port 8000)
# Lancer UNE SEULE FOIS après `cloudflared tunnel login`

TUNNEL_NAME="tennisboss"

echo "=== Création du tunnel $TUNNEL_NAME ==="
cloudflared tunnel create $TUNNEL_NAME

# Récupère l'ID du tunnel créé
TUNNEL_ID=$(cloudflared tunnel list --name $TUNNEL_NAME --output json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'])" 2>/dev/null)
if [ -z "$TUNNEL_ID" ]; then
    TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep $TUNNEL_NAME | awk '{print $1}')
fi
echo "Tunnel ID: $TUNNEL_ID"

# Crée le fichier de config
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: $TUNNEL_ID
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json

ingress:
  - service: http://localhost:8000
EOF

echo ""
echo "=== Config écrite dans ~/.cloudflared/config.yml ==="
echo ""
echo "Options pour exposer l'URL :"
echo ""
echo "A) Sans domaine perso (URL trycloudflare.com — change à chaque restart) :"
echo "   cloudflared tunnel --url http://localhost:8000"
echo ""
echo "B) Avec domaine Cloudflare (URL permanente) :"
echo "   cloudflared tunnel route dns $TUNNEL_NAME api.TON-DOMAINE.com"
echo "   cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo "Lance le tunnel maintenant (mode quick sans domaine) :"
cloudflared tunnel --url http://localhost:8000 2>&1 | grep -E "trycloudflare|cloudflare.com|URL" &
CFPID=$!
sleep 8
echo ""
echo "Copie l'URL ci-dessus et mets-la dans .env : CLOUDFLARE_URL=https://xxxx.trycloudflare.com"
