#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ROOT="$(dirname "$BACKEND_ROOT")"
FRONTEND_ROOT="${1:-$DEPLOY_ROOT/typescript-web-nuxt}"
BACKEND_ENV_FILE="$BACKEND_ROOT/.env.production.local"
INITIAL_ADMIN_ENV_FILE="$BACKEND_ROOT/.env.initial-admin.local"
FRONTEND_ENV_FILE="$FRONTEND_ROOT/.env.production.local"
EDGE_NETWORK_NAME="fastapi-web-production-edge"
EDGE_NETWORK_SUBNET="172.30.0.0/24"
DEPLOY_PUBLIC_IP="47.113.177.140"

for command_name in docker curl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command is missing: $command_name" >&2
    exit 1
  fi
done

for required_file in "$BACKEND_ENV_FILE" "$INITIAL_ADMIN_ENV_FILE" "$FRONTEND_ENV_FILE"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required environment file is missing: $required_file" >&2
    exit 1
  fi
done

if docker network inspect "$EDGE_NETWORK_NAME" >/dev/null 2>&1; then
  current_subnet="$(docker network inspect --format '{{(index .IPAM.Config 0).Subnet}}' "$EDGE_NETWORK_NAME")"
  if [[ "$current_subnet" != "$EDGE_NETWORK_SUBNET" ]]; then
    echo "Docker network $EDGE_NETWORK_NAME uses $current_subnet; expected $EDGE_NETWORK_SUBNET." >&2
    exit 1
  fi
else
  docker network create \
    --driver bridge \
    --internal \
    --subnet "$EDGE_NETWORK_SUBNET" \
    "$EDGE_NETWORK_NAME"
fi

backend_compose=(
  docker compose
  --project-directory "$BACKEND_ROOT"
  --env-file "$BACKEND_ENV_FILE"
  -f "$BACKEND_ROOT/compose.yml"
  -f "$BACKEND_ROOT/compose.production.yml"
  -f "$BACKEND_ROOT/compose.caddy.yml"
)
frontend_compose=(
  docker compose
  --project-directory "$FRONTEND_ROOT"
  --env-file "$FRONTEND_ENV_FILE"
  -f "$FRONTEND_ROOT/compose.yml"
  -f "$FRONTEND_ROOT/compose.production.yml"
  -f "$FRONTEND_ROOT/compose.caddy.yml"
)
caddy_compose=(
  docker compose
  --project-directory "$BACKEND_ROOT/deploy/caddy"
  --env-file "$BACKEND_ENV_FILE"
  -f "$BACKEND_ROOT/deploy/caddy/compose.yml"
)

"${backend_compose[@]}" config --quiet
"${frontend_compose[@]}" config --quiet
"${caddy_compose[@]}" config --quiet

"${backend_compose[@]}" up -d --build
"${backend_compose[@]}" run \
  --rm \
  --no-deps \
  --env-from-file "$INITIAL_ADMIN_ENV_FILE" \
  app \
  python -m src.cli.create_initial_admin
"${frontend_compose[@]}" up -d --build
"${caddy_compose[@]}" up -d

ready_url="http://127.0.0.1/health/ready"
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error "$ready_url" >/dev/null; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "Production readiness check failed: $ready_url" >&2
    exit 1
  fi
  sleep 2
done

"${backend_compose[@]}" ps
"${frontend_compose[@]}" ps
"${caddy_compose[@]}" ps

echo "Temporary production entry: http://$DEPLOY_PUBLIC_IP"
echo "After recording the admin password, remove: $INITIAL_ADMIN_ENV_FILE"
