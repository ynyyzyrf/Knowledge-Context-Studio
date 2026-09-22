#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f compose.deploy.yaml)
[[ -f deploy/runtime/.env && -f deploy/runtime/postgres.env ]] || {
  echo 'Missing cloud configuration. Follow docs/docker-deployment.md first.' >&2; exit 1;
}
"${compose[@]}" up -d --wait postgres
# Stop application writers before migrations or publisher configuration changes.
"${compose[@]}" stop api worker
"${compose[@]}" run --rm tools alembic upgrade head
if [[ ! -f deploy/runtime/engine.json ]]; then
  "${compose[@]}" run --rm tools python scripts/configure-engine.py
fi
"${compose[@]}" up -d engine
connected=false
for attempt in $(seq 1 30); do
  if "${compose[@]}" run --rm tools python scripts/connect-engine.py; then
    connected=true; break
  fi
  sleep 2
done
[[ "$connected" == true ]] || { echo 'Engine publisher setup failed.' >&2; exit 1; }
"${compose[@]}" run --rm tools python scripts/check-engine.py
# Recreate to read any updated bind-mounted environment file.
"${compose[@]}" up -d --force-recreate --wait api worker
"${compose[@]}" ps
echo 'Platform started. Readiness is not an Agent end-to-end smoke result.'
