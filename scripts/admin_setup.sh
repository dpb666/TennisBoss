#!/bin/bash
# TennisBoss — Admin Setup Automation
# Automatise: server start, webhook Telegram, health check
set -euo pipefail

WORKDIR="/mnt/c/Users/donpa/TennisBoss"
cd "$WORKDIR"

# ─── Couleurs ───────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()  { echo -e "${RED}❌ $*${NC}"; }
info() { echo -e "${CYAN}ℹ️  $*${NC}"; }

echo -e "\n${BOLD}🎾 TennisBoss Admin Setup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── 1. Charger .env ────────────────────────────────────────────────────────
info "Chargement .env..."
if [ -f "$WORKDIR/.env" ]; then
    set -a; source "$WORKDIR/.env"; set +a
    ok ".env chargé"
else
    err ".env introuvable — crée le fichier d'abord"
    exit 1
fi

# ─── 2. Vérifier token Telegram ─────────────────────────────────────────────
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ "$TELEGRAM_BOT_TOKEN" = "REPLACE_ME" ]; then
    err "TELEGRAM_BOT_TOKEN manquant dans .env"
    echo "  → Ajoute ton token dans .env: TELEGRAM_BOT_TOKEN=ton_token"
    exit 1
fi

BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
NGROK="${NGROK_URL:-https://plausible-matchbox-thrive.ngrok-free.dev}"
APP_PORT="${APP_PORT:-8000}"
WEBHOOK_URL="${NGROK}/tg-webhook"

ok "Token Telegram: ${BOT_TOKEN:0:12}..."
ok "URL ngrok: $NGROK"

# ─── 3. Vérifier/démarrer le serveur ────────────────────────────────────────
echo ""
info "Vérification serveur sur port $APP_PORT..."

SERVER_RUNNING=false
if curl -s --max-time 3 "http://localhost:$APP_PORT/health" > /dev/null 2>&1; then
    ok "Serveur déjà actif sur :$APP_PORT"
    SERVER_RUNNING=true
elif curl -s --max-time 3 "http://localhost:$APP_PORT/api/chat" > /dev/null 2>&1; then
    ok "Serveur Flask actif sur :$APP_PORT"
    SERVER_RUNNING=true
else
    warn "Serveur non détecté sur :$APP_PORT"
    echo ""
    echo "  Démarre le serveur dans un autre terminal avec:"
    echo -e "  ${CYAN}  cd $WORKDIR && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $APP_PORT${NC}"
    echo ""
    read -p "  Appuie sur ENTER une fois démarré (ou Ctrl+C pour annuler)..."
fi

# ─── 4. Valider bot Telegram (getMe) ────────────────────────────────────────
echo ""
info "Validation bot Telegram (getMe)..."
BOT_INFO=$(curl -s --max-time 10 \
    "https://api.telegram.org/bot${BOT_TOKEN}/getMe")

BOT_OK=$(echo "$BOT_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok','false'))" 2>/dev/null || echo "false")

if [ "$BOT_OK" = "True" ] || [ "$BOT_OK" = "true" ]; then
    BOT_NAME=$(echo "$BOT_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'].get('username','?'))" 2>/dev/null)
    ok "Bot validé: @$BOT_NAME"
else
    err "Token invalide ou API inaccessible"
    echo "  Réponse: $BOT_INFO"
    exit 1
fi

# ─── 5. Enregistrer webhook Telegram ────────────────────────────────────────
echo ""
info "Enregistrement webhook: $WEBHOOK_URL"

WEBHOOK_RESP=$(curl -s --max-time 10 \
    "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
    -d "url=${WEBHOOK_URL}" \
    -d "allowed_updates=[\"message\",\"callback_query\"]" \
    -d "drop_pending_updates=true")

WH_OK=$(echo "$WEBHOOK_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok','false'))" 2>/dev/null || echo "false")

if [ "$WH_OK" = "True" ] || [ "$WH_OK" = "true" ]; then
    ok "Webhook enregistré ✓"
else
    err "Échec enregistrement webhook"
    echo "  Réponse: $WEBHOOK_RESP"
fi

# ─── 6. Vérifier webhook enregistré ─────────────────────────────────────────
echo ""
info "Vérification webhook actif..."
WH_INFO=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo")
WH_URL=$(echo "$WH_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'].get('url',''))" 2>/dev/null || echo "")
WH_ERR=$(echo "$WH_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'].get('last_error_message',''))" 2>/dev/null || echo "")

if [ "$WH_URL" = "$WEBHOOK_URL" ]; then
    ok "Webhook confirmé: $WH_URL"
else
    warn "Webhook URL: $WH_URL (attendu: $WEBHOOK_URL)"
fi
[ -n "$WH_ERR" ] && warn "Dernière erreur: $WH_ERR"

# ─── 7. Test endpoint chat (si serveur actif) ────────────────────────────────
echo ""
info "Test endpoint /tg-chat..."
CHAT_RESP=$(curl -s --max-time 5 -X POST "http://localhost:$APP_PORT/tg-chat" \
    -H "Content-Type: application/json" \
    -d '{"user_id":7379016864,"message":"ping"}' 2>/dev/null || echo '{"error":"timeout"}')

if echo "$CHAT_RESP" | python3 -c "import sys,json; json.load(sys.stdin)" > /dev/null 2>&1; then
    ok "Endpoint /tg-chat répond"
    echo "  Réponse: $(echo "$CHAT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d)[:120])" 2>/dev/null)"
else
    warn "/tg-chat non disponible (serveur FastAPI peut-être pas lancé)"
fi

# ─── 8. Envoyer message de confirmation à l'admin ────────────────────────────
echo ""
info "Envoi notification admin Telegram..."
ADMIN_ID="${TELEGRAM_ADMIN_ID:-7379016864}"
NOTIFY_MSG="🎾 *TennisBoss Admin Setup* ✅%0A%0AWebhook actif: \`${WEBHOOK_URL}\`%0AServeur: http://localhost:${APP_PORT}%0ABot: @${BOT_NAME:-tennis_bot}"

NOTIFY_RESP=$(curl -s --max-time 10 \
    "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${ADMIN_ID}" \
    -d "text=${NOTIFY_MSG}" \
    -d "parse_mode=Markdown" 2>/dev/null || echo '{}')

NOTIFY_OK=$(echo "$NOTIFY_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok','false'))" 2>/dev/null || echo "false")
[ "$NOTIFY_OK" = "True" ] || [ "$NOTIFY_OK" = "true" ] && ok "Notification envoyée → Telegram" || warn "Notification non envoyée (check admin ID)"

# ─── Résumé Final ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}📊 RÉSUMÉ${NC}"
echo "  Bot:      @${BOT_NAME:-?}"
echo "  Webhook:  $WEBHOOK_URL"
echo "  Serveur:  http://localhost:$APP_PORT"
echo "  Ngrok:    $NGROK"
echo ""
echo -e "${CYAN}  Test rapide depuis Telegram: envoie un message au bot${NC}"
echo -e "${CYAN}  Ou: curl -X POST http://localhost:$APP_PORT/tg-chat -H 'Content-Type: application/json' -d '{\"user_id\":1,\"message\":\"test\"}'${NC}"
echo ""
