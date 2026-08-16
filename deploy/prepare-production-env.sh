#!/usr/bin/env bash
set -euo pipefail

BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ROOT="$(dirname "$BACKEND_ROOT")"
FRONTEND_ROOT="${1:-$DEPLOY_ROOT/typescript-web-nuxt}"
BACKEND_ENV_FILE="$BACKEND_ROOT/.env.production.local"
INITIAL_ADMIN_ENV_FILE="$BACKEND_ROOT/.env.initial-admin.local"
FRONTEND_ENV_FILE="$FRONTEND_ROOT/.env.production.local"
DEPLOY_PUBLIC_IP="47.113.177.140"
POSTGRES_DB="fastapi_web_skeleton"
POSTGRES_USER="fastapi_prod"

for command_name in openssl sha256sum; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command is missing: $command_name" >&2
    exit 1
  fi
done

if [[ ! -d "$FRONTEND_ROOT" ]]; then
  echo "Frontend repository not found: $FRONTEND_ROOT" >&2
  exit 1
fi

for target_file in "$BACKEND_ENV_FILE" "$INITIAL_ADMIN_ENV_FILE" "$FRONTEND_ENV_FILE"; do
  if [[ -e "$target_file" ]]; then
    echo "Refusing to overwrite existing environment file: $target_file" >&2
    exit 1
  fi
done

umask 077
postgres_password="$(openssl rand -hex 24)"
redis_password="$(openssl rand -hex 24)"
jwt_secret="$(openssl rand -hex 48)"
auth_bootstrap_admin_password="$(openssl rand -hex 18)"
rabbitmq_password="$(openssl rand -hex 24)"
initial_admin_password="$(openssl rand -hex 18)"
initial_admin_bootstrap_secret="$(openssl rand -hex 24)"
database_fingerprint_source="postgresql+psycopg://${POSTGRES_USER}@postgres:5432/${POSTGRES_DB}|public"
database_fingerprint="$(printf '%s' "$database_fingerprint_source" | sha256sum | cut -d ' ' -f 1)"

cat > "$BACKEND_ENV_FILE" <<EOF
APP_ENV=production
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$postgres_password
REDIS_PASSWORD=$redis_password
JWT_SECRET=$jwt_secret
AUTH_BOOTSTRAP_ADMIN_PASSWORD=$auth_bootstrap_admin_password
RABBITMQ_DEFAULT_USER=fastapi_prod
RABBITMQ_DEFAULT_PASS=$rabbitmq_password
RABBITMQ_DEFAULT_VHOST=/
RABBITMQ_VHOST_ENCODED=%2F
EDGE_NETWORK_NAME=fastapi-web-production-edge
CADDY_SITE_ADDRESS=http://$DEPLOY_PUBLIC_IP
CADDY_BIND_ADDRESS=0.0.0.0
CADDY_HTTP_PORT=80
CADDY_HTTPS_PORT=443
EOF

cat > "$INITIAL_ADMIN_ENV_FILE" <<EOF
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=$initial_admin_password
INITIAL_ADMIN_CONFIRM=create-initial-admin
INITIAL_ADMIN_ALLOW_PRODUCTION=true
INITIAL_ADMIN_DATABASE_FINGERPRINT=$database_fingerprint
INITIAL_ADMIN_BOOTSTRAP_SECRET=$initial_admin_bootstrap_secret
INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM=$initial_admin_bootstrap_secret
EOF

cat > "$FRONTEND_ENV_FILE" <<EOF
EDGE_NETWORK_NAME=fastapi-web-production-edge
NUXT_API_BASE_URL=http://app:8000
NUXT_PUBLIC_API_BASE_URL=/api
NUXT_PUBLIC_API_TIMEOUT=10000
NUXT_PUBLIC_ADMIN_OPS_ENABLED=false
NUXT_PUBLIC_CODEX_FEATURE_ENABLED=true
NUXT_PUBLIC_CODEX_REALTIME_PATH=/codex/events
NUXT_PUBLIC_CODEX_WS_BASE_URL=
EOF

chmod 600 "$BACKEND_ENV_FILE" "$INITIAL_ADMIN_ENV_FILE" "$FRONTEND_ENV_FILE"

echo "Production environment files created."
echo "Initial administrator username: admin"
echo "Initial administrator password: $initial_admin_password"
echo "Store the password securely, then remove $INITIAL_ADMIN_ENV_FILE after bootstrap."
