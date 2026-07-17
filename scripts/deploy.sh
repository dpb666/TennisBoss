#!/usr/bin/env bash
# TennisBoss — déploiement reproductible et journalisé.
# docs/ARCHITECTURE_BLUEPRINT.md §9.3 / ADR-011 (roadmap Q3 #5).
#
# Usage (sur l'hôte prod, WSL ou VPS) :
#   scripts/deploy.sh                 # systemd (défaut) : pull + restart + health check
#   scripts/deploy.sh --compose       # docker compose up -d --build
#   scripts/deploy.sh --no-pull       # déployer l'arbre tel quel (déjà pullé/vérifié)
#
# Chaque exécution enregistre une ligne dans deployment_history via
# `run.py record-deploy` — succès comme rollback. C'est ce journal qui élimine
# la dérive prod vs repo (risque R-6) : on sait toujours quel commit tourne.
#
# Rollback : si /health ne répond pas après restart, retour au commit précédent
# (detached HEAD — l'opérateur re-branche après diagnostic) + restart + journal.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="systemd"
PULL=1
for arg in "$@"; do
  case "$arg" in
    --compose) MODE="compose" ;;
    --no-pull) PULL=0 ;;
    *) echo "option inconnue: $arg (attendu: --compose, --no-pull)" >&2; exit 2 ;;
  esac
done

HEALTH_URL="${TENNISBOSS_HEALTH_URL:-http://127.0.0.1:8000/health}"
PY="${TENNISBOSS_PYTHON:-python3}"

PREV_HASH=$(git rev-parse --short HEAD)

if [ "$PULL" = 1 ]; then
  git pull --ff-only
fi
NEW_HASH=$(git rev-parse --short HEAD)

# Dépendances AVANT restart : si pip échoue (réseau...), set -e arrête ici
# et la prod continue de tourner sur l'ancien code — bon mode de défaillance.
"$PY" -m pip install -r requirements.txt --quiet

restart_services() {
  if [ "$MODE" = "compose" ]; then
    docker compose up -d --build
  else
    sudo systemctl restart tennisboss-bot.service
    sudo systemctl restart tennisboss-scheduler.service
  fi
}

health_ok() {
  # ~60 s au total : 12 essais espacés de 5 s.
  for _ in $(seq 1 12); do
    if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

echo "Déploiement $PREV_HASH -> $NEW_HASH ($MODE)"
restart_services

if health_ok; then
  "$PY" run.py record-deploy --git-hash "$NEW_HASH" --component all --result success \
    --notes "deploy.sh $MODE (depuis $PREV_HASH)"
  echo "OK — santé confirmée sur $HEALTH_URL"
else
  echo "ÉCHEC health check — rollback vers $PREV_HASH" >&2
  git checkout --quiet "$PREV_HASH"
  restart_services
  if health_ok; then RESULT="rollback"; else RESULT="failed"; fi
  "$PY" run.py record-deploy --git-hash "$PREV_HASH" --component all --result "$RESULT" \
    --notes "rollback auto depuis $NEW_HASH (health KO)"
  exit 1
fi
