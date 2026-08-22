#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ROOT="$(dirname "$BACKEND_ROOT")"
FRONTEND_ROOT="${PRODUCTION_FRONTEND_ROOT:-$DEPLOY_ROOT/typescript-web-nuxt}"
BACKEND_ENV_FILE="$BACKEND_ROOT/.env.production.local"
INITIAL_ADMIN_ENV_FILE="$BACKEND_ROOT/.env.initial-admin.local"
FRONTEND_ENV_FILE="$FRONTEND_ROOT/.env.production.local"
BACKUP_ROOT="${PRODUCTION_BACKUP_ROOT:-/var/backups/fastapi-web}"
EDGE_NETWORK_NAME="fastapi-web-production-edge"
EDGE_NETWORK_SUBNET="172.30.0.0/24"
READY_URL=""
READY_CURL_ARGS=()
COMMAND="${1:-help}"

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

usage() {
  cat <<'EOF'
Usage: bash deploy/production.sh <command> [argument]

Commands:
  bootstrap          Generate secrets and perform the first deployment with admin creation.
  deploy             Build and deploy the currently checked-out backend and frontend revisions.
  update             Back up PostgreSQL, fast-forward both main branches, then deploy.
  doctor             Validate host tools, repository layout, environment files, and Compose.
  config             Validate all production Compose configurations.
  status             Show Git revisions, containers, disk usage, and readiness.
  logs [group]       Show the last 200 log lines for all, backend, frontend, or caddy.
  follow [group]     Follow logs for all, backend, frontend, or caddy.
  backup [directory] Create a PostgreSQL custom-format dump and checksum.
  stop               Stop the public gateway and all application services without deleting volumes.
  start              Start existing images without rebuilding them.
  help               Show this help.

Environment overrides:
  PRODUCTION_FRONTEND_ROOT  Frontend repository path. Default: sibling typescript-web-nuxt.
  PRODUCTION_BACKUP_ROOT    Backup directory. Default: /var/backups/fastapi-web.
  PRODUCTION_RESOURCE_PROFILE  standard (default) or small. Persisted by bootstrap for later releases.
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command is missing: $1" >&2
    exit 1
  fi
}

require_repositories() {
  if [[ ! -d "$BACKEND_ROOT/.git" ]]; then
    echo "Backend Git repository is missing: $BACKEND_ROOT" >&2
    exit 1
  fi
  if [[ ! -d "$FRONTEND_ROOT/.git" ]]; then
    echo "Frontend Git repository is missing: $FRONTEND_ROOT" >&2
    exit 1
  fi
}

require_runtime_files() {
  for required_file in "$BACKEND_ENV_FILE" "$FRONTEND_ENV_FILE"; do
    if [[ ! -f "$required_file" ]]; then
      echo "Required environment file is missing: $required_file" >&2
      echo "Run: bash deploy/production.sh bootstrap" >&2
      exit 1
    fi
  done
}

ensure_edge_network() {
  if docker network inspect "$EDGE_NETWORK_NAME" >/dev/null 2>&1; then
    local current_subnet
    local current_internal
    current_subnet="$(docker network inspect --format '{{(index .IPAM.Config 0).Subnet}}' "$EDGE_NETWORK_NAME")"
    current_internal="$(docker network inspect --format '{{.Internal}}' "$EDGE_NETWORK_NAME")"
    if [[ "$current_subnet" != "$EDGE_NETWORK_SUBNET" || "$current_internal" != "true" ]]; then
      echo "Docker network $EDGE_NETWORK_NAME must be internal with subnet $EDGE_NETWORK_SUBNET." >&2
      exit 1
    fi
    return
  fi
  docker network create \
    --driver bridge \
    --internal \
    --subnet "$EDGE_NETWORK_SUBNET" \
    "$EDGE_NETWORK_NAME"
}

validate_edge_network() {
  local current_subnet
  local current_internal
  if ! docker network inspect "$EDGE_NETWORK_NAME" >/dev/null 2>&1; then
    echo "Docker network is missing: $EDGE_NETWORK_NAME" >&2
    echo "Run bootstrap or deploy to create it." >&2
    exit 1
  fi
  current_subnet="$(docker network inspect --format '{{(index .IPAM.Config 0).Subnet}}' "$EDGE_NETWORK_NAME")"
  current_internal="$(docker network inspect --format '{{.Internal}}' "$EDGE_NETWORK_NAME")"
  if [[ "$current_subnet" != "$EDGE_NETWORK_SUBNET" || "$current_internal" != "true" ]]; then
    echo "Docker network $EDGE_NETWORK_NAME must be internal with subnet $EDGE_NETWORK_SUBNET." >&2
    exit 1
  fi
}

validate_config() {
  require_repositories
  require_runtime_files
  validate_edge_network
  "${backend_compose[@]}" config --quiet
  "${frontend_compose[@]}" config --quiet
  "${caddy_compose[@]}" config --quiet
}

load_readiness_target() {
  local site_address
  site_address="$(awk -F= '$1 == "CADDY_SITE_ADDRESS" {print substr($0, index($0, "=") + 1)}' "$BACKEND_ENV_FILE" | tail -n 1)"
  if [[ -z "$site_address" ]]; then
    echo "CADDY_SITE_ADDRESS is missing from $BACKEND_ENV_FILE" >&2
    exit 1
  fi
  READY_CURL_ARGS=()
  case "$site_address" in
    http://*|https://*)
      READY_URL="${site_address%/}/health/ready"
      ;;
    *)
      READY_URL="https://${site_address%/}/health/ready"
      READY_CURL_ARGS+=(--resolve "${site_address%/}:443:127.0.0.1")
      ;;
  esac
}

wait_for_readiness() {
  local attempt
  load_readiness_target
  for attempt in $(seq 1 60); do
    if curl --fail --silent --show-error "${READY_CURL_ARGS[@]}" "$READY_URL" >/dev/null; then
      echo "Readiness check passed: $READY_URL"
      return
    fi
    sleep 2
  done
  echo "Production readiness check failed: $READY_URL" >&2
  exit 1
}

deploy_current_revisions() {
  require_repositories
  require_runtime_files
  bash "$BACKEND_ROOT/deploy/run-production-ip.sh" "$FRONTEND_ROOT"
}

bootstrap() {
  require_repositories
  bash "$BACKEND_ROOT/deploy/prepare-production-env.sh" "$FRONTEND_ROOT"
  PRODUCTION_BOOTSTRAP_ADMIN=1 \
    bash "$BACKEND_ROOT/deploy/run-production-ip.sh" "$FRONTEND_ROOT"
}

repository_is_clean() {
  [[ -z "$(git -C "$1" status --porcelain --untracked-files=normal)" ]]
}

require_update_ready_repository() {
  local repository_root="$1"
  local repository_label="$2"
  if ! repository_is_clean "$repository_root"; then
    echo "$repository_label repository has uncommitted or untracked files: $repository_root" >&2
    exit 1
  fi
  if [[ "$(git -C "$repository_root" branch --show-current)" != "main" ]]; then
    echo "$repository_label repository must be on main before update." >&2
    exit 1
  fi
}

postgres_is_running() {
  local container_id
  container_id="$("${backend_compose[@]}" ps -q postgres 2>/dev/null || true)"
  [[ -n "$container_id" ]] && [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" == "true" ]]
}

postgres_container_exists() {
  [[ -n "$("${backend_compose[@]}" ps --all -q postgres 2>/dev/null || true)" ]]
}

create_backup() {
  local requested_root="${1:-$BACKUP_ROOT}"
  local timestamp
  local dump_path
  local temporary_dump_path
  local metadata_path
  require_repositories
  require_runtime_files
  if ! postgres_is_running; then
    echo "PostgreSQL is not running; backup cannot be created." >&2
    exit 1
  fi
  install -d -m 700 "$requested_root"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dump_path="$requested_root/postgres-$timestamp.dump"
  temporary_dump_path="$dump_path.partial"
  metadata_path="$dump_path.metadata"
  umask 077
  if ! "${backend_compose[@]}" exec -T postgres \
    sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$temporary_dump_path"; then
    rm -f "$temporary_dump_path"
    echo "PostgreSQL backup failed." >&2
    exit 1
  fi
  mv "$temporary_dump_path" "$dump_path"
  (
    cd "$requested_root"
    sha256sum "$(basename "$dump_path")" > "$(basename "$dump_path").sha256"
  )
  printf 'created_at_utc=%s\nbackend_commit=%s\nfrontend_commit=%s\n' \
    "$timestamp" \
    "$(git -C "$BACKEND_ROOT" rev-parse HEAD)" \
    "$(git -C "$FRONTEND_ROOT" rev-parse HEAD)" > "$metadata_path"
  chmod 600 "$dump_path" "$dump_path.sha256" "$metadata_path"
  echo "PostgreSQL backup created: $dump_path"
  echo "Checksum: $dump_path.sha256"
  echo "Revision metadata: $metadata_path"
}

update_repositories_and_deploy() {
  local old_backend_revision
  local old_frontend_revision
  require_repositories
  require_runtime_files
  require_update_ready_repository "$BACKEND_ROOT" "Backend"
  require_update_ready_repository "$FRONTEND_ROOT" "Frontend"

  git -C "$BACKEND_ROOT" fetch origin main
  git -C "$FRONTEND_ROOT" fetch origin main
  git -C "$BACKEND_ROOT" merge-base --is-ancestor HEAD origin/main
  git -C "$FRONTEND_ROOT" merge-base --is-ancestor HEAD origin/main

  old_backend_revision="$(git -C "$BACKEND_ROOT" rev-parse HEAD)"
  old_frontend_revision="$(git -C "$FRONTEND_ROOT" rev-parse HEAD)"
  if postgres_is_running; then
    create_backup "$BACKUP_ROOT"
  elif postgres_container_exists; then
    echo "PostgreSQL container exists but is not running; update aborted before changing code." >&2
    exit 1
  else
    echo "No PostgreSQL container exists; update continues without a database backup."
  fi

  git -C "$BACKEND_ROOT" merge --ff-only origin/main
  git -C "$FRONTEND_ROOT" merge --ff-only origin/main
  echo "Previous backend revision: $old_backend_revision"
  echo "Previous frontend revision: $old_frontend_revision"
  deploy_current_revisions
}

show_logs() {
  local group="${1:-all}"
  local follow_flag="${2:-0}"
  local log_args=(logs --tail 200)
  require_runtime_files
  if [[ "$follow_flag" == "1" ]]; then
    if [[ "$group" == "all" ]]; then
      echo "Follow one group at a time: backend, frontend, or caddy." >&2
      exit 1
    fi
    log_args+=(--follow)
  fi
  case "$group" in
    all)
      "${backend_compose[@]}" "${log_args[@]}"
      "${frontend_compose[@]}" "${log_args[@]}"
      "${caddy_compose[@]}" "${log_args[@]}"
      ;;
    backend)
      "${backend_compose[@]}" "${log_args[@]}"
      ;;
    frontend)
      "${frontend_compose[@]}" "${log_args[@]}"
      ;;
    caddy)
      "${caddy_compose[@]}" "${log_args[@]}"
      ;;
    *)
      echo "Unknown log group: $group" >&2
      exit 1
      ;;
  esac
}

show_status() {
  require_repositories
  require_runtime_files
  echo "Backend revision: $(git -C "$BACKEND_ROOT" rev-parse HEAD)"
  echo "Frontend revision: $(git -C "$FRONTEND_ROOT" rev-parse HEAD)"
  "${backend_compose[@]}" ps
  "${frontend_compose[@]}" ps
  "${caddy_compose[@]}" ps
  df -h /
  docker system df
  load_readiness_target
  curl --fail --silent --show-error "${READY_CURL_ARGS[@]}" "$READY_URL"
  echo
}

start_existing_images() {
  require_repositories
  require_runtime_files
  ensure_edge_network
  "${backend_compose[@]}" config --quiet
  "${frontend_compose[@]}" config --quiet
  "${caddy_compose[@]}" config --quiet
  "${backend_compose[@]}" up -d --no-build
  "${frontend_compose[@]}" up -d --no-build
  "${caddy_compose[@]}" up -d --no-build
  wait_for_readiness
}

stop_stack() {
  require_runtime_files
  "${caddy_compose[@]}" stop
  "${frontend_compose[@]}" stop
  "${backend_compose[@]}" stop
  echo "Production containers stopped. Named volumes were preserved."
}

doctor() {
  for command_name in git docker openssl sha256sum curl awk; do
    require_command "$command_name"
  done
  require_repositories
  require_runtime_files
  validate_config
  git -C "$BACKEND_ROOT" status --short --branch
  git -C "$FRONTEND_ROOT" status --short --branch
  docker --version
  docker compose version
  df -h /
  echo "Production deployment prerequisites are valid."
}

case "$COMMAND" in
  bootstrap)
    for command_name in git docker openssl sha256sum curl awk; do
      require_command "$command_name"
    done
    bootstrap
    ;;
  deploy)
    deploy_current_revisions
    ;;
  update)
    update_repositories_and_deploy
    ;;
  doctor)
    doctor
    ;;
  config)
    validate_config
    echo "All production Compose configurations are valid."
    ;;
  status)
    show_status
    ;;
  logs)
    show_logs "${2:-all}" 0
    ;;
  follow)
    show_logs "${2:-all}" 1
    ;;
  backup)
    create_backup "${2:-$BACKUP_ROOT}"
    ;;
  stop)
    stop_stack
    ;;
  start)
    start_existing_images
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $COMMAND" >&2
    usage >&2
    exit 1
    ;;
esac
