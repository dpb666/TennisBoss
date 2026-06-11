#!/usr/bin/env bash
# Relance les deux serveurs TennisBoss après reboot PC / wsl --shutdown.
#   bash scripts/start_servers.sh
# - Quant API (FastAPI/uvicorn)  : port 8001  — /api/v2/* (value-ai, health…)
# - Bot API (Flask, app Android) : port 8000  — /api/* (value, calibration…)
set -u
cd "$(dirname "$0")/.."
mkdir -p logs

start_one() {
    local name="$1" port="$2" cmd="$3" log="$4" health="$5"
    if ss -tln | grep -q ":${port} "; then
        echo "[${name}] déjà en écoute sur ${port} — rien à faire."
        return 0
    fi
    echo "[${name}] démarrage…"
    nohup ${cmd} > "${log}" 2>&1 &
    for _ in $(seq 1 20); do
        sleep 1
        if curl -fs --max-time 3 "http://127.0.0.1:${port}${health}" > /dev/null 2>&1; then
            echo "[${name}] OK sur ${port} (log: ${log})"
            return 0
        fi
    done
    echo "[${name}] ÉCHEC — dernières lignes de ${log} :"
    tail -5 "${log}"
    return 1
}

rc=0
start_one "quant"  8001 "python3 run.py quant"                              "logs/quant.log" "/api/v2/health" || rc=1
start_one "bot"    8000 "python3 run.py serve --host 0.0.0.0 --port 8000"   "logs/serve.log" "/api/status"    || rc=1

# Supervisor (boucle apprentissage/self-healing) — pas de port, check par process.
if pgrep -f "run.py start" > /dev/null; then
    echo "[supervisor] déjà lancé — rien à faire."
else
    echo "[supervisor] démarrage…"
    nohup python3 run.py start > logs/start.log 2>&1 &
    sleep 2
    pgrep -f "run.py start" > /dev/null && echo "[supervisor] OK (log: logs/start.log)" || { echo "[supervisor] ÉCHEC"; rc=1; }
fi

echo
echo "Téléphone : http://192.168.0.94:8000 (même Wi-Fi, mode miroir, pas de portproxy)."
exit $rc
