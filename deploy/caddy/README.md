# Caddy Docker Gateway

This gateway is the only public container in production. FastAPI, Nuxt,
PostgreSQL, Redis, and RabbitMQ remain on Docker networks without published
ports.

The trusted edge boundary is fixed to `172.30.0.0/24`. It must match
`config/runtime/security_runtime/security_runtime_production.toml` so FastAPI
accepts forwarded client IP and Origin metadata only from the gateway network.
The startup script runs `docker network create` when this external network does
not already exist and rejects an existing network with a different subnet.

## Domain production deployment

The maintained Chinese deployment and operations runbook is
[`docs/生产环境Docker一键部署与长期运维指南.md`](../../docs/生产环境Docker一键部署与长期运维指南.md).

The public entry is `https://nuotop.xyz`. Point the apex DNS A record at
`47.113.177.140`, then clone the two
repositories as siblings on the server:

```bash
install -d -m 755 /opt/web
cd /opt/web
git clone git@github-backend:1nuo123/python-web-fastapi.git
git clone git@github-frontend:1nuo123/typescript-web-nuxt.git
```

Generate untracked production secrets and start the complete stack with the
one-time bootstrap command:

```bash
cd /opt/web/python-web-fastapi
bash deploy/production.sh bootstrap
```

Routine releases use `bash deploy/production.sh update`; it creates a
PostgreSQL backup, fast-forwards both repositories, rebuilds the stack, runs
migrations, and verifies readiness. Run `bash deploy/production.sh help` for
the complete command list.

The environment generator creates three mode-`600` files:

- backend runtime secrets: `.env.production.local`
- one-time administrator bootstrap data: `.env.initial-admin.local`
- frontend runtime configuration: `../typescript-web-nuxt/.env.production.local`

Record the generated `admin` password securely and remove
`.env.initial-admin.local` after the administrator is created.

The generated backend environment uses `CADDY_SITE_ADDRESS=nuotop.xyz` by
default. Once DNS resolves publicly and TCP ports 80 and 443 reach this host,
Caddy obtains and renews the public HTTPS certificate automatically. Production
refresh cookies and the Windows Agent WebSocket connection are HTTPS/WSS only.

The `caddy_data` volume stores certificates and must be backed up. Never use
`docker compose down -v` during routine deployment or rollback.

Final HTTPS acceptance must cover login refresh, WebSocket reconnection, a
mobile network switch, and snapshot recovery.
