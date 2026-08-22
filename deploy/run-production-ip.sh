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
BOOTSTRAP_INITIAL_ADMIN="${PRODUCTION_BOOTSTRAP_ADMIN:-0}"

resolve_production_resource_profile() {
  local configured_profile=""
  if [[ -z "${PRODUCTION_RESOURCE_PROFILE:-}" && -f "$BACKEND_ENV_FILE" ]]; then
    configured_profile="$(awk -F= '$1 == "PRODUCTION_RESOURCE_PROFILE" {print substr($0, index($0, "=") + 1)}' "$BACKEND_ENV_FILE" | tail -n 1)"
  fi
  PRODUCTION_RESOURCE_PROFILE="${PRODUCTION_RESOURCE_PROFILE:-${configured_profile:-standard}}"
  case "$PRODUCTION_RESOURCE_PROFILE" in
    standard|small) ;;
    *)
      echo "PRODUCTION_RESOURCE_PROFILE must be standard or small." >&2
      exit 1
      ;;
  esac
}

resolve_production_resource_profile

for command_name in docker curl awk; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command is missing: $command_name" >&2
    exit 1
  fi
done

for required_file in "$BACKEND_ENV_FILE" "$FRONTEND_ENV_FILE"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required environment file is missing: $required_file" >&2
    exit 1
  fi
done

if [[ "$BOOTSTRAP_INITIAL_ADMIN" == "1" && ! -f "$INITIAL_ADMIN_ENV_FILE" ]]; then
  echo "Initial administrator environment file is missing: $INITIAL_ADMIN_ENV_FILE" >&2
  exit 1
fi

if docker network inspect "$EDGE_NETWORK_NAME" >/dev/null 2>&1; then
  current_subnet="$(docker network inspect --format '{{(index .IPAM.Config 0).Subnet}}' "$EDGE_NETWORK_NAME")"
  current_internal="$(docker network inspect --format '{{.Internal}}' "$EDGE_NETWORK_NAME")"
  if [[ "$current_subnet" != "$EDGE_NETWORK_SUBNET" || "$current_internal" != "true" ]]; then
    echo "Docker network $EDGE_NETWORK_NAME must be internal with subnet $EDGE_NETWORK_SUBNET." >&2
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
  --project-name fastapi-web-production
  --project-directory "$BACKEND_ROOT"
  --env-file "$BACKEND_ENV_FILE"
  -f "$BACKEND_ROOT/compose.yml"
  -f "$BACKEND_ROOT/compose.production.yml"
  -f "$BACKEND_ROOT/compose.caddy.yml"
)
frontend_compose=(
  docker compose
  --project-name typescript-web-production
  --project-directory "$FRONTEND_ROOT"
  --env-file "$FRONTEND_ENV_FILE"
  -f "$FRONTEND_ROOT/compose.yml"
  -f "$FRONTEND_ROOT/compose.production.yml"
  -f "$FRONTEND_ROOT/compose.caddy.yml"
)
caddy_compose=(
  docker compose
  --project-name fastapi-web-production-caddy
  --project-directory "$BACKEND_ROOT/deploy/caddy"
  --env-file "$BACKEND_ENV_FILE"
  -f "$BACKEND_ROOT/deploy/caddy/compose.yml"
)

if [[ "$PRODUCTION_RESOURCE_PROFILE" == "small" ]]; then
  backend_compose+=(-f "$BACKEND_ROOT/compose.production.small.yml")
  frontend_compose+=(-f "$FRONTEND_ROOT/compose.production.small.yml")
  caddy_compose+=(-f "$BACKEND_ROOT/deploy/caddy/compose.small.yml")
fi

"${backend_compose[@]}" config --quiet
"${frontend_compose[@]}" config --quiet
"${caddy_compose[@]}" config --quiet

# 在启动运行时服务前串行构建镜像。小规格主机的构建峰值远高于稳态，
# 先构建可避免 Nuxt 构建与数据库、Worker 同时争用 2 GiB 内存。
COMPOSE_PARALLEL_LIMIT=1 "${backend_compose[@]}" build
COMPOSE_PARALLEL_LIMIT=1 "${frontend_compose[@]}" build

"${backend_compose[@]}" up -d --no-build
if [[ "$BOOTSTRAP_INITIAL_ADMIN" == "1" ]]; then
  "${backend_compose[@]}" run \
    --rm \
    --no-deps \
    --env-from-file "$INITIAL_ADMIN_ENV_FILE" \
    app \
    python -m src.cli.create_initial_admin
fi
"${frontend_compose[@]}" up -d --no-build
"${caddy_compose[@]}" up -d --no-build

site_address="$(awk -F= '$1 == "CADDY_SITE_ADDRESS" {print substr($0, index($0, "=") + 1)}' "$BACKEND_ENV_FILE" | tail -n 1)"
if [[ -z "$site_address" ]]; then
  echo "CADDY_SITE_ADDRESS is missing from $BACKEND_ENV_FILE" >&2
  exit 1
fi
ready_curl_args=()
case "$site_address" in
  http://*|https://*)
    ready_url="${site_address%/}/health/ready"
    ;;
  *)
    ready_url="https://${site_address%/}/health/ready"
    ready_curl_args+=(--resolve "${site_address%/}:443:127.0.0.1")
    ;;
esac
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error "${ready_curl_args[@]}" "$ready_url" >/dev/null; then
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

echo "Production entry is configured by CADDY_SITE_ADDRESS in $BACKEND_ENV_FILE"
if [[ "$BOOTSTRAP_INITIAL_ADMIN" == "1" ]]; then
  echo "After recording the admin password, remove: $INITIAL_ADMIN_ENV_FILE"
fi
