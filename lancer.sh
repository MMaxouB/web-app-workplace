#!/usr/bin/env bash
# Démarre l'application et ouvre le navigateur (§4 du cahier des charges).
#
#   ./lancer.sh
#
# Le serveur écoute sur 127.0.0.1 uniquement : le Vault contient des
# données personnelles et l'API n'a pas d'authentification.

set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Création de l'environnement Python…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q fastapi "uvicorn[standard]" pyyaml pytest
fi

PORT="${VAULT_WEB_PORT:-8765}"
URL="http://127.0.0.1:${PORT}"

echo "Vault Web  →  ${URL}"

# Ouvre le navigateur une fois le serveur prêt.
(
  for _ in $(seq 1 40); do
    if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
      command -v xdg-open >/dev/null && xdg-open "${URL}" >/dev/null 2>&1
      break
    fi
    sleep 0.25
  done
) &

exec .venv/bin/python -m uvicorn api.app:app --host 127.0.0.1 --port "${PORT}" "$@"
